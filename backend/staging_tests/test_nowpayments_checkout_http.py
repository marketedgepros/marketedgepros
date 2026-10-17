"""Real PostgreSQL HTTP contracts for the isolated NOWPayments checkout pilot.

This suite starts a fresh runner-owned database for every case, applies the real
000002 migration (including its deferred triggers), and uses the application
factory plus route decorators.  Provider transport is always a local monkeypatch:
no live provider, TCP listener, or external credential is involved.
"""
from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
import hashlib
import hmac
import json
import traceback

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.engine import make_url


BACKEND = Path(__file__).resolve().parents[1]
REVISION = "20261013_000002"
_SECRET = "synthetic-ipn-secret-for-staging-http-only-0123456789"
_API_KEY = "synthetic-api-key-for-staging-http-only-0123456789"
_TRON_ADDRESS = "T9yD14Nj9j7xAB4dbGeiX9h8unkKHxuWwb"
_POLICY = {
    "ORDER_QUOTES_ENABLED": True,
    "ORDER_QUOTE_CURRENCY": "USD",
    "NOWPAYMENTS_PILOT_ENABLED": True,
    "NOWPAYMENTS_API_KEY": _API_KEY,
    "NOWPAYMENTS_IPN_SECRET": _SECRET,
    "NOWPAYMENTS_APPROVED_POLICY_VERSION": "staging-http-policy-v1",
    "NOWPAYMENTS_MERCHANT_CONTEXT": "staging-http-merchant",
    "NOWPAYMENTS_CALLBACK_ORIGIN": "https://checkout.example.invalid",
    "NOWPAYMENTS_STORAGE_REVISION": REVISION,
    "NOWPAYMENTS_PILOT_PRINCIPAL_IDS": (2,),
    "NOWPAYMENTS_PILOT_TENANT_IDS": (1,),
    "NOWPAYMENTS_PILOT_ROLES": ("trader",),
    "NOWPAYMENTS_ALLOWED_CURRENCIES": (
        {"code": "usdttrc20", "label": "Synthetic USDT / TRC20", "network": "TRC20", "decimals": 6},
    ),
    "NOWPAYMENTS_OUTCOME_CURRENCY": "usdttrc20",
    "NOWPAYMENTS_FIXED_RATE": False,
    "NOWPAYMENTS_FEE_PAID_BY_USER": False,
    "NOWPAYMENTS_REFRESH_MIN_SECONDS": 30,
}
_PUBLIC_ACCOUNT_ACCESS_PROFILE = {
    "PUBLIC_ACCOUNT_ACCESS_ENABLED": True,
    "EMAIL_PROVIDER": "brevo",
    "BREVO_API_KEY": "synthetic-brevo-key-1234567890-ABC",
    "EMAIL_FROM_ADDRESS": "accounts@marketedgepros.com",
    "EMAIL_FROM_NAME": "MarketEdgePros",
    "EMAIL_SENDER_VERIFIED": True,
    "EMAIL_DOMAIN_AUTHENTICATED": True,
    "FRONTEND_URL": "https://marketedgepros.com",
}


def _non_testing_demo_config(app):
    """Use this exact HTTP policy in the pure, non-Testing deployment guards."""
    config = dict(app.config)
    config.update({
        "TESTING": False,
        "PRODUCTION": False,
        "DEMO_RELEASE_ENABLED": True,
        "SQLALCHEMY_DATABASE_URI": (
            "postgresql://marketedgepros_demo:demo-password@127.0.0.1:5432/"
            "marketedgepros_demo_20261012"
        ),
        "REDIS_URL": "redis://:synthetic-dedicated-redis-password-0123456789@127.0.0.1:6380/0",
        "CACHE_REDIS_URL": "redis://:synthetic-dedicated-redis-password-0123456789@127.0.0.1:6380/1",
        "RATELIMIT_STORAGE_URL": "redis://:synthetic-dedicated-redis-password-0123456789@127.0.0.1:6380/2",
        "PLATFORM_ROOT_USER_ID": 1,
    })
    return config


