"""Runner-private PostgreSQL rehearsal for the reviewed legacy snapshot importer.

The test imports the command module by file path and maps its two fixed symbolic
names to two newly-created runner-private databases.  It does not loosen the
command's production peer-only connector: that connector is replaced only inside
this test process so the real planner/apply logic can exercise isolated socket
connections under the staging runner.
"""
from __future__ import annotations

import csv
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import threading
from types import SimpleNamespace
from uuid import uuid4

from alembic import command
from alembic.config import Config
import psycopg2
from psycopg2 import extras
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


BACKEND = Path(__file__).resolve().parents[1]
IMPORTER_PATH = BACKEND / "scripts" / "import_legacy_snapshot.py"
SNAPSHOT_PROTOCOL_BASELINE = "20261013_000001"
DATABASE_RE = re.compile(r"marketedgepros_test_[0-9a-f]{32}\Z")
ROLE_RE = re.compile(r"legacy_runtime_[0-9a-f]{16}\Z")
@dataclass(frozen=True)
class SnapshotDatabases:
    source_name: str
    target_name: str
    source_url: str
    target_url: str
    runtime_user: str
    socket_dir: str
    port: str
    runtime_role: str


def _quoted_identifier(name: str) -> str:
    """Quote only test-generated PostgreSQL identifiers."""
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", name):
        raise AssertionError(f"unsafe synthetic identifier: {name!r}")
    return f'"{name}"'


def _database_name() -> str:
    name = "marketedgepros_test_" + uuid4().hex
    assert DATABASE_RE.fullmatch(name)
    return name


def _database_url(resources: dict[str, object], name: str) -> str:
    return make_url(str(resources["pg_url"])).set(database=name).render_as_string(hide_password=False)


def _alembic_config(url: str) -> Config:
    config = Config(str(BACKEND / "migrations" / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    # ConfigParser interpolation requires escaped percent signs in Unix-socket URLs.
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def _upgrade_to_snapshot_protocol_baseline(engine, url: str) -> None:
    """Upgrade only to the frozen importer protocol baseline over a caller-owned connection."""
    config = _alembic_config(url)
    try:
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, SNAPSHOT_PROTOCOL_BASELINE)
            connection.commit()
    finally:
        config.attributes.pop("connection", None)


@contextmanager
def _isolated_snapshot_databases(staging_resources):
    """Create and tear down source/target DBs and every role this test creates."""
    source_name = _database_name()
    target_name = _database_name()
    assert source_name != target_name != staging_resources["db_name"]
    source_url = _database_url(staging_resources, source_name)
    target_url = _database_url(staging_resources, target_name)
    primary_url = make_url(str(staging_resources["pg_url"]))
    admin_engine = create_engine(primary_url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    source_engine = None
    target_engine = None
    runtime_role = "legacy_runtime_" + uuid4().hex[:16]
    assert ROLE_RE.fullmatch(runtime_role)
    created_archive_owner = False
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f"CREATE DATABASE {_quoted_identifier(source_name)}"))
            connection.execute(text(f"CREATE DATABASE {_quoted_identifier(target_name)}"))
            # The importer owns the archive as postgres in production.  The runner
            # bootstrap superuser is intentionally the unprivileged OS runtime user,
            # so create this private-cluster-only owner if the cluster lacks it.
            exists = connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname = 'postgres'")).scalar()
            if not exists:
                connection.execute(text("CREATE ROLE postgres LOGIN SUPERUSER"))
                created_archive_owner = True
            connection.execute(text(
                f"CREATE ROLE {_quoted_identifier(runtime_role)} LOGIN NOSUPERUSER NOINHERIT"
            ))
        source_engine = create_engine(source_url)
        target_engine = create_engine(target_url)
        # The snapshot protocol is intentionally frozen at 000001. Source then
        # adds only a synthetic snapshot-only table; target remains public-empty.
        _upgrade_to_snapshot_protocol_baseline(source_engine, source_url)
        _upgrade_to_snapshot_protocol_baseline(target_engine, target_url)
        url = make_url(str(staging_resources["pg_url"]))
        yield SnapshotDatabases(
            source_name=source_name,
            target_name=target_name,
            source_url=source_url,
            target_url=target_url,
            runtime_user=str(url.username),
            socket_dir=str(dict(url.query)["host"]),
            port=str(dict(url.query)["port"]),
            runtime_role=runtime_role,
        )
    finally:
        if source_engine is not None:
            source_engine.dispose()
        if target_engine is not None:
            target_engine.dispose()
        with admin_engine.connect() as connection:
            # FORCE also cleans up connections from a test that deliberately fails
            # part way through the importer transaction.
            for name in (source_name, target_name):
                connection.execute(text(f"DROP DATABASE IF EXISTS {_quoted_identifier(name)} WITH (FORCE)"))
            connection.execute(text(f"DROP ROLE IF EXISTS {_quoted_identifier(runtime_role)}"))
            if created_archive_owner:
                connection.execute(text("DROP ROLE IF EXISTS postgres"))
        admin_engine.dispose()


