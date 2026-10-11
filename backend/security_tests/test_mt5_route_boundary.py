"""Full-factory boundary checks for persisted, unverified MT5 route data."""
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Query

from src.database import db
from src.models.mt5_models import MT5Account, MT5Position, MT5Trade
from src.models.tenant import Tenant
from src.models.token_blacklist import TokenBlacklist
from src.models.trading_program import Challenge, TradingProgram
from src.models.user import User


@compiles(JSONB, "sqlite")
def _jsonb_as_json_for_mt5_boundary(type_, compiler, **kwargs):
    """Production JSONB fields are portable only inside this SQLite fixture."""
    return "JSON"


def _make_mt5_app(*, expanded_hierarchy=False):
    """Build the actual application with only the schema this boundary needs."""
    from src.app import create_app

    app = create_app("testing", config_overrides={
        "EXPANDED_HIERARCHY_ENABLED": expanded_hierarchy,
        "PLATFORM_ROOT_USER_ID": 1,
        "PROPAGATE_EXCEPTIONS": False,
        "RATELIMIT_ENABLED": False,
    })
    tables = [
        Tenant.__table__, User.__table__, TokenBlacklist.__table__,
        TradingProgram.__table__, Challenge.__table__, MT5Account.__table__,
        MT5Trade.__table__, MT5Position.__table__,
    ]
    instant = datetime(2026, 10, 11, 12, 0, 0)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=tables)
        db.session.add_all([
            Tenant(id=1, name="Synthetic Launch Brand", subdomain="mt5-launch", status="active"),
            Tenant(id=2, name="Synthetic Foreign Brand", subdomain="mt5-foreign", status="active"),
            User(
                id=1, email="mt5-root@example.invalid", password_hash="not-a-login-credential",
                first_name="Synthetic", last_name="Root", role="supermaster", tenant_id=1,
                is_active=True, is_verified=True, can_create_same_role=True,
                parent_id=None, tree_path="1", level=0,
            ),
            User(
                id=2, email="mt5-owner@example.invalid", password_hash="not-a-login-credential",
                first_name="Synthetic", last_name="Owner", role="trader", tenant_id=1,
                is_active=True, is_verified=True, can_create_same_role=False,
                parent_id=5, tree_path="1/5/2", level=2,
            ),
            User(
                id=3, email="mt5-other@example.invalid", password_hash="not-a-login-credential",
                first_name="Synthetic", last_name="Other", role="trader", tenant_id=1,
                is_active=True, is_verified=True, can_create_same_role=False,
                parent_id=1, tree_path="1/3", level=1,
            ),
            User(
                id=4, email="mt5-foreign@example.invalid", password_hash="not-a-login-credential",
                first_name="Synthetic", last_name="Foreign", role="trader", tenant_id=2,
                is_active=True, is_verified=True, can_create_same_role=False,
                parent_id=None, tree_path="4", level=0,
            ),
            User(
                id=5, email="mt5-master@example.invalid", password_hash="not-a-login-credential",
                first_name="Synthetic", last_name="Master", role="master", tenant_id=1,
                is_active=True, is_verified=True, can_create_same_role=False,
                parent_id=1, tree_path="1/5", level=1,
            ),
            User(
                id=6, email="mt5-inactive@example.invalid", password_hash="not-a-login-credential",
                first_name="Synthetic", last_name="Inactive", role="trader", tenant_id=1,
                is_active=False, is_verified=True, can_create_same_role=False,
                parent_id=1, tree_path="1/6", level=1,
            ),
            TradingProgram(
                id=10, tenant_id=1, name="Tenant One Program", type="one_phase",
                account_size=Decimal("10000.00"), price=Decimal("10.00"), is_active=True,
            ),
            TradingProgram(
                id=20, tenant_id=2, name="Tenant Two Program", type="one_phase",
                account_size=Decimal("10000.00"), price=Decimal("10.00"), is_active=True,
            ),
            Challenge(
                id=10, user_id=2, program_id=10, status="active",
                initial_balance=Decimal("100.00"), current_balance=Decimal("100.00"),
            ),
            Challenge(
                id=11, user_id=3, program_id=10, status="active",
                initial_balance=Decimal("100.00"), current_balance=Decimal("100.00"),
            ),
            Challenge(
                id=12, user_id=4, program_id=20, status="active",
                initial_balance=Decimal("100.00"), current_balance=Decimal("100.00"),
            ),
            Challenge(
                id=13, user_id=6, program_id=10, status="active",
                initial_balance=Decimal("100.00"), current_balance=Decimal("100.00"),
            ),
            # The owner is tenant one but this program is tenant two: it must
            # never make the account readable despite all foreign keys existing.
            Challenge(
                id=14, user_id=2, program_id=20, status="active",
                initial_balance=Decimal("100.00"), current_balance=Decimal("100.00"),
            ),
        ])
        db.session.flush()
        db.session.add_all([
            MT5Account(
                id=101, user_id=2, challenge_id=10, mt5_login="TEST101",
                mt5_password_encrypted="TEST", balance=Decimal("100.00"), equity=None,
                status="active", created_at=instant, updated_at=instant,
            ),
            # Explicitly supported historical row: no challenge, no reconstructed
            # money values or entitlement are implied by its presence.
            MT5Account(
                id=102, user_id=2, challenge_id=None, mt5_login="TEST102",
                mt5_password_encrypted="TEST", balance=None, equity=None,
                status="active", created_at=instant, updated_at=instant,
            ),
            # Foreign challenge owner and foreign brand both conflict with account owner.
            MT5Account(
                id=103, user_id=2, challenge_id=12, mt5_login="TEST103",
                mt5_password_encrypted="TEST", balance=Decimal("700.00"), equity=Decimal("700.00"),
                status="active", created_at=instant, updated_at=instant,
            ),
            MT5Account(
                id=104, user_id=3, challenge_id=11, mt5_login="TEST104",
                mt5_password_encrypted="TEST", balance=Decimal("300.00"), equity=Decimal("300.00"),
                status="active", created_at=instant, updated_at=instant,
            ),
            MT5Account(
                id=105, user_id=4, challenge_id=12, mt5_login="TEST105",
                mt5_password_encrypted="TEST", balance=Decimal("400.00"), equity=Decimal("400.00"),
                status="active", created_at=instant, updated_at=instant,
            ),
            MT5Account(
                id=106, user_id=6, challenge_id=13, mt5_login="TEST106",
                mt5_password_encrypted="TEST", balance=Decimal("600.00"), equity=Decimal("600.00"),
                status="active", created_at=instant, updated_at=instant,
            ),
            MT5Account(
                id=107, user_id=2, challenge_id=14, mt5_login="TEST107",
                mt5_password_encrypted="TEST", balance=Decimal("700.00"), equity=Decimal("700.00"),
                status="active", created_at=instant, updated_at=instant,
            ),
        ])
        db.session.add_all([
            MT5Trade(
                id=201, mt5_account_id=101, ticket=9201, status="closed",
                profit=Decimal("100.00"), open_time=datetime(2026, 10, 10, 10, 0, 0),
            ),
            MT5Trade(
                id=202, mt5_account_id=101, ticket=9202, status="closed",
                profit=Decimal("-50.00"), open_time=datetime(2026, 10, 10, 11, 0, 0),
            ),
            MT5Trade(
                id=203, mt5_account_id=101, ticket=9203, status="open",
                profit=Decimal("900.00"), open_time=datetime(2026, 10, 10, 12, 0, 0),
            ),
            MT5Trade(
                id=204, mt5_account_id=102, ticket=9204, status="closed",
                profit=None, open_time=datetime(2026, 10, 10, 13, 0, 0),
            ),
            MT5Position(
                id=301, mt5_account_id=101, ticket=9301,
                open_time=datetime(2026, 10, 10, 12, 0, 0), profit=None,
            ),
            MT5Position(
                id=302, mt5_account_id=101, ticket=9302,
                open_time=datetime(2026, 10, 10, 13, 0, 0), profit=Decimal("2.50"),
            ),
        ])
        db.session.commit()
        # Column defaults turn constructor ``None`` into zero at INSERT time.
        # Simulate actual historical missing values at rest, which the route must
        # expose as null rather than silently changing to a known zero.
        db.session.execute(text(
            "UPDATE mt5_accounts SET equity = NULL WHERE id = :account_id"
        ), {"account_id": 101})
        db.session.execute(text(
            "UPDATE mt5_accounts SET balance = NULL, equity = NULL WHERE id = :account_id"
        ), {"account_id": 102})
        db.session.commit()
        db.session.expire_all()
        app.mt5_tokens = {
            identity: db.session.get(User, identity).generate_access_token()
            for identity in (1, 2, 3, 4, 5, 6)
        }
    return app, tables


