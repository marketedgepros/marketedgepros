"""UI-4 dashboard read verification against the runner-created PostgreSQL cluster."""
from datetime import datetime, timedelta
from decimal import Decimal
import json

import pytest
from flask import Flask
from sqlalchemy import Column, Integer, Table, event, select, text


@pytest.fixture
def ui4_dashboard_reads_pg_app(staging_resources):
    """A real route host with only runner-issued Unix-socket PostgreSQL resources."""
    from src.database import db
    from src.models.affiliate import (
        AffiliateCommission, AffiliateLink, AffiliatePayout, AffiliateReferral, AffiliateSettings,
    )
    from src.models.tenant import Tenant
    from src.models.token_blacklist import TokenBlacklist
    from src.models.trading_program import Challenge, TradingProgram
    from src.models.user import User
    from src.routes.affiliate import affiliate_bp
    from src.routes.users import users_bp
    from src.utils.hierarchy_scoping import init_hierarchy_scoping

    app = Flask("ui4-dashboard-reads-postgresql")
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI=staging_resources["pg_url"],
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY="ui4-dashboard-staging-synthetic-key",
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=10),
        JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=1),
        EXPANDED_HIERARCHY_ENABLED=True,
    )
    db.init_app(app)
    init_hierarchy_scoping(db, User)
    app.register_blueprint(users_bp, url_prefix="/api/v1/users")
    app.register_blueprint(affiliate_bp, url_prefix="/api/v1/affiliate")

    sentinel_created = "programs" not in db.metadata.tables
    programs = (Table("programs", db.metadata, Column("id", Integer, primary_key=True))
                if sentinel_created else db.metadata.tables["programs"])
    tables = [
        Tenant.__table__, User.__table__, TokenBlacklist.__table__, TradingProgram.__table__, Challenge.__table__,
        programs, AffiliateSettings.__table__, AffiliateLink.__table__, AffiliateReferral.__table__,
        AffiliatePayout.__table__, AffiliateCommission.__table__,
    ]
    # Tenant/user/program/challenge are shared with the autouse staging app;
    # only these tables belong to this fixture and must go first at teardown.
    fixture_tables = [
        programs, AffiliateSettings.__table__, AffiliateLink.__table__, AffiliateReferral.__table__,
        AffiliatePayout.__table__, AffiliateCommission.__table__,
    ]
    instant = datetime(2026, 10, 12, 10, 0, 0)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=tables)
        # Temporary staging-only corruption proves that a non-null payout must
        # resolve to the current affiliate owner before any dashboard aggregate.
        db.session.execute(text(
            "ALTER TABLE affiliate_commissions "
            "DROP CONSTRAINT affiliate_commissions_payout_id_fkey"
        ))
        # ``AffiliateReferral.program_id`` targets this fixture-only historic
        # table, not ``trading_programs``.  Its rows make the explicit foreign
        # key valid while the dashboard separately checks current program tenant.
        db.session.execute(programs.insert(), [{"id": 1}, {"id": 2}])
        db.session.add_all([
            Tenant(id=1, name="UI4 PG tenant", subdomain="ui4-pg", status="active"),
            Tenant(id=2, name="UI4 PG foreign", subdomain="ui4-pg-foreign", status="active"),
            User(id=1, email="pg-trader@example.invalid", password_hash="x", first_name="Trader", last_name="One",
                 tenant_id=1, role="trader", is_active=True, is_verified=True, tree_path="1", level=0),
            User(id=2, email="pg-affiliate@example.invalid", password_hash="x", first_name="Affiliate", last_name="Two",
                 tenant_id=1, role="affiliate", is_active=True, is_verified=True, tree_path="2", level=0),
            User(id=3, email="pg-referred@example.invalid", password_hash="x", first_name="Referred", last_name="Three",
                 tenant_id=1, role="trader", is_active=True, is_verified=True, tree_path="3", level=0),
            User(id=4, email="pg-foreign@example.invalid", password_hash="x", first_name="Foreign", last_name="Four",
                 tenant_id=2, role="trader", is_active=True, is_verified=True, tree_path="4", level=0),
            TradingProgram(id=1, tenant_id=1, name="UI4 tenant program", type="one_phase",
                           account_size=Decimal("1000.00"), price=Decimal("99.00"), is_active=True),
            TradingProgram(id=2, tenant_id=2, name="UI4 foreign program", type="one_phase",
                           account_size=Decimal("1000.00"), price=Decimal("99.00"), is_active=True),
        ])
        db.session.add_all([
            Challenge(id=1, user_id=1, program_id=1, status="active", initial_balance=Decimal("1000.00"),
                      current_balance=Decimal("1002.00"), created_at=instant),
            Challenge(id=2, user_id=1, program_id=2, status="passed", initial_balance=Decimal("1.00"),
                      current_balance=Decimal("9.00"), created_at=instant + timedelta(minutes=1)),
            AffiliateLink(id=1, user_id=2, code="SAFEPGCOPY", name="Staging canonical root", clicks=4, conversions=1,
                          total_revenue=Decimal("40.00"), total_commission=Decimal("99.00"),
                          commission_rate=Decimal("15.00"), created_at=instant),
            AffiliateLink(id=2, user_id=1, code="WRONGOWNER", name="Wrong owner", clicks=8, conversions=8,
                          total_revenue=Decimal("80.00"), total_commission=Decimal("80.00"),
                          commission_rate=Decimal("15.00"), created_at=instant),
        ])
        db.session.flush()
        db.session.execute(programs.insert().values(id=999))
        db.session.add_all([
            AffiliateReferral(id=1, affiliate_link_id=1, affiliate_user_id=2, referred_user_id=3, program_id=1,
                              status="converted", commission_amount=Decimal("6.00"), click_date=instant),
            AffiliateReferral(id=2, affiliate_link_id=1, affiliate_user_id=2, referred_user_id=2, status="converted",
                              commission_amount=Decimal("50.00"), click_date=instant + timedelta(minutes=1)),
            AffiliateReferral(id=3, affiliate_link_id=2, affiliate_user_id=2, referred_user_id=3, status="converted",
                              commission_amount=Decimal("60.00"), click_date=instant + timedelta(minutes=2)),
            AffiliateReferral(id=4, affiliate_link_id=1, affiliate_user_id=2, referred_user_id=4, status="converted",
                              commission_amount=Decimal("70.00"), click_date=instant + timedelta(minutes=3)),
            AffiliateReferral(id=5, affiliate_link_id=1, affiliate_user_id=2, referred_user_id=3, program_id=2,
                              status="converted", commission_amount=Decimal("80.00"), click_date=instant + timedelta(minutes=4)),
            # Satisfies the legacy FK but cannot resolve to a current tenant program.
            AffiliateReferral(id=6, affiliate_link_id=1, affiliate_user_id=2, referred_user_id=3, program_id=999,
                              status="converted", commission_amount=Decimal("90.00"), click_date=instant + timedelta(minutes=5)),
            # Nullable historical parents are retained as incomplete source data.
            AffiliateReferral(id=7, affiliate_link_id=1, affiliate_user_id=2, referred_user_id=None, program_id=None,
                              status="pending", commission_amount=Decimal("2.00"), click_date=instant + timedelta(minutes=6)),
            AffiliateReferral(id=8, affiliate_link_id=1, affiliate_user_id=2, referred_user_id=3, program_id=1,
                              status="unknown", commission_amount=Decimal("100.00"), click_date=instant + timedelta(minutes=7)),
        ])
        db.session.flush()
        db.session.add_all([
            AffiliatePayout(id=1, affiliate_user_id=2, amount=Decimal("1.00"), method="hidden", status="pending"),
            AffiliatePayout(id=2, affiliate_user_id=1, amount=Decimal("1.00"), method="hidden", status="pending"),
            AffiliateCommission(id=1, affiliate_user_id=2, referral_id=1, amount=Decimal("6.00"),
                                type="one_time", status="approved", created_at=instant),
            AffiliateCommission(id=2, affiliate_user_id=2, referral_id=2, amount=Decimal("50.00"),
                                type="one_time", status="paid", created_at=instant),
            AffiliateCommission(id=3, affiliate_user_id=2, referral_id=3, amount=Decimal("60.00"),
                                type="one_time", status="approved", created_at=instant),
            AffiliateCommission(id=4, affiliate_user_id=2, referral_id=4, amount=Decimal("70.00"),
                                type="one_time", status="approved", created_at=instant),
            AffiliateCommission(id=5, affiliate_user_id=2, referral_id=5, amount=Decimal("80.00"),
                                type="one_time", status="approved", created_at=instant),
            AffiliateCommission(id=6, affiliate_user_id=2, referral_id=None, amount=Decimal("90.00"),
                                type="one_time", status="approved", created_at=instant),
            AffiliateCommission(id=7, affiliate_user_id=2, referral_id=6, amount=Decimal("90.00"),
                                type="one_time", status="approved", created_at=instant),
            AffiliateCommission(id=8, affiliate_user_id=2, referral_id=7, amount=Decimal("2.00"),
                                type="one_time", status="pending", payout_id=1, created_at=instant),
            AffiliateCommission(id=9, affiliate_user_id=2, referral_id=7, amount=Decimal("3.00"),
                                type="one_time", status="approved", payout_id=1, created_at=instant),
            AffiliateCommission(id=10, affiliate_user_id=2, referral_id=1, amount=Decimal("4.00"),
                                type="one_time", status="paid", payout_id=1, created_at=instant),
            AffiliateCommission(id=11, affiliate_user_id=2, referral_id=1, amount=Decimal("50.00"),
                                type="one_time", status="pending", payout_id=2, created_at=instant),
            AffiliateCommission(id=12, affiliate_user_id=2, referral_id=1, amount=Decimal("60.00"),
                                type="one_time", status="approved", payout_id=999, created_at=instant),
            AffiliateCommission(id=13, affiliate_user_id=2, referral_id=1, amount=Decimal("70.00"),
                                type="one_time", status="paid", payout_id=2, created_at=instant),
            AffiliateCommission(id=14, affiliate_user_id=2, referral_id=1, amount=Decimal("80.00"),
                                type="one_time", status="paid", payout_id=999, created_at=instant),
            AffiliateCommission(id=15, affiliate_user_id=2, referral_id=1, amount=Decimal("90.00"),
                                type="legacy_unknown", status="approved", created_at=instant),
            AffiliateCommission(id=16, affiliate_user_id=2, referral_id=8, amount=Decimal("100.00"),
                                type="one_time", status="approved", created_at=instant),
        ])
        db.session.commit()
        app.tokens = {identity: db.session.get(User, identity).generate_access_token() for identity in (1, 2)}
    try:
        yield app, tables
    finally:
        with app.app_context():
            db.session.rollback()
            db.session.remove()
            db.metadata.drop_all(bind=db.engine, tables=list(reversed(fixture_tables)))
            if sentinel_created:
                db.metadata.remove(programs)


