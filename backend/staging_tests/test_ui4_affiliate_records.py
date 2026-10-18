"""UI-4 affiliate records against the runner-created temporary PostgreSQL cluster."""
from datetime import datetime, timedelta
from decimal import Decimal
import json

import pytest
from flask import Flask
from sqlalchemy import Column, Integer, Table, event, text


@pytest.fixture
def ui4_affiliate_records_pg_app(staging_resources):
    """A real affiliate route host backed only by the staging runner's Unix socket."""
    from src.database import db
    from src.models.affiliate import (
        AffiliateCommission, AffiliateLink, AffiliatePayout, AffiliateReferral, AffiliateSettings,
    )
    from src.models.tenant import Tenant
    from src.models.token_blacklist import TokenBlacklist
    from src.models.trading_program import TradingProgram
    from src.models.user import User
    from src.routes.affiliate import affiliate_bp
    from src.utils.hierarchy_scoping import init_hierarchy_scoping

    app = Flask("ui4-affiliate-records-postgresql")
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI=staging_resources["pg_url"],
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY="ui4-affiliate-records-staging-synthetic-key",
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=10),
        JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=1),
        EXPANDED_HIERARCHY_ENABLED=True,
    )
    db.init_app(app)
    init_hierarchy_scoping(db, User)
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
    fixture_tables = [
        programs, AffiliateSettings.__table__, AffiliateLink.__table__, AffiliateReferral.__table__,
        AffiliatePayout.__table__, AffiliateCommission.__table__,
    ]
    instant = datetime(2026, 10, 12, 13, 0, 0)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=tables)
        # A current FK normally prevents this historic corruption.  Dropping it
        # only in the runner-created temporary schema lets the read contract
        # prove that a non-null, missing payout parent is still excluded.
        db.session.execute(text(
            "ALTER TABLE affiliate_commissions "
            "DROP CONSTRAINT affiliate_commissions_payout_id_fkey"
        ))
        db.session.execute(programs.insert(), [{"id": 1}, {"id": 2}, {"id": 999}])
        db.session.add_all([
            Tenant(id=1, name="UI4 PG owner", subdomain="ui4-records-pg-owner", status="active"),
            Tenant(id=2, name="UI4 PG foreign", subdomain="ui4-records-pg-foreign", status="active"),
            User(id=2, email="pg-affiliate@example.invalid", password_hash="x", first_name="Affiliate",
                 last_name="PG", tenant_id=1, role="affiliate", is_active=True, is_verified=True,
                 tree_path="2", level=0),
            User(id=3, email="pg-referred@example.invalid", password_hash="x", first_name="Referred",
                 last_name="PG", tenant_id=1, role="trader", is_active=True, is_verified=True,
                 tree_path="3", level=0),
            User(id=4, email="pg-foreign@example.invalid", password_hash="x", first_name="Foreign",
                 last_name="PG", tenant_id=2, role="trader", is_active=True, is_verified=True,
                 tree_path="4", level=0),
            User(id=6, email="pg-foreign-owner@example.invalid", password_hash="x", first_name="Foreign",
                 last_name="Owner", tenant_id=2, role="affiliate", is_active=True, is_verified=True,
                 tree_path="6", level=0),
            TradingProgram(id=1, tenant_id=1, name="UI4 PG program", type="one_phase",
                           account_size=Decimal("1000.00"), price=Decimal("99.00"), is_active=True),
            TradingProgram(id=2, tenant_id=2, name="UI4 PG foreign program", type="one_phase",
                           account_size=Decimal("1000.00"), price=Decimal("99.00"), is_active=True),
            AffiliateLink(id=10, user_id=2, code="UI4PGOWNER", name="must not leak",
                          clicks=1, conversions=1, total_revenue=Decimal("1.00"),
                          total_commission=Decimal("1.00"), commission_rate=Decimal("15.00"), created_at=instant),
            AffiliateLink(id=11, user_id=6, code="UI4PGFOREIGN", name="foreign", clicks=1, conversions=1,
                          total_revenue=Decimal("1.00"), total_commission=Decimal("1.00"),
                          commission_rate=Decimal("15.00"), created_at=instant),
        ])
        db.session.flush()
        db.session.add_all([
            AffiliateReferral(id=1, affiliate_link_id=10, affiliate_user_id=2, referred_user_id=3,
                              program_id=1, status="converted", purchase_amount=Decimal("0.00"),
                              commission_amount=Decimal("0.00"), click_date=instant),
            AffiliateReferral(id=2, affiliate_link_id=10, affiliate_user_id=2, referred_user_id=3,
                              program_id=1, status="pending", click_date=instant),
            AffiliateReferral(id=3, affiliate_link_id=10, affiliate_user_id=2, referred_user_id=2,
                              program_id=1, status="converted", click_date=instant),
            AffiliateReferral(id=4, affiliate_link_id=10, affiliate_user_id=2, referred_user_id=4,
                              program_id=1, status="converted", click_date=instant),
            AffiliateReferral(id=5, affiliate_link_id=11, affiliate_user_id=2, referred_user_id=3,
                              program_id=1, status="converted", click_date=instant),
            AffiliateReferral(id=6, affiliate_link_id=10, affiliate_user_id=2, referred_user_id=3,
                              program_id=2, status="converted", click_date=instant),
            AffiliateReferral(id=7, affiliate_link_id=10, affiliate_user_id=2, referred_user_id=3,
                              program_id=999, status="converted", click_date=instant),
        ])
        db.session.flush()
        db.session.add_all([
            AffiliatePayout(id=1, affiliate_user_id=2, amount=Decimal("1.00"), method="hidden", status="pending"),
            AffiliatePayout(id=2, affiliate_user_id=6, amount=Decimal("1.00"), method="hidden", status="pending"),
            AffiliateCommission(id=1, affiliate_user_id=2, referral_id=1, amount=Decimal("0.00"),
                                type="one_time", status="approved", created_at=instant),
            AffiliateCommission(id=2, affiliate_user_id=2, referral_id=2, amount=Decimal("1.25"),
                                type="recurring", status="paid", payout_id=1, created_at=instant),
            AffiliateCommission(id=3, affiliate_user_id=2, referral_id=1, amount=Decimal("2.00"),
                                type="one_time", status="approved", payout_id=2, created_at=instant),
            AffiliateCommission(id=4, affiliate_user_id=2, referral_id=1, amount=Decimal("3.00"),
                                type="one_time", status="approved", payout_id=999, created_at=instant),
            AffiliateCommission(id=5, affiliate_user_id=2, referral_id=None, amount=Decimal("4.00"),
                                type="one_time", status="approved", created_at=instant),
            *[
                AffiliateCommission(id=commission_id, affiliate_user_id=2, referral_id=referral_id,
                                    amount=Decimal("5.00"), type="one_time", status="approved", created_at=instant)
                for commission_id, referral_id in zip(range(6, 11), range(3, 8))
            ],
        ])
        db.session.commit()
        app.token = db.session.get(User, 2).generate_access_token()
    try:
        yield app, tables
    finally:
        with app.app_context():
            db.session.rollback()
            db.session.remove()
            db.metadata.drop_all(bind=db.engine, tables=list(reversed(fixture_tables)))
            if sentinel_created:
                db.metadata.remove(programs)