@pytest.fixture
def mt5_boundary_app():
    app, tables = _make_mt5_app(expanded_hierarchy=False)
    try:
        yield app
    finally:
        with app.app_context():
            db.session.remove()
            db.metadata.drop_all(bind=db.engine, tables=list(reversed(tables)))
            db.engine.dispose()


@pytest.fixture
def mt5_expanded_app():
    app, tables = _make_mt5_app(expanded_hierarchy=True)
    try:
        yield app
    finally:
        with app.app_context():
            db.session.remove()
            db.metadata.drop_all(bind=db.engine, tables=list(reversed(tables)))
            db.engine.dispose()


def _headers(app, actor=2):
    return {"Authorization": "Bearer " + app.mt5_tokens[actor]}


def _counts():
    return {
        "accounts": db.session.query(MT5Account).count(),
        "trades": db.session.query(MT5Trade).count(),
        "positions": db.session.query(MT5Position).count(),
    }


def test_owner_reads_are_explicitly_tenant_challenge_scoped_paginated_and_redacted(mt5_boundary_app):
    client = mt5_boundary_app.test_client()
    response = client.get("/api/mt5/accounts?page=1&per_page=1", headers=_headers(mt5_boundary_app))
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["total"] == 2
    assert payload["page"] == 1 and payload["pages"] == 2
    assert payload["per_page"] == payload["returned_count"] == 1
    assert payload["accounts"][0]["id"] == 101
    assert "mt5_password" not in payload["accounts"][0]
    assert payload["accounts"][0]["equity"] is None
    assert payload["accounts"][0]["data_status"] == "unverified_legacy"

    all_owned = client.get("/api/mt5/accounts?per_page=10", headers=_headers(mt5_boundary_app))
    accounts = {row["id"]: row for row in all_owned.get_json()["accounts"]}
    assert set(accounts) == {101, 102}
    assert accounts[102]["balance"] is None and accounts[102]["equity"] is None
    assert accounts[102]["metadata"] == {
        "source": "persisted_legacy", "mt5_freshness": "not_verified",
        "challenge_link": "legacy_unlinked", "entitlement": "not_verified",
    }

    # A current-owner account linked to another owner's foreign challenge, a
    # foreign-program challenge, a same-brand peer, and a foreign tenant all fail
    # indistinguishably as absent.
    for account_id in (103, 104, 105, 107):
        assert client.get(f"/api/mt5/accounts/{account_id}", headers=_headers(mt5_boundary_app)).status_code == 404


