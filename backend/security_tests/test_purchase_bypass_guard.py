"""Stage4a regressions for disabled legacy purchase and challenge lifecycle paths.

The scratch schema is deliberately explicit: this executes production route
registration, JWT authentication, and ORM models without a provider, private
DB, or metadata-wide setup.
"""
from decimal import Decimal

import pytest
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from src.database import db
from src.models.payment import Payment
from src.models.payment_approval import PaymentApprovalRequest
from src.models.purchase_order import PurchaseOrder
from src.models.tenant import Tenant
from src.models.token_blacklist import TokenBlacklist
from src.models.trading_program import Challenge, ProgramAddOn, TradingProgram
from src.models.user import User


@compiles(JSONB, "sqlite")
def _jsonb_as_json_for_scratch_sqlite(type_, compiler, **kwargs):
    """Compile production PostgreSQL JSONB fields in this isolated SQLite DB."""
    return "JSON"


_ROOT_ID = 8101
_TRADER_ID = 8102
_FOREIGN_ID = 8103
_TENANT_ID = 81
_PROGRAM_ID = 8201
_OWNED_PENDING_CHALLENGE_ID = 8301
_FOREIGN_PENDING_CHALLENGE_ID = 8302
_SETTLEMENT_DISABLED = {
    "error": "Order settlement is not configured",
    "code": "ORDER_SETTLEMENT_NOT_CONFIGURED",
}
_TABLES = (
    Tenant.__table__,
    User.__table__,
    TokenBlacklist.__table__,
    TradingProgram.__table__,
    ProgramAddOn.__table__,
    Challenge.__table__,
    Payment.__table__,
    PaymentApprovalRequest.__table__,
    # Parent-owned Stage4 order model must be explicitly present in scratch DB.
    PurchaseOrder.__table__,
)


def _user(*, user_id, email, role, parent_id, path, can_create_same_role=False):
    return User(
        id=user_id,
        email=email,
        password_hash="not-a-login-credential",
        first_name="Guard",
        last_name="Fixture",
        role=role,
        parent_id=parent_id,
        tree_path=path,
        level=0 if parent_id is None else 1,
        tenant_id=_TENANT_ID,
        is_active=True,
        is_verified=True,
        can_create_same_role=can_create_same_role,
    )


@pytest.fixture
def purchase_bypass_guard_app():
    """A full production factory backed by minimal, isolated real models."""
    from src.app import create_app

    app = create_app(
        "testing",
        config_overrides={
            "EXPANDED_HIERARCHY_ENABLED": False,
            "PLATFORM_ROOT_USER_ID": _ROOT_ID,
            "PROPAGATE_EXCEPTIONS": False,
            "RATELIMIT_ENABLED": False,
        },
    )
    with app.app_context():
        for table in _TABLES:
            table.create(db.engine)
        db.session.add(Tenant(
            id=_TENANT_ID,
            name="Purchase Guard",
            subdomain="purchase-guard",
            status="active",
        ))
        db.session.add_all([
            _user(
                user_id=_ROOT_ID,
                email="root@purchase-guard.invalid",
                role="supermaster",
                parent_id=None,
                path=str(_ROOT_ID),
                can_create_same_role=True,
            ),
            _user(
                user_id=_TRADER_ID,
                email="trader@purchase-guard.invalid",
                role="trader",
                parent_id=_ROOT_ID,
                path=f"{_ROOT_ID}/{_TRADER_ID}",
            ),
            _user(
                user_id=_FOREIGN_ID,
                email="foreign@purchase-guard.invalid",
                role="trader",
                parent_id=_ROOT_ID,
                path=f"{_ROOT_ID}/{_FOREIGN_ID}",
            ),
        ])
        db.session.add(TradingProgram(
            id=_PROGRAM_ID,
            tenant_id=_TENANT_ID,
            name="Guarded Program",
            type="one_phase",
            account_size=Decimal("10000.00"),
            price=Decimal("99.00"),
            profit_target=Decimal("8.00"),
            max_daily_loss=Decimal("5.00"),
            max_total_loss=Decimal("10.00"),
            rules={},
            is_active=True,
        ))
        db.session.add(ProgramAddOn(
            id=8202,
            program_id=_PROGRAM_ID,
            name="Guarded Add-on",
            price=Decimal("10.00"),
            benefits={},
            is_active=True,
        ))
        db.session.add_all([
            Challenge(
                id=_OWNED_PENDING_CHALLENGE_ID,
                user_id=_TRADER_ID,
                program_id=_PROGRAM_ID,
                status="pending",
                payment_status="pending",
                payment_type="cash",
                approval_status="pending",
                initial_balance=Decimal("10000.00"),
                current_balance=Decimal("10000.00"),
            ),
            Challenge(
                id=_FOREIGN_PENDING_CHALLENGE_ID,
                user_id=_FOREIGN_ID,
                program_id=_PROGRAM_ID,
                status="pending",
                payment_status="pending",
                payment_type="free",
                approval_status="pending",
                initial_balance=Decimal("10000.00"),
                current_balance=Decimal("10000.00"),
            ),
        ])
        db.session.commit()
        app.purchase_guard_tokens = {
            "root": db.session.get(User, _ROOT_ID).generate_access_token(),
            "trader": db.session.get(User, _TRADER_ID).generate_access_token(),
        }
        db.session.remove()

    try:
        yield app
    finally:
        # Use a fresh application context only after requests complete; holding
        # one across requests would mask request-local g/session scope leaks.
        with app.app_context():
            db.session.remove()
            for table in reversed(_TABLES):
                table.drop(db.engine)


