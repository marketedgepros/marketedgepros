"""Fail-closed regressions for legacy affiliate commission and approval mutations."""
from decimal import Decimal

import pytest
from sqlalchemy import JSON

from src.database import db
from src.models.agent import Agent
from src.models.commission import Commission
from src.models.payment import Payment
from src.models.payment_approval import PaymentApprovalRequest
from src.models.referral import Referral
from src.models.tenant import Tenant
from src.models.token_blacklist import TokenBlacklist
from src.models.trading_program import Challenge, TradingProgram
from src.models.user import User
from src.services.affiliate_financial_boundary import AffiliateSettlementNotConfigured
from src.services.commission_service import CommissionService
from src.services.notification_service import NotificationService
from src.services.payment_approval_service import PaymentApprovalService


@pytest.fixture
def commission_boundary_app():
    """Full application factory with only synthetic affiliate settlement state."""
    from src.app import create_app

    app = create_app('testing', config_overrides={
        'EXPANDED_HIERARCHY_ENABLED': False,
        'PLATFORM_ROOT_USER_ID': 1,
        'PROPAGATE_EXCEPTIONS': False,
    })
    tables = [
        Tenant.__table__, User.__table__, TokenBlacklist.__table__, Agent.__table__,
        Referral.__table__, TradingProgram.__table__, Challenge.__table__, Payment.__table__,
        PaymentApprovalRequest.__table__, Commission.__table__,
    ]
    tenant_settings_type = Tenant.__table__.c.settings.type
    with app.app_context():
        if db.engine.dialect.name == 'sqlite':
            Tenant.__table__.c.settings.type = JSON()
        db.metadata.create_all(bind=db.engine, tables=tables)
        db.session.add_all([
            Tenant(id=1, name='Synthetic Commission Brand', subdomain='commission-brand', status='active'),
            User(
                id=1, email='commission-admin@example.invalid', password_hash='not-a-credential',
                first_name='Synthetic', last_name='Admin', tenant_id=1, role='supermaster',
                is_active=True, is_verified=True, can_create_same_role=True,
                parent_id=None, tree_path='1', level=0,
            ),
            User(
                id=2, email='commission-trader@example.invalid', password_hash='not-a-credential',
                first_name='Synthetic', last_name='Trader', tenant_id=1, role='trader',
                is_active=True, is_verified=True, can_create_same_role=False,
                parent_id=1, tree_path='1/2', level=1,
            ),
            User(
                id=3, email='commission-agent@example.invalid', password_hash='not-a-credential',
                first_name='Synthetic', last_name='Agent', tenant_id=1, role='affiliate',
                is_active=True, is_verified=True, can_create_same_role=False,
                parent_id=1, tree_path='1/3', level=1,
            ),
            Agent(
                id=31, agent_code='SYNTHCOM31', user_id=3, commission_rate=Decimal('10.00'),
                pending_balance=Decimal('9.90'), total_earned=Decimal('1.00'),
                total_withdrawn=Decimal('1.00'), total_sales=Decimal('99.00'), is_active=True,
            ),
            Referral(
                id=41, agent_id=31, referred_user_id=2, referral_code='SYNTH-COMMISSION',
                status='active', total_purchases=1, total_spent=Decimal('99.00'),
            ),
            TradingProgram(
                id=10, tenant_id=1, name='Synthetic Commission Program', type='one_phase',
                account_size=Decimal('10000.00'), price=Decimal('99.00'), is_active=True,
            ),
            Challenge(
                id=50, user_id=2, program_id=10, status='pending', payment_status='pending',
                payment_type='cash', approval_status='pending',
            ),
            Payment(
                id=60, user_id=2, amount=Decimal('99.00'), payment_type='cash',
                transaction_id='synthetic-commission-payment', status='pending', approval_status='pending',
            ),
            PaymentApprovalRequest(
                id=70, challenge_id=50, payment_id=60, requested_by=1, requested_for=2,
                amount=Decimal('99.00'), payment_type='cash', status='pending',
            ),
            Commission(
                id=80, agent_id=31, referral_id=41, challenge_id=50, sale_amount=Decimal('99.00'),
                commission_rate=Decimal('10.00'), commission_amount=Decimal('9.90'), status='pending',
            ),
        ])
        db.session.commit()
        app.commission_tokens = {
            identity: db.session.get(User, identity).generate_access_token()
            for identity in (1, 2, 3)
        }
    yield app
    with app.app_context():
        db.session.remove()
        db.metadata.drop_all(bind=db.engine, tables=list(reversed(tables)))
        Tenant.__table__.c.settings.type = tenant_settings_type


def _headers(app, actor=1):
    return {'Authorization': 'Bearer ' + app.commission_tokens[actor]}


