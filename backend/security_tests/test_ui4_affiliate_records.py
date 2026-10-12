"""Focused real-Flask UI-4 affiliate record-read security contracts."""
from datetime import datetime, timedelta
from decimal import Decimal
import json

import pytest
from flask import Flask
from sqlalchemy import Column, Integer, Table, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from src.database import db
from src.models.affiliate import (
    AffiliateCommission,
    AffiliateLink,
    AffiliatePayout,
    AffiliateReferral,
    AffiliateSettings,
)
from src.models.tenant import Tenant
from src.models.token_blacklist import TokenBlacklist
from src.models.trading_program import TradingProgram
from src.models.user import User
from src.routes.affiliate import affiliate_bp


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_element, _compiler, **_kwargs):
    """Use JSON only in this synthetic SQLite route fixture."""
    return "JSON"


@pytest.fixture
def ui4_affiliate_records_app():
    """Real affiliate blueprint plus deliberately coherent and forged records."""
    app = Flask("ui4-affiliate-records-security")
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY="ui4-affiliate-records-synthetic-key",
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=10),
        JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=1),
        EXPANDED_HIERARCHY_ENABLED=True,
    )
    db.init_app(app)
    app.register_blueprint(affiliate_bp, url_prefix="/api/v1/affiliate")

    sentinel_created = "programs" not in db.metadata.tables
    programs = (
        Table("programs", db.metadata, Column("id", Integer, primary_key=True))
        if sentinel_created else db.metadata.tables["programs"]
    )
    tables = [
        Tenant.__table__, User.__table__, TokenBlacklist.__table__, TradingProgram.__table__, programs,
        AffiliateSettings.__table__, AffiliateLink.__table__, AffiliateReferral.__table__,
        AffiliatePayout.__table__, AffiliateCommission.__table__,
    ]
    instant = datetime(2026, 10, 12, 12, 0, 0)

    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=tables)
        db.session.add_all([
            Tenant(id=1, name="UI4 owner tenant", subdomain="ui4-records-owner", status="active"),
            Tenant(id=2, name="UI4 foreign tenant", subdomain="ui4-records-foreign", status="active"),
            User(id=2, email="affiliate@example.invalid", password_hash="x", first_name="Affiliate",
                 last_name="Owner", role="affiliate", tenant_id=1, is_active=True, is_verified=True,
                 tree_path="2", level=0),
            User(id=3, email="referred@example.invalid", password_hash="x", first_name="Referred",
                 last_name="Tenant", role="trader", tenant_id=1, is_active=True, is_verified=True,
                 tree_path="3", level=0),
            User(id=4, email="foreign@example.invalid", password_hash="x", first_name="Foreign",
                 last_name="Tenant", role="trader", tenant_id=2, is_active=True, is_verified=True,
                 tree_path="4", level=0),
            User(id=5, email="no-tenant@example.invalid", password_hash="x", first_name="No",
                 last_name="Tenant", role="affiliate", tenant_id=None, is_active=True, is_verified=True,
                 tree_path="5", level=0),
            User(id=6, email="foreign-owner@example.invalid", password_hash="x", first_name="Foreign",
                 last_name="Owner", role="affiliate", tenant_id=2, is_active=True, is_verified=True,
                 tree_path="6", level=0),
            TradingProgram(id=1, tenant_id=1, name="UI4 owner program", type="one_phase",
                           account_size=Decimal("1000.00"), price=Decimal("99.00"), is_active=True),
            TradingProgram(id=2, tenant_id=2, name="UI4 foreign program", type="one_phase",
                           account_size=Decimal("1000.00"), price=Decimal("99.00"), is_active=True),
            AffiliateLink(id=10, user_id=2, code="UI4OWNER", name="Do not disclose link name",
                          clicks=1, conversions=1, total_revenue=Decimal("1.00"),
                          total_commission=Decimal("1.00"), commission_rate=Decimal("15.00"),
                          created_at=instant),
            AffiliateLink(id=11, user_id=6, code="UI4FOREIGN", name="Foreign link",
                          clicks=1, conversions=1, total_revenue=Decimal("1.00"),
                          total_commission=Decimal("1.00"), commission_rate=Decimal("15.00"),
                          created_at=instant),
        ])
        db.session.flush()
        # Historic FK parent exists for ids 1/2/999; only current programs 1/2
        # are available to tenant-scoped UI4 reads.
        db.session.execute(programs.insert(), [{"id": 1}, {"id": 2}, {"id": 999}])
        db.session.add_all([
            AffiliateReferral(id=1, affiliate_link_id=10, affiliate_user_id=2, referred_user_id=3,
                              program_id=1, status="converted", purchase_amount=Decimal("0.00"),
                              commission_amount=Decimal("0.00"), click_date=instant,
                              conversion_date=instant + timedelta(minutes=1)),
            AffiliateReferral(id=2, affiliate_link_id=10, affiliate_user_id=2, referred_user_id=3,
                              program_id=1, status="pending", purchase_amount=None, commission_amount=None,
                              click_date=instant),
            # Every parent defect below must be excluded from both direct records
            # and commissions that cite it.
            AffiliateReferral(id=3, affiliate_link_id=10, affiliate_user_id=2, referred_user_id=2,
                              program_id=1, status="converted", click_date=instant),
            AffiliateReferral(id=4, affiliate_link_id=10, affiliate_user_id=2, referred_user_id=9999,
                              program_id=1, status="converted", click_date=instant),
            AffiliateReferral(id=5, affiliate_link_id=10, affiliate_user_id=2, referred_user_id=4,
                              program_id=1, status="converted", click_date=instant),
            AffiliateReferral(id=6, affiliate_link_id=11, affiliate_user_id=2, referred_user_id=3,
                              program_id=1, status="converted", click_date=instant),
            AffiliateReferral(id=7, affiliate_link_id=10, affiliate_user_id=3, referred_user_id=3,
                              program_id=1, status="converted", click_date=instant),
            AffiliateReferral(id=8, affiliate_link_id=10, affiliate_user_id=2, referred_user_id=3,
                              program_id=2, status="converted", click_date=instant),
            AffiliateReferral(id=9, affiliate_link_id=10, affiliate_user_id=2, referred_user_id=3,
                              program_id=999, status="converted", click_date=instant),
            AffiliateReferral(id=10, affiliate_link_id=10, affiliate_user_id=2, referred_user_id=3,
                              program_id=None, status="converted", click_date=instant),
            AffiliateReferral(id=11, affiliate_link_id=10, affiliate_user_id=2, referred_user_id=None,
                              program_id=1, status="converted", click_date=instant),
            # A current-looking parent pair is still rejected when its legacy
            # status is not one of the shared referral labels.
            AffiliateReferral(id=12, affiliate_link_id=10, affiliate_user_id=2, referred_user_id=3,
                              program_id=1, status="unknown", click_date=instant),
        ])
        db.session.flush()
        db.session.add_all([
            AffiliatePayout(id=1, affiliate_user_id=2, amount=Decimal("1.00"), method="ignored",
                            payment_details={"email": "must-not-leak@example.invalid"}, status="pending"),
            AffiliatePayout(id=2, affiliate_user_id=6, amount=Decimal("1.00"), method="ignored",
                            payment_details={"email": "foreign-must-not-leak@example.invalid"}, status="pending"),
        ])
        db.session.add_all([
            AffiliateCommission(id=1, affiliate_user_id=2, referral_id=1, amount=Decimal("0.00"),
                                type="one_time", status="approved", created_at=instant,
                                approved_at=instant, description="must-not-leak"),
            AffiliateCommission(id=2, affiliate_user_id=2, referral_id=2, amount=Decimal("1.25"),
                                type="recurring", status="paid", created_at=instant, payout_id=1,
                                paid_at=instant + timedelta(minutes=2)),
            AffiliateCommission(id=3, affiliate_user_id=2, referral_id=1, amount=Decimal("2.00"),
                                type="one_time", status="pending", payout_id=2, created_at=instant),
            AffiliateCommission(id=4, affiliate_user_id=2, referral_id=1, amount=Decimal("3.00"),
                                type="one_time", status="approved", payout_id=999, created_at=instant),
            AffiliateCommission(id=5, affiliate_user_id=2, referral_id=None, amount=Decimal("4.00"),
                                type="one_time", status="approved", created_at=instant),
            AffiliateCommission(id=6, affiliate_user_id=3, referral_id=1, amount=Decimal("5.00"),
                                type="one_time", status="approved", created_at=instant),
            AffiliateCommission(id=7, affiliate_user_id=2, referral_id=3, amount=Decimal("6.00"),
                                type="one_time", status="approved", created_at=instant),
            AffiliateCommission(id=8, affiliate_user_id=2, referral_id=4, amount=Decimal("6.00"),
                                type="one_time", status="approved", created_at=instant),
            AffiliateCommission(id=9, affiliate_user_id=2, referral_id=5, amount=Decimal("6.00"),
                                type="one_time", status="approved", created_at=instant),
            AffiliateCommission(id=10, affiliate_user_id=2, referral_id=6, amount=Decimal("6.00"),
                                type="one_time", status="approved", created_at=instant),
            AffiliateCommission(id=11, affiliate_user_id=2, referral_id=7, amount=Decimal("6.00"),
                                type="one_time", status="approved", created_at=instant),
            AffiliateCommission(id=12, affiliate_user_id=2, referral_id=8, amount=Decimal("6.00"),
                                type="one_time", status="approved", created_at=instant),
            AffiliateCommission(id=13, affiliate_user_id=2, referral_id=9, amount=Decimal("6.00"),
                                type="one_time", status="approved", created_at=instant),
            # Nullable historical referral parents are intentionally retained.
            AffiliateCommission(id=14, affiliate_user_id=2, referral_id=10, amount=Decimal("6.00"),
                                type="one_time", status="approved", created_at=instant),
            AffiliateCommission(id=15, affiliate_user_id=2, referral_id=11, amount=Decimal("6.00"),
                                type="one_time", status="approved", created_at=instant),
            # Only this owner's payout parent may affect each dashboard status sum.
            AffiliateCommission(id=16, affiliate_user_id=2, referral_id=1, amount=Decimal("4.00"),
                                type="one_time", status="pending", payout_id=1, created_at=instant),
            AffiliateCommission(id=17, affiliate_user_id=2, referral_id=1, amount=Decimal("5.00"),
                                type="one_time", status="approved", payout_id=1, created_at=instant),
            AffiliateCommission(id=18, affiliate_user_id=2, referral_id=1, amount=Decimal("7.00"),
                                type="one_time", status="paid", payout_id=2, created_at=instant),
            AffiliateCommission(id=19, affiliate_user_id=2, referral_id=1, amount=Decimal("8.00"),
                                type="one_time", status="pending", payout_id=999, created_at=instant),
            AffiliateCommission(id=20, affiliate_user_id=2, referral_id=1, amount=Decimal("9.00"),
                                type="one_time", status="approved", payout_id=2, created_at=instant),
            AffiliateCommission(id=21, affiliate_user_id=2, referral_id=1, amount=Decimal("10.00"),
                                type="one_time", status="paid", payout_id=999, created_at=instant),
            AffiliateCommission(id=22, affiliate_user_id=2, referral_id=12, amount=Decimal("100.00"),
                                type="one_time", status="approved", created_at=instant),
            AffiliateCommission(id=23, affiliate_user_id=2, referral_id=1, amount=Decimal("200.00"),
                                type="one_time", status="unknown", created_at=instant),
            AffiliateCommission(id=24, affiliate_user_id=2, referral_id=1, amount=Decimal("300.00"),
                                type="legacy_unknown", status="approved", created_at=instant),
        ])
        db.session.commit()
        app.tokens = {
            user_id: db.session.get(User, user_id).generate_access_token()
            for user_id in (2, 5)
        }
        db.session.remove()

    yield app

    with app.app_context():
        db.session.remove()
        db.metadata.drop_all(bind=db.engine, tables=list(reversed(tables)))
        if sentinel_created:
            db.metadata.remove(programs)