def _headers(app, user_id):
    return {"Authorization": "Bearer " + app.tokens[user_id]}


def test_ui4_dashboard_reads_postgresql_owner_scope_decimals_and_no_writes(
    ui4_dashboard_reads_pg_app, record_property,
):
    """PostgreSQL confirms exact tenant-bound projections without legacy mutations."""
    from src.database import db
    from src.models.affiliate import AffiliateCommission, AffiliateLink, AffiliateReferral

    app, _tables = ui4_dashboard_reads_pg_app
    with app.app_context():
        assert db.engine.dialect.name == "postgresql"
        before = {
            "links": [dict(row) for row in db.session.execute(select(AffiliateLink.__table__).order_by(AffiliateLink.id)).mappings()],
            "referrals": [dict(row) for row in db.session.execute(select(AffiliateReferral.__table__).order_by(AffiliateReferral.id)).mappings()],
            "commissions": [dict(row) for row in db.session.execute(select(AffiliateCommission.__table__).order_by(AffiliateCommission.id)).mappings()],
        }
        writes = []

        def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
                writes.append(statement)

        event.listen(db.engine, "before_cursor_execute", observe)
        try:
            user_response = app.test_client().get("/api/v1/users/dashboard", headers=_headers(app, 1))
            affiliate_response = app.test_client().get("/api/v1/affiliate/dashboard", headers=_headers(app, 2))
            referrals_response = app.test_client().get("/api/v1/affiliate/referrals", headers=_headers(app, 2))
            pending_response = app.test_client().get(
                "/api/v1/affiliate/commissions?status=pending", headers=_headers(app, 2),
            )
            approved_response = app.test_client().get(
                "/api/v1/affiliate/commissions?status=approved", headers=_headers(app, 2),
            )
            paid_response = app.test_client().get(
                "/api/v1/affiliate/commissions?status=paid", headers=_headers(app, 2),
            )
        finally:
            event.remove(db.engine, "before_cursor_execute", observe)
        assert (
            user_response.status_code == affiliate_response.status_code == referrals_response.status_code
            == pending_response.status_code == approved_response.status_code == paid_response.status_code == 200
        )
        user_payload = user_response.get_json()
        affiliate_payload = affiliate_response.get_json()
        assert user_payload["owner_context"] == {"user_id": 1, "tenant_id": 1}
        assert user_payload["user"]["tenant_id"] == 1
        assert set(user_payload["user"]) == {"id", "tenant_id", "role", "first_name"}
        assert [row["id"] for row in user_payload["recent_challenges"]] == [1]
        assert user_payload["recent_challenges"][0]["currency"] is None
        assert affiliate_payload["owner_context"] == {"user_id": 2, "tenant_id": 1}
        assert affiliate_payload["stats"] == {
            "total_clicks": 4,
            "total_conversions": 1,
            "total_revenue": "40.00",
            "total_commission": "15.00",
            "conversion_rate": "25",
            "pending_commission": "2.00",
            "approved_commission": "9.00",
            "paid_commission": "4.00",
            "currency": None,
            "available_for_payout": None,
            "payouts_enabled": False,
            "commission_verification": "unverified_legacy",
        }
        assert affiliate_payload["link_pagination"] == {"total": 1, "limit": 50, "truncated": False}
        assert affiliate_payload["links"] == [{
            "id": 1, "name": "Staging canonical root", "url": "https://marketedgepros.com/?ref=SAFEPGCOPY",
            "clicks": 4, "conversions": 1,
        }]
        assert [row["id"] for row in referrals_response.get_json()["referrals"]] == [7, 1]
        assert [row["id"] for row in affiliate_payload["recent_referrals"]] == [7, 1]
        assert [row["id"] for row in pending_response.get_json()["commissions"]] == [8]
        assert [row["id"] for row in approved_response.get_json()["commissions"]] == [9, 1]
        assert [row["id"] for row in paid_response.get_json()["commissions"]] == [10]
        assert writes == []
        db.session.expire_all()
        after = {
            "links": [dict(row) for row in db.session.execute(select(AffiliateLink.__table__).order_by(AffiliateLink.id)).mappings()],
            "referrals": [dict(row) for row in db.session.execute(select(AffiliateReferral.__table__).order_by(AffiliateReferral.id)).mappings()],
            "commissions": [dict(row) for row in db.session.execute(select(AffiliateCommission.__table__).order_by(AffiliateCommission.id)).mappings()],
        }
        assert after == before

    record_property("ui4_user_dashboard_payload", json.dumps(user_payload, sort_keys=True))
    record_property("ui4_affiliate_dashboard_payload", json.dumps(affiliate_payload, sort_keys=True))


def test_ui4_dashboard_reads_postgresql_nullable_counters_are_unknown(
    ui4_dashboard_reads_pg_app,
):
    """A complete aggregate never substitutes zero for a NULL legacy counter."""
    from src.database import db
    from src.models.affiliate import AffiliateLink

    app, _tables = ui4_dashboard_reads_pg_app
    with app.app_context():
        link = db.session.get(AffiliateLink, 1)
        link.clicks = None
        link.conversions = None
        link.total_revenue = None
        db.session.commit()

    response = app.test_client().get("/api/v1/affiliate/dashboard", headers=_headers(app, 2))
    assert response.status_code == 200
    payload = response.get_json()
    assert {
        key: payload["stats"][key]
        for key in ("total_clicks", "total_conversions", "total_revenue", "conversion_rate")
    } == {
        "total_clicks": None,
        "total_conversions": None,
        "total_revenue": None,
        "conversion_rate": None,
    }
    assert payload["links"] == [{
        "id": 1,
        "name": "Staging canonical root",
        "url": "https://marketedgepros.com/?ref=SAFEPGCOPY",
        "clicks": None,
        "conversions": None,
    }]
