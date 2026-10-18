"""Synthetic-only NOWPayments checkout regressions; the isolated runner forbids TCP."""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from decimal import Decimal

import pytest
from sqlalchemy import JSON

from src.database import db
from src.models.nowpayments_checkout import (
    CheckoutIntent, NowPaymentsObservation, NowPaymentsPaymentBinding,
    NowPaymentsSettlementEntry, NowPaymentsSettlementJournal,
    NowPaymentsVerifiedReceipt, OrderEntitlementGrant,
)
from src.models.purchase_order import PurchaseOrder
from src.models.tenant import Tenant
from src.models.token_blacklist import TokenBlacklist
from src.models.trading_program import Challenge, ProgramAddOn, TradingProgram
from src.models.user import User
from src.services.nowpayments_checkout import (
    CheckoutError, CheckoutPolicy, NowPaymentsTransport, ProviderUnavailable, canonical_ipn_bytes,
    parse_bounded_json, verify_ipn_signature,
)


_SECRET = "synthetic-ipn-secret-for-isolated-tests-only-0123456789"
_API_KEY = "synthetic-np-api-A1b2C3d4E5f6G7"
_TRON_ADDRESS = "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb"
_POLICY = {
    "ORDER_QUOTES_ENABLED": True,
    "ORDER_QUOTE_CURRENCY": "USD",
    "NOWPAYMENTS_PILOT_ENABLED": True,
    "NOWPAYMENTS_API_KEY": _API_KEY,
    "NOWPAYMENTS_IPN_SECRET": _SECRET,
    "NOWPAYMENTS_APPROVED_POLICY_VERSION": "synthetic-test-v1",
    "NOWPAYMENTS_MERCHANT_CONTEXT": "synthetic-merchant",
    "NOWPAYMENTS_CALLBACK_ORIGIN": "https://checkout.example.invalid",
    "NOWPAYMENTS_STORAGE_REVISION": "20261013_000002",
    "NOWPAYMENTS_PILOT_PRINCIPAL_IDS": (2,),
    "NOWPAYMENTS_PILOT_TENANT_IDS": (1,),
    "NOWPAYMENTS_PILOT_ROLES": ("trader",),
    "NOWPAYMENTS_ALLOWED_CURRENCIES": ({"code": "usdttrc20", "label": "Synthetic USDT / TRC20", "network": "TRC20", "decimals": 6},),
    "NOWPAYMENTS_OUTCOME_CURRENCY": "usdttrc20",
    "NOWPAYMENTS_FIXED_RATE": False,
    "NOWPAYMENTS_FEE_PAID_BY_USER": False,
    "NOWPAYMENTS_REFRESH_MIN_SECONDS": 30,
}


@pytest.fixture
def checkout_app():
    from src.app import create_app
    app = create_app("testing", config_overrides={
        "EXPANDED_HIERARCHY_ENABLED": False, "PLATFORM_ROOT_USER_ID": 1,
        "PROPAGATE_EXCEPTIONS": False, **_POLICY,
    })
    tables = [
        Tenant.__table__, User.__table__, TokenBlacklist.__table__, TradingProgram.__table__,
        ProgramAddOn.__table__, Challenge.__table__, PurchaseOrder.__table__, CheckoutIntent.__table__,
        NowPaymentsPaymentBinding.__table__, NowPaymentsObservation.__table__,
        NowPaymentsVerifiedReceipt.__table__, NowPaymentsSettlementJournal.__table__,
        NowPaymentsSettlementEntry.__table__, OrderEntitlementGrant.__table__,
    ]
    # These production tables use PostgreSQL JSONB. This synthetic isolated
    # SQLite fixture substitutes portable SQLAlchemy JSON only while creating
    # its own tables, then restores every mapped production column on teardown.
    json_columns = (
        Tenant.__table__.c.settings,
        TradingProgram.__table__.c.rules,
        ProgramAddOn.__table__.c.benefits,
        Challenge.__table__.c.addons,
        Challenge.__table__.c.daily_drawdown_history,
    )
    production_json_types = [(column, column.type) for column in json_columns]
    for column, _production_type in production_json_types:
        column.type = JSON()
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=tables)
        db.session.add(Tenant(id=1, name="Synthetic checkout brand", subdomain="checkout", status="active"))
        db.session.add_all([
            User(id=1, email="checkout-root@example.invalid", password_hash="not-a-credential", first_name="Root", last_name="Synthetic", tenant_id=1, role="supermaster", is_active=True, is_verified=True, can_create_same_role=True, parent_id=None, tree_path="1", level=0),
            User(id=2, email="checkout-owner@example.invalid", password_hash="not-a-credential", first_name="Owner", last_name="Synthetic", tenant_id=1, role="trader", is_active=True, is_verified=True, can_create_same_role=False, parent_id=1, tree_path="1/2", level=1),
            User(id=3, email="checkout-other@example.invalid", password_hash="not-a-credential", first_name="Other", last_name="Synthetic", tenant_id=1, role="trader", is_active=True, is_verified=True, can_create_same_role=False, parent_id=1, tree_path="1/3", level=1),
        ])
        db.session.add(TradingProgram(id=10, tenant_id=1, name="Synthetic program", type="one_phase", account_size=10000, price=Decimal("19.99"), is_active=True))
        db.session.commit()
        app.tokens = {identity: db.session.get(User, identity).generate_access_token() for identity in (1, 2, 3)}
    yield app
    with app.app_context():
        db.session.remove()
        db.metadata.drop_all(bind=db.engine, tables=list(reversed(tables)))
    for column, production_type in production_json_types:
        column.type = production_type


