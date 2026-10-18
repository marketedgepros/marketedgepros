"""Real PostgreSQL contract tests for frozen settlement-ledger migration 000007 only."""
from __future__ import annotations

import io
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError, IntegrityError

from test_purchase_order_schema import (
    insert_quote,
    insert_quote_parents,
    purchase_order_database,
    record_schema_ddl,
    upgrade_orders,
)


BACKEND = Path(__file__).resolve().parents[1]
PREVIOUS = "20261011_000006"
REVISION = "20261011_000007"
RECEIPT = "payment_event_receipts"
JOURNAL = "settlement_journals"
ENTRY = "settlement_entries"
TABLES = {RECEIPT, JOURNAL, ENTRY}
IMMUTABLE_FUNCTION = "marketedgepros_settlement_ledger_immutable"
VALIDATE_FUNCTION = "marketedgepros_settlement_ledger_validate"

EXPECTED_COLUMNS = {
    RECEIPT: {
        "id": "varchar(36)",
        "source": "varchar(64)",
        "merchant_context": "varchar(128)",
        "event_key": "varchar(128)",
        "order_id": "varchar(36)",
        "amount_minor": "bigint",
        "currency": "varchar(3)",
        "payload_hash": "varchar(64)",
        "created_at": "timestamp without time zone",
    },
    JOURNAL: {
        "id": "varchar(36)",
        "receipt_id": "varchar(36)",
        "order_id": "varchar(36)",
        "amount_minor": "bigint",
        "currency": "varchar(3)",
        "created_at": "timestamp without time zone",
    },
    ENTRY: {
        "id": "varchar(36)",
        "journal_id": "varchar(36)",
        "line_number": "integer",
        "account_code": "varchar(64)",
        "side": "varchar(6)",
        "amount_minor": "bigint",
    },
}

EXPECTED_FKS = {
    RECEIPT: {"fk_receipt_order": ("order_id", "purchase_orders")},
    JOURNAL: {
        "fk_journal_receipt": ("receipt_id", RECEIPT),
        "fk_journal_order": ("order_id", "purchase_orders"),
    },
    ENTRY: {"fk_entry_journal": ("journal_id", JOURNAL)},
}

EXPECTED_UNIQUES = {
    RECEIPT: {"uq_payment_event_identity": ["source", "merchant_context", "event_key"]},
    JOURNAL: {"uq_journal_receipt": ["receipt_id"], "uq_journal_order": ["order_id"]},
    ENTRY: {"uq_journal_line": ["journal_id", "line_number"]},
}

EXPECTED_CHECKS = {
    RECEIPT: {"ck_receipt_amount", "ck_receipt_currency", "ck_receipt_hash"},
    JOURNAL: {"ck_journal_amount", "ck_journal_currency"},
    ENTRY: {"ck_entry_line", "ck_entry_amount", "ck_entry_account"},
}


def _normalised_type(type_) -> str:
    rendered = str(type_.compile(dialect=postgresql.dialect())).lower()
    return " ".join(rendered.replace("character varying", "varchar").split())


def upgrade_ledger(connection, config) -> None:
    command.upgrade(config, REVISION)
    assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == REVISION


def prepare_quote_and_ledger(connection, config, *, order_id: str = "00000000-0000-0000-0000-000000007001") -> str:
    """Reach 000007 from a true 000005 graph with one canonical immutable quote."""
    insert_quote_parents(connection, users=(991001,))
    upgrade_orders(connection, config)
    insert_quote(connection, identifier=order_id, idempotency_key="ledger-" + order_id[-6:])
    connection.commit()
    upgrade_ledger(connection, config)
    return order_id


def insert_receipt(connection, *, receipt_id: str, order_id: str, event_key: str,
                   amount_minor: int = 49999, currency: str = "USD", payload_hash: str | None = None) -> None:
    connection.execute(text("""
        INSERT INTO payment_event_receipts (
            id, source, merchant_context, event_key, order_id, amount_minor,
            currency, payload_hash, created_at
        ) VALUES (
            :id, 'synthetic', 'isolated-tests', :event_key, :order_id, :amount_minor,
            :currency, :payload_hash, CURRENT_TIMESTAMP
        )
    """), {
        "id": receipt_id,
        "event_key": event_key,
        "order_id": order_id,
        "amount_minor": amount_minor,
        "currency": currency,
        "payload_hash": payload_hash or "a" * 64,
    })