def _headers(app, user_id=2):
    return {"Authorization": "Bearer " + app.tokens[user_id]}


def _resource_sql(statements):
    resources = (
        "affiliate_links", "affiliate_referrals", "affiliate_commissions",
        "affiliate_payouts", "trading_programs",
    )
    return [statement for statement in statements if any(table in statement.lower() for table in resources)]


def test_ui4_affiliate_records_http_payloads_are_exact_private_and_stable(
    ui4_affiliate_records_app, record_property,
):
    """HTTP responses have only contract fields, finite decimals, and stable pages."""
    app = ui4_affiliate_records_app
    client = app.test_client()

    referrals = client.get(
        "/api/v1/affiliate/referrals?per_page=1&page=1&status=pending", headers=_headers(app),
    )
    commissions = client.get(
        "/api/v1/affiliate/commissions?per_page=1&page=1&status=paid", headers=_headers(app),
    )
    assert referrals.status_code == commissions.status_code == 200
    referral_payload = referrals.get_json()
    commission_payload = commissions.get_json()

    envelope = {
        "owner_context", "verification", "payouts_enabled", "available_for_payout", "currency",
        "pagination", "filters",
    }
    assert set(referral_payload) == envelope | {"referrals"}
    assert set(commission_payload) == envelope | {"commissions"}
    for payload in (referral_payload, commission_payload):
        assert payload["owner_context"] == {"user_id": 2, "tenant_id": 1}
        assert payload["verification"] == "unverified_legacy"
        assert payload["payouts_enabled"] is False
        assert payload["available_for_payout"] is None
        assert payload["currency"] is None
        assert payload["pagination"] == {"page": 1, "per_page": 1, "total": 1, "pages": 1}
    assert referral_payload["filters"] == {"status": "pending"}
    assert commission_payload["filters"] == {"status": "paid"}

    # Equal timestamps use descending immutable ids, so repeating and advancing
    # a page cannot reorder rows or duplicate an id.
    assert [row["id"] for row in referral_payload["referrals"]] == [2]
    assert [row["id"] for row in commission_payload["commissions"]] == [2]
    referral_second = client.get(
        "/api/v1/affiliate/referrals?per_page=1&page=2&status=pending", headers=_headers(app),
    )
    commission_second = client.get(
        "/api/v1/affiliate/commissions?per_page=1&page=2&status=paid", headers=_headers(app),
    )
    assert referral_second.get_json()["referrals"] == []
    assert commission_second.get_json()["commissions"] == []
    assert client.get(
        "/api/v1/affiliate/referrals?per_page=1&page=1&status=pending", headers=_headers(app),
    ).get_json() == referral_payload
    assert client.get(
        "/api/v1/affiliate/commissions?per_page=1&page=1&status=paid", headers=_headers(app),
    ).get_json() == commission_payload

    referral_row = referral_payload["referrals"][0]
    commission_row = commission_payload["commissions"][0]
    assert set(referral_row) == {
        "id", "status", "click_date", "conversion_date", "purchase_amount", "commission_amount", "currency",
    }
    assert referral_row["purchase_amount"] is referral_row["commission_amount"] is None
    assert set(referral_payload["referrals"][0]) == set(referral_row)
    assert set(commission_row) == {
        "id", "amount", "type", "status", "created_at", "approved_at", "paid_at", "currency",
    }
    assert commission_row["amount"] == "1.25"
    assert commission_row["currency"] is None

    raw = json.dumps({"referrals": referral_payload, "commissions": commission_payload}, sort_keys=True)
    for forbidden in (
        "referred_user", "email", "name", "ip_address", "user_agent", "landing_page",
        "payment_details", "notes", "description", "payout_id", "affiliate_link_id", "program_id",
        "must-not-leak",
    ):
        assert forbidden not in raw
    record_property("ui4_affiliate_referrals_payload", json.dumps(referral_payload, sort_keys=True))
    record_property("ui4_affiliate_commissions_payload", json.dumps(commission_payload, sort_keys=True))