def _headers(app, actor=2, key="synthetic_checkout_key_0001"):
    return {"Authorization": "Bearer " + app.tokens[actor], "Idempotency-Key": key}


def _quote(app, key="synthetic_quote_key_0001", actor=2):
    response = app.test_client().post("/api/v1/orders/", json={"program_id": 10}, headers=_headers(app, actor, key))
    assert response.status_code == 201
    return response.get_json()["order"]["id"]


def _provider_response(payload):
    return {
        "payment_id": 123456789, "payment_status": "waiting", "pay_address": _TRON_ADDRESS,
        "price_amount": "19.99", "price_currency": "usd", "pay_amount": "20.0", "pay_currency": "usdttrc20",
        "order_id": payload["order_id"], "network": "TRC20", "payin_extra_id": None,
        "expiration_estimate_date": "2030-01-01T00:00:00Z",
    }


def _sign(payload):
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    parsed = parse_bounded_json(raw)
    signature = hmac.new(_SECRET.encode(), canonical_ipn_bytes(parsed), hashlib.sha512).hexdigest()
    return raw, signature


def test_canonical_node_sort_arrays_unicode_decimals_and_tampering(checkout_app):
    with checkout_app.app_context():
        raw = b'{"z":1.0,"fee":{"serviceFee":1e-7},"array":[1.0,{"text":"\\u05e9\\u05dc\\u05d5\\u05dd"}],"a":1}'
        parsed = parse_bounded_json(raw)
        assert canonical_ipn_bytes(parsed).decode() == '{"a":1,"array":{"0":1,"1":{"text":"שלום"}},"fee":{"serviceFee":1e-7},"z":1}'
        signature = hmac.new(_SECRET.encode(), canonical_ipn_bytes(parsed), hashlib.sha512).hexdigest()
        assert verify_ipn_signature(raw, signature, _SECRET)[1] == hashlib.sha256(canonical_ipn_bytes(parsed)).hexdigest()
        with pytest.raises(Exception):
            verify_ipn_signature(raw, "0" * 128, _SECRET)


@pytest.mark.parametrize("raw", [
    b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}',
    b'{"padding":"' + b'x' * (64 * 1024) + b'"}', b"{" + b'\"x\":' * 17 + b"0" + b"}" * 17,
])
def test_canonical_parser_refuses_ambiguous_or_bounded_payloads(checkout_app, raw):
    with checkout_app.app_context():
        with pytest.raises(Exception):
            parse_bounded_json(raw)
    assert len(b"x" * (64 * 1024 + 1)) > 64 * 1024


def test_capabilities_are_disabled_without_complete_policy_and_never_call_provider(checkout_app, monkeypatch):
    called = []
    monkeypatch.setattr(NowPaymentsTransport, "create_payment", lambda payload: called.append(payload))
    checkout_app.config["NOWPAYMENTS_PILOT_ENABLED"] = False
    response = checkout_app.test_client().get("/api/v1/orders/payment-capabilities", headers=_headers(checkout_app))
    assert response.status_code == 200
    body = response.get_json()
    assert body["enabled"] is False and body["currencies"] == [] and body["reason"] == "PILOT_DISABLED"
    assert called == []


