"""Create local-only synthetic trading protocol persistence.

Revision ID: 20261011_000008
Revises: 20261011_000007

This frozen rehearsal migration creates no provider integration, entitlement, account,
financial mutation, seed row, worker, or schedule.  PostgreSQL triggers are the
authority for direct-SQL immutability, cross-table identity binding, and the one-way
synthetic command state machine.  Online upgrade rejects every owned collision before
DDL; online downgrade refuses nonempty or ownership-drifted data before any DROP.
"""
from __future__ import annotations

import re

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261011_000008"
down_revision = "20261011_000007"
branch_labels = None
depends_on = None

SNAPSHOT_TABLE = "trading_rule_snapshots"
COMMAND_TABLE = "trading_provision_commands"
INBOX_TABLE = "trading_event_inbox"
TABLES = (SNAPSHOT_TABLE, COMMAND_TABLE, INBOX_TABLE)

IMMUTABLE_FUNCTION = "marketedgepros_trading_protocol_immutable"
SNAPSHOT_VALIDATE_FUNCTION = "marketedgepros_trading_rule_snapshot_validate"
COMMAND_VALIDATE_FUNCTION = "marketedgepros_trading_provision_command_validate"
INBOX_VALIDATE_FUNCTION = "marketedgepros_trading_event_inbox_validate"
COMMAND_TRANSITION_FUNCTION = "marketedgepros_trading_provision_command_transition"
FUNCTION_BODIES: dict[str, str] = {
    IMMUTABLE_FUNCTION: """BEGIN
    RAISE EXCEPTION 'trading protocol rows are immutable';
END;""",
    SNAPSHOT_VALIDATE_FUNCTION: """BEGIN
    IF NEW.source <> 'synthetic' THEN
        RAISE EXCEPTION 'trading rule snapshot source must be synthetic';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM public.trading_programs AS program
        WHERE program.id = NEW.program_id AND program.tenant_id = NEW.tenant_id
    ) THEN
        RAISE EXCEPTION 'trading rule snapshot program must belong to its tenant';
    END IF;
    IF jsonb_typeof(NEW.canonical_rules->'program_id') IS DISTINCT FROM 'number'
       OR jsonb_typeof(NEW.canonical_rules->'phase') IS DISTINCT FROM 'number'
       OR jsonb_typeof(NEW.canonical_rules->'rules_version') IS DISTINCT FROM 'string'
       OR NEW.canonical_rules->'program_id' IS DISTINCT FROM to_jsonb(NEW.program_id)
       OR NEW.canonical_rules->'phase' IS DISTINCT FROM to_jsonb(NEW.phase)
       OR NEW.canonical_rules->>'rules_version' IS DISTINCT FROM NEW.rules_version THEN
        RAISE EXCEPTION 'trading rule snapshot canonical rules must bind program, phase, and version';
    END IF;
    RETURN NEW;
END;""",
    COMMAND_VALIDATE_FUNCTION: """DECLARE
    v_snapshot public.trading_rule_snapshots%ROWTYPE;
    v_challenge public.challenges%ROWTYPE;
    v_owner_tenant integer;
BEGIN
    IF NEW.source <> 'synthetic' THEN
        RAISE EXCEPTION 'trading provision command source must be synthetic';
    END IF;
    IF NEW.status IS DISTINCT FROM 'planned'
       OR NEW.attempt_token IS NOT NULL OR NEW.account_id IS NOT NULL THEN
        RAISE EXCEPTION 'trading provision commands must be inserted planned without token or account';
    END IF;
    SELECT snapshot.* INTO v_snapshot
    FROM public.trading_rule_snapshots AS snapshot
    WHERE snapshot.id = NEW.rule_snapshot_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'trading provision command rule snapshot is missing';
    END IF;
    SELECT challenge.* INTO v_challenge
    FROM public.challenges AS challenge
    WHERE challenge.id = NEW.challenge_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'trading provision command challenge is missing';
    END IF;
    SELECT owner.tenant_id INTO v_owner_tenant
    FROM public.users AS owner
    WHERE owner.id = v_challenge.user_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'trading provision command challenge owner is missing';
    END IF;
    IF v_snapshot.tenant_id IS DISTINCT FROM NEW.tenant_id
       OR v_snapshot.program_id IS DISTINCT FROM v_challenge.program_id
       OR v_snapshot.phase IS DISTINCT FROM NEW.phase
       OR v_owner_tenant IS DISTINCT FROM NEW.tenant_id
       OR NEW.created_at < v_snapshot.created_at
       OR NOT EXISTS (SELECT 1 FROM public.trading_programs p
                      WHERE p.id=v_challenge.program_id AND p.tenant_id=NEW.tenant_id) THEN
        RAISE EXCEPTION 'trading provision command tenant, challenge, snapshot, program, or phase mismatch';
    END IF;
    RETURN NEW;
END;""",
    INBOX_VALIDATE_FUNCTION: """DECLARE
    v_command public.trading_provision_commands%ROWTYPE;
    v_rules_digest varchar(64);
BEGIN
    SELECT command.* INTO v_command
    FROM public.trading_provision_commands AS command
    WHERE command.id = NEW.command_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'trading event inbox command is missing';
    END IF;
    IF v_command.status <> 'acknowledged'
       OR v_command.provider_id <> NEW.provider_id
       OR v_command.account_id <> NEW.account_id THEN
        RAISE EXCEPTION 'trading event inbox requires acknowledged command identity';
    END IF;
    SELECT snapshot.rules_digest INTO v_rules_digest
    FROM public.trading_rule_snapshots AS snapshot
    WHERE snapshot.id = v_command.rule_snapshot_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'trading event inbox rule snapshot is missing';
    END IF;
    IF jsonb_typeof(NEW.payload->'observation'->'tenant_id') IS DISTINCT FROM 'number'
       OR jsonb_typeof(NEW.payload->'observation'->'challenge_id') IS DISTINCT FROM 'number'
       OR jsonb_typeof(NEW.payload->'observation'->'sequence') IS DISTINCT FROM 'number'
       OR jsonb_typeof(NEW.payload->'observation'->'currency_scale') IS DISTINCT FROM 'number'
       OR jsonb_typeof(NEW.payload->'observation'->'balance_units') IS DISTINCT FROM 'number'
       OR jsonb_typeof(NEW.payload->'observation'->'equity_units') IS DISTINCT FROM 'number'
       OR jsonb_typeof(NEW.payload->'observation'->'observed_at') IS DISTINCT FROM 'string'
       OR jsonb_typeof(NEW.payload->'observation'->'currency') IS DISTINCT FROM 'string'
       OR jsonb_typeof(NEW.payload->'observation'->'equity_includes_fees_and_swaps') IS DISTINCT FROM 'boolean'
       OR NEW.payload->'observation'->'tenant_id' IS DISTINCT FROM to_jsonb(v_command.tenant_id)
       OR NEW.payload->'observation'->'challenge_id' IS DISTINCT FROM to_jsonb(v_command.challenge_id)
       OR NEW.payload->'observation'->>'provider_id' IS DISTINCT FROM NEW.provider_id
       OR NEW.payload->'observation'->>'account_id' IS DISTINCT FROM NEW.account_id
       OR NEW.payload->'observation'->>'rules_digest' IS DISTINCT FROM v_rules_digest
       OR NEW.payload->'observation'->>'event_id' IS DISTINCT FROM NEW.event_id
       OR NEW.payload->'observation'->'sequence' IS DISTINCT FROM to_jsonb(NEW.sequence)
       OR NEW.payload->'source' IS DISTINCT FROM '"synthetic"'::jsonb
       OR NEW.payload->'local_only' IS DISTINCT FROM 'true'::jsonb THEN
        RAISE EXCEPTION 'trading event inbox payload must be the canonical local synthetic observation';
    END IF;
    RETURN NEW;
END;""",
    COMMAND_TRANSITION_FUNCTION: """BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'trading provision commands cannot be deleted';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.challenge_id IS DISTINCT FROM OLD.challenge_id
       OR NEW.phase IS DISTINCT FROM OLD.phase
       OR NEW.provider_id IS DISTINCT FROM OLD.provider_id
       OR NEW.rule_snapshot_id IS DISTINCT FROM OLD.rule_snapshot_id
       OR NEW.source IS DISTINCT FROM OLD.source
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'trading provision command identity is immutable';
    END IF;
    IF NEW.updated_at < OLD.updated_at OR NEW.updated_at < NEW.created_at THEN
        RAISE EXCEPTION 'trading provision command timestamps cannot move backwards';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM public.trading_rule_snapshots AS snapshot
        JOIN public.challenges AS challenge ON challenge.id = OLD.challenge_id
        JOIN public.users AS owner ON owner.id = challenge.user_id
        JOIN public.trading_programs AS program ON program.id = challenge.program_id
        WHERE snapshot.id = OLD.rule_snapshot_id
          AND snapshot.tenant_id = OLD.tenant_id
          AND snapshot.program_id = challenge.program_id
          AND snapshot.phase = OLD.phase
          AND owner.tenant_id = OLD.tenant_id
          AND program.tenant_id = OLD.tenant_id
          AND OLD.created_at >= snapshot.created_at
    ) THEN
        RAISE EXCEPTION 'trading provision command scope changed after planning';
    END IF;
    -- Exact state/identity replays and monotonic supplied timestamps are harmless.
    IF NEW.status = OLD.status
       AND NEW.attempt_token IS NOT DISTINCT FROM OLD.attempt_token
       AND NEW.account_id IS NOT DISTINCT FROM OLD.account_id THEN
        RETURN NEW;
    END IF;
    IF OLD.status = 'planned' THEN
        IF NEW.status <> 'dispatched'
           OR NEW.attempt_token IS NULL
           OR NEW.account_id IS NOT NULL THEN
            RAISE EXCEPTION 'trading provision command only transitions planned to dispatched with one token';
        END IF;
    ELSIF OLD.status = 'dispatched' THEN
        IF NEW.status NOT IN ('uncertain', 'acknowledged')
           OR NEW.attempt_token IS DISTINCT FROM OLD.attempt_token
           OR (NEW.status = 'uncertain' AND NEW.account_id IS NOT NULL)
           OR (NEW.status = 'acknowledged' AND NEW.account_id IS NULL) THEN
            RAISE EXCEPTION 'trading provision command dispatched transition is invalid';
        END IF;
    ELSIF OLD.status = 'uncertain' THEN
        IF NEW.status <> 'acknowledged'
           OR NEW.attempt_token IS DISTINCT FROM OLD.attempt_token
           OR NEW.account_id IS NULL THEN
            RAISE EXCEPTION 'trading provision command uncertain transition is invalid';
        END IF;
    ELSE
        RAISE EXCEPTION 'trading provision command acknowledged state is terminal';
    END IF;
    RETURN NEW;
END;""",
}