def test_ui4_affiliate_records_filters_coherent_parents_and_payouts(ui4_affiliate_records_app):
    """Self, missing, foreign, dangling, and foreign-payout legacy parents are closed."""
    app = ui4_affiliate_records_app
    client = app.test_client()

    referral_response = client.get("/api/v1/affiliate/referrals?status=converted", headers=_headers(app))
    commission_response = client.get("/api/v1/affiliate/commissions?status=approved", headers=_headers(app))
    dashboard_response = client.get("/api/v1/affiliate/dashboard", headers=_headers(app))
    all_referrals_response = client.get("/api/v1/affiliate/referrals", headers=_headers(app))
    assert referral_response.status_code == commission_response.status_code == dashboard_response.status_code == 200
    referral_payload = referral_response.get_json()
    commission_payload = commission_response.get_json()
    assert referral_payload["filters"] == {"status": "converted"}
    assert referral_payload["pagination"] == {"page": 1, "per_page": 20, "total": 3, "pages": 1}
    assert [row["id"] for row in referral_payload["referrals"]] == [11, 10, 1]
    assert commission_payload["filters"] == {"status": "approved"}
    assert commission_payload["pagination"] == {"page": 1, "per_page": 20, "total": 4, "pages": 1}
    assert [row["id"] for row in commission_payload["commissions"]] == [17, 15, 14, 1]

    # The nullable rows are incomplete historical source records, but the exact
    # same row IDs appear in dashboard and bounded list projections.
    all_referrals_payload = all_referrals_response.get_json()
    dashboard_payload = dashboard_response.get_json()
    assert [row["id"] for row in all_referrals_payload["referrals"]] == [11, 10, 2, 1]
    assert [row["id"] for row in dashboard_payload["recent_referrals"]] == [11, 10, 2, 1]
    assert {
        key: dashboard_payload["stats"][key]
        for key in ("total_commission", "pending_commission", "approved_commission", "paid_commission")
    } == {
        "total_commission": "22.25",
        "pending_commission": "4.00",
        "approved_commission": "17.00",
        "paid_commission": "1.25",
    }

    paid_response = client.get("/api/v1/affiliate/commissions?status=paid", headers=_headers(app))
    assert paid_response.status_code == 200
    assert [row["id"] for row in paid_response.get_json()["commissions"]] == [2]
    # id=2 is the only paid commission with a non-null payout that remains;
    # owner payout id=1 is accepted while foreign/dangling parents are closed.
    assert paid_response.get_json()["pagination"]["total"] == 1
    pending_response = client.get("/api/v1/affiliate/commissions?status=pending", headers=_headers(app))
    assert [row["id"] for row in pending_response.get_json()["commissions"]] == [16]
    assert pending_response.get_json()["pagination"]["total"] == 1


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/affiliate/referrals?status=converted&status=pending",
        "/api/v1/affiliate/referrals?status[]=converted",
        "/api/v1/affiliate/referrals?status[]=",
        "/api/v1/affiliate/referrals?status=unknown",
        "/api/v1/affiliate/referrals?page=01",
        "/api/v1/affiliate/referrals?per_page=51",
        "/api/v1/affiliate/commissions?status=approved&status=paid",
        "/api/v1/affiliate/commissions?status[]=approved",
        "/api/v1/affiliate/commissions?status[]=",
        "/api/v1/affiliate/commissions?status=converted",
        "/api/v1/affiliate/commissions?page=10001",
        "/api/v1/affiliate/commissions?per_page=0",
    ],
)
def test_ui4_affiliate_records_invalid_query_precedes_resource_sql(ui4_affiliate_records_app, path):
    """Unknown/duplicate/malformed query strings stop before affiliate data SQL."""
    app = ui4_affiliate_records_app
    with app.app_context():
        statements = []

        def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)

        event.listen(db.engine, "before_cursor_execute", observe)
        try:
            response = app.test_client().get(path, headers=_headers(app))
        finally:
            event.remove(db.engine, "before_cursor_execute", observe)
    assert response.status_code == 400
    assert response.get_json()["code"] == "AFFILIATE_RECORDS_QUERY_INVALID"
    assert _resource_sql(statements) == []