def test_synthetic_31_character_api_key_passes_full_policy_and_mocked_transport(checkout_app, monkeypatch):
    class FakeResponse:
        status_code = 201

        def iter_content(self, chunk_size):
            yield b"{}"

        def close(self):
            return None

    captured = {}

    def fake_post(url, *, data, headers, timeout, allow_redirects, stream):
        captured.update(url=url, headers=dict(headers), timeout=timeout, allow_redirects=allow_redirects, stream=stream)
        return FakeResponse()

    with checkout_app.app_context():
        assert len(_API_KEY) == 31
        policy = CheckoutPolicy.from_config()
        monkeypatch.setattr("src.services.nowpayments_checkout.requests.post", fake_post)
        body, raw = NowPaymentsTransport.create_payment({
            "price_amount": "19.99",
            "price_currency": "usd",
            "pay_currency": "usdttrc20",
            "ipn_callback_url": policy.callback_url,
            "order_id": "synthetic-transport-reference",
            "is_fixed_rate": False,
            "is_fee_paid_by_user": False,
        })

    assert body == {} and raw == b"{}"
    assert captured["headers"]["x-api-key"] == _API_KEY
    assert captured["url"].endswith("/payment") and captured["allow_redirects"] is False and captured["stream"] is True

    checkout_app.config["NOWPAYMENTS_IPN_SECRET"] = _API_KEY
    with checkout_app.app_context():
        with pytest.raises(CheckoutError) as error:
            CheckoutPolicy.from_config()
    assert error.value.code == "POLICY_NOT_CONFIGURED"


def test_instant_bound_immutable_quote_is_readable_but_never_calls_provider(checkout_app, monkeypatch):
    """A historical Instant quote cannot open a new checkout command or POST."""
    calls = []
    monkeypatch.setattr(NowPaymentsTransport, "create_payment", lambda payload: calls.append(payload))
    order_id = "00000000-0000-4000-8000-000000000013"
    snapshot = {
        "schema": 1, "kind": "purchase_quote", "user_id": 2, "tenant_id": 1,
        "program_id": 10, "currency": "USD", "base_amount": "19.99", "addons": [],
        "amount": "19.99", "rounding": "USD cents; ROUND_HALF_UP per add-on line",
        "terms": {"name": "Historical Instant", "type": "instant_funding"},
        "settlement": "not_configured", "entitlement": False,
    }
    snapshot_json = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    with checkout_app.app_context():
        db.session.add(PurchaseOrder(
            id=order_id, user_id=2, tenant_id=1, program_id=10,
            idempotency_key="synthetic_instant_checkout_quote_0001",
            request_hash=hashlib.sha256(b"synthetic-request").hexdigest(),
            snapshot_hash=hashlib.sha256(snapshot_json.encode()).hexdigest(),
            snapshot_json=snapshot_json, amount_minor=1999, currency="USD", state="quoted",
        ))
        db.session.commit()
    client = checkout_app.test_client()
    create = client.post(
        f"/api/v1/orders/{order_id}/payments/nowpayments",
        json={"pay_currency": "usdttrc20"}, headers=_headers(checkout_app),
    )
    assert create.status_code == 409 and create.get_json()["code"] == "PROGRAM_COMING_SOON"
    assert calls == []
    with checkout_app.app_context():
        assert db.session.query(CheckoutIntent).count() == 0
    # This local projection executes no provider call and remains available for
    # the immutable quote; only new provider creation is closed.
    projection = client.get(f"/api/v1/orders/{order_id}/payment", headers=_headers(checkout_app))
    assert projection.status_code == 200
    assert projection.get_json()["can_create"] is False
    assert projection.get_json()["reason"] == "PROGRAM_COMING_SOON"


