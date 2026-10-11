"""Full-app regressions for the temporary Stage4a legacy payment boundary.

The tests use real Flask registration, database-backed principals, and signed JWTs.
Mocks are restricted to outbound provider/fulfillment canaries; local Stripe and
NOWPayments signature verification uses genuine HMAC/SDK logic.
"""
from datetime import timedelta
from decimal import Decimal
import hashlib
import hmac
import json
import time

import pytest
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles


SETTLEMENT_CODE = "ORDER_SETTLEMENT_NOT_CONFIGURED"


@pytest.fixture(scope="session", autouse=True)
def sqlite_jsonb_compiler():
    """Allow the explicitly selected Tenant table to be created on SQLite."""
    @compiles(JSONB, "sqlite")
    def compile_jsonb(_element, _compiler, **_kwargs):
        return "JSON"


@pytest.fixture
def application(sqlite_jsonb_compiler):
    """Build the real app against only the tables this boundary exercises."""
    from src.app import create_app
    from src.database import db
    from src.models import Payment, Tenant, TokenBlacklist, User

    app = create_app(
        "testing",
        config_overrides={
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "JWT_ACCESS_TOKEN_EXPIRES": timedelta(hours=1),
            "STRIPE_WEBHOOK_SECRET": "whsec_stage4a_test_only",
            "NOWPAYMENTS_IPN_SECRET": "nowpayments_stage4a_test_only",
        },
    )
    tables = [Tenant.__table__, User.__table__, TokenBlacklist.__table__, Payment.__table__]
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=tables)

    try:
        yield app
    finally:
        with app.app_context():
            db.session.remove()
            db.metadata.drop_all(bind=db.engine, tables=list(reversed(tables)))
            db.engine.dispose()


@pytest.fixture
def actors(application):
    """Persist a payment owner and a root actor, each with a real signed JWT."""
    from src.database import db
    from src.models import Payment, Tenant, User

    with application.app_context():
        tenant = Tenant(name="Stage4a Test Tenant", subdomain="stage4a-payment-test")
        db.session.add(tenant)
        db.session.flush()

        owner = User(
            email="stage4a-owner@example.test",
            password_hash="test-only-password-hash",
            first_name="Payment",
            last_name="Owner",
            role="trader",
            is_active=True,
            is_verified=True,
            tenant_id=tenant.id,
        )
        root = User(
            email="stage4a-root@example.test",
            password_hash="test-only-password-hash",
            first_name="Payment",
            last_name="Root",
            role="supermaster",
            is_active=True,
            is_verified=True,
            tenant_id=tenant.id,
        )
        db.session.add_all([owner, root])
        db.session.flush()
        owner.tree_path = str(owner.id)
        root.tree_path = str(root.id)
        db.session.add_all([
            Payment(
                user_id=owner.id,
                amount=Decimal("101.00"),
                currency="USD",
                payment_method="legacy",
                payment_type="credit_card",
                status="pending",
            ),
            Payment(
                user_id=root.id,
                amount=Decimal("202.00"),
                currency="USD",
                payment_method="legacy",
                payment_type="credit_card",
                status="pending",
            ),
        ])
        db.session.commit()
        return {
            "owner_headers": {"Authorization": f"Bearer {owner.generate_access_token()}"},
            "root_headers": {"Authorization": f"Bearer {root.generate_access_token()}"},
            "owner_id": owner.id,
            "root_id": root.id,
        }


def _assert_settlement_gate(response):
    assert response.status_code == 503
    assert response.get_json()["code"] == SETTLEMENT_CODE
    assert response.get_json()["reason"] == "SETTLEMENT_NOT_CONFIGURED"


def _stripe_signature(payload, secret):
    """Produce a genuine current Stripe v1 webhook HMAC signature header."""
    timestamp = int(time.time())
    signed_payload = f"{timestamp}.".encode("ascii") + payload
    digest = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={digest}"


def _nowpayments_signature(payload_dict, secret):
    """Sign canonical sorted JSON with NOWPayments' documented HMAC-SHA-512."""
    canonical = json.dumps(
        payload_dict,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), canonical, hashlib.sha512).hexdigest()


