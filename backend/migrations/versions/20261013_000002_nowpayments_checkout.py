"""Add disabled-by-default, append-only NOWPayments checkout evidence.

Revision ID: 20261013_000002
Revises: 20261013_000001

The seven tables are deliberately separate from quotes and legacy/synthetic ledger
records.  Upgrade proves every owned relation (including constraint indexes) and
function overload is absent before DDL.  Downgrade is online-only, empty-only, and
requires the full static ownership contract before any non-CASCADE DROP.
"""
from __future__ import annotations

from alembic import context, op
import sqlalchemy as sa

from src.services.nowpayments_checkout_schema import (
    BINDING_TABLE,
    CHECKS,
    ENTRY_TABLE,
    EXPECTED_COLUMNS,
    FOREIGN_KEYS,
    FUNCTIONS,
    GRANT_TABLE,
    IMMUTABLE_FUNCTION,
    IMMUTABLE_FUNCTION_BODY,
    IMMUTABLE_TRIGGERS,
    INTENT_TABLE,
    JOURNAL_TABLE,
    NO_TRUNCATE_TRIGGERS,
    OBSERVATION_TABLE,
    OWNED_RELATIONS,
    RECEIPT_TABLE,
    REVISION,
    SCHEMA,
    TABLES,
    TRANSITION_FUNCTION,
    TRANSITION_FUNCTION_BODY,
    UNIQUE_CONSTRAINTS,
    VALIDATE_FUNCTION,
    VALIDATE_FUNCTION_BODY,
    VALIDATE_TRIGGERS,
    CheckoutSchemaValidationError,
    validate_checkout_schema,
)

revision = REVISION
down_revision = "20261013_000001"
branch_labels = None
depends_on = None

# The migration has no model imports: these are static shapes of its immutable FK
# parents, not metadata inferred at migration execution time.
PARENT_COLUMNS = {
    "purchase_orders": {
        "id": ("varchar(36)", False), "user_id": ("integer", False),
        "tenant_id": ("integer", False), "amount_minor": ("bigint", False),
        "currency": ("varchar(3)", False),
    },
    "users": {"id": ("integer", False)},
    "tenants": {"id": ("integer", False)},
}


def _normalised_type(type_) -> str:
    from sqlalchemy.dialects import postgresql
    return " ".join(str(type_.compile(dialect=postgresql.dialect())).lower().replace("character varying", "varchar").split())


def _function_rows(bind, function_name: str):
    """Return every public overload; any overload is an upgrade collision."""
    return bind.execute(sa.text("""
        SELECT procedure.oid, pg_get_function_identity_arguments(procedure.oid) AS signature
        FROM pg_proc AS procedure
        JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
        WHERE namespace.nspname = :schema AND procedure.proname = :function_name
        ORDER BY procedure.oid
    """), {"schema": SCHEMA, "function_name": function_name}).mappings().all()


def _public_relation_names(bind) -> set[str]:
    return set(bind.execute(sa.text("""
        SELECT relation.relname FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = :schema
    """), {"schema": SCHEMA}).scalars())


def _parent_shape_errors(bind) -> list[str]:
    inspector = sa.inspect(bind)
    errors: list[str] = []
    for table, expected_columns in PARENT_COLUMNS.items():
        relation = bind.execute(sa.text("""
            SELECT relation.relkind FROM pg_class AS relation
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname = :schema AND relation.relname = :table
        """), {"schema": SCHEMA, "table": table}).scalar_one_or_none()
        if relation not in ("r", "p"):
            errors.append(table)
            continue
        columns = {column["name"]: column for column in inspector.get_columns(table, schema=SCHEMA)}
        for name, (type_name, nullable) in expected_columns.items():
            actual = columns.get(name)
            if actual is None or _normalised_type(actual["type"]) != type_name or actual["nullable"] is not nullable:
                errors.append(table + "." + name)
        primary = inspector.get_pk_constraint(table, schema=SCHEMA)
        if primary.get("constrained_columns") != ["id"]:
            errors.append(table + ".primary_key")
    return errors


