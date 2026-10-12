"""PostgreSQL staging verification for the UI-4 admin payment read projections."""
from datetime import datetime, timedelta
from decimal import Decimal
import json

import pytest
from flask import Flask
from sqlalchemy import event, select


@pytest.fixture
def ui4_admin_payments_pg_app(staging_resources):
    """A private Unix-socket PostgreSQL host for the two real admin read routes."""
    from src.database import db
    from src.models.payment import Payment
    from src.models.payment_approval import PaymentApprovalRequest
    from src.models.tenant import Tenant
    from src.models.token_blacklist import TokenBlacklist
    from src.models.trading_program import Challenge, TradingProgram
    from src.models.user import User
    from src.routes.admin import admin_bp
    from src.routes.payment_approvals import bp as approvals_bp
    from src.utils.hierarchy_scoping import init_hierarchy_scoping

    app = Flask("ui4-admin-payment-records-postgresql")
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI=staging_resources["pg_url"],
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY="ui4-admin-payment-staging-synthetic-key",
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=10),
        JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=1),
        PLATFORM_ROOT_USER_ID=1,
        EXPANDED_HIERARCHY_ENABLED=True,
    )
    db.init_app(app)
    init_hierarchy_scoping(db, User)
    app.register_blueprint(admin_bp, url_prefix="/api/v1/admin")
    app.register_blueprint(approvals_bp)

    tables = [
        Tenant.__table__, User.__table__, TokenBlacklist.__table__, TradingProgram.__table__,
        Challenge.__table__, Payment.__table__, PaymentApprovalRequest.__table__,
    ]
    instant = datetime(2026, 10, 12, 13, 0, 0)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=tables)
        # The shared staging fixture truncates its own tables before this fixture;
        # this focused table is owned here and must also start empty.
        db.session.execute(PaymentApprovalRequest.__table__.delete())
        db.session.add_all([
            Tenant(id=1, name="PG payment tenant", subdomain="pg-ui4-payment-one", status="active"),
            Tenant(id=2, name="PG payment foreign", subdomain="pg-ui4-payment-two", status="active"),
        ])
        db.session.flush()
        root = User(id=1, email="pg-root@example.invalid", password_hash="x", first_name="Root", last_name="One",
                    role="supermaster", tenant_id=1, parent_id=None, tree_path="1", level=0,
                    can_create_same_role=True, is_active=True, is_verified=True)
        db.session.add(root)
        db.session.flush()
        db.session.add_all([
            User(id=2, email="pg-master@example.invalid", password_hash="x", first_name="Master", last_name="Two",
                 role="master", tenant_id=1, parent_id=1, tree_path="1/2", level=1,
                 is_active=True, is_verified=True),
            User(id=3, email="pg-downline@example.invalid", password_hash="x", first_name="Downline", last_name="Three",
                 role="trader", tenant_id=1, parent_id=2, tree_path="1/2/3", level=2,
                 is_active=True, is_verified=True),
            User(id=4, email="pg-foreign@example.invalid", password_hash="x", first_name="Foreign", last_name="Four",
                 role="trader", tenant_id=2, parent_id=None, tree_path="4", level=0,
                 is_active=True, is_verified=True),
        ])
        db.session.add_all([
            TradingProgram(id=1, tenant_id=1, name="PG payment program", type="one_phase",
                           account_size=Decimal("1000.00"), price=Decimal("99.00"), is_active=True),
            TradingProgram(id=2, tenant_id=2, name="PG payment foreign program", type="one_phase",
                           account_size=Decimal("1000.00"), price=Decimal("99.00"), is_active=True),
        ])
        db.session.flush()
        db.session.add(Challenge(id=1, user_id=3, program_id=1, status="pending", initial_balance=Decimal("1000.00"),
                                 current_balance=Decimal("1000.00"), created_at=instant))
        db.session.add_all([
            Payment(id=1, user_id=3, amount=Decimal("101.25"), currency="USD", payment_method="stripe",
                    payment_type="credit_card", purpose="challenge_purchase", status="completed",
                    transaction_id="pg-private-1", provider_response="pg provider secret",
                    created_at=instant + timedelta(minutes=1)),
            Payment(id=2, user_id=4, amount=Decimal("22.00"), currency="EUR", payment_method="paypal",
                    payment_type="credit_card", purpose="refund", status="refunded",
                    transaction_id="pg-private-2", provider_response="foreign provider secret",
                    created_at=instant + timedelta(minutes=2)),
            Payment(id=3, user_id=2, amount=Decimal("7.00"), currency="usd", payment_method="legacy text!",
                    payment_type="cash", purpose="legacy", status="legacy",
                    transaction_id="pg-private-3", provider_response="legacy provider secret",
                    created_at=instant + timedelta(minutes=3)),
        ])
        db.session.flush()
        db.session.add_all([
            PaymentApprovalRequest(id=1, requested_by=2, requested_for=3, challenge_id=1, payment_id=1,
                                   amount=Decimal("101.25"), payment_type="cash", status="pending",
                                   created_at=instant + timedelta(minutes=1)),
            PaymentApprovalRequest(id=2, requested_by=2, requested_for=3, challenge_id=None, payment_id=None,
                                   amount=Decimal("9.00"), payment_type="free", status="pending",
                                   created_at=instant + timedelta(minutes=2)),
            PaymentApprovalRequest(id=3, requested_by=4, requested_for=4, challenge_id=None, payment_id=2,
                                   amount=Decimal("22.00"), payment_type="cash", status="pending",
                                   created_at=instant + timedelta(minutes=3)),
        ])
        db.session.commit()
        app.tokens = {identity: db.session.get(User, identity).generate_access_token() for identity in (1, 2, 3, 4)}

    try:
        yield app
    finally:
        with app.app_context():
            db.session.rollback()
            PaymentApprovalRequest.__table__.drop(db.engine, checkfirst=True)
            db.session.remove()


