"""Focused real-HTTP security contracts for the UI-4 admin insight read endpoints."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json

import pytest
from flask import Flask
from sqlalchemy import event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from src.database import db
from src.models.payment import Payment
from src.models.tenant import Tenant
from src.models.token_blacklist import TokenBlacklist
from src.models.trading_program import Challenge, TradingProgram
from src.models.user import User
from src.utils.hierarchy_scoping import init_hierarchy_scoping


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_element, _compiler, **_kwargs):
    return "JSON"


@pytest.fixture
def ui4_admin_insights_app(monkeypatch):
    """Minimal real Flask routes and only synthetic, non-production records."""
    from src.services import session_service
    from src.routes.admin import admin_bp
    from src.routes.analytics import analytics_bp

    app = Flask("ui4-admin-insights-security")
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY="ui4-admin-insights-security-synthetic-key",
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=10),
        JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=1),
        PLATFORM_ROOT_USER_ID=1,
        EXPANDED_HIERARCHY_ENABLED=True,
    )
    db.init_app(app)
    init_hierarchy_scoping(db, User)
    monkeypatch.setattr(session_service, "get_redis", lambda: None)
    app.register_blueprint(admin_bp, url_prefix="/api/v1/admin")
    app.register_blueprint(analytics_bp, url_prefix="/api/v1/analytics")

    tables = [
        Tenant.__table__, User.__table__, TokenBlacklist.__table__, TradingProgram.__table__,
        Challenge.__table__, Payment.__table__,
    ]
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=tables)
        db.session.add_all([
            Tenant(id=1, name="Tenant one", subdomain="ui4-insights-one", status="active"),
            Tenant(id=2, name="Tenant two", subdomain="ui4-insights-two", status="active"),
            User(id=1, email="root@example.invalid", password_hash="x", first_name="Root", last_name="One",
                 role="supermaster", tenant_id=1, parent_id=None, tree_path="1", level=0,
                 can_create_same_role=True, is_active=True, is_verified=True, created_at=now - timedelta(days=3)),
            User(id=2, email="master@example.invalid", password_hash="x", first_name="Master", last_name="Two",
                 role="master", tenant_id=1, parent_id=1, tree_path="1/2", level=1,
                 is_active=True, is_verified=True, created_at=now - timedelta(days=2)),
            User(id=3, email="downline@example.invalid", password_hash="x", first_name="Downline", last_name="Three",
                 role="trader", tenant_id=1, parent_id=2, tree_path="1/2/3", level=2,
                 is_active=False, is_verified=True, created_at=now - timedelta(days=1)),
            User(id=4, email="foreign@example.invalid", password_hash="x", first_name="Foreign", last_name="Four",
                 role="trader", tenant_id=2, parent_id=None, tree_path="4", level=0,
                 is_active=True, is_verified=True, created_at=now - timedelta(days=1)),
            # A positive user ID with a missing tenant must refuse before records SQL.
            User(id=6, email="tenantless@example.invalid", password_hash="x", first_name="No", last_name="Tenant",
                 role="master", tenant_id=None, parent_id=1, tree_path="1/6", level=1,
                 is_active=True, is_verified=True, created_at=now - timedelta(days=1)),
            # Future user data is not a dashboard or analytics record.
            User(id=7, email="future@example.invalid", password_hash="x", first_name="Future", last_name="User",
                 role="trader", tenant_id=1, parent_id=2, tree_path="1/2/7", level=2,
                 is_active=True, is_verified=True, created_at=now + timedelta(days=1)),
        ])
        db.session.add_all([
            TradingProgram(id=1, tenant_id=1, name="Tenant one program", type="one_phase",
                           account_size=Decimal("1000.00"), price=Decimal("99.00"), is_active=True),
            TradingProgram(id=2, tenant_id=2, name="Tenant two program", type="one_phase",
                           account_size=Decimal("1000.00"), price=Decimal("99.00"), is_active=True),
        ])
        db.session.flush()
        db.session.add_all([
            Challenge(id=1, user_id=3, program_id=1, status="active", initial_balance=Decimal("1000.00"),
                      current_balance=Decimal("1000.00"), created_at=now - timedelta(days=1)),
            # Legacy code contributes to the required null distribution group.
            Challenge(id=2, user_id=2, program_id=1, status="legacy_status", initial_balance=Decimal("1000.00"),
                      current_balance=Decimal("1000.00"), created_at=now - timedelta(days=2)),
            Challenge(id=3, user_id=4, program_id=2, status="failed", initial_balance=Decimal("1000.00"),
                      current_balance=Decimal("1000.00"), created_at=now - timedelta(days=1)),
            # Program belongs to another tenant: coherency predicate must exclude it.
            Challenge(id=4, user_id=3, program_id=2, status="pending", initial_balance=Decimal("1000.00"),
                      current_balance=Decimal("1000.00"), created_at=now - timedelta(days=1)),
            # SQLite permits this synthetic dangling foreign key; the owner join must exclude it.
            Challenge(id=5, user_id=999, program_id=1, status="pending", initial_balance=Decimal("1000.00"),
                      current_balance=Decimal("1000.00"), created_at=now - timedelta(days=1)),
            Challenge(id=6, user_id=3, program_id=1, status="pending", initial_balance=Decimal("1000.00"),
                      current_balance=Decimal("1000.00"), created_at=now + timedelta(days=1)),
        ])
        db.session.add_all([
            Payment(id=1, user_id=3, amount=Decimal("101.25"), currency="USD", payment_method="stripe",
                    payment_type="credit_card", purpose="challenge_purchase", status="completed",
                    transaction_id="private-payment-1", provider_response="provider secret", created_at=now - timedelta(days=1)),
            Payment(id=2, user_id=2, amount=Decimal("7.00"), currency="usd", payment_method="cash",
                    payment_type="cash", purpose="legacy_purpose", status="legacy_status",
                    transaction_id="private-payment-2", provider_response="provider secret", created_at=now - timedelta(days=2)),
            Payment(id=3, user_id=4, amount=Decimal("22.00"), currency="EUR", payment_method="paypal",
                    payment_type="credit_card", purpose="refund", status="refunded",
                    transaction_id="private-payment-3", provider_response="provider secret", created_at=now - timedelta(days=1)),
            Payment(id=4, user_id=3, amount=Decimal("9.00"), currency="USD", payment_method="stripe",
                    payment_type="credit_card", purpose="withdrawal", status="pending",
                    transaction_id="private-payment-future", provider_response="provider secret", created_at=now + timedelta(days=1)),
            Payment(id=5, user_id=999, amount=Decimal("1.00"), currency="USD", payment_method="stripe",
                    payment_type="credit_card", purpose="withdrawal", status="pending",
                    transaction_id="private-payment-dangling", provider_response="provider secret", created_at=now - timedelta(days=1)),
            # Null legacy dates count only on dashboard and remain an unknown recent date.
            Payment(id=6, user_id=3, amount=Decimal("5.50"), currency=None, payment_method="cash",
                    payment_type="cash", purpose="withdrawal", status="pending",
                    transaction_id="private-payment-null-date", provider_response="provider secret", created_at=None),
            Payment(id=7, user_id=2, amount=Decimal("11.00"), currency="USD", payment_method="stripe",
                    payment_type="credit_card", purpose="withdrawal", status="failed",
                    transaction_id="private-payment-old", provider_response="provider secret", created_at=now - timedelta(days=10)),
        ])
        db.session.flush()
        # SQLAlchemy applies the column default to constructor ``None``; make this
        # compatibility record's nullable payment date genuinely unknown.
        db.session.execute(Payment.__table__.update().where(Payment.id == 6).values(created_at=None))
        db.session.commit()
        app.tokens = {identity: db.session.get(User, identity).generate_access_token() for identity in (1, 2, 3, 4, 6)}
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
        if "challenges" in statement.lower() or "payments" in statement.lower()
    ]


def _assert_shape(payload, *, days):
    assert set(payload) == {
        "owner_context", "record_verification", "settlement_enabled", "as_of", "filters", "counts",
        "distributions", "recent_users", "recent_payments", "daily_activity",
    }
    assert payload["record_verification"] == "unverified_legacy"
    assert payload["settlement_enabled"] is False
    assert payload["filters"] == {"days": days}
    assert payload["as_of"].endswith("Z")
    assert set(payload["counts"]) == {"users", "challenges", "payments"}
    assert all(isinstance(value, int) and value >= 0 for value in payload["counts"].values())
    allowed = {
        "user_roles": {"supermaster", "master", "affiliate", "trader", "guest"},
        "user_kyc": {"not_submitted", "pending", "approved", "rejected", "incomplete", "verified", "unverified"},
        "challenge_status": {"pending", "active", "completed", "passed", "failed", "funded", "cancelled"},
        "payment_status": {"pending", "completed", "failed", "refunded"},
    }
    source = {"user_roles": "users", "user_kyc": "users", "challenge_status": "challenges", "payment_status": "payments"}
    assert set(payload["distributions"]) == set(allowed)
    for key, rows in payload["distributions"].items():
        assert all(set(row) == {"code", "count"} for row in rows)
        assert all(row["code"] is None or row["code"] in allowed[key] for row in rows)
        assert len({row["code"] for row in rows}) == len(rows)
        assert sum(row["count"] for row in rows) == payload["counts"][source[key]]
    assert all(set(row) == {"id", "role", "is_active", "kyc_status", "created_at"} for row in payload["recent_users"])
    assert all(set(row) == {"id", "user_id", "amount", "currency", "payment_type", "status", "created_at"}
               for row in payload["recent_payments"])
    assert all(row["created_at"] is None or row["created_at"].endswith("Z")
               for row in payload["recent_users"] + payload["recent_payments"])


def test_ui4_admin_insights_http_payload_scopes_allowlists_and_junit_system_out(ui4_admin_insights_app):
    """Master's two real HTTP payloads contain only the canonical bounded fields."""
    app = ui4_admin_insights_app
    client = app.test_client()
    dashboard_response = client.get("/api/v1/admin/dashboard/stats", headers=_headers(app, 2))
    analytics_response = client.get("/api/v1/analytics/comprehensive?days=7", headers=_headers(app, 2))
    assert dashboard_response.status_code == analytics_response.status_code == 200
    dashboard = dashboard_response.get_json()
    analytics = analytics_response.get_json()
    _assert_shape(dashboard, days=None)
    _assert_shape(analytics, days=7)
    assert dashboard["owner_context"] == analytics["owner_context"] == {"user_id": 2, "tenant_id": 1}
    assert dashboard["counts"] == {"users": 2, "challenges": 2, "payments": 4}
    assert analytics["counts"] == {"users": 2, "challenges": 2, "payments": 2}
    assert dashboard["distributions"]["challenge_status"] == [{"code": "active", "count": 1}, {"code": None, "count": 1}]
    assert dashboard["distributions"]["payment_status"] == [
        {"code": "completed", "count": 1}, {"code": "failed", "count": 1},
        {"code": "pending", "count": 1}, {"code": None, "count": 1},
    ]
    assert [row["id"] for row in dashboard["recent_payments"]] == [1, 2, 7, 6]
    assert dashboard["recent_payments"][-1]["created_at"] is None
    assert dashboard["recent_payments"][1]["currency"] is None
    assert analytics["recent_users"] == analytics["recent_payments"] == []
    assert len(analytics["daily_activity"]) == 7
    assert {key: sum(row[key] for row in analytics["daily_activity"]) for key in analytics["counts"]} == analytics["counts"]
    serialized = json.dumps({"dashboard": dashboard, "analytics": analytics}, sort_keys=True)
    assert all(secret not in serialized for secret in (
        "email", "first_name", "last_name", "transaction_id", "provider_response", "private-payment", "provider secret",
    ))
    # pytest's junit_logging=all option writes captured stdout into <system-out>.
    print("ADMIN_INSIGHT_DASHBOARD_HTTP_JSON=" + json.dumps(dashboard, sort_keys=True))
    print("ADMIN_INSIGHT_ANALYTICS_HTTP_JSON=" + json.dumps(analytics, sort_keys=True))