def _install_outbound_canaries(monkeypatch):
    """Make every historical provider or fulfillment call fail the test if reached."""
    import requests
    import stripe
    from src.services.mt5_challenge_service import mt5_challenge_service
    from src.services.payment_service import PaymentService

    calls = []

    def blocked(name):
        def _blocked(*args, **kwargs):
            calls.append(name)
            raise AssertionError(f"unexpected external or financial operation: {name}")
        return _blocked

    monkeypatch.setattr(requests, "post", blocked("requests.post"))
    monkeypatch.setattr(requests, "get", blocked("requests.get"))
    monkeypatch.setattr(stripe.PaymentIntent, "create", blocked("stripe.PaymentIntent.create"))
    monkeypatch.setattr(stripe.PaymentIntent, "retrieve", blocked("stripe.PaymentIntent.retrieve"))
    monkeypatch.setattr(stripe.Refund, "create", blocked("stripe.Refund.create"))
    monkeypatch.setattr(PaymentService, "create_payment_intent", blocked("PaymentService.create_payment_intent"))
    monkeypatch.setattr(PaymentService, "confirm_payment", blocked("PaymentService.confirm_payment"))
    monkeypatch.setattr(PaymentService, "refund_payment", blocked("PaymentService.refund_payment"))
    monkeypatch.setattr(PaymentService, "get_payment_status", blocked("PaymentService.get_payment_status"))
    monkeypatch.setattr(PaymentService, "handle_webhook", blocked("PaymentService.handle_webhook"))
    monkeypatch.setattr(
        mt5_challenge_service,
        "create_mt5_account_for_challenge",
        blocked("mt5.create_mt5_account_for_challenge"),
    )
    return calls


def test_legacy_mutations_and_provider_reads_are_gated_before_effects(
    application, actors, monkeypatch
):
    """Malicious legacy inputs cannot create rows, call providers, or fulfill."""
    from src.database import db
    from src.models import Payment

    calls = _install_outbound_canaries(monkeypatch)
    client = application.test_client()
    headers = actors["owner_headers"]
    with application.app_context():
        payment_count_before = db.session.query(Payment).count()

    responses = [
        client.post(
            "/api/v1/payments/",
            headers=headers,
            json={
                "amount": "0.01",
                "payment_type": "free",
                "currency": "USD",
                "payment_method": "anything",
            },
        ),
        client.post(
            "/api/v1/payments/create-payment-intent",
            headers=headers,
            json={"challenge_id": 999999},
        ),
        client.post(
            "/api/v1/payments/confirm-payment",
            headers=headers,
            json={"payment_intent_id": "pi_requires_action_test"},
        ),
        client.post(
            "/api/v1/payments/refund/999999",
            headers=headers,
            json={"reason": "attacker-controlled"},
        ),
        client.get("/api/v1/payments/status/pi_unowned", headers=headers),
        client.post(
            "/api/crypto/create-payment",
            headers=headers,
            json={"program_id": 1, "amount": "0.01", "email": "attacker@example.test"},
        ),
        client.get("/api/crypto/payment-status/crypto_unowned", headers=headers),
        client.get("/api/crypto/currencies"),
    ]
    for response in responses:
        _assert_settlement_gate(response)

    with application.app_context():
        assert db.session.query(Payment).count() == payment_count_before
    assert calls == []


def test_crypto_legacy_operations_require_authentication_before_gate(application):
    """Crypto creation and status no longer reveal or query public payment IDs."""
    client = application.test_client()
    assert client.post("/api/crypto/create-payment", json={"amount": "1"}).status_code == 401
    assert client.get("/api/crypto/payment-status/unowned").status_code == 401
    assert client.get("/api/v1/payments/status/pi_unowned").status_code == 401


def test_legacy_payment_list_is_owner_scoped_and_pagination_is_bounded(application, actors):
    """The preserved read endpoint exposes only each authenticated actor's rows."""
    client = application.test_client()

    owner_response = client.get(
        "/api/v1/payments/?page=1&per_page=1", headers=actors["owner_headers"]
    )
    assert owner_response.status_code == 200
    owner_body = owner_response.get_json()
    assert owner_body["total"] == 1
    assert owner_body["current_page"] == 1
    assert owner_body["per_page"] == 1
    assert [row["user_id"] for row in owner_body["payments"]] == [actors["owner_id"]]

    root_response = client.get("/api/v1/payments/", headers=actors["root_headers"])
    assert root_response.status_code == 200
    assert root_response.get_json()["total"] == 1
    assert [row["user_id"] for row in root_response.get_json()["payments"]] == [actors["root_id"]]

    assert client.get(
        "/api/v1/payments/?page=1000&per_page=100", headers=actors["owner_headers"]
    ).status_code == 200
    for query in ("page=0", "page=1001", "page=one", "per_page=0", "per_page=101"):
        response = client.get(f"/api/v1/payments/?{query}", headers=actors["owner_headers"])
        assert response.status_code == 400
        assert response.get_json()["code"] == "PAGINATION_INVALID"