def _driver_connection(databases: SnapshotDatabases, database: str, *, read_only: bool, user: str | None = None):
    """Open only a private Unix-socket psycopg2 connection for the importer shim."""
    assert database in {databases.source_name, databases.target_name}
    connection = psycopg2.connect(
        dbname=database,
        user=user or databases.runtime_user,
        host=databases.socket_dir,
        port=databases.port,
        options="-c default_transaction_read_only=on" if read_only else "",
        connect_timeout=5,
    )
    connection.autocommit = False
    with connection.cursor() as cursor:
        if read_only:
            cursor.execute("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY DEFERRABLE")
            cursor.execute("SHOW transaction_read_only")
            assert cursor.fetchone()[0].lower() == "on"
        else:
            cursor.execute("BEGIN TRANSACTION ISOLATION LEVEL SERIALIZABLE READ WRITE")
    return connection


def _admin_connection(databases: SnapshotDatabases, database: str):
    connection = psycopg2.connect(
        dbname=database,
        user=databases.runtime_user,
        host=databases.socket_dir,
        port=databases.port,
        connect_timeout=5,
    )
    connection.autocommit = False
    return connection


def _load_importer_module():
    """Load exactly the script under review without application import side effects."""
    module_name = "legacy_snapshot_import_staging_" + uuid4().hex
    specification = importlib.util.spec_from_file_location(module_name, IMPORTER_PATH)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    sys.modules[module_name] = module
    try:
        specification.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    return module_name, module


def _unload_importer_module(module_name: str) -> None:
    sys.modules.pop(module_name, None)