def test_owner_create_projection_signed_finished_grant_and_admin_record(checkout_app, monkeypatch):
    calls = []
    def fake_create(payload):
        calls.append(payload)
        data = _provider_response(payload)
        return data, json.dumps(data, separators=(",", ":")).encode()
    monkeypatch.setattr(NowPaymentsTransport, "create_payment", fake_create)
    order_id = _quote(checkout_app)
    create = checkout_app.test_client().post(f"/api/v1/orders/{order_id}/payments/nowpayments", json={"pay_currency": "usdttrc20"}, headers=_headers(checkout_app))
    assert create.status_code == 201
    body = create.get_json()
    assert body["state"] == "awaiting_payment" and body["paid"] is False and body["recorded_purchase"] is False
    assert body["creation_attempted"] is True and body["can_create"] is False and body["payment"]["pay_amount"] == "20"
    assert set(calls[0]) == {"price_amount", "price_currency", "pay_currency", "ipn_callback_url", "order_id", "is_fixed_rate", "is_fee_paid_by_user"}
    assert calls[0]["price_amount"] == "19.99" and calls[0]["price_currency"] == "usd"
    payload = {
        "payment_id": 123456789, "parent_payment_id": None, "payment_status": "finished",
        "pay_address": _TRON_ADDRESS, "payin_extra_id": None, "price_amount": 19.99,
        "price_currency": "usd", "pay_amount": 20, "actually_paid": 20, "pay_currency": "usdttrc20",
        "order_id": calls[0]["order_id"], "outcome_amount": 19.8, "outcome_currency": "usdttrc20",
    }
    raw, signature = _sign(payload)
    callback = checkout_app.test_client().post("/api/v1/orders/webhooks/nowpayments", data=raw, content_type="application/json", headers={"x-nowpayments-sig": signature})
    assert callback.status_code == 200 and callback.get_json()["replayed"] is False
    replay = checkout_app.test_client().post("/api/v1/orders/webhooks/nowpayments", data=raw, content_type="application/json", headers={"x-nowpayments-sig": signature})
    assert replay.status_code == 200 and replay.get_json()["replayed"] is True
    projection = checkout_app.test_client().get(f"/api/v1/orders/{order_id}/payment", headers=_headers(checkout_app)).get_json()
    assert projection["state"] == "paid" and projection["paid"] is True and projection["recorded_purchase"] is True
    with checkout_app.app_context():
        assert db.session.query(NowPaymentsVerifiedReceipt).count() == db.session.query(NowPaymentsSettlementJournal).count() == db.session.query(OrderEntitlementGrant).count() == 1
        assert db.session.query(NowPaymentsSettlementEntry).count() == 2
    # The configured root is deliberately not in the pilot allowlist, but existing
    # finance-admin authority can read the current tenant's recorded evidence.
    records = checkout_app.test_client().get("/api/v1/orders/payment-records", headers=_headers(checkout_app, 1)).get_json()
    assert records["availability"] is True
    assert records["owner_context"]["user_id"] == 1
    checkout_app.config["NOWPAYMENTS_PILOT_ENABLED"] = False
    records = checkout_app.test_client().get("/api/v1/orders/payment-records", headers=_headers(checkout_app, 1)).get_json()
    assert records["availability"] is True and records["records"][0]["recorded_purchase"] is True
    assert records["records"][0]["quote_amount_minor"] == "1999" and records["records"][0]["pay_currency"] == "usdttrc20"


def test_timeout_creates_uncertain_and_replay_never_posts_twice(checkout_app, monkeypatch):
    attempts = []
    def uncertain(payload):
        attempts.append(payload)
        raise ProviderUnavailable()
    monkeypatch.setattr(NowPaymentsTransport, "create_payment", uncertain)
    order_id = _quote(checkout_app, "synthetic_quote_key_0002")
    first = checkout_app.test_client().post(f"/api/v1/orders/{order_id}/payments/nowpayments", json={"pay_currency": "usdttrc20"}, headers=_headers(checkout_app, key="synthetic_checkout_key_0002"))
    assert first.status_code == 503 and first.get_json()["state"] == "creation_uncertain"
    second = checkout_app.test_client().post(f"/api/v1/orders/{order_id}/payments/nowpayments", json={"pay_currency": "usdttrc20"}, headers=_headers(checkout_app, key="synthetic_checkout_key_0002"))
    assert second.status_code == 200 and second.get_json()["replayed"] is True and second.get_json()["can_create"] is False
    assert len(attempts) == 1


