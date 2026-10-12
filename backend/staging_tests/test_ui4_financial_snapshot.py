"""Single-statement UI-4 financial list snapshots on real migrated PostgreSQL only."""
from __future__ import annotations

import threading
import time

from sqlalchemy import create_engine, event, text

from test_ui4_financial_records import _headers, ui4_financial_staging_app


_SNAPSHOT_LOCK_KEY = 2_026_101_204


def _snapshot_statements(statements):
    return [statement for statement in statements if "financial_scoped AS" in statement]


def test_ui4_financial_snapshot_lists_are_one_statement_filtered_and_keep_beyond_total(
    ui4_financial_staging_app,
):
    """All four bounded lists use the shared CTE count/page statement on PostgreSQL."""
    from src.database import db

    with ui4_financial_staging_app.app_context():
        engine = db.engine
        assert engine.dialect.name == "postgresql"

    statements = []

    def observe(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", observe)
    try:
        client = ui4_financial_staging_app.test_client()
        transactions = client.get(
            "/api/v1/wallet/transactions?balance_type=main&per_page=1",
            headers=_headers(ui4_financial_staging_app, 3),
        )
        owner_withdrawals = client.get(
            "/api/v1/traders/withdrawals?status=pending&per_page=1",
            headers=_headers(ui4_financial_staging_app, 3),
        )
        wallets = client.get(
            "/api/v1/wallet/admin/wallets?per_page=1",
            headers=_headers(ui4_financial_staging_app, 2),
        )
        admin_withdrawals = client.get(
            "/api/v1/wallet/admin/withdrawals?status=pending&per_page=1",
            headers=_headers(ui4_financial_staging_app, 2),
        )
        beyond_total = client.get(
            "/api/v1/wallet/transactions?balance_type=main&page=2&per_page=1",
            headers=_headers(ui4_financial_staging_app, 3),
        )
    finally:
        event.remove(engine, "before_cursor_execute", observe)

    assert all(response.status_code == 200 for response in (
        transactions, owner_withdrawals, wallets, admin_withdrawals, beyond_total,
    ))
    assert transactions.get_json()["filters"] == {"balance_type": "main"}
    assert transactions.get_json()["pagination"] == {"page": 1, "per_page": 1, "total": 1, "pages": 1}
    assert [row["id"] for row in transactions.get_json()["transactions"]] == [200]
    assert owner_withdrawals.get_json()["filters"] == {"status": "pending"}
    assert [row["id"] for row in owner_withdrawals.get_json()["withdrawals"]] == [300]
    assert [row["id"] for row in wallets.get_json()["wallets"]] == [30]
    assert admin_withdrawals.get_json()["filters"] == {"status": "pending"}
    assert [row["id"] for row in admin_withdrawals.get_json()["withdrawals"]] == [300]
    assert beyond_total.get_json()["transactions"] == []
    assert beyond_total.get_json()["pagination"] == {"page": 2, "per_page": 1, "total": 1, "pages": 1}

    snapshots = _snapshot_statements(statements)
    assert len(snapshots) == 5
    for statement in snapshots:
        assert "financial_scoped AS MATERIALIZED" in statement
        assert "financial_total AS" in statement
        assert "count(*) AS _financial_total" in statement
        assert "financial_page AS" in statement
        assert "LEFT OUTER JOIN financial_page ON true" in statement
        assert "LIMIT" in statement and "OFFSET" in statement


def _install_snapshot_pause(engine):
    """Create an isolated-test pause after total is available but before page evaluation."""
    with engine.begin() as connection:
        connection.execute(text(f"""
            CREATE OR REPLACE FUNCTION ui4_financial_snapshot_pause()
            RETURNS boolean
            LANGUAGE plpgsql
            AS $$
            BEGIN
                PERFORM pg_advisory_lock({_SNAPSHOT_LOCK_KEY});
                PERFORM pg_sleep(0.45);
                PERFORM pg_advisory_unlock({_SNAPSHOT_LOCK_KEY});
                RETURN true;
            END;
            $$
        """))


def _commit_when_snapshot_page_pauses(engine, mutation, complete, errors):
    """Commit a real external mutation only after the read statement holds its pause lock."""
    try:
        with engine.connect() as connection:
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                owns_lock = connection.execute(
                    text("SELECT pg_try_advisory_lock(:lock_key)"),
                    {"lock_key": _SNAPSHOT_LOCK_KEY},
                ).scalar_one()
                if owns_lock:
                    connection.execute(
                        text("SELECT pg_advisory_unlock(:lock_key)"),
                        {"lock_key": _SNAPSHOT_LOCK_KEY},
                    )
                    connection.commit()
                    time.sleep(0.01)
                    continue
                connection.execute(text(mutation))
                connection.commit()
                complete.set()
                return
            errors.append("read statement never reached its snapshot page pause")
    except Exception as error:  # the main test reports cross-thread DB failures deterministically
        errors.append(repr(error))


def test_ui4_financial_snapshot_survives_concurrent_delete_and_insert_between_total_and_page(
    ui4_financial_staging_app,
):
    """A real second PostgreSQL connection mutates while the single list statement is paused."""
    from src.database import db

    with ui4_financial_staging_app.app_context():
        engine = db.engine
        assert engine.dialect.name == "postgresql"
        mutator = create_engine(str(engine.url))
        _install_snapshot_pause(mutator)

    source_statements = []

    def pause_after_total(_connection, _cursor, statement, parameters, _context, _executemany):
        if "financial_scoped AS" not in statement:
            return statement, parameters
        source_statements.append(statement)
        page_start = statement.index("financial_page AS")
        before_page = statement[:page_start]
        page_and_result = statement[page_start:]
        needle = "FROM financial_scoped ORDER BY"
        assert needle in page_and_result
        before_page += (
            "financial_pause AS MATERIALIZED "
            "(SELECT ui4_financial_snapshot_pause() AS paused FROM financial_total), "
        )
        page_and_result = page_and_result.replace(
            needle,
            "FROM financial_scoped "
            "CROSS JOIN financial_total AS financial_snapshot_total "
            "CROSS JOIN financial_pause "
            "WHERE financial_pause.paused ORDER BY",
            1,
        )
        page_and_result = page_and_result.replace(
            "FROM financial_total LEFT OUTER JOIN financial_page ON true",
            "FROM financial_total CROSS JOIN financial_pause "
            "LEFT OUTER JOIN financial_page ON true",
            1,
        )
        return before_page + page_and_result, parameters

    event.listen(engine, "before_cursor_execute", pause_after_total, retval=True)
    try:
        client = ui4_financial_staging_app.test_client()

        deleted = threading.Event()
        delete_errors = []
        delete_thread = threading.Thread(
            target=_commit_when_snapshot_page_pauses,
            args=(mutator, "DELETE FROM transactions WHERE id = 200", deleted, delete_errors),
            daemon=True,
        )
        delete_thread.start()
        delete_response = client.get(
            "/api/v1/wallet/transactions?balance_type=main&per_page=1",
            headers=_headers(ui4_financial_staging_app, 3),
        )
        delete_thread.join(timeout=4)
        assert not delete_thread.is_alive()
        assert delete_errors == [] and deleted.is_set()
        assert delete_response.status_code == 200
        delete_payload = delete_response.get_json()
        # The CTE total and page retain the statement snapshot from before the
        # concurrent deletion; an old count()/all() pair could return total=1
        # with an empty page at this exact interleaving point.
        assert delete_payload["pagination"] == {"page": 1, "per_page": 1, "total": 1, "pages": 1}
        assert [row["id"] for row in delete_payload["transactions"]] == [200]

        inserted = threading.Event()
        insert_errors = []
        insert_thread = threading.Thread(
            target=_commit_when_snapshot_page_pauses,
            args=(
                mutator,
                """
                INSERT INTO transactions
                    (id, wallet_id, type, amount, balance_type, balance_before, balance_after, created_at, updated_at)
                VALUES
                    (202, 30, 'deposit', 77.00, 'main', 0.00, 77.00,
                     '2026-10-12 12:01:00', '2026-10-12 12:01:00')
                """,
                inserted,
                insert_errors,
            ),
            daemon=True,
        )
        insert_thread.start()
        insert_response = client.get(
            "/api/v1/wallet/transactions?balance_type=main&per_page=1",
            headers=_headers(ui4_financial_staging_app, 3),
        )
        insert_thread.join(timeout=4)
        assert not insert_thread.is_alive()
        assert insert_errors == [] and inserted.is_set()
        assert insert_response.status_code == 200
        insert_payload = insert_response.get_json()
        # The insert committed while the page CTE was paused, but it is not in
        # this statement's shared snapshot, so the null-ID sentinel keeps a
        # coherent total=0/rows=[] response.
        assert insert_payload["pagination"] == {"page": 1, "per_page": 1, "total": 0, "pages": 0}
        assert insert_payload["transactions"] == []

        with mutator.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM transactions WHERE id IN (200, 202)")).scalar_one() == 1
    finally:
        event.remove(engine, "before_cursor_execute", pause_after_total)
        with mutator.begin() as connection:
            connection.execute(text("DELETE FROM transactions WHERE id = 202"))
            connection.execute(text("DROP FUNCTION IF EXISTS ui4_financial_snapshot_pause()"))
        mutator.dispose()
        with ui4_financial_staging_app.app_context():
            # Never commit the fixture's scoped Flask session from this test.
            db.session.rollback()

    assert len(source_statements) == 2
    for statement in source_statements:
        assert "financial_total AS" in statement
        assert "financial_page AS" in statement
        assert "LEFT OUTER JOIN financial_page ON true" in statement
