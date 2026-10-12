"""Full-factory JWT requests with synthetic data; no provider or production use."""
from decimal import Decimal

import pytest
from sqlalchemy import Column, Integer, Table, event, select

from src.database import db
from src.models.user import User
from src.models.tenant import Tenant
from src.models.token_blacklist import TokenBlacklist
from src.models.trading_program import TradingProgram
from src.models.affiliate import (
    AffiliateSettings, AffiliateLink, AffiliateReferral, AffiliateCommission, AffiliatePayout,
)
from src.services.affiliate_service import AffiliateService
from src.services.affiliate_financial_boundary import AffiliateSettlementNotConfigured


@pytest.fixture
def affiliate_boundary_app():
    from src.app import create_app
    app = create_app('testing', config_overrides={
        'EXPANDED_HIERARCHY_ENABLED': False, 'PLATFORM_ROOT_USER_ID': 1,
        'PROPAGATE_EXCEPTIONS': False,
    })
    # Legacy affiliate FK targets programs, not the newer trading_programs
    # model. Fixture-only sentinel table; never register a production model.
    sentinel_created = 'programs' not in db.metadata.tables
    programs = (Table('programs', db.metadata, Column('id', Integer, primary_key=True))
                if sentinel_created else db.metadata.tables['programs'])
    tables = [Tenant.__table__, User.__table__, TokenBlacklist.__table__, TradingProgram.__table__,
              programs,
              AffiliateSettings.__table__, AffiliateLink.__table__, AffiliateReferral.__table__,
              AffiliatePayout.__table__, AffiliateCommission.__table__]
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=tables)
        db.session.add_all([
            Tenant(id=1, name='Synthetic affiliate brand', subdomain='affiliate-boundary', status='active'),
            Tenant(id=2, name='Foreign brand', subdomain='affiliate-foreign', status='active'),
            TradingProgram(id=1, tenant_id=1, name='Synthetic affiliate program', type='one_phase',
                           account_size=Decimal('1000.00'), price=Decimal('99.00'), is_active=True),
        ])
        for identity, role, tenant in [(1, 'supermaster', 1), (2, 'affiliate', 1), (3, 'trader', 1), (4, 'affiliate', 2)]:
            db.session.add(User(id=identity, email=f'affiliate-{identity}@example.invalid', password_hash='not-a-credential',
                                first_name='Synthetic', last_name='Actor', role=role, tenant_id=tenant,
                                is_active=True, is_verified=True, can_create_same_role=identity == 1,
                                parent_id=None if identity == 1 else 1, tree_path='1' if identity == 1 else f'1/{identity}',
                                level=0 if identity == 1 else 1))
        # Deliberately retain an unsafe historic auto-approval setting: it must
        # not reopen ANY financial mutation or make the totals payout authority.
        db.session.add(AffiliateSettings(id=1, is_active=True, default_commission_rate=Decimal('15.00'),
                                         auto_approve_commissions=True, min_payout_amount=Decimal('1.00')))
        db.session.add(AffiliateLink(id=10, user_id=2, code='SYNTH_AFFILIATE', commission_rate=Decimal('15.00'),
                                    clicks=12, conversions=1, total_revenue=Decimal('100.00'), total_commission=Decimal('15.00')))
        db.session.flush()
        db.session.execute(programs.insert().values(id=1))
        db.session.add(AffiliateReferral(id=11, affiliate_link_id=10, affiliate_user_id=2, referred_user_id=3,
                                         program_id=1, status='converted'))
        db.session.add(AffiliatePayout(id=12, affiliate_user_id=2, amount=Decimal('7.50'), method='synthetic', status='pending'))
        db.session.flush()
        db.session.add_all([
            AffiliateCommission(id=13, affiliate_user_id=2, referral_id=11, amount=Decimal('7.50'), status='approved'),
            AffiliateCommission(id=14, affiliate_user_id=2, referral_id=11, amount=Decimal('7.50'), status='approved', payout_id=12),
        ])
        db.session.commit()
        app.affiliate_tokens = {identity: db.session.get(User, identity).generate_access_token() for identity in (1, 2, 3, 4)}
    yield app
    with app.app_context():
        db.session.remove()
        db.metadata.drop_all(bind=db.engine, tables=list(reversed(tables)))
        if sentinel_created:
            db.metadata.remove(programs)


def headers(app, actor=2):
    return {'Authorization': 'Bearer ' + app.affiliate_tokens[actor]}


def legacy_state():
    return {
        'links': [dict(row) for row in db.session.execute(select(AffiliateLink.__table__).order_by(AffiliateLink.id)).mappings()],
        'referrals': [dict(row) for row in db.session.execute(select(AffiliateReferral.__table__).order_by(AffiliateReferral.id)).mappings()],
        'commissions': [dict(row) for row in db.session.execute(select(AffiliateCommission.__table__).order_by(AffiliateCommission.id)).mappings()],
        'payouts': [dict(row) for row in db.session.execute(select(AffiliatePayout.__table__).order_by(AffiliatePayout.id)).mappings()],
        'settings': [(row.id, row.default_commission_rate, row.auto_approve_commissions) for row in AffiliateSettings.query.all()],
    }