@contextmanager
def _checkout_http_database(resources, monkeypatch):
    """Own a migrated private PostgreSQL database and a genuine Flask factory."""
    from src.app import create_app
    from src.database import db
    from src.models.user import User
    from src.services.nowpayments_checkout_schema import validate_checkout_schema

    database = "marketedgepros_test_" + uuid4().hex
    url = make_url(resources["pg_url"]).set(database=database)
    rendered = url.render_as_string(hide_password=False)
    admin = create_engine(make_url(resources["pg_url"]).set(database="postgres"), isolation_level="AUTOCOMMIT")
    app = None
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database}"'))
        monkeypatch.setenv("TEST_DATABASE_URL", rendered)
        migration_config = Config(str(BACKEND / "migrations/alembic.ini"))
        migration_config.set_main_option("script_location", str(BACKEND / "migrations"))
        migration_config.set_main_option("sqlalchemy.url", rendered.replace("%", "%%"))
        migration_engine = create_engine(url)
        try:
            with migration_engine.connect() as connection:
                migration_config.attributes["connection"] = connection
                command.upgrade(migration_config, REVISION)
        finally:
            migration_config.attributes.pop("connection", None)
            migration_engine.dispose()

        app = create_app("testing", config_overrides={
            "SQLALCHEMY_DATABASE_URI": rendered,
            "ISOLATED_STAGING_DATABASE": True,
            "SQLALCHEMY_ENGINE_OPTIONS": {"pool_size": 4, "max_overflow": 0, "pool_timeout": 5},
            "JWT_SECRET_KEY": "staging-http-synthetic-jwt-not-a-secret",
            "PLATFORM_ROOT_USER_ID": 1,
            "EXPANDED_HIERARCHY_ENABLED": False,
            "PROPAGATE_EXCEPTIONS": True,
            **_POLICY, **_PUBLIC_ACCOUNT_ACCESS_PROFILE,
        })
        with app.app_context():
            assert db.engine.dialect.name == "postgresql"
            assert db.session.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == REVISION
            # Runtime readiness invokes this same migration-owned verifier with a
            # Connection, not an Engine; prove it before adding synthetic parents.
            assert validate_checkout_schema(db.session.connection()) is True
            db.session.execute(text("""
                INSERT INTO tenants (id, name, slug, subdomain, status) VALUES
                (1, 'Synthetic checkout brand', 'staging-http-brand', 'staging-http', 'active'),
                (2, 'Synthetic foreign brand', 'staging-http-foreign', 'staging-http-foreign', 'active')
            """))
            db.session.add_all([
                User(id=1, email="staging-http-root@example.invalid", password_hash="not-a-credential",
                     first_name="Root", last_name="Synthetic", role="supermaster", tenant_id=1,
                     parent_id=None, level=0, tree_path="1", can_create_same_role=True,
                     is_active=True, is_verified=True),
                User(id=2, email="staging-http-buyer@example.invalid", password_hash="not-a-credential",
                     first_name="Buyer", last_name="Synthetic", role="trader", tenant_id=1,
                     parent_id=1, level=1, tree_path="1/2", can_create_same_role=False,
                     is_active=True, is_verified=True),
                User(id=3, email="staging-http-other@example.invalid", password_hash="not-a-credential",
                     first_name="Other", last_name="Synthetic", role="trader", tenant_id=1,
                     parent_id=1, level=1, tree_path="1/3", can_create_same_role=False,
                     is_active=True, is_verified=True),
                User(id=4, email="staging-http-foreign@example.invalid", password_hash="not-a-credential",
                     first_name="Foreign", last_name="Synthetic", role="trader", tenant_id=2,
                     parent_id=None, level=0, tree_path="4", can_create_same_role=False,
                     is_active=True, is_verified=True),
            ])
            db.session.execute(text("""
                INSERT INTO trading_programs
                    (id, tenant_id, name, program_type, type, account_size, price, rules, is_active,
                     profit_target, max_daily_loss, max_total_loss, profit_split)
                VALUES
                    (10, 1, 'Synthetic HTTP program', 'one_phase', 'one_phase', 10000, 19.99,
                     CAST(:rules AS jsonb), true, 10, 5, 10, 80),
                    (20, 2, 'Synthetic foreign program', 'one_phase', 'one_phase', 10000, 29.99,
                     CAST(:rules AS jsonb), true, 10, 5, 10, 80)
            """), {"rules": '{"staging":true}'})
            db.session.commit()
            app.tokens = {identity: db.session.get(User, identity).generate_access_token()
                          for identity in (1, 2, 3, 4)}
        yield app
    finally:
        if app is not None:
            with app.app_context():
                db.session.rollback()
                db.session.remove()
                db.engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def nowpayments_checkout_http_app(staging_resources, monkeypatch):
    with _checkout_http_database(staging_resources, monkeypatch) as app:
        yield app


