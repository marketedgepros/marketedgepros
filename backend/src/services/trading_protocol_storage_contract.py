"""Frozen storage metadata for the synthetic Stage5c trading-protocol rehearsal.

This module is deliberately data-only: runtime readiness checks can inspect PostgreSQL
without importing Alembic migration code or application models.
"""
from __future__ import annotations

import hashlib
import re
from types import MappingProxyType

from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql

HEAD_REVISION = "20261011_000008"

SNAPSHOT_TABLE = "trading_rule_snapshots"
COMMAND_TABLE = "trading_provision_commands"
INBOX_TABLE = "trading_event_inbox"
TABLES = (SNAPSHOT_TABLE, COMMAND_TABLE, INBOX_TABLE)

IMMUTABLE_FUNCTION = "marketedgepros_trading_protocol_immutable"
SNAPSHOT_VALIDATE_FUNCTION = "marketedgepros_trading_rule_snapshot_validate"
COMMAND_VALIDATE_FUNCTION = "marketedgepros_trading_provision_command_validate"
INBOX_VALIDATE_FUNCTION = "marketedgepros_trading_event_inbox_validate"
COMMAND_TRANSITION_FUNCTION = "marketedgepros_trading_provision_command_transition"
FUNCTION_NAMES = (
    IMMUTABLE_FUNCTION,
    SNAPSHOT_VALIDATE_FUNCTION,
    COMMAND_VALIDATE_FUNCTION,
    INBOX_VALIDATE_FUNCTION,
    COMMAND_TRANSITION_FUNCTION,
)

EXPECTED_COLUMNS = MappingProxyType({
    SNAPSHOT_TABLE: MappingProxyType({
        "id": ("varchar(64)", False),
        "tenant_id": ("integer", False),
        "program_id": ("integer", False),
        "phase": ("integer", False),
        "rules_version": ("varchar(64)", False),
        "rules_digest": ("varchar(64)", False),
        "canonical_rules": ("jsonb", False),
        "source": ("varchar(16)", False),
        "created_at": ("timestamp with time zone", False),
    }),
    COMMAND_TABLE: MappingProxyType({
        "id": ("varchar(36)", False),
        "tenant_id": ("integer", False),
        "challenge_id": ("integer", False),
        "phase": ("integer", False),
        "provider_id": ("varchar(64)", False),
        "rule_snapshot_id": ("varchar(64)", False),
        "source": ("varchar(16)", False),
        "status": ("varchar(16)", False),
        "attempt_token": ("varchar(36)", True),
        "account_id": ("varchar(64)", True),
        "created_at": ("timestamp with time zone", False),
        "updated_at": ("timestamp with time zone", False),
    }),
    INBOX_TABLE: MappingProxyType({
        "id": ("varchar(36)", False),
        "command_id": ("varchar(36)", False),
        "provider_id": ("varchar(64)", False),
        "account_id": ("varchar(64)", False),
        "event_id": ("varchar(128)", False),
        "sequence": ("bigint", False),
        "payload_hash": ("varchar(64)", False),
        "payload": ("jsonb", False),
        "received_at": ("timestamp with time zone", False),
    }),
})

EXPECTED_FOREIGN_KEYS = MappingProxyType({
    SNAPSHOT_TABLE: MappingProxyType({
        "fk_trading_rule_snapshots_tenant": ("tenant_id", "tenants"),
        "fk_trading_rule_snapshots_program": ("program_id", "trading_programs"),
    }),
    COMMAND_TABLE: MappingProxyType({
        "fk_trading_provision_commands_tenant": ("tenant_id", "tenants"),
        "fk_trading_provision_commands_challenge": ("challenge_id", "challenges"),
        "fk_trading_provision_commands_snapshot": ("rule_snapshot_id", SNAPSHOT_TABLE),
    }),
    INBOX_TABLE: MappingProxyType({
        "fk_trading_event_inbox_command": ("command_id", COMMAND_TABLE),
    }),
})