def _state():
    commission = db.session.get(Commission, 80)
    agent = db.session.get(Agent, 31)
    challenge = db.session.get(Challenge, 50)
    payment = db.session.get(Payment, 60)
    approval = db.session.get(PaymentApprovalRequest, 70)
    return {
        'commission': (commission.status, commission.approved_at, commission.paid_at,
                       commission.payment_method, commission.transaction_id),
        'agent': (agent.pending_balance, agent.total_earned, agent.total_withdrawn, agent.total_sales),
        'challenge': (challenge.status, challenge.payment_status, challenge.approval_status,
                      challenge.approved_by, challenge.approved_at),
        'payment': (payment.status, payment.approval_status, payment.approved_by,
                    payment.approved_at, payment.completed_at),
        'approval': (approval.status, approval.reviewed_by, approval.reviewed_at, approval.admin_notes),
    }


class _QueryCanary:
    def __init__(self, calls):
        self.calls = calls

    def __getattr__(self, name):
        self.calls.append('query.' + name)
        raise AssertionError('legacy affiliate mutator performed an ORM query')


def _forbidden(calls, label):
    def blocked(*args, **kwargs):
        calls.append(label)
        raise AssertionError(label + ' must not be called by a refused legacy mutator')
    return blocked


def test_direct_commission_and_payment_approval_mutators_refuse_before_query_session_or_notification(
    commission_boundary_app, monkeypatch,
):
    """Even malformed inputs must not reach ORM/session/notification code."""
    with commission_boundary_app.app_context():
        calls = []
        query_canary = _QueryCanary(calls)
        for model in (Commission, Agent, Referral, Challenge, Payment, PaymentApprovalRequest, User):
            monkeypatch.setattr(model, 'query', query_canary, raising=False)
        for method in ('query', 'add', 'commit', 'rollback', 'flush'):
            monkeypatch.setattr(db.session, method, _forbidden(calls, 'session.' + method))
        monkeypatch.setattr(NotificationService, 'create_notification', _forbidden(calls, 'notification'))
        monkeypatch.setattr(PaymentApprovalService, '_notify_super_admins', _forbidden(calls, 'notify_super_admins'))
        monkeypatch.setattr(PaymentApprovalService, '_notify_approval', _forbidden(calls, 'notify_approval'))

        for method, args in [
            (CommissionService.calculate_and_create_commission, (None, object())),
            (CommissionService.approve_commission, ('not-an-id', None)),
            (CommissionService.mark_commission_paid, (False, None, object())),
            (PaymentApprovalService.create_approval_request, (None, None, None, None, object(), 'invalid')),
            (PaymentApprovalService.approve_request, ('not-an-id', None, object())),
        ]:
            with pytest.raises(AffiliateSettlementNotConfigured) as caught:
                method(*args)
            assert caught.value.code == 'AFFILIATE_SETTLEMENT_NOT_CONFIGURED'
            assert caught.value.status == 503
        assert calls == []


def test_direct_approval_refusal_leaves_existing_challenge_payment_and_request_unchanged(commission_boundary_app):
    with commission_boundary_app.app_context():
        before = _state()
        with pytest.raises(AffiliateSettlementNotConfigured):
            PaymentApprovalService.approve_request(70, 1, admin_notes='must not persist')
        db.session.expire_all()
        assert _state() == before


@pytest.mark.parametrize('path', [
    '/api/v1/commissions/80/approve',
    '/api/v1/commissions/80/pay',
])
def test_commission_http_mutators_require_auth_then_admin_then_fixed_refusal_without_body_parsing(
    commission_boundary_app, path, monkeypatch,
):
    with commission_boundary_app.app_context():
        before = _state()

        def service_forbidden(*args, **kwargs):
            raise AssertionError('commission endpoint must not invoke a legacy service mutator')

        monkeypatch.setattr(CommissionService, 'approve_commission', service_forbidden)
        monkeypatch.setattr(CommissionService, 'mark_commission_paid', service_forbidden)
        client = commission_boundary_app.test_client()
        assert client.post(path, data='{', content_type='application/json').status_code == 401
        ordinary = client.post(path, data='{', content_type='application/json', headers=_headers(commission_boundary_app, 2))
        assert ordinary.status_code == 403
        assert ordinary.get_json() == {'error': 'Admin access required'}

        cookie_client = commission_boundary_app.test_client()
        cookie_client.set_cookie('access_token', commission_boundary_app.commission_tokens[1])
        csrf = cookie_client.post(path, data='{', content_type='application/json')
        assert csrf.status_code == 403
        assert csrf.get_json() == {'error': 'CSRF validation failed', 'code': 'CSRF_INVALID'}

        refused = client.post(path, data='{', content_type='application/json', headers=_headers(commission_boundary_app))
        assert refused.status_code == 503
        assert refused.get_json() == {
            'error': 'Affiliate settlement and identity verification are not configured',
            'code': 'AFFILIATE_SETTLEMENT_NOT_CONFIGURED',
        }
        db.session.expire_all()
        assert _state() == before
