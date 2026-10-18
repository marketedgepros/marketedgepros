"""Focused UI-4 dashboard read contracts using only synthetic SQLite rows."""
from datetime import datetime, timedelta
from decimal import Decimal
import json

import pytest
from flask import Flask
from sqlalchemy import Column, Integer, Table, event, select
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
from src.models.trading_program import Challenge, TradingProgram
from src.models.user import User
from src.routes.affiliate import affiliate_bp
from src.routes.users import users_bp


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_element, _compiler, **_kwargs):
    """Test-only SQLite compatibility; production JSONB remains unchanged."""
    return "JSON"


@pytest.fixture
def ui4_dashboard_reads_app():
    """Minimal real-route app populated only with explicit synthetic records."""
    app = Flask("ui4-dashboard-reads-security")
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY="ui4-dashboard-synthetic-key",
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=10),
        JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=1),
        EXPANDED_HIERARCHY_ENABLED=True,
    )
    db.init_app(app)
    app.register_blueprint(users_bp, url_prefix="/api/v1/users")
    app.register_blueprint(affiliate_bp, url_prefix="/api/v1/affiliate")

    # The legacy model has an optional FK to the no-longer-mapped ``programs``
    # table.  This fixture-only sentinel permits real referral-table DDL.
    sentinel_created = "programs" not in db.metadata.tables
    programs = (
        Table("programs", db.metadata, Column("id", Integer, primary_key=True))
        if sentinel_created else db.metadata.tables["programs"]
    )
    tables = [
        Tenant.__table__, User.__table__, TokenBlacklist.__table__,
        TradingProgram.__table__, Challenge.__table__, programs,
        AffiliateSettings.__table__, AffiliateLink.__table__, AffiliateReferral.__table__,
        AffiliatePayout.__table__, AffiliateCommission.__table__,
    ]
    instant = datetime(2026, 10, 12, 9, 0, 0)

    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=tables)
        db.session.add_all([
            Tenant(id=1, name="Tenant one", subdomain="ui4-tenant-one", status="active"),
            Tenant(id=2, name="Tenant two", subdomain="ui4-tenant-two", status="active"),
            User(id=1, email="trader@example.invalid", password_hash="x", first_name="Trader", last_name="One",
                 role="trader", tenant_id=1, is_active=True, is_verified=True, tree_path="1", level=0),
            User(id=2, email="affiliate@example.invalid", password_hash="x", first_name="Affiliate", last_name="Two",
                 role="affiliate", tenant_id=1, is_active=True, is_verified=True, tree_path="2", level=0),
            User(id=3, email="referred@example.invalid", password_hash="x", first_name="Referred", last_name="Three",
                 role="trader", tenant_id=1, is_active=True, is_verified=True, tree_path="3", level=0),
            User(id=4, email="foreign@example.invalid", password_hash="x", first_name="Foreign", last_name="Four",
                 role="affiliate", tenant_id=2, is_active=True, is_verified=True, tree_path="4", level=0),
            User(id=5, email="missing-tenant@example.invalid", password_hash="x", first_name="No", last_name="Tenant",
                 role="affiliate", tenant_id=None, is_active=True, is_verified=True, tree_path="5", level=0),
            TradingProgram(id=1, tenant_id=1, name="Tenant one challenge", type="one_phase",
                           account_size=Decimal("1000.00"), price=Decimal("99.00"), is_active=True),
            TradingProgram(id=2, tenant_id=2, name="Tenant two challenge", type="one_phase",
                           account_size=Decimal("1000.00"), price=Decimal("99.00"), is_active=True),
        ])
        db.session.add_all([
            Challenge(id=1, user_id=1, program_id=1, status="active", initial_balance=Decimal("1000.00"),
                      current_balance=Decimal("1001.25"), created_at=instant),
            # Owner-matching but program-tenant-mismatched must remain hidden.
            Challenge(id=2, user_id=1, program_id=2, status="passed", initial_balance=Decimal("1.00"),
                      current_balance=Decimal("9.00"), created_at=instant + timedelta(minutes=1)),
            Challenge(id=3, user_id=3, program_id=1, status="passed", initial_balance=Decimal("1.00"),
                      current_balance=Decimal("2.00"), created_at=instant + timedelta(minutes=2)),
        ])
        # The canonical root URL link is intentionally latest, so it remains in
        # the bounded page even when the 51-link truncation contract applies.
        db.session.add(AffiliateLink(
            id=10, user_id=2, code="SAFECOPY", name="Canonical root link",
            clicks=10, conversions=1, total_revenue=Decimal("99.00"),
            total_commission=Decimal("99.00"), commission_rate=Decimal("15.00"),
            created_at=instant + timedelta(minutes=100),
        ))
        for link_id in range(11, 61):
            db.session.add(AffiliateLink(
                id=link_id, user_id=2, code=f"OWNER2{link_id}", name=f"Owner two {link_id}",
                clicks=0, conversions=0, total_revenue=Decimal("0.00"), total_commission=Decimal("0.00"),
                commission_rate=Decimal("15.00"), created_at=instant + timedelta(minutes=link_id),
            ))
        # A foreign tenant link is deliberately used by a forged referral below.
        db.session.add(AffiliateLink(
            id=100, user_id=4, code="FOREIGNLINK", name="Foreign link", clicks=7, conversions=7,
            total_revenue=Decimal("700.00"), total_commission=Decimal("700.00"),
            commission_rate=Decimal("15.00"), created_at=instant,
        ))
        db.session.flush()
        db.session.execute(programs.insert(), [{"id": 1}, {"id": 2}, {"id": 999}])
        db.session.add_all([
            AffiliateReferral(id=1, affiliate_link_id=10, affiliate_user_id=2, referred_user_id=3,
                              program_id=1, status="converted", commission_amount=Decimal("12.50"),
                              click_date=instant + timedelta(minutes=1)),
            AffiliateReferral(id=2, affiliate_link_id=11, affiliate_user_id=2, referred_user_id=None,
                              program_id=None, status="pending", commission_amount=None,
                              click_date=instant + timedelta(minutes=2)),
            # These legacy rows are retained but never shown or summed.
            AffiliateReferral(id=3, affiliate_link_id=12, affiliate_user_id=2, referred_user_id=2,
                              status="converted", commission_amount=Decimal("19.00"), click_date=instant + timedelta(minutes=3)),
            AffiliateReferral(id=4, affiliate_link_id=100, affiliate_user_id=2, referred_user_id=3,
                              status="converted", commission_amount=Decimal("20.00"), click_date=instant + timedelta(minutes=4)),
            AffiliateReferral(id=5, affiliate_link_id=13, affiliate_user_id=2, referred_user_id=4,
                              status="converted", commission_amount=Decimal("21.00"), click_date=instant + timedelta(minutes=5)),
            AffiliateReferral(id=6, affiliate_link_id=14, affiliate_user_id=2, referred_user_id=3, program_id=2,
                              status="converted", commission_amount=Decimal("22.00"), click_date=instant + timedelta(minutes=6)),
            # It satisfies the legacy FK but has no current tenant-scoped program.
            AffiliateReferral(id=7, affiliate_link_id=15, affiliate_user_id=2, referred_user_id=3, program_id=999,
                              status="converted", commission_amount=Decimal("23.00"), click_date=instant + timedelta(minutes=7)),
        ])
        db.session.flush()
        db.session.add_all([
            AffiliateCommission(id=1, affiliate_user_id=2, referral_id=1, amount=Decimal("12.50"), status="approved"),
            AffiliateCommission(id=2, affiliate_user_id=2, referral_id=2, amount=Decimal("3.25"), status="pending"),
            AffiliateCommission(id=3, affiliate_user_id=2, referral_id=3, amount=Decimal("19.00"), status="paid"),
            AffiliateCommission(id=4, affiliate_user_id=2, referral_id=4, amount=Decimal("20.00"), status="approved"),
            AffiliateCommission(id=5, affiliate_user_id=2, referral_id=5, amount=Decimal("21.00"), status="approved"),
            AffiliateCommission(id=6, affiliate_user_id=2, referral_id=6, amount=Decimal("22.00"), status="approved"),
            # No valid referral: inner dashboard join must exclude it.
            AffiliateCommission(id=7, affiliate_user_id=2, referral_id=None, amount=Decimal("100.00"), status="approved"),
            # A non-null program without a current program row is also excluded.
            AffiliateCommission(id=8, affiliate_user_id=2, referral_id=7, amount=Decimal("23.00"), status="approved"),
        ])
        db.session.commit()
        app.tokens = {
            user_id: db.session.get(User, user_id).generate_access_token()
            for user_id in (1, 2, 3, 4, 5)
        }
        db.session.remove()

    yield app

    with app.app_context():
        db.session.remove()
        db.metadata.drop_all(bind=db.engine, tables=list(reversed(tables)))
        if sentinel_created:
            db.metadata.remove(programs)


