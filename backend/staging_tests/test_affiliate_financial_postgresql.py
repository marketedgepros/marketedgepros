"""Legacy affiliate data stays unchanged in runner-isolated PostgreSQL."""
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import Column, Integer, Table, event, select


@pytest.fixture
def affiliate_pg_rows(app, staging_resources):
    from src.database import db
    from src.models.user import User
    from src.models.tenant import Tenant
    from src.models.affiliate import AffiliateSettings, AffiliateLink, AffiliateReferral, AffiliateCommission, AffiliatePayout

    # The historic programs FK is not the newer trading_programs model. As in
    # the legacy inventory, this is fixture-only metadata, removed at teardown.
    added_sentinel = 'programs' not in db.metadata.tables
    programs = (Table('programs', db.metadata, Column('id', Integer, primary_key=True))
                if added_sentinel else db.metadata.tables['programs'])
    tables = [programs, AffiliateSettings.__table__, AffiliateLink.__table__, AffiliateReferral.__table__,
              AffiliatePayout.__table__, AffiliateCommission.__table__]
    with app.app_context():
        assert db.engine.dialect.name == 'postgresql'
        db.metadata.create_all(bind=db.engine, tables=tables)
        db.session.add(Tenant(id=1, name='Synthetic PG affiliate', subdomain='affiliate-pg', status='active'))
        db.session.add(User(id=1, tenant_id=1, email='affiliate-pg@example.invalid', password_hash='not-a-credential',
                            first_name='Synthetic', last_name='Affiliate', role='affiliate', is_active=True,
                            is_verified=True, parent_id=None, tree_path='1', level=0))
        db.session.add(AffiliateSettings(id=1, is_active=True, auto_approve_commissions=True))
        db.session.add(AffiliateLink(id=1, user_id=1, code='AFF_PG_SYNTH', commission_rate=Decimal('15.00'),
                                    clicks=1, conversions=1, total_revenue=Decimal('100.00'), total_commission=Decimal('15.00')))
        db.session.flush()
        # A deliberately historic self-referral row is retained, not repaired or
        # deleted silently. No new commission can be generated from it.
        db.session.add(AffiliateReferral(id=1, affiliate_link_id=1, affiliate_user_id=1, referred_user_id=1,
                                        status='converted', purchase_amount=Decimal('100.00'), commission_amount=Decimal('15.00'),
                                        conversion_date=datetime(2026, 10, 11, 12)))
        db.session.flush()
        db.session.add(AffiliateCommission(id=1, affiliate_user_id=1, referral_id=1, amount=Decimal('15.00'), status='approved'))
        db.session.commit()
    try:
        yield app, tables
    finally:
        with app.app_context():
            db.session.rollback()
            db.session.remove()
            db.metadata.drop_all(bind=db.engine, tables=list(reversed(tables)))
            if added_sentinel:
                db.metadata.remove(programs)


def test_refused_self_referral_and_payout_never_reach_sql_and_preserve_every_column(affiliate_pg_rows):
    from src.database import db
    from src.services.affiliate_service import AffiliateService
    from src.services.commission_service import CommissionService
    from src.services.payment_approval_service import PaymentApprovalService
    from src.services.affiliate_financial_boundary import AffiliateSettlementNotConfigured
    app, tables = affiliate_pg_rows
    with app.app_context():
        def snapshot():
            return {table.name: [dict(row) for row in db.session.execute(select(table).order_by(table.c.id)).mappings()]
                    for table in tables}
        before = snapshot()
        statements = []
        def reject_sql(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
            raise AssertionError('Refused affiliate mutator used PostgreSQL')
        event.listen(db.engine, 'before_cursor_execute', reject_sql)
        try:
            for method, args in [
                (AffiliateService.track_conversion, (1, 1, Decimal('100.00'), 'AFF_PG_SYNTH')),
                (AffiliateService.validate_payout_request, (1,)),
                (CommissionService.calculate_and_create_commission, (1, Decimal('100.00'))),
                (CommissionService.approve_commission, (1, 1)),
                (CommissionService.mark_commission_paid, (1, 'crypto', 'synthetic-not-a-transfer')),
                (PaymentApprovalService.create_approval_request, (1, 1, 1, 1, Decimal('100.00'), 'cash')),
                (PaymentApprovalService.approve_request, (1, 1)),
            ]:
                with pytest.raises(AffiliateSettlementNotConfigured):
                    method(*args)
        finally:
            event.remove(db.engine, 'before_cursor_execute', reject_sql)
        assert statements == []
        db.session.expire_all()
        assert snapshot() == before


def test_postgresql_aggregate_reports_legacy_history_but_never_available_funds(affiliate_pg_rows):
    from src.database import db
    from src.services.affiliate_service import AffiliateService
    from src.models.affiliate import AffiliateCommission
    app, _ = affiliate_pg_rows
    with app.app_context():
        writes = []
        def observe(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
                writes.append(statement)
        event.listen(db.engine, 'before_cursor_execute', observe)
        try:
            result = AffiliateService.get_affiliate_stats(1)
        finally:
            event.remove(db.engine, 'before_cursor_execute', observe)
        assert result is not None
        assert result['commissions']['approved'] == 15
        assert result['commissions']['available_for_payout'] is None
        assert result['commissions']['payouts_enabled'] is False
        assert result['commissions']['verification'] == 'unverified_legacy'
        assert writes == []
        assert db.session.get(AffiliateCommission, 1).status == 'approved'
