"""Focused security contracts for the UI-4 admin challenge closure screen."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from flask import Flask
from sqlalchemy import event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from src.database import db
from src.models.mt5_models import MT5Account
from src.models.tenant import Tenant
from src.models.token_blacklist import TokenBlacklist
from src.models.trading_program import Challenge, TradingProgram
from src.models.user import User
from src.utils.hierarchy_scoping import init_hierarchy_scoping


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_element, _compiler, **_kwargs):
    return "JSON"


@pytest.fixture
def ui4_closure_challenges_app(monkeypatch):
    """A minimal real challenge blueprint with only synthetic private records."""
    from src.routes.challenges import challenges_bp
    from src.services import session_service

    app = Flask("ui4-closure-challenges-security")
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY="ui4-closure-challenges-synthetic-key",
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=10),
        JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=1),
        PLATFORM_ROOT_USER_ID=1,
        EXPANDED_HIERARCHY_ENABLED=True,
    )
    db.init_app(app)
    init_hierarchy_scoping(db, User)
    monkeypatch.setattr(session_service, "get_redis", lambda: None)
    app.register_blueprint(challenges_bp, url_prefix="/api/v1/challenges")

    tables = [
        Tenant.__table__, User.__table__, TokenBlacklist.__table__, TradingProgram.__table__,
        Challenge.__table__, MT5Account.__table__,
    ]
    instant = datetime(2026, 10, 12, 12, 0, 0)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=tables)
        db.session.add_all([
            Tenant(id=1, name="Synthetic one", subdomain="closure-one", status="active"),
            Tenant(id=2, name="Synthetic two", subdomain="closure-two", status="active"),
            User(id=1, email="root@example.invalid", password_hash="x", first_name="Root", last_name="One",
                 role="supermaster", tenant_id=1, parent_id=None, tree_path="1", level=0,
                 can_create_same_role=True, is_active=True, is_verified=True),
            User(id=2, email="master@example.invalid", password_hash="x", first_name="Master", last_name="Two",
                 role="master", tenant_id=1, parent_id=1, tree_path="1/2", level=1,
                 is_active=True, is_verified=True),
            User(id=3, email="downline@example.invalid", password_hash="x", first_name="Down", last_name="Line",
                 role="trader", tenant_id=1, parent_id=2, tree_path="1/2/3", level=2,
                 is_active=True, is_verified=True),
            User(id=4, email="peer@example.invalid", password_hash="x", first_name="Peer", last_name="Trader",
                 role="trader", tenant_id=1, parent_id=1, tree_path="1/4", level=1,
                 is_active=True, is_verified=True),
            User(id=5, email="foreign@example.invalid", password_hash="x", first_name="Foreign", last_name="Trader",
                 role="trader", tenant_id=2, parent_id=None, tree_path="5", level=0,
                 is_active=True, is_verified=True),
            User(id=6, email="tenantless@example.invalid", password_hash="x", first_name="No", last_name="Tenant",
                 role="master", tenant_id=None, parent_id=1, tree_path="1/6", level=1,
                 is_active=True, is_verified=True),
        ])
        db.session.add_all([
            TradingProgram(id=10, tenant_id=1, name="Tenant one program", type="one_phase",
                           account_size=Decimal("10000.00"), price=Decimal("99.00"), is_active=True),
            TradingProgram(id=20, tenant_id=2, name="Tenant two program", type="one_phase",
                           account_size=Decimal("10000.00"), price=Decimal("99.00"), is_active=True),
        ])
        db.session.add_all([
            Challenge(id=101, user_id=3, program_id=10, status="active", payment_status="paid",
                      initial_balance=Decimal("0.00"), current_balance=None, max_drawdown=Decimal("-0.00"),
                      current_phase=0, total_phases=2, created_at=instant),
            Challenge(id=102, user_id=4, program_id=10, status="funded", payment_status="paid",
                      initial_balance=Decimal("25000.00"), current_balance=Decimal("25001.10"),
                      current_phase=1, total_phases=2, created_at=instant + timedelta(minutes=1)),
            Challenge(id=103, user_id=5, program_id=20, status="active", payment_status="pending",
                      initial_balance=Decimal("1000.00"), current_balance=Decimal("1000.00"),
                      current_phase=1, total_phases=1, created_at=instant + timedelta(minutes=2)),
            # The owner exists but program tenant conflicts; it is not a readable challenge.
            Challenge(id=104, user_id=3, program_id=20, status="active", payment_status="paid",
                      initial_balance=Decimal("9.00"), current_balance=Decimal("9.00"),
                      current_phase=1, total_phases=1, created_at=instant + timedelta(minutes=3)),
        ])
        db.session.flush()
        db.session.add(MT5Account(
            id=501, user_id=3, challenge_id=101, mt5_login="RECORDED501", mt5_password_encrypted="synthetic",
            balance=Decimal("0.00"), equity=None, status="active", created_at=instant, updated_at=instant,
        ))
        db.session.commit()
        app.tokens = {identity: db.session.get(User, identity).generate_access_token() for identity in range(1, 7)}
        db.session.remove()

    try:
        yield app
    finally:
        with app.app_context():
            db.session.remove()
            db.metadata.drop_all(bind=db.engine, tables=list(reversed(tables)))
            db.engine.dispose()


def _headers(app, identity):
    return {"Authorization": "Bearer " + app.tokens[identity]}


def _resource_sql(statements):
    return [
        statement.lower() for statement in statements
        if any(table in statement.lower() for table in ("challenges", "trading_programs", "mt5_accounts"))
    ]


def test_ui4_closure_challenge_list_and_detail_are_exact_scoped_and_private(ui4_closure_challenges_app):
    app = ui4_closure_challenges_app
    client = app.test_client()
    listing = client.get("/api/v1/challenges/admin/all?page=1&per_page=20&status=active", headers=_headers(app, 1))
    assert listing.status_code == 200
    payload = listing.get_json()
    assert payload["owner_context"] == {"user_id": 1, "tenant_id": 1}
    assert payload["data_status"] == "unverified_legacy"
    assert payload["provider_authenticated"] is False
    assert payload["filters"] == {"status": "active", "include_mt5": True}
    assert payload["pagination"] == {"page": 1, "per_page": 20, "total": 2, "pages": 1}
    assert [row["id"] for row in payload["challenges"]] == [103, 101]
    owned = next(row for row in payload["challenges"] if row["id"] == 101)
    assert owned["current_phase"] == 0
    assert owned["initial_balance"] == "0.00" and owned["current_balance"] is None
    # SQLite normalizes persisted Numeric -0.00 to 0.00; the response remains a
    # JSON decimal string and never crosses a float boundary.
    assert owned["max_drawdown_observed"] == "0.00"
    assert owned["mt5_account"]["balance"] == "0.00"
    assert "mt5_password" not in str(owned)

    detail = client.get("/api/v1/challenges/admin/101?include_mt5=false", headers=_headers(app, 1))
    assert detail.status_code == 200
    detail_payload = detail.get_json()
    assert detail_payload["owner_context"] == {"user_id": 1, "tenant_id": 1}
    assert detail_payload["filters"] == {"include_mt5": False}
    assert detail_payload["challenge"]["mt5_account_binding"] == "not_requested"
    assert detail_payload["challenge"]["mt5_account"] is None


def test_ui4_closure_challenge_scope_is_root_or_downline_and_detail_hides_foreign(ui4_closure_challenges_app):
    app = ui4_closure_challenges_app
    client = app.test_client()
    master_list = client.get("/api/v1/challenges/admin/all", headers=_headers(app, 2))
    assert master_list.status_code == 200
    assert [row["id"] for row in master_list.get_json()["challenges"]] == [101]
    assert master_list.get_json()["owner_context"] == {"user_id": 2, "tenant_id": 1}
    assert client.get("/api/v1/challenges/admin/102", headers=_headers(app, 2)).status_code == 404
    assert client.get("/api/v1/challenges/admin/103", headers=_headers(app, 2)).status_code == 404
    assert client.get("/api/v1/challenges/admin/104", headers=_headers(app, 1)).status_code == 404

    with app.app_context():
        statements = []

        def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)

        event.listen(db.engine, "before_cursor_execute", observe)
        try:
            missing_scope = client.get("/api/v1/challenges/admin/all", headers=_headers(app, 6))
        finally:
            event.remove(db.engine, "before_cursor_execute", observe)
    assert missing_scope.status_code == 403
    assert missing_scope.get_json()["code"] == "ADMIN_CHALLENGE_SCOPE_REQUIRED"
    assert _resource_sql(statements) == []


def test_ui4_closure_challenge_invalid_queries_and_reads_do_not_touch_or_flush_resources(ui4_closure_challenges_app):
    app = ui4_closure_challenges_app
    client = app.test_client()
    with app.app_context():
        for suffix, expected_code in (
            ("?page=01", "PAGINATION_INVALID"),
            ("?per_page=101", "PAGINATION_INVALID"),
            ("?page=502&per_page=20", "PAGINATION_INVALID"),
            ("?status=", "QUERY_INVALID"),
            ("?unknown=1", "QUERY_INVALID"),
            ("?include_mt5=true&include_mt5=false", "QUERY_INVALID"),
        ):
            statements = []

            def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
                statements.append(statement)

            event.listen(db.engine, "before_cursor_execute", observe)
            try:
                response = client.get("/api/v1/challenges/admin/all" + suffix, headers=_headers(app, 1))
            finally:
                event.remove(db.engine, "before_cursor_execute", observe)
            assert response.status_code == 400
            assert response.get_json()["code"] == expected_code
            assert _resource_sql(statements) == []

        pending = Challenge(user_id=3, program_id=10, status="pending", payment_status="pending")
        db.session.add(pending)
        writes = []

        def observe_writes(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
                writes.append(statement)

        event.listen(db.engine, "before_cursor_execute", observe_writes)
        try:
            response = client.get("/api/v1/challenges/admin/all", headers=_headers(app, 2))
        finally:
            event.remove(db.engine, "before_cursor_execute", observe_writes)
        assert response.status_code == 200
        assert pending.id is None
        assert writes == []
        db.session.rollback()


def test_ui4_closure_challenge_unverified_mutations_refuse_after_auth_before_body_or_resource_sql(ui4_closure_challenges_app):
    app = ui4_closure_challenges_app
    client = app.test_client()
    with app.app_context():
        statements = []

        def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)

        event.listen(db.engine, "before_cursor_execute", observe)
        try:
            responses = [
                client.post("/api/v1/challenges/", data=b"{", content_type="application/json", headers=_headers(app, 3)),
                client.post("/api/v1/challenges/101/fund", data=b"{", content_type="application/json", headers=_headers(app, 1)),
                client.delete("/api/v1/challenges/admin/101", data=b"{", content_type="application/json", headers=_headers(app, 1)),
            ]
        finally:
            event.remove(db.engine, "before_cursor_execute", observe)
    assert [(response.status_code, response.get_json()["code"]) for response in responses] == [
        (503, "ORDER_SETTLEMENT_NOT_CONFIGURED"),
        (503, "MT5_PROVIDER_NOT_CONFIGURED"),
        (503, "TRADING_EVIDENCE_NOT_CONFIGURED"),
    ]
    assert _resource_sql(statements) == []