def insert_journal(connection, *, journal_id: str, receipt_id: str, order_id: str,
                   amount_minor: int = 49999, currency: str = "USD") -> None:
    connection.execute(text("""
        INSERT INTO settlement_journals (
            id, receipt_id, order_id, amount_minor, currency, created_at
        ) VALUES (
            :id, :receipt_id, :order_id, :amount_minor, :currency, CURRENT_TIMESTAMP
        )
    """), {
        "id": journal_id,
        "receipt_id": receipt_id,
        "order_id": order_id,
        "amount_minor": amount_minor,
        "currency": currency,
    })


def insert_entry(connection, *, entry_id: str, journal_id: str, line_number: int,
                 account_code: str, side: str, amount_minor: int = 49999) -> None:
    connection.execute(text("""
        INSERT INTO settlement_entries (
            id, journal_id, line_number, account_code, side, amount_minor
        ) VALUES (
            :id, :journal_id, :line_number, :account_code, :side, :amount_minor
        )
    """), {
        "id": entry_id,
        "journal_id": journal_id,
        "line_number": line_number,
        "account_code": account_code,
        "side": side,
        "amount_minor": amount_minor,
    })


def insert_complete_ledger(connection, *, suffix: str, order_id: str,
                           amount_minor: int = 49999, journal_order_id: str | None = None,
                           payload_hash: str | None = None) -> tuple[str, str]:
    """Insert the only permitted receipt/journal/two-line shape without committing."""
    receipt_id = f"00000000-0000-0000-0000-00000010{suffix}"
    journal_id = f"00000000-0000-0000-0000-00000020{suffix}"
    insert_receipt(
        connection,
        receipt_id=receipt_id,
        order_id=order_id,
        event_key="event-" + suffix,
        amount_minor=amount_minor,
        payload_hash=payload_hash,
    )
    insert_journal(
        connection,
        journal_id=journal_id,
        receipt_id=receipt_id,
        order_id=journal_order_id or order_id,
        amount_minor=amount_minor,
    )
    insert_entry(
        connection,
        entry_id=f"00000000-0000-0000-0000-00000030{suffix}",
        journal_id=journal_id,
        line_number=1,
        account_code="provider_clearing",
        side="debit",
        amount_minor=amount_minor,
    )
    insert_entry(
        connection,
        entry_id=f"00000000-0000-0000-0000-00000040{suffix}",
        journal_id=journal_id,
        line_number=2,
        account_code="unapplied_order_receipts",
        side="credit",
        amount_minor=amount_minor,
    )
    return receipt_id, journal_id