FOREIGN_KEYS = {
    SNAPSHOT_TABLE: {
        "fk_trading_rule_snapshots_tenant": ("tenant_id", "tenants"),
        "fk_trading_rule_snapshots_program": ("program_id", "trading_programs"),
    },
    COMMAND_TABLE: {
        "fk_trading_provision_commands_tenant": ("tenant_id", "tenants"),
        "fk_trading_provision_commands_challenge": ("challenge_id", "challenges"),
        "fk_trading_provision_commands_snapshot": ("rule_snapshot_id", SNAPSHOT_TABLE),
    },
    INBOX_TABLE: {"fk_trading_event_inbox_command": ("command_id", COMMAND_TABLE)},
}

UNIQUE_CONSTRAINTS = {
    SNAPSHOT_TABLE: {"uq_trading_rule_snapshot_context": ["tenant_id", "program_id", "phase", "rules_version"]},
    COMMAND_TABLE: {
        "uq_trading_provision_command_context": ["tenant_id", "challenge_id", "phase"],
        "uq_trading_provision_provider_account": ["provider_id", "account_id"],
    },
    INBOX_TABLE: {
        "uq_trading_event_inbox_event": ["provider_id", "account_id", "event_id"],
        "uq_trading_event_inbox_sequence": ["provider_id", "account_id", "sequence"],
    },
}

