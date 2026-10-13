"""Real PostgreSQL contract tests for NOWPayments checkout storage revision 000002.

The test uses only the staging wrapper's Unix-socket PostgreSQL and synthetic quote
parents.  It never calls provider APIs or opens a network listener.
"""
from __future__ import annotations

from contextlib import contextmanager
import io
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

from src.services.nowpayments_checkout_schema import (
    EXPECTED_COLUMNS,
    FUNCTIONS,
    IMMUTABLE_FUNCTION,
    OWNED_RELATIONS,
    TABLES,
    VALIDATE_FUNCTION,
    CheckoutSchemaValidationError,
    validate_checkout_schema,
)
from test_purchase_order_schema import (
    insert_quote,
    insert_quote_parents,
    purchase_order_database,
    record_schema_ddl,
    upgrade_orders,
)

BACKEND = Path(__file__).resolve().parents[1]
PREVIOUS = "20261013_000001"
REVISION = "20261013_000002"
AT = "2026-10-13 10:00:00+00"


@contextmanager
def checkout_database(resources):
    """Build the real revision-000001 baseline with one synthetic quote parent graph."""
    with purchase_order_database(resources) as (connection, config):
        insert_quote_parents(connection)
        upgrade_orders(connection, config)
        command.upgrade(config, PREVIOUS)
        connection.commit()
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == PREVIOUS
        yield connection, config


def upgrade_checkout(connection, config) -> None:
    command.upgrade(config, REVISION)
    assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == REVISION


def insert_chain(
    connection,
    *,
    tag: str,
    order_id: str,
    receipt_order_id: str | None = None,
    price_amount: str = "499.99",
    pay_amount: str = "1.000000",
    actually_paid: str | None = None,
    receipt_amount: int = 49999,
    grant_policy: str = "np-policy-1",
    with_journal: bool = True,
    with_grant: bool = True,
) -> dict[str, str]:
    """Insert one complete or intentionally malformed chain in one transaction."""
    ids = {kind: f"{kind}-{tag}" for kind in ("intent", "binding", "observation", "receipt", "journal", "grant")}
    receipt_order_id = receipt_order_id or order_id
    actually_paid = actually_paid if actually_paid is not None else pay_amount
    connection.execute(text("""
        INSERT INTO checkout_intents (
            id, order_id, user_id, tenant_id, provider, merchant_context, command_key,
            external_reference, request_digest, pay_currency, network, decimals,
            outcome_currency, policy_version, state, created_at, updated_at,
            dispatch_reserved_at, last_refresh_at
        ) VALUES (
            :id, :order_id, 991001, 991001, 'nowpayments', 'stage-disabled', :command_key,
            :external_reference, :digest, 'usdttrc20', 'TRC20', 6, 'usdttrc20', 'np-policy-1',
            'prepared', :at, :at, NULL, NULL
        )
    """), {"id": ids["intent"], "order_id": order_id, "command_key": "key-" + tag,
            "external_reference": "ref-" + tag, "digest": "a" * 64, "at": AT})
    connection.execute(text("""
        INSERT INTO nowpayments_payment_bindings (
            id, intent_id, order_id, provider, merchant_context, provider_payment_id,
            parent_payment_id, response_digest, price_amount, price_currency, pay_amount,
            pay_currency, network, decimals, pay_address, memo, expires_at, initial_status,
            fee_paid_by_user, created_at
        ) VALUES (
            :id, :intent_id, :order_id, 'nowpayments', 'stage-disabled', :payment_id,
            NULL, :digest, :price_amount, 'USD', :pay_amount, 'usdttrc20', 'TRC20', 6,
            'TNOWPaymentsStagingOnly', NULL, NULL, 'waiting', false, :at
        )
    """), {"id": ids["binding"], "intent_id": ids["intent"], "order_id": order_id,
            "payment_id": "payment-" + tag, "digest": "b" * 64,
            "price_amount": price_amount, "pay_amount": pay_amount, "at": AT})
    connection.execute(text("""
        INSERT INTO nowpayments_observations (
            id, binding_id, order_id, provider_payment_id, payload_digest, source, status,
            review_required, pay_amount, actually_paid, outcome_amount, outcome_currency, created_at
        ) VALUES (
            :id, :binding_id, :order_id, :payment_id, :digest, 'ipn', 'finished', false,
            :pay_amount, :actually_paid, '0.990000', 'usdttrc20', :at
        )
    """), {"id": ids["observation"], "binding_id": ids["binding"], "order_id": order_id,
            "payment_id": "payment-" + tag, "digest": "c" * 64, "pay_amount": pay_amount,
            "actually_paid": actually_paid, "at": AT})
    connection.execute(text("""
        INSERT INTO nowpayments_verified_receipts (
            id, order_id, binding_id, observation_id, amount_minor, currency, source, created_at
        ) VALUES (:id, :order_id, :binding_id, :observation_id, :amount_minor, 'USD', 'nowpayments', :at)
    """), {"id": ids["receipt"], "order_id": receipt_order_id, "binding_id": ids["binding"],
            "observation_id": ids["observation"], "amount_minor": receipt_amount, "at": AT})
    if with_journal:
        connection.execute(text("""
            INSERT INTO nowpayments_settlement_journals (
                id, receipt_id, order_id, amount_minor, currency, created_at
            ) VALUES (:id, :receipt_id, :order_id, :amount_minor, 'USD', :at)
        """), {"id": ids["journal"], "receipt_id": ids["receipt"], "order_id": receipt_order_id,
                "amount_minor": receipt_amount, "at": AT})
        connection.execute(text("""
            INSERT INTO nowpayments_settlement_entries (id, journal_id, line_number, account_code, side, amount_minor)
            VALUES (:id, :journal_id, 1, 'provider_clearing', 'debit', :amount_minor),
                   (:id2, :journal_id, 2, 'unapplied_order_receipts', 'credit', :amount_minor)
        """), {"id": "entry-debit-" + tag, "id2": "entry-credit-" + tag,
                "journal_id": ids["journal"], "amount_minor": receipt_amount})
    if with_grant:
        connection.execute(text("""
            INSERT INTO order_entitlement_grants (
                id, order_id, receipt_id, observation_id, source, policy_version, created_at
            ) VALUES (:id, :order_id, :receipt_id, :observation_id, 'nowpayments', :policy_version, :at)
        """), {"id": ids["grant"], "order_id": receipt_order_id, "receipt_id": ids["receipt"],
                "observation_id": ids["observation"], "policy_version": grant_policy, "at": AT})
    return ids