def _preflight_upgrade() -> None:
    """Reject all relation/function collisions and invalid parents before first DDL."""
    if context.is_offline_mode():
        return
    bind = op.get_bind()
    safe_path = bind.execute(sa.text("""
        SELECT current_schema() = 'public'
           AND current_schemas(false) = ARRAY['public']::name[]
    """)).scalar_one()
    collisions = sorted(OWNED_RELATIONS & _public_relation_names(bind))
    function_collisions = {name: _function_rows(bind, name) for name in FUNCTIONS}
    parent_errors = _parent_shape_errors(bind)
    if safe_path is not True or collisions or any(function_collisions.values()) or parent_errors:
        details: list[str] = []
        if safe_path is not True:
            details.append("unsafe search path")
        if collisions:
            details.append("public relations: " + ", ".join(collisions))
        for name, rows in function_collisions.items():
            if rows:
                details.append("public functions: " + ", ".join(
                    f"public.{name}({row['signature']})" for row in rows
                ))
        if parent_errors:
            details.append("invalid immutable parents: " + ", ".join(parent_errors))
        raise RuntimeError("NOWPayments checkout schema collision before DDL: " + "; ".join(details))


def _external_dependency_errors(bind) -> list[str]:
    errors: list[str] = []
    for table in TABLES:
        external_fks = bind.execute(sa.text("""
            SELECT dependent_relation.relname
            FROM pg_constraint AS constraint_name
            JOIN pg_class AS referenced_relation ON referenced_relation.oid = constraint_name.confrelid
            JOIN pg_class AS dependent_relation ON dependent_relation.oid = constraint_name.conrelid
            JOIN pg_namespace AS namespace ON namespace.oid = dependent_relation.relnamespace
            WHERE constraint_name.contype = 'f' AND namespace.nspname = :schema
              AND referenced_relation.relname = :table AND dependent_relation.relname <> ALL(:owned)
        """), {"schema": SCHEMA, "table": table, "owned": list(TABLES)}).scalars().all()
        if external_fks:
            errors.append(table + ".external_foreign_keys")
        view_dependents = bind.execute(sa.text("""
            SELECT DISTINCT dependent_relation.relname
            FROM pg_depend AS dependency
            JOIN pg_rewrite AS rewrite_rule ON rewrite_rule.oid = dependency.objid
              AND dependency.classid = 'pg_rewrite'::regclass
            JOIN pg_class AS dependent_relation ON dependent_relation.oid = rewrite_rule.ev_class
            WHERE dependency.refobjid = (
                SELECT relation.oid FROM pg_class AS relation
                JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
                WHERE namespace.nspname = :schema AND relation.relname = :table
            )
        """), {"schema": SCHEMA, "table": table}).scalars().all()
        if view_dependents:
            errors.append(table + ".view_dependents")
    return sorted(set(errors))


def _preflight_downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("20261013_000002 offline downgrade is unsupported; online ownership and data proof is required")
    bind = op.get_bind()
    present = bind.execute(sa.text("""
        SELECT relation.relname FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = :schema AND relation.relkind = 'r' AND relation.relname = ANY(:tables)
    """), {"schema": SCHEMA, "tables": list(TABLES)}).scalars().all()
    if set(present) != set(TABLES):
        raise RuntimeError("NOWPayments checkout downgrade refuses partial ownership")
    bind.execute(sa.text("SET LOCAL lock_timeout = '3s'"))
    bind.execute(sa.text("SET LOCAL statement_timeout = '5s'"))
    bind.execute(sa.text("LOCK TABLE " + ", ".join(f"{SCHEMA}.{table}" for table in TABLES) + " IN ACCESS EXCLUSIVE MODE"))
    nonempty = [table for table in TABLES if bind.execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {SCHEMA}.{table} LIMIT 1)")).scalar_one()]
    if nonempty:
        raise RuntimeError("NOWPayments checkout downgrade refuses durable evidence: " + ", ".join(nonempty))
    try:
        validate_checkout_schema(bind)
    except CheckoutSchemaValidationError as exc:
        raise RuntimeError("NOWPayments checkout downgrade refuses changed ownership metadata before DDL: " + str(exc)) from exc
    dependencies = _external_dependency_errors(bind)
    if dependencies:
        raise RuntimeError("NOWPayments checkout downgrade refuses external dependencies: " + ", ".join(dependencies))