def _headers(app, identity):
    return {"Authorization": "Bearer " + app.tokens[identity]}


def test_ui4_admin_payment_postgresql_payload_timeout_snapshot_and_no_writes(
    ui4_admin_payments_pg_app, record_property, record_testsuite_property,
):
    """PG confirms exact string scalars, one-root scope, timeout and row preservation."""
    from src.database import db
    from src.models.payment import Payment
    from src.models.payment_approval import PaymentApprovalRequest

    app = ui4_admin_payments_pg_app
    with app.app_context():
        assert db.engine.dialect.name == "postgresql"
        before = {
            "payments": [dict(row) for row in db.session.execute(select(Payment.__table__).order_by(Payment.id)).mappings()],
            "requests": [dict(row) for row in db.session.execute(
                select(PaymentApprovalRequest.__table__).order_by(PaymentApprovalRequest.id)
            ).mappings()],
        }
        writes = []
        statements = []

        def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)
            if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
                writes.append(statement)

        event.listen(db.engine, "before_cursor_execute", observe)
        try:
            payments_response = app.test_client().get(
                "/api/v1/admin/payments?page=1&per_page=20", headers=_headers(app, 1),
            )
            requests_response = app.test_client().get(
                "/api/v1/payment-approvals/pending?page=1&per_page=20", headers=_headers(app, 1),
            )
        finally:
            event.remove(db.engine, "before_cursor_execute", observe)
        assert payments_response.status_code == requests_response.status_code == 200
        payments = payments_response.get_json()
        requests = requests_response.get_json()
        assert payments["owner_context"] == requests["owner_context"] == {"user_id": 1, "tenant_id": 1}
        assert payments["record_verification"] == requests["record_verification"] == "unverified_legacy"
        assert payments["settlement_enabled"] is requests["settlement_enabled"] is False
        assert payments["filters"] == {"status": None, "type": None}
        assert requests["filters"] == {"status": "pending"}
        assert payments["pagination"] == {"page": 1, "per_page": 20, "total": 3, "pages": 1}
        assert requests["pagination"] == {"page": 1, "per_page": 20, "total": 3, "pages": 1}
        assert [row["id"] for row in payments["payments"]] == [3, 2, 1]
        assert [row["id"] for row in requests["requests"]] == [3, 2, 1]
        assert all(set(row) == {
            "id", "user_id", "amount", "currency", "payment_type", "payment_method", "status", "created_at",
        } for row in payments["payments"])
        assert all(set(row) == {
            "id", "requested_by", "requested_for", "challenge_id", "payment_id", "amount", "payment_type",
            "status", "created_at", "reviewed_at",
        } for row in requests["requests"])
        assert payments["payments"][0]["amount"] == "7.00"
        assert payments["payments"][0]["currency"] is None
        assert payments["payments"][0]["status"] is None
        assert writes == []
        assert sum("SET LOCAL statement_timeout = 1500" in statement for statement in statements) == 2
        db.session.expire_all()
        after = {
            "payments": [dict(row) for row in db.session.execute(select(Payment.__table__).order_by(Payment.id)).mappings()],
            "requests": [dict(row) for row in db.session.execute(
                select(PaymentApprovalRequest.__table__).order_by(PaymentApprovalRequest.id)
            ).mappings()],
        }
        assert after == before

    record_property("admin_payments_payload", json.dumps(payments, sort_keys=True))
    record_property("admin_approval_requests_payload", json.dumps(requests, sort_keys=True))
    record_testsuite_property("admin_payments_payload", json.dumps(payments, sort_keys=True))
    record_testsuite_property("admin_approval_requests_payload", json.dumps(requests, sort_keys=True))


def test_ui4_admin_payment_postgresql_downline_filter_and_invalid_query_before_records_sql(ui4_admin_payments_pg_app):
    """PG confirms hierarchy scope, filter efficacy and no records SQL on invalid syntax."""
    from src.database import db

    app = ui4_admin_payments_pg_app
    client = app.test_client()
    downline = client.get("/api/v1/admin/payments?status=completed&type=challenge_purchase", headers=_headers(app, 2))
    assert downline.status_code == 200
    assert [row["id"] for row in downline.get_json()["payments"]] == [1]

    with app.app_context():
        statements = []

        def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)

        event.listen(db.engine, "before_cursor_execute", observe)
        try:
            invalid = client.get("/api/v1/admin/payments?page=01", headers=_headers(app, 1))
        finally:
            event.remove(db.engine, "before_cursor_execute", observe)
    assert invalid.status_code == 400
    assert invalid.get_json()["code"] == "INVALID_ADMIN_PAYMENT_QUERY"
    resource = [statement.lower() for statement in statements if any(table in statement.lower() for table in (
        "payments", "payment_approval_requests", "challenges", "trading_programs",
    ))]
    assert resource == []