def test_admin_root_is_wide_only_with_real_root_scope_and_master_uses_crm_downline(mt5_boundary_app, mt5_expanded_app):
    launch_response = mt5_boundary_app.test_client().get(
        "/api/mt5/admin/accounts?per_page=100", headers=_headers(mt5_boundary_app, 1),
    )
    assert launch_response.status_code == 200
    # The genuine configured root may read valid rows across brands, but never
    # malformed ownership/program links or an inactive owner.
    assert {row["id"] for row in launch_response.get_json()["accounts"]} == {101, 102, 104, 105}

    expanded_response = mt5_expanded_app.test_client().get(
        "/api/mt5/admin/accounts?per_page=100", headers=_headers(mt5_expanded_app, 5),
    )
    assert expanded_response.status_code == 200
    assert {row["id"] for row in expanded_response.get_json()["accounts"]} == {101, 102}

    with mt5_boundary_app.app_context():
        db.session.get(Tenant, 1).status = "inactive"
        db.session.commit()
    # A real signed root token does not bypass the configured active brand.
    assert mt5_boundary_app.test_client().get(
        "/api/mt5/admin/accounts", headers=_headers(mt5_boundary_app, 1),
    ).status_code == 401


def test_lists_reject_duplicate_or_invalid_bounds_and_status_without_unbounded_fallback(mt5_boundary_app):
    client = mt5_boundary_app.test_client()
    for path in (
        "/api/mt5/accounts?page=0",
        "/api/mt5/accounts?page=1&page=2",
        "/api/mt5/accounts?per_page=101",
        "/api/mt5/accounts/101/trades?status=OPEN",
        "/api/mt5/accounts/101/trades?status=open&status=closed",
        "/api/mt5/accounts/101/positions?page=1001",
        "/api/mt5/admin/accounts?per_page=true",
        "/api/mt5/accounts?page=" + "9" * 5000,
        "/api/mt5/accounts?per_page=" + "0" * 5000 + "1",
        "/api/mt5/accounts?page=01",
    ):
        response = client.get(path, headers=_headers(mt5_boundary_app, 1 if "/admin/" in path else 2))
        assert response.status_code == 400
        assert response.get_json()["code"] == "INVALID_MT5_QUERY"

    closed = client.get(
        "/api/mt5/accounts/101/trades?status=closed&per_page=1", headers=_headers(mt5_boundary_app),
    ).get_json()
    assert closed["status"] == "closed" and closed["total"] == 2
    assert closed["pages"] == 2 and closed["trades"][0]["id"] == 202

    open_only = client.get(
        "/api/mt5/accounts/101/trades?status=open", headers=_headers(mt5_boundary_app),
    ).get_json()
    assert open_only["total"] == 1 and open_only["trades"][0]["id"] == 203

    positions = client.get(
        "/api/mt5/accounts/101/positions?per_page=1", headers=_headers(mt5_boundary_app),
    ).get_json()
    assert positions["total"] == positions["pages"] == 2
    assert positions["positions"][0]["id"] == 302