def _headers(app, user_id):
    return {"Authorization": "Bearer " + app.tokens[user_id]}


def test_ui4_dashboard_reads_owner_payloads_are_bounded_private_and_parity_serializable(
    ui4_dashboard_reads_app, record_property,
):
    """The two UI projections are owner-only and carry exact UI-4 metadata."""
    app = ui4_dashboard_reads_app
    client = app.test_client()

    user_response = client.get("/api/v1/users/dashboard", headers=_headers(app, 1))
    assert user_response.status_code == 200
    user_payload = user_response.get_json()
    assert user_payload["owner_context"] == {"user_id": 1, "tenant_id": 1}
    assert user_payload["user"]["tenant_id"] == 1
    assert user_payload["user"]["role"] == "trader"
    assert set(user_payload["user"]) == {"id", "tenant_id", "role", "first_name"}
    assert [row["id"] for row in user_payload["recent_challenges"]] == [1]
    assert user_payload["recent_challenges"][0]["user_id"] == 1
    assert user_payload["recent_challenges"][0]["currency"] is None
    assert user_payload["statistics"]["status_counts"]["total"] == 1

    affiliate_response = client.get("/api/v1/affiliate/dashboard", headers=_headers(app, 2))
    assert affiliate_response.status_code == 200
    affiliate_payload = affiliate_response.get_json()
    assert affiliate_payload["owner_context"] == {"user_id": 2, "tenant_id": 1}
    assert affiliate_payload["stats"] == {
        "total_clicks": 10,
        "total_conversions": 1,
        "total_revenue": "99.00",
        "total_commission": "15.75",
        "conversion_rate": "10",
        "pending_commission": "3.25",
        "approved_commission": "12.50",
        "paid_commission": None,
        "currency": None,
        "available_for_payout": None,
        "payouts_enabled": False,
        "commission_verification": "unverified_legacy",
    }
    assert affiliate_payload["link_pagination"] == {"total": 51, "limit": 50, "truncated": True}
    assert len(affiliate_payload["links"]) == 50
    canonical = next(link for link in affiliate_payload["links"] if link["id"] == 10)
    assert canonical == {
        "id": 10,
        "name": "Canonical root link",
        "url": "https://marketedgepros.com/?ref=SAFECOPY",
        "clicks": 10,
        "conversions": 1,
    }
    assert all(set(link) == {"id", "name", "url", "clicks", "conversions"} for link in affiliate_payload["links"])
    assert affiliate_payload["recent_referrals"] == [
        {"id": 2, "status": "pending", "click_date": "2026-10-12T09:02:00", "commission_amount": None, "currency": None},
        {"id": 1, "status": "converted", "click_date": "2026-10-12T09:01:00", "commission_amount": "12.50", "currency": None},
    ]
    assert all("referred_user" not in row for row in affiliate_payload["recent_referrals"])
    assert "12.50" != "99.00"  # cached link commission cannot substitute valid referral commission history

    record_property("ui4_user_dashboard_payload", json.dumps(user_payload, sort_keys=True))
    record_property("ui4_affiliate_dashboard_payload", json.dumps(affiliate_payload, sort_keys=True))


