"""Create immutable purchase-quote snapshots without payment or entitlement effects.

Revision ID: 20261011_000006
Revises: 20261011_000005

This frozen migration creates only the ``purchase_orders`` quote snapshot table.
It does not create payments, ledger entries, wallets, entitlements, provider records,
or any account/permission changes.  Application mapper events can reject ORM updates,
but the PostgreSQL trigger below is the authoritative protection for direct and bulk
SQL UPDATE/DELETE operations as well.

Online upgrade rejects every public relation/function collision before any DDL.  An
online downgrade is deliberately data preserving: it rejects populated tables and any
missing, replaced, or externally extended owned metadata before it drops the trigger,
function, or empty table.  Offline downgrade cannot make those proofs and emits no
SQL.
"""
from __future__ import annotations

from alembic import context, op
import re
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20261011_000006"
down_revision = "20261011_000005"
branch_labels = None
depends_on = None


# Frozen source constants only.  This migration never imports application models.
TABLE_NAME = "purchase_orders"
FUNCTION_NAME = "marketedgepros_purchase_orders_immutable"
TRIGGER_NAME = "purchase_orders_immutable"

FOREIGN_KEYS = {
    "fk_purchase_orders_user_id_users": ("user_id", "users"),
    "fk_purchase_orders_tenant_id_tenants": ("tenant_id", "tenants"),
    "fk_purchase_orders_program_id_trading_programs": ("program_id", "trading_programs"),
}

CHECKS = {
    "ck_purchase_orders_amount": "amount_minor > 0 AND amount_minor <= 9999999999",
    "ck_purchase_orders_currency": "currency = 'USD'",
    "ck_purchase_orders_state": "state = 'quoted'",
    "ck_purchase_orders_hash_length": "length(request_hash) = 64 AND length(snapshot_hash) = 64",
}

# PostgreSQL creates the primary-key and unique-constraint backing indexes with these
# names.  They share pg_class's namespace with tables, sequences, views, and indexes.
OWNED_RELATIONS = frozenset({
    TABLE_NAME,
    "purchase_orders_pkey",
    "uq_purchase_orders_user_key",
    "ix_purchase_orders_user_created",
    "ix_purchase_orders_tenant",
})

EXPECTED_COLUMNS = {
    "id": ("varchar(36)", False),
    "user_id": ("integer", False),
    "tenant_id": ("integer", False),
    "program_id": ("integer", False),
    "idempotency_key": ("varchar(128)", False),
    "request_hash": ("varchar(64)", False),
    "snapshot_hash": ("varchar(64)", False),
    "snapshot_json": ("text", False),
    "amount_minor": ("bigint", False),
    "currency": ("varchar(3)", False),
    "state": ("varchar(20)", False),
    "created_at": ("timestamp without time zone", False),
}

EXPECTED_INDEXES = {
    ("purchase_orders_pkey", True, True, "id"),
    ("uq_purchase_orders_user_key", True, False, "user_id,idempotency_key"),
    ("ix_purchase_orders_user_created", False, False, "user_id,created_at"),
    ("ix_purchase_orders_tenant", False, False, "tenant_id"),
}

FUNCTION_BODY = """BEGIN
    RAISE EXCEPTION 'purchase_orders are immutable';
END;"""


def _normalised_type(type_) -> str:
    """Compare PostgreSQL type spellings without treating aliases as drift."""
    rendered = str(type_.compile(dialect=postgresql.dialect())).lower()
    return " ".join(rendered.replace("character varying", "varchar").split())


def _normalised_check(expression: str) -> str:
    """Normalise PostgreSQL's harmless check-expression parentheses/whitespace."""
    normalised = "".join(str(expression).lower().split())
    # PostgreSQL renders a BIGINT comparison literal as '999'::bigint on some
    # server/driver combinations even when the frozen DDL used numeric syntax.
    normalised = re.sub(r"'([0-9]+)'::bigint", r"\1", normalised)
    return (
        normalised
        .replace("::character varying", "")
        .replace("::text", "")
        .replace('"', "")
        .replace("(", "")
        .replace(")", "")
    )


def _public_relation_names(bind) -> set[str]:
    return set(bind.execute(sa.text("""
        SELECT relation.relname
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
    """)).scalars())


