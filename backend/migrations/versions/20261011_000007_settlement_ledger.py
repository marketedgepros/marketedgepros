"""Create the append-only synthetic receipt settlement ledger.

Revision ID: 20261011_000007
Revises: 20261011_000006

This frozen migration is deliberately limited to internal operational bookkeeping.
It creates receipt evidence, a matching journal, and two balancing clearing lines; it
creates no provider integration, public payment endpoint, wallet, entitlement, refund,
or investment transaction.  The PostgreSQL constraint triggers, rather than mapper
hooks, are authoritative for final transaction consistency and direct SQL immutability.

Online upgrade rejects every public relation/function collision before its first DDL.
Online downgrade rejects data and every ownership drift before any destructive DDL.
Offline downgrade emits no DROP SQL because it cannot prove either property.
"""
from __future__ import annotations

import re

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20261011_000007"
down_revision = "20261011_000006"
branch_labels = None
depends_on = None


# Frozen source constants only.  This migration never imports application models.
RECEIPT_TABLE = "payment_event_receipts"
JOURNAL_TABLE = "settlement_journals"
ENTRY_TABLE = "settlement_entries"
TABLES = (RECEIPT_TABLE, JOURNAL_TABLE, ENTRY_TABLE)

IMMUTABLE_FUNCTION = "marketedgepros_settlement_ledger_immutable"
VALIDATE_FUNCTION = "marketedgepros_settlement_ledger_validate"
FUNCTION_NAMES = (IMMUTABLE_FUNCTION, VALIDATE_FUNCTION)

IMMUTABLE_TRIGGERS = {
    RECEIPT_TABLE: "payment_event_receipts_immutable",
    JOURNAL_TABLE: "settlement_journals_immutable",
    ENTRY_TABLE: "settlement_entries_immutable",
}
VALIDATE_TRIGGERS = {
    RECEIPT_TABLE: "payment_event_receipts_validate_complete",
    JOURNAL_TABLE: "settlement_journals_validate_complete",
    ENTRY_TABLE: "settlement_entries_validate_complete",
}

FOREIGN_KEYS = {
    RECEIPT_TABLE: {"fk_receipt_order": ("order_id", "purchase_orders")},
    JOURNAL_TABLE: {
        "fk_journal_receipt": ("receipt_id", RECEIPT_TABLE),
        "fk_journal_order": ("order_id", "purchase_orders"),
    },
    ENTRY_TABLE: {"fk_entry_journal": ("journal_id", JOURNAL_TABLE)},
}

CHECKS = {
    RECEIPT_TABLE: {
        "ck_receipt_amount": "amount_minor > 0 AND amount_minor <= 9999999999",
        "ck_receipt_currency": "currency = 'USD'",
        "ck_receipt_hash": "length(payload_hash) = 64",
    },
    JOURNAL_TABLE: {
        "ck_journal_amount": "amount_minor > 0 AND amount_minor <= 9999999999",
        "ck_journal_currency": "currency = 'USD'",
    },
    ENTRY_TABLE: {
        "ck_entry_line": "line_number IN (1, 2)",
        "ck_entry_amount": "amount_minor > 0 AND amount_minor <= 9999999999",
        "ck_entry_account": "(line_number = 1 AND side = 'debit' AND account_code = 'provider_clearing') OR "
                            "(line_number = 2 AND side = 'credit' AND account_code = 'unapplied_order_receipts')",
    },
}

UNIQUE_CONSTRAINTS = {
    RECEIPT_TABLE: {"uq_payment_event_identity": ["source", "merchant_context", "event_key"]},
    JOURNAL_TABLE: {
        "uq_journal_receipt": ["receipt_id"],
        "uq_journal_order": ["order_id"],
    },
    ENTRY_TABLE: {"uq_journal_line": ["journal_id", "line_number"]},
}