EXPECTED_UNIQUES = MappingProxyType({
    SNAPSHOT_TABLE: MappingProxyType({
        "uq_trading_rule_snapshot_context": ("tenant_id", "program_id", "phase", "rules_version"),
    }),
    COMMAND_TABLE: MappingProxyType({
        "uq_trading_provision_command_context": ("tenant_id", "challenge_id", "phase"),
        "uq_trading_provision_provider_account": ("provider_id", "account_id"),
    }),
    INBOX_TABLE: MappingProxyType({
        "uq_trading_event_inbox_event": ("provider_id", "account_id", "event_id"),
        "uq_trading_event_inbox_sequence": ("provider_id", "account_id", "sequence"),
    }),
})

EXPECTED_CHECKS = MappingProxyType({
    SNAPSHOT_TABLE: frozenset({
        "ck_trading_rule_snapshot_id", "ck_trading_rule_snapshot_phase",
        "ck_trading_rule_snapshot_rules_version", "ck_trading_rule_snapshot_digest",
        "ck_trading_rule_snapshot_canonical", "ck_trading_rule_snapshot_source",
    }),
    COMMAND_TABLE: frozenset({
        "ck_trading_provision_command_id", "ck_trading_provision_command_phase",
        "ck_trading_provision_command_provider", "ck_trading_provision_command_source",
        "ck_trading_provision_command_status", "ck_trading_provision_command_shape",
        "ck_trading_provision_command_token", "ck_trading_provision_command_account",
        "ck_trading_provision_command_times",
    }),
    INBOX_TABLE: frozenset({
        "ck_trading_event_inbox_id", "ck_trading_event_inbox_identity",
        "ck_trading_event_inbox_sequence", "ck_trading_event_inbox_hash",
        "ck_trading_event_inbox_payload",
    }),
})

# Keys are (table, trigger name); values are (pg_trigger.tgtype, function name).
EXPECTED_TRIGGERS = MappingProxyType({
    (SNAPSHOT_TABLE, "trading_rule_snapshots_immutable"): (27, IMMUTABLE_FUNCTION),
    (SNAPSHOT_TABLE, "trading_rule_snapshots_validate_insert"): (7, SNAPSHOT_VALIDATE_FUNCTION),
    (SNAPSHOT_TABLE, "trading_rule_snapshots_no_truncate"): (34, IMMUTABLE_FUNCTION),
    (COMMAND_TABLE, "trading_provision_commands_transition"): (27, COMMAND_TRANSITION_FUNCTION),
    (COMMAND_TABLE, "trading_provision_commands_validate_insert"): (7, COMMAND_VALIDATE_FUNCTION),
    (COMMAND_TABLE, "trading_provision_commands_no_truncate"): (34, IMMUTABLE_FUNCTION),
    (INBOX_TABLE, "trading_event_inbox_immutable"): (27, IMMUTABLE_FUNCTION),
    (INBOX_TABLE, "trading_event_inbox_validate_insert"): (7, INBOX_VALIDATE_FUNCTION),
    (INBOX_TABLE, "trading_event_inbox_no_truncate"): (34, IMMUTABLE_FUNCTION),
})

# SHA-256 of PostgreSQL pg_proc.prosrc.strip().  Values are intentionally literals
# rather than computed from migration source, so runtime checks remain independent.
FUNCTION_HASHES = MappingProxyType({
    IMMUTABLE_FUNCTION: "bc0ad77ae63c3a8ce37e1382c4b98455d271fd85530845cbc26c2e1861222a53",
    SNAPSHOT_VALIDATE_FUNCTION: "3eb4fd44b77d1de526f1cd3143254b54c15bae5128c13942f054330324f7b246",
    COMMAND_VALIDATE_FUNCTION: "da958f21d771d81d4e174b83e0c951e0a9e6ce311580a2656280642ad6950ed0",
    INBOX_VALIDATE_FUNCTION: "2d21f0fb4c5548e1c297440d0a87764ad7570112ac75e5acdfb1e53d2a87f48b",
    COMMAND_TRANSITION_FUNCTION: "f7bc9beda5044647c950fed9269d211b1e3a72fd5ccd494ac98cd09e3537f4d7",
})
EXPECTED_FUNCTION_HASHES = FUNCTION_HASHES
FOREIGN_KEYS = EXPECTED_FOREIGN_KEYS
UNIQUE_CONSTRAINTS = EXPECTED_UNIQUES