def test_ui4_admin_insights_root_cross_tenant_but_downline_never_reads_foreign_or_dangling(ui4_admin_insights_app):
    app = ui4_admin_insights_app
    client = app.test_client()
    root = client.get("/api/v1/admin/dashboard/stats", headers=_headers(app, 1))
    master = client.get("/api/v1/admin/dashboard/stats", headers=_headers(app, 2))
    assert root.status_code == master.status_code == 200
    assert root.get_json()["counts"] == {"users": 4, "challenges": 3, "payments": 5}
    assert master.get_json()["counts"] == {"users": 2, "challenges": 2, "payments": 4}
    assert 3 in [row["id"] for row in root.get_json()["recent_payments"]]
    assert 3 not in [row["id"] for row in master.get_json()["recent_payments"]]

    with app.app_context():
        statements = []

        def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)

        event.listen(db.engine, "before_cursor_execute", observe)
        try:
            no_tenant = client.get("/api/v1/admin/dashboard/stats", headers=_headers(app, 6))
        finally:
            event.remove(db.engine, "before_cursor_execute", observe)
    assert no_tenant.status_code == 403
    assert no_tenant.get_json()["code"] == "ADMIN_INSIGHTS_SCOPE_REQUIRED"
    assert _resource_sql(statements) == []


