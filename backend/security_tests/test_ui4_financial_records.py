"""UI-4 financial-record HTTP boundary regressions on isolated SQLite only."""
from collections import Counter
from datetime import datetime
from decimal import Decimal
import json

import pytest
from sqlalchemy import JSON, event

from src.database import db
from src.models.agent import Agent
from src.models.tenant import Tenant
from src.models.token_blacklist import TokenBlacklist
from src.models.trading_program import Challenge, TradingProgram
from src.models.user import User
from src.models.wallet import Transaction, Wallet
from src.models.withdrawal import Withdrawal


_TABLES = (
    Tenant.__table__, User.__table__, TokenBlacklist.__table__, Wallet.__table__,
    Transaction.__table__, Agent.__table__, TradingProgram.__table__, Challenge.__table__,
    Withdrawal.__table__,
)


def _portable_json_columns():
    return [
        (Tenant.__table__.c.settings, Tenant.__table__.c.settings.type),
        (TradingProgram.__table__.c.rules, TradingProgram.__table__.c.rules.type),
        (Challenge.__table__.c.addons, Challenge.__table__.c.addons.type),
        (Challenge.__table__.c.daily_drawdown_history, Challenge.__table__.c.daily_drawdown_history.type),
    ]


@pytest.fixture
def ui4_financial_app():
    """Use the production Flask factory and restore only temporary SQLite metadata."""
    from src.app import create_app

    app = create_app("testing", config_overrides={
        "EXPANDED_HIERARCHY_ENABLED": True,
        "PLATFORM_ROOT_USER_ID": 1,
        "PROPAGATE_EXCEPTIONS": False,
    })
    portable_columns = _portable_json_columns()
    with app.app_context():
        if db.engine.dialect.name == "sqlite":
            for column, _original_type in portable_columns:
                column.type = JSON()
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        _seed(app)
    try:
        yield app
    finally:
        with app.app_context():
            db.session.remove()
            db.metadata.drop_all(bind=db.engine, tables=tuple(reversed(_TABLES)))
            for column, original_type in portable_columns:
                column.type = original_type
            db.engine.dispose()


def _user(identity, *, tenant_id, role, parent_id, tree_path, root=False):
    return User(
        id=identity,
        email=f"ui4-financial-{identity}@example.invalid",
        password_hash="synthetic-not-a-credential",
        first_name="Synthetic",
        last_name=f"Financial{identity}",
        tenant_id=tenant_id,
        role=role,
        parent_id=parent_id,
        tree_path=tree_path,
        level=0 if parent_id is None else 1,
        is_active=True,
        is_verified=True,
        can_create_same_role=root,
    )