CHECKS = MappingProxyType({
    SNAPSHOT_TABLE: MappingProxyType({
        "ck_trading_rule_snapshot_id": "id ~ '^[0-9a-f]{64}$'",
        "ck_trading_rule_snapshot_phase": "phase >= 1 AND phase <= 9",
        "ck_trading_rule_snapshot_rules_version": "rules_version ~ '^[A-Za-z0-9._:-]{1,64}$'",
        "ck_trading_rule_snapshot_digest": "rules_digest ~ '^[0-9a-f]{64}$'",
        "ck_trading_rule_snapshot_canonical": "jsonb_typeof(canonical_rules) = 'object' AND canonical_rules ?& ARRAY['schema_version','rules_version','program_id','phase','currency','currency_scale','initial_units','profit_target','daily_loss','total_loss','target_basis','daily_basis','daily_reference_basis','total_basis','total_drawdown_mode','loss_at_threshold_is_breach','target_at_threshold_is_met','timezone_name','reset_hour','reset_minute','reset_fold','maximum_age_seconds'] AND (canonical_rules - 'schema_version' - 'rules_version' - 'program_id' - 'phase' - 'currency' - 'currency_scale' - 'initial_units' - 'profit_target' - 'daily_loss' - 'total_loss' - 'target_basis' - 'daily_basis' - 'daily_reference_basis' - 'total_basis' - 'total_drawdown_mode' - 'loss_at_threshold_is_breach' - 'target_at_threshold_is_met' - 'timezone_name' - 'reset_hour' - 'reset_minute' - 'reset_fold' - 'maximum_age_seconds') = '{}'::jsonb",
        "ck_trading_rule_snapshot_source": "source = 'synthetic'",
    }),
    COMMAND_TABLE: MappingProxyType({
        "ck_trading_provision_command_id": "id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
        "ck_trading_provision_command_phase": "phase >= 1 AND phase <= 9",
        "ck_trading_provision_command_provider": "provider_id ~ '^[A-Za-z0-9_.:-]{1,64}$'",
        "ck_trading_provision_command_source": "source = 'synthetic'",
        "ck_trading_provision_command_status": "status IN ('planned', 'dispatched', 'uncertain', 'acknowledged')",
        "ck_trading_provision_command_shape": "(status = 'planned' AND attempt_token IS NULL AND account_id IS NULL) OR (status IN ('dispatched', 'uncertain') AND attempt_token IS NOT NULL AND account_id IS NULL) OR (status = 'acknowledged' AND attempt_token IS NOT NULL AND account_id IS NOT NULL)",
        "ck_trading_provision_command_token": "attempt_token IS NULL OR attempt_token ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
        "ck_trading_provision_command_account": "account_id IS NULL OR account_id ~ '^[A-Za-z0-9_.:-]{1,64}$'",
        "ck_trading_provision_command_times": "updated_at >= created_at",
    }),
    INBOX_TABLE: MappingProxyType({
        "ck_trading_event_inbox_id": "id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
        "ck_trading_event_inbox_identity": "provider_id ~ '^[A-Za-z0-9_.:-]{1,64}$' AND account_id ~ '^[A-Za-z0-9_.:-]{1,64}$' AND event_id ~ '^[A-Za-z0-9_.:-]{1,128}$'",
        "ck_trading_event_inbox_sequence": "sequence > 0",
        "ck_trading_event_inbox_hash": "payload_hash ~ '^[0-9a-f]{64}$'",
        "ck_trading_event_inbox_payload": "jsonb_typeof(payload) = 'object' AND payload ?& ARRAY['schema_version','source','local_only','observation'] AND (payload - 'schema_version' - 'source' - 'local_only' - 'observation') = '{}'::jsonb AND payload->'schema_version' = '1'::jsonb AND payload->'source' = '\"synthetic\"'::jsonb AND payload->'local_only' = 'true'::jsonb AND jsonb_typeof(payload->'observation') = 'object' AND payload->'observation' ?& ARRAY['tenant_id','challenge_id','provider_id','account_id','rules_digest','event_id','sequence','observed_at','currency','currency_scale','balance_units','equity_units','equity_includes_fees_and_swaps'] AND ((payload->'observation') - 'tenant_id' - 'challenge_id' - 'provider_id' - 'account_id' - 'rules_digest' - 'event_id' - 'sequence' - 'observed_at' - 'currency' - 'currency_scale' - 'balance_units' - 'equity_units' - 'equity_includes_fees_and_swaps') = '{}'::jsonb",
    }),
})
EXPECTED_INDEXES = MappingProxyType({
    SNAPSHOT_TABLE: frozenset({("trading_rule_snapshots_pkey", True, True, "id"), ("uq_trading_rule_snapshot_context", True, False, "tenant_id,program_id,phase,rules_version")}),
    COMMAND_TABLE: frozenset({("trading_provision_commands_pkey", True, True, "id"), ("uq_trading_provision_command_context", True, False, "tenant_id,challenge_id,phase"), ("uq_trading_provision_provider_account", True, False, "provider_id,account_id")}),
    INBOX_TABLE: frozenset({("trading_event_inbox_pkey", True, True, "id"), ("uq_trading_event_inbox_event", True, False, "provider_id,account_id,event_id"), ("uq_trading_event_inbox_sequence", True, False, "provider_id,account_id,sequence")}),
})