CHECKS = {
    SNAPSHOT_TABLE: {
        "ck_trading_rule_snapshot_id": "id ~ '^[0-9a-f]{64}$'",
        "ck_trading_rule_snapshot_phase": "phase >= 1 AND phase <= 9",
        "ck_trading_rule_snapshot_rules_version": "rules_version ~ '^[A-Za-z0-9._:-]{1,64}$'",
        "ck_trading_rule_snapshot_digest": "rules_digest ~ '^[0-9a-f]{64}$'",
        "ck_trading_rule_snapshot_canonical": "jsonb_typeof(canonical_rules) = 'object' AND canonical_rules ?& ARRAY['schema_version','rules_version','program_id','phase','currency','currency_scale','initial_units','profit_target','daily_loss','total_loss','target_basis','daily_basis','daily_reference_basis','total_basis','total_drawdown_mode','loss_at_threshold_is_breach','target_at_threshold_is_met','timezone_name','reset_hour','reset_minute','reset_fold','maximum_age_seconds'] AND (canonical_rules - 'schema_version' - 'rules_version' - 'program_id' - 'phase' - 'currency' - 'currency_scale' - 'initial_units' - 'profit_target' - 'daily_loss' - 'total_loss' - 'target_basis' - 'daily_basis' - 'daily_reference_basis' - 'total_basis' - 'total_drawdown_mode' - 'loss_at_threshold_is_breach' - 'target_at_threshold_is_met' - 'timezone_name' - 'reset_hour' - 'reset_minute' - 'reset_fold' - 'maximum_age_seconds') = '{}'::jsonb",
        "ck_trading_rule_snapshot_source": "source = 'synthetic'",
    },
    COMMAND_TABLE: {
        "ck_trading_provision_command_id": "id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
        "ck_trading_provision_command_phase": "phase >= 1 AND phase <= 9",
        "ck_trading_provision_command_provider": "provider_id ~ '^[A-Za-z0-9_.:-]{1,64}$'",
        "ck_trading_provision_command_source": "source = 'synthetic'",
        "ck_trading_provision_command_status": "status IN ('planned', 'dispatched', 'uncertain', 'acknowledged')",
        "ck_trading_provision_command_shape": "(status = 'planned' AND attempt_token IS NULL AND account_id IS NULL) OR (status IN ('dispatched', 'uncertain') AND attempt_token IS NOT NULL AND account_id IS NULL) OR (status = 'acknowledged' AND attempt_token IS NOT NULL AND account_id IS NOT NULL)",
        "ck_trading_provision_command_token": "attempt_token IS NULL OR attempt_token ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
        "ck_trading_provision_command_account": "account_id IS NULL OR account_id ~ '^[A-Za-z0-9_.:-]{1,64}$'",
        "ck_trading_provision_command_times": "updated_at >= created_at",
    },
    INBOX_TABLE: {
        "ck_trading_event_inbox_id": "id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
        "ck_trading_event_inbox_identity": "provider_id ~ '^[A-Za-z0-9_.:-]{1,64}$' AND account_id ~ '^[A-Za-z0-9_.:-]{1,64}$' AND event_id ~ '^[A-Za-z0-9_.:-]{1,128}$'",
        "ck_trading_event_inbox_sequence": "sequence > 0",
        "ck_trading_event_inbox_hash": "payload_hash ~ '^[0-9a-f]{64}$'",
        "ck_trading_event_inbox_payload": "jsonb_typeof(payload) = 'object' AND payload ?& ARRAY['schema_version','source','local_only','observation'] AND (payload - 'schema_version' - 'source' - 'local_only' - 'observation') = '{}'::jsonb AND payload->'schema_version' = '1'::jsonb AND payload->'source' = '\"synthetic\"'::jsonb AND payload->'local_only' = 'true'::jsonb AND jsonb_typeof(payload->'observation') = 'object' AND payload->'observation' ?& ARRAY['tenant_id','challenge_id','provider_id','account_id','rules_digest','event_id','sequence','observed_at','currency','currency_scale','balance_units','equity_units','equity_includes_fees_and_swaps'] AND ((payload->'observation') - 'tenant_id' - 'challenge_id' - 'provider_id' - 'account_id' - 'rules_digest' - 'event_id' - 'sequence' - 'observed_at' - 'currency' - 'currency_scale' - 'balance_units' - 'equity_units' - 'equity_includes_fees_and_swaps') = '{}'::jsonb",
    },
}