def test_stats_use_sql_gross_profit_factor_and_report_missing_profit_as_unknown(mt5_boundary_app, monkeypatch):
    def no_materialized_trade_list(*args, **kwargs):
        raise AssertionError("stats must aggregate rather than call Query.all()")

    monkeypatch.setattr(Query, "all", no_materialized_trade_list)
    client = mt5_boundary_app.test_client()
    response = client.get("/api/mt5/accounts/101/stats", headers=_headers(mt5_boundary_app))
    assert response.status_code == 200
    stats = response.get_json()["stats"]
    assert stats["total_trades"] == 2
    assert stats["winning_trades"] == stats["losing_trades"] == 1
    assert stats["total_profit"] == 50.0
    assert stats["gross_profit"] == 100.0 and stats["gross_loss"] == -50.0
    assert stats["profit_factor"] == 2.0  # gross profit / absolute gross loss, never net / loss
    assert stats["current_equity"] is None

    unknown = client.get("/api/mt5/accounts/102/stats", headers=_headers(mt5_boundary_app))
    assert unknown.status_code == 200
    unknown_stats = unknown.get_json()["stats"]
    assert unknown_stats["missing_profit_rows"] == 1
    assert unknown_stats["profit_data_status"] == "unknown"
    assert unknown_stats["total_profit"] is unknown_stats["profit_factor"] is None


def test_all_four_authenticated_mutators_refuse_before_body_or_db_work(mt5_boundary_app, monkeypatch):
    with mt5_boundary_app.app_context():
        before = _counts()
        original = db.session.get(MT5Account, 101)
        before_state = (original.status, original.balance, original.equity, original.updated_at)

    def db_write_forbidden(*args, **kwargs):
        raise AssertionError("refused MT5 mutator must not add or commit local state")

    # These are armed only after seed/auth setup.  JWT signature, principal,
    # revocation and role checks remain real and unmocked.
    monkeypatch.setattr(db.session, "add", db_write_forbidden)
    monkeypatch.setattr(db.session, "commit", db_write_forbidden)
    client = mt5_boundary_app.test_client()
    for path, actor in (
        ("/api/mt5/accounts/create", 2),
        ("/api/mt5/admin/accounts/101/disable", 1),
        ("/api/mt5/admin/accounts/101/balance", 1),
        ("/api/mt5/sync/101", 2),
    ):
        # Invalid JSON demonstrates the fixed provider refusal is before body parsing.
        response = client.post(path, data="{", content_type="application/json", headers=_headers(mt5_boundary_app, actor))
        assert response.status_code == 503
        assert response.get_json() == {
            "success": False,
            "message": "MT5 provider is not configured",
            "code": "MT5_PROVIDER_NOT_CONFIGURED",
        }

    with mt5_boundary_app.app_context():
        assert _counts() == before
        db.session.expire_all()
        account = db.session.get(MT5Account, 101)
        assert (account.status, account.balance, account.equity, account.updated_at) == before_state


def test_mutator_auth_role_and_cookie_csrf_precede_provider_refusal(mt5_boundary_app):
    client = mt5_boundary_app.test_client()
    endpoint = "/api/mt5/admin/accounts/101/disable"
    assert client.post(endpoint, json={}).status_code == 401
    assert client.post(endpoint, json={}, headers=_headers(mt5_boundary_app, 2)).status_code == 403

    cookie_client = mt5_boundary_app.test_client()
    cookie_client.set_cookie("access_token", mt5_boundary_app.mt5_tokens[1])
    csrf_response = cookie_client.post(endpoint, data="{", content_type="application/json")
    assert csrf_response.status_code == 403
    assert csrf_response.get_json()["code"] == "CSRF_INVALID"

    # The inactive owner has a genuine signed token but SessionService rejects it.
    assert client.get("/api/mt5/accounts", headers=_headers(mt5_boundary_app, 6)).status_code == 401