def test_settlement_ledger_migration_is_static_exact_schema_and_preserves_quote_schema(staging_resources):
    """000007 adds only the three named ledger relations and exact database authorities."""
    source = (BACKEND / "migrations/versions/20261011_000007_settlement_ledger.py").read_text(encoding="utf-8")
    assert "src.models" not in source
    assert "create_all" not in source
    assert "CREATE TABLE IF NOT EXISTS" not in source

    with purchase_order_database(staging_resources) as (connection, config):
        upgrade_orders(connection, config)
        quote_before = {
            column["name"]: (_normalised_type(column["type"]), column["nullable"])
            for column in inspect(connection).get_columns("purchase_orders", schema="public")
        }
        tables_before = set(inspect(connection).get_table_names(schema="public"))
        upgrade_ledger(connection, config)
        inspector = inspect(connection)
        assert set(inspector.get_table_names(schema="public")) - tables_before == TABLES
        assert {
            column["name"]: (_normalised_type(column["type"]), column["nullable"])
            for column in inspector.get_columns("purchase_orders", schema="public")
        } == quote_before

        for table_name in TABLES:
            columns = {column["name"]: column for column in inspector.get_columns(table_name, schema="public")}
            assert set(columns) == set(EXPECTED_COLUMNS[table_name])
            for name, expected_type in EXPECTED_COLUMNS[table_name].items():
                assert _normalised_type(columns[name]["type"]) == expected_type
                assert columns[name]["nullable"] is False
                assert columns[name]["default"] is None
            primary_key = inspector.get_pk_constraint(table_name, schema="public")
            assert primary_key["constrained_columns"] == ["id"]
            assert primary_key["name"] == table_name + "_pkey"
            foreign_keys = {item["name"]: item for item in inspector.get_foreign_keys(table_name, schema="public")}
            assert set(foreign_keys) == set(EXPECTED_FKS[table_name])
            for name, (column, parent) in EXPECTED_FKS[table_name].items():
                assert foreign_keys[name]["constrained_columns"] == [column]
                assert foreign_keys[name]["referred_table"] == parent
                assert foreign_keys[name]["referred_columns"] == ["id"]
                assert foreign_keys[name]["referred_schema"] in (None, "public")
                assert not foreign_keys[name].get("options")
            uniques = {item["name"]: item["column_names"] for item in inspector.get_unique_constraints(table_name, schema="public")}
            assert uniques == EXPECTED_UNIQUES[table_name]
            assert {item["name"] for item in inspector.get_check_constraints(table_name, schema="public")} == EXPECTED_CHECKS[table_name]

        indexes = {
            table_name: {
                item["name"]: (item["column_names"], item["unique"])
                for item in inspector.get_indexes(table_name, schema="public")
                if not item.get("duplicates_constraint")
            }
            for table_name in TABLES
        }
        assert indexes == {
            RECEIPT: {"ix_receipt_order": (["order_id"], False)},
            JOURNAL: {},
            ENTRY: {"ix_entry_journal": (["journal_id"], False)},
        }

        trigger_rows = connection.execute(text("""
            SELECT relation.relname, trigger.tgname, trigger.tgtype, trigger.tgenabled,
                   trigger.tgdeferrable, trigger.tginitdeferred, procedure.proname
            FROM pg_trigger AS trigger
            JOIN pg_class AS relation ON relation.oid = trigger.tgrelid
            JOIN pg_proc AS procedure ON procedure.oid = trigger.tgfoid
            WHERE relation.relname IN ('payment_event_receipts', 'settlement_journals', 'settlement_entries')
              AND NOT trigger.tgisinternal
            ORDER BY relation.relname, trigger.tgname
        """)).all()
        assert trigger_rows == [
            ("payment_event_receipts", "payment_event_receipts_immutable", 27, "O", False, False, IMMUTABLE_FUNCTION),
            ("payment_event_receipts", "payment_event_receipts_no_truncate", 34, "O", False, False, IMMUTABLE_FUNCTION),
            ("payment_event_receipts", "payment_event_receipts_validate_complete", 5, "O", True, True, VALIDATE_FUNCTION),
            ("settlement_entries", "settlement_entries_immutable", 27, "O", False, False, IMMUTABLE_FUNCTION),
            ("settlement_entries", "settlement_entries_no_truncate", 34, "O", False, False, IMMUTABLE_FUNCTION),
            ("settlement_entries", "settlement_entries_validate_complete", 5, "O", True, True, VALIDATE_FUNCTION),
            ("settlement_journals", "settlement_journals_immutable", 27, "O", False, False, IMMUTABLE_FUNCTION),
            ("settlement_journals", "settlement_journals_no_truncate", 34, "O", False, False, IMMUTABLE_FUNCTION),
            ("settlement_journals", "settlement_journals_validate_complete", 5, "O", True, True, VALIDATE_FUNCTION),
        ]


def test_settlement_ledger_deferrable_triggers_accept_a_real_balanced_commit(staging_resources):
    """Only the complete operational clearing pair survives a real PostgreSQL commit."""
    with purchase_order_database(staging_resources) as (connection, config):
        order_id = prepare_quote_and_ledger(connection, config)
        receipt_id, journal_id = insert_complete_ledger(connection, suffix="01", order_id=order_id)
        # This invokes all three deferred constraint trigger rows before commit.
        connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))
        connection.commit()

        receipt = connection.execute(text("""
            SELECT id, source, merchant_context, event_key, order_id, amount_minor, currency, payload_hash
            FROM payment_event_receipts
        """)).one()
        assert tuple(receipt) == (receipt_id, "synthetic", "isolated-tests", "event-01", order_id, 49999, "USD", "a" * 64)
        assert connection.execute(text("""
            SELECT id, receipt_id, order_id, amount_minor, currency FROM settlement_journals
        """)).one() == (journal_id, receipt_id, order_id, 49999, "USD")
        assert connection.execute(text("""
            SELECT line_number, account_code, side, amount_minor
            FROM settlement_entries ORDER BY line_number
        """)).all() == [
            (1, "provider_clearing", "debit", 49999),
            (2, "unapplied_order_receipts", "credit", 49999),
        ]