def _seed(app):
    now = datetime(2026, 10, 12, 12, 0, 0)
    with app.app_context():
        db.session.add_all([
            Tenant(id=1, name="Synthetic financial tenant", subdomain="ui4-financial-a", status="active"),
            Tenant(id=2, name="Synthetic foreign tenant", subdomain="ui4-financial-b", status="active"),
            _user(1, tenant_id=1, role="supermaster", parent_id=None, tree_path="1", root=True),
            _user(2, tenant_id=1, role="master", parent_id=1, tree_path="1/2"),
            _user(3, tenant_id=1, role="trader", parent_id=2, tree_path="1/2/3"),
            _user(4, tenant_id=2, role="trader", parent_id=None, tree_path="4"),
            _user(5, tenant_id=None, role="trader", parent_id=None, tree_path="5"),
            TradingProgram(
                id=10, tenant_id=1, name="Synthetic tenant one", type="one_phase",
                account_size=Decimal("10000.00"), price=Decimal("1.00"), rules={},
            ),
            TradingProgram(
                id=11, tenant_id=2, name="Synthetic tenant two", type="one_phase",
                account_size=Decimal("10000.00"), price=Decimal("1.00"), rules={},
            ),
        ])
        db.session.flush()
        db.session.add_all([
            Challenge(
                id=100, user_id=3, program_id=10, status="active",
                initial_balance=Decimal("10000.00"), current_balance=Decimal("10000.00"),
            ),
            # A same-owner challenge on a foreign program must not authorize a record.
            Challenge(
                id=101, user_id=3, program_id=11, status="active",
                initial_balance=Decimal("10000.00"), current_balance=Decimal("10000.00"),
            ),
            Wallet(
                id=30, user_id=3, main_balance=Decimal("12.34"),
                commission_balance=Decimal("5.66"), bonus_balance=Decimal("1.00"),
                is_active=True, last_transaction_at=now, created_at=now,
            ),
            Agent(id=31, agent_code="UI4FIN31", user_id=3),
            Agent(id=41, agent_code="UI4FIN41", user_id=4),
        ])
        db.session.flush()
        db.session.add_all([
            Transaction(
                id=200, wallet_id=30, type="deposit", balance_type="main", amount=Decimal("12.34"),
                balance_before=Decimal("0.00"), balance_after=Decimal("12.34"), created_at=now,
            ),
            Transaction(
                id=201, wallet_id=30, type="commission", balance_type="commission", amount=Decimal("5.66"),
                balance_before=Decimal("0.00"), balance_after=Decimal("5.66"), created_at=now,
            ),
            Withdrawal(
                id=300, user_id=3, challenge_id=100, amount=Decimal("10.00"), fee=Decimal("1.00"),
                net_amount=Decimal("9.00"), payment_method="bank_transfer", status="pending", created_at=now,
            ),
            Withdrawal(
                id=301, agent_id=31, challenge_id=100, amount=Decimal("11.00"), fee=Decimal("0.00"),
                net_amount=Decimal("11.00"), payment_method="paypal", status="completed", created_at=now,
                completed_at=now,
            ),
            # Conflicting direct and agent owners are never guessed or exposed.
            Withdrawal(
                id=302, user_id=3, agent_id=41, amount=Decimal("12.00"), fee=Decimal("0.00"),
                net_amount=Decimal("12.00"), payment_method="bank_transfer", status="pending", created_at=now,
            ),
            # A challenge cannot contribute tenant identity when its program is foreign.
            Withdrawal(
                id=303, user_id=3, challenge_id=101, amount=Decimal("13.00"), fee=Decimal("0.00"),
                net_amount=Decimal("13.00"), payment_method="bank_transfer", status="pending", created_at=now,
            ),
            Withdrawal(
                id=304, user_id=4, amount=Decimal("14.00"), fee=Decimal("0.00"),
                net_amount=Decimal("14.00"), payment_method="bank_transfer", status="pending", created_at=now,
            ),
        ])
        db.session.commit()
        app.ui4_financial_tokens = {
            identity: db.session.get(User, identity).generate_access_token()
            for identity in (1, 2, 3, 4, 5)
        }


def _headers(app, actor):
    return {"Authorization": "Bearer " + app.ui4_financial_tokens[actor]}