EXPECTED_COLUMNS = {
    SNAPSHOT_TABLE: {
        "id": ("varchar(64)", False), "tenant_id": ("integer", False),
        "program_id": ("integer", False), "phase": ("integer", False),
        "rules_version": ("varchar(64)", False), "rules_digest": ("varchar(64)", False),
        "canonical_rules": ("jsonb", False), "source": ("varchar(16)", False),
        "created_at": ("timestamp with time zone", False),
    },
    COMMAND_TABLE: {
        "id": ("varchar(36)", False), "tenant_id": ("integer", False),
        "challenge_id": ("integer", False), "phase": ("integer", False),
        "provider_id": ("varchar(64)", False), "rule_snapshot_id": ("varchar(64)", False),
        "source": ("varchar(16)", False), "status": ("varchar(16)", False),
        "attempt_token": ("varchar(36)", True), "account_id": ("varchar(64)", True),
        "created_at": ("timestamp with time zone", False), "updated_at": ("timestamp with time zone", False),
    },
    INBOX_TABLE: {
        "id": ("varchar(36)", False), "command_id": ("varchar(36)", False),
        "provider_id": ("varchar(64)", False), "account_id": ("varchar(64)", False),
        "event_id": ("varchar(128)", False), "sequence": ("bigint", False),
        "payload_hash": ("varchar(64)", False), "payload": ("jsonb", False),
        "received_at": ("timestamp with time zone", False),
    },
}

EXPECTED_INDEXES = {
    SNAPSHOT_TABLE: {
        ("trading_rule_snapshots_pkey", True, True, "id"),
        ("uq_trading_rule_snapshot_context", True, False, "tenant_id,program_id,phase,rules_version"),
    },
    COMMAND_TABLE: {
        ("trading_provision_commands_pkey", True, True, "id"),
        ("uq_trading_provision_command_context", True, False, "tenant_id,challenge_id,phase"),
        ("uq_trading_provision_provider_account", True, False, "provider_id,account_id"),
    },
    INBOX_TABLE: {
        ("trading_event_inbox_pkey", True, True, "id"),
        ("uq_trading_event_inbox_event", True, False, "provider_id,account_id,event_id"),
        ("uq_trading_event_inbox_sequence", True, False, "provider_id,account_id,sequence"),
    },
}