EXPECTED_COLUMNS = {
    RECEIPT_TABLE: {
        "id": ("varchar(36)", False),
        "source": ("varchar(64)", False),
        "merchant_context": ("varchar(128)", False),
        "event_key": ("varchar(128)", False),
        "order_id": ("varchar(36)", False),
        "amount_minor": ("bigint", False),
        "currency": ("varchar(3)", False),
        "payload_hash": ("varchar(64)", False),
        "created_at": ("timestamp without time zone", False),
    },
    JOURNAL_TABLE: {
        "id": ("varchar(36)", False),
        "receipt_id": ("varchar(36)", False),
        "order_id": ("varchar(36)", False),
        "amount_minor": ("bigint", False),
        "currency": ("varchar(3)", False),
        "created_at": ("timestamp without time zone", False),
    },
    ENTRY_TABLE: {
        "id": ("varchar(36)", False),
        "journal_id": ("varchar(36)", False),
        "line_number": ("integer", False),
        "account_code": ("varchar(64)", False),
        "side": ("varchar(6)", False),
        "amount_minor": ("bigint", False),
    },
}

# PostgreSQL creates primary/unique backing indexes in pg_class's public namespace.
OWNED_RELATIONS = frozenset({
    RECEIPT_TABLE,
    "payment_event_receipts_pkey",
    "uq_payment_event_identity",
    "ix_receipt_order",
    JOURNAL_TABLE,
    "settlement_journals_pkey",
    "uq_journal_receipt",
    "uq_journal_order",
    ENTRY_TABLE,
    "settlement_entries_pkey",
    "uq_journal_line",
    "ix_entry_journal",
})

EXPECTED_INDEXES = {
    RECEIPT_TABLE: {
        ("payment_event_receipts_pkey", True, True, "id"),
        ("uq_payment_event_identity", True, False, "source,merchant_context,event_key"),
        ("ix_receipt_order", False, False, "order_id"),
    },
    JOURNAL_TABLE: {
        ("settlement_journals_pkey", True, True, "id"),
        ("uq_journal_receipt", True, False, "receipt_id"),
        ("uq_journal_order", True, False, "order_id"),
    },
    ENTRY_TABLE: {
        ("settlement_entries_pkey", True, True, "id"),
        ("uq_journal_line", True, False, "journal_id,line_number"),
        ("ix_entry_journal", False, False, "journal_id"),
    },
}

IMMUTABLE_FUNCTION_BODY = """BEGIN
    RAISE EXCEPTION 'settlement ledger rows are immutable';
END;"""

