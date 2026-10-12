"""Fail-closed public catalog regressions using only synthetic SQLite state."""
from decimal import Decimal

import pytest
from sqlalchemy import event

from src.database import db
from src.models.purchase_order import PurchaseOrder
from src.models.tenant import Tenant
from src.models.token_blacklist import TokenBlacklist
from src.models.trading_program import Challenge, ProgramAddOn, TradingProgram
from src.models.user import User
from src.services.order_service import OrderService


@pytest.fixture
def catalog_app():
    from src.app import create_app

    app = create_app("testing", config_overrides={
        "EXPANDED_HIERARCHY_ENABLED": False,
        "PLATFORM_ROOT_USER_ID": 1,
        "ORDER_QUOTES_ENABLED": True,
        "ORDER_QUOTE_CURRENCY": "USD",
        "PROPAGATE_EXCEPTIONS": False,
    })
    tables = [
        Tenant.__table__, User.__table__, TokenBlacklist.__table__, TradingProgram.__table__,
        ProgramAddOn.__table__, Challenge.__table__, PurchaseOrder.__table__,
    ]
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=tables)
        db.session.add_all([
            Tenant(id=1, name="Configured Brand", subdomain="configured", status="active"),
            Tenant(id=2, name="Foreign Brand", subdomain="foreign", status="active"),
            User(
                id=1, email="catalog-root@example.invalid", password_hash="not-a-credential",
                first_name="Configured", last_name="Root", tenant_id=1, role="supermaster",
                parent_id=None, level=0, tree_path="1", is_active=True, is_verified=True,
                can_create_same_role=True,
            ),
            User(
                id=2, email="catalog-user@example.invalid", password_hash="not-a-credential",
                first_name="Catalog", last_name="User", tenant_id=1, role="trader",
                parent_id=1, level=1, tree_path="1/2", is_active=True, is_verified=True,
                can_create_same_role=False,
            ),
            TradingProgram(
                id=10, tenant_id=1, name="Configured Zeroes", type="unknown_ascii_offer",
                description="Catalog terms are stored terms, not a verification claim.",
                payout_mode="on_demand", account_size=Decimal("10000.00"),
                profit_target=Decimal("0.00"), max_daily_loss=Decimal("0.00"),
                max_total_loss=Decimal("10.00"), price=Decimal("19.99"),
                profit_split=Decimal("0.00"), profit_split_percentage=Decimal("0.00"),
                minimum_payout_amount=Decimal("0.00"), rules={"nested": {"target": None}},
                is_active=True,
            ),
            TradingProgram(
                id=11, tenant_id=2, name="Foreign", type="one_phase", account_size=Decimal("10000.00"),
                price=Decimal("1.00"), rules={}, is_active=True,
            ),
            TradingProgram(
                id=12, tenant_id=1, name="Inactive", type="one_phase", account_size=Decimal("10000.00"),
                price=Decimal("1.00"), rules={}, is_active=False,
            ),
            ProgramAddOn(
                id=20, program_id=10, name="Zero fixed", description=None, price=Decimal("0.00"),
                price_type="fixed", benefits={"feature": None}, is_active=True,
            ),
            ProgramAddOn(
                id=21, program_id=10, name="Percentage", description="Bounded rate", price=Decimal("10.00"),
                price_type="percentage", benefits={}, is_active=True,
            ),
            ProgramAddOn(
                id=22, program_id=11, name="Foreign add-on", price=Decimal("1.00"),
                price_type="fixed", benefits={}, is_active=True,
            ),
            ProgramAddOn(
                id=23, program_id=10, name="Inactive add-on", price=Decimal("1.00"),
                price_type="fixed", benefits={}, is_active=False,
            ),
        ])
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.metadata.drop_all(bind=db.engine, tables=list(reversed(tables)))


def test_public_catalog_uses_only_configured_root_and_ignores_selectors(catalog_app):
    client = catalog_app.test_client()
    headers = {"Host": "foreign.example.invalid", "X-Tenant-ID": "2"}
    response = client.get("/api/v1/programs/?tenant_id=2&brand=foreign", headers=headers)
    assert response.status_code == 200
    body = response.get_json()
    assert [program["id"] for program in body["programs"]] == [10]

    detail = client.get("/api/v1/programs/10?tenant_id=2", headers=headers)
    assert detail.status_code == 200
    program = detail.get_json()
    assert program["tenant_id"] == 1 and [addon["id"] for addon in program["addons"]] == [20, 21]


