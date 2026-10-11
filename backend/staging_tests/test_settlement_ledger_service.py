"""Isolated PostgreSQL proof for the synthetic receipt/journal service only.

These tests deliberately exercise no HTTP endpoint, provider, wallet, entitlement or
payment-verification flow.  They create a server-priced frozen quote with the real
OrderService, then use only the internal synthetic-ledger rehearsal service.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier
from time import monotonic
from uuid import uuid4
import hashlib
import json

import pytest
from alembic import command
from alembic.config import Config
from flask import Flask
from sqlalchemy import text

from test_order_quote_concurrency import quote_database


LEDGER_HEAD = "20261011_000007"


@contextmanager
def ledger_database(resources, monkeypatch):
    """Reuse the 000006 quote database, then install only real 000007 Alembic DDL.

    No table in this fixture is created with ``create_all``.  The migration is
    intentionally applied through the application engine while inside its context,
    so the service readiness gate sees the exact private PostgreSQL target it will
    use below.
    """
    from src.database import db

    with quote_database(resources, monkeypatch) as app:
        app.config["SYNTHETIC_SETTLEMENT_ENABLED"] = True
        backend = Path(__file__).resolve().parents[1]
        migration_config = Config(str(backend / "migrations" / "alembic.ini"))
        migration_config.set_main_option("script_location", str(backend / "migrations"))
        migration_config.set_main_option(
            "sqlalchemy.url", app.config["SQLALCHEMY_DATABASE_URI"].replace("%", "%%")
        )
        with app.app_context():
            # ``quote_database`` deliberately stops at 000006.  Upgrade the same
            # synthetic database to the frozen ledger revision before importing or
            # touching the ledger models.
            with db.engine.connect() as connection:
                migration_config.attributes["connection"] = connection
                command.upgrade(migration_config, LEDGER_HEAD)
            migration_config.attributes.pop("connection", None)
            db.session.remove()
            assert db.session.execute(text("SELECT version_num FROM public.alembic_version")).scalars().all() == [LEDGER_HEAD]
            # Model import is post-DDL only; it must not manufacture schema.
            from src.models.settlement_ledger import (  # noqa: F401
                PaymentEventReceipt,
                SettlementEntry,
                SettlementJournal,
            )
        yield app


@pytest.fixture
def ledger_app(staging_resources, monkeypatch):
    with ledger_database(staging_resources, monkeypatch) as app:
        yield app


def _ledger_counts():
    """Return exact receipt/journal/line row counts using PostgreSQL SQL."""
    from src.database import db

    return db.session.execute(text("""
        SELECT
            (SELECT count(*) FROM payment_event_receipts),
            (SELECT count(*) FROM settlement_journals),
            (SELECT count(*) FROM settlement_entries)
    """)).one()


def _ledger_rows():
    """Return ledger contents in persistence order rather than ORM count proxies."""
    from src.database import db

    receipts = db.session.execute(text("""
        SELECT id, source, merchant_context, event_key, order_id, amount_minor, currency, payload_hash
        FROM payment_event_receipts ORDER BY id
    """)).all()
    journals = db.session.execute(text("""
        SELECT id, receipt_id, order_id, amount_minor, currency
        FROM settlement_journals ORDER BY id
    """)).all()
    entries = db.session.execute(text("""
        SELECT journal_id, line_number, account_code, side, amount_minor
        FROM settlement_entries ORDER BY journal_id, line_number
    """)).all()
    return receipts, journals, entries


def _create_frozen_quote(app, sequence):
    """Create and commit one real User-2 quote from the synthetic catalog."""
    from src.database import db
    from src.models.user import User
    from src.services.order_service import OrderService

    with app.app_context(), app.test_request_context("/api/v1/orders/"):
        actor = db.session.get(User, 2)
        order, created = OrderService.create_quote(
            actor, {"program_id": 10, "addon_ids": [20]}, f"synthetic_ledger_quote_{sequence:04d}"
        )
        assert created is True
        snapshot = {
            "id": order.id,
            "amount_minor": order.amount_minor,
            "currency": order.currency,
            "snapshot_json": order.snapshot_json,
            "snapshot_hash": order.snapshot_hash,
            "state": order.state,
        }
        db.session.commit()
        db.session.remove()
        return snapshot


def _synthetic_receipt(order, event_key="event_A"):
    """Build a canonical byte payload from the frozen quote, never a client price."""
    payload = {
        "schema": 1,
        "kind": "synthetic_purchase_receipt",
        "order_id": order["id"],
        "amount_minor": order["amount_minor"],
        "currency": order["currency"],
        "quote_snapshot_hash": order["snapshot_hash"],
    }
    synthetic_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return {
        "source": "synthetic",
        "merchant_context": "isolated-tests",
        "event_key": event_key,
        "order_id": order["id"],
        "amount_minor": order["amount_minor"],
        "currency": order["currency"],
        "payload_hash": hashlib.sha256(synthetic_bytes).hexdigest(),
    }


def _empty_valid_receipt(event_key="readiness_event"):
    """A syntactically valid request for gates that must refuse before order lookup."""
    digest = hashlib.sha256(b"isolated-readiness-canary").hexdigest()
    return {
        "source": "synthetic",
        "merchant_context": "isolated-tests",
        "event_key": event_key,
        "order_id": str(uuid4()),
        "amount_minor": 1,
        "currency": "USD",
        "payload_hash": digest,
    }


def _record(data):
    from src.services.settlement_ledger_service import SettlementLedgerService

    return SettlementLedgerService.record_synthetic_receipt(data)


def _run_concurrently(app, bodies):
    """Run service-only contenders, retaining real independent app sessions."""
    from src.database import db
    from src.services.settlement_ledger_service import LedgerError

    barrier = Barrier(len(bodies), timeout=10)

    def worker(body):
        with app.app_context():
            try:
                barrier.wait()
                result = _record(body)
                db.session.commit()
                return ("ok", result.created, result.receipt_id, result.journal_id, result.order_id)
            except LedgerError as error:
                db.session.rollback()
                return ("refused", error.code)
            finally:
                db.session.remove()

    started = monotonic()
    with ThreadPoolExecutor(max_workers=len(bodies)) as executor:
        futures = [executor.submit(worker, body) for body in bodies]
        results = [future.result(timeout=15) for future in futures]
    return monotonic() - started, results


def _ledger_trigger(table_name, deferred):
    """Resolve a ledger (not purchase-order) trigger from the frozen contract."""
    from src.services.settlement_ledger_contract import EXPECTED_TRIGGERS

    matches = [
        item for item in EXPECTED_TRIGGERS.items()
        if item[0][0] == table_name and bool(item[1][1]) is deferred and not item[0][1].endswith("_no_truncate")
    ]
    assert len(matches) == 1, f"expected one canonical trigger for {table_name}"
    return matches[0]


def _qident(identifier):
    return '"' + identifier.replace('"', '""') + '"'


def test_balanced_receipt_creates_exact_evidence_and_keeps_quote_side_effects_zero(ledger_app):
    from src.database import db
    from src.models.purchase_order import PurchaseOrder

    order = _create_frozen_quote(ledger_app, 1)
    data = _synthetic_receipt(order)
    assert data["amount_minor"] == order["amount_minor"]
    assert data["payload_hash"] == hashlib.sha256(json.dumps({
        "schema": 1,
        "kind": "synthetic_purchase_receipt",
        "order_id": order["id"],
        "amount_minor": order["amount_minor"],
        "currency": order["currency"],
        "quote_snapshot_hash": order["snapshot_hash"],
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")).hexdigest()

    with ledger_app.app_context():
        result = _record(data)
        assert result.created is True
        assert result.order_id == order["id"]
        assert result.amount_minor == order["amount_minor"]
        assert result.currency == "USD"
        db.session.commit()

        assert _ledger_counts() == (1, 1, 2)
        receipts, journals, entries = _ledger_rows()
        assert receipts == [(result.receipt_id, "synthetic", "isolated-tests", "event_A", order["id"], order["amount_minor"], "USD", data["payload_hash"])]
        assert journals == [(result.journal_id, result.receipt_id, order["id"], order["amount_minor"], "USD")]
        assert entries == [
            (result.journal_id, 1, "provider_clearing", "debit", order["amount_minor"]),
            (result.journal_id, 2, "unapplied_order_receipts", "credit", order["amount_minor"]),
        ]

        # The quote's frozen string remains byte-for-byte unchanged and its public
        # representation is still explicitly unpaid; no wallet/payment/challenge
        # row is manufactured by receipt recording.
        frozen = db.session.execute(text("""
            SELECT snapshot_json, snapshot_hash, amount_minor, currency, state
            FROM purchase_orders WHERE id = :id
        """), {"id": order["id"]}).one()
        assert frozen == (order["snapshot_json"], order["snapshot_hash"], order["amount_minor"], "USD", "quoted")
        assert db.session.get(PurchaseOrder, order["id"]).to_dict()["paid"] is False
        assert db.session.execute(text("""
            SELECT (SELECT count(*) FROM wallets),
                   (SELECT count(*) FROM payments),
                   (SELECT count(*) FROM challenges)
        """)).one() == (0, 0, 0)


def test_replay_conflicts_and_second_event_for_one_order_leave_no_orphan_rows(ledger_app):
    from src.database import db
    from src.services.settlement_ledger_service import LedgerError

    order = _create_frozen_quote(ledger_app, 2)
    first_data = _synthetic_receipt(order, "event_A")
    with ledger_app.app_context():
        first = _record(first_data)
        db.session.commit()
        replay = _record(dict(first_data))
        db.session.commit()
        assert replay.created is False
        assert (replay.receipt_id, replay.journal_id, replay.order_id) == (first.receipt_id, first.journal_id, first.order_id)
        assert _ledger_counts() == (1, 1, 2)

        changed = dict(first_data, payload_hash="e" * 64)
        with pytest.raises(LedgerError) as event_conflict:
            _record(changed)
        assert event_conflict.value.code == "LEDGER_EVENT_CONFLICT"
        db.session.rollback()

        with pytest.raises(LedgerError) as order_conflict:
            _record(_synthetic_receipt(order, "event_B"))
        assert order_conflict.value.code == "LEDGER_ORDER_ALREADY_RECORDED"
        db.session.rollback()

        assert _ledger_counts() == (1, 1, 2)
        receipts, journals, entries = _ledger_rows()
        assert [row[0] for row in receipts] == [first.receipt_id]
        assert [row[0] for row in journals] == [first.journal_id]
        assert [row[0] for row in entries] == [first.journal_id, first.journal_id]


@pytest.mark.parametrize(
    "mutate, expected_code",
    [
        (lambda body: dict(body, amount_minor=0), "LEDGER_INVALID"),
        (lambda body: dict(body, amount_minor=True), "LEDGER_INVALID"),
        (lambda body: dict(body, amount_minor=1.0), "LEDGER_INVALID"),
        (lambda body: dict(body, currency="EUR"), "LEDGER_INVALID"),
        (lambda body: dict(body, source="refund"), "LEDGER_SOURCE_NOT_CONFIGURED"),
    ],
    ids=["nonpositive-price", "bool-price", "float-price", "wrong-currency", "refund-source"],
)
def test_malformed_normalized_receipts_refuse_before_any_ledger_write(ledger_app, mutate, expected_code):
    from src.database import db
    from src.services.settlement_ledger_service import LedgerError

    order = _create_frozen_quote(ledger_app, 3)
    with ledger_app.app_context():
        with pytest.raises(LedgerError) as refused:
            _record(mutate(_synthetic_receipt(order)))
        assert refused.value.code == expected_code
        # Validation may inspect the isolated database gate but must not write any
        # evidence before returning its direct service error.
        assert _ledger_counts() == (0, 0, 0)
        db.session.rollback()


def test_outer_transaction_rollback_removes_the_exact_three_inserted_rows(ledger_app):
    from src.database import db

    order = _create_frozen_quote(ledger_app, 4)
    with ledger_app.app_context():
        result = _record(_synthetic_receipt(order))
        assert _ledger_counts() == (1, 1, 2)
        receipts, journals, entries = _ledger_rows()
        assert receipts[0][0] == result.receipt_id and receipts[0][5:] == (order["amount_minor"], "USD", receipts[0][7])
        assert journals == [(result.journal_id, result.receipt_id, order["id"], order["amount_minor"], "USD")]
        assert entries == [
            (result.journal_id, 1, "provider_clearing", "debit", order["amount_minor"]),
            (result.journal_id, 2, "unapplied_order_receipts", "credit", order["amount_minor"]),
        ]

        db.session.rollback()
        assert _ledger_counts() == (0, 0, 0)
        assert _ledger_rows() == ([], [], [])


@pytest.mark.parametrize("failing_flush", [1, 2, 3], ids=["after-receipt", "after-journal", "after-entries"])
def test_flush_failure_inside_savepoint_leaves_no_orphans_when_caller_commits(ledger_app, monkeypatch, failing_flush):
    from src.database import db

    order = _create_frozen_quote(ledger_app, 10 + failing_flush)
    with ledger_app.app_context():
        real_flush = db.session.flush
        calls = 0
        observed = []

        def flush_then_fail(*args, **kwargs):
            nonlocal calls
            calls += 1
            # This is a canary failure injection only: each targeted service flush
            # reaches the genuine PostgreSQL flush before the RuntimeError is raised.
            real_flush(*args, **kwargs)
            if calls == failing_flush:
                observed.append(db.session.connection().execute(text('SELECT (SELECT count(*) FROM payment_event_receipts), (SELECT count(*) FROM settlement_journals)')).one())
                raise RuntimeError(f"injected flush failure {failing_flush}")

        monkeypatch.setattr(db.session, "flush", flush_then_fail)
        with pytest.raises(RuntimeError, match=f"injected flush failure {failing_flush}"):
            _record(_synthetic_receipt(order, f"failure_{failing_flush}"))
        assert calls == failing_flush
        assert observed == [(1, 0) if failing_flush == 1 else (1, 1)]

        # The calling transaction is intentionally committed rather than rolled
        # back.  begin_nested() must already have removed receipt/journal/entries.
        db.session.commit()
        assert _ledger_counts() == (0, 0, 0)
        assert _ledger_rows() == ([], [], [])


def test_concurrent_identity_and_order_conflicts_complete_without_deadlock(ledger_app):
    from src.database import db

    same_order = _create_frozen_quote(ledger_app, 20)
    with ledger_app.app_context():
        elapsed, results = _run_concurrently(
            ledger_app, [_synthetic_receipt(same_order, "concurrent_same"), _synthetic_receipt(same_order, "concurrent_same")]
        )
        assert elapsed < 10
        assert [row[0] for row in results].count("ok") == 2
        assert sorted(row[1] for row in results) == [False, True]
        assert len({row[2] for row in results}) == len({row[3] for row in results}) == 1
        assert _ledger_counts() == (1, 1, 2)

    distinct_event_order = _create_frozen_quote(ledger_app, 21)
    with ledger_app.app_context():
        elapsed, results = _run_concurrently(
            ledger_app, [_synthetic_receipt(distinct_event_order, "concurrent_A"), _synthetic_receipt(distinct_event_order, "concurrent_B")]
        )
        assert elapsed < 10
        assert [row[0] for row in results].count("ok") == 1
        assert ("refused", "LEDGER_ORDER_ALREADY_RECORDED") in results
        assert _ledger_counts() == (2, 2, 4)

    first_order = _create_frozen_quote(ledger_app, 22)
    second_order = _create_frozen_quote(ledger_app, 23)
    with ledger_app.app_context():
        elapsed, results = _run_concurrently(
            ledger_app,
            [_synthetic_receipt(first_order, "same_event_orders"), _synthetic_receipt(second_order, "same_event_orders")],
        )
        assert elapsed < 10
        assert [row[0] for row in results].count("ok") == 1
        assert ("refused", "LEDGER_EVENT_CONFLICT") in results
        # One winner from each preceding subcase; the losing source identity's
        # failed savepoint cannot leave an unjournaled receipt behind.
        assert _ledger_counts() == (3, 3, 6)
        receipts, journals, entries = _ledger_rows()
        assert len({row[0] for row in receipts}) == len(journals) == 3
        assert {row[0] for row in entries} == {row[0] for row in journals}
        assert len(entries) == 6
        db.session.rollback()


@pytest.mark.parametrize(
    "case",
    ["immutable-disabled", "entry-validate-disabled", "wrong-function", "journal-order-unique-dropped"],
)
def test_runtime_storage_gate_refuses_noncanonical_ledger_checks_before_insertion(ledger_app, case):
    from src.database import db
    from src.services.settlement_ledger_service import LedgerError

    with ledger_app.app_context():
        if case == "immutable-disabled":
            (table, trigger), _expected = _ledger_trigger("payment_event_receipts", False)
            db.session.execute(text(
                f"ALTER TABLE public.{_qident(table)} DISABLE TRIGGER {_qident(trigger)}"
            ))
        elif case == "entry-validate-disabled":
            (table, trigger), _expected = _ledger_trigger("settlement_entries", True)
            db.session.execute(text(
                f"ALTER TABLE public.{_qident(table)} DISABLE TRIGGER {_qident(trigger)}"
            ))
        elif case == "wrong-function":
            (_table, _trigger), expected = _ledger_trigger("settlement_entries", True)
            function_name = expected[3]
            db.session.execute(text(f"""
                CREATE OR REPLACE FUNCTION public.{_qident(function_name)}()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    RETURN NEW;
                END;
                $$
            """))
        else:
            db.session.execute(text(
                "ALTER TABLE public.settlement_journals DROP CONSTRAINT uq_journal_order"
            ))
        db.session.commit()

        with pytest.raises(LedgerError) as refused:
            _record(_empty_valid_receipt(f"readiness_{case.replace('-', '_')}"))
        assert refused.value.code == "LEDGER_STORAGE_NOT_READY"
        db.session.rollback()
        assert _ledger_counts() == (0, 0, 0)
        assert _ledger_rows() == ([], [], [])


def test_non_testing_disabled_guard_executes_no_database_sql_and_no_public_route_exists(monkeypatch, ledger_app):
    """Production-shaped disabled configuration must fail before the SQL canary."""
    from src.database import db
    from src.services.settlement_ledger_service import LedgerError

    application = Flask("ledger-production-guard")
    application.config.update(TESTING=False, SYNTHETIC_SETTLEMENT_ENABLED=False)
    sql_calls = 0

    def no_sql(*args, **kwargs):
        nonlocal sql_calls
        sql_calls += 1
        raise AssertionError("disabled non-testing ledger guard attempted database SQL")

    monkeypatch.setattr(db.session, "execute", no_sql)
    with application.app_context():
        with pytest.raises(LedgerError) as refused:
            _record(_empty_valid_receipt("production_disabled"))
    assert refused.value.code == "LEDGER_NOT_CONFIGURED"
    assert sql_calls == 0

    # The real test app exposes no settlement/ledger route at all.  This suite
    # calls the internal service directly and makes no financial-verification claim.
    assert not any(
        "settlement" in rule.rule.lower() or "ledger" in rule.rule.lower()
        for rule in ledger_app.url_map.iter_rules()
    )


@pytest.mark.parametrize('case', ['foreign-key-dropped', 'replication-role'])
def test_ledger_refuses_source_binding_or_trigger_execution_bypass(ledger_app, case):
    from src.database import db
    from src.services.settlement_ledger_service import LedgerError
    with ledger_app.app_context():
        if case == 'foreign-key-dropped':
            db.session.execute(text('ALTER TABLE payment_event_receipts DROP CONSTRAINT fk_receipt_order'))
            db.session.commit()
        else:
            db.session.execute(text('SET LOCAL session_replication_role = replica'))
        with pytest.raises(LedgerError) as refused:
            _record(_empty_valid_receipt('binding_bypass'))
        assert refused.value.code == 'LEDGER_STORAGE_NOT_READY'
        db.session.rollback()
        assert _ledger_counts() == (0, 0, 0)
