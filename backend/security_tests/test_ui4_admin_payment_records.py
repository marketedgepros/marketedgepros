"""Focused security contracts for the UI-4 admin payment record screens."""
from datetime import datetime, timedelta
from decimal import Decimal
import json

import pytest
from flask import Flask
from sqlalchemy import event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from src.database import db
from src.models.payment import Payment
from src.models.payment_approval import PaymentApprovalRequest
from src.models.tenant import Tenant
from src.models.token_blacklist import TokenBlacklist
from src.models.trading_program import Challenge, TradingProgram
from src.models.user import User
from src.utils.hierarchy_scoping import init_hierarchy_scoping


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_element, _compiler, **_kwargs):
    return "JSON"


@pytest.fixture
def ui4_admin_payments_app(monkeypatch):
    """A minimal real-route app with only private synthetic payment rows."""
    from src.services import session_service
    from src.routes.admin import admin_bp
    from src.routes.payment_approvals import bp as approvals_bp

    app = Flask("ui4-admin-payment-records-security")
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY="ui4-admin-payment-security-synthetic-key",
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=10),
        JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=1),
        PLATFORM_ROOT_USER_ID=1,
        EXPANDED_HIERARCHY_ENABLED=True,
    )
    db.init_app(app)
    init_hierarchy_scoping(db, User)
    monkeypatch.setattr(session_service, "get_redis", lambda: None)
    app.register_blueprint(admin_bp, url_prefix="/api/v1/admin")
    app.register_blueprint(approvals_bp)

    tables = [
        Tenant.__table__, User.__table__, TokenBlacklist.__table__, TradingProgram.__table__,
        Challenge.__table__, Payment.__table__, PaymentApprovalRequest.__table__,
    ]
    instant = datetime(2026, 10, 12, 12, 0, 0)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=tables)
        db.session.add_all([
            Tenant(id=1, name="Tenant one", subdomain="ui4-payment-one", status="active"),
            Tenant(id=2, name="Tenant two", subdomain="ui4-payment-two", status="active"),
            User(id=1, email="root@example.invalid", password_hash="x", first_name="Root", last_name="One",
                 role="supermaster", tenant_id=1, parent_id=None, tree_path="1", level=0,
                 can_create_same_role=True, is_active=True, is_verified=True),
            User(id=2, email="master@example.invalid", password_hash="x", first_name="Master", last_name="Two",
                 role="master", tenant_id=1, parent_id=1, tree_path="1/2", level=1,
                 is_active=True, is_verified=True),
            User(id=3, email="downline@example.invalid", password_hash="x", first_name="Downline", last_name="Three",
                 role="trader", tenant_id=1, parent_id=2, tree_path="1/2/3", level=2,
                 is_active=True, is_verified=True),
            User(id=4, email="foreign@example.invalid", password_hash="x", first_name="Foreign", last_name="Four",
                 role="trader", tenant_id=2, parent_id=None, tree_path="4", level=0,
                 is_active=True, is_verified=True),
            # Has the supermaster role but is not the configured, parentless root.
            User(id=5, email="child-super@example.invalid", password_hash="x", first_name="Child", last_name="Super",
                 role="supermaster", tenant_id=1, parent_id=1, tree_path="1/5", level=1,
                 can_create_same_role=False, is_active=True, is_verified=True),
            # Missing tenant rejects before records SQL despite an otherwise valid role/path.
            User(id=6, email="tenantless@example.invalid", password_hash="x", first_name="No", last_name="Tenant",
                 role="master", tenant_id=None, parent_id=1, tree_path="1/6", level=1,
                 is_active=True, is_verified=True),
            TradingProgram(id=1, tenant_id=1, name="Tenant one program", type="one_phase",
                           account_size=Decimal("1000.00"), price=Decimal("99.00"), is_active=True),
            TradingProgram(id=2, tenant_id=2, name="Tenant two program", type="one_phase",
                           account_size=Decimal("1000.00"), price=Decimal("99.00"), is_active=True),
        ])
        db.session.add_all([
            Challenge(id=1, user_id=3, program_id=1, status="pending", initial_balance=Decimal("1000.00"),
                      current_balance=Decimal("1000.00"), created_at=instant),
            # FK exists but user mismatches the approval's requested_for user.
            Challenge(id=2, user_id=2, program_id=1, status="pending", initial_balance=Decimal("1000.00"),
                      current_balance=Decimal("1000.00"), created_at=instant),
        ])
        db.session.add_all([
            Payment(id=1, user_id=3, amount=Decimal("101.25"), currency="USD", payment_method="stripe",
                    payment_type="credit_card", purpose="challenge_purchase", status="completed",
                    transaction_id="pi_private_1", provider_response="secret provider payload",
                    created_at=instant + timedelta(minutes=1)),
            # Valid foreign-brand payment is visible only to the explicit platform root.
            Payment(id=2, user_id=4, amount=Decimal("22.00"), currency="EUR", payment_method="paypal",
                    payment_type="credit_card", purpose="refund", status="refunded",
                    transaction_id="pi_private_2", provider_response="foreign secret",
                    created_at=instant + timedelta(minutes=2)),
            # Unknown legacy codes are represented as null, never relabeled or normalised.
            Payment(id=3, user_id=2, amount=Decimal("7.00"), currency="usd", payment_method="legacy method text!",
                    payment_type="cash", purpose="legacy purpose", status="legacy status",
                    transaction_id="pi_private_3", provider_response="legacy secret",
                    created_at=instant + timedelta(minutes=3)),
        ])
        db.session.flush()
        db.session.add_all([
            PaymentApprovalRequest(id=1, requested_by=2, requested_for=3, challenge_id=1, payment_id=1,
                                   amount=Decimal("101.25"), payment_type="cash", status="pending",
                                   created_at=instant + timedelta(minutes=1)),
            # Both nullable historic parents remain an incomplete, unverified row.
            PaymentApprovalRequest(id=2, requested_by=2, requested_for=3, challenge_id=None, payment_id=None,
                                   amount=Decimal("9.00"), payment_type="free", status="pending",
                                   created_at=instant + timedelta(minutes=2)),
            # Coherent foreign-brand row: root may view valid brands, downline cannot query pending.
            PaymentApprovalRequest(id=3, requested_by=4, requested_for=4, challenge_id=None, payment_id=2,
                                   amount=Decimal("22.00"), payment_type="cash", status="pending",
                                   created_at=instant + timedelta(minutes=3)),
            # Payment parent belongs to master, not requested_for trader: must remain hidden.
            PaymentApprovalRequest(id=4, requested_by=2, requested_for=3, challenge_id=None, payment_id=3,
                                   amount=Decimal("7.00"), payment_type="cash", status="pending",
                                   created_at=instant + timedelta(minutes=4)),
            # Self requester/recipient is a coherent same-tenant relationship.
            PaymentApprovalRequest(id=5, requested_by=2, requested_for=2, challenge_id=None, payment_id=3,
                                   amount=Decimal("7.00"), payment_type="free", status="pending",
                                   created_at=instant + timedelta(minutes=5)),
            # Cross-tenant requested parent is never coherent.
            PaymentApprovalRequest(id=6, requested_by=2, requested_for=4, challenge_id=None, payment_id=None,
                                   amount=Decimal("1.00"), payment_type="cash", status="pending",
                                   created_at=instant + timedelta(minutes=6)),
            # Challenge FK exists but belongs to a user other than requested_for.
            PaymentApprovalRequest(id=7, requested_by=2, requested_for=3, challenge_id=2, payment_id=None,
                                   amount=Decimal("1.00"), payment_type="cash", status="pending",
                                   created_at=instant + timedelta(minutes=7)),
        ])
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
        if any(table in statement.lower() for table in (
            "payments", "payment_approval_requests", "challenges", "trading_programs",
        ))
    ]