def _headers(app, actor=2, key=None):
    headers = {"Authorization": "Bearer " + app.tokens[actor]}
    if key is not None:
        headers["Idempotency-Key"] = key
    return headers


def _quote(app, *, actor=2, program_id=10, key="http_quote_key_0001"):
    response = app.test_client().post(
        "/api/v1/orders/", json={"program_id": program_id}, headers=_headers(app, actor, key),
    )
    assert response.status_code == 201, response.get_json()
    return response.get_json()["order"]["id"]


def _provider_response(payload, *, status="waiting", payment_id=123456789):
    return {
        "payment_id": payment_id,
        "payment_status": status,
        "pay_address": _TRON_ADDRESS,
        "price_amount": "19.99",
        "price_currency": "usd",
        "pay_amount": "20.0",
        "pay_currency": "usdttrc20",
        "order_id": payload["order_id"],
        "network": "TRC20",
        "payin_extra_id": None,
        "expiration_estimate_date": "2030-01-01T00:00:00Z",
    }


def _finished(reference):
    return {
        "payment_id": 123456789,
        "parent_payment_id": None,
        "payment_status": "finished",
        "pay_address": _TRON_ADDRESS,
        "payin_extra_id": None,
        "price_amount": 19.99,
        "price_currency": "usd",
        "pay_amount": 20,
        "actually_paid": 20,
        "pay_currency": "usdttrc20",
        "order_id": reference,
        "outcome_amount": 19.8,
        "outcome_currency": "usdttrc20",
    }


def _signed(body):
    from src.services.nowpayments_checkout import canonical_ipn_bytes, parse_bounded_json

    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    signature = hmac.new(_SECRET.encode("utf-8"), canonical_ipn_bytes(parse_bounded_json(raw)), hashlib.sha512).hexdigest()
    return raw, signature


def _notify(app, body):
    raw, signature = _signed(body)
    return app.test_client().post(
        "/api/v1/orders/webhooks/nowpayments", data=raw, content_type="application/json",
        headers={"x-nowpayments-sig": signature},
    )


def _bind_waiting(app, monkeypatch, *, quote_key="http_quote_key_0002", create_key="http_create_key_0002", payment_id=123456789):
    """Create a quote and a single locally transported waiting payment binding."""
    from src.services.nowpayments_checkout import NowPaymentsCheckoutService, NowPaymentsTransport

    calls, prepare_traces = [], []
    original_prepare = NowPaymentsCheckoutService.prepare_create

    def traced_prepare(*args, **kwargs):
        try:
            return original_prepare(*args, **kwargs)
        except Exception:
            prepare_traces.append(traceback.format_exc(limit=8))
            raise

    def provider(payload):
        calls.append(dict(payload))
        response = _provider_response(payload, payment_id=payment_id)
        return response, json.dumps(response, separators=(",", ":")).encode("utf-8")

    monkeypatch.setattr(NowPaymentsCheckoutService, "prepare_create", traced_prepare)
    monkeypatch.setattr(NowPaymentsTransport, "create_payment", provider)
    order_id = _quote(app, key=quote_key)
    created = app.test_client().post(
        f"/api/v1/orders/{order_id}/payments/nowpayments", json={"pay_currency": "usdttrc20"},
        headers=_headers(app, key=create_key),
    )
    if created.status_code != 201:
        from src.database import db
        from src.models.nowpayments_checkout import CheckoutIntent

        with app.app_context():
            intent = db.session.execute(select(CheckoutIntent).where(CheckoutIntent.order_id == order_id)).scalar_one_or_none()
            intent_state = None if intent is None else intent.state
        pytest.fail(
            f"create returned {created.get_json()!r}; provider_calls={calls!r}; intent_state={intent_state!r}; "
            f"prepare_trace={prepare_traces[-1:]!r}"
        )
    return order_id, calls[0]["order_id"]