# The function is intentionally stateless: every deferred invocation reads the final
# constrained table set at SET CONSTRAINTS/transaction end, then derives one receipt.
VALIDATE_FUNCTION_BODY = """DECLARE
    v_receipt_id varchar(36);
    v_receipt public.payment_event_receipts%ROWTYPE;
    v_journal public.settlement_journals%ROWTYPE;
    v_order_amount bigint;
    v_order_currency varchar(3);
    v_entry_count integer;
    v_debit_total bigint;
    v_credit_total bigint;
BEGIN
    IF TG_TABLE_NAME = 'payment_event_receipts' THEN
        v_receipt_id := NEW.id;
    ELSIF TG_TABLE_NAME = 'settlement_journals' THEN
        v_receipt_id := NEW.receipt_id;
    ELSIF TG_TABLE_NAME = 'settlement_entries' THEN
        SELECT journal.receipt_id INTO v_receipt_id
        FROM public.settlement_journals AS journal
        WHERE journal.id = NEW.journal_id;
    ELSE
        RAISE EXCEPTION 'unexpected settlement ledger trigger table: %', TG_TABLE_NAME;
    END IF;

    SELECT receipt.* INTO v_receipt
    FROM public.payment_event_receipts AS receipt
    WHERE receipt.id = v_receipt_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'settlement ledger receipt is missing';
    END IF;

    SELECT journal.* INTO v_journal
    FROM public.settlement_journals AS journal
    WHERE journal.receipt_id = v_receipt.id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'payment event receipt requires one settlement journal';
    END IF;

    IF v_journal.order_id <> v_receipt.order_id
       OR v_journal.amount_minor <> v_receipt.amount_minor
       OR v_journal.currency <> v_receipt.currency THEN
        RAISE EXCEPTION 'settlement journal must match its receipt order, amount, and currency';
    END IF;

    SELECT purchase_order.amount_minor, purchase_order.currency
      INTO v_order_amount, v_order_currency
    FROM public.purchase_orders AS purchase_order
    WHERE purchase_order.id = v_receipt.order_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'settlement ledger purchase order is missing';
    END IF;

    IF v_journal.amount_minor <> v_order_amount
       OR v_journal.currency <> v_order_currency THEN
        RAISE EXCEPTION 'settlement journal must match its purchase order amount and currency';
    END IF;

    SELECT count(*)::integer,
           COALESCE(sum(CASE WHEN entry.side = 'debit' THEN entry.amount_minor ELSE 0 END), 0),
           COALESCE(sum(CASE WHEN entry.side = 'credit' THEN entry.amount_minor ELSE 0 END), 0)
      INTO v_entry_count, v_debit_total, v_credit_total
    FROM public.settlement_entries AS entry
    WHERE entry.journal_id = v_journal.id;

    IF v_entry_count <> 2
       OR v_debit_total <> v_journal.amount_minor
       OR v_credit_total <> v_journal.amount_minor THEN
        RAISE EXCEPTION 'settlement journal requires exactly two balanced entries';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM public.settlement_entries AS entry
        WHERE entry.journal_id = v_journal.id
          AND entry.line_number = 1
          AND entry.account_code = 'provider_clearing'
          AND entry.side = 'debit'
          AND entry.amount_minor = v_journal.amount_minor
    ) OR NOT EXISTS (
        SELECT 1 FROM public.settlement_entries AS entry
        WHERE entry.journal_id = v_journal.id
          AND entry.line_number = 2
          AND entry.account_code = 'unapplied_order_receipts'
          AND entry.side = 'credit'
          AND entry.amount_minor = v_journal.amount_minor
    ) THEN
        RAISE EXCEPTION 'settlement journal entries must use the canonical clearing accounts';
    END IF;

    RETURN NEW;
END;"""


# The model's historical parent is deliberately verified before frozen FKs are made.
PARENT_COLUMNS = {
    "id": ("varchar(36)", False),
    "amount_minor": ("bigint", False),
    "currency": ("varchar(3)", False),
}


def _normalised_type(type_) -> str:
    rendered = str(type_.compile(dialect=postgresql.dialect())).lower()
    return " ".join(rendered.replace("character varying", "varchar").split())


def _normalised_check(expression: str) -> str:
    normalised = "".join(str(expression).lower().split())
    normalised = re.sub(r"'([0-9]+)'::bigint", r"\1", normalised)
    # PostgreSQL renders ``IN (1, 2)`` as ``= ANY (ARRAY[1, 2])`` in catalog
    # definitions.  They are the same frozen finite line-number predicate.
    normalised = normalised.replace("=any(array[1,2])", "in(1,2)")
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