def _public_columns(connection, table: str) -> list[dict[str, str]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name, data_type, is_nullable, column_default, is_identity
              FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = %s
             ORDER BY ordinal_position
            """,
            (table,),
        )
        return [
            {
                "name": str(name), "type": str(data_type), "nullable": str(nullable),
                "default": "" if default is None else str(default), "identity": str(identity),
            }
            for name, data_type, nullable, default, identity in cursor.fetchall()
        ]


def _insert_row(connection, table: str, assigned: dict[str, object]) -> None:
    """Fill every required current-head column with deterministic synthetic values."""
    values = dict(assigned)
    for column in _public_columns(connection, table):
        name = column["name"]
        if name in values or column["nullable"] == "YES" or column["default"] or column["identity"] == "YES":
            continue
        values[name] = _required_synthetic_value(table, name, column["type"])
    assert values, table
    names = list(values)
    columns_sql = ", ".join(_quoted_identifier(name) for name in names)
    placeholders = ", ".join(["%s"] * len(names))
    with connection.cursor() as cursor:
        cursor.execute(
            f"INSERT INTO public.{_quoted_identifier(table)} ({columns_sql}) VALUES ({placeholders})",
            tuple(values[name] for name in names),
        )


def _required_synthetic_value(table: str, column: str, data_type: str):
    """Use harmless values suitable for non-null source-only rehearsal rows."""
    by_name: dict[str, object] = {
        "id": 1,
        "tenant_id": 1,
        "user_id": 1,
        "program_id": 1,
        "name": f"synthetic-{table}",
        "email": "legacy-import-synthetic@example.invalid",
        "password_hash": "not-a-login-credential",
        "first_name": "Synthetic",
        "last_name": "Snapshot",
        "slug": "legacy-import-synthetic",
        "subdomain": "legacy-import-synthetic",
        "status": "active",
        "tier": "basic",
        "role": "user",
        "program_type": "one_phase",
        "type": "one_phase",
        "token_type": "access",
        "jti": "synthetic-revoked-token",
        "tree_path": "1",
    }
    if column in by_name:
        return by_name[column]
    if data_type in {"character varying", "text", "character"}:
        return f"synthetic-{table}-{column}"
    if data_type in {"integer", "smallint", "bigint"}:
        return 1
    if data_type in {"numeric", "decimal", "double precision", "real"}:
        return Decimal("1.00")
    if data_type == "boolean":
        return True
    if data_type == "date":
        return datetime(2040, 1, 1, tzinfo=timezone.utc).date()
    if data_type.startswith("timestamp"):
        return datetime(2040, 1, 1, tzinfo=timezone.utc)
    if data_type in {"json", "jsonb"}:
        return extras.Json({})
    if data_type == "uuid":
        return "00000000-0000-0000-0000-000000000001"
    raise AssertionError(f"unhandled required source column {table}.{column}:{data_type}")


def _seed_source(databases: SnapshotDatabases) -> None:
    """Seed only ordinary synthetic rows that exercise copy and archive boundaries."""
    connection = _admin_connection(databases, databases.source_name)
    try:
        _insert_row(connection, "tenants", {
            "id": 1, "name": "Synthetic Legacy Tenant", "slug": "legacy-import-synthetic",
            "subdomain": "legacy-import-synthetic", "status": "active", "tier": "basic",
            "is_active": True,
        })
        _insert_row(connection, "users", {
            "id": 1, "email": "legacy-import-synthetic@example.invalid",
            "password_hash": "not-a-login-credential", "first_name": "Synthetic", "last_name": "Snapshot",
            "tenant_id": 1, "role": "user", "is_active": True, "is_verified": True,
            "token_version": 7, "tree_path": "1",
        })
        program_values: dict[str, object] = {
            "id": 1, "tenant_id": 1, "name": "Synthetic Legacy Program",
            "type": "one_phase", "program_type": "one_phase", "account_size": Decimal("10000.00"),
            "price": Decimal("20.12"), "profit_split": 80, "is_active": True,
        }
        program_columns = {item["name"]: item for item in _public_columns(connection, "trading_programs")}
        for risk_column in ("profit_target", "max_daily_loss", "max_total_loss"):
            if risk_column in program_columns:
                assert program_columns[risk_column]["nullable"] == "YES", risk_column
                program_values[risk_column] = None
        _insert_row(connection, "trading_programs", program_values)
        # A revoked/token record must never become an active public record; its
        # source user is deliberately real only inside this private runner DB.
        _insert_row(connection, "token_blacklist", {
            "id": 1, "user_id": 1, "jti": "synthetic-revoked-token", "token_type": "access",
            "revoked_at": datetime(2040, 1, 1, tzinfo=timezone.utc),
            "expires_at": datetime(2040, 1, 2, tzinfo=timezone.utc),
        })
        # No primary key: the two identical source JSON rows prove archive ordinal
        # preserves duplicates even when their content digest is identical.
        with connection.cursor() as cursor:
            cursor.execute("CREATE TABLE public.customlegacy (legacy_marker text NOT NULL)")
            cursor.execute(
                "INSERT INTO public.customlegacy (legacy_marker) VALUES (%s), (%s)",
                ("synthetic-duplicate-archive-row", "synthetic-duplicate-archive-row"),
            )
            # The source begins at current migration heads solely so Alembic can
            # build it privately.  Remove target-only renamed fields afterwards to
            # model the reviewed legacy shape: the finite importer mappings must
            # provide slug/is_active, program_type/min_trading_days, and phase.
            # Keeping both names in one source schema would instead request two
            # independent source fields for the same active target column.
            cursor.execute("ALTER TABLE public.tenants DROP COLUMN slug, DROP COLUMN is_active")
            cursor.execute(
                "ALTER TABLE public.trading_programs DROP COLUMN program_type, DROP COLUMN min_trading_days"
            )
            cursor.execute("ALTER TABLE public.challenges DROP COLUMN phase")
        connection.commit()
    finally:
        connection.close()


def _catalog_and_counts(connection) -> tuple[dict[str, dict[str, dict[str, str]]], dict[str, int]]:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT table_name, column_name, data_type, is_nullable
              FROM information_schema.columns
             WHERE table_schema = 'public'
             ORDER BY table_name, ordinal_position
            """
        )
        columns: dict[str, dict[str, dict[str, str]]] = {}
        for table, column, data_type, nullable in cursor.fetchall():
            columns.setdefault(str(table), {})[str(column)] = {
                "type": str(data_type), "nullable": str(nullable),
            }
    counts: dict[str, int] = {}
    with connection.cursor() as cursor:
        for table in sorted(columns):
            cursor.execute(f"SELECT count(*) FROM public.{_quoted_identifier(table)}")
            counts[table] = int(cursor.fetchone()[0])
    return columns, counts