def test_nowpayments_checkout_http_non_testing_semantic_guards_allow_complete_brevo_and_pilot(
    nowpayments_checkout_http_app,
):
    """The Testing factory skip is not evidence for the real deployment guards."""
    from src.production_safety import (
        validate_demo_release_configuration,
        validate_production_configuration,
    )

    demo = _non_testing_demo_config(nowpayments_checkout_http_app)
    assert demo["TESTING"] is False
    validate_demo_release_configuration(demo)

    production = dict(demo)
    production.update({
        "PRODUCTION": True,
        "DEMO_RELEASE_ENABLED": False,
        "DEBUG": False,
        "SECRET_KEY": "staging-http-production-secret-abcdefghijklmnopqrstuvwxyz",
        "JWT_SECRET_KEY": "staging-http-production-jwt-abcdefghijklmnopqrstuvwxyz",
        "SQLALCHEMY_DATABASE_URI": "postgresql://staging:synthetic@database.invalid:5432/staging",
        "REDIS_URL": "redis://redis.invalid:6379/0",
        "CACHE_TYPE": "RedisCache",
        "RATELIMIT_ENABLED": True,
        "CACHE_REDIS_URL": "redis://cache.invalid:6379/1",
        "RATELIMIT_STORAGE_URL": "redis://limiter.invalid:6379/2",
    })
    validate_production_configuration(production)


def test_nowpayments_checkout_http_capabilities_create_commits_before_transport(nowpayments_checkout_http_app, monkeypatch):
    """Real PG readiness, capability DTO, and committed local command precede fake I/O."""
    from src.database import db
    from src.models.nowpayments_checkout import CheckoutIntent, NowPaymentsPaymentBinding
    from src.services.nowpayments_checkout import NowPaymentsTransport
    from src.services.nowpayments_checkout_schema import validate_checkout_schema

    app = nowpayments_checkout_http_app
    client = app.test_client()
    with app.app_context():
        assert validate_checkout_schema(db.session.connection()) is True
    capabilities = client.get("/api/v1/orders/payment-capabilities", headers=_headers(app))
    assert capabilities.status_code == 200
    assert capabilities.get_json() == {
        "schema_version": 1,
        "owner_context": {"user_id": 2, "tenant_id": 1, "role": "trader"},
        "enabled": True,
        "reason": None,
        "currencies": [{"code": "usdttrc20", "label": "Synthetic USDT / TRC20", "network": "TRC20", "decimals": 6}],
        "quote_currency": "USD",
        "fee_paid_by_user": False,
        "policy_version": "staging-http-policy-v1",
        "live_trading_enabled": False,
    }
    # The additive customer scope deliberately ignores the individual pilot-ID
    # tuple, but remains confined to this allowed brand and trader/affiliate
    # role set.  Restore the default pilot scope before command creation.
    app.config["NOWPAYMENTS_CHECKOUT_SCOPE"] = "customers"
    customer_capabilities = client.get("/api/v1/orders/payment-capabilities", headers=_headers(app, 3))
    assert customer_capabilities.status_code == 200
    assert customer_capabilities.get_json()["enabled"] is True
    assert customer_capabilities.get_json()["owner_context"] == {"user_id": 3, "tenant_id": 1, "role": "trader"}
    app.config["NOWPAYMENTS_CHECKOUT_SCOPE"] = "pilot"

    order_id = _quote(app, key="http_quote_key_transport")
    independent = create_engine(app.config["SQLALCHEMY_DATABASE_URI"])
    calls, sql_while_transport = [], []
    transport_active = False

    def observe(_connection, _cursor, statement, _parameters, _context, _executemany):
        if transport_active:
            sql_while_transport.append(statement)

    def provider(payload):
        nonlocal transport_active
        transport_active = True
        try:
            # Route code removed the scoped request session after the reserve
            # commit.  The independent PG connection can already see that durable
            # reserved command while no application-engine SQL is allowed here.
            assert db.session().in_transaction() is False
            with independent.connect() as connection:
                command = connection.execute(text("""
                    SELECT state, dispatch_reserved_at IS NOT NULL AS reserved, external_reference
                    FROM checkout_intents WHERE order_id = :order_id
                """), {"order_id": order_id}).mappings().one()
            assert command["state"] == "creating" and command["reserved"] is True
            assert command["external_reference"] == payload["order_id"]
            assert sql_while_transport == []
            calls.append(dict(payload))
            response = _provider_response(payload)
            return response, json.dumps(response, separators=(",", ":")).encode("utf-8")
        finally:
            transport_active = False

    with app.app_context():
        event.listen(db.engine, "before_cursor_execute", observe)
    monkeypatch.setattr(NowPaymentsTransport, "create_payment", provider)
    try:
        created = client.post(
            f"/api/v1/orders/{order_id}/payments/nowpayments", json={"pay_currency": "usdttrc20"},
            headers=_headers(app, key="http_create_key_transport"),
        )
    finally:
        with app.app_context():
            event.remove(db.engine, "before_cursor_execute", observe)
        independent.dispose()
    if created.status_code != 201:
        with app.app_context():
            intent = db.session.execute(select(CheckoutIntent).where(CheckoutIntent.order_id == order_id)).scalar_one_or_none()
            intent_state = None if intent is None else intent.state
        pytest.fail(f"create returned {created.get_json()!r}; provider_calls={calls!r}; intent_state={intent_state!r}")
    body = created.get_json()
    assert body["state"] == "awaiting_payment" and body["payment"]["pay_amount"] == "20"
    assert body["creation_attempted"] is True and body["can_create"] is False
    assert sql_while_transport == [] and len(calls) == 1
    assert set(calls[0]) == {
        "price_amount", "price_currency", "pay_currency", "ipn_callback_url", "order_id",
        "is_fixed_rate", "is_fee_paid_by_user",
    }
    assert calls[0]["price_amount"] == "19.99" and calls[0]["is_fixed_rate"] is False
    serialized = json.dumps(body, sort_keys=True)
    assert app.config["SQLALCHEMY_DATABASE_URI"] not in serialized
    assert _API_KEY not in serialized and _SECRET not in serialized
    with app.app_context():
        assert db.session.execute(select(CheckoutIntent).where(CheckoutIntent.order_id == order_id)).scalar_one().state == "awaiting_payment"
        assert db.session.query(NowPaymentsPaymentBinding).count() == 1