@pytest.mark.parametrize("kind, expected", [
    ("orphan_receipt", "requires one settlement journal"),
    ("missing_line", "requires exactly two balanced entries"),
    ("wrong_order", "must match its receipt order, amount, and currency"),
    ("wrong_price", "must match its purchase order amount and currency"),
])
def test_settlement_ledger_deferred_database_authority_rejects_final_malformed_state(staging_resources, kind, expected):
    """SET CONSTRAINTS proves malformed final ledger states cannot be committed."""
    with purchase_order_database(staging_resources) as (connection, config):
        order_id = prepare_quote_and_ledger(connection, config)
        if kind == "orphan_receipt":
            insert_receipt(
                connection,
                receipt_id="00000000-0000-0000-0000-000000101001",
                order_id=order_id,
                event_key="orphan",
            )
        elif kind == "missing_line":
            insert_receipt(
                connection,
                receipt_id="00000000-0000-0000-0000-000000101002",
                order_id=order_id,
                event_key="missing-line",
            )
            insert_journal(
                connection,
                journal_id="00000000-0000-0000-0000-000000201002",
                receipt_id="00000000-0000-0000-0000-000000101002",
                order_id=order_id,
            )
            insert_entry(
                connection,
                entry_id="00000000-0000-0000-0000-000000301002",
                journal_id="00000000-0000-0000-0000-000000201002",
                line_number=1,
                account_code="provider_clearing",
                side="debit",
            )
        elif kind == "wrong_order":
            second_order = "00000000-0000-0000-0000-000000007002"
            insert_quote(connection, identifier=second_order, idempotency_key="ledger-second")
            insert_complete_ledger(
                connection,
                suffix="03",
                order_id=order_id,
                journal_order_id=second_order,
            )
        else:
            insert_complete_ledger(connection, suffix="04", order_id=order_id, amount_minor=50000)

        with pytest.raises(DBAPIError, match=expected):
            connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        connection.rollback()
        assert connection.execute(text("SELECT count(*) FROM payment_event_receipts")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM settlement_journals")).scalar_one() == 0
        assert connection.execute(text("SELECT count(*) FROM settlement_entries")).scalar_one() == 0


def test_settlement_ledger_checks_reject_bad_hash_length_and_extra_line(staging_resources):
    """Finite checks prevent a noncanonical receipt hash shape or a third journal line."""
    with purchase_order_database(staging_resources) as (connection, config):
        order_id = prepare_quote_and_ledger(connection, config)
        with pytest.raises(IntegrityError, match="ck_receipt_hash"):
            insert_receipt(
                connection,
                receipt_id="00000000-0000-0000-0000-000000101010",
                order_id=order_id,
                event_key="short-hash",
                payload_hash="a" * 63,
            )
        connection.rollback()

        receipt_id, journal_id = insert_complete_ledger(connection, suffix="10", order_id=order_id)
        # PostgreSQL may report either overlapping finite predicate first; both
        # checks forbid the third line and are asserted exactly in the schema test.
        with pytest.raises(IntegrityError, match="ck_entry_(line|account)"):
            insert_entry(
                connection,
                entry_id="00000000-0000-0000-0000-000000301010",
                journal_id=journal_id,
                line_number=3,
                account_code="provider_clearing",
                side="debit",
            )
        connection.rollback()
        assert connection.execute(text("SELECT count(*) FROM payment_event_receipts")).scalar_one() == 0
        assert receipt_id


def test_settlement_ledger_immutable_triggers_block_direct_bulk_update_and_delete(staging_resources):
    """Direct SQL cannot rewrite or remove receipt evidence, journals, or clearing entries."""
    with purchase_order_database(staging_resources) as (connection, config):
        order_id = prepare_quote_and_ledger(connection, config)
        insert_complete_ledger(connection, suffix="20", order_id=order_id)
        connection.commit()
        for table_name in (RECEIPT, JOURNAL, ENTRY):
            with pytest.raises(DBAPIError, match="settlement ledger rows are immutable"):
                connection.execute(text(f"UPDATE {table_name} SET id = id"))
            connection.rollback()
            with pytest.raises(DBAPIError, match="settlement ledger rows are immutable"):
                connection.execute(text(f"DELETE FROM {table_name}"))
            connection.rollback()
        assert connection.execute(text("SELECT count(*) FROM payment_event_receipts")).scalar_one() == 1
        assert connection.execute(text("SELECT count(*) FROM settlement_journals")).scalar_one() == 1
        assert connection.execute(text("SELECT count(*) FROM settlement_entries")).scalar_one() == 2


@pytest.mark.parametrize("collision", [
    "CREATE TABLE ix_entry_journal (id integer PRIMARY KEY)",
    """CREATE FUNCTION public.marketedgepros_settlement_ledger_validate(ignored integer)
       RETURNS integer LANGUAGE sql AS 'SELECT ignored'""",
])
def test_settlement_ledger_upgrade_refuses_all_owned_collisions_before_ddl(staging_resources, collision):
    """A foreign relation or overload blocks 000007 before it creates any owned object."""
    with purchase_order_database(staging_resources) as (connection, config):
        upgrade_orders(connection, config)
        connection.execute(text(collision))
        connection.commit()
        with record_schema_ddl(connection) as emitted:
            with pytest.raises(RuntimeError, match="Settlement ledger schema collision before DDL"):
                upgrade_ledger(connection, config)
        assert emitted == []
        assert not TABLES.intersection(inspect(connection).get_table_names(schema="public"))
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == PREVIOUS


def test_settlement_ledger_empty_downgrade_reupgrade_and_populated_refusal(staging_resources):
    """Empty owned schema can reverse/reapply; any evidence blocks downgrade before DDL."""
    with purchase_order_database(staging_resources) as (connection, config):
        order_id = prepare_quote_and_ledger(connection, config)
        command.downgrade(config, PREVIOUS)
        assert not TABLES.intersection(inspect(connection).get_table_names(schema="public"))
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == PREVIOUS
        upgrade_ledger(connection, config)
        insert_complete_ledger(connection, suffix="30", order_id=order_id)
        connection.commit()
        with record_schema_ddl(connection) as emitted:
            with pytest.raises(RuntimeError, match="refuses to delete ledger evidence"):
                command.downgrade(config, PREVIOUS)
        assert emitted == []
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == REVISION
        assert connection.execute(text("SELECT count(*) FROM settlement_entries")).scalar_one() == 2


def test_settlement_ledger_offline_downgrade_emits_no_unverified_drop_sql(staging_resources, monkeypatch):
    """Offline SQL cannot prove empty ownership, so this revision stops before DROP."""
    buffer = io.StringIO()
    config = Config(str(BACKEND / "migrations/alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", staging_resources["pg_url"].replace("%", "%%"))
    config.output_buffer = buffer
    monkeypatch.setenv("TEST_DATABASE_URL", staging_resources["pg_url"])
    with pytest.raises(RuntimeError, match="offline downgrade is unsupported"):
        command.downgrade(config, f"{REVISION}:{PREVIOUS}", sql=True)
    assert "DROP" not in buffer.getvalue().upper()


@pytest.mark.parametrize('alteration', [
    'CREATE INDEX foreign_ledger_expression ON settlement_entries ((lower(account_code)))',
    'CREATE INDEX foreign_ledger_partial ON settlement_entries (amount_minor) WHERE amount_minor > 100',
    'ALTER TABLE settlement_entries DISABLE TRIGGER settlement_entries_validate_complete',
    'ALTER TABLE settlement_journals DROP CONSTRAINT uq_journal_order',
    'ALTER TABLE payment_event_receipts DROP CONSTRAINT fk_receipt_order',
])
def test_settlement_ledger_downgrade_refuses_changed_metadata_before_any_drop(staging_resources, alteration):
    with purchase_order_database(staging_resources) as (connection, config):
        upgrade_orders(connection, config)
        upgrade_ledger(connection, config)
        connection.execute(text(alteration))
        connection.commit()
        with record_schema_ddl(connection) as emitted:
            with pytest.raises(RuntimeError, match='changed ownership metadata before DDL'):
                command.downgrade(config, PREVIOUS)
        assert emitted == []
        assert TABLES.issubset(inspect(connection).get_table_names(schema='public'))
        assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == REVISION


def test_settlement_ledger_no_truncate_preserves_all_evidence(staging_resources):
    with purchase_order_database(staging_resources) as (connection, config):
        order_id = prepare_quote_and_ledger(connection, config)
        insert_complete_ledger(connection, suffix='55', order_id=order_id)
        connection.commit()
        with pytest.raises(DBAPIError, match='settlement ledger rows are immutable'):
            connection.execute(text('TRUNCATE payment_event_receipts, settlement_journals, settlement_entries'))
        connection.rollback()
        assert connection.execute(text('SELECT count(*) FROM payment_event_receipts')).scalar_one() == 1
        assert connection.execute(text('SELECT count(*) FROM settlement_journals')).scalar_one() == 1
        assert connection.execute(text('SELECT count(*) FROM settlement_entries')).scalar_one() == 2
