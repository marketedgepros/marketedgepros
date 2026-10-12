#!/usr/bin/env python3
"""Import one reviewed, immutable legacy PostgreSQL snapshot without schema restore.

This tool deliberately has no DSN arguments.  It is meant to be invoked locally as
``runuser -u postgres -- .venv/bin/python backend/scripts/import_legacy_snapshot.py``
so PostgreSQL Unix-peer authentication is the only credential path.  It never runs
``pg_restore``, never modifies ``alembic_version``, and defaults to a read-only
planning run.

Apply creates a private ``legacy_import.records`` JSONB archive for every legacy
base-table row except the obsolete Alembic control row.  It then copies only a
reviewed, complete active-table projection in one target transaction.  Credential
and session/token records are archive-only.  Any schema, count, source-digest,
required-value, precision, foreign-key-order, or archive-verification problem
causes a rollback; reports contain only counts, field names, and digests.
"""
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping, Sequence


SOURCE_DATABASE = "marketedgepros_transfer_source_20261013"
TARGET_DATABASE = "marketedgepros_demo_20261012"
PUBLIC_SCHEMA = "public"
ARCHIVE_SCHEMA = "legacy_import"
ARCHIVE_TABLE = "records"
TARGET_HEAD = "20261013_000001"
DIRECT_REVIEW_STATUSES = frozenset({"matched", "same", "changed"})

# These rows can prove a prior session or reset/verification capability.  They are
# retained only in the inaccessible preservation archive, never reactivated.
ARCHIVE_ONLY_SECURITY_TABLES = frozenset(
    {"token_blacklist", "email_verification_tokens", "password_reset_tokens"}
)
IGNORED_CONTROL_TABLES = frozenset({"alembic_version"})

# False is a security-reducing default: it cannot grant authority.  It is allowed
# only because the active target already declares this additive field/default.
SAFE_TARGET_DEFAULTS: dict[str, frozenset[str]] = {
    "users": frozenset({"can_create_same_role"}),
}

IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]*$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class ImportRefusal(RuntimeError):
    """A deliberate, PII-free stop before a legacy snapshot can be applied."""

    def __init__(self, code: str, *, table: str | None = None, field: str | None = None):
        self.code = code
        self.table = table
        self.field = field
        suffix = ".".join(item for item in (table, field) if item)
        super().__init__(code if not suffix else f"{code}:{suffix}")


@dataclass(frozen=True)
class CatalogColumn:
    name: str
    metadata_type: str
    nullable: bool
    display_type: str
    default: str | None
    identity: bool
    generated: bool


@dataclass(frozen=True)
class FieldMap:
    source: str
    target: str
    transform: str = "copy"  # copy | token_version_increment


# These are the reviewed exceptions to direct same-name copying.  They are
# deliberately finite: instant_funding is not transformed into any target field.
EXPLICIT_MAPPINGS: dict[str, tuple[FieldMap, ...]] = {
    "tenants": (
        FieldMap("subdomain", "slug"),
        FieldMap("status", "is_active", "tenant_status_to_is_active"),
    ),
    "trading_programs": (
        FieldMap("type", "program_type"),
        FieldMap("minimum_trading_days", "min_trading_days"),
    ),
    "challenges": (FieldMap("current_phase", "phase"),),
}


@dataclass
class TablePlan:
    name: str
    source_columns: tuple[str, ...]
    target_columns: tuple[CatalogColumn, ...] = ()
    mappings: tuple[FieldMap, ...] = ()
    archive_only_reason: str | None = None
    compatibility_issues: list[str] = field(default_factory=list)
    source_rows: list[str] = field(default_factory=list)
    approved_brand_tenant_id: int | None = None

    @property
    def active(self) -> bool:
        return self.archive_only_reason is None and bool(self.mappings)


@dataclass
class Snapshot:
    tables: dict[str, TablePlan]
    digest: str
    table_fingerprints: dict[str, str]


@dataclass(frozen=True)
class ReviewedMetadata:
    counts: dict[str, dict[str, int]]
    columns: dict[str, dict[str, dict[str, str]]]
    csv_rows: dict[str, tuple[dict[str, str], ...]]
    metadata_digest: str
    csv_digest: str


def _identifier(value: str) -> str:
    if not IDENTIFIER_RE.fullmatch(value):
        raise ImportRefusal("unsafe_identifier")
    return '"' + value + '"'


def _qualified(schema: str, table: str) -> str:
    return f"{_identifier(schema)}.{_identifier(table)}"


def _base_type(display_type: str) -> str:
    """Reduce catalog typmods only for category matching; values are fit-tested."""
    return display_type.split("(", 1)[0].strip().lower()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _fingerprint_rows(table: str, raw_rows: Iterable[str]) -> str:
    """Order-independent deterministic fingerprint without emitting source values."""
    row_hashes = sorted(_sha256_bytes(row.encode("utf-8")) for row in raw_rows)
    payload = (table + "\n" + "\n".join(row_hashes)).encode("ascii")
    return _sha256_bytes(payload)


def _fingerprint_snapshot(table_fingerprints: Mapping[str, str]) -> str:
    payload = "\n".join(f"{name}:{table_fingerprints[name]}" for name in sorted(table_fingerprints))
    return _sha256_bytes(payload.encode("ascii"))