def _write_reviewed_metadata(databases: SnapshotDatabases, directory: Path) -> tuple[Path, Path, dict[str, int]]:
    """Build a PII-free reviewed inventory from information_schema and row counts."""
    source = _admin_connection(databases, databases.source_name)
    target = _admin_connection(databases, databases.target_name)
    try:
        old_columns, old_counts = _catalog_and_counts(source)
        new_columns, new_counts = _catalog_and_counts(target)
    finally:
        source.close()
        target.close()
    payload = {
        "old_and_new": {
            "old": {
                "counts": [{"table": table, "rows": old_counts[table]} for table in sorted(old_counts)],
                "columns": [
                    {"table": table, "column": column, **old_columns[table][column]}
                    for table in sorted(old_columns) for column in sorted(old_columns[table])
                ],
            },
            "new": {
                "counts": [{"table": table, "rows": new_counts[table]} for table in sorted(new_counts)],
                "columns": [
                    {"table": table, "column": column, **new_columns[table][column]}
                    for table in sorted(new_columns) for column in sorted(new_columns[table])
                ],
            },
        },
    }
    metadata_path = directory / "reviewed-database-metadata-comparison.json"
    csv_path = directory / "reviewed-old-new-schema-columns.csv"
    metadata_path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        fields = ("table", "column", "status", "old_type", "new_type", "old_nullable", "new_nullable")
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for table in sorted(set(old_columns) | set(new_columns)):
            for column in sorted(set(old_columns.get(table, {})) | set(new_columns.get(table, {}))):
                old = old_columns.get(table, {}).get(column, {})
                new = new_columns.get(table, {}).get(column, {})
                writer.writerow({
                    "table": table,
                    "column": column,
                    # Direct same-name fields use only the closed approved status
                    # vocabulary.  Separately encoded finite importer mappings may
                    # map a source field to a different target field in addition.
                    "status": "matched" if old and new else ("old_only" if old else "new_only"),
                    "old_type": old.get("type", ""),
                    "new_type": new.get("type", ""),
                    "old_nullable": old.get("nullable", ""), "new_nullable": new.get("nullable", ""),
                })
    return metadata_path, csv_path, old_counts


def _snapshot_for_expected_digest(module, databases: SnapshotDatabases, metadata_path: Path, csv_path: Path):
    """Compute the approved digest using the importer's own current canonicalization."""
    metadata = module._read_reviewed_metadata(metadata_path, csv_path)
    source = _driver_connection(databases, databases.source_name, read_only=True)
    target = _driver_connection(databases, databases.target_name, read_only=False)
    try:
        source_catalog = module._catalog(source)
        target_catalog = module._catalog(target)
        module._validate_catalog(source_catalog, metadata.counts["old"], metadata.columns["old"], side="source")
        module._validate_catalog(target_catalog, metadata.counts["new"], metadata.columns["new"], side="target")
        source_counts = module._table_counts(source, source_catalog)
        plans = module._build_table_plans(metadata, source_catalog, target_catalog, source_counts)
        module._SOURCE_DISPLAY_TYPES = {
            table: {name: column.display_type for name, column in columns.items()}
            for table, columns in source_catalog.items()
        }
        snapshot = module._load_snapshot(source, plans, metadata.counts["old"])
        return metadata, snapshot
    finally:
        target.rollback()
        target.close()
        source.rollback()
        source.close()


def _patch_private_connections(monkeypatch, module, databases: SnapshotDatabases):
    """Map only the module's fixed symbolic names to these test-private databases."""
    opened: list[tuple[str, bool]] = []

    def mapped_connect(symbolic_name: str, *, read_only: bool):
        expected = {
            module.SOURCE_DATABASE: (databases.source_name, True),
            module.TARGET_DATABASE: (databases.target_name, False),
        }
        assert symbolic_name in expected
        actual_name, expected_read_only = expected[symbolic_name]
        assert read_only is expected_read_only
        opened.append((symbolic_name, read_only))
        return _driver_connection(databases, actual_name, read_only=read_only)

    monkeypatch.setattr(module, "_connect", mapped_connect)
    return opened


def _run_args(databases: SnapshotDatabases, metadata_path: Path, csv_path: Path, digest: str) -> SimpleNamespace:
    return SimpleNamespace(
        metadata=metadata_path,
        schema_csv=csv_path,
        expected_source_digest=digest,
        expected_metadata_digest=hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
        expected_schema_csv_digest=hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        report=None,
        apply=True,
        runtime_role=databases.runtime_role,
    )


def _target_counts(databases: SnapshotDatabases, tables: list[str]) -> dict[str, int]:
    connection = _admin_connection(databases, databases.target_name)
    try:
        return {table: count for table, count in _catalog_and_counts(connection)[1].items() if table in tables}
    finally:
        connection.close()