def test_nowpayments_checkout_http_signed_finished_callback_is_atomic_and_replay_safe(nowpayments_checkout_http_app, monkeypatch):
    """A signed completion commits the exact deferred chain once and balances its ledger."""
    from src.database import db
    from src.models.nowpayments_checkout import (
        NowPaymentsObservation, NowPaymentsSettlementEntry, NowPaymentsSettlementJournal,
        NowPaymentsVerifiedReceipt, OrderEntitlementGrant,
    )

    app = nowpayments_checkout_http_app
    order_id, reference = _bind_waiting(app, monkeypatch)
    first = _notify(app, _finished(reference))
    replay = _notify(app, _finished(reference))
    assert first.status_code == replay.status_code == 200
    assert first.get_json() == {"schema_version": 1, "replayed": False}
    assert replay.get_json() == {"schema_version": 1, "replayed": True}
    projection = app.test_client().get(f"/api/v1/orders/{order_id}/payment", headers=_headers(app))
    assert projection.status_code == 200
    assert projection.get_json()["state"] == "paid"
    assert projection.get_json()["paid"] is projection.get_json()["recorded_purchase"] is True
    with app.app_context():
        receipt = db.session.execute(select(NowPaymentsVerifiedReceipt)).scalar_one()
        journal = db.session.execute(select(NowPaymentsSettlementJournal)).scalar_one()
        entries = db.session.execute(select(NowPaymentsSettlementEntry).order_by(NowPaymentsSettlementEntry.line_number)).scalars().all()
        assert receipt.order_id == journal.order_id == order_id
        assert receipt.amount_minor == journal.amount_minor == 1999
        assert receipt.currency == journal.currency == "USD"
        assert [(entry.line_number, entry.side, entry.account_code, entry.amount_minor) for entry in entries] == [
            (1, "debit", "provider_clearing", 1999),
            (2, "credit", "unapplied_order_receipts", 1999),
        ]
        assert sum(entry.amount_minor for entry in entries if entry.side == "debit") == sum(
            entry.amount_minor for entry in entries if entry.side == "credit"
        ) == 1999
        assert db.session.query(NowPaymentsObservation).count() == 1
        assert db.session.query(OrderEntitlementGrant).count() == 1
        # A completed HTTP commit proves PostgreSQL's INITIALLY DEFERRED chain
        # validator accepted receipt, journal, exact two entries, and grant together.
        assert db.session.query(NowPaymentsVerifiedReceipt).count() == db.session.query(NowPaymentsSettlementJournal).count() == 1