def _decimal_json(value: Any, *, sort_keys: bool = False) -> str:
    """Serialize JSON values exactly enough for Decimal-backed PostgreSQL JSONB."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ImportRefusal("non_finite_json_number")
        rendered = format(value, "f")
        if sort_keys:
            rendered = rendered.rstrip('0').rstrip('.') if '.' in rendered else rendered
            return '0' if value == 0 else rendered
        return rendered
    if isinstance(value, dict):
        items = sorted(value.items()) if sort_keys else value.items()
        return "{" + ",".join(
            json.dumps(str(key), ensure_ascii=False, separators=(",", ":"))
            + ":"
            + _decimal_json(item, sort_keys=sort_keys)
            for key, item in items
        ) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_decimal_json(item, sort_keys=sort_keys) for item in value) + "]"
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _decode_record(raw: str) -> dict[str, Any]:
    value = json.loads(raw, parse_float=Decimal)
    if not isinstance(value, dict):
        raise ImportRefusal("source_row_not_object")
    return value


def _canonical_json_text(raw: str) -> str:
    """Canonical semantic JSON for PII-free fingerprints across JSONB formatting."""
    return _decimal_json(_decode_record(raw), sort_keys=True)


def _read_reviewed_metadata(metadata_path: Path, csv_path: Path) -> ReviewedMetadata:
    try:
        raw_metadata = metadata_path.read_bytes()
        raw_csv = csv_path.read_bytes()
        payload = json.loads(raw_metadata)
    except (OSError, json.JSONDecodeError) as exc:
        raise ImportRefusal("reviewed_metadata_unreadable") from exc

    try:
        sides = payload["old_and_new"]
        counts: dict[str, dict[str, int]] = {}
        columns: dict[str, dict[str, dict[str, str]]] = {}
        for side in ("old", "new"):
            counts[side] = {
                str(row["table"]): int(row["rows"])
                for row in sides[side]["counts"]
            }
            columns[side] = {}
            for row in sides[side]["columns"]:
                table = str(row["table"])
                column = str(row["column"])
                columns[side].setdefault(table, {})[column] = {
                    "type": str(row["type"]),
                    "nullable": str(row["nullable"]),
                }
    except (KeyError, TypeError, ValueError) as exc:
        raise ImportRefusal("reviewed_metadata_shape_invalid") from exc

    csv_rows: dict[str, list[dict[str, str]]] = {}
    try:
        reader = csv.DictReader(raw_csv.decode("utf-8-sig").splitlines())
        required = {"table", "column", "status", "old_type", "new_type", "old_nullable", "new_nullable"}
        if set(reader.fieldnames or ()) != required:
            raise ImportRefusal("reviewed_csv_header_invalid")
        for row in reader:
            if not row or not row["table"] or not row["column"]:
                raise ImportRefusal("reviewed_csv_row_invalid")
            if row["status"] not in DIRECT_REVIEW_STATUSES | {"old_only", "new_only"}:
                raise ImportRefusal("reviewed_csv_status_invalid")
            if any(item["column"] == row["column"] for item in csv_rows.get(row["table"], ())):
                raise ImportRefusal("reviewed_csv_duplicate_field")
            csv_rows.setdefault(row["table"], []).append({key: row[key] or "" for key in required})
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ImportRefusal("reviewed_csv_unreadable") from exc

    for group in (counts["old"], counts["new"], columns["old"], columns["new"]):
        for table in group:
            _identifier(table)
    expected_fields = {(table, name) for side in columns.values() for table, names in side.items() for name in names}
    actual_fields = {(table, row["column"]) for table, rows in csv_rows.items() for row in rows}
    if expected_fields != actual_fields:
        raise ImportRefusal("reviewed_csv_field_inventory_mismatch")
    for table, rows in csv_rows.items():
        for row in rows:
            name = row["column"]
            old = columns["old"].get(table, {}).get(name)
            new = columns["new"].get(table, {}).get(name)
            expected_statuses = DIRECT_REVIEW_STATUSES if old and new else {"old_only"} if old else {"new_only"}
            if row["status"] not in expected_statuses:
                raise ImportRefusal("reviewed_csv_status_identity_mismatch", table=table, field=name)
            for side, spec in (("old", old), ("new", new)):
                if row[side + "_type"] != (spec["type"] if spec else "") or row[side + "_nullable"] != (spec["nullable"] if spec else ""):
                    raise ImportRefusal("reviewed_csv_metadata_mismatch", table=table, field=name)
    return ReviewedMetadata(
        counts=counts,
        columns=columns,
        csv_rows={key: tuple(value) for key, value in csv_rows.items()},
        metadata_digest=_sha256_bytes(raw_metadata),
        csv_digest=_sha256_bytes(raw_csv),
    )


def _connect(database: str, *, read_only: bool):
    """Connect only over the local PostgreSQL Unix socket, using peer identity."""
    if database not in {SOURCE_DATABASE, TARGET_DATABASE}:
        raise ImportRefusal("database_name_not_allowlisted")
    try:
        import psycopg2  # Imported lazily so pure synthetic tests need no driver.
    except ImportError as exc:  # pragma: no cover - deployment dependency guard
        raise ImportRefusal("psycopg2_required") from exc
    options = "-c default_transaction_read_only=on" if read_only else ""
    try:
        connection = psycopg2.connect(
            dbname=database,
            user="postgres",
            host="/var/run/postgresql",
            options=options,
            connect_timeout=5,
        )
        connection.autocommit = False
        with connection.cursor() as cursor:
            if read_only:
                cursor.execute("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY DEFERRABLE")
                cursor.execute("SHOW transaction_read_only")
                if cursor.fetchone()[0].lower() != "on":
                    raise ImportRefusal("source_not_read_only")
            else:
                # Public table locks below are the write exclusion. READ COMMITTED
                # sees writers that committed before those locks were acquired.
                cursor.execute("BEGIN TRANSACTION ISOLATION LEVEL READ COMMITTED READ WRITE")
            cursor.execute("SELECT current_database(), current_user")
            current_database, current_user = cursor.fetchone()
            if current_database != database or current_user != "postgres":
                raise ImportRefusal("peer_identity_mismatch")
        return connection
    except ImportRefusal:
        raise
    except Exception as exc:  # Do not surface libpq host/database details in reports.
        raise ImportRefusal("local_peer_connection_failed") from exc


def _catalog(connection, schema: str = PUBLIC_SCHEMA) -> dict[str, dict[str, CatalogColumn]]:
    """Return ordinary base-table columns and full destination typmods from catalog."""
    query = """
        SELECT c.relname, a.attname,
               format_type(a.atttypid, a.atttypmod),
               a.attnotnull, pg_get_expr(ad.adbin, ad.adrelid),
               a.attidentity <> '', a.attgenerated <> ''
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
          JOIN pg_attribute a ON a.attrelid = c.oid
          LEFT JOIN pg_attrdef ad ON ad.adrelid = c.oid AND ad.adnum = a.attnum
         WHERE n.nspname = %s
           AND c.relkind IN ('r', 'p')
           AND a.attnum > 0 AND NOT a.attisdropped
         ORDER BY c.relname, a.attnum
    """
    catalog: dict[str, dict[str, CatalogColumn]] = {}
    with connection.cursor() as cursor:
        cursor.execute(query, (schema,))
        for table, name, display_type, not_null, default, identity, generated in cursor.fetchall():
            catalog.setdefault(table, {})[name] = CatalogColumn(
                name=name,
                metadata_type=_base_type(display_type),
                nullable=not bool(not_null),
                display_type=display_type,
                default=default,
                identity=bool(identity),
                generated=bool(generated),
            )
    return catalog


def _table_counts(connection, tables: Iterable[str], schema: str = PUBLIC_SCHEMA) -> dict[str, int]:
    result: dict[str, int] = {}
    with connection.cursor() as cursor:
        for table in sorted(tables):
            cursor.execute(f"SELECT count(*) FROM {_qualified(schema, table)}")
            result[table] = int(cursor.fetchone()[0])
    return result


def _lock_target_tables(connection, tables: Iterable[str]) -> None:
    names = sorted(tables)
    if not names or "alembic_version" not in names:
        raise ImportRefusal("target_current_alembic_head_missing")
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL lock_timeout = '5s'")
        cursor.execute("SET LOCAL statement_timeout = '60s'")
        cursor.execute("LOCK TABLE " + ", ".join(_qualified(PUBLIC_SCHEMA, name) for name in names) + " IN ACCESS EXCLUSIVE MODE")


def _validate_catalog(
    catalog: Mapping[str, Mapping[str, CatalogColumn]],
    expected_counts: Mapping[str, int],
    expected_columns: Mapping[str, Mapping[str, Mapping[str, str]]],
    *,
    side: str,
) -> None:
    actual_tables = set(catalog)
    expected_tables = set(expected_counts)
    if actual_tables != expected_tables:
        raise ImportRefusal(f"{side}_base_table_inventory_mismatch")
    for table in sorted(expected_tables):
        actual = catalog[table]
        expected = expected_columns.get(table)
        if expected is None or set(actual) != set(expected):
            raise ImportRefusal(f"{side}_column_inventory_mismatch", table=table)
        for name, expected_column in expected.items():
            actual_column = actual[name]
            if _base_type(expected_column["type"]) != actual_column.metadata_type:
                raise ImportRefusal(f"{side}_metadata_type_mismatch", table=table, field=name)
            expected_nullable = expected_column["nullable"] == "YES"
            if actual_column.nullable != expected_nullable:
                raise ImportRefusal(f"{side}_metadata_nullability_mismatch", table=table, field=name)


def _expected_source_counts(metadata: ReviewedMetadata) -> dict[str, int]:
    return metadata.counts["old"]


def _build_table_plans(
    metadata: ReviewedMetadata,
    source_catalog: Mapping[str, Mapping[str, CatalogColumn]],
    target_catalog: Mapping[str, Mapping[str, CatalogColumn]],
    source_counts: Mapping[str, int],
) -> dict[str, TablePlan]:
    """Build only direct reviewed mappings; never guess a business-state transform."""
    plans: dict[str, TablePlan] = {}
    for table in sorted(source_catalog):
        source_columns = tuple(source_catalog[table])
        plan = TablePlan(name=table, source_columns=source_columns)
        if table in IGNORED_CONTROL_TABLES:
            # Retain the old control record in the private archive as evidence,
            # while never writing it to public.alembic_version or altering heads.
            plan.archive_only_reason = "obsolete_alembic_control_record_archive_only"
            plans[table] = plan
            continue
        if table in ARCHIVE_ONLY_SECURITY_TABLES:
            plan.archive_only_reason = "credential_or_session_record_archive_only"
            plans[table] = plan
            continue
        if table not in target_catalog:
            plan.archive_only_reason = "no_reviewed_active_target_table"
            plans[table] = plan
            continue

        target_columns = tuple(target_catalog[table].values())
        mappings: list[FieldMap] = []
        for row in metadata.csv_rows.get(table, ()):
            source = row["column"]
            if row["status"] not in DIRECT_REVIEW_STATUSES | {"old_only", "new_only"}:
                raise ImportRefusal("reviewed_csv_status_invalid", table=table, field=source)
            if row["old_type"] and row["new_type"] and row["status"] not in DIRECT_REVIEW_STATUSES:
                raise ImportRefusal("reviewed_csv_status_identity_mismatch", table=table, field=source)
            # A same-named pair in the reviewed CSV is evidence of an explicit
            # field identity even if nullability/precision changed and needs fit
            # validation below.  No old_only/new_only field crosses active boundary.
            if (
                row["status"] in DIRECT_REVIEW_STATUSES
                and row["old_type"]
                and row["new_type"]
                and source in source_catalog[table]
                and source in target_catalog[table]
            ):
                mappings.append(FieldMap(source, source))
        for item in EXPLICIT_MAPPINGS.get(table, ()):
            if item.source in source_catalog[table] and item.target in target_catalog[table]:
                mappings.append(item)

        # PostgreSQL may round while casting numeric to integer.  Permit this
        # reviewed direct category change only through a transform that accepts
        # exact integral values and emits an actual Python int.
        normalized_mappings: list[FieldMap] = []
        for item in mappings:
            source_type = _base_type(source_catalog[table][item.source].display_type)
            target_type = _base_type(target_catalog[table][item.target].display_type)
            if item.transform == "copy" and source_type == "numeric" and target_type in {"smallint", "integer", "bigint"}:
                normalized_mappings.append(FieldMap(item.source, item.target, "numeric_to_integer_exact"))
            elif item.transform == "copy" and source_type in {"smallint", "integer", "bigint"} and target_type == "numeric":
                normalized_mappings.append(FieldMap(item.source, item.target, "integer_to_numeric_exact"))
            elif item.transform == "copy" and source_type in {"json", "jsonb"} and target_type in {"json", "jsonb"}:
                normalized_mappings.append(FieldMap(item.source, item.target, "json_semantic_copy"))
            else:
                normalized_mappings.append(item)
        mappings = normalized_mappings

        # Preserve a source password hash exactly; it is included by the direct
        # review mapping.  Token versions deliberately invalidate all old JWTs.
        if (
            table == "users"
            and "token_version" in source_catalog[table]
            and "token_version" in target_catalog[table]
        ):
            mappings = [item for item in mappings if item.target != "token_version"]
            mappings.append(FieldMap("token_version", "token_version", "token_version_increment"))

        # The one target column names in a mapping must be unique.  CSV review
        # ambiguities are a hard stop rather than reliance on arbitrary ordering.
        by_target: dict[str, FieldMap] = {}
        for item in mappings:
            if item.target in by_target and by_target[item.target] != item:
                raise ImportRefusal("reviewed_mapping_ambiguous", table=table, field=item.target)
            by_target[item.target] = item
        plan.target_columns = target_columns
        plan.mappings = tuple(sorted(by_target.values(), key=lambda item: item.target))

        # A record is either complete in the active model or archive-only.  Do
        # not fabricate new phase/program/type/ownership state from defaults.
        mapped_targets = {item.target for item in plan.mappings}
        unavailable_required = [
            column.name
            for column in target_columns
            if not column.nullable
            and not column.identity
            and not column.generated
            and column.name not in mapped_targets
            and column.name not in SAFE_TARGET_DEFAULTS.get(table, frozenset())
        ]
        if source_counts[table] and unavailable_required:
            plan.archive_only_reason = "required_target_field_unmapped:" + ",".join(sorted(unavailable_required))
            plan.mappings = ()
        elif not plan.mappings:
            plan.archive_only_reason = "no_reviewed_active_fields"
        plans[table] = plan
    return plans


def _load_snapshot(source_connection, plans: Mapping[str, TablePlan], expected_counts: Mapping[str, int]) -> Snapshot:
    fingerprints: dict[str, str] = {}
    with source_connection.cursor() as cursor:
        for table in sorted(plans):
            # The table/column names were validated against static metadata before
            # interpolation.  to_jsonb preserves every source column in JSONB.
            cursor.execute(f"SELECT to_jsonb(t)::text FROM {_qualified(PUBLIC_SCHEMA, table)} AS t")
            rows = [str(row[0]) for row in cursor.fetchall()]
            if len(rows) != expected_counts[table]:
                raise ImportRefusal("source_row_count_mismatch", table=table)
            plans[table].source_rows = rows
            fingerprints[table] = _fingerprint_rows(table, rows)
    return Snapshot(tables=dict(plans), digest=_fingerprint_snapshot(fingerprints), table_fingerprints=fingerprints)


def _materialize_row(plan: TablePlan, raw: str) -> dict[str, Any]:
    source = _decode_record(raw)
    result: dict[str, Any] = {}
    for field_map in plan.mappings:
        if field_map.source not in source:
            raise ImportRefusal("source_field_missing", table=plan.name, field=field_map.source)
        value = source[field_map.source]
        if field_map.transform in {"copy", "json_semantic_copy"}:
            result[field_map.target] = value
        elif field_map.transform == "integer_to_numeric_exact":
            if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
                raise ImportRefusal("integer_to_numeric_source_invalid", table=plan.name, field=field_map.source)
            result[field_map.target] = Decimal(value) if value is not None else None
        elif field_map.transform == "token_version_increment":
            if value is None:
                # Explicit reviewed security boundary: NULL (old default) becomes
                # version 1.  The exact legacy value remains in archive JSONB.
                result[field_map.target] = 1
            elif isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                result[field_map.target] = value + 1
            else:
                raise ImportRefusal("invalid_source_token_version", table=plan.name, field=field_map.source)
        elif field_map.transform == "tenant_status_to_is_active":
            # The parent-reviewed legacy vocabulary is intentionally closed.
            # Unknown spelling/state cannot be treated as disabled or enabled.
            if value == "active":
                result[field_map.target] = True
            elif value in {"inactive", "suspended"}:
                result[field_map.target] = False
            else:
                raise ImportRefusal("unknown_tenant_status", table=plan.name, field=field_map.source)
        elif field_map.transform == "numeric_to_integer_exact":
            if value is None:
                result[field_map.target] = None
                continue
            if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
                raise ImportRefusal("numeric_to_integer_source_invalid", table=plan.name, field=field_map.source)
            decimal_value = Decimal(value)
            if decimal_value != decimal_value.to_integral_value():
                raise ImportRefusal("numeric_to_integer_not_exact", table=plan.name, field=field_map.source)
            result[field_map.target] = int(decimal_value)
        else:  # pragma: no cover - protects future mappings
            raise ImportRefusal("unknown_mapping_transform", table=plan.name, field=field_map.target)
    if plan.name == "tenants" and plan.approved_brand_tenant_id is not None and source.get("id") == plan.approved_brand_tenant_id:
        for field_name, field_value in (("name", "MarketEdgePros"), ("slug", "marketedgepros"), ("subdomain", "marketedgepros")):
            if field_name not in result:
                raise ImportRefusal("brand_projection_incomplete", table=plan.name, field=field_name)
            result[field_name] = field_value
    return result


def _active_rows(plan: TablePlan) -> list[dict[str, Any]]:
    return [_materialize_row(plan, raw) for raw in plan.source_rows]


def _collect_compatibility_issues(plans: Mapping[str, TablePlan]) -> None:
    """Record aggregate-only blockers for dry run; do not expose source values."""
    for plan in plans.values():
        if not plan.active or not plan.source_rows:
            continue
        target = {column.name: column for column in plan.target_columns}
        rows = _active_rows(plan)
        for mapping in plan.mappings:
            target_column = target[mapping.target]
            if not target_column.nullable:
                null_count = sum(row[mapping.target] is None for row in rows)
                if null_count:
                    plan.compatibility_issues.append(
                        f"required_target_value_missing:{mapping.target}:count={null_count}"
                    )
            if mapping.transform in {"tenant_status_to_is_active", "numeric_to_integer_exact", "json_semantic_copy", "integer_to_numeric_exact"}:
                continue
            source_display = _SOURCE_DISPLAY_TYPES[plan.name][mapping.source]
            if _base_type(source_display) != _base_type(target_column.display_type):
                plan.compatibility_issues.append(
                    f"mapped_type_category_mismatch:{mapping.target}"
                )
            elif source_display != target_column.display_type:
                plan.compatibility_issues.append(
                    f"target_precision_or_length_validation_required:{mapping.target}"
                )


def _target_foreign_keys(connection, active_tables: set[str]) -> dict[str, set[str]]:
    """Return only active-table dependencies; no constraints are deferred."""
    query = """
        SELECT child.relname, parent.relname
          FROM pg_constraint fk
          JOIN pg_class child ON child.oid = fk.conrelid
          JOIN pg_namespace child_ns ON child_ns.oid = child.relnamespace
          JOIN pg_class parent ON parent.oid = fk.confrelid
          JOIN pg_namespace parent_ns ON parent_ns.oid = parent.relnamespace
         WHERE fk.contype = 'f'
           AND child_ns.nspname = %s AND parent_ns.nspname = %s
    """
    graph = {table: set() for table in active_tables}
    with connection.cursor() as cursor:
        cursor.execute(query, (PUBLIC_SCHEMA, PUBLIC_SCHEMA))
        for child, parent in cursor.fetchall():
            if child in active_tables and parent in active_tables and child != parent:
                graph[child].add(parent)
    return graph


def _topological_order(graph: Mapping[str, set[str]]) -> list[str]:
    remaining = {node: set(edges) for node, edges in graph.items()}
    order: list[str] = []
    while remaining:
        ready = sorted(node for node, edges in remaining.items() if not edges)
        if not ready:
            raise ImportRefusal("non_deferrable_foreign_key_cycle")
        order.extend(ready)
        for node in ready:
            remaining.pop(node)
        for edges in remaining.values():
            edges.difference_update(ready)
    return order


def _validate_target_empty(connection, target_catalog: Mapping[str, Mapping[str, CatalogColumn]]) -> None:
    counts = _table_counts(connection, target_catalog)
    if counts.get("alembic_version", 0) != 1:
        raise ImportRefusal("target_current_alembic_head_missing")
    with connection.cursor() as cursor:
        cursor.execute("SELECT version_num FROM public.alembic_version")
        if [row[0] for row in cursor.fetchall()] != [TARGET_HEAD]:
            raise ImportRefusal("target_current_alembic_head_mismatch")
    populated = [table for table, count in counts.items() if table not in IGNORED_CONTROL_TABLES and count]
    if populated:
        raise ImportRefusal("target_not_empty_except_alembic")
    with connection.cursor() as cursor:
        cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = %s)", (ARCHIVE_SCHEMA,))
        if cursor.fetchone()[0]:
            raise ImportRefusal("legacy_archive_schema_already_exists")


def _validate_runtime_role(connection, runtime_role: str | None) -> None:
    if not runtime_role:
        raise ImportRefusal("runtime_role_required_for_private_archive")
    if not IDENTIFIER_RE.fullmatch(runtime_role) or runtime_role == "postgres":
        raise ImportRefusal("runtime_role_invalid")
    with connection.cursor() as cursor:
        cursor.execute("SELECT rolsuper FROM pg_roles WHERE rolname = %s", (runtime_role,))
        row = cursor.fetchone()
        if row is None or row[0]:
            raise ImportRefusal("runtime_role_missing_or_superuser")
        # Include NOINHERIT memberships: SET ROLE can still reach a superuser
        # role via explicit membership on supported PostgreSQL versions.
        cursor.execute("""
            WITH RECURSIVE reachable(oid) AS (
                SELECT oid FROM pg_roles WHERE rolname = %s
                UNION
                SELECT m.roleid FROM pg_auth_members m JOIN reachable r ON m.member = r.oid
            ) SELECT EXISTS (SELECT 1 FROM reachable r JOIN pg_roles p ON p.oid = r.oid WHERE p.rolsuper)
        """, (runtime_role,))
        if cursor.fetchone()[0]:
            raise ImportRefusal("runtime_role_has_superuser_membership")


def _validate_rows_and_types(connection, plans: Mapping[str, TablePlan]) -> None:
    """Preflight values with target typmods in temporary tables inside apply txn."""
    try:
        from psycopg2.extras import execute_values
    except ImportError as exc:  # pragma: no cover - deployment guard
        raise ImportRefusal("psycopg2_required") from exc

    for plan in plans.values():
        if not plan.active or not plan.source_rows:
            continue
        rows = _active_rows(plan)
        target = {column.name: column for column in plan.target_columns}
        for mapping in plan.mappings:
            # Target non-null must never rely on an accidental database default.
            if not target[mapping.target].nullable and any(row[mapping.target] is None for row in rows):
                raise ImportRefusal("required_target_value_missing", table=plan.name, field=mapping.target)
        for mapping in plan.mappings:
            source_column = mapping.source
            # The source display type is attached dynamically in main validation.
            source_display = _SOURCE_DISPLAY_TYPES[plan.name][source_column]
            target_display = target[mapping.target].display_type
            if mapping.transform in {"tenant_status_to_is_active", "numeric_to_integer_exact"}:
                # _materialize_row already returns an approved bool/int and rejects
                # unapproved source representations before any INSERT is attempted.
                continue
            if mapping.transform == "json_semantic_copy":
                continue
            if _base_type(source_display) != _base_type(target_display) and mapping.transform != "integer_to_numeric_exact":
                raise ImportRefusal("mapped_type_category_mismatch", table=plan.name, field=mapping.target)
            if source_display == target_display:
                continue
            # Same type category with different precision/length: PostgreSQL itself
            # validates every value against the exact target typmod in a temp table.
            temp = "legacy_import_fit_" + _sha256_bytes(f"{plan.name}:{mapping.target}".encode())[:12]
            with connection.cursor() as cursor:
                cursor.execute("SAVEPOINT legacy_import_fit")
                try:
                    cursor.execute(f"CREATE TEMP TABLE {_identifier(temp)} (value {target_display}) ON COMMIT DROP")
                    values = [(row[mapping.target],) for row in rows]
                    execute_values(cursor, f"INSERT INTO {_identifier(temp)} (value) VALUES %s", values, page_size=500)
                    cursor.execute(f"SELECT value FROM {_identifier(temp)}")
                    fitted = [row[0] for row in cursor.fetchall()]
                    original = [row[mapping.target] for row in rows]
                    def value_key(value):
                        return _decimal_json(value, sort_keys=True)
                    if sorted(map(value_key, fitted)) != sorted(map(value_key, original)):
                        raise ImportRefusal("mapped_value_precision_loss", table=plan.name, field=mapping.target)
                except Exception as exc:
                    cursor.execute("ROLLBACK TO SAVEPOINT legacy_import_fit")
                    raise ImportRefusal("mapped_value_precision_mismatch", table=plan.name, field=mapping.target) from exc
                else:
                    cursor.execute("RELEASE SAVEPOINT legacy_import_fit")


def _create_archive(connection, runtime_role: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(f"CREATE SCHEMA {_identifier(ARCHIVE_SCHEMA)} AUTHORIZATION postgres")
        cursor.execute(f"REVOKE ALL ON SCHEMA {_identifier(ARCHIVE_SCHEMA)} FROM PUBLIC")
        cursor.execute(
            f"CREATE TABLE {_qualified(ARCHIVE_SCHEMA, ARCHIVE_TABLE)} ("
            "source_table text NOT NULL, archive_ordinal bigint NOT NULL, "
            "record_digest character(64) NOT NULL, payload jsonb NOT NULL, "
            "PRIMARY KEY (source_table, archive_ordinal))"
        )
        cursor.execute(f"REVOKE ALL ON {_qualified(ARCHIVE_SCHEMA, ARCHIVE_TABLE)} FROM PUBLIC")
        cursor.execute(
            f"ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA {_identifier(ARCHIVE_SCHEMA)} "
            "REVOKE ALL ON TABLES FROM PUBLIC"
        )
    _validate_archive_privileges(connection, runtime_role)


def _validate_archive_privileges(connection, runtime_role: str) -> None:
    _validate_runtime_role(connection, runtime_role)
    with connection.cursor() as cursor:
        cursor.execute("""
            WITH RECURSIVE reachable(oid) AS (
                SELECT oid FROM pg_roles WHERE rolname = %s
                UNION
                SELECT m.roleid FROM pg_auth_members m JOIN reachable r ON m.member = r.oid
            ) SELECT p.rolname FROM reachable r JOIN pg_roles p ON p.oid = r.oid ORDER BY p.rolname
        """, (runtime_role,))
        roles = [row[0] for row in cursor.fetchall()]
        for role in roles:
            for privilege in ("USAGE", "CREATE"):
                cursor.execute("SELECT has_schema_privilege(%s, %s, %s)", (role, ARCHIVE_SCHEMA, privilege))
                if cursor.fetchone()[0]:
                    raise ImportRefusal("runtime_role_has_archive_schema_privilege")
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
                cursor.execute("SELECT has_table_privilege(%s, %s, %s)", (role, f"{ARCHIVE_SCHEMA}.{ARCHIVE_TABLE}", privilege))
                if cursor.fetchone()[0]:
                    raise ImportRefusal("runtime_role_has_archive_table_privilege")
            for privilege in ("SELECT", "INSERT", "UPDATE", "REFERENCES"):
                cursor.execute("SELECT has_any_column_privilege(%s, %s, %s)", (role, f"{ARCHIVE_SCHEMA}.{ARCHIVE_TABLE}", privilege))
                if cursor.fetchone()[0]:
                    raise ImportRefusal("runtime_role_has_archive_column_privilege")


def _archive_rows(connection, snapshot: Snapshot) -> None:
    try:
        from psycopg2.extras import execute_values
    except ImportError as exc:  # pragma: no cover
        raise ImportRefusal("psycopg2_required") from exc
    with connection.cursor() as cursor:
        for table, plan in sorted(snapshot.tables.items()):
            # The ordinal is part of the archive identity so even two byte-for-byte
            # identical source rows are retained separately instead of colliding on
            # their content fingerprint.
            rows = [
                (table, ordinal, _sha256_bytes(raw.encode("utf-8")), raw)
                for ordinal, raw in enumerate(plan.source_rows, start=1)
            ]
            if rows:
                execute_values(
                    cursor,
                    f"INSERT INTO {_qualified(ARCHIVE_SCHEMA, ARCHIVE_TABLE)} "
                    "(source_table, archive_ordinal, record_digest, payload) VALUES %s",
                    rows,
                    template="(%s, %s, %s, %s::jsonb)",
                    page_size=500,
                )


def _insert_active_table(connection, plan: TablePlan) -> None:
    """Use one execute_values statement; self-FKs are intentionally statement-scoped."""
    try:
        from psycopg2.extras import Json, execute_values
    except ImportError as exc:  # pragma: no cover
        raise ImportRefusal("psycopg2_required") from exc
    rows = _active_rows(plan)
    if not rows:
        return
    targets = [mapping.target for mapping in plan.mappings]
    values: list[tuple[Any, ...]] = []
    target_types = {column.name: _base_type(column.display_type) for column in plan.target_columns}
    for row in rows:
        value_row: list[Any] = []
        for target in targets:
            value = row[target]
            if target_types[target] in {"json", "jsonb"} and value is not None:
                value = Json(value, dumps=_decimal_json)
            value_row.append(value)
        values.append(tuple(value_row))
    columns_sql = ", ".join(_identifier(target) for target in targets)
    with connection.cursor() as cursor:
        execute_values(
            cursor,
            f"INSERT INTO {_qualified(PUBLIC_SCHEMA, plan.name)} ({columns_sql}) VALUES %s",
            values,
            page_size=500,
        )


def _advance_sequences(connection, plans: Mapping[str, TablePlan]) -> None:
    with connection.cursor() as cursor:
        for plan in plans.values():
            if not plan.active or "id" not in {item.target for item in plan.mappings}:
                continue
            cursor.execute("SELECT pg_get_serial_sequence(%s, 'id')", (f"{PUBLIC_SCHEMA}.{plan.name}",))
            sequence = cursor.fetchone()[0]
            if not sequence:
                continue
            cursor.execute(f"SELECT max({_identifier('id')}) FROM {_qualified(PUBLIC_SCHEMA, plan.name)}")
            maximum = cursor.fetchone()[0]
            if maximum is not None:
                # ALTER SEQUENCE is transactional; setval is not and would leak
                # sequence state even when a subsequent integrity check rolls back.
                cursor.execute("SELECT n.nspname, c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.oid=%s::regclass AND c.relkind='S'", (sequence,))
                schema_name, sequence_name = cursor.fetchone()
                cursor.execute(f"ALTER SEQUENCE {_qualified(schema_name, sequence_name)} RESTART WITH {int(maximum) + 1}")


def _target_table_fingerprint(connection, plan: TablePlan) -> str:
    fields = [mapping.target for mapping in plan.mappings]
    if not fields:
        return _fingerprint_rows(plan.name, [])
    pieces = ", ".join(_identifier(field) for field in fields)
    # Row projection avoids the 100-argument limit of jsonb_build_object for
    # wide legacy tables. Only reviewed mapped fields enter the fingerprint.
    query = f"SELECT to_jsonb(projected)::text FROM (SELECT {pieces} FROM {_qualified(PUBLIC_SCHEMA, plan.name)}) AS projected"
    with connection.cursor() as cursor:
        cursor.execute(query)
        return _fingerprint_rows(plan.name, (_canonical_json_text(str(row[0])) for row in cursor.fetchall()))


def _planned_table_fingerprint(plan: TablePlan) -> str:
    return _fingerprint_rows(plan.name, (_decimal_json(row, sort_keys=True) for row in _active_rows(plan)))


def _verify_apply(connection, snapshot: Snapshot) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT source_table, record_digest, payload::text FROM {_qualified(ARCHIVE_SCHEMA, ARCHIVE_TABLE)} ORDER BY source_table, archive_ordinal"
        )
        archive_digests: dict[str, list[str]] = {}
        archive_payloads: dict[str, list[str]] = {}
        for table, digest, payload in cursor.fetchall():
            archive_digests.setdefault(table, []).append(str(digest))
            archive_payloads.setdefault(table, []).append(_canonical_json_text(str(payload)))
    if set(archive_digests) - set(snapshot.tables):
        raise ImportRefusal("archive_unexpected_source_table")
    for table, plan in snapshot.tables.items():
        expected = sorted(_sha256_bytes(raw.encode("utf-8")) for raw in plan.source_rows)
        if sorted(archive_digests.get(table, [])) != expected:
            raise ImportRefusal("archive_count_or_fingerprint_mismatch", table=table)
        source_payloads = [_canonical_json_text(raw) for raw in plan.source_rows]
        if _fingerprint_rows(table, archive_payloads.get(table, [])) != _fingerprint_rows(table, source_payloads):
            raise ImportRefusal("archive_payload_fingerprint_mismatch", table=table)
    for table, plan in snapshot.tables.items():
        if not plan.active:
            continue
        with connection.cursor() as cursor:
            cursor.execute(f"SELECT count(*) FROM {_qualified(PUBLIC_SCHEMA, table)}")
            count = int(cursor.fetchone()[0])
        if count != len(plan.source_rows):
            raise ImportRefusal("active_row_count_mismatch", table=table)
        if _target_table_fingerprint(connection, plan) != _planned_table_fingerprint(plan):
            raise ImportRefusal("active_mapped_fingerprint_mismatch", table=table)


def _report(snapshot: Snapshot, metadata: ReviewedMetadata, *, apply: bool, runtime_role: str | None) -> dict[str, Any]:
    tables: dict[str, dict[str, Any]] = {}
    for table, plan in sorted(snapshot.tables.items()):
        tables[table] = {
            "source_rows": len(plan.source_rows),
            "source_fingerprint": snapshot.table_fingerprints[table],
            "archive": True,
            "active_copy": plan.active,
            "archive_only_reason": plan.archive_only_reason,
            "compatibility_issues": sorted(plan.compatibility_issues),
            "mapped_fields": [item.target for item in plan.mappings],
            "unmapped_source_fields": sorted(set(plan.source_columns) - {item.source for item in plan.mappings}),
        }
    return {
        "tool": "legacy_snapshot_import",
        "mode": "apply" if apply else "dry_run",
        "source_database": SOURCE_DATABASE,
        "target_database": TARGET_DATABASE,
        "source_snapshot_digest": snapshot.digest,
        "reviewed_metadata_sha256": metadata.metadata_digest,
        "reviewed_schema_csv_sha256": metadata.csv_digest,
        "runtime_role_checked": runtime_role if apply else None,
        "security": {
            "source_read_only": True,
            "fixed_local_peer_databases": True,
            "old_alembic_not_imported": True,
            "token_and_session_tables_archive_only": sorted(ARCHIVE_ONLY_SECURITY_TABLES),
            "password_hashes_directly_preserved_when_users_are_active": True,
            "user_token_version_rule": "coalesce(legacy_token_version,0)+1; legacy value remains archive-only",
            "no_password_or_owner_or_role_or_tenant_inference": True,
        },
        "functional_parity": "not claimed; archive-only tables and unmapped reviewed fields require a separate approved migration",
        "tables": tables,
    }


# Filled only after the source catalog is validated.  This lets pure tests exercise
# planning without a database driver while still retaining exact catalog typmods.
_SOURCE_DISPLAY_TYPES: dict[str, dict[str, str]] = {}


def _write_report(path: Path | None, payload: Mapping[str, Any]) -> None:
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if path is None:
        print(rendered)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rendered, encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata", type=Path, required=True, help="reviewed database-metadata-comparison.json")
    parser.add_argument("--schema-csv", type=Path, required=True, help="reviewed old-new-schema-columns.csv")
    parser.add_argument("--expected-source-digest", required=True, help="approved SHA-256 snapshot digest")
    parser.add_argument("--expected-metadata-digest", required=True, help="approved SHA-256 reviewed metadata bytes")
    parser.add_argument("--expected-schema-csv-digest", required=True, help="approved SHA-256 reviewed field mapping bytes")
    parser.add_argument("--report", type=Path, help="PII-free JSON result path (stdout if omitted)")
    parser.add_argument("--apply", action="store_true", help="perform the one atomic target transaction; default is dry run")
    parser.add_argument("--runtime-role", help="non-superuser application DB role to prove cannot access legacy_import")
    parser.add_argument("--brand-tenant-id", type=int, help="explicit owner-approved tenant ID to rename only; IDs/roles/FKs remain unchanged")
    return parser


def run(args: argparse.Namespace) -> dict[str, Any]:
    if not DIGEST_RE.fullmatch(args.expected_source_digest):
        raise ImportRefusal("expected_source_digest_invalid")
    if args.runtime_role and not IDENTIFIER_RE.fullmatch(args.runtime_role):
        raise ImportRefusal("runtime_role_invalid")
    if args.apply and not args.runtime_role:
        raise ImportRefusal("runtime_role_required_for_private_archive")

    metadata = _read_reviewed_metadata(args.metadata, args.schema_csv)
    for expected, actual in ((args.expected_metadata_digest, metadata.metadata_digest), (args.expected_schema_csv_digest, metadata.csv_digest)):
        if not DIGEST_RE.fullmatch(expected) or expected != actual:
            raise ImportRefusal("reviewed_metadata_digest_mismatch")
    source = _connect(SOURCE_DATABASE, read_only=True)
    target = None
    try:
        source_catalog = _catalog(source)
        _validate_catalog(source_catalog, metadata.counts["old"], metadata.columns["old"], side="source")
        source_counts = _table_counts(source, source_catalog)
        if source_counts != _expected_source_counts(metadata):
            raise ImportRefusal("source_count_inventory_mismatch")
        target = _connect(TARGET_DATABASE, read_only=False)
        target_catalog = _catalog(target)
        if args.apply:
            _lock_target_tables(target, target_catalog)
            locked_catalog = _catalog(target)
            if locked_catalog != target_catalog:
                raise ImportRefusal("target_catalog_changed_during_lock")
            target_catalog = locked_catalog
        _validate_catalog(target_catalog, metadata.counts["new"], metadata.columns["new"], side="target")
        _validate_target_empty(target, target_catalog)
        plans = _build_table_plans(metadata, source_catalog, target_catalog, source_counts)
        global _SOURCE_DISPLAY_TYPES
        _SOURCE_DISPLAY_TYPES = {
            table: {name: column.display_type for name, column in columns.items()}
            for table, columns in source_catalog.items()
        }
        snapshot = _load_snapshot(source, plans, metadata.counts["old"])
        if snapshot.digest != args.expected_source_digest:
            raise ImportRefusal("source_snapshot_digest_mismatch")
        brand_id = getattr(args, "brand_tenant_id", None)
        if brand_id is not None:
            if isinstance(brand_id, bool) or not isinstance(brand_id, int) or not 0 < brand_id <= 2147483647:
                raise ImportRefusal("approved_brand_tenant_id_invalid")
            tenant_plan = plans.get("tenants")
            if tenant_plan is None or not tenant_plan.active or sum(_decode_record(raw).get("id") == brand_id for raw in tenant_plan.source_rows) != 1:
                raise ImportRefusal("approved_brand_tenant_missing_or_not_unique")
            tenant_plan.approved_brand_tenant_id = brand_id
        _collect_compatibility_issues(plans)
        report = _report(snapshot, metadata, apply=args.apply, runtime_role=args.runtime_role)
        report["approved_brand_rename"] = {"tenant_id": brand_id, "name": "MarketEdgePros", "ownership_changed": False} if brand_id is not None else None
        if not args.apply:
            target.rollback()  # Explicitly leave even the read-only planning target unchanged.
            return report

        _validate_runtime_role(target, args.runtime_role)
        _validate_rows_and_types(target, plans)
        _create_archive(target, args.runtime_role)
        _archive_rows(target, snapshot)
        active = {name for name, plan in plans.items() if plan.active and plan.source_rows}
        order = _topological_order(_target_foreign_keys(target, active))
        for table in order:
            _insert_active_table(target, plans[table])
        _advance_sequences(target, plans)
        _verify_apply(target, snapshot)
        _validate_archive_privileges(target, args.runtime_role)
        target.commit()
        report["apply_verification"] = "committed_after_archive_and_active_count_fingerprint_checks"
        return report
    except Exception:
        if target is not None:
            target.rollback()
        raise
    finally:
        try:
            source.rollback()
        finally:
            source.close()
        if target is not None:
            target.close()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = run(args)
    except ImportRefusal as exc:
        # Intentionally omit database-driver text, SQL, values, and PII.
        _write_report(args.report, {"tool": "legacy_snapshot_import", "status": "refused", "code": exc.code, "table": exc.table, "field": exc.field})
        return 2
    except Exception:
        _write_report(args.report, {"tool": "legacy_snapshot_import", "status": "refused", "code": "unexpected_internal_failure"})
        return 2
    _write_report(args.report, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