TRIGGERS = {
    SNAPSHOT_TABLE: {
        "trading_rule_snapshots_immutable": (27, IMMUTABLE_FUNCTION),
        "trading_rule_snapshots_validate_insert": (7, SNAPSHOT_VALIDATE_FUNCTION),
        "trading_rule_snapshots_no_truncate": (34, IMMUTABLE_FUNCTION),
    },
    COMMAND_TABLE: {
        "trading_provision_commands_transition": (27, COMMAND_TRANSITION_FUNCTION),
        "trading_provision_commands_validate_insert": (7, COMMAND_VALIDATE_FUNCTION),
        "trading_provision_commands_no_truncate": (34, IMMUTABLE_FUNCTION),
    },
    INBOX_TABLE: {
        "trading_event_inbox_immutable": (27, IMMUTABLE_FUNCTION),
        "trading_event_inbox_validate_insert": (7, INBOX_VALIDATE_FUNCTION),
        "trading_event_inbox_no_truncate": (34, IMMUTABLE_FUNCTION),
    },
}

# PostgreSQL public relation names include tables and indexes backing PK/UNIQUE constraints.
OWNED_RELATIONS = frozenset({
    SNAPSHOT_TABLE, "trading_rule_snapshots_pkey", "uq_trading_rule_snapshot_context",
    COMMAND_TABLE, "trading_provision_commands_pkey", "uq_trading_provision_command_context",
    "uq_trading_provision_provider_account", INBOX_TABLE, "trading_event_inbox_pkey",
    "uq_trading_event_inbox_event", "uq_trading_event_inbox_sequence",
})

PARENT_COLUMNS = {
    "tenants": {"id": ("integer", False)},
    # Historical owners are nullable in the legacy schema.  The insert validators
    # still reject a NULL/mismatched owner for every new protocol row.
    "trading_programs": {"id": ("integer", False), "tenant_id": ("integer", None)},
    "challenges": {"id": ("integer", False), "user_id": ("integer", False), "program_id": ("integer", False)},
    "users": {"id": ("integer", False), "tenant_id": ("integer", None)},
}


def _normalised_type(type_) -> str:
    rendered = str(type_.compile(dialect=postgresql.dialect())).lower()
    return " ".join(rendered.replace("character varying", "varchar").split())


def _normalised_check(expression: str) -> str:
    value = "".join(str(expression).lower().split())
    value = re.sub(r"'([0-9]+)'::bigint", r"\1", value)
    value = value.replace("::text[]", "").replace("::character varying", "").replace("::charactervarying", "").replace("::text", "")
    value = re.sub(r"=any\(array\[([^]]*)\]\)", r"in(\1)", value)
    return value.replace('"', '').replace("(", "").replace(")", "")


def _public_relation_names(bind) -> set[str]:
    return set(bind.execute(sa.text("""
        SELECT relation.relname FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
    """)).scalars())


def _function_rows(bind, name: str):
    return bind.execute(sa.text("""
        SELECT procedure.oid, pg_get_function_identity_arguments(procedure.oid) AS signature,
               procedure.prorettype::regtype::text AS return_type, procedure.prokind,
               language.lanname AS language, procedure.prosrc, procedure.provolatile,
               procedure.proisstrict, procedure.prosecdef, procedure.proleakproof,
               procedure.proparallel, procedure.proconfig, procedure.proacl
        FROM pg_proc AS procedure
        JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
        JOIN pg_language AS language ON language.oid = procedure.prolang
        WHERE namespace.nspname = 'public' AND procedure.proname = :name
        ORDER BY procedure.oid
    """), {"name": name}).mappings().all()


def _parent_shape_errors(bind) -> list[str]:
    inspector = sa.inspect(bind)
    errors: list[str] = []
    for table, expected in PARENT_COLUMNS.items():
        relation = bind.execute(sa.text("""
            SELECT relation.relkind FROM pg_class AS relation
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = 'public' AND relation.relname = :table
        """), {"table": table}).scalar()
        if relation not in ("r", "p"):
            errors.append(table)
            continue
        columns = {row["name"]: row for row in inspector.get_columns(table, schema="public")}
        for name, (type_name, nullable) in expected.items():
            column = columns.get(name)
            if (column is None or _normalised_type(column["type"]) != type_name
                    or (nullable is not None and column["nullable"] is not nullable)):
                errors.append(f"{table}.{name}")
        primary = inspector.get_pk_constraint(table, schema="public")
        if primary.get("constrained_columns") != ["id"]:
            errors.append(f"{table}.id")
    return errors