def test_owner_isolation_cookie_csrf_and_wrong_asset_manual_review(checkout_app, monkeypatch):
    monkeypatch.setattr(NowPaymentsTransport, "create_payment", lambda payload: (_provider_response(payload), json.dumps(_provider_response(payload)).encode()))
    order_id = _quote(checkout_app, "synthetic_quote_key_0003")
    client = checkout_app.test_client()
    client.set_cookie("access_token", checkout_app.tokens[2])
    csrf = client.post(f"/api/v1/orders/{order_id}/payments/nowpayments", json={"pay_currency": "usdttrc20"}, headers={"Idempotency-Key": "synthetic_checkout_key_0003"})
    assert csrf.status_code == 403
    create = checkout_app.test_client().post(f"/api/v1/orders/{order_id}/payments/nowpayments", json={"pay_currency": "usdttrc20"}, headers=_headers(checkout_app, key="synthetic_checkout_key_0003"))
    assert create.status_code == 201
    with checkout_app.app_context():
        reference = db.session.query(CheckoutIntent).filter_by(order_id=order_id).one().external_reference
    payload = {
        "payment_id": 123456789, "parent_payment_id": None, "payment_status": "finished", "pay_address": _TRON_ADDRESS,
        "price_amount": 19.99, "price_currency": "usd", "pay_amount": 20, "actually_paid": 20,
        "pay_currency": "btc", "order_id": reference, "outcome_amount": 19.8, "outcome_currency": "usdttrc20",
    }
    raw, signature = _sign(payload)
    assert checkout_app.test_client().post("/api/v1/orders/webhooks/nowpayments", data=raw, content_type="application/json", headers={"x-nowpayments-sig": signature}).status_code == 200
    owner = checkout_app.test_client().get(f"/api/v1/orders/{order_id}/payment", headers=_headers(checkout_app)).get_json()
    assert owner["state"] == "manual_review" and owner["paid"] is False and owner["recorded_purchase"] is False
    assert checkout_app.test_client().get(f"/api/v1/orders/{order_id}/payment", headers=_headers(checkout_app, 3)).status_code == 404


_NODE_VECTORS = json.loads((Path(__file__).parent / "fixtures" / "nowpayments_node_vectors.json").read_text())["vectors"]

@pytest.mark.parametrize("vector", _NODE_VECTORS, ids=["float-boundaries", "bigint-metadata", "unicode-integer-keys", "recursive-arrays"])
def test_node_official_signature_is_independent_and_exact(checkout_app, vector):
    with checkout_app.app_context():
        raw = vector["raw"].encode()
        parsed = parse_bounded_json(raw)
        assert canonical_ipn_bytes(parsed).decode() == vector["canonical"]
        assert verify_ipn_signature(raw, vector["signature"], _SECRET)[1] == hashlib.sha256(vector["canonical"].encode()).hexdigest()


def _bound_payment(app, monkeypatch):
    calls=[]
    def transport(payload):
        # The app must release every SQLAlchemy transaction before vendor I/O.
        assert not db.session().in_transaction()
        calls.append(payload)
        result=_provider_response(payload)
        return result,json.dumps(result,separators=(",",":")).encode()
    monkeypatch.setattr(NowPaymentsTransport,"create_payment",transport)
    order_id=_quote(app)
    created=app.test_client().post(f"/api/v1/orders/{order_id}/payments/nowpayments",json={"pay_currency":"usdttrc20"},headers=_headers(app))
    assert created.status_code==201, created.get_json()
    return order_id,calls[0]["order_id"]


def _finished(reference, **changes):
    body={"payment_id":123456789,"parent_payment_id":None,"payment_status":"finished","pay_address":_TRON_ADDRESS,"payin_extra_id":None,"price_amount":19.99,"price_currency":"usd","pay_amount":20,"actually_paid":20,"pay_currency":"usdttrc20","order_id":reference,"outcome_amount":19.8,"outcome_currency":"usdttrc20"}
    body.update(changes)
    return body


def _notify(app, body):
    raw, signature=_sign(body)
    return app.test_client().post("/api/v1/orders/webhooks/nowpayments",data=raw,content_type="application/json",headers={"x-nowpayments-sig":signature})