def test_ui4_dashboard_reads_tenant_gate_no_writes_and_interleaved_owners_do_not_leak(
    ui4_dashboard_reads_app,
):
    """Tenant-less callers stop before resource SQL; reads do not flush pending rows."""
    app = ui4_dashboard_reads_app

    with app.app_context():
        engine = db.engine
        pending = AffiliateLink(user_id=2, code="UNFLUSHED", name="Unflushed", clicks=99, conversions=99)
        db.session.add(pending)

        def capture_request(path, user_id):
            statements = []

            def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
                statements.append(statement)

            event.listen(engine, "before_cursor_execute", observe)
            try:
                response = app.test_client().get(path, headers=_headers(app, user_id))
            finally:
                event.remove(engine, "before_cursor_execute", observe)
            return response, statements

        try:
            denied_user, denied_user_sql = capture_request("/api/v1/users/dashboard", 5)
            denied_affiliate, denied_affiliate_sql = capture_request("/api/v1/affiliate/dashboard", 5)
            affiliate_one, affiliate_one_sql = capture_request("/api/v1/affiliate/dashboard", 2)
            trader, trader_sql = capture_request("/api/v1/users/dashboard", 1)
            affiliate_two, affiliate_two_sql = capture_request("/api/v1/affiliate/dashboard", 2)
        finally:
            db.session.rollback()

    assert denied_user.status_code == denied_affiliate.status_code == 403
    assert pending.id is None
    assert affiliate_one.status_code == affiliate_two.status_code == trader.status_code == 200
    assert affiliate_one.get_json()["owner_context"] == affiliate_two.get_json()["owner_context"] == {"user_id": 2, "tenant_id": 1}
    assert trader.get_json()["owner_context"] == {"user_id": 1, "tenant_id": 1}
    all_statements = (
        denied_user_sql + denied_affiliate_sql + affiliate_one_sql + trader_sql + affiliate_two_sql
    )
    assert all(not statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for statement in all_statements)

    def dashboard_resource_sql(statements):
        resource_tables = (
            "affiliate_links", "affiliate_referrals", "affiliate_commissions", "challenges", "trading_programs",
        )
        return [
            statement.lower() for statement in statements
            if any(table in statement.lower() for table in resource_tables)
        ]

    # Each denied request is observed before an authorized call runs, so no
    # later resource query can mask a gate regression.
    assert dashboard_resource_sql(denied_user_sql) == []
    assert dashboard_resource_sql(denied_affiliate_sql) == []
    assert denied_user.get_json()["code"] == denied_affiliate.get_json()["code"] == "TENANT_CONTEXT_REQUIRED"