def _authorization(token):
    return {"Authorization": f"Bearer {token}"}


def _snapshot(app):
    """Capture writable lifecycle state from a fresh context, never request g."""
    with app.app_context():
        db.session.remove()
        snapshot = {
            "orders": PurchaseOrder.query.count(),
            "payments": Payment.query.count(),
            "approvals": PaymentApprovalRequest.query.count(),
            "challenges": [
                (row.id, row.user_id, row.status, row.payment_status, row.approval_status)
                for row in Challenge.query.order_by(Challenge.id).all()
            ],
        }
        db.session.remove()
        return snapshot


def _assert_settlement_gate(response, before, app):
    assert response.status_code == 503
    assert response.get_json() == _SETTLEMENT_DISABLED
    assert _snapshot(app) == before


def test_purchase_bypass_guard_blocks_request_controlled_free_cash_and_foreign_purchase(
    purchase_bypass_guard_app,
):
    """Signed trader and root claims cannot create settlement-adjacent records."""
    app = purchase_bypass_guard_app
    before = _snapshot(app)
    attacker_payload = {
        "addon_ids": [8202],
        "user_id": _FOREIGN_ID,
        "payment_type": "free",
        "payment_status": "paid",
        "approval_status": "approved",
        "status": "active",
    }

    trader_response = app.test_client().post(
        f"/api/v1/programs/{_PROGRAM_ID}/purchase",
        json={**attacker_payload, "payment_type": "cash"},
        headers=_authorization(app.purchase_guard_tokens["trader"]),
    )
    _assert_settlement_gate(trader_response, before, app)

    root_response = app.test_client().post(
        f"/api/v1/programs/{_PROGRAM_ID}/purchase",
        json=attacker_payload,
        headers=_authorization(app.purchase_guard_tokens["root"]),
    )
    _assert_settlement_gate(root_response, before, app)


def test_purchase_bypass_guard_blocks_direct_challenge_creation_and_start_without_mt5(
    purchase_bypass_guard_app, monkeypatch
):
    """Direct creation and pending-to-active legacy paths stop before lookups."""
    app = purchase_bypass_guard_app
    mt5_attribute_reads = []

    class _NoMT5Calls:
        def __getattr__(self, name):
            mt5_attribute_reads.append(name)
            raise AssertionError("legacy settlement gate must run before MT5 use")

    import src.routes.challenges as challenge_routes
    # The provider import is gone; a canary still proves no legacy use occurs.
    monkeypatch.setattr(challenge_routes, "mt5_challenge_service", _NoMT5Calls(), raising=False)
    before = _snapshot(app)
    malicious_direct_payload = {
        "program_id": _PROGRAM_ID,
        "user_id": _FOREIGN_ID,
        "payment_type": "free",
        "payment_status": "paid",
        "approval_status": "approved",
        "status": "active",
        "initial_balance": 999999,
    }

    direct_response = app.test_client().post(
        "/api/v1/challenges/",
        json=malicious_direct_payload,
        headers=_authorization(app.purchase_guard_tokens["trader"]),
    )
    _assert_settlement_gate(direct_response, before, app)

    owned_start = app.test_client().post(
        f"/api/v1/challenges/{_OWNED_PENDING_CHALLENGE_ID}/start",
        headers=_authorization(app.purchase_guard_tokens["trader"]),
    )
    _assert_settlement_gate(owned_start, before, app)
    assert _snapshot(app)["challenges"][0][2:4] == ("pending", "pending")

    foreign_start = app.test_client().post(
        f"/api/v1/challenges/{_FOREIGN_PENDING_CHALLENGE_ID}/start",
        headers=_authorization(app.purchase_guard_tokens["trader"]),
    )
    _assert_settlement_gate(foreign_start, before, app)
    assert foreign_start.get_json() == owned_start.get_json()
    assert mt5_attribute_reads == []


def test_purchase_bypass_guard_preserves_authentication_and_cookie_csrf_boundaries(
    purchase_bypass_guard_app,
):
    """The gate is inside handlers: unauthenticated and unsafe cookie calls stay protected."""
    app = purchase_bypass_guard_app
    before = _snapshot(app)

    anonymous = app.test_client().post(
        f"/api/v1/programs/{_PROGRAM_ID}/purchase",
        json={"payment_type": "free", "payment_status": "paid"},
    )
    assert anonymous.status_code == 401
    assert _snapshot(app) == before

    cookie_client = app.test_client()
    cookie_client.set_cookie("access_token", app.purchase_guard_tokens["root"])
    csrf_rejected = cookie_client.post(
        f"/api/v1/programs/{_PROGRAM_ID}/purchase",
        json={"user_id": _FOREIGN_ID, "payment_type": "free", "payment_status": "paid"},
    )
    assert csrf_rejected.status_code == 403
    assert csrf_rejected.get_json()["code"] == "CSRF_INVALID"
    assert _snapshot(app) == before