def _preflight_upgrade() -> None:
    if context.is_offline_mode():
        return
    bind = op.get_bind()
    collisions = sorted(OWNED_RELATIONS & _public_relation_names(bind))
    functions = {name: _function_rows(bind, name) for name in FUNCTION_BODIES}
    parents = _parent_shape_errors(bind)
    if collisions or any(functions.values()) or parents:
        detail: list[str] = []
        if collisions:
            detail.append("public relations: " + ", ".join(collisions))
        for name, rows in functions.items():
            if rows:
                detail.append("public functions: " + ", ".join(f"public.{name}({row['signature']})" for row in rows))
        if parents:
            detail.append("invalid FK targets: " + ", ".join(parents))
        raise RuntimeError("Trading protocol schema collision before DDL: " + "; ".join(detail))


def _table_oid_or_error(bind, table: str) -> int:
    row = bind.execute(sa.text("""
        SELECT relation.oid, relation.relkind FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public' AND relation.relname = :table
    """), {"table": table}).mappings().first()
    if row is None or row["relkind"] != "r":
        raise RuntimeError("Trading protocol downgrade refuses partial ownership: " + table)
    return int(row["oid"])


def _owned_index_rows(bind, table_oid: int):
    return bind.execute(sa.text("""
        SELECT index_relation.relname AS name, index_meta.indisunique AS is_unique,
               index_meta.indisprimary AS is_primary, index_meta.indpred IS NULL AS no_predicate,
               index_meta.indexprs IS NULL AS no_expressions,
               array_to_string(array_agg(attribute.attname ORDER BY key_part.ordinality), ',') AS columns,
               array_to_string(index_meta.indoption, ',') AS options
        FROM pg_index AS index_meta
        JOIN pg_class AS index_relation ON index_relation.oid = index_meta.indexrelid
        LEFT JOIN LATERAL unnest(index_meta.indkey) WITH ORDINALITY AS key_part(attnum, ordinality) ON true
        LEFT JOIN pg_attribute AS attribute ON attribute.attrelid = index_meta.indrelid AND attribute.attnum = key_part.attnum
        WHERE index_meta.indrelid = :oid
        GROUP BY index_relation.relname, index_meta.indisunique, index_meta.indisprimary,
                 index_meta.indpred, index_meta.indexprs, index_meta.indoption
    """), {"oid": table_oid}).mappings().all()


def _function_ownership_error(bind, name: str, body: str) -> tuple[int | None, str | None]:
    rows = _function_rows(bind, name)
    if len(rows) != 1:
        return None, "public." + name
    row = rows[0]
    if (row["signature"] != "" or row["return_type"] != "trigger" or row["prokind"] != "f"
            or row["language"] != "plpgsql" or row["prosrc"].strip() != body.strip()
            or row["provolatile"] != "v" or row["proisstrict"] or row["prosecdef"]
            or row["proleakproof"] or row["proparallel"] != "u" or row["proconfig"] is not None
            or row["proacl"] is not None):
        return int(row["oid"]), "public." + name
    return int(row["oid"]), None