def _function_rows(bind):
    """Find every public overload; any one is an unowned collision on upgrade."""
    return bind.execute(sa.text("""
        SELECT procedure.oid,
               pg_get_function_identity_arguments(procedure.oid) AS signature,
               procedure.prorettype::regtype::text AS return_type,
               procedure.prokind,
               language.lanname AS language,
               procedure.prosrc,
               procedure.provolatile,
               procedure.proisstrict,
               procedure.prosecdef,
               procedure.proleakproof,
               procedure.proparallel,
               procedure.proconfig,
               procedure.proacl
        FROM pg_proc AS procedure
        JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
        JOIN pg_language AS language ON language.oid = procedure.prolang
        WHERE namespace.nspname = 'public'
          AND procedure.proname = :function_name
        ORDER BY procedure.oid
    """), {"function_name": FUNCTION_NAME}).mappings().all()


def _parent_shape_errors(bind) -> list[str]:
    """Ensure the frozen FK targets are the expected legacy integer primary keys."""
    rows = bind.execute(sa.text("""
        SELECT relation.relname,
               relation.relkind,
               attribute.atttypid::regtype::text AS type_name,
               attribute.attnotnull
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        LEFT JOIN pg_attribute AS attribute
          ON attribute.attrelid = relation.oid
         AND attribute.attname = 'id'
         AND attribute.attnum > 0
         AND NOT attribute.attisdropped
        WHERE namespace.nspname = 'public'
          AND relation.relname IN ('users', 'tenants', 'trading_programs')
    """)).mappings().all()
    actual = {row["relname"]: row for row in rows}
    errors: list[str] = []
    for parent in ("users", "tenants", "trading_programs"):
        row = actual.get(parent)
        if row is None or row["relkind"] not in ("r", "p"):
            errors.append(parent)
        elif row["type_name"] != "integer" or not row["attnotnull"]:
            errors.append(parent + ".id")
    return errors


def _preflight_upgrade() -> None:
    """Reject all relation/function/parent collisions before the first DDL."""
    if context.is_offline_mode():
        # SQL generation has no catalog to inspect.  The live path remains
        # fail-closed and checks every object before it creates the table.
        return

    bind = op.get_bind()
    collisions = sorted(OWNED_RELATIONS & _public_relation_names(bind))
    functions = _function_rows(bind)
    parent_errors = _parent_shape_errors(bind)
    if collisions or functions or parent_errors:
        details: list[str] = []
        if collisions:
            details.append("public relations: " + ", ".join(collisions))
        if functions:
            signatures = [f"public.{FUNCTION_NAME}({row['signature']})" for row in functions]
            details.append("public functions: " + ", ".join(signatures))
        if parent_errors:
            details.append("invalid FK targets: " + ", ".join(parent_errors))
        raise RuntimeError("Purchase order schema collision before DDL: " + "; ".join(details))


def _table_oid_or_error(bind) -> int:
    row = bind.execute(sa.text("""
        SELECT relation.oid, relation.relkind
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public' AND relation.relname = :table_name
    """), {"table_name": TABLE_NAME}).mappings().first()
    if row is None or row["relkind"] != "r":
        raise RuntimeError("Purchase order downgrade refuses partial ownership: purchase_orders")
    return int(row["oid"])


def _owned_index_rows(bind, table_oid: int):
    """Return all local indexes, including primary/unique backing indexes."""
    return bind.execute(sa.text("""
        SELECT index_relation.relname AS name,
               index_meta.indisunique AS is_unique,
               index_meta.indisprimary AS is_primary,
               index_meta.indpred IS NULL AS has_no_predicate,
               index_meta.indexprs IS NULL AS has_no_expressions,
               array_to_string(
                   array_agg(attribute.attname ORDER BY key_part.ordinality), ','
               ) AS columns,
               array_to_string(index_meta.indoption, ',') AS options
        FROM pg_index AS index_meta
        JOIN pg_class AS index_relation ON index_relation.oid = index_meta.indexrelid
        LEFT JOIN LATERAL unnest(index_meta.indkey) WITH ORDINALITY
            AS key_part(attnum, ordinality) ON true
        LEFT JOIN pg_attribute AS attribute
            ON attribute.attrelid = index_meta.indrelid
           AND attribute.attnum = key_part.attnum
        WHERE index_meta.indrelid = :table_oid
        GROUP BY index_relation.relname, index_meta.indisunique, index_meta.indisprimary,
                 index_meta.indpred, index_meta.indexprs, index_meta.indoption
        ORDER BY index_relation.relname
    """), {"table_oid": table_oid}).mappings().all()