def _sequence_canary(databases: SnapshotDatabases, tables: set[str]) -> dict[str, tuple[object, bool]]:
    """Read actual serial-sequence state without advancing it."""
    connection = _admin_connection(databases, databases.target_name)
    try:
        result: dict[str, tuple[object, bool]] = {}
        with connection.cursor() as cursor:
            for table in sorted(tables):
                cursor.execute("SELECT pg_get_serial_sequence(%s, 'id')", (f"public.{table}",))
                sequence = cursor.fetchone()[0]
                if sequence is None:
                    continue
                schema, name = str(sequence).split(".", 1)
                assert schema == "public"
                cursor.execute(
                    f"SELECT last_value, is_called FROM {_quoted_identifier(schema)}.{_quoted_identifier(name)}"
                )
                last_value, is_called = cursor.fetchone()
                result[table] = (last_value, bool(is_called))
        connection.rollback()
        return result
    finally:
        connection.close()


def _assert_rolled_back_target(databases: SnapshotDatabases, active_tables: set[str]) -> None:
    connection = _admin_connection(databases, databases.target_name)
    try:
        counts = _catalog_and_counts(connection)[1]
        assert all(counts[table] == 0 for table in active_tables)
        with connection.cursor() as cursor:
            cursor.execute("SELECT to_regclass('legacy_import.records')")
            assert cursor.fetchone()[0] is None
    finally:
        connection.close()


def _empty_table_insert_statement(connection, table: str) -> tuple[str, tuple[object, ...]]:
    """Prepare a valid synthetic INSERT before the test transaction locks the table."""
    values: dict[str, object] = {}
    for column in _public_columns(connection, table):
        if column["nullable"] == "YES" or column["default"] or column["identity"] == "YES":
            continue
        values[column["name"]] = _required_synthetic_value(table, column["name"], column["type"])
    assert values, table
    columns = ", ".join(_quoted_identifier(name) for name in values)
    placeholders = ", ".join("%s" for _ in values)
    return f"INSERT INTO public.{_quoted_identifier(table)} ({columns}) VALUES ({placeholders})", tuple(values.values())


def test_legacy_snapshot_apply_isolated_postgresql_preserves_archive_and_active_boundaries(
    staging_resources, monkeypatch, tmp_path,
):
    """Run a complete committed import against two fresh real PostgreSQL databases."""
    with _isolated_snapshot_databases(staging_resources) as databases:
        _seed_source(databases)
        metadata_path, csv_path, expected_counts = _write_reviewed_metadata(databases, tmp_path)
        module_name, module = _load_importer_module()
        try:
            metadata, expected_snapshot = _snapshot_for_expected_digest(module, databases, metadata_path, csv_path)
            assert expected_counts["customlegacy"] == 2
            assert expected_snapshot.tables["customlegacy"].archive_only_reason == "no_reviewed_active_target_table"
            assert expected_snapshot.tables["token_blacklist"].archive_only_reason == "credential_or_session_record_archive_only"
            assert {"tenants", "users", "trading_programs"}.issubset(
                {name for name, plan in expected_snapshot.tables.items() if plan.active and plan.source_rows}
            )
            opened = _patch_private_connections(monkeypatch, module, databases)
            args = _run_args(databases, metadata_path, csv_path, expected_snapshot.digest)
            args.brand_tenant_id = 1
            result = module.run(args)
            assert result["apply_verification"] == "committed_after_archive_and_active_count_fingerprint_checks"
            assert result["source_snapshot_digest"] == expected_snapshot.digest
            assert opened == [(module.SOURCE_DATABASE, True), (module.TARGET_DATABASE, False)]

            # The source remains byte-for-byte canonical-fingerprint equivalent after
            # apply, and every source table row (including Alembic evidence) has one
            # archive row.  Duplicate customlegacy payloads survive independently.
            _, after_snapshot = _snapshot_for_expected_digest(module, databases, metadata_path, csv_path)
            assert after_snapshot.digest == expected_snapshot.digest
            assert after_snapshot.table_fingerprints == expected_snapshot.table_fingerprints
            target = _admin_connection(databases, databases.target_name)
            try:
                with target.cursor() as cursor:
                    cursor.execute(
                        "SELECT source_table, count(*) FROM legacy_import.records GROUP BY source_table"
                    )
                    archive_counts = {str(table): int(count) for table, count in cursor.fetchall()}
                    assert not (set(archive_counts) - set(expected_counts))
                    assert {table: archive_counts.get(table, 0) for table in expected_counts} == expected_counts
                    cursor.execute("SELECT count(*), count(DISTINCT record_digest) FROM legacy_import.records WHERE source_table = 'customlegacy'")
                    assert tuple(cursor.fetchone()) == (2, 1)
                    cursor.execute("SELECT token_version FROM public.users WHERE id = 1")
                    assert cursor.fetchone()[0] == 8
                    cursor.execute("SELECT id, name, slug, subdomain FROM public.tenants WHERE id = 1")
                    assert tuple(cursor.fetchone()) == (1, "MarketEdgePros", "marketedgepros", "marketedgepros")
                    cursor.execute("SELECT tenant_id, role FROM public.users WHERE id = 1")
                    assert tuple(cursor.fetchone()) == (1, "user")
                    cursor.execute(
                        "SELECT profit_target, max_daily_loss, max_total_loss FROM public.trading_programs WHERE id = 1"
                    )
                    assert tuple(cursor.fetchone()) == (None, None, None)
                    cursor.execute("SELECT count(*) FROM public.token_blacklist")
                    assert cursor.fetchone()[0] == 0
                    cursor.execute("SELECT has_schema_privilege(%s, 'legacy_import', 'USAGE')", (databases.runtime_role,))
                    assert cursor.fetchone()[0] is False
                    cursor.execute("SELECT has_table_privilege(%s, 'legacy_import.records', 'SELECT')", (databases.runtime_role,))
                    assert cursor.fetchone()[0] is False
                target.commit()
            finally:
                target.close()

            # Privilege catalog checks are reinforced with a real non-superuser
            # socket connection: neither schema usage nor direct archive SELECT works.
            runtime = _driver_connection(databases, databases.target_name, read_only=True, user=databases.runtime_role)
            try:
                with runtime.cursor() as cursor:
                    with pytest.raises(psycopg2.Error):
                        cursor.execute("SELECT count(*) FROM legacy_import.records")
                runtime.rollback()
            finally:
                runtime.close()

            active_nonempty = {
                table for table, plan in expected_snapshot.tables.items()
                if plan.active and expected_counts[table]
            }
            target_counts = _target_counts(databases, sorted(active_nonempty))
            assert target_counts == {table: expected_counts[table] for table in active_nonempty}
            assert metadata.counts["old"] == expected_counts
        finally:
            _unload_importer_module(module_name)