def test_nowpayments_checkout_http_invalid_ipn_and_stale_storage_never_grant_or_activate(nowpayments_checkout_http_app, monkeypatch):
    """Only one exact signed final callback can settle; stale storage closes every path."""
    from src.database import db
    from src.models.nowpayments_checkout import CheckoutIntent, NowPaymentsVerifiedReceipt, OrderEntitlementGrant

    app = nowpayments_checkout_http_app
    unsigned_order, unsigned_reference = _bind_waiting(
        app, monkeypatch, quote_key="http_quote_key_unsigned", create_key="http_create_key_unsigned",
    )
    raw, _signature = _signed(_finished(unsigned_reference))
    unsigned = app.test_client().post(
        "/api/v1/orders/webhooks/nowpayments", data=raw, content_type="application/json",
    )
    assert unsigned.status_code == 401 and unsigned.get_json()["code"] == "IPN_INVALID"

    for tag, changes, payment_id in (
        ("mismatch", {"price_amount": 19.98}, 123456790),
        ("underpaid", {"actually_paid": 19.999999}, 123456791),
    ):
        order_id, reference = _bind_waiting(
            app, monkeypatch,
            quote_key=f"http_quote_key_{tag}", create_key=f"http_create_key_{tag}",
            payment_id=payment_id,
        )
        rejected = _notify(app, {**_finished(reference), "payment_id": payment_id, **changes})
        assert rejected.status_code == 200 and rejected.get_json() == {"schema_version": 1, "replayed": False}
        projection = app.test_client().get(f"/api/v1/orders/{order_id}/payment", headers=_headers(app))
        assert projection.status_code == 200
        assert projection.get_json()["state"] == "manual_review"
        assert projection.get_json()["paid"] is projection.get_json()["recorded_purchase"] is False

    # Revision 000001 lacks the checkout schema. The actual service readiness
    # guard must block both callback settlement and a fresh local command before
    # provider transport; this is runner-owned PostgreSQL only, never a migration.
    with app.app_context():
        db.session.execute(text("UPDATE alembic_version SET version_num = '20261013_000001'"))
        db.session.commit()
    capabilities = app.test_client().get("/api/v1/orders/payment-capabilities", headers=_headers(app))
    assert capabilities.status_code == 200
    assert capabilities.get_json()["enabled"] is False
    assert capabilities.get_json()["reason"] == "CHECKOUT_STORAGE_NOT_READY"
    blocked_callback = _notify(app, _finished(unsigned_reference))
    assert blocked_callback.status_code == 503
    assert blocked_callback.get_json()["code"] == "CHECKOUT_STORAGE_NOT_READY"
    stale_order = _quote(app, key="http_quote_key_stale_revision")
    blocked_create = app.test_client().post(
        f"/api/v1/orders/{stale_order}/payments/nowpayments", json={"pay_currency": "usdttrc20"},
        headers=_headers(app, key="http_create_key_stale_revision"),
    )
    assert blocked_create.status_code == 503
    assert blocked_create.get_json()["code"] == "CHECKOUT_STORAGE_NOT_READY"
    with app.app_context():
        assert db.session.query(NowPaymentsVerifiedReceipt).count() == 0
        assert db.session.query(OrderEntitlementGrant).count() == 0
        assert db.session.execute(select(CheckoutIntent).where(CheckoutIntent.order_id == stale_order)).scalar_one_or_none() is None
        assert db.session.execute(select(CheckoutIntent).where(CheckoutIntent.order_id == unsigned_order)).scalar_one().state == "awaiting_payment"