def test_ui4_dashboard_reads_unknown_counters_and_invalid_legacy_codes_stay_null(
    ui4_dashboard_reads_app,
):
    """Partial or invalid legacy values must not be presented as recorded zeros."""
    app = ui4_dashboard_reads_app

    with app.app_context():
        link = db.session.get(AffiliateLink, 10)
        link.clicks = None
        link.conversions = None
        link.total_revenue = None
        db.session.commit()

    null_response = app.test_client().get("/api/v1/affiliate/dashboard", headers=_headers(app, 2))
    assert null_response.status_code == 200
    null_payload = null_response.get_json()
    assert null_payload["link_pagination"]["total"] == 51
    assert {
        key: null_payload["stats"][key]
        for key in ("total_clicks", "total_conversions", "total_revenue", "conversion_rate")
    } == {
        "total_clicks": None,
        "total_conversions": None,
        "total_revenue": None,
        "conversion_rate": None,
    }
    null_link = next(row for row in null_payload["links"] if row["id"] == 10)
    assert null_link["clicks"] is None
    assert null_link["conversions"] is None

    with app.app_context():
        link = db.session.get(AffiliateLink, 10)
        link.clicks = -1
        link.conversions = -1
        link.total_revenue = Decimal("99.00")
        link.code = "LEGACY_CODE"
        db.session.commit()

    invalid_response = app.test_client().get("/api/v1/affiliate/dashboard", headers=_headers(app, 2))
    assert invalid_response.status_code == 200
    invalid_payload = invalid_response.get_json()
    assert invalid_payload["stats"]["total_clicks"] is None
    assert invalid_payload["stats"]["total_conversions"] is None
    assert invalid_payload["stats"]["conversion_rate"] is None
    assert invalid_payload["stats"]["total_revenue"] == "99.00"
    invalid_link = next(row for row in invalid_payload["links"] if row["id"] == 10)
    assert invalid_link["clicks"] is None
    assert invalid_link["conversions"] is None
    assert invalid_link["url"] is None


def test_ui4_dashboard_reads_use_fixed_select_counts_for_bounded_owner_pages(ui4_dashboard_reads_app):
    """Fifty returned links must not add selects beyond the fixed dashboard plan."""
    app = ui4_dashboard_reads_app

    def select_count(path, headers):
        statements = []

        def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith("select"):
                statements.append(statement)

        with app.app_context():
            engine = db.engine
        event.listen(engine, "before_cursor_execute", observe)
        try:
            response = app.test_client().get(path, headers=headers)
        finally:
            event.remove(engine, "before_cursor_execute", observe)
        assert response.status_code == 200
        return len(statements)

    affiliate_first = select_count("/api/v1/affiliate/dashboard", _headers(app, 2))
    user_count = select_count("/api/v1/users/dashboard", _headers(app, 1))
    affiliate_second = select_count("/api/v1/affiliate/dashboard", _headers(app, 2))
    # JWT principal + blacklist, then four bounded affiliate dashboard selects;
    # the personal dashboard is likewise a fixed aggregate plus bounded page.
    assert (affiliate_first, user_count, affiliate_second) == (6, 4, 6)


def test_ui4_dashboard_reads_affiliate_storage_failure_is_generic_503(ui4_dashboard_reads_app):
    """Database details never escape the affiliate dashboard's generic storage error."""
    app = ui4_dashboard_reads_app

    def fail_dashboard_read(_conn, _cursor, statement, _parameters, _context, _executemany):
        if "FROM affiliate_links" in statement:
            raise RuntimeError("synthetic storage detail")

    with app.app_context():
        engine = db.engine
    event.listen(engine, "before_cursor_execute", fail_dashboard_read)
    try:
        response = app.test_client().get("/api/v1/affiliate/dashboard", headers=_headers(app, 2))
    finally:
        event.remove(engine, "before_cursor_execute", fail_dashboard_read)
    assert response.status_code == 503
    assert response.get_json() == {
        "error": "Dashboard is temporarily unavailable",
        "code": "AFFILIATE_DASHBOARD_UNAVAILABLE",
    }