@pytest.mark.parametrize("changes", [
 {"actually_paid":19.999999},{"actually_paid":20.000001},{"network":"ERC20"},
 {"parent_payment_id":987654321},{"payin_extra_id":"unexpected-memo"},
 {"price_amount":20.00},{"outcome_currency":"btc"},{"actually_paid":"-1"},
])
def test_mismatched_deposit_is_sticky_and_cannot_become_an_auto_purchase(checkout_app,monkeypatch,changes):
    order_id,reference=_bound_payment(checkout_app,monkeypatch)
    response=_notify(checkout_app,_finished(reference,**changes))
    assert response.status_code==200,response.get_json()
    assert _notify(checkout_app,_finished(reference)).status_code==200
    body=checkout_app.test_client().get(f"/api/v1/orders/{order_id}/payment",headers=_headers(checkout_app)).get_json()
    assert body["state"]=="manual_review" and body["paid"] is False
    with checkout_app.app_context():
        assert db.session.query(OrderEntitlementGrant).count()==0


def test_equivalent_finished_and_delayed_waiting_keep_one_paid_receipt(checkout_app,monkeypatch):
    order_id,reference=_bound_payment(checkout_app,monkeypatch)
    assert _notify(checkout_app,_finished(reference)).status_code==200
    assert _notify(checkout_app,_finished(reference,additional_field="synthetic equivalent observation")).status_code==200
    assert _notify(checkout_app,_finished(reference,payment_status="waiting",actually_paid=0,outcome_amount=None,outcome_currency=None)).status_code==200
    body=checkout_app.test_client().get(f"/api/v1/orders/{order_id}/payment",headers=_headers(checkout_app)).get_json()
    assert body["state"]=="paid" and body["provider_status"]=="finished"
    assert body["payment"]["actually_paid"]=="20"
    with checkout_app.app_context():
        assert db.session.query(OrderEntitlementGrant).count()==db.session.query(NowPaymentsVerifiedReceipt).count()==1


def test_finished_refresh_waits_for_signed_ipn_and_has_no_network_transaction(checkout_app,monkeypatch):
    order_id,reference=_bound_payment(checkout_app,monkeypatch)
    def read(payment_id):
        assert payment_id=="123456789" and not db.session().in_transaction()
        body=_finished(reference)
        raw = json.dumps(body,separators=(",",":")).encode()
        return parse_bounded_json(raw),raw
    monkeypatch.setattr(NowPaymentsTransport,"get_payment",read)
    response=checkout_app.test_client().post(f"/api/v1/orders/{order_id}/payment/refresh",json={},headers=_headers(checkout_app))
    assert response.status_code==200,response.get_json()
    assert response.get_json()["state"]=="processing" and response.get_json()["paid"] is False
    assert _notify(checkout_app,_finished(reference)).status_code==200
    assert checkout_app.test_client().get(f"/api/v1/orders/{order_id}/payment",headers=_headers(checkout_app)).get_json()["state"]=="paid"


@pytest.mark.parametrize("status", ["expired","failed"])
def test_late_finished_after_terminal_status_requires_review_not_new_grant(checkout_app,monkeypatch,status):
    order_id,reference=_bound_payment(checkout_app,monkeypatch)
    assert _notify(checkout_app,_finished(reference,payment_status=status,actually_paid=0,outcome_amount=None,outcome_currency=None)).status_code==200
    assert _notify(checkout_app,_finished(reference)).status_code==200
    body=checkout_app.test_client().get(f"/api/v1/orders/{order_id}/payment",headers=_headers(checkout_app)).get_json()
    assert body["state"]=="manual_review" and body["paid"] is False
    with checkout_app.app_context(): assert db.session.query(OrderEntitlementGrant).count()==0


def test_customer_history_is_readonly_owned_and_survives_pilot_close(checkout_app,monkeypatch):
    order_id,reference=_bound_payment(checkout_app,monkeypatch)
    assert _notify(checkout_app,_finished(reference)).status_code==200
    checkout_app.config["NOWPAYMENTS_PILOT_ENABLED"]=False
    monkeypatch.setattr(NowPaymentsTransport,"create_payment",lambda *_: pytest.fail("history is local"))
    monkeypatch.setattr(NowPaymentsTransport,"get_payment",lambda *_: pytest.fail("history is local"))
    body=checkout_app.test_client().get("/api/v1/orders/purchases",headers=_headers(checkout_app)).get_json()
    assert body["availability"] is True and body["records"][0]["order_id"]==order_id
    assert body["records"][0]["program_name"]=="Synthetic program"
    other=checkout_app.test_client().get("/api/v1/orders/purchases",headers=_headers(checkout_app,3)).get_json()
    assert other["records"]==[] and other["pagination"]["total"]==0
    assert checkout_app.test_client().get("/api/v1/orders/purchases?user_id=2",headers=_headers(checkout_app,3)).status_code==400
    assert checkout_app.test_client().get("/api/v1/orders/purchases?page=1&page=2",headers=_headers(checkout_app)).status_code==400