def test_nowpayments_checkout_http_read_models_are_local_owner_scoped_and_brand_isolated(nowpayments_checkout_http_app, monkeypatch):
    """Historical GETs are provider-free and never disclose another buyer or brand."""
    from src.services.nowpayments_checkout import NowPaymentsTransport

    app = nowpayments_checkout_http_app
    order_id, reference = _bind_waiting(app, monkeypatch, quote_key="http_quote_key_reads", create_key="http_create_key_reads")
    assert _notify(app, _finished(reference)).status_code == 200
    foreign_quote = app.test_client().post('/api/v1/orders/', json={'program_id':20}, headers=_headers(app,4,'http_quote_key_foreign'))
    assert foreign_quote.status_code == 401, 'cross-brand hierarchy session is rejected before an order exists'
    app.config["NOWPAYMENTS_PILOT_ENABLED"] = False

    def supplier_on_read(*_args, **_kwargs):
        pytest.fail("a local checkout read must not call a supplier")

    monkeypatch.setattr(NowPaymentsTransport, "create_payment", supplier_on_read)
    monkeypatch.setattr(NowPaymentsTransport, "get_payment", supplier_on_read)
    client = app.test_client()
    owner = client.get(f"/api/v1/orders/{order_id}/payment", headers=_headers(app, 2))
    purchases = client.get("/api/v1/orders/purchases", headers=_headers(app, 2))
    finance = client.get("/api/v1/orders/payment-records", headers=_headers(app, 1))
    other_payment = client.get(f"/api/v1/orders/{order_id}/payment", headers=_headers(app, 3))
    other_records = client.get("/api/v1/orders/purchases", headers=_headers(app, 3))
    foreign_payment = client.get(f"/api/v1/orders/{order_id}/payment", headers=_headers(app, 4))
    foreign_records = client.get("/api/v1/orders/purchases", headers=_headers(app, 4))
    assert owner.status_code == purchases.status_code == finance.status_code == 200
    assert other_payment.status_code == 404
    assert foreign_payment.status_code == foreign_records.status_code == 401
    assert other_records.status_code == 200
    assert owner.get_json()["state"] == "paid" and owner.get_json()["can_create"] is False
    assert purchases.get_json()["owner_context"] == {"user_id": 2, "tenant_id": 1, "role": "trader"}
    assert [row["order_id"] for row in purchases.get_json()["records"]] == [order_id]
    assert other_records.get_json()["records"] == []
    assert 'records' not in foreign_records.get_json() and order_id not in json.dumps(foreign_payment.get_json())
    finance_body = finance.get_json()
    assert finance_body["owner_context"] == {"user_id": 1, "tenant_id": 1, "role": "supermaster"}
    assert finance_body["pagination"]["total"] == 1
    record = finance_body["records"][0]
    assert record == {
        "order_id": order_id, "program_id": 10, "program_name": "Synthetic HTTP program",
        "user_id": 2, "tenant_id": 1, "state": "paid", "paid": True, "review_required": False,
        "quote_amount_minor": "1999", "quote_currency": "USD", "provider_payment_id": "123456789",
        "pay_currency": "usdttrc20", "network": "TRC20", "actually_paid": "20",
        "outcome_amount": "19.8", "outcome_currency": "usdttrc20", "updated_at": record["updated_at"],
        "recorded_purchase": True,
    }
    assert all(row['tenant_id'] == 1 and row['user_id'] != 4 for row in finance_body['records'])
    assert _API_KEY not in json.dumps({"owner": owner.get_json(), "finance": finance_body})


