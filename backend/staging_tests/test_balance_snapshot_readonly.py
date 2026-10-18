"""PostgreSQL contract tests for the read-only legacy balance snapshot service.

The fixture migrates a disposable private database to the real ledger head.  Every
wallet and transaction below is a synthetic SQL fixture row; no HTTP route, provider,
or financial action is exercised.
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from test_settlement_ledger_service import LEDGER_HEAD, ledger_database


SEED_TIME = datetime(2026, 1, 1, 12, 0, 0)


@pytest.fixture
def balance_snapshot_app(staging_resources, monkeypatch):
    """Use the genuine 000007 migrated database with only quote fixture users 1 and 2."""
    with ledger_database(staging_resources, monkeypatch) as application:
        yield application


def _begin_readonly(connection):
    transaction = connection.begin()
    connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"))
    return transaction


def _seed_wallet_and_transaction(connection, *, wallet_id=10, transaction_id=100, main="10.00"):
    """Insert only compliant synthetic legacy rows, including TimestampMixin fields."""
    connection.execute(text("""
        INSERT INTO public.wallets
            (id, user_id, main_balance, commission_balance, bonus_balance,
             last_transaction_at, is_active, notes, created_at, updated_at)
        VALUES
            (:wallet_id, 1, CAST(:main AS numeric), CAST('0.00' AS numeric), CAST('0.00' AS numeric),
             :created_at, true, NULL, :created_at, :created_at)
    """), {"wallet_id": wallet_id, "main": main, "created_at": SEED_TIME})
    connection.execute(text("""
        INSERT INTO public.transactions
            (id, wallet_id, type, amount, balance_type, balance_before, balance_after,
             reference_type, reference_id, description, notes, created_by, created_at, updated_at)
        VALUES
            (:transaction_id, :wallet_id, 'deposit', CAST(:amount AS numeric), 'main',
             CAST('0.00' AS numeric), CAST(:amount AS numeric),
             'synthetic_fixture', :transaction_id, NULL, NULL, NULL, :created_at, :created_at)
    """), {
        "transaction_id": transaction_id,
        "wallet_id": wallet_id,
        "amount": main,
        "created_at": SEED_TIME,
    })


def _read(connection, **kwargs):
    from src.services.balance_snapshot_service import reconcile_readonly_connection

    return reconcile_readonly_connection(connection, **kwargs)


def _capture_sql(connection):
    statements = []

    def listener(_conn, _cursor, statement, parameters, _context, _executemany):
        statements.append((statement, parameters))

    event.listen(connection, "before_cursor_execute", listener)
    return statements, listener


def test_migrated_ledger_fixture_has_two_quote_users_but_no_wallet_and_reports_unknown_absence(balance_snapshot_app):
    from src.database import db
    from src.services.balance_reconciliation import aggregate_summary

    with balance_snapshot_app.app_context(), db.engine.connect() as connection:
        transaction = _begin_readonly(connection)
        assert connection.execute(text("SELECT version_num FROM public.alembic_version")).scalar_one() == LEDGER_HEAD
        assert connection.execute(text("SELECT count(*) FROM public.wallets")).scalar_one() == 0
        report = _read(connection)
        assert report["counts"] == {
            "users": 2,
            "wallets": 0,
            "transactions": 0,
            "users_without_wallet": 2,
            "issues": 0,
        }
        assert report["status"] == "unverified"
        assert report["verified_balance_count"] == 0
        assert report["wallets"] == []
        assert aggregate_summary(report)["counts"]["users_without_wallet"] == 2
        transaction.rollback()


def test_requires_existing_repeatable_read_read_only_transaction_before_any_projected_wallet_read(balance_snapshot_app):
    from src.database import db
    from src.services.balance_reconciliation import ReconciliationInputError

    with balance_snapshot_app.app_context(), db.engine.connect() as connection:
        statements, listener = _capture_sql(connection)
        try:
            with pytest.raises(ReconciliationInputError, match="explicit PostgreSQL"):
                _read(connection)
            assert statements == []
        finally:
            event.remove(connection, "before_cursor_execute", listener)

    for setup in ("mutable", "read-committed-read-only"):
        with balance_snapshot_app.app_context(), db.engine.connect() as connection:
            transaction = connection.begin()
            if setup == "read-committed-read-only":
                connection.execute(text("SET TRANSACTION ISOLATION LEVEL READ COMMITTED READ ONLY"))
            statements, listener = _capture_sql(connection)
            try:
                with pytest.raises(ReconciliationInputError, match="consistent read-only"):
                    _read(connection)
                assert not any("public.wallets" in statement.lower() for statement, _ in statements)
                assert not any("public.transactions" in statement.lower() for statement, _ in statements)
            finally:
                event.remove(connection, "before_cursor_execute", listener)
                transaction.rollback()


def test_user_row_budget_refuses_two_users_before_wallet_or_transaction_reads_and_returns_no_partial_report(balance_snapshot_app):
    from src.database import db
    from src.services.balance_reconciliation import ReconciliationInputError

    with balance_snapshot_app.app_context(), db.engine.connect() as connection:
        transaction = _begin_readonly(connection)
        statements, listener = _capture_sql(connection)
        try:
            with pytest.raises(ReconciliationInputError, match="exceeds row budget"):
                _read(connection, max_rows=1)
            projected = "\n".join(statement.lower() for statement, _ in statements)
            assert "from public.users" in projected
            assert "from public.wallets" not in projected
            assert "from public.transactions" not in projected
        finally:
            event.remove(connection, "before_cursor_execute", listener)
            transaction.rollback()


def test_sql_projection_has_no_pii_canary_and_binds_only_the_row_ceiling(balance_snapshot_app):
    from src.database import db

    with balance_snapshot_app.app_context(), db.engine.connect() as connection:
        transaction = _begin_readonly(connection)
        statements, listener = _capture_sql(connection)
        try:
            report = _read(connection)
        finally:
            event.remove(connection, "before_cursor_execute", listener)
            transaction.rollback()

    projection_sql = "\n".join(statement.lower() for statement, _ in statements)
    assert "select id from public.users" in projection_sql
    for forbidden in ("email", "password", "first_name", "last_name", "password_hash"):
        assert forbidden not in projection_sql
    ceiling_parameters = [parameters for statement, parameters in statements if "limit" in statement.lower()]
    assert ceiling_parameters == [{"ceiling": 10001}] * 3
    assert report["verified_balance_count"] == 0


def test_missing_projected_table_is_a_postgresql_error_not_an_empty_snapshot(balance_snapshot_app):
    from src.database import db

    with balance_snapshot_app.app_context(), db.engine.begin() as writer:
        writer.execute(text("ALTER TABLE public.wallets RENAME TO wallets_missing_for_snapshot_test"))

    with balance_snapshot_app.app_context(), db.engine.connect() as connection:
        transaction = _begin_readonly(connection)
        try:
            with pytest.raises(ProgrammingError):
                _read(connection)
        finally:
            transaction.rollback()


def test_postgresql_read_only_transaction_rejects_an_actual_insert_after_snapshot(balance_snapshot_app):
    from psycopg2.errors import ReadOnlySqlTransaction
    from src.database import db

    with balance_snapshot_app.app_context(), db.engine.connect() as connection:
        transaction = _begin_readonly(connection)
        report = _read(connection)
        assert report["verified_balance_count"] == 0
        with pytest.raises(DBAPIError) as error:
            connection.execute(text("""
                INSERT INTO public.wallets
                    (id, user_id, main_balance, commission_balance, bonus_balance,
                     last_transaction_at, is_active, notes, created_at, updated_at)
                VALUES (10, 1, 0.00, 0.00, 0.00, NULL, true, NULL, :created_at, :created_at)
            """), {"created_at": SEED_TIME})
        assert isinstance(error.value.orig, ReadOnlySqlTransaction)
        transaction.rollback()


def test_service_leaves_caller_owned_transaction_active_and_never_uses_orm_flush(balance_snapshot_app, monkeypatch):
    from src.database import db

    flushes = []

    def no_flush(*_args, **_kwargs):
        flushes.append(True)
        raise AssertionError("read-only snapshot attempted ORM flush")

    with balance_snapshot_app.app_context(), db.engine.connect() as connection:
        monkeypatch.setattr(db.session, "flush", no_flush)
        transaction = _begin_readonly(connection)
        report = _read(connection)
        assert report["complete_supplied_snapshot"] is True
        assert connection.in_transaction() is True
        assert flushes == []
        transaction.rollback()
        assert connection.in_transaction() is False


def test_repeatable_read_snapshot_stays_consistent_while_explicit_atomic_writer_commits_then_new_read_sees_change(balance_snapshot_app):
    from src.database import db

    with balance_snapshot_app.app_context(), db.engine.begin() as seed:
        _seed_wallet_and_transaction(seed)

    with balance_snapshot_app.app_context(), db.engine.connect() as reader, db.engine.connect() as writer:
        read_transaction = _begin_readonly(reader)
        before = _read(reader)
        assert before["wallets"][0]["buckets"]["main"]["stored_minor"] == 1000
        assert before["wallets"][0]["buckets"]["main"]["transaction_count"] == 1

        writer_transaction = writer.begin()
        writer.execute(text("UPDATE public.wallets SET main_balance = 15.00, updated_at = :updated_at WHERE id = 10"),
                       {"updated_at": SEED_TIME})
        writer.execute(text("""
            INSERT INTO public.transactions
                (id, wallet_id, type, amount, balance_type, balance_before, balance_after,
                 reference_type, reference_id, description, notes, created_by, created_at, updated_at)
            VALUES
                (101, 10, 'deposit', 5.00, 'main', 10.00, 15.00,
                 'synthetic_fixture', 101, NULL, NULL, NULL, :created_at, :created_at)
        """), {"created_at": SEED_TIME})
        writer_transaction.commit()

        retained = _read(reader)
        assert retained == before
        read_transaction.rollback()

    with balance_snapshot_app.app_context(), db.engine.connect() as fresh_reader:
        fresh_transaction = _begin_readonly(fresh_reader)
        after = _read(fresh_reader)
        main = after["wallets"][0]["buckets"]["main"]
        assert (main["stored_minor"], main["transaction_count"], main["closing_observed_minor"]) == (1500, 2, 1500)
        assert after["verified_balance_count"] == 0
        fresh_transaction.rollback()