def _normalised_type(type_) -> str:
    return " ".join(str(type_.compile(dialect=postgresql.dialect())).lower().replace("character varying", "varchar").split())


def _normalised_check(expression: str) -> str:
    value = "".join(str(expression).lower().split())
    value = re.sub(r"'([0-9]+)'::bigint", r"\1", value)
    value = value.replace("::text[]", "").replace("::character varying", "").replace("::charactervarying", "").replace("::text", "")
    value = re.sub(r"=any\(array\[([^]]*)\]\)", r"in(\1)", value)
    return value.replace('"', '').replace("(", "").replace(")", "")


def _index_rows(connection, table_name: str):
    return connection.execute(text("""
        SELECT index_relation.relname AS name, index_meta.indisunique AS is_unique,
               index_meta.indisprimary AS is_primary, index_meta.indpred IS NULL AS no_predicate,
               index_meta.indexprs IS NULL AS no_expressions,
               array_to_string(array_agg(attribute.attname ORDER BY key_part.ordinality), ',') AS columns
        FROM pg_index AS index_meta JOIN pg_class AS table_relation ON table_relation.oid = index_meta.indrelid
        JOIN pg_namespace AS namespace ON namespace.oid = table_relation.relnamespace
        JOIN pg_class AS index_relation ON index_relation.oid = index_meta.indexrelid
        LEFT JOIN LATERAL unnest(index_meta.indkey) WITH ORDINALITY AS key_part(attnum, ordinality) ON true
        LEFT JOIN pg_attribute AS attribute ON attribute.attrelid = index_meta.indrelid AND attribute.attnum = key_part.attnum
        WHERE namespace.nspname = 'public' AND table_relation.relname = :table_name
        GROUP BY index_relation.relname, index_meta.indisunique, index_meta.indisprimary, index_meta.indpred, index_meta.indexprs
    """), {"table_name": table_name}).mappings().all()