def test_ui4_admin_payment_payloads_are_exact_private_and_record_junit_properties(
    ui4_admin_payments_app, record_property, record_testsuite_property,
):
    """Root id=1/tenant=1 records the exact required page-one UI fixtures."""
    app = ui4_admin_payments_app
    client = app.test_client()

    payment_response = client.get("/api/v1/admin/payments?page=1&per_page=20", headers=_headers(app, 1))
    approval_response = client.get("/api/v1/payment-approvals/pending?page=1&per_page=20", headers=_headers(app, 1))
    assert payment_response.status_code == approval_response.status_code == 200
    payments = payment_response.get_json()
    approvals = approval_response.get_json()

    assert payments["owner_context"] == approvals["owner_context"] == {"user_id": 1, "tenant_id": 1}
    assert payments["record_verification"] == approvals["record_verification"] == "unverified_legacy"
    assert payments["settlement_enabled"] is approvals["settlement_enabled"] is False
    assert payments["filters"] == {"status": None, "type": None}
    assert approvals["filters"] == {"status": "pending"}
    assert payments["pagination"] == {"page": 1, "per_page": 20, "total": 3, "pages": 1}
    assert approvals["pagination"] == {"page": 1, "per_page": 20, "total": 4, "pages": 1}
    assert [row["id"] for row in payments["payments"]] == [3, 2, 1]
    assert [row["id"] for row in approvals["requests"]] == [5, 3, 2, 1]
    assert all(set(row) == {
        "id", "user_id", "amount", "currency", "payment_type", "payment_method", "status", "created_at",
    } for row in payments["payments"])
    assert all(set(row) == {
        "id", "requested_by", "requested_for", "challenge_id", "payment_id", "amount", "payment_type",
        "status", "created_at", "reviewed_at",
    } for row in approvals["requests"])
    assert payments["payments"][0] == {
        "id": 3, "user_id": 2, "amount": "7.00", "currency": None, "payment_type": None,
        "payment_method": "legacy method text!", "status": None, "created_at": "2026-10-12T12:03:00",
    }
    assert approvals["requests"][-1]["amount"] == "101.25"
    serialized = json.dumps({"payments": payments, "approvals": approvals}, sort_keys=True)
    assert all(secret not in serialized for secret in ("transaction_id", "provider_response", "pi_private", "secret", "email"))
    record_property("admin_payments_payload", json.dumps(payments, sort_keys=True))
    record_property("admin_approval_requests_payload", json.dumps(approvals, sort_keys=True))
    record_testsuite_property("admin_payments_payload", json.dumps(payments, sort_keys=True))
    record_testsuite_property("admin_approval_requests_payload", json.dumps(approvals, sort_keys=True))