def test_known_signed_receipt_is_processed_after_new_payment_creation_is_closed(checkout_app,monkeypatch):
    order_id, reference = _bound_payment(checkout_app, monkeypatch)
    checkout_app.config["NOWPAYMENTS_PILOT_ENABLED"] = False
    checkout_app.config["NOWPAYMENTS_API_KEY"] = None
    response = _notify(checkout_app, _finished(reference))
    assert response.status_code == 200, response.get_json()
    body = checkout_app.test_client().get(f"/api/v1/orders/{order_id}/payment", headers=_headers(checkout_app)).get_json()
    assert body["paid"] is True and body["can_create"] is False and body["can_refresh"] is False
    assert _notify(checkout_app, _finished("synthetic_unknown_reference")).status_code == 409


def test_customers_scope_allows_brand_customer_without_individual_allowlist_and_never_root(checkout_app):
    from types import SimpleNamespace
    from src.services.nowpayments_checkout import CheckoutPolicy
    from src.production_safety import _valid_nowpayments_pilot
    checkout_app.config['NOWPAYMENTS_CHECKOUT_SCOPE'] = 'customers'
    checkout_app.config['NOWPAYMENTS_PILOT_PRINCIPAL_IDS'] = ()
    checkout_app.config['NOWPAYMENTS_PILOT_ROLES'] = ('trader','affiliate')
    assert _valid_nowpayments_pilot(checkout_app.config)
    with checkout_app.app_context():
        policy=CheckoutPolicy.from_config()
        assert policy.scope=='customers'
        assert policy.eligible(db.session.get(User,3),db.session.get(Tenant,1))
        assert not policy.eligible(db.session.get(User,1),db.session.get(Tenant,1))
        assert not policy.eligible(SimpleNamespace(id=400,tenant_id=2,role='trader',is_active=True),SimpleNamespace(id=2))
        assert not policy.eligible(SimpleNamespace(id=400,tenant_id=1,role='trader',is_active=False),SimpleNamespace(id=1))
    for actor in (2,3):
        body=checkout_app.test_client().get('/api/v1/orders/payment-capabilities',headers=_headers(checkout_app,actor)).get_json()
        assert body['enabled'] is True and body['owner_context']['user_id']==actor
    root=checkout_app.test_client().get('/api/v1/orders/payment-capabilities',headers=_headers(checkout_app,1)).get_json()
    assert root['enabled'] is False
    checkout_app.config['NOWPAYMENTS_CHECKOUT_SCOPE']='pilot'
    other=checkout_app.test_client().get('/api/v1/orders/payment-capabilities',headers=_headers(checkout_app,3)).get_json()
    assert other['enabled'] is False and other['reason']=='POLICY_NOT_CONFIGURED'


@pytest.mark.parametrize('scope,roles,tenants',[
    ('all',('trader',),(1,)), ({},('trader',),(1,)),
    ('customers',('supermaster',),(1,)), ('customers',({},),(1,)),
    ('customers',('trader',),()), ('customers',('trader',),({'id':1},)),
])
def test_public_configuration_does_not_turn_malformed_scope_or_admin_roles_into_wildcards(checkout_app,scope,roles,tenants):
    from src.production_safety import _valid_nowpayments_pilot
    config=dict(checkout_app.config,NOWPAYMENTS_CHECKOUT_SCOPE=scope,NOWPAYMENTS_PILOT_ROLES=roles,NOWPAYMENTS_PILOT_TENANT_IDS=tenants)
    assert _valid_nowpayments_pilot(config) is False


