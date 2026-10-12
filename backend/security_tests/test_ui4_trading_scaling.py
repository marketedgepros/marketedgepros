"""Focused real-Flask UI-4 trading/scaling contract regressions (synthetic only)."""
from collections import Counter
from datetime import datetime, timedelta
from decimal import Decimal
import json

import pytest
from sqlalchemy import event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from src.database import db
from src.models.account_scaling import AccountScaling
from src.models.tenant import Tenant
from src.models.token_blacklist import TokenBlacklist
from src.models.trade import Trade
from src.models.trading_program import Challenge, TradingProgram
from src.models.user import User


_TABLES = (
    Tenant.__table__,
    User.__table__,
    TokenBlacklist.__table__,
    TradingProgram.__table__,
    Challenge.__table__,
    Trade.__table__,
    AccountScaling.__table__,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    """Test-only SQLite adapter; production PostgreSQL JSONB is unchanged."""
    return "JSON"


def _remove_duplicate_legacy_indexes():
    """SQLite rejects the model's pre-existing duplicate index declaration."""
    names = set()
    for index in tuple(AccountScaling.__table__.indexes):
        if index.name in names:
            AccountScaling.__table__.indexes.remove(index)
        else:
            names.add(index.name)


@pytest.fixture
def ui4_app():
    """The production factory plus a deliberately small in-memory table set."""
    from src.app import create_app

    app = create_app("testing", config_overrides={
        "EXPANDED_HIERARCHY_ENABLED": True,
        "PLATFORM_ROOT_USER_ID": 1,
        "PROPAGATE_EXCEPTIONS": False,
    })
    with app.app_context():
        _remove_duplicate_legacy_indexes()
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        _seed(app)
    yield app
    with app.app_context():
        db.session.remove()
        db.metadata.drop_all(bind=db.engine, tables=list(reversed(_TABLES)))


def _user(identity, *, tenant_id, role, parent_id, tree_path, root=False):
    return User(
        id=identity,
        email=f"ui4-{identity}@example.invalid",
        password_hash="synthetic-not-a-credential",
        first_name="Synthetic",
        last_name=f"User{identity}",
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
    now = datetime.utcnow().replace(microsecond=0)
    users = [
        _user(1, tenant_id=1, role="supermaster", parent_id=None, tree_path="1", root=True),
        _user(2, tenant_id=1, role="master", parent_id=1, tree_path="1/2"),
        _user(3, tenant_id=1, role="trader", parent_id=2, tree_path="1/2/3"),
        _user(4, tenant_id=1, role="trader", parent_id=1, tree_path="1/4"),
        _user(5, tenant_id=2, role="trader", parent_id=None, tree_path="5"),
        _user(6, tenant_id=1, role="affiliate", parent_id=1, tree_path="1/6"),
        _user(7, tenant_id=None, role="trader", parent_id=None, tree_path="7"),
    ]
    db.session.add_all([
        Tenant(id=1, name="Synthetic tenant A", subdomain="ui4-a"),
        Tenant(id=2, name="Synthetic tenant B", subdomain="ui4-b"),
        *users,
        TradingProgram(id=10, tenant_id=1, name="A", type="one_phase",
                       account_size=Decimal("10000.00"), price=Decimal("1.00"), rules={}),
        TradingProgram(id=11, tenant_id=2, name="B", type="one_phase",
                       account_size=Decimal("10000.00"), price=Decimal("1.00"), rules={}),
        Challenge(id=100, user_id=3, program_id=10, status="active",
                  initial_balance=Decimal("10000.00"), current_balance=Decimal("10000.00")),
        Challenge(id=101, user_id=4, program_id=10, status="active",
                  initial_balance=Decimal("10000.00"), current_balance=Decimal("10000.00")),
        # This deliberately malformed owner/program pairing must never pass tenant scoping.
        Challenge(id=102, user_id=3, program_id=11, status="active",
                  initial_balance=Decimal("10000.00"), current_balance=Decimal("10000.00")),
        Trade(id=1000, ticket="UI4-A", challenge_id=100, symbol="eurusd", trade_type="buy",
              volume=Decimal("1.20"), open_price=Decimal("1.23456"),
              close_price=Decimal("1.34567"), profit=Decimal("10.10"),
              commission=Decimal("0.00"), swap=Decimal("0.00"), status="closed",
              open_time=now - timedelta(days=2), close_time=now - timedelta(days=1)),
        Trade(id=1001, ticket="UI4-B", challenge_id=100, symbol="EURUSD", trade_type="sell",
              volume=Decimal("0.00"), open_price=Decimal("0.00000"),
              close_price=Decimal("0.00000"), profit=Decimal("-3.25"),
              commission=Decimal("0.00"), swap=Decimal("0.00"), status="closed",
              open_time=now - timedelta(days=2), close_time=now - timedelta(days=1)),
        Trade(id=1002, ticket="UI4-ZERO", challenge_id=100, symbol="ZERO", trade_type="buy",
              volume=Decimal("0.00"), open_price=Decimal("0.00000"),
              close_price=Decimal("0.00000"), profit=Decimal("0.00"),
              commission=Decimal("0.00"), swap=Decimal("0.00"), status="closed",
              open_time=now - timedelta(hours=4), close_time=now - timedelta(hours=3)),
        Trade(id=1003, ticket="UI4-NULL", challenge_id=100, symbol="NULLP", trade_type="buy",
              volume=Decimal("2.00"), open_price=Decimal("2.00000"), close_price=None,
              profit=None, commission=None, swap=None, status="open",
              open_time=now - timedelta(hours=1), close_time=None),
        Trade(id=1004, ticket="UI4-FOREIGN", challenge_id=101, symbol="FOREIGN", trade_type="buy",
              volume=Decimal("9.00"), open_price=Decimal("9.00000"),
              close_price=Decimal("9.00000"), profit=Decimal("99.00"),
              commission=Decimal("0.00"), swap=Decimal("0.00"), status="closed",
              open_time=now, close_time=now),
        Trade(id=1005, ticket="UI4-CROSS", challenge_id=102, symbol="CROSS", trade_type="buy",
              volume=Decimal("9.00"), open_price=Decimal("9.00000"),
              close_price=Decimal("9.00000"), profit=Decimal("88.00"),
              commission=Decimal("0.00"), swap=Decimal("0.00"), status="closed",
              open_time=now, close_time=now),
        AccountScaling(id=200, user_id=3, current_tier=1,
                       current_account_size=Decimal("10000.00"), next_tier=2,
                       next_account_size=Decimal("25000.00"), total_profit=Decimal("0.00"),
                       target_profit=Decimal("800.00"), progress_percentage=Decimal("0.00"),
                       times_scaled=0, is_eligible_for_scaling=True, status="active"),
        AccountScaling(id=201, user_id=4, current_tier=2,
                       current_account_size=Decimal("25000.00"), next_tier=None,
                       next_account_size=None, total_profit=Decimal("12.34"),
                       target_profit=Decimal("200.00"), progress_percentage=Decimal("6.17"),
                       times_scaled=1, is_eligible_for_scaling=True, status="active"),
    ])
    db.session.commit()
    app.ui4_tokens = {
        identity: db.session.get(User, identity).generate_access_token()
        for identity in range(1, 8)
    }
    db.session.remove()


def _headers(app, actor=3):
    return {"Authorization": "Bearer " + app.ui4_tokens[actor]}


def _sql_count(app, call):
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


def test_history_real_response_is_tenant_owned_decimal_exact_and_junit_payload(ui4_app, record_property):
    response = ui4_app.test_client().get(
        "/api/v1/traders/history?symbol=eurusd&type=all&period=all&per_page=2",
        headers=_headers(ui4_app),
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["owner_context"] == {"user_id": 3, "tenant_id": 1}
    assert body["filters"] == {"symbol": "EURUSD", "type": "all", "period": "all"}
    assert body["pagination"] == {"page": 1, "per_page": 2, "total": 2, "pages": 1}
    assert [trade["id"] for trade in body["trades"]] == [1001, 1000]
    assert body["statistics"] == {
        "total_trades": 2,
        "winning_trades": 1,
        "losing_trades": 1,
        "total_profit": "6.85",
    }
    assert body["trades"][0]["volume"] == "0.00"
    assert body["trades"][0]["open_price"] == "0.00000"
    assert "lots" not in body["trades"][0] and "pips" not in body["trades"][0]
    assert body["currency"] is None and body["provider_authenticated"] is False

    zero = ui4_app.test_client().get(
        "/api/v1/traders/history?symbol=ZERO", headers=_headers(ui4_app)
    ).get_json()
    assert zero["statistics"]["total_profit"] == "0.00"
    null_profit = ui4_app.test_client().get(
        "/api/v1/traders/history?symbol=NULLP", headers=_headers(ui4_app)
    ).get_json()
    assert null_profit["statistics"] == {
        "total_trades": 1,
        "winning_trades": None,
        "losing_trades": None,
        "total_profit": None,
    }
    record_property("ui4_trading_history_response", json.dumps(body, sort_keys=True))


def test_history_auth_invalid_query_and_missing_tenant_gate_before_trading_resource_sql(ui4_app):
    client = ui4_app.test_client()
    assert client.get("/api/v1/traders/history").status_code == 401
    for path, actor, expected in (
        ("/api/v1/traders/history?unexpected=1", 3, 400),
        ("/api/v1/traders/history?page=1&page=2", 3, 400),
        ("/api/v1/traders/history?symbol=EUR%20USD", 3, 400),
        ("/api/v1/traders/history", 7, 403),
    ):
        response, statements = _sql_count(
            ui4_app, lambda: client.get(path, headers=_headers(ui4_app, actor))
        )
        assert response.status_code == expected
        sql = "\n".join(statements)
        assert "trades" not in sql and "challenges" not in sql and "trading_programs" not in sql


def test_history_read_uses_no_autoflush_and_bounded_trade_page(ui4_app, monkeypatch):
    flushed = []
    original_flush = db.session.flush

    def forbidden_flush(*args, **kwargs):
        flushed.append(True)
        raise AssertionError("history read attempted a flush")

    # The decorator, aggregate, and bounded page run through the real request;
    # no pending mutation exists, so any flush is evidence of a read violation.
    monkeypatch.setattr(db.session, "flush", forbidden_flush)
    try:
        response = ui4_app.test_client().get(
            "/api/v1/traders/history?per_page=1", headers=_headers(ui4_app)
        )
    finally:
        monkeypatch.setattr(db.session, "flush", original_flush)
    assert response.status_code == 200 and len(response.get_json()["trades"]) == 1
    assert flushed == []


def test_scaling_read_scope_admin_and_conflict_fail_closed_with_junit_payload(ui4_app, record_property):
    client = ui4_app.test_client()
    mine = client.get("/api/v1/scaling/my-progress", headers=_headers(ui4_app, 3))
    assert mine.status_code == 200
    body = mine.get_json()
    projection = body["data"]
    assert body["owner_context"] == {"user_id": 3, "tenant_id": 1}
    assert projection["total_profit"] == "0.00"
    assert projection["times_scaled"] == 0
    assert projection["is_eligible_for_scaling"] is False
    assert body["currency"] is None and body["scaling_enabled"] is False

    # A master sees only its CRM-scope downline; sibling and other tenant stay hidden.
    scoped = client.get("/api/v1/scaling/admin/all-users", headers=_headers(ui4_app, 2))
    assert scoped.status_code == 200
    assert [row["user_id"] for row in scoped.get_json()["data"]] == [3]
    assert client.get("/api/v1/scaling/admin/user/4", headers=_headers(ui4_app, 2)).status_code == 404
    assert client.get("/api/v1/scaling/admin/all-users", headers=_headers(ui4_app, 6)).status_code == 403
    root = client.get("/api/v1/scaling/admin/all-users", headers=_headers(ui4_app, 1))
    assert root.status_code == 200
    assert {row["user_id"] for row in root.get_json()["data"]} == {3, 4}

    with ui4_app.app_context():
        db.session.add(AccountScaling(id=202, user_id=3, current_tier=9,
                                      current_account_size=Decimal("1.00"),
                                      target_profit=Decimal("1.00"), total_profit=Decimal("0.00"),
                                      times_scaled=0, status="active"))
        db.session.commit()
    assert client.get("/api/v1/scaling/my-progress", headers=_headers(ui4_app, 3)).status_code == 409
    assert client.get("/api/v1/scaling/admin/all-users", headers=_headers(ui4_app, 1)).status_code == 409
    record_property("ui4_scaling_progress_response", json.dumps(body, sort_keys=True))


def test_scaling_mutations_are_auth_csrf_admin_ordered_and_preserve_legacy_rows(ui4_app):
    client = ui4_app.test_client()
    mutation_paths = [
        "/api/v1/scaling/initialize",
        "/api/v1/scaling/scale-up",
        "/api/v1/scaling/pause",
        "/api/v1/scaling/resume",
    ]
    for path in mutation_paths:
        assert client.post(path, json={}).status_code == 401
        assert client.post(path, json={}, headers=_headers(ui4_app, 3)).status_code == 503

    # Cookie sessions must satisfy the production token_required CSRF rule before denial.
    cookie_client = ui4_app.test_client()
    cookie_client.set_cookie("access_token", ui4_app.ui4_tokens[3])
    assert cookie_client.post("/api/v1/scaling/pause", json={}).status_code == 403
    from src.middleware.csrf_middleware import generate_csrf_token
    with ui4_app.app_context():
        csrf = generate_csrf_token(ui4_app.ui4_tokens[3])
    cookie_client.set_cookie("csrf_token", csrf)
    allowed_denial = cookie_client.post(
        "/api/v1/scaling/pause", json={"ignored": "body"}, headers={"X-CSRF-Token": csrf}
    )
    assert allowed_denial.status_code == 503
    assert allowed_denial.get_json()["code"] == "SCALING_EVIDENCE_NOT_CONFIGURED"

    # Admin authorization is checked before the canonical unavailable response.
    assert client.post("/api/v1/scaling/admin/user/3/update-profit", json={}, headers=_headers(ui4_app, 6)).status_code == 403
    assert client.post("/api/v1/scaling/admin/user/3/update-profit", json={}, headers=_headers(ui4_app, 2)).status_code == 503
    for endpoint in ("/api/v1/scaling/eligibility", "/api/v1/scaling/tiers"):
        response = client.get(endpoint, headers=_headers(ui4_app, 3))
        assert response.status_code == 503
        assert response.get_json()["code"] == "SCALING_EVIDENCE_NOT_CONFIGURED"
    with ui4_app.app_context():
        row = db.session.get(AccountScaling, 200)
        assert (row.current_tier, row.total_profit, row.status, row.is_eligible_for_scaling) == (
            1, Decimal("0.00"), "active", True
        )


def test_scaling_blocked_mutations_never_run_resource_sql(ui4_app):
    client = ui4_app.test_client()
    for path in (
        "/api/v1/scaling/initialize",
        "/api/v1/scaling/scale-up",
        "/api/v1/scaling/pause",
        "/api/v1/scaling/resume",
        "/api/v1/scaling/admin/user/3/update-profit",
    ):
        actor = 2 if "/admin/" in path else 3
        response, statements = _sql_count(
            ui4_app, lambda path=path, actor=actor: client.post(path, json={"user_id": 4}, headers=_headers(ui4_app, actor))
        )
        assert response.status_code == 503
        sql = "\n".join(statements)
        assert "account_scaling" not in sql and "challenges" not in sql and "trades" not in sql