def test_ui4_admin_payment_scope_is_root_or_downline_and_never_foreign(ui4_admin_payments_app):
    app = ui4_admin_payments_app
    client = app.test_client()

    downline = client.get("/api/v1/admin/payments", headers=_headers(app, 2))
    assert downline.status_code == 200
    assert [row["id"] for row in downline.get_json()["payments"]] == [3, 1]
    assert downline.get_json()["owner_context"] == {"user_id": 2, "tenant_id": 1}

    # Role alone is not platform root authority.  It must use the canonical scope error.
    child_super = client.get("/api/v1/payment-approvals/pending", headers=_headers(app, 5))
    assert child_super.status_code == 403
    assert child_super.get_json()["code"] == "ADMIN_PAYMENT_SCOPE_REQUIRED"
    master_pending = client.get("/api/v1/payment-approvals/pending", headers=_headers(app, 2))
    assert master_pending.status_code == 403

    with app.app_context():
        engine = db.engine
        statements = []

        def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", observe)
        try:
            missing_scope = client.get("/api/v1/admin/payments", headers=_headers(app, 6))
        finally:
            event.remove(engine, "before_cursor_execute", observe)
    assert missing_scope.status_code == 403
    assert missing_scope.get_json()["code"] == "ADMIN_PAYMENT_SCOPE_REQUIRED"
    assert _resource_sql(statements) == []


def test_ui4_admin_payment_invalid_query_precedes_resource_sql_and_bounds_pages(ui4_admin_payments_app):
    app = ui4_admin_payments_app
    client = app.test_client()
    with app.app_context():
        engine = db.engine
        for suffix in ("?page=01", "?per_page=0", "?page=1&page=2", "?unknown=1", "?type=credit_card", "?status="):
            statements = []

            def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
                statements.append(statement)

            event.listen(engine, "before_cursor_execute", observe)
            try:
                response = client.get("/api/v1/admin/payments" + suffix, headers=_headers(app, 1))
            finally:
                event.remove(engine, "before_cursor_execute", observe)
            assert response.status_code == 400
            assert response.get_json()["code"] == "INVALID_ADMIN_PAYMENT_QUERY"
            assert _resource_sql(statements) == []

        statements = []

        def observe_approval(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)

        event.listen(engine, "before_cursor_execute", observe_approval)
        try:
            approval_invalid = client.get(
                "/api/v1/payment-approvals/pending?status=pending", headers=_headers(app, 1),
            )
        finally:
            event.remove(engine, "before_cursor_execute", observe_approval)
        assert approval_invalid.status_code == 400
        assert approval_invalid.get_json()["code"] == "INVALID_ADMIN_PAYMENT_QUERY"
        assert _resource_sql(statements) == []

    after_end = client.get("/api/v1/admin/payments?page=6&per_page=2", headers=_headers(app, 1))
    assert after_end.status_code == 200
    assert after_end.get_json()["payments"] == []
    assert after_end.get_json()["pagination"] == {"page": 6, "per_page": 2, "total": 3, "pages": 2}
    filtered = client.get(
        "/api/v1/admin/payments?status=completed&type=challenge_purchase", headers=_headers(app, 1),
    )
    assert filtered.status_code == 200
    assert [row["id"] for row in filtered.get_json()["payments"]] == [1]