def _ownership_errors(bind, oids: dict[str, int]) -> list[str]:
    inspector = sa.inspect(bind)
    errors: list[str] = []
    function_oids: dict[str, int | None] = {}
    for name, body in FUNCTION_BODIES.items():
        function_oids[name], error = _function_ownership_error(bind, name, body)
        if error:
            errors.append(error)
    trigger_oids: dict[str, set[int]] = {name: set() for name in FUNCTION_BODIES}
    owned_oid_csv = ", ".join(str(oid) for oid in oids.values())
    for table, oid in oids.items():
        columns = {row["name"]: row for row in inspector.get_columns(table, schema="public")}
        if set(columns) != set(EXPECTED_COLUMNS[table]):
            errors.append(table + ".columns")
        for name, (type_name, nullable) in EXPECTED_COLUMNS[table].items():
            item = columns.get(name)
            if item is not None and (_normalised_type(item["type"]) != type_name or item["nullable"] is not nullable or item["default"] is not None):
                errors.append(f"{table}.{name}")
        primary = inspector.get_pk_constraint(table, schema="public")
        if primary.get("name") != table + "_pkey" or primary.get("constrained_columns") != ["id"]:
            errors.append(table + ".primary_key")
        fks = {row["name"]: row for row in inspector.get_foreign_keys(table, schema="public")}
        if set(fks) != set(FOREIGN_KEYS[table]):
            errors.append(table + ".foreign_keys")
        for name, (column, parent) in FOREIGN_KEYS[table].items():
            item = fks.get(name)
            if item is not None and (item.get("constrained_columns") != [column] or item.get("referred_table") != parent or item.get("referred_columns") != ["id"] or item.get("referred_schema") not in (None, "public") or item.get("options")):
                errors.append(f"{table}.{name}")
        uniques = {row["name"]: row for row in inspector.get_unique_constraints(table, schema="public")}
        if set(uniques) != set(UNIQUE_CONSTRAINTS[table]):
            errors.append(table + ".unique_constraints")
        for name, expected in UNIQUE_CONSTRAINTS[table].items():
            if name in uniques and uniques[name].get("column_names") != expected:
                errors.append(f"{table}.{name}")
        checks = {row["name"]: row for row in inspector.get_check_constraints(table, schema="public")}
        if set(checks) != set(CHECKS[table]):
            errors.append(table + ".check_constraints")
        for name, expected in CHECKS[table].items():
            if name in checks and _normalised_check(checks[name].get("sqltext", "")) != _normalised_check(expected):
                errors.append(f"{table}.{name}")
        index_rows = _owned_index_rows(bind, oid)
        if any(not row["no_predicate"] or not row["no_expressions"] or row["options"] not in ("0", "0,0", "0,0,0", "0,0,0,0") for row in index_rows):
            errors.append(table + ".unowned_index_definition")
        if {(row["name"], row["is_unique"], row["is_primary"], row["columns"]) for row in index_rows} != EXPECTED_INDEXES[table]:
            errors.append(table + ".indexes")
        rows = bind.execute(sa.text("""
            SELECT trigger.oid, trigger.tgname, trigger.tgtype, trigger.tgenabled, trigger.tgfoid,
                   trigger.tgqual IS NULL AS no_when, trigger.tgnargs
            FROM pg_trigger AS trigger WHERE trigger.tgrelid = :oid AND NOT trigger.tgisinternal
        """), {"oid": oid}).mappings().all()
        trigger_map = {row["tgname"]: row for row in rows}
        if set(trigger_map) != set(TRIGGERS[table]):
            errors.append(table + ".triggers")
        else:
            for name, (tgtype, function_name) in TRIGGERS[table].items():
                item = trigger_map[name]
                function_oid = function_oids[function_name]
                if (item["tgtype"] != tgtype or item["tgenabled"] != "O" or not item["no_when"]
                        or item["tgnargs"] != 0 or function_oid is None or int(item["tgfoid"]) != function_oid):
                    errors.append(f"{table}.{name}")
                else:
                    trigger_oids[function_name].add(int(item["oid"]))
        external = bind.execute(sa.text(f"""
            SELECT conname FROM pg_constraint
            WHERE contype = 'f' AND confrelid = :oid AND conrelid NOT IN ({owned_oid_csv})
        """), {"oid": oid}).scalars().all()
        if external:
            errors.append(table + ".external_foreign_keys")
        views = bind.execute(sa.text("""
            SELECT DISTINCT dependent_relation.relname
            FROM pg_depend AS dependency
            JOIN pg_rewrite AS rewrite_rule ON rewrite_rule.oid = dependency.objid AND dependency.classid = 'pg_rewrite'::regclass
            JOIN pg_class AS dependent_relation ON dependent_relation.oid = rewrite_rule.ev_class
            WHERE dependency.refobjid = :oid AND dependent_relation.oid <> :oid
        """), {"oid": oid}).scalars().all()
        if views:
            errors.append(table + ".view_dependents")
    for name, function_oid in function_oids.items():
        if function_oid is None:
            continue
        dependent = bind.execute(sa.text("""
            SELECT trigger.oid FROM pg_depend AS dependency
            JOIN pg_trigger AS trigger ON trigger.oid = dependency.objid AND dependency.classid = 'pg_trigger'::regclass
            WHERE dependency.refobjid = :oid
        """), {"oid": function_oid}).scalars().all()
        if set(map(int, dependent)) != trigger_oids[name]:
            errors.append("public." + name + ".dependents")
    return sorted(set(errors))


def _preflight_downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("20261011_000008 offline downgrade is unsupported; an online data and ownership preflight is required")
    bind = op.get_bind()
    oids = {table: _table_oid_or_error(bind, table) for table in TABLES}
    bind.execute(sa.text("SET LOCAL lock_timeout = '3s'"))
    bind.execute(sa.text("SET LOCAL statement_timeout = '5s'"))
    bind.execute(sa.text("LOCK TABLE public.trading_rule_snapshots, public.trading_provision_commands, public.trading_event_inbox IN ACCESS EXCLUSIVE MODE"))
    nonempty = [table for table in TABLES if bind.execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM public.{table} LIMIT 1)")).scalar_one()]
    if nonempty:
        raise RuntimeError("Trading protocol downgrade refuses to delete synthetic protocol evidence: " + ", ".join(nonempty))
    errors = _ownership_errors(bind, oids)
    if errors:
        raise RuntimeError("Trading protocol downgrade refuses changed ownership metadata before DDL: " + ", ".join(errors))