def test_ui4_admin_insights_rejects_all_noncanonical_queries_before_resource_sql(ui4_admin_insights_app):
    app = ui4_admin_insights_app
    client = app.test_client()
    invalid = (
        ("/api/v1/admin/dashboard/stats?days=30", 1),
        ("/api/v1/analytics/comprehensive?days=01", 2),
        ("/api/v1/analytics/comprehensive?days=7&days=30", 2),
        ("/api/v1/analytics/comprehensive?unknown=1", 2),
        ("/api/v1/analytics/comprehensive?days=0", 2),
        ("/api/v1/analytics/comprehensive?days=99999999999", 2),
        ("/api/v1/analytics/comprehensive?days=%D9%A7", 2),
    )
    with app.app_context():
        for url, identity in invalid:
            statements = []

            def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
                statements.append(statement)

            event.listen(db.engine, "before_cursor_execute", observe)
            try:
                response = client.get(url, headers=_headers(app, identity))
            finally:
                event.remove(db.engine, "before_cursor_execute", observe)
            assert response.status_code == 400
            assert response.get_json()["code"] == "INVALID_ADMIN_INSIGHTS_QUERY"
            assert _resource_sql(statements) == []


def test_ui4_admin_insights_snapshot_is_one_resource_statement_no_flush_and_utc_calendar(ui4_admin_insights_app):
    app = ui4_admin_insights_app
    client = app.test_client()
    with app.app_context():
        pending = Payment(user_id=3, amount=Decimal("999.00"), currency="USD", payment_method="stripe",
                          payment_type="credit_card", purpose="withdrawal", status="pending")
        db.session.add(pending)
        statements, writes = [], []

        def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)
            if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
                writes.append(statement)

        event.listen(db.engine, "before_cursor_execute", observe)
        try:
            dashboard = client.get("/api/v1/admin/dashboard/stats", headers=_headers(app, 2))
            analytics = client.get("/api/v1/analytics/comprehensive?days=7", headers=_headers(app, 2))
        finally:
            event.remove(db.engine, "before_cursor_execute", observe)
        assert dashboard.status_code == analytics.status_code == 200
        assert pending.id is None
        assert writes == []
        assert len(_resource_sql(statements)) == 2
        assert all(statement.count("select") >= 1 and "union all" in statement for statement in _resource_sql(statements))
        daily = analytics.get_json()["daily_activity"]
        as_of_day = datetime.fromisoformat(analytics.get_json()["as_of"].replace("Z", "+00:00")).date()
        assert [row["date"] for row in daily] == [
            (as_of_day - timedelta(days=6 - offset)).isoformat() for offset in range(7)
        ]
        assert all(row["date"] <= as_of_day.isoformat() for row in daily)
        db.session.rollback()