def test_legacy_snapshot_precision_loss_refuses_before_archive_or_active_writes(
    staging_resources, monkeypatch, tmp_path,
):
    """A numeric(10,3) source value may not silently round into numeric(10,2)."""
    with _isolated_snapshot_databases(staging_resources) as databases:
        _seed_source(databases)
        source = _admin_connection(databases, databases.source_name)
        try:
            with source.cursor() as cursor:
                cursor.execute(
                    "ALTER TABLE public.trading_programs ALTER COLUMN price TYPE numeric(10,3) USING price::numeric(10,3)"
                )
                cursor.execute("UPDATE public.trading_programs SET price = 20.123 WHERE id = 1")
            source.commit()
        finally:
            source.close()
        metadata_path, csv_path, _ = _write_reviewed_metadata(databases, tmp_path)
        module_name, module = _load_importer_module()
        try:
            _, snapshot = _snapshot_for_expected_digest(module, databases, metadata_path, csv_path)
            _patch_private_connections(monkeypatch, module, databases)
            with pytest.raises(module.ImportRefusal) as refused:
                module.run(_run_args(databases, metadata_path, csv_path, snapshot.digest))
            assert "precision" in refused.value.code or "value" in refused.value.code
            _assert_rolled_back_target(
                databases,
                {name for name, plan in snapshot.tables.items() if plan.active},
            )
        finally:
            _unload_importer_module(module_name)


def test_legacy_snapshot_archive_payload_tamper_rolls_back_everything(
    staging_resources, monkeypatch, tmp_path,
):
    """Verification must digest archived payloads, not merely trust stored digests."""
    with _isolated_snapshot_databases(staging_resources) as databases:
        _seed_source(databases)
        metadata_path, csv_path, _ = _write_reviewed_metadata(databases, tmp_path)
        module_name, module = _load_importer_module()
        try:
            _, snapshot = _snapshot_for_expected_digest(module, databases, metadata_path, csv_path)
            _patch_private_connections(monkeypatch, module, databases)
            original_archive_rows = module._archive_rows
            active_tables = {name for name, plan in snapshot.tables.items() if plan.active}
            sequence_before = _sequence_canary(databases, active_tables)

            def archive_then_mutate_payload(connection, imported_snapshot):
                original_archive_rows(connection, imported_snapshot)
                with connection.cursor() as cursor:
                    # Leave record_digest unchanged: semantic verification has to
                    # hash the stored JSONB payload itself to detect this mutation.
                    cursor.execute(
                        """
                        UPDATE legacy_import.records
                           SET payload = jsonb_set(payload, '{verification_tamper}', 'true'::jsonb)
                         WHERE source_table = 'customlegacy' AND archive_ordinal = 1
                        """
                    )

            monkeypatch.setattr(module, "_archive_rows", archive_then_mutate_payload)
            with pytest.raises(module.ImportRefusal) as refused:
                module.run(_run_args(databases, metadata_path, csv_path, snapshot.digest))
            assert "archive" in refused.value.code
            _assert_rolled_back_target(databases, active_tables)
            # This failure happens after active inserts and sequence advancement,
            # so equality proves the rollback did not burn a target ID canary.
            assert _sequence_canary(databases, active_tables) == sequence_before
        finally:
            _unload_importer_module(module_name)