def test_catalog_decimal_shape_zero_and_terms_are_quote_snapshot_terms(catalog_app):
    client = catalog_app.test_client()
    program = client.get("/api/v1/programs/10").get_json()
    expected_top = {
        "account_size": "10000.00", "profit_target": "0.00", "max_daily_loss": "0.00",
        "max_total_loss": "10.00", "price": "19.99", "profit_split": "0.00",
    }
    assert {key: program[key] for key in expected_top} == expected_top
    assert program["currency"] == "USD"
    assert program["name"] == program["terms"]["name"]
    assert program["type"] == program["terms"]["type"]
    assert program["description"] == program["terms"]["description"]
    assert program["rules"] == program["terms"]["rules"] == {"nested": {"target": None}}
    assert program["terms"]["minimum_payout_amount"] == "0.00"
    assert program["addons"][0]["price"] == "0.00"
    assert program["addons"][1]["price"] == "10.00"

    with catalog_app.app_context(), catalog_app.test_request_context("/api/v1/orders/"):
        actor = db.session.get(User, 2)
        order, created = OrderService.create_quote(actor, {"program_id": 10, "addon_ids": [20, 21]}, "catalog_terms_parity_0001")
        db.session.commit()
        snapshot = order.to_dict()["snapshot"]
    assert created is True
    assert snapshot["base_amount"] == program["price"]
    assert snapshot["terms"] == program["terms"]


@pytest.mark.parametrize("program_id", [11, 12, 999])
def test_foreign_inactive_and_missing_detail_are_the_same_404(catalog_app, program_id):
    response = catalog_app.test_client().get(f"/api/v1/programs/{program_id}?tenant_id=2")
    assert response.status_code == 404
    assert response.get_json() == {"error": "Resource not found"}


def test_missing_currency_policy_and_unavailable_root_fail_before_program_read(catalog_app):
    statements = []

    def observe(_, __, statement, *___):
        if "trading_programs" in statement.lower():
            statements.append(statement)

    with catalog_app.app_context():
        event.listen(db.engine, "before_cursor_execute", observe)
    try:
        catalog_app.config["ORDER_QUOTE_CURRENCY"] = None
        response = catalog_app.test_client().get("/api/v1/programs/")
        assert response.status_code == 503 and response.get_json()["code"] == "CATALOG_UNAVAILABLE"
        assert statements == []

        catalog_app.config["ORDER_QUOTE_CURRENCY"] = "USD"
        with catalog_app.app_context():
            db.session.get(User, 1).is_active = False
            db.session.commit()
        response = catalog_app.test_client().get("/api/v1/programs/?tenant_id=2")
        assert response.status_code == 503 and response.get_json()["code"] == "CATALOG_UNAVAILABLE"
        assert statements == []
    finally:
        with catalog_app.app_context():
            event.remove(db.engine, "before_cursor_execute", observe)


def test_list_uses_one_bounded_program_query_and_never_loads_addons(catalog_app):
    statements = []

    def observe(_, __, statement, *___):
        lowered = statement.lower()
        if "trading_programs" in lowered or "program_addons" in lowered:
            statements.append(lowered)

    with catalog_app.app_context():
        event.listen(db.engine, "before_cursor_execute", observe)
    try:
        response = catalog_app.test_client().get("/api/v1/programs/")
    finally:
        with catalog_app.app_context():
            event.remove(db.engine, "before_cursor_execute", observe)
    assert response.status_code == 200
    assert len([sql for sql in statements if "trading_programs" in sql]) == 1
    assert not any("program_addons" in sql for sql in statements)
    assert "limit" in statements[0]


def test_over_budget_programs_or_addons_return_503_without_truncation(catalog_app):
    with catalog_app.app_context():
        db.session.add_all([
            TradingProgram(
                id=1000 + index, tenant_id=1, name=f"Extra {index}", type="one_phase",
                account_size=Decimal("1.00"), price=Decimal("1.00"), rules={}, is_active=True,
            )
            for index in range(200)
        ])
        db.session.commit()
    assert catalog_app.test_client().get("/api/v1/programs/").status_code == 503

    with catalog_app.app_context():
        db.session.query(TradingProgram).filter(TradingProgram.id >= 1000).delete()
        db.session.add_all([
            ProgramAddOn(
                id=1000 + index, program_id=10, name=f"Extra {index}", price=Decimal("0.00"),
                price_type="fixed", benefits={}, is_active=True,
            )
            for index in range(200)
        ])
        db.session.commit()
    assert catalog_app.test_client().get("/api/v1/programs/10").status_code == 503


def test_malformed_catalog_never_coerces_or_leaks_a_500(catalog_app):
    with catalog_app.app_context():
        program = db.session.get(TradingProgram, 10)
        program.rules = []
        db.session.commit()
    response = catalog_app.test_client().get("/api/v1/programs/10")
    assert response.status_code == 503
    assert response.get_json()["code"] == "CATALOG_UNAVAILABLE"


def test_complete_terms_snapshot_has_a_64_kib_budget(catalog_app):
    with catalog_app.app_context():
        db.session.get(TradingProgram, 10).description = "x" * 65536
        db.session.commit()
    response = catalog_app.test_client().get("/api/v1/programs/10")
    assert response.status_code == 503
    assert response.get_json()["code"] == "CATALOG_UNAVAILABLE"