def _resource_sql(app, call):
    statements = Counter()
    with app.app_context():
        engine = db.engine

    def observed(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements[statement.lower()] += 1

    event.listen(engine, "before_cursor_execute", observed)
    try:
        return call(), statements
    finally:
        event.remove(engine, "before_cursor_execute", observed)


def _assert_flags(payload, *, user_id):
    assert payload["owner_context"] == {"user_id": user_id, "tenant_id": 1}
    assert payload["balance_verification"] == "unverified_legacy"
    assert payload["payouts_enabled"] is False
    assert payload["available_for_payout"] is None
    assert payload["currency"] is None


def test_ui4_financial_valid_http_projections_are_exact_and_junit_recorded(ui4_financial_app, record_property, monkeypatch):
    client = ui4_financial_app.test_client()
    from src.services.financial_records_read import FinancialRecordsReadService
    withdrawals_errors = []
    original_withdrawals_for_owner = FinancialRecordsReadService.withdrawals_for_owner

    def capture_withdrawal_error(*args, **kwargs):
        try:
            return original_withdrawals_for_owner(*args, **kwargs)
        except Exception as error:
            withdrawals_errors.append(error)
            raise

    monkeypatch.setattr(FinancialRecordsReadService, "withdrawals_for_owner", capture_withdrawal_error)

    balance = client.get("/api/v1/wallet/balance", headers=_headers(ui4_financial_app, 3))
    assert balance.status_code == 200
    balance_payload = balance.get_json()
    _assert_flags(balance_payload, user_id=3)
    assert set(balance_payload) == {
        "owner_context", "balance_verification", "payouts_enabled", "available_for_payout", "currency", "wallet",
    }
    assert balance_payload["wallet"] == {
        "id": 30, "user_id": 3, "main_balance": "12.34", "commission_balance": "5.66",
        "bonus_balance": "1.00", "is_active": True, "last_transaction_at": "2026-10-12T12:00:00",
        "created_at": "2026-10-12T12:00:00",
    }
    assert "total_balance" not in balance_payload["wallet"]
    record_property("ui4_wallet_balance_payload", json.dumps(balance_payload, sort_keys=True))

    transactions = client.get("/api/v1/wallet/transactions?balance_type=main&per_page=1", headers=_headers(ui4_financial_app, 3))
    assert transactions.status_code == 200
    transactions_payload = transactions.get_json()
    _assert_flags(transactions_payload, user_id=3)
    assert transactions_payload["wallet_id"] == 30
    assert transactions_payload["filters"] == {"balance_type": "main"}
    assert transactions_payload["pagination"] == {"page": 1, "per_page": 1, "total": 1, "pages": 1}
    assert transactions_payload["transactions"] == [{
        "id": 200, "wallet_id": 30, "type": "deposit", "balance_type": "main", "amount": "12.34",
        "balance_before": "0.00", "balance_after": "12.34", "created_at": "2026-10-12T12:00:00",
    }]
    record_property("ui4_wallet_transactions_payload", json.dumps(transactions_payload, sort_keys=True))

    mine = client.get("/api/v1/traders/withdrawals", headers=_headers(ui4_financial_app, 3))
    assert not withdrawals_errors
    assert mine.status_code == 200
    withdrawals_payload = mine.get_json()
    _assert_flags(withdrawals_payload, user_id=3)
    assert withdrawals_payload["filters"] == {"status": None}
    assert withdrawals_payload["pagination"] == {"page": 1, "per_page": 20, "total": 2, "pages": 1}
    assert [row["id"] for row in withdrawals_payload["withdrawals"]] == [301, 300]
    assert all(set(row) == {
        "id", "user_id", "amount", "fee", "net_amount", "payment_method", "status", "created_at",
        "approved_at", "processed_at", "completed_at",
    } for row in withdrawals_payload["withdrawals"])
    assert all("notes" not in row and "payment_details" not in row for row in withdrawals_payload["withdrawals"])
    record_property("ui4_withdrawals_payload", json.dumps(withdrawals_payload, sort_keys=True))

    admin = client.get("/api/v1/wallet/admin/withdrawals", headers=_headers(ui4_financial_app, 2))
    assert admin.status_code == 200
    admin_payload = admin.get_json()
    _assert_flags(admin_payload, user_id=2)
    assert [row["id"] for row in admin_payload["withdrawals"]] == [301, 300]
    record_property("ui4_admin_withdrawals_payload", json.dumps(admin_payload, sort_keys=True))

    admin_wallets = client.get("/api/v1/wallet/admin/wallets", headers=_headers(ui4_financial_app, 2))
    assert admin_wallets.status_code == 200
    wallet_payload = admin_wallets.get_json()
    _assert_flags(wallet_payload, user_id=2)
    assert wallet_payload["wallets"] == [balance_payload["wallet"]]
    assert "email" not in json.dumps(wallet_payload) and "name" not in json.dumps(wallet_payload)


def test_ui4_financial_rejects_noncanonical_unknown_duplicate_and_missing_tenant_before_resource_sql(ui4_financial_app):
    client = ui4_financial_app.test_client()
    resource_names = ("wallets", "transactions", "withdrawals", "agents", "challenges", "trading_programs")
    for path, actor, expected in (
        ("/api/v1/wallet/balance?unexpected=1", 3, 400),
        ("/api/v1/wallet/transactions?page=01", 3, 400),
        ("/api/v1/wallet/transactions?page=1&page=2", 3, 400),
        ("/api/v1/wallet/transactions?balance_type=main&balance_type=bonus", 3, 400),
        ("/api/v1/traders/withdrawals?status=PENDING", 3, 400),
        ("/api/v1/wallet/admin/withdrawals?per_page=51", 2, 400),
        ("/api/v1/wallet/transactions?page=501&per_page=21", 3, 400),
        ("/api/v1/wallet/transactions?page=" + "9" * 5000, 3, 400),
        ("/api/v1/wallet/transactions?page=١", 3, 400),
        ("/api/v1/traders/withdrawals?status=", 3, 400),
        ("/api/v1/traders/withdrawals?unexpected=1", 3, 400),
        ("/api/v1/traders/withdrawals?status=pending&status=completed", 3, 400),
        ("/api/v1/wallet/admin/wallets?unexpected=1", 2, 400),
        ("/api/v1/wallet/admin/withdrawals?page=0", 2, 400),
        ("/api/v1/wallet/transactions", 5, 403),
    ):
        response, statements = _resource_sql(
            ui4_financial_app, lambda path=path, actor=actor: client.get(path, headers=_headers(ui4_financial_app, actor)),
        )
        assert response.status_code == expected
        sql = "\n".join(statements)
        assert not any(resource in sql for resource in resource_names)


def test_ui4_financial_missing_wallet_is_canonical_and_reads_do_not_autoflush(ui4_financial_app):
    client = ui4_financial_app.test_client()
    missing = client.get("/api/v1/wallet/balance", headers=_headers(ui4_financial_app, 2))
    assert missing.status_code == 404
    assert missing.get_json() == {
        "error": "Wallet not found", "code": "WALLET_NOT_FOUND", "reason": "unverified_legacy",
    }

    with ui4_financial_app.app_context():
        pending = Wallet(
            user_id=2, main_balance=Decimal("999.99"), commission_balance=Decimal("0.00"), bonus_balance=Decimal("0.00"),
        )
        db.session.add(pending)
        writes = []

        def observe_write(_connection, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
                writes.append(statement)

        event.listen(db.engine, "before_cursor_execute", observe_write)
        try:
            response = client.get("/api/v1/wallet/transactions?per_page=1", headers=_headers(ui4_financial_app, 3))
        finally:
            event.remove(db.engine, "before_cursor_execute", observe_write)
            db.session.rollback()
        assert response.status_code == 200
        assert pending.id is None and writes == []


def test_ui4_financial_trader_withdrawal_post_is_token_csrf_ordered_and_fixed_before_body_or_sql(ui4_financial_app):
    client = ui4_financial_app.test_client()
    endpoint = "/api/v1/traders/withdrawals"
    assert client.post(endpoint, data="{", content_type="application/json").status_code == 401
    response, statements = _resource_sql(
        ui4_financial_app,
        lambda: client.post(endpoint, data="{", content_type="application/json", headers=_headers(ui4_financial_app, 3)),
    )
    assert response.status_code == 503
    assert response.get_json() == {
        "error": "Wallet ledger is not configured", "code": "WALLET_LEDGER_NOT_CONFIGURED",
    }
    sql = "\n".join(statements)
    assert not any(resource in sql for resource in ("wallets", "transactions", "withdrawals", "challenges"))

    cookie_client = ui4_financial_app.test_client()
    cookie_client.set_cookie("access_token", ui4_financial_app.ui4_financial_tokens[3])
    csrf = cookie_client.post(endpoint, data="{", content_type="application/json")
    assert csrf.status_code == 403 and csrf.get_json()["code"] == "CSRF_INVALID"


def test_ui4_financial_configured_root_reads_all_valid_owners_without_private_fields(ui4_financial_app):
    client = ui4_financial_app.test_client()
    response = client.get("/api/v1/wallet/admin/withdrawals", headers=_headers(ui4_financial_app, 1))
    assert response.status_code == 200
    payload = response.get_json()
    _assert_flags(payload, user_id=1)
    assert [row["id"] for row in payload["withdrawals"]] == [304, 301, 300]
    assert payload["pagination"] == {"page": 1, "per_page": 20, "total": 3, "pages": 1}
    assert {row["user_id"] for row in payload["withdrawals"]} == {3, 4}
    assert all("payment_details" not in row and "notes" not in row and "email" not in row for row in payload["withdrawals"])


def test_ui4_financial_missing_driver_total_row_fails_instead_of_inventing_zero(ui4_financial_app, monkeypatch):
    from src.services.financial_records_read import FinancialReadArguments, _snapshot_page

    class BrokenResult:
        def all(self):
            return []

    with ui4_financial_app.app_context():
        query = db.session.query(Transaction.id, Transaction.created_at)
        monkeypatch.setattr(db.session, "execute", lambda *args, **kwargs: BrokenResult())
        with pytest.raises(RuntimeError, match="did not return its total row"):
            _snapshot_page(query, FinancialReadArguments(1, 20, 0, None))