@pytest.mark.parametrize('path,actor', [('/api/v1/affiliate/payout', 2),
                                       ('/api/v1/affiliate/admin/payout/12/process', 1),
                                       ('/api/v1/affiliate/admin/payout/999/process', 1)])
@pytest.mark.parametrize('body', [b'{', b'[]', b'x' * 5000,
                                 b'{"status":"completed","transaction_id":"fake","amount":999999,"affiliate_user_id":2}'],
                         ids=['invalid-json', 'array', 'oversized', 'forged-payment'])
def test_authenticated_payout_refusal_precedes_body_or_financial_sql(affiliate_boundary_app, monkeypatch, path, actor, body):
    from flask.wrappers import Request
    app = affiliate_boundary_app
    writes = []
    with app.app_context():
        before = legacy_state()
        def observe(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
                writes.append(statement)
        def forbid_body(*args, **kwargs):
            raise AssertionError('Legacy payout must not parse request body')
        monkeypatch.setattr(Request, 'get_json', forbid_body)
        event.listen(db.engine, 'before_cursor_execute', observe)
        try:
            # Fresh client/request context, not a mocked authentication decorator.
            response = app.test_client().post(path, data=body, content_type='application/json', headers=headers(app, actor))
        finally:
            event.remove(db.engine, 'before_cursor_execute', observe)
        assert response.status_code == 503
        assert response.get_json()['code'] == 'AFFILIATE_SETTLEMENT_NOT_CONFIGURED'
        assert legacy_state() == before
        assert writes == []


def test_auth_role_tenant_and_cookie_csrf_are_not_bypassed(affiliate_boundary_app):
    app = affiliate_boundary_app
    for path in ['/api/v1/affiliate/payout', '/api/v1/affiliate/admin/payout/12/process']:
        assert app.test_client().post(path, json={}).status_code == 401
        assert app.test_client().post(path, json={}, headers={'Authorization': 'Bearer invalid'}).status_code == 401
        assert app.test_client().post(path, json={}, headers=headers(app, 4)).status_code == 401
        client = app.test_client()
        client.set_cookie('access_token', app.affiliate_tokens[1])
        response = client.post(path, json={})
        assert response.status_code == 403 and response.get_json()['code'] == 'CSRF_INVALID'
    denied = app.test_client().post('/api/v1/affiliate/admin/payout/12/process', json={}, headers=headers(app, 2))
    assert denied.status_code == 403 and denied.get_json()['error'] == 'Admin access required'


@pytest.mark.parametrize('method,args', [(AffiliateService.track_conversion, (2, 10, Decimal('100.00'), 'SYNTH_AFFILIATE')),
                                       (AffiliateService.track_conversion, (3, 10, Decimal('-100.00'), None)),
                                       (AffiliateService.validate_payout_request, (2,))])
def test_direct_legacy_services_fail_without_any_app_context(method, args):
    # No request, IP, user or DB lookup is available. They still fail with the
    # intended explicit boundary, not None/success or a swallowed exception.
    with pytest.raises(AffiliateSettlementNotConfigured) as caught:
        method(*args)
    assert caught.value.code == 'AFFILIATE_SETTLEMENT_NOT_CONFIGURED'
    assert caught.value.status == 503


def test_direct_services_do_not_use_session_even_with_legacy_auto_approve(affiliate_boundary_app, monkeypatch):
    with affiliate_boundary_app.app_context():
        before = legacy_state()
        def forbidden(*args, **kwargs):
            raise AssertionError('Legacy financial service touched DB/session')
        for name in ('query', 'execute', 'add', 'flush', 'commit', 'rollback'):
            monkeypatch.setattr(db.session, name, forbidden)
        for method, args in [(AffiliateService.track_conversion, (2, 10, 100, 'SYNTH_AFFILIATE')),
                             (AffiliateService.validate_payout_request, (2,))]:
            with pytest.raises(AffiliateSettlementNotConfigured):
                method(*args)
        assert before['settings'][0][2] is True


@pytest.mark.parametrize('value', [True, 1, 0, 'true', 'false', None, [], {}])
def test_auto_approval_cannot_be_enabled_or_coerced(affiliate_boundary_app, value):
    app = affiliate_boundary_app
    with app.app_context():
        before = legacy_state()
    response = app.test_client().put('/api/v1/affiliate/admin/settings', json={'auto_approve_commissions': value,
                                       'default_commission_rate': 99}, headers=headers(app, 1))
    assert response.status_code == 409 and response.get_json()['code'] == 'AFFILIATE_AUTO_APPROVAL_UNAVAILABLE'
    with app.app_context():
        assert legacy_state() == before


def test_auto_approval_can_be_disabled_but_not_reenabled(affiliate_boundary_app):
    app = affiliate_boundary_app
    response = app.test_client().put('/api/v1/affiliate/admin/settings', json={'auto_approve_commissions': False}, headers=headers(app, 1))
    assert response.status_code == 200
    with app.app_context():
        assert db.session.get(AffiliateSettings, 1).auto_approve_commissions is False
    assert app.test_client().put('/api/v1/affiliate/admin/settings', json={'auto_approve_commissions': True}, headers=headers(app, 1)).status_code == 409


@pytest.mark.parametrize('raw,code', [(b'{', 400), (b'[]', 400), (b'x' * 4097, 413),
                                      (b'{"auto_approve_commissions":true,"auto_approve_commissions":false}', 400),
                                      (b'[' * 1100 + b']' * 1100, 400)],
                         ids=['invalid-json', 'array', 'oversized', 'duplicate-fields', 'deep-json'])
def test_settings_body_is_bounded_and_unambiguous(affiliate_boundary_app, raw, code):
    app = affiliate_boundary_app
    assert app.test_client().put('/api/v1/affiliate/admin/settings', data=raw, content_type='application/json', headers=headers(app, 1)).status_code == code


def test_program_and_history_are_explicitly_not_payout_authority(affiliate_boundary_app):
    app = affiliate_boundary_app
    info = app.test_client().get('/api/v1/affiliate/info')
    assert info.status_code == 200 and info.get_json()['program']['commission_rate'] == 15
    assert info.get_json()['program']['payouts_enabled'] is False
    with app.app_context():
        before = legacy_state()
    dashboard = app.test_client().get('/api/v1/affiliate/dashboard', headers=headers(app))
    assert dashboard.status_code == 200
    stats = dashboard.get_json()['stats']
    # This fixture refers owner 2 to a different same-tenant user (3). Its two
    # stored commissions remain exact legacy categories, never payout authority.
    assert stats['approved_commission'] == '15.00' and stats['available_for_payout'] is None
    assert stats['payouts_enabled'] is False and stats['commission_verification'] == 'unverified_legacy'
    for endpoint, field in [('commissions', 'commissions'), ('payouts', 'payouts')]:
        response = app.test_client().get('/api/v1/affiliate/' + endpoint, headers=headers(app))
        assert response.status_code == 200 and response.get_json()[field]
        assert response.get_json()['payouts_enabled'] is False
        assert response.get_json()['verification'] == 'unverified_legacy'
    with app.app_context():
        assert legacy_state() == before


def test_missing_settings_get_and_put_do_not_create_defaults(affiliate_boundary_app):
    app = affiliate_boundary_app
    with app.app_context():
        db.session.query(AffiliateSettings).delete()
        db.session.commit()
    for method in ('get', 'put'):
        response = getattr(app.test_client(), method)('/api/v1/affiliate/admin/settings', json={} if method == 'put' else None, headers=headers(app, 1))
        assert response.status_code == 404
    with app.app_context():
        assert db.session.query(AffiliateSettings).count() == 0


def test_affiliate_code_collision_has_five_attempt_budget(affiliate_boundary_app, monkeypatch):
    import src.routes.affiliate as routes
    app = affiliate_boundary_app
    with app.app_context():
        before = db.session.query(AffiliateLink).count()
        db.session.add(AffiliateLink(user_id=2, code='AAAAAAAA'))
        db.session.commit()
        choices = []
        def collision(alphabet):
            choices.append(1)
            return 'A'
        monkeypatch.setattr(routes.secrets, 'choice', collision)
        with pytest.raises(RuntimeError, match='allocation unavailable'):
            routes.generate_affiliate_code()
        assert len(choices) == 5 * 8
        assert db.session.query(AffiliateLink).count() == before + 1


def test_global_program_settings_require_configured_platform_owner(affiliate_boundary_app):
    app = affiliate_boundary_app
    app.config['EXPANDED_HIERARCHY_ENABLED'] = True
    with app.app_context():
        db.session.add(User(id=5, email='foreign-admin@example.invalid', password_hash='not-a-credential',
                            first_name='Synthetic', last_name='Foreign Admin', tenant_id=2, role='master',
                            is_active=True, is_verified=True, parent_id=1, tree_path='1/5', level=1))
        db.session.commit()
        token = db.session.get(User, 5).generate_access_token()
        before = legacy_state()
    for method in ('get', 'put'):
        response = getattr(app.test_client(), method)('/api/v1/affiliate/admin/settings',
            json={'default_commission_rate': 99} if method == 'put' else None,
            headers={'Authorization': 'Bearer ' + token})
        assert response.status_code == 403 and response.get_json()['error'] == 'Platform owner access required'
    with app.app_context():
        assert legacy_state() == before


@pytest.mark.parametrize('constant', ['NaN', 'Infinity', '-Infinity'])
def test_global_settings_nonfinite_json_is_not_committed(affiliate_boundary_app, constant):
    app = affiliate_boundary_app
    with app.app_context():
        before = legacy_state()
    response = app.test_client().put('/api/v1/affiliate/admin/settings',
        data='{"default_commission_rate":' + constant + '}', content_type='application/json', headers=headers(app, 1))
    assert response.status_code == 400
    with app.app_context():
        assert legacy_state() == before