def test_ui4_admin_payment_reads_do_not_flush_and_approval_detail_is_scoped(ui4_admin_payments_app):
    app = ui4_admin_payments_app
    client = app.test_client()
    with app.app_context():
        pending = Payment(user_id=3, amount=Decimal("999.00"), currency="USD", payment_method="stripe",
                          payment_type="credit_card", purpose="challenge_purchase", status="pending")
        db.session.add(pending)
        writes = []

        def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
                writes.append(statement)

        event.listen(db.engine, "before_cursor_execute", observe)
        try:
            records = client.get("/api/v1/admin/payments", headers=_headers(app, 2))
        finally:
            event.remove(db.engine, "before_cursor_execute", observe)
        assert records.status_code == 200
        assert pending.id is None
        assert writes == []
        db.session.rollback()

    mine = client.get("/api/v1/payment-approvals/my-requests?page=1&per_page=20", headers=_headers(app, 2))
    assert mine.status_code == 200
    assert [row["id"] for row in mine.get_json()["requests"]] == [5, 2, 1]
    detail = client.get("/api/v1/payment-approvals/1", headers=_headers(app, 2))
    assert detail.status_code == 200
    assert set(detail.get_json()["request"]) == {
        "id", "requested_by", "requested_for", "challenge_id", "payment_id", "amount", "payment_type",
        "status", "created_at", "reviewed_at",
    }
    foreign = client.get("/api/v1/payment-approvals/3", headers=_headers(app, 2))
    absent = client.get("/api/v1/payment-approvals/999", headers=_headers(app, 1))
    trader = client.get("/api/v1/payment-approvals/1", headers=_headers(app, 3))
    assert foreign.status_code == absent.status_code == trader.status_code == 404
    assert all(response.get_json()["code"] == "ADMIN_PAYMENT_RECORD_NOT_FOUND" for response in (foreign, absent, trader))


def test_ui4_admin_payment_legacy_reject_stops_after_auth_csrf_before_body_sql_or_mail(
    ui4_admin_payments_app, monkeypatch,
):
    from src.services.payment_approval_service import (
        PaymentApprovalService, PaymentApprovalSettlementNotConfigured,
    )

    app = ui4_admin_payments_app
    client = app.test_client()
    mail_calls = []
    monkeypatch.setattr(
        PaymentApprovalService, "_notify_approval", lambda *args, **kwargs: mail_calls.append(1),
    )
    with app.app_context():
        statements = []

        def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)

        event.listen(db.engine, "before_cursor_execute", observe)
        try:
            with pytest.raises(PaymentApprovalSettlementNotConfigured):
                PaymentApprovalService.reject_request(1, 1, "attacker controlled")
        finally:
            event.remove(db.engine, "before_cursor_execute", observe)
    assert _resource_sql(statements) == []

    # An intentionally malformed body proves the handler returns before JSON parsing.
    response = client.post("/api/v1/payment-approvals/1/reject", data=b'{"rejection_reason":',
                           content_type="application/json", headers=_headers(app, 1))
    assert response.status_code == 503
    assert response.get_json()["code"] == "ORDER_SETTLEMENT_NOT_CONFIGURED"

    # Cookie auth keeps the existing CSRF check in front of the legacy reject gate.
    client.set_cookie("access_token", app.tokens[1])
    csrf = client.post("/api/v1/payment-approvals/1/reject", json={"rejection_reason": "x"})
    assert csrf.status_code == 403
    assert csrf.get_json()["code"] == "CSRF_INVALID"
    assert mail_calls == []