def test_stripe_webhook_uses_real_local_sdk_verification_then_gates(
    application, monkeypatch
):
    """Invalid Stripe signatures fail; valid ones do not acknowledge settlement."""
    calls = _install_outbound_canaries(monkeypatch)
    client = application.test_client()
    secret = application.config["STRIPE_WEBHOOK_SECRET"]
    payload = b'{"id":"evt_stage4a","type":"payment_intent.succeeded","data":{"object":{"id":"pi_test"}}}'

    invalid = client.post(
        "/api/v1/payments/webhook",
        data=payload,
        headers={"Stripe-Signature": "t=1,v1=not-a-valid-signature"},
        content_type="application/json",
    )
    assert invalid.status_code == 400

    valid = client.post(
        "/api/v1/payments/webhook",
        data=payload,
        headers={"Stripe-Signature": _stripe_signature(payload, secret)},
        content_type="application/json",
    )
    _assert_settlement_gate(valid)

    application.config["STRIPE_WEBHOOK_SECRET"] = None
    missing_secret = client.post(
        "/api/v1/payments/webhook",
        data=payload,
        headers={"Stripe-Signature": _stripe_signature(payload, secret)},
        content_type="application/json",
    )
    assert missing_secret.status_code == 400
    assert calls == []


def test_nowpayments_signature_is_strict_and_valid_ipn_is_not_acknowledged(
    application, monkeypatch
):
    """Missing secrets and malformed signatures fail before the valid-event gate."""
    from src.routes.nowpayments import verify_webhook_signature

    calls = _install_outbound_canaries(monkeypatch)
    client = application.test_client()
    secret = application.config["NOWPAYMENTS_IPN_SECRET"]
    payload_dict = {
        "payment_status": "finished",
        "order_id": "order-stage4a",
        "metadata": {"attempt": 2, "label": "test"},
    }
    # Deliberately use a non-canonical key order; verification signs the sorted body.
    payload = (
        b'{"payment_status":"finished","order_id":"order-stage4a",'
        b'"metadata":{"label":"test","attempt":2}}'
    )
    signature = _nowpayments_signature(payload_dict, secret)

    valid = client.post(
        "/api/crypto/webhook",
        data=payload,
        headers={"x-nowpayments-sig": signature},
        content_type="application/json",
    )
    _assert_settlement_gate(valid)
    assert client.post("/api/crypto/webhook", data=payload).status_code == 401
    assert client.post(
        "/api/crypto/webhook",
        data=b'{"payment_status":',
        headers={"x-nowpayments-sig": signature},
        content_type="application/json",
    ).status_code == 401

    with application.app_context():
        assert not verify_webhook_signature(
            b'{"order_id":"first","order_id":"second"}', signature
        )
        assert not verify_webhook_signature(b'{"amount":NaN}', signature)
        assert not verify_webhook_signature(b'\xff', signature)
        assert not verify_webhook_signature(b'{"amount":1.0}', signature)
        application.config["NOWPAYMENTS_IPN_SECRET"] = None
        assert not verify_webhook_signature(payload, signature)

    assert client.post(
        "/api/crypto/webhook",
        data=payload,
        headers={"x-nowpayments-sig": signature},
        content_type="application/json",
    ).status_code == 401
    assert calls == []


def test_webhook_input_budgets_are_enforced_before_verification(application):
    client = application.test_client()
    for path, header, status in [('/api/v1/payments/webhook', {'Stripe-Signature': 'not-valid'}, 400),
                                 ('/api/crypto/webhook', {'x-nowpayments-sig': 'not-valid'}, 401)]:
        assert client.post(path, data=b'x' * 65537, headers=header, content_type='application/json').status_code == status
    deeply_nested = ('{"x":' * 1100 + 'null' + '}' * 1100).encode()
    assert client.post('/api/crypto/webhook', data=deeply_nested,
                       headers={'x-nowpayments-sig': 'not-valid'}, content_type='application/json').status_code == 401


def test_extreme_pagination_is_rejected_without_integer_conversion_failure(application, actors):
    response = application.test_client().get('/api/v1/payments/?page=' + '9' * 5000, headers=actors['owner_headers'])
    assert response.status_code == 400 and response.get_json()['code'] == 'PAGINATION_INVALID'