def _create_functions_and_triggers() -> None:
    for name, body in FUNCTION_BODIES.items():
        op.execute(f"CREATE FUNCTION public.{name}() RETURNS trigger LANGUAGE plpgsql AS $function$\n{body}\n$function$")
    for table in (SNAPSHOT_TABLE, INBOX_TABLE):
        op.execute(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.{IMMUTABLE_FUNCTION}()")
        op.execute(f"CREATE TRIGGER {table}_validate_insert BEFORE INSERT ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.{SNAPSHOT_VALIDATE_FUNCTION if table == SNAPSHOT_TABLE else INBOX_VALIDATE_FUNCTION}()")
        op.execute(f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON public.{table} FOR EACH STATEMENT EXECUTE FUNCTION public.{IMMUTABLE_FUNCTION}()")
    op.execute(f"CREATE TRIGGER trading_provision_commands_transition BEFORE UPDATE OR DELETE ON public.{COMMAND_TABLE} FOR EACH ROW EXECUTE FUNCTION public.{COMMAND_TRANSITION_FUNCTION}()")
    op.execute(f"CREATE TRIGGER trading_provision_commands_validate_insert BEFORE INSERT ON public.{COMMAND_TABLE} FOR EACH ROW EXECUTE FUNCTION public.{COMMAND_VALIDATE_FUNCTION}()")
    op.execute(f"CREATE TRIGGER trading_provision_commands_no_truncate BEFORE TRUNCATE ON public.{COMMAND_TABLE} FOR EACH STATEMENT EXECUTE FUNCTION public.{IMMUTABLE_FUNCTION}()")


def upgrade() -> None:
    _preflight_upgrade()
    op.create_table(
        SNAPSHOT_TABLE,
        sa.Column("id", sa.String(64), nullable=False), sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("program_id", sa.Integer(), nullable=False), sa.Column("phase", sa.Integer(), nullable=False),
        sa.Column("rules_version", sa.String(64), nullable=False), sa.Column("rules_digest", sa.String(64), nullable=False),
        sa.Column("canonical_rules", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source", sa.String(16), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="trading_rule_snapshots_pkey"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_trading_rule_snapshots_tenant"),
        sa.ForeignKeyConstraint(["program_id"], ["trading_programs.id"], name="fk_trading_rule_snapshots_program"),
        sa.UniqueConstraint("tenant_id", "program_id", "phase", "rules_version", name="uq_trading_rule_snapshot_context"),
        *(sa.CheckConstraint(expression, name=name) for name, expression in CHECKS[SNAPSHOT_TABLE].items()),
    )
    op.create_table(
        COMMAND_TABLE,
        sa.Column("id", sa.String(36), nullable=False), sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("challenge_id", sa.Integer(), nullable=False), sa.Column("phase", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.String(64), nullable=False), sa.Column("rule_snapshot_id", sa.String(64), nullable=False),
        sa.Column("source", sa.String(16), nullable=False), sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempt_token", sa.String(36), nullable=True), sa.Column("account_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="trading_provision_commands_pkey"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_trading_provision_commands_tenant"),
        sa.ForeignKeyConstraint(["challenge_id"], ["challenges.id"], name="fk_trading_provision_commands_challenge"),
        sa.ForeignKeyConstraint(["rule_snapshot_id"], [f"{SNAPSHOT_TABLE}.id"], name="fk_trading_provision_commands_snapshot"),
        sa.UniqueConstraint("tenant_id", "challenge_id", "phase", name="uq_trading_provision_command_context"),
        sa.UniqueConstraint("provider_id", "account_id", name="uq_trading_provision_provider_account"),
        *(sa.CheckConstraint(expression, name=name) for name, expression in CHECKS[COMMAND_TABLE].items()),
    )
    op.create_table(
        INBOX_TABLE,
        sa.Column("id", sa.String(36), nullable=False), sa.Column("command_id", sa.String(36), nullable=False),
        sa.Column("provider_id", sa.String(64), nullable=False), sa.Column("account_id", sa.String(64), nullable=False),
        sa.Column("event_id", sa.String(128), nullable=False), sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False), sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="trading_event_inbox_pkey"),
        sa.ForeignKeyConstraint(["command_id"], [f"{COMMAND_TABLE}.id"], name="fk_trading_event_inbox_command"),
        sa.UniqueConstraint("provider_id", "account_id", "event_id", name="uq_trading_event_inbox_event"),
        sa.UniqueConstraint("provider_id", "account_id", "sequence", name="uq_trading_event_inbox_sequence"),
        *(sa.CheckConstraint(expression, name=name) for name, expression in CHECKS[INBOX_TABLE].items()),
    )
    _create_functions_and_triggers()


def downgrade() -> None:
    _preflight_downgrade()
    for table, triggers in TRIGGERS.items():
        for name in triggers:
            op.execute(f"DROP TRIGGER {name} ON public.{table}")
    for name in reversed(tuple(FUNCTION_BODIES)):
        op.execute(f"DROP FUNCTION public.{name}()")
    op.drop_table(INBOX_TABLE)
    op.drop_table(COMMAND_TABLE)
    op.drop_table(SNAPSHOT_TABLE)