def test_nowpayments_checkout_migrates_from_001_with_exact_schema_and_empty_down_up(staging_resources):
    with checkout_database(staging_resources) as (connection, config):
        before = set(inspect(connection).get_table_names(schema="public"))
        upgrade_checkout(connection, config)
        inspector = inspect(connection)
        assert set(inspector.get_table_names(schema="public")) - before == set(TABLES)
        assert all(set(column["name"] for column in inspector.get_columns(table, schema="public")) == set(EXPECTED_COLUMNS[table]) for table in TABLES)
        assert all(column["default"] is None for table in TABLES for column in inspector.get_columns(table, schema="public"))
        assert validate_checkout_schema(connection) is True
        assert set(FUNCTIONS) == set(connection.execute(text("""
            SELECT proname FROM pg_proc JOIN pg_namespace ON pg_namespace.oid = pg_proc.pronamespace
            WHERE nspname='public' AND proname = ANY(:names)
        """), {"names": list(FUNCTIONS)}).scalars())
        command.downgrade(config, PREVIOUS)
        assert not set(TABLES).intersection(inspect(connection).get_table_names(schema="public"))
        upgrade_checkout(connection, config)
        assert validate_checkout_schema(connection) is True


def test_nowpayments_checkout_preflight_rejects_index_and_function_overload_before_ddl(staging_resources):
    with checkout_database(staging_resources) as (connection, config):
        connection.execute(text("CREATE INDEX ix_checkout_intents_owner ON purchase_orders (id)"))
        connection.commit()
        with record_schema_ddl(connection) as emitted:
            with pytest.raises(RuntimeError, match="schema collision before DDL"):
                upgrade_checkout(connection, config)
        assert emitted == []
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == PREVIOUS

    with checkout_database(staging_resources) as (connection, config):
        connection.execute(text("""
            CREATE FUNCTION public.marketedgepros_nowpayments_immutable(integer)
            RETURNS integer LANGUAGE sql AS 'SELECT $1'
        """))
        connection.commit()
        with record_schema_ddl(connection) as emitted:
            with pytest.raises(RuntimeError, match="schema collision before DDL"):
                upgrade_checkout(connection, config)
        assert emitted == []
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == PREVIOUS


def test_nowpayments_checkout_downgrade_refuses_metadata_tamper_and_populated_evidence_before_ddl(staging_resources):
    with checkout_database(staging_resources) as (connection, config):
        upgrade_checkout(connection, config)
        connection.execute(text("ALTER TABLE checkout_intents DISABLE TRIGGER checkout_intents_validate_complete"))
        connection.commit()
        with record_schema_ddl(connection) as emitted:
            with pytest.raises(RuntimeError, match="changed ownership metadata"):
                command.downgrade(config, PREVIOUS)
        assert emitted == []

    with checkout_database(staging_resources) as (connection, config):
        upgrade_checkout(connection, config)
        insert_quote(connection, identifier="np-populated", idempotency_key="np-populated")
        connection.commit()
        insert_chain(connection, tag="populated", order_id="np-populated")
        connection.commit()
        with record_schema_ddl(connection) as emitted:
            with pytest.raises(RuntimeError, match="refuses durable evidence"):
                command.downgrade(config, PREVIOUS)
        assert emitted == []