def _ownership_errors(bind, table_oid: int) -> list[str]:
    """Validate every object this revision will implicitly or explicitly remove."""
    inspector = sa.inspect(bind)
    errors: list[str] = []

    columns = {column["name"]: column for column in inspector.get_columns(TABLE_NAME, schema="public")}
    if set(columns) != set(EXPECTED_COLUMNS):
        errors.append("purchase_orders.columns")
    for name, (expected_type, expected_nullable) in EXPECTED_COLUMNS.items():
        actual = columns.get(name)
        if actual is None:
            continue
        if (_normalised_type(actual["type"]) != expected_type
                or actual["nullable"] is not expected_nullable
                or actual["default"] is not None):
            errors.append("purchase_orders." + name)

    primary_key = inspector.get_pk_constraint(TABLE_NAME, schema="public")
    if (primary_key.get("name") != "purchase_orders_pkey"
            or primary_key.get("constrained_columns") != ["id"]):
        errors.append("purchase_orders.purchase_orders_pkey")

    foreign_keys = {foreign_key["name"]: foreign_key for foreign_key in inspector.get_foreign_keys(TABLE_NAME, schema="public")}
    if set(foreign_keys) != set(FOREIGN_KEYS):
        errors.append("purchase_orders.foreign_keys")
    for name, (column, parent) in FOREIGN_KEYS.items():
        actual = foreign_keys.get(name)
        if actual is None:
            continue
        if (actual.get("constrained_columns") != [column]
                or actual.get("referred_table") != parent
                or actual.get("referred_columns") != ["id"]
                or actual.get("referred_schema") not in (None, "public")
                or actual.get("options")):
            errors.append("purchase_orders." + name)

    unique_constraints = {
        constraint["name"]: constraint
        for constraint in inspector.get_unique_constraints(TABLE_NAME, schema="public")
    }
    expected_unique = {"uq_purchase_orders_user_key"}
    if set(unique_constraints) != expected_unique:
        errors.append("purchase_orders.unique_constraints")
    elif unique_constraints["uq_purchase_orders_user_key"].get("column_names") != ["user_id", "idempotency_key"]:
        errors.append("purchase_orders.uq_purchase_orders_user_key")

    checks = {check["name"]: check for check in inspector.get_check_constraints(TABLE_NAME, schema="public")}
    if set(checks) != set(CHECKS):
        errors.append("purchase_orders.check_constraints")
    for name, expression in CHECKS.items():
        actual = checks.get(name)
        if actual is not None and _normalised_check(actual.get("sqltext", "")) != _normalised_check(expression):
            errors.append("purchase_orders." + name)

    index_rows = _owned_index_rows(bind, table_oid)
    if any(not row['has_no_predicate'] or not row['has_no_expressions']
           or row['options'] not in ('0', '0,0') for row in index_rows):
        errors.append('purchase_orders.unowned_index_definition')
    indexes = {
        (
            row["name"], row["is_unique"], row["is_primary"], row["columns"]
        )
        for row in index_rows
    }
    if indexes != EXPECTED_INDEXES:
        errors.append("purchase_orders.indexes")

    functions = _function_rows(bind)
    if len(functions) != 1:
        errors.append("public." + FUNCTION_NAME)
        function_oid = None
    else:
        function = functions[0]
        function_oid = int(function["oid"])
        if (
            function["signature"] != ""
            or function["return_type"] != "trigger"
            or function["prokind"] != "f"
            or function["language"] != "plpgsql"
            or function["prosrc"].strip() != FUNCTION_BODY.strip()
            or function["provolatile"] != "v"
            or function["proisstrict"]
            or function["prosecdef"]
            or function["proleakproof"]
            or function["proparallel"] != "u"
            or function["proconfig"] is not None
            or function["proacl"] is not None
        ):
            errors.append("public." + FUNCTION_NAME)

    triggers = bind.execute(sa.text("""
        SELECT trigger.oid, trigger.tgname, trigger.tgtype, trigger.tgenabled, trigger.tgfoid,
               trigger.tgqual IS NULL AS has_no_when_predicate
        FROM pg_trigger AS trigger
        WHERE trigger.tgrelid = :table_oid AND NOT trigger.tgisinternal
        ORDER BY trigger.tgname
    """), {"table_oid": table_oid}).mappings().all()
    if len(triggers) != 1:
        errors.append("purchase_orders.triggers")
    else:
        trigger = triggers[0]
        if (trigger["tgname"] != TRIGGER_NAME
                or trigger["tgtype"] != 27  # BEFORE + ROW + UPDATE + DELETE
                or trigger["tgenabled"] != "O"
                or not trigger["has_no_when_predicate"]
                or function_oid is None
                or int(trigger["tgfoid"]) != function_oid):
            errors.append("purchase_orders." + TRIGGER_NAME)

    # A later foreign key, trigger, or view may make DROP TABLE/FUNCTION fail after
    # partial cleanup.  Treat those dependencies as unowned rather than dropping them.
    external_fks = bind.execute(sa.text("""
        SELECT constraint_name.conname
        FROM pg_constraint AS constraint_name
        WHERE constraint_name.contype = 'f'
          AND constraint_name.confrelid = :table_oid
          AND constraint_name.conrelid <> :table_oid
    """), {"table_oid": table_oid}).scalars().all()
    if external_fks:
        errors.append("purchase_orders.external_foreign_keys")

    if function_oid is not None and triggers:
        expected_trigger_oid = int(triggers[0]["oid"])
        function_dependents = bind.execute(sa.text("""
            SELECT trigger.oid
            FROM pg_depend AS dependency
            JOIN pg_trigger AS trigger
              ON trigger.oid = dependency.objid
             AND dependency.classid = 'pg_trigger'::regclass
            WHERE dependency.refobjid = :function_oid
        """), {"function_oid": function_oid}).scalars().all()
        if set(map(int, function_dependents)) != {expected_trigger_oid}:
            errors.append("public." + FUNCTION_NAME + ".dependents")

    view_dependents = bind.execute(sa.text("""
        SELECT DISTINCT dependent_relation.relname
        FROM pg_depend AS dependency
        JOIN pg_rewrite AS rewrite_rule
          ON rewrite_rule.oid = dependency.objid
         AND dependency.classid = 'pg_rewrite'::regclass
        JOIN pg_class AS dependent_relation ON dependent_relation.oid = rewrite_rule.ev_class
        WHERE dependency.refobjid = :table_oid
          AND dependent_relation.oid <> :table_oid
    """), {"table_oid": table_oid}).scalars().all()
    if view_dependents:
        errors.append("purchase_orders.view_dependents")

    return sorted(set(errors))