def _create_functions_and_triggers() -> None:
    for name, body in (
        (IMMUTABLE_FUNCTION, IMMUTABLE_FUNCTION_BODY),
        (TRANSITION_FUNCTION, TRANSITION_FUNCTION_BODY),
        (VALIDATE_FUNCTION, VALIDATE_FUNCTION_BODY),
    ):
        op.execute(f"""
            CREATE FUNCTION {SCHEMA}.{name}() RETURNS trigger LANGUAGE plpgsql AS $function$
{body}
$function$
        """)
    op.execute(f"""
        CREATE TRIGGER checkout_intents_transition
        BEFORE UPDATE OR DELETE ON {SCHEMA}.{INTENT_TABLE}
        FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.{TRANSITION_FUNCTION}()
    """)
    for table in TABLES:
        if table != INTENT_TABLE:
            op.execute(f"""
                CREATE TRIGGER {IMMUTABLE_TRIGGERS[table]}
                BEFORE UPDATE OR DELETE ON {SCHEMA}.{table}
                FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.{IMMUTABLE_FUNCTION}()
            """)
        op.execute(f"""
            CREATE TRIGGER {NO_TRUNCATE_TRIGGERS[table]}
            BEFORE TRUNCATE ON {SCHEMA}.{table}
            FOR EACH STATEMENT EXECUTE FUNCTION {SCHEMA}.{IMMUTABLE_FUNCTION}()
        """)
        op.execute(f"""
            CREATE CONSTRAINT TRIGGER {VALIDATE_TRIGGERS[table]}
            AFTER INSERT OR UPDATE ON {SCHEMA}.{table}
            DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
            EXECUTE FUNCTION {SCHEMA}.{VALIDATE_FUNCTION}()
        """)