def _function_rows(bind, function_name: str):
    """Find every public overload; any one collides with this frozen revision."""
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
    """), {"function_name": function_name}).mappings().all()


def _parent_shape_errors(bind) -> list[str]:
    """Ensure purchase_orders remains the frozen direct source of the three FKs."""
    row = bind.execute(sa.text("""
        SELECT relation.oid, relation.relkind
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public' AND relation.relname = 'purchase_orders'
    """)).mappings().first()
    if row is None or row["relkind"] not in ("r", "p"):
        return ["purchase_orders"]

    inspector = sa.inspect(bind)
    columns = {item["name"]: item for item in inspector.get_columns("purchase_orders", schema="public")}
    errors: list[str] = []
    for name, (expected_type, expected_nullable) in PARENT_COLUMNS.items():
        actual = columns.get(name)
        if (actual is None
                or _normalised_type(actual["type"]) != expected_type
                or actual["nullable"] is not expected_nullable):
            errors.append("purchase_orders." + name)
    primary_key = inspector.get_pk_constraint("purchase_orders", schema="public")
    if primary_key.get("name") != "purchase_orders_pkey" or primary_key.get("constrained_columns") != ["id"]:
        errors.append("purchase_orders.purchase_orders_pkey")
    return errors


def _preflight_upgrade() -> None:
    """Reject all conflicts before the first CREATE/ALTER operation."""
    if context.is_offline_mode():
        # Static offline SQL remains usable; only live catalogs can prove collisions.
        return

    bind = op.get_bind()
    collisions = sorted(OWNED_RELATIONS & _public_relation_names(bind))
    function_collisions = {
        name: _function_rows(bind, name) for name in FUNCTION_NAMES
    }
    parent_errors = _parent_shape_errors(bind)
    if collisions or any(function_collisions.values()) or parent_errors:
        details: list[str] = []
        if collisions:
            details.append("public relations: " + ", ".join(collisions))
        for name, rows in function_collisions.items():
            if rows:
                signatures = [f"public.{name}({row['signature']})" for row in rows]
                details.append("public functions: " + ", ".join(signatures))
        if parent_errors:
            details.append("invalid FK target: " + ", ".join(parent_errors))
        raise RuntimeError("Settlement ledger schema collision before DDL: " + "; ".join(details))


def _table_oid_or_error(bind, table_name: str) -> int:
    row = bind.execute(sa.text("""
        SELECT relation.oid, relation.relkind
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public' AND relation.relname = :table_name
    """), {"table_name": table_name}).mappings().first()
    if row is None or row["relkind"] != "r":
        raise RuntimeError("Settlement ledger downgrade refuses partial ownership: " + table_name)
    return int(row["oid"])


def _owned_index_rows(bind, table_oid: int):
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


def _function_ownership_error(bind, function_name: str, expected_body: str) -> tuple[int | None, str | None]:
    rows = _function_rows(bind, function_name)
    if len(rows) != 1:
        return None, "public." + function_name
    function = rows[0]
    if (
        function["signature"] != ""
        or function["return_type"] != "trigger"
        or function["prokind"] != "f"
        or function["language"] != "plpgsql"
        or function["prosrc"].strip() != expected_body.strip()
        or function["provolatile"] != "v"
        or function["proisstrict"]
        or function["prosecdef"]
        or function["proleakproof"]
        or function["proparallel"] != "u"
        or function["proconfig"] is not None
        or function["proacl"] is not None
    ):
        return int(function["oid"]), "public." + function_name
    return int(function["oid"]), None


def _ownership_errors(bind, table_oids: dict[str, int]) -> list[str]:
    """Validate every object this revision would remove, before removing any object."""
    inspector = sa.inspect(bind)
    errors: list[str] = []

    function_oids: dict[str, int | None] = {}
    for name, body in ((IMMUTABLE_FUNCTION, IMMUTABLE_FUNCTION_BODY), (VALIDATE_FUNCTION, VALIDATE_FUNCTION_BODY)):
        function_oid, error = _function_ownership_error(bind, name, body)
        function_oids[name] = function_oid
        if error:
            errors.append(error)

    trigger_oids_by_function: dict[str, set[int]] = {name: set() for name in FUNCTION_NAMES}
    for table_name, table_oid in table_oids.items():
        columns = {column["name"]: column for column in inspector.get_columns(table_name, schema="public")}
        if set(columns) != set(EXPECTED_COLUMNS[table_name]):
            errors.append(table_name + ".columns")
        for name, (expected_type, expected_nullable) in EXPECTED_COLUMNS[table_name].items():
            actual = columns.get(name)
            if actual is None:
                continue
            if (_normalised_type(actual["type"]) != expected_type
                    or actual["nullable"] is not expected_nullable
                    or actual["default"] is not None):
                errors.append(table_name + "." + name)

        primary_key = inspector.get_pk_constraint(table_name, schema="public")
        if (primary_key.get("name") != table_name + "_pkey"
                or primary_key.get("constrained_columns") != ["id"]):
            errors.append(table_name + "." + table_name + "_pkey")

        foreign_keys = {
            foreign_key["name"]: foreign_key
            for foreign_key in inspector.get_foreign_keys(table_name, schema="public")
        }
        if set(foreign_keys) != set(FOREIGN_KEYS[table_name]):
            errors.append(table_name + ".foreign_keys")
        for name, (column, parent) in FOREIGN_KEYS[table_name].items():
            actual = foreign_keys.get(name)
            if actual is None:
                continue
            if (actual.get("constrained_columns") != [column]
                    or actual.get("referred_table") != parent
                    or actual.get("referred_columns") != ["id"]
                    or actual.get("referred_schema") not in (None, "public")
                    or actual.get("options")):
                errors.append(table_name + "." + name)

        unique_constraints = {
            constraint["name"]: constraint
            for constraint in inspector.get_unique_constraints(table_name, schema="public")
        }
        if set(unique_constraints) != set(UNIQUE_CONSTRAINTS[table_name]):
            errors.append(table_name + ".unique_constraints")
        for name, expected_columns in UNIQUE_CONSTRAINTS[table_name].items():
            actual = unique_constraints.get(name)
            if actual is not None and actual.get("column_names") != expected_columns:
                errors.append(table_name + "." + name)

        checks = {
            check["name"]: check
            for check in inspector.get_check_constraints(table_name, schema="public")
        }
        if set(checks) != set(CHECKS[table_name]):
            errors.append(table_name + ".check_constraints")
        for name, expression in CHECKS[table_name].items():
            actual = checks.get(name)
            if actual is not None and _normalised_check(actual.get("sqltext", "")) != _normalised_check(expression):
                errors.append(table_name + "." + name)

        index_rows = _owned_index_rows(bind, table_oid)
        if any(not row["has_no_predicate"] or not row["has_no_expressions"]
               or row["options"] not in ("0", "0,0", "0,0,0") for row in index_rows):
            errors.append(table_name + ".unowned_index_definition")
        indexes = {
            (row["name"], row["is_unique"], row["is_primary"], row["columns"])
            for row in index_rows
        }
        if indexes != EXPECTED_INDEXES[table_name]:
            errors.append(table_name + ".indexes")

        triggers = bind.execute(sa.text("""
            SELECT trigger.oid, trigger.tgname, trigger.tgtype, trigger.tgenabled,
                   trigger.tgfoid, trigger.tgconstraint, trigger.tgdeferrable,
                   trigger.tginitdeferred, trigger.tgnargs,
                   trigger.tgqual IS NULL AS has_no_when_predicate
            FROM pg_trigger AS trigger
            WHERE trigger.tgrelid = :table_oid AND NOT trigger.tgisinternal
            ORDER BY trigger.tgname
        """), {"table_oid": table_oid}).mappings().all()
        if len(triggers) != 3:
            errors.append(table_name + ".triggers")
            continue
        expected = {
            IMMUTABLE_TRIGGERS[table_name]: (27, IMMUTABLE_FUNCTION, False),
            table_name + "_no_truncate": (34, IMMUTABLE_FUNCTION, False),
            VALIDATE_TRIGGERS[table_name]: (5, VALIDATE_FUNCTION, True),
        }
        trigger_map = {row["tgname"]: row for row in triggers}
        if set(trigger_map) != set(expected):
            errors.append(table_name + ".triggers")
            continue
        for trigger_name, (trigger_type, function_name, is_constraint) in expected.items():
            trigger = trigger_map[trigger_name]
            function_oid = function_oids[function_name]
            if (
                trigger["tgtype"] != trigger_type
                or trigger["tgenabled"] != "O"
                or not trigger["has_no_when_predicate"]
                or trigger["tgnargs"] != 0
                or function_oid is None
                or int(trigger["tgfoid"]) != function_oid
                or (int(trigger["tgconstraint"]) != 0) is not is_constraint
                or bool(trigger["tgdeferrable"]) is not is_constraint
                or bool(trigger["tginitdeferred"]) is not is_constraint
            ):
                errors.append(table_name + "." + trigger_name)
            else:
                trigger_oids_by_function[function_name].add(int(trigger["oid"]))

        owned_table_oids = ", ".join(str(table_oids[name]) for name in TABLES)
        external_fks = bind.execute(sa.text(f"""
            SELECT constraint_name.conname
            FROM pg_constraint AS constraint_name
            WHERE constraint_name.contype = 'f'
              AND constraint_name.confrelid = :table_oid
              AND constraint_name.conrelid NOT IN ({owned_table_oids})
        """), {"table_oid": table_oid}).scalars().all()
        if external_fks:
            errors.append(table_name + ".external_foreign_keys")

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
            errors.append(table_name + ".view_dependents")

    for function_name, function_oid in function_oids.items():
        if function_oid is None:
            continue
        dependents = bind.execute(sa.text("""
            SELECT trigger.oid
            FROM pg_depend AS dependency
            JOIN pg_trigger AS trigger
              ON trigger.oid = dependency.objid
             AND dependency.classid = 'pg_trigger'::regclass
            WHERE dependency.refobjid = :function_oid
        """), {"function_oid": function_oid}).scalars().all()
        if set(map(int, dependents)) != trigger_oids_by_function[function_name]:
            errors.append("public." + function_name + ".dependents")

    return sorted(set(errors))


def _preflight_downgrade() -> None:
    """Prove all three tables are empty and exclusively owned before any DROP."""
    if context.is_offline_mode():
        raise RuntimeError(
            "20261011_000007 offline downgrade is unsupported; "
            "an online data and ownership preflight is required"
        )

    bind = op.get_bind()
    # All relations are proven to exist before locks are requested.  The locks stay
    # with Alembic's enclosing transaction through the following non-CASCADE drops,
    # so a concurrent receipt cannot pass the empty check and be deleted afterward.
    table_oids = {table_name: _table_oid_or_error(bind, table_name) for table_name in TABLES}
    bind.execute(sa.text("SET LOCAL lock_timeout = '3s'"))
    bind.execute(sa.text("SET LOCAL statement_timeout = '5s'"))
    bind.execute(sa.text("""
        LOCK TABLE public.payment_event_receipts,
                   public.settlement_journals,
                   public.settlement_entries IN ACCESS EXCLUSIVE MODE
    """))
    # Data is checked while all append-only triggers remain enabled and the owned
    # table set is locked against concurrent inserts for this downgrade transaction.
    nonempty = [
        table_name for table_name in TABLES
        if bind.execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM public.{table_name} LIMIT 1)")).scalar_one()
    ]
    if nonempty:
        raise RuntimeError(
            "Settlement ledger downgrade refuses to delete ledger evidence: " + ", ".join(nonempty)
        )

    errors = _ownership_errors(bind, table_oids)
    if errors:
        raise RuntimeError(
            "Settlement ledger downgrade refuses changed ownership metadata before DDL: "
            + ", ".join(errors)
        )


def _create_functions_and_triggers() -> None:
    op.execute(f"""
        CREATE FUNCTION public.{IMMUTABLE_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $function$
{IMMUTABLE_FUNCTION_BODY}
$function$
    """)
    op.execute(f"""
        CREATE FUNCTION public.{VALIDATE_FUNCTION}()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $function$
{VALIDATE_FUNCTION_BODY}
$function$
    """)
    for table_name in TABLES:
        op.execute(f"""
            CREATE TRIGGER {IMMUTABLE_TRIGGERS[table_name]}
            BEFORE UPDATE OR DELETE ON public.{table_name}
            FOR EACH ROW EXECUTE FUNCTION public.{IMMUTABLE_FUNCTION}()
        """)
        op.execute(f"""
            CREATE CONSTRAINT TRIGGER {VALIDATE_TRIGGERS[table_name]}
            AFTER INSERT ON public.{table_name}
            DEFERRABLE INITIALLY DEFERRED
            FOR EACH ROW EXECUTE FUNCTION public.{VALIDATE_FUNCTION}()
        """)
        op.execute(f"""
            CREATE TRIGGER {table_name}_no_truncate
            BEFORE TRUNCATE ON public.{table_name}
            FOR EACH STATEMENT EXECUTE FUNCTION public.{IMMUTABLE_FUNCTION}()
        """)


def upgrade() -> None:
    _preflight_upgrade()

    op.create_table(
        RECEIPT_TABLE,
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("merchant_context", sa.String(length=128), nullable=False),
        sa.Column("event_key", sa.String(length=128), nullable=False),
        sa.Column("order_id", sa.String(length=36), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="payment_event_receipts_pkey"),
        sa.ForeignKeyConstraint(["order_id"], ["purchase_orders.id"], name="fk_receipt_order"),
        sa.UniqueConstraint("source", "merchant_context", "event_key", name="uq_payment_event_identity"),
        sa.CheckConstraint(CHECKS[RECEIPT_TABLE]["ck_receipt_amount"], name="ck_receipt_amount"),
        sa.CheckConstraint(CHECKS[RECEIPT_TABLE]["ck_receipt_currency"], name="ck_receipt_currency"),
        sa.CheckConstraint(CHECKS[RECEIPT_TABLE]["ck_receipt_hash"], name="ck_receipt_hash"),
    )
    op.create_index("ix_receipt_order", RECEIPT_TABLE, ["order_id"], unique=False)

    op.create_table(
        JOURNAL_TABLE,
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("receipt_id", sa.String(length=36), nullable=False),
        sa.Column("order_id", sa.String(length=36), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="settlement_journals_pkey"),
        sa.ForeignKeyConstraint(["receipt_id"], [f"{RECEIPT_TABLE}.id"], name="fk_journal_receipt"),
        sa.ForeignKeyConstraint(["order_id"], ["purchase_orders.id"], name="fk_journal_order"),
        sa.UniqueConstraint("receipt_id", name="uq_journal_receipt"),
        sa.UniqueConstraint("order_id", name="uq_journal_order"),
        sa.CheckConstraint(CHECKS[JOURNAL_TABLE]["ck_journal_amount"], name="ck_journal_amount"),
        sa.CheckConstraint(CHECKS[JOURNAL_TABLE]["ck_journal_currency"], name="ck_journal_currency"),
    )

    op.create_table(
        ENTRY_TABLE,
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("journal_id", sa.String(length=36), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("account_code", sa.String(length=64), nullable=False),
        sa.Column("side", sa.String(length=6), nullable=False),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="settlement_entries_pkey"),
        sa.ForeignKeyConstraint(["journal_id"], [f"{JOURNAL_TABLE}.id"], name="fk_entry_journal"),
        sa.UniqueConstraint("journal_id", "line_number", name="uq_journal_line"),
        sa.CheckConstraint(CHECKS[ENTRY_TABLE]["ck_entry_line"], name="ck_entry_line"),
        sa.CheckConstraint(CHECKS[ENTRY_TABLE]["ck_entry_amount"], name="ck_entry_amount"),
        sa.CheckConstraint(CHECKS[ENTRY_TABLE]["ck_entry_account"], name="ck_entry_account"),
    )
    op.create_index("ix_entry_journal", ENTRY_TABLE, ["journal_id"], unique=False)
    _create_functions_and_triggers()


def downgrade() -> None:
    _preflight_downgrade()

    # The preflight proves no evidence/dependent metadata can be lost.  No CASCADE
    # is used; child tables are removed before their receipt/order references.
    for table_name in reversed(TABLES):
        op.execute(f"DROP TRIGGER {table_name}_no_truncate ON public.{table_name}")
        op.execute(f"DROP TRIGGER {VALIDATE_TRIGGERS[table_name]} ON public.{table_name}")
        op.execute(f"DROP TRIGGER {IMMUTABLE_TRIGGERS[table_name]} ON public.{table_name}")
    op.execute(f"DROP FUNCTION public.{VALIDATE_FUNCTION}()")
    op.execute(f"DROP FUNCTION public.{IMMUTABLE_FUNCTION}()")
    op.drop_table(ENTRY_TABLE)
    op.drop_table(JOURNAL_TABLE)
    op.drop_table(RECEIPT_TABLE)