def test_ui4_admin_insights_internal_days_type_is_exact_before_sql(ui4_admin_insights_app):
    from src.services.admin_insights_read import AdminInsightsReadService, AdminInsightsQueryInvalid
    with ui4_admin_insights_app.app_context():
        actor = db.session.get(User, 2)
        statements = []
        def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)
        event.listen(db.engine, "before_cursor_execute", observe)
        try:
            for value in (30.0, "30", True, False, None, [], {}):
                with pytest.raises(AdminInsightsQueryInvalid):
                    AdminInsightsReadService.comprehensive(actor, value)
        finally:
            event.remove(db.engine, "before_cursor_execute", observe)
        assert statements == []


def test_ui4_admin_insights_fractional_seconds_sort_by_time_not_iso_text(ui4_admin_insights_app):
    app = ui4_admin_insights_app
    base = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0) - timedelta(days=1)
    with app.app_context():
        for model in (User, Payment):
            older_id, newer_id = (3, 2) if model is User else (2, 1)
            db.session.execute(model.__table__.update().where(model.id == older_id).values(created_at=base))
            db.session.execute(model.__table__.update().where(model.id == newer_id).values(created_at=base + timedelta(microseconds=100000)))
        db.session.commit()
    response = app.test_client().get("/api/v1/admin/dashboard/stats", headers=_headers(app, 2))
    assert response.status_code == 200
    body = response.get_json()
    assert [row["id"] for row in body["recent_users"]] == [2, 3]
    assert [row["id"] for row in body["recent_payments"]][:2] == [1, 2]
    assert body["recent_users"][0]["created_at"].endswith(".100000Z")
    assert body["recent_users"][1]["created_at"] == base.isoformat() + "Z"