def test_nowpayments_checkout_http_refresh_needs_signed_ipn_and_early_ipn_does_not_regress(nowpayments_checkout_http_app, monkeypatch):
    """Manual refresh cannot grant; the same canonical signed IPN can, including during POST."""
    from src.database import db
    from src.models.nowpayments_checkout import (
        CheckoutIntent, NowPaymentsPaymentBinding, NowPaymentsSettlementEntry,
        NowPaymentsVerifiedReceipt, OrderEntitlementGrant,
    )
    from src.services.nowpayments_checkout import NowPaymentsTransport, parse_bounded_json

    app = nowpayments_checkout_http_app
    order_id, reference = _bind_waiting(app, monkeypatch, quote_key="http_quote_key_refresh", create_key="http_create_key_refresh")
    finished = _finished(reference)
    raw, _signature = _signed(finished)

    def get_finished(payment_id):
        assert payment_id == "123456789" and db.session().in_transaction() is False
        return parse_bounded_json(raw), raw

    monkeypatch.setattr(NowPaymentsTransport, "get_payment", get_finished)
    refreshed = app.test_client().post(
        f"/api/v1/orders/{order_id}/payment/refresh", json={}, headers=_headers(app, key="http_refresh_key_0001"),
    )
    assert refreshed.status_code == 200, refreshed.get_json()
    assert refreshed.get_json()["state"] == "processing" and refreshed.get_json()["paid"] is False
    assert app.test_client().post(
        f"/api/v1/orders/{order_id}/payment/refresh", json={}, headers=_headers(app, key="http_refresh_key_0002"),
    ).status_code == 429
    signed = _notify(app, finished)
    assert signed.status_code == 200 and signed.get_json()["replayed"] is False
    assert app.test_client().get(f"/api/v1/orders/{order_id}/payment", headers=_headers(app)).get_json()["state"] == "paid"

    early_order = _quote(app, key="http_quote_key_early")
    nested_client = app.test_client()
    nested_callbacks = []

    def provider_with_early_ipn(payload):
        early_finished = _finished(payload["order_id"])
        early_finished['payment_id'] = 987654321
        callback = _notify(app, early_finished)
        nested_callbacks.append(callback.get_json())
        assert callback.status_code == 200
        response = _provider_response(payload)
        response['payment_id'] = 987654321
        return response, json.dumps(response, separators=(",", ":")).encode("utf-8")

    monkeypatch.setattr(NowPaymentsTransport, "create_payment", provider_with_early_ipn)
    early_created = nested_client.post(
        f"/api/v1/orders/{early_order}/payments/nowpayments", json={"pay_currency": "usdttrc20"},
        headers=_headers(app, key="http_create_key_early"),
    )
    assert early_created.status_code == 201, early_created.get_json()
    assert nested_callbacks == [{"schema_version": 1, "replayed": False}]
    early_projection = nested_client.get(f"/api/v1/orders/{early_order}/payment", headers=_headers(app)).get_json()
    assert early_projection["state"] == "paid" and early_projection["paid"] is True
    with app.app_context():
        intent = db.session.execute(select(CheckoutIntent).where(CheckoutIntent.order_id == early_order)).scalar_one()
        assert intent.state == "paid"
        assert db.session.execute(select(NowPaymentsPaymentBinding).where(NowPaymentsPaymentBinding.order_id == early_order)).scalar_one()
        assert db.session.execute(select(OrderEntitlementGrant).where(OrderEntitlementGrant.order_id == early_order)).scalar_one()
        assert db.session.execute(select(NowPaymentsVerifiedReceipt).where(NowPaymentsVerifiedReceipt.order_id == early_order)).scalar_one()
        assert db.session.query(NowPaymentsSettlementEntry).filter_by(journal_id=db.session.execute(text("""
            SELECT id FROM nowpayments_settlement_journals WHERE order_id = :order_id
        """), {"order_id": early_order}).scalar_one()).count() == 2


def test_nowpayments_checkout_http_early_conflicting_signed_callback_commits_sticky_review(nowpayments_checkout_http_app,monkeypatch):
    from src.database import db
    from src.models.nowpayments_checkout import OrderEntitlementGrant,NowPaymentsVerifiedReceipt
    from src.services.nowpayments_checkout import NowPaymentsTransport
    app=nowpayments_checkout_http_app
    order_id=_quote(app,key='http_quote_key_review')
    references=[]
    def early(payload):
        references.append(payload['order_id'])
        body=_finished(payload['order_id']);body['price_amount']=19.98
        rejected=_notify(app,body)
        assert rejected.status_code==200,rejected.get_json()
        stored=app.test_client().get(f'/api/v1/orders/{order_id}/payment',headers=_headers(app)).get_json()
        assert stored['state']=='manual_review' and stored['paid'] is False
        response=_provider_response(payload)
        return response,json.dumps(response,separators=(',',':')).encode()
    monkeypatch.setattr(NowPaymentsTransport,'create_payment',early)
    created=app.test_client().post(f'/api/v1/orders/{order_id}/payments/nowpayments',json={'pay_currency':'usdttrc20'},headers=_headers(app,key='http_create_key_review'))
    assert created.status_code==201,created.get_json()
    assert _notify(app,_finished(references[0])).status_code==200
    stored=app.test_client().get(f'/api/v1/orders/{order_id}/payment',headers=_headers(app)).get_json()
    assert stored['state']=='manual_review' and stored['recorded_purchase'] is False
    with app.app_context():
        assert db.session.query(OrderEntitlementGrant).count()==db.session.query(NowPaymentsVerifiedReceipt).count()==0