@pytest.mark.parametrize(
    ("heads", "expected_code"),
    (
        (("not_the_reviewed_head",), "target_current_alembic_head_mismatch"),
        (("20261013_000001", "not_the_reviewed_head"), "target_current_alembic_head_missing"),
    ),
    ids=("wrong-single-head", "multiple-head-rows"),
)
def test_legacy_snapshot_wrong_or_multiple_target_heads_refuse_before_archive(
    staging_resources, monkeypatch, tmp_path, heads, expected_code,
):
    """The target must have exactly the reviewed singleton Alembic head before archive creation."""
    with _isolated_snapshot_databases(staging_resources) as databases:
        _seed_source(databases)
        metadata_path, csv_path, _ = _write_reviewed_metadata(databases, tmp_path)
        target = _admin_connection(databases, databases.target_name)
        try:
            with target.cursor() as cursor:
                cursor.execute("DELETE FROM public.alembic_version")
                for head in heads:
                    cursor.execute("INSERT INTO public.alembic_version (version_num) VALUES (%s)", (head,))
            target.commit()
        finally:
            target.close()
        module_name, module = _load_importer_module()
        try:
            _, snapshot = _snapshot_for_expected_digest(module, databases, metadata_path, csv_path)
            _patch_private_connections(monkeypatch, module, databases)
            with pytest.raises(module.ImportRefusal) as refused:
                module.run(_run_args(databases, metadata_path, csv_path, snapshot.digest))
            assert refused.value.code == expected_code
            _assert_rolled_back_target(
                databases,
                {name for name, plan in snapshot.tables.items() if plan.active},
            )
        finally:
            _unload_importer_module(module_name)


def test_legacy_snapshot_access_exclusive_lock_blocks_concurrent_target_writer(staging_resources):
    """A real concurrent writer must time out only after the locked-empty gate is held."""
    with _isolated_snapshot_databases(staging_resources) as databases:
        module_name, module = _load_importer_module()
        target = _admin_connection(databases, databases.target_name)
        try:
            catalog = module._catalog(target)
            statement, values = _empty_table_insert_statement(target, "tenants")
            module._lock_target_tables(target, catalog)
            module._validate_target_empty(target, catalog)
            result: dict[str, object] = {}

            def concurrent_writer() -> None:
                writer = _admin_connection(databases, databases.target_name)
                try:
                    with writer.cursor() as cursor:
                        cursor.execute("SET lock_timeout = '500ms'")
                        cursor.execute(statement, values)
                    writer.commit()
                    result["committed"] = True
                except BaseException as exc:  # Thread errors must become test assertions.
                    result["error"] = exc
                    writer.rollback()
                finally:
                    writer.close()

            writer_thread = threading.Thread(target=concurrent_writer, name="legacy-import-lock-writer")
            writer_thread.start()
            writer_thread.join(timeout=5)
            assert not writer_thread.is_alive(), "concurrent target writer did not honor lock_timeout"
            assert "committed" not in result
            assert isinstance(result.get("error"), psycopg2.errors.LockNotAvailable)
            # Release our ACCESS EXCLUSIVE locks before a separate verifier opens
            # read locks against the same relations.
            target.rollback()
            _assert_rolled_back_target(databases, set(catalog) - {"alembic_version"})
        finally:
            target.rollback()
            target.close()
            _unload_importer_module(module_name)