def _headers(app):
    return {"Authorization": "Bearer " + app.token}


def test_ui4_affiliate_records_postgresql_temporary_schema_contract(
    ui4_affiliate_records_pg_app, record_property,
):
    """Temporary PostgreSQL confirms timeout, owner joins, exact payloads, and no DML."""
    from src.database import db

    app, _tables = ui4_affiliate_records_pg_app
    with app.app_context():
        assert db.engine.dialect.name == "postgresql"
        statements = []

        def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)

        event.listen(db.engine, "before_cursor_execute", observe)
        try:
            referrals = app.test_client().get("/api/v1/affiliate/referrals?per_page=1&page=1", headers=_headers(app))
            commissions = app.test_client().get("/api/v1/affiliate/commissions?per_page=1&page=1", headers=_headers(app))
            filtered = app.test_client().get("/api/v1/affiliate/commissions?status=approved", headers=_headers(app))
        finally:
            event.remove(db.engine, "before_cursor_execute", observe)

    assert referrals.status_code == commissions.status_code == filtered.status_code == 200
    referral_payload = referrals.get_json()
    commission_payload = commissions.get_json()
    assert referral_payload["pagination"] == {"page": 1, "per_page": 1, "total": 2, "pages": 2}
    assert commission_payload["pagination"] == {"page": 1, "per_page": 1, "total": 2, "pages": 2}
    assert [row["id"] for row in referral_payload["referrals"]] == [2]
    assert [row["id"] for row in commission_payload["commissions"]] == [2]
    assert filtered.get_json()["pagination"] == {"page": 1, "per_page": 20, "total": 1, "pages": 1}
    assert [row["id"] for row in filtered.get_json()["commissions"]] == [1]
    assert all(not statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for statement in statements)
    assert sum("SET LOCAL statement_timeout" in statement for statement in statements) == 3
    assert "must not leak" not in json.dumps({"r": referral_payload, "c": commission_payload})
    record_property("ui4_affiliate_referrals_payload", json.dumps(referral_payload, sort_keys=True))
    record_property("ui4_affiliate_commissions_payload", json.dumps(commission_payload, sort_keys=True))