def test_nowpayments_checkout_deferred_chain_rejects_bad_receipt_grant_order_price_quantum_and_orphan(staging_resources):
    with checkout_database(staging_resources) as (connection, config):
        upgrade_checkout(connection, config)
        connection.commit()  # Deliberate deferred-check rollbacks must not roll back the migration DDL.
        for tag, kwargs, expected in (
            ("bad-receipt", {"receipt_amount": 49998}, "receipt must equal immutable USD purchase order"),
            ("bad-grant", {"grant_policy": "other-policy"}, "entitlement grant must match"),
            ("bad-price", {"price_amount": "499.98"}, "binding price or exact deposit quantum"),
            ("bad-quantum", {"pay_amount": "1.0000001", "actually_paid": "1.0000001"}, "binding price or exact deposit quantum"),
            ("orphan", {"with_journal": False, "with_grant": False}, "requires one matching settlement journal"),
        ):
            insert_quote(connection, identifier="order-" + tag, idempotency_key="quote-" + tag)
            insert_chain(connection, tag=tag, order_id="order-" + tag, **kwargs)
            with pytest.raises(DBAPIError, match=expected):
                connection.commit()
            connection.rollback()

        insert_quote(connection, identifier="order-mismatch-a", idempotency_key="quote-mismatch-a")
        insert_quote(connection, identifier="order-mismatch-b", idempotency_key="quote-mismatch-b")
        connection.commit()
        insert_chain(connection, tag="bad-order", order_id="order-mismatch-a", receipt_order_id="order-mismatch-b")
        with pytest.raises(DBAPIError, match="intent must match quoted order owner"):
            connection.commit()
        connection.rollback()


def test_nowpayments_checkout_accepts_balanced_verified_chain_and_blocks_direct_mutation(staging_resources):
    with checkout_database(staging_resources) as (connection, config):
        upgrade_checkout(connection, config)
        insert_quote(connection, identifier="order-good", idempotency_key="quote-good")
        connection.commit()
        ids = insert_chain(connection, tag="good", order_id="order-good")
        connection.commit()
        assert validate_checkout_schema(connection) is True
        assert connection.execute(text("SELECT count(*) FROM nowpayments_settlement_entries")).scalar_one() == 2
        with pytest.raises(DBAPIError, match="immutable"):
            connection.execute(text("UPDATE nowpayments_payment_bindings SET pay_address=pay_address"))
        connection.rollback()
        with pytest.raises(DBAPIError, match="immutable"):
            connection.execute(text("TRUNCATE nowpayments_verified_receipts CASCADE"))
        connection.rollback()
        connection.execute(text("UPDATE checkout_intents SET state='creating', updated_at=:at WHERE id=:id"), {"id": ids["intent"], "at": "2026-10-13 10:00:01+00"})
        connection.execute(text("UPDATE checkout_intents SET state='paid', updated_at=:at WHERE id=:id"), {"id": ids["intent"], "at": "2026-10-13 10:00:02+00"})
        connection.execute(text("UPDATE checkout_intents SET state='manual_review', updated_at=:at WHERE id=:id"), {"id": ids["intent"], "at": "2026-10-13 10:00:03+00"})
        connection.commit()


def test_nowpayments_checkout_schema_helper_fails_closed_on_disabled_trigger(staging_resources):
    with checkout_database(staging_resources) as (connection, config):
        upgrade_checkout(connection, config)
        connection.execute(text("ALTER TABLE nowpayments_settlement_entries DISABLE TRIGGER nowpayments_settlement_entries_validate_complete"))
        connection.commit()
        with pytest.raises(CheckoutSchemaValidationError, match="schema drift"):
            validate_checkout_schema(connection)


def test_nowpayments_checkout_offline_downgrade_emits_no_drop(staging_resources, monkeypatch):
    buffer = io.StringIO()
    config = Config(str(BACKEND / "migrations/alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", staging_resources["pg_url"].replace("%", "%%"))
    config.output_buffer = buffer
    monkeypatch.setenv("TEST_DATABASE_URL", staging_resources["pg_url"])
    with pytest.raises(RuntimeError, match="offline downgrade is unsupported"):
        command.downgrade(config, f"{REVISION}:{PREVIOUS}", sql=True)
    assert "DROP" not in buffer.getvalue().upper()