def _preflight_downgrade() -> None:
    """Prove no quote data or changed ownership exists before any destructive DDL."""
    if context.is_offline_mode():
        raise RuntimeError(
            "20261011_000006 offline downgrade is unsupported; "
            "an online data and ownership preflight is required"
        )

    bind = op.get_bind()
    table_oid = _table_oid_or_error(bind)
    # This gate intentionally comes before dropping the trigger: direct SQL must
    # never obtain a migration-created chance to bypass quote immutability.
    if bind.execute(sa.text("SELECT EXISTS (SELECT 1 FROM public.purchase_orders LIMIT 1)")).scalar_one():
        raise RuntimeError(
            "Purchase order downgrade refuses to delete immutable quote snapshots"
        )

    errors = _ownership_errors(bind, table_oid)
    if errors:
        raise RuntimeError(
            "Purchase order downgrade refuses changed ownership metadata before DDL: "
            + ", ".join(errors)
        )


def upgrade() -> None:
    _preflight_upgrade()

    op.create_table(
        TABLE_NAME,
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("program_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_purchase_orders_user_id_users"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], name="fk_purchase_orders_tenant_id_tenants"),
        sa.ForeignKeyConstraint(
            ["program_id"], ["trading_programs.id"], name="fk_purchase_orders_program_id_trading_programs"
        ),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_purchase_orders_user_key"),
        sa.CheckConstraint(CHECKS["ck_purchase_orders_amount"], name="ck_purchase_orders_amount"),
        sa.CheckConstraint(CHECKS["ck_purchase_orders_currency"], name="ck_purchase_orders_currency"),
        sa.CheckConstraint(CHECKS["ck_purchase_orders_state"], name="ck_purchase_orders_state"),
        sa.CheckConstraint(CHECKS["ck_purchase_orders_hash_length"], name="ck_purchase_orders_hash_length"),
    )
    op.create_index("ix_purchase_orders_user_created", TABLE_NAME, ["user_id", "created_at"], unique=False)
    op.create_index("ix_purchase_orders_tenant", TABLE_NAME, ["tenant_id"], unique=False)
    op.execute(f"""
        CREATE FUNCTION public.{FUNCTION_NAME}()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $function$
{FUNCTION_BODY}
$function$
    """)
    op.execute(f"""
        CREATE TRIGGER {TRIGGER_NAME}
        BEFORE UPDATE OR DELETE ON public.{TABLE_NAME}
        FOR EACH ROW EXECUTE FUNCTION public.{FUNCTION_NAME}()
    """)


def downgrade() -> None:
    _preflight_downgrade()

    # The data gate above runs while the immutable trigger is still active.
    op.execute(f"DROP TRIGGER {TRIGGER_NAME} ON public.{TABLE_NAME}")
    op.execute(f"DROP FUNCTION public.{FUNCTION_NAME}()")
    op.drop_table(TABLE_NAME)