@pytest.mark.parametrize(
    ("grant_sql", "expected_code"),
    (
        ("GRANT TRUNCATE ON legacy_import.records TO {role}", "runtime_role_has_archive_table_privilege"),
        ("GRANT SELECT (payload) ON legacy_import.records TO {role}", "runtime_role_has_archive_column_privilege"),
        ("GRANT CREATE ON SCHEMA legacy_import TO {role}", "runtime_role_has_archive_schema_privilege"),
    ),
    ids=("truncate", "column-select", "schema-create"),
)
def test_legacy_snapshot_archive_runtime_grants_refuse_and_roll_back(
    staging_resources, monkeypatch, tmp_path, grant_sql, expected_code,
):
    """Table, column, and schema grants to runtime are caught after archive creation."""
    with _isolated_snapshot_databases(staging_resources) as databases:
        _seed_source(databases)
        metadata_path, csv_path, _ = _write_reviewed_metadata(databases, tmp_path)
        module_name, module = _load_importer_module()
        try:
            _, snapshot = _snapshot_for_expected_digest(module, databases, metadata_path, csv_path)
            _patch_private_connections(monkeypatch, module, databases)
            original_create_archive = module._create_archive

            def create_archive_then_grant(connection, runtime_role):
                original_create_archive(connection, runtime_role)
                with connection.cursor() as cursor:
                    cursor.execute(grant_sql.format(role=_quoted_identifier(runtime_role)))
                # The explicit extracted post-create validator is the boundary under
                # test; run() also invokes it again immediately before commit.
                module._validate_archive_privileges(connection, runtime_role)

            monkeypatch.setattr(module, "_create_archive", create_archive_then_grant)
            with pytest.raises(module.ImportRefusal) as refused:
                module.run(_run_args(databases, metadata_path, csv_path, snapshot.digest))
            assert refused.value.code == expected_code
            _assert_rolled_back_target(
                databases,
                {name for name, plan in snapshot.tables.items() if plan.active},
            )
        finally:
            _unload_importer_module(module_name)


def test_legacy_snapshot_named_default_archive_privilege_to_runtime_refuses_and_rolls_back(
    staging_resources, monkeypatch, tmp_path,
):
    """A named (non-PUBLIC) default table grant is materialized and rejected for runtime."""
    with _isolated_snapshot_databases(staging_resources) as databases:
        _seed_source(databases)
        metadata_path, csv_path, _ = _write_reviewed_metadata(databases, tmp_path)
        defaults = _admin_connection(databases, databases.target_name)
        try:
            with defaults.cursor() as cursor:
                cursor.execute(
                    f"ALTER DEFAULT PRIVILEGES FOR ROLE postgres GRANT SELECT ON TABLES TO {_quoted_identifier(databases.runtime_role)}"
                )
            defaults.commit()
        finally:
            defaults.close()
        module_name, module = _load_importer_module()
        try:
            _, snapshot = _snapshot_for_expected_digest(module, databases, metadata_path, csv_path)
            _patch_private_connections(monkeypatch, module, databases)
            original_create_archive = module._create_archive

            def create_archive_as_postgres(connection, runtime_role):
                # The runner connection is a private bootstrap superuser; production
                # connects as postgres, so use that role for default-ACL materialization.
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL ROLE postgres")
                original_create_archive(connection, runtime_role)

            monkeypatch.setattr(module, "_create_archive", create_archive_as_postgres)
            with pytest.raises(module.ImportRefusal) as refused:
                module.run(_run_args(databases, metadata_path, csv_path, snapshot.digest))
            assert refused.value.code == "runtime_role_has_archive_table_privilege"
            _assert_rolled_back_target(
                databases,
                {name for name, plan in snapshot.tables.items() if plan.active},
            )
        finally:
            _unload_importer_module(module_name)


def test_legacy_snapshot_runtime_member_of_postgres_rejected_before_archive(
    staging_resources, monkeypatch, tmp_path,
):
    """NOINHERIT does not make a membership path to a superuser role safe for apply."""
    with _isolated_snapshot_databases(staging_resources) as databases:
        _seed_source(databases)
        metadata_path, csv_path, _ = _write_reviewed_metadata(databases, tmp_path)
        target = _admin_connection(databases, databases.target_name)
        try:
            with target.cursor() as cursor:
                cursor.execute("SELECT rolsuper FROM pg_roles WHERE rolname = %s", (databases.runtime_role,))
                assert cursor.fetchone() == (False,)
                cursor.execute(f"GRANT postgres TO {_quoted_identifier(databases.runtime_role)}")
            target.commit()
        finally:
            target.close()
        module_name, module = _load_importer_module()
        try:
            _, snapshot = _snapshot_for_expected_digest(module, databases, metadata_path, csv_path)
            _patch_private_connections(monkeypatch, module, databases)
            with pytest.raises(module.ImportRefusal) as refused:
                module.run(_run_args(databases, metadata_path, csv_path, snapshot.digest))
            assert refused.value.code == "runtime_role_has_superuser_membership"
            _assert_rolled_back_target(
                databases,
                {name for name, plan in snapshot.tables.items() if plan.active},
            )
        finally:
            _unload_importer_module(module_name)