def test_ui4_affiliate_records_tenant_gate_no_writes_and_jwt_csrf_boundary(ui4_affiliate_records_app):
    """Tenant-less reads are closed before resources; GET does not alter JWT/CSRF policy."""
    app = ui4_affiliate_records_app
    with app.app_context():
        pending = AffiliateLink(user_id=2, code="UNFLUSHED", name="pending")
        db.session.add(pending)
        statements = []

        def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)

        event.listen(db.engine, "before_cursor_execute", observe)
        try:
            denied_referrals = app.test_client().get("/api/v1/affiliate/referrals", headers=_headers(app, 5))
            denied_referral_sql = list(statements)
            statements.clear()
            denied_commissions = app.test_client().get("/api/v1/affiliate/commissions", headers=_headers(app, 5))
            denied_commission_sql = list(statements)
            statements.clear()
            allowed = app.test_client().get("/api/v1/affiliate/referrals", headers=_headers(app, 2))
            allowed_sql = list(statements)
        finally:
            event.remove(db.engine, "before_cursor_execute", observe)
            db.session.rollback()

    assert denied_referrals.status_code == denied_commissions.status_code == 403
    assert denied_referrals.get_json()["code"] == denied_commissions.get_json()["code"] == "TENANT_CONTEXT_REQUIRED"
    assert allowed.status_code == 200
    assert pending.id is None
    assert _resource_sql(denied_referral_sql) == _resource_sql(denied_commission_sql) == []
    assert _resource_sql(allowed_sql)
    assert all(
        not statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
        for statement in denied_referral_sql + denied_commission_sql + allowed_sql
    )

    assert app.test_client().get("/api/v1/affiliate/referrals").status_code == 401
    cookie_client = app.test_client()
    cookie_client.set_cookie("access_token", app.tokens[2])
    assert cookie_client.get("/api/v1/affiliate/commissions").status_code == 200
    csrf = cookie_client.post("/api/v1/affiliate/payout", json={})
    assert csrf.status_code == 403 and csrf.get_json()["code"] == "CSRF_INVALID"