def validate_storage(connection) -> None:
    """Raise RuntimeError unless every Stage5c relation, trigger, and function is frozen."""
    inspector, errors = inspect(connection), []
    for table in TABLES:
        columns = {row["name"]: row for row in inspector.get_columns(table, schema="public")}
        if set(columns) != set(EXPECTED_COLUMNS[table]):
            errors.append(table + ".columns")
            continue
        for name, (type_name, nullable) in EXPECTED_COLUMNS[table].items():
            item = columns[name]
            if _normalised_type(item["type"]) != type_name or item["nullable"] is not nullable or item["default"] is not None:
                errors.append(table + "." + name)
        if inspector.get_pk_constraint(table, schema="public").get("constrained_columns") != ["id"]:
            errors.append(table + ".primary_key")
        fks = {row["name"]: row for row in inspector.get_foreign_keys(table, schema="public")}
        if set(fks) != set(FOREIGN_KEYS[table]): errors.append(table + ".foreign_keys")
        for name, (column, parent) in FOREIGN_KEYS[table].items():
            item = fks.get(name)
            if item is None or item.get("constrained_columns") != [column] or item.get("referred_table") != parent or item.get("referred_columns") != ["id"] or item.get("referred_schema") not in (None, "public") or item.get("options"):
                errors.append(table + "." + name)
        uniques = {row["name"]: row for row in inspector.get_unique_constraints(table, schema="public")}
        if set(uniques) != set(UNIQUE_CONSTRAINTS[table]): errors.append(table + ".unique_constraints")
        for name, expected in UNIQUE_CONSTRAINTS[table].items():
            if name not in uniques or tuple(uniques[name].get("column_names") or ()) != tuple(expected): errors.append(table + "." + name)
        checks = {row["name"]: row for row in inspector.get_check_constraints(table, schema="public")}
        if set(checks) != set(CHECKS[table]): errors.append(table + ".check_constraints")
        for name, expected in CHECKS[table].items():
            if name not in checks or _normalised_check(checks[name].get("sqltext", "")) != _normalised_check(expected): errors.append(table + "." + name)
        indexes = _index_rows(connection, table)
        if any(not row["no_predicate"] or not row["no_expressions"] for row in indexes): errors.append(table + ".index_definition")
        if {(row["name"], row["is_unique"], row["is_primary"], row["columns"]) for row in indexes} != EXPECTED_INDEXES[table]: errors.append(table + ".indexes")
    rows = connection.execute(text("""
        SELECT relation.relname AS table_name, trigger.tgname, trigger.tgtype, trigger.tgenabled,
               trigger.tgnargs, trigger.tgqual IS NULL AS no_when, trigger.tgfoid, procedure.proname
        FROM pg_trigger AS trigger JOIN pg_class AS relation ON relation.oid = trigger.tgrelid
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace JOIN pg_proc AS procedure ON procedure.oid = trigger.tgfoid
        WHERE namespace.nspname = 'public' AND relation.relname = ANY(:tables) AND NOT trigger.tgisinternal
    """), {"tables": list(TABLES)}).mappings().all()
    triggers = {(row["table_name"], row["tgname"]): row for row in rows}
    if set(triggers) != set(EXPECTED_TRIGGERS): errors.append("triggers")
    for key, (tgtype, function_name) in EXPECTED_TRIGGERS.items():
        row = triggers.get(key)
        if row is None or row["tgtype"] != tgtype or row["tgenabled"] != "O" or row["tgnargs"] != 0 or not row["no_when"] or row["proname"] != function_name: errors.append("trigger." + key[1])
    rows = connection.execute(text("""
        SELECT procedure.oid, procedure.proname, procedure.prosrc,
               pg_get_function_identity_arguments(procedure.oid) AS signature,
               procedure.prorettype::regtype::text AS return_type, procedure.prokind,
               language.lanname AS language, procedure.provolatile, procedure.proisstrict,
               procedure.prosecdef, procedure.proleakproof, procedure.proparallel,
               procedure.proconfig, procedure.proacl
        FROM pg_proc AS procedure JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
        JOIN pg_language AS language ON language.oid = procedure.prolang
        WHERE namespace.nspname = 'public' AND procedure.proname = ANY(:names)
    """), {"names": list(FUNCTION_NAMES)}).mappings().all()
    functions = {row["proname"]: row for row in rows}
    if set(functions) != set(FUNCTION_HASHES): errors.append("functions")
    for name, expected_hash in FUNCTION_HASHES.items():
        row = functions.get(name)
        if (row is None or row["signature"] != "" or row["return_type"] != "trigger" or row["prokind"] != "f"
                or row["language"] != "plpgsql" or row["provolatile"] != "v" or row["proisstrict"]
                or row["prosecdef"] or row["proleakproof"] or row["proparallel"] != "u"
                or row["proconfig"] is not None or row["proacl"] is not None
                or hashlib.sha256(row["prosrc"].strip().encode("utf-8")).hexdigest() != expected_hash): errors.append("function." + name)
    for key, (_, function_name) in EXPECTED_TRIGGERS.items():
        if key in triggers and function_name in functions and int(triggers[key]["tgfoid"]) != int(functions[function_name]["oid"]):
            errors.append("trigger_function." + key[1])
    if errors:
        raise RuntimeError("Trading protocol storage metadata mismatch: " + ", ".join(sorted(set(errors))))