def upgrade() -> None:
    _preflight_upgrade()
    op.create_table(
        INTENT_TABLE,
        sa.Column("id", sa.String(36), nullable=False), sa.Column("order_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False), sa.Column("tenant_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False), sa.Column("merchant_context", sa.String(64), nullable=False),
        sa.Column("command_key", sa.String(128), nullable=False), sa.Column("external_reference", sa.String(96), nullable=False),
        sa.Column("request_digest", sa.String(64), nullable=False), sa.Column("pay_currency", sa.String(32), nullable=False),
        sa.Column("network", sa.String(32), nullable=False), sa.Column("decimals", sa.Integer(), nullable=False),
        sa.Column("outcome_currency", sa.String(32), nullable=False), sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("state", sa.String(24), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False), sa.Column("dispatch_reserved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_refresh_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="checkout_intents_pkey"),
        sa.ForeignKeyConstraint(["order_id"], ["public.purchase_orders.id"], name="fk_checkout_intents_order"),
        sa.ForeignKeyConstraint(["user_id"], ["public.users.id"], name="fk_checkout_intents_user"),
        sa.ForeignKeyConstraint(["tenant_id"], ["public.tenants.id"], name="fk_checkout_intents_tenant"),
        *(sa.UniqueConstraint(*columns, name=name) for name, columns in UNIQUE_CONSTRAINTS[INTENT_TABLE].items()),
        *(sa.CheckConstraint(expression, name=name) for name, expression in CHECKS[INTENT_TABLE].items()), schema=SCHEMA,
    )
    op.create_index("ix_checkout_intents_owner", INTENT_TABLE, ["user_id", "tenant_id", "created_at"], schema=SCHEMA)
    op.create_table(
        BINDING_TABLE,
        sa.Column("id", sa.String(36), nullable=False), sa.Column("intent_id", sa.String(36), nullable=False), sa.Column("order_id", sa.String(36), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False), sa.Column("merchant_context", sa.String(64), nullable=False), sa.Column("provider_payment_id", sa.String(128), nullable=False),
        sa.Column("parent_payment_id", sa.String(128), nullable=True), sa.Column("response_digest", sa.String(64), nullable=False),
        sa.Column("price_amount", sa.String(80), nullable=False), sa.Column("price_currency", sa.String(3), nullable=False), sa.Column("pay_amount", sa.String(80), nullable=False),
        sa.Column("pay_currency", sa.String(32), nullable=False), sa.Column("network", sa.String(32), nullable=False), sa.Column("decimals", sa.Integer(), nullable=False),
        sa.Column("pay_address", sa.String(256), nullable=False), sa.Column("memo", sa.String(128), nullable=True), sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("initial_status", sa.String(24), nullable=False), sa.Column("fee_paid_by_user", sa.Boolean(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="nowpayments_payment_bindings_pkey"),
        sa.ForeignKeyConstraint(["intent_id"], [f"public.{INTENT_TABLE}.id"], name="fk_nowpayments_bindings_intent"),
        sa.ForeignKeyConstraint(["order_id"], ["public.purchase_orders.id"], name="fk_nowpayments_bindings_order"),
        *(sa.UniqueConstraint(*columns, name=name) for name, columns in UNIQUE_CONSTRAINTS[BINDING_TABLE].items()),
        *(sa.CheckConstraint(expression, name=name) for name, expression in CHECKS[BINDING_TABLE].items()), schema=SCHEMA,
    )
    op.create_index("ix_nowpayments_bindings_payment", BINDING_TABLE, ["provider_payment_id"], schema=SCHEMA)
    op.create_table(
        OBSERVATION_TABLE,
        sa.Column("id", sa.String(36), nullable=False), sa.Column("binding_id", sa.String(36), nullable=False), sa.Column("order_id", sa.String(36), nullable=False),
        sa.Column("provider_payment_id", sa.String(128), nullable=False), sa.Column("payload_digest", sa.String(64), nullable=False), sa.Column("source", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False), sa.Column("review_required", sa.Boolean(), nullable=False), sa.Column("pay_amount", sa.String(80), nullable=True),
        sa.Column("actually_paid", sa.String(80), nullable=True), sa.Column("outcome_amount", sa.String(80), nullable=True), sa.Column("outcome_currency", sa.String(32), nullable=True), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="nowpayments_observations_pkey"),
        sa.ForeignKeyConstraint(["binding_id"], [f"public.{BINDING_TABLE}.id"], name="fk_nowpayments_observations_binding"),
        sa.ForeignKeyConstraint(["order_id"], ["public.purchase_orders.id"], name="fk_nowpayments_observations_order"),
        *(sa.UniqueConstraint(*columns, name=name) for name, columns in UNIQUE_CONSTRAINTS[OBSERVATION_TABLE].items()),
        *(sa.CheckConstraint(expression, name=name) for name, expression in CHECKS[OBSERVATION_TABLE].items()), schema=SCHEMA,
    )
    op.create_index("ix_nowpayments_observations_binding_created", OBSERVATION_TABLE, ["binding_id", "created_at"], schema=SCHEMA)
    op.create_table(
        RECEIPT_TABLE,
        sa.Column("id", sa.String(36), nullable=False), sa.Column("order_id", sa.String(36), nullable=False), sa.Column("binding_id", sa.String(36), nullable=False), sa.Column("observation_id", sa.String(36), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False), sa.Column("currency", sa.String(3), nullable=False), sa.Column("source", sa.String(32), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="nowpayments_verified_receipts_pkey"),
        sa.ForeignKeyConstraint(["order_id"], ["public.purchase_orders.id"], name="fk_nowpayments_receipts_order"),
        sa.ForeignKeyConstraint(["binding_id"], [f"public.{BINDING_TABLE}.id"], name="fk_nowpayments_receipts_binding"),
        sa.ForeignKeyConstraint(["observation_id"], [f"public.{OBSERVATION_TABLE}.id"], name="fk_nowpayments_receipts_observation"),
        *(sa.UniqueConstraint(*columns, name=name) for name, columns in UNIQUE_CONSTRAINTS[RECEIPT_TABLE].items()),
        *(sa.CheckConstraint(expression, name=name) for name, expression in CHECKS[RECEIPT_TABLE].items()), schema=SCHEMA,
    )
    op.create_table(
        JOURNAL_TABLE,
        sa.Column("id", sa.String(36), nullable=False), sa.Column("receipt_id", sa.String(36), nullable=False), sa.Column("order_id", sa.String(36), nullable=False), sa.Column("amount_minor", sa.BigInteger(), nullable=False), sa.Column("currency", sa.String(3), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="nowpayments_settlement_journals_pkey"),
        sa.ForeignKeyConstraint(["receipt_id"], [f"public.{RECEIPT_TABLE}.id"], name="fk_nowpayments_journals_receipt"),
        sa.ForeignKeyConstraint(["order_id"], ["public.purchase_orders.id"], name="fk_nowpayments_journals_order"),
        *(sa.UniqueConstraint(*columns, name=name) for name, columns in UNIQUE_CONSTRAINTS[JOURNAL_TABLE].items()),
        *(sa.CheckConstraint(expression, name=name) for name, expression in CHECKS[JOURNAL_TABLE].items()), schema=SCHEMA,
    )
    op.create_table(
        ENTRY_TABLE,
        sa.Column("id", sa.String(36), nullable=False), sa.Column("journal_id", sa.String(36), nullable=False), sa.Column("line_number", sa.Integer(), nullable=False), sa.Column("account_code", sa.String(64), nullable=False), sa.Column("side", sa.String(6), nullable=False), sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="nowpayments_settlement_entries_pkey"),
        sa.ForeignKeyConstraint(["journal_id"], [f"public.{JOURNAL_TABLE}.id"], name="fk_nowpayments_entries_journal"),
        *(sa.UniqueConstraint(*columns, name=name) for name, columns in UNIQUE_CONSTRAINTS[ENTRY_TABLE].items()),
        *(sa.CheckConstraint(expression, name=name) for name, expression in CHECKS[ENTRY_TABLE].items()), schema=SCHEMA,
    )
    op.create_table(
        GRANT_TABLE,
        sa.Column("id", sa.String(36), nullable=False), sa.Column("order_id", sa.String(36), nullable=False), sa.Column("receipt_id", sa.String(36), nullable=False), sa.Column("observation_id", sa.String(36), nullable=False), sa.Column("source", sa.String(32), nullable=False), sa.Column("policy_version", sa.String(64), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="order_entitlement_grants_pkey"),
        sa.ForeignKeyConstraint(["order_id"], ["public.purchase_orders.id"], name="fk_order_entitlement_grants_order"),
        sa.ForeignKeyConstraint(["receipt_id"], [f"public.{RECEIPT_TABLE}.id"], name="fk_order_entitlement_grants_receipt"),
        sa.ForeignKeyConstraint(["observation_id"], [f"public.{OBSERVATION_TABLE}.id"], name="fk_order_entitlement_grants_observation"),
        *(sa.UniqueConstraint(*columns, name=name) for name, columns in UNIQUE_CONSTRAINTS[GRANT_TABLE].items()),
        *(sa.CheckConstraint(expression, name=name) for name, expression in CHECKS[GRANT_TABLE].items()), schema=SCHEMA,
    )
    _create_functions_and_triggers()


def downgrade() -> None:
    _preflight_downgrade()
    for table in reversed(TABLES):
        op.execute(f"DROP TRIGGER {VALIDATE_TRIGGERS[table]} ON {SCHEMA}.{table}")
        op.execute(f"DROP TRIGGER {NO_TRUNCATE_TRIGGERS[table]} ON {SCHEMA}.{table}")
        if table == INTENT_TABLE:
            op.execute(f"DROP TRIGGER checkout_intents_transition ON {SCHEMA}.{table}")
        else:
            op.execute(f"DROP TRIGGER {IMMUTABLE_TRIGGERS[table]} ON {SCHEMA}.{table}")
    for name in reversed(FUNCTIONS):
        op.execute(f"DROP FUNCTION {SCHEMA}.{name}()")
    for table in reversed(TABLES):
        op.drop_table(table, schema=SCHEMA)