def test_json_payment_policy_loader_preserves_explicit_values_and_redacts_bad_configuration(monkeypatch):
    from src.config import _payment_policy_json
    field='SYNTHETIC_CHECKOUT_CONFIG'
    monkeypatch.delenv(field,raising=False)
    assert _payment_policy_json(field) is None
    monkeypatch.setenv(field,'false')
    assert _payment_policy_json(field) is False
    monkeypatch.setenv(field,'[1,2]')
    assert _payment_policy_json(field)==[1,2]
    for bad in ('NaN','{"synthetic-sensitive-marker":', 'x'*8193):
        monkeypatch.setenv(field,bad)
        with pytest.raises(ValueError) as error:
            _payment_policy_json(field)
        assert str(error.value)=='Invalid payment configuration field: '+field


def test_identical_canonical_unsigned_refresh_cannot_consume_later_signed_notification(checkout_app,monkeypatch):
    order_id,reference=_bound_payment(checkout_app,monkeypatch)
    body=_finished(reference)
    canonical=canonical_ipn_bytes(parse_bounded_json(json.dumps(body,separators=(',',':')).encode()))
    monkeypatch.setattr(NowPaymentsTransport,'get_payment',lambda payment_id:(parse_bounded_json(canonical),canonical))
    client=checkout_app.test_client()
    refreshed=client.post(f'/api/v1/orders/{order_id}/payment/refresh',json={},headers=_headers(checkout_app))
    assert refreshed.status_code==200,refreshed.get_json()
    assert refreshed.get_json()['paid'] is False
    received=_notify(checkout_app,body)
    assert received.status_code==200,received.get_json()
    assert client.get(f'/api/v1/orders/{order_id}/payment',headers=_headers(checkout_app)).get_json()['paid'] is True


@pytest.mark.parametrize('changes',[{'price_amount':19.98},{'pay_currency':'btc'},{'network':'ERC20'}])
def test_early_signed_conflict_remains_committed_review_after_later_valid_evidence(checkout_app,monkeypatch,changes):
    seen=[]
    def early(payload):
        seen.append(payload)
        bad=_notify(checkout_app,_finished(payload['order_id'],**changes))
        assert bad.status_code==200,bad.get_json()
        # A separate HTTP context must already see the committed stop.
        stored=checkout_app.test_client().get(f"/api/v1/orders/{order_id}/payment",headers=_headers(checkout_app)).get_json()
        assert stored['state']=='manual_review' and stored['paid'] is False
        response=_provider_response(payload)
        return response,json.dumps(response,separators=(',',':')).encode()
    monkeypatch.setattr(NowPaymentsTransport,'create_payment',early)
    order_id=_quote(checkout_app)
    created=checkout_app.test_client().post(f'/api/v1/orders/{order_id}/payments/nowpayments',json={'pay_currency':'usdttrc20'},headers=_headers(checkout_app))
    assert created.status_code==201,created.get_json()
    assert _notify(checkout_app,_finished(seen[0]['order_id'])).status_code==200
    stored=checkout_app.test_client().get(f'/api/v1/orders/{order_id}/payment',headers=_headers(checkout_app)).get_json()
    assert stored['state']=='manual_review' and stored['paid'] is False and stored['recorded_purchase'] is False
    with checkout_app.app_context():
        assert db.session.query(OrderEntitlementGrant).count()==db.session.query(NowPaymentsVerifiedReceipt).count()==0


def test_explicit_callback_retention_is_valid_after_creation_stop_and_cannot_open_checkout(checkout_app,monkeypatch):
    from src.production_safety import _valid_nowpayments_pilot
    order_id,reference=_bound_payment(checkout_app,monkeypatch)
    checkout_app.config['NOWPAYMENTS_PILOT_ENABLED']=False
    assert _valid_nowpayments_pilot(checkout_app.config) is False
    checkout_app.config['NOWPAYMENTS_ACCEPT_EXISTING_IPN']=True
    assert _valid_nowpayments_pilot(checkout_app.config) is True
    cap=checkout_app.test_client().get('/api/v1/orders/payment-capabilities',headers=_headers(checkout_app)).get_json()
    assert cap['enabled'] is False and cap['currencies']==[]
    assert _notify(checkout_app,_finished(reference)).status_code==200
    stored=checkout_app.test_client().get(f'/api/v1/orders/{order_id}/payment',headers=_headers(checkout_app)).get_json()
    assert stored['paid'] is True and stored['can_create'] is False
