"""PostgreSQL staging contracts for the UI-4 admin insight read projections."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import threading
import time

import pytest
from flask import Flask
from sqlalchemy import event, select


@pytest.fixture
def ui4_admin_insights_pg_app(staging_resources):
    """A private runner-created PostgreSQL app hosting both actual HTTP routes."""
    from src.database import db
    from src.models.payment import Payment
    from src.models.tenant import Tenant
    from src.models.token_blacklist import TokenBlacklist
    from src.models.trading_program import Challenge, TradingProgram
    from src.models.user import User
    from src.routes.admin import admin_bp
    from src.routes.analytics import analytics_bp
    from src.utils.hierarchy_scoping import init_hierarchy_scoping

    app = Flask("ui4-admin-insights-postgresql")
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI=staging_resources["pg_url"],
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY="ui4-admin-insights-staging-synthetic-key",
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=10),
        JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=1),
        PLATFORM_ROOT_USER_ID=1,
        EXPANDED_HIERARCHY_ENABLED=True,
    )
    db.init_app(app)
    init_hierarchy_scoping(db, User)
    app.register_blueprint(admin_bp, url_prefix="/api/v1/admin")
    app.register_blueprint(analytics_bp, url_prefix="/api/v1/analytics")

    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    with app.app_context():
        assert db.engine.dialect.name == "postgresql"
        db.session.add_all([
            Tenant(id=1, name="PG insight tenant", subdomain="pg-ui4-insight-one", status="active"),
            Tenant(id=2, name="PG insight foreign", subdomain="pg-ui4-insight-two", status="active"),
            User(id=1, email="pg-root@example.invalid", password_hash="x", first_name="Root", last_name="One",
                 role="supermaster", tenant_id=1, parent_id=None, tree_path="1", level=0,
                 can_create_same_role=True, is_active=True, is_verified=True, created_at=now - timedelta(days=3)),
            User(id=2, email="pg-master@example.invalid", password_hash="x", first_name="Master", last_name="Two",
                 role="master", tenant_id=1, parent_id=1, tree_path="1/2", level=1,
                 is_active=True, is_verified=True, created_at=now - timedelta(days=2)),
            User(id=3, email="pg-downline@example.invalid", password_hash="x", first_name="Downline", last_name="Three",
                 role="trader", tenant_id=1, parent_id=2, tree_path="1/2/3", level=2,
                 is_active=True, is_verified=True, created_at=now - timedelta(days=1)),
            User(id=4, email="pg-foreign@example.invalid", password_hash="x", first_name="Foreign", last_name="Four",
                 role="trader", tenant_id=2, parent_id=None, tree_path="4", level=0,
                 is_active=True, is_verified=True, created_at=now - timedelta(days=1)),
            User(id=6, email="pg-tenantless@example.invalid", password_hash="x", first_name="No", last_name="Tenant",
                 role="master", tenant_id=None, parent_id=1, tree_path="1/6", level=1,
                 is_active=True, is_verified=True, created_at=now - timedelta(days=1)),
        ])
        db.session.add_all([
            TradingProgram(id=1, tenant_id=1, name="PG tenant one program", type="one_phase",
                           account_size=Decimal("1000.00"), price=Decimal("99.00"), is_active=True),
            TradingProgram(id=2, tenant_id=2, name="PG tenant two program", type="one_phase",
                           account_size=Decimal("1000.00"), price=Decimal("99.00"), is_active=True),
        ])
        db.session.flush()
        db.session.add_all([
            Challenge(id=1, user_id=3, program_id=1, status="active", initial_balance=Decimal("1000.00"),
                      current_balance=Decimal("1000.00"), created_at=now - timedelta(days=1)),
            Challenge(id=2, user_id=2, program_id=1, status="unknown_legacy", initial_balance=Decimal("1000.00"),
                      current_balance=Decimal("1000.00"), created_at=now - timedelta(days=2)),
            Challenge(id=3, user_id=4, program_id=2, status="failed", initial_balance=Decimal("1000.00"),
                      current_balance=Decimal("1000.00"), created_at=now - timedelta(days=1)),
            Challenge(id=4, user_id=3, program_id=2, status="pending", initial_balance=Decimal("1000.00"),
                      current_balance=Decimal("1000.00"), created_at=now - timedelta(days=1)),
            Challenge(id=5, user_id=3, program_id=1, status="pending", initial_balance=Decimal("1000.00"),
                      current_balance=Decimal("1000.00"), created_at=now + timedelta(days=1)),
        ])
        db.session.add_all([
            Payment(id=1, user_id=3, amount=Decimal("101.25"), currency="USD", payment_method="stripe",
                    payment_type="credit_card", purpose="challenge_purchase", status="completed",
                    transaction_id="pg-insight-private-1", provider_response="provider secret", created_at=now - timedelta(days=1)),
            Payment(id=2, user_id=2, amount=Decimal("7.00"), currency="usd", payment_method="cash",
                    payment_type="cash", purpose="legacy", status="legacy",
                    transaction_id="pg-insight-private-2", provider_response="provider secret", created_at=now - timedelta(days=2)),
            Payment(id=3, user_id=4, amount=Decimal("22.00"), currency="EUR", payment_method="paypal",
                    payment_type="credit_card", purpose="refund", status="refunded",
                    transaction_id="pg-insight-private-3", provider_response="provider secret", created_at=now - timedelta(days=1)),
            Payment(id=4, user_id=3, amount=Decimal("9.00"), currency="USD", payment_method="stripe",
                    payment_type="credit_card", purpose="withdrawal", status="pending",
                    transaction_id="pg-insight-future", provider_response="provider secret", created_at=now + timedelta(days=1)),
            Payment(id=5, user_id=3, amount=Decimal("5.50"), currency=None, payment_method="cash",
                    payment_type="cash", purpose="withdrawal", status="pending",
                    transaction_id="pg-insight-null", provider_response="provider secret", created_at=None),
        ])
        db.session.flush()
        # Constructor ``None`` invokes the model default, so update the nullable
        # compatibility field explicitly to exercise dashboard-vs-analytics null handling.
        db.session.execute(Payment.__table__.update().where(Payment.id == 5).values(created_at=None))
        db.session.commit()
        app.tokens = {identity: db.session.get(User, identity).generate_access_token() for identity in (1, 2, 6)}
        db.session.remove()
    try:
        yield app
    finally:
        with app.app_context():
            db.session.rollback()
            db.session.remove()


def _headers(app, identity):
    return {"Authorization": "Bearer " + app.tokens[identity]}


def _resource_sql(statements):
    return [statement.lower() for statement in statements if "admin_insight_rows" in statement.lower()]


def test_ui4_admin_insights_postgresql_payload_timeout_query_count_and_preservation(
    ui4_admin_insights_pg_app,
):
    """One SQL snapshot per route; no write or financial aggregation is introduced."""
    from src.database import db
    from src.models.payment import Payment

    app = ui4_admin_insights_pg_app
    with app.app_context():
        before = [dict(row) for row in db.session.execute(select(Payment.__table__).order_by(Payment.id)).mappings()]
        statements, writes = [], []

        def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)
            if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
                writes.append(statement)

        event.listen(db.engine, "before_cursor_execute", observe)
        try:
            dashboard_response = app.test_client().get("/api/v1/admin/dashboard/stats", headers=_headers(app, 2))
            analytics_response = app.test_client().get(
                "/api/v1/analytics/comprehensive?days=7", headers=_headers(app, 2),
            )
        finally:
            event.remove(db.engine, "before_cursor_execute", observe)
        assert dashboard_response.status_code == analytics_response.status_code == 200
        dashboard = dashboard_response.get_json()
        analytics = analytics_response.get_json()
        assert dashboard["owner_context"] == analytics["owner_context"] == {"user_id": 2, "tenant_id": 1}
        assert dashboard["counts"] == {"users": 2, "challenges": 2, "payments": 3}
        assert analytics["counts"] == {"users": 2, "challenges": 2, "payments": 2}
        assert dashboard["recent_payments"][-1]["created_at"] is None
        assert analytics["recent_users"] == analytics["recent_payments"] == []
        assert len(analytics["daily_activity"]) == 7
        assert {key: sum(row[key] for row in analytics["daily_activity"]) for key in analytics["counts"]} == analytics["counts"]
        assert all("sum(" not in statement for statement in _resource_sql(statements))
        assert len(_resource_sql(statements)) == 2
        assert all("union all" in statement and "admin_insight_users" in statement for statement in _resource_sql(statements))
        assert sum("SET LOCAL statement_timeout = 1500" in statement for statement in statements) == 2
        assert writes == []
        db.session.expire_all()
        after = [dict(row) for row in db.session.execute(select(Payment.__table__).order_by(Payment.id)).mappings()]
        assert after == before

    # pytest's junit_logging=all captures these two actual Flask payloads in system-out.
    print("ADMIN_INSIGHT_DASHBOARD_HTTP_JSON=" + json.dumps(dashboard, sort_keys=True))
    print("ADMIN_INSIGHT_ANALYTICS_HTTP_JSON=" + json.dumps(analytics, sort_keys=True))


def test_ui4_admin_insights_postgresql_scope_validation_future_calendar_and_single_statement_snapshot_concurrency(
    ui4_admin_insights_pg_app,
):
    """A concurrent committed PG write cannot split the one-statement response snapshot."""
    from src.database import db
    from src.models.payment import Payment

    app = ui4_admin_insights_pg_app
    client = app.test_client()
    assert client.get("/api/v1/admin/dashboard/stats", headers=_headers(app, 1)).get_json()["counts"] == {
        "users": 4, "challenges": 3, "payments": 4,
    }
    assert client.get("/api/v1/analytics/comprehensive?days=7", headers=_headers(app, 2)).get_json()["counts"] == {
        "users": 2, "challenges": 2, "payments": 2,
    }
    assert client.get("/api/v1/admin/dashboard/stats", headers=_headers(app, 6)).status_code == 403

    with app.app_context():
        # Make the real aggregate scan long enough for the separate PG connection
        # to commit after the request statement has begun its MVCC snapshot.
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        db.session.execute(Payment.__table__.insert(), [
            {
                "id": 1000 + offset,
                "user_id": 3,
                "amount": Decimal("1.00"),
                "currency": "USD",
                "payment_method": "bulk",
                "payment_type": "credit_card",
                "purpose": "withdrawal",
                "status": "pending",
                "approval_status": "approved",
                "transaction_id": f"pg-insight-bulk-{offset}",
                "provider_response": "synthetic",
                "created_at": now - timedelta(days=1),
                "updated_at": now - timedelta(days=1),
            }
            for offset in range(8000)
        ])
        db.session.commit()
        started, finished = threading.Event(), threading.Event()
        writer_error = []

        def concurrent_writer():
            if not started.wait(timeout=5):
                writer_error.append("insight statement did not start")
                finished.set()
                return
            # The event is raised immediately before cursor.execute; this short
            # delay lets PostgreSQL establish the read statement's MVCC snapshot.
            time.sleep(0.01)
            try:
                with app.app_context():
                    with db.engine.begin() as connection:
                        connection.execute(Payment.__table__.insert().values(
                            id=99_999,
                            user_id=3,
                            amount=Decimal("2.00"),
                            currency="USD",
                            payment_method="concurrent",
                            payment_type="credit_card",
                            purpose="withdrawal",
                            status="pending",
                            approval_status="approved",
                            transaction_id="pg-insight-concurrent",
                            provider_response="synthetic",
                            created_at=now - timedelta(days=1),
                            updated_at=now - timedelta(days=1),
                        ))
            except Exception as exc:  # pragma: no cover - assertion below retains the diagnostic
                writer_error.append(repr(exc))
            finally:
                finished.set()

        def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
            if "admin_insight_rows" in statement.lower():
                started.set()

        thread = threading.Thread(target=concurrent_writer, daemon=True)
        event.listen(db.engine, "before_cursor_execute", observe)
        thread.start()
        try:
            response = client.get("/api/v1/analytics/comprehensive?days=7", headers=_headers(app, 2))
        finally:
            event.remove(db.engine, "before_cursor_execute", observe)
        assert finished.wait(timeout=10)
        thread.join(timeout=1)
        assert writer_error == []
        assert response.status_code == 200
        payload = response.get_json()
        # Existing two payments plus 8,000 pre-snapshot rows; the committed
        # writer's row is visible to a later statement, never a partial response.
        assert payload["counts"]["payments"] == 8_002
        assert sum(row["payments"] for row in payload["daily_activity"]) == 8_002
        db.session.expire_all()
        assert db.session.scalar(select(Payment.id).where(Payment.id == 99_999)) == 99_999
        assert sum(row["count"] for row in payload["distributions"]["payment_status"]) == 8_002


def test_ui4_admin_insights_postgresql_fractional_second_order(ui4_admin_insights_pg_app):
    from src.database import db
    from src.models.payment import Payment
    from src.models.user import User
    app = ui4_admin_insights_pg_app
    base = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0) - timedelta(days=1)
    with app.app_context():
        db.session.execute(User.__table__.update().where(User.id == 2).values(created_at=base + timedelta(microseconds=100000)))
        db.session.execute(User.__table__.update().where(User.id == 3).values(created_at=base))
        db.session.execute(Payment.__table__.update().where(Payment.id == 1).values(created_at=base + timedelta(microseconds=100000)))
        db.session.execute(Payment.__table__.update().where(Payment.id == 2).values(created_at=base))
        db.session.commit()
    response = app.test_client().get("/api/v1/admin/dashboard/stats", headers=_headers(app, 2))
    assert response.status_code == 200
    body = response.get_json()
    assert [row["id"] for row in body["recent_users"]] == [2, 3]
    assert [row["id"] for row in body["recent_payments"]][:2] == [1, 2]
    assert body["recent_users"][0]["created_at"] == (base + timedelta(microseconds=100000)).isoformat() + "Z"
    assert body["recent_users"][1]["created_at"] == base.isoformat() + "Z"
    assert all(row["created_at"] is None or row["created_at"].endswith("Z")
               for row in body["recent_users"] + body["recent_payments"])
