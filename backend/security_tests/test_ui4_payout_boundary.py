"""Legacy payout API/service: real factory, synthetic rows, no financial I/O."""
from decimal import Decimal

import pytest
from sqlalchemy import JSON, event, select

from src.database import db
from src.models.payout_request import PayoutRequest
from src.models.tenant import Tenant
from src.models.token_blacklist import TokenBlacklist
from src.models.trading_program import TradingProgram
from src.models.user import User
from src.services.payout_service import PayoutService
from src.services.wallet_service import WalletLedgerNotConfigured

ENDPOINTS = (
    ('GET', '/api/payouts', False),
    ('GET', '/api/payouts/', False),
    ('GET', '/api/payouts/check-eligibility', False),
    ('POST', '/api/payouts/request', False),
    ('GET', '/api/payouts/my-payouts', False),
    ('GET', '/api/payouts/my-statistics', False),
    ('GET', '/api/payouts/999', False),
    ('GET', '/api/payouts/admin/pending', True),
    ('POST', '/api/payouts/admin/999/approve', True),
    ('POST', '/api/payouts/admin/999/reject', True),
    ('POST', '/api/payouts/admin/999/mark-paid', True),
    ('GET', '/api/payouts/admin/statistics', True),
)
DENIAL = {'error': 'Wallet ledger is not configured', 'code': 'WALLET_LEDGER_NOT_CONFIGURED'}
SERVICE_CALLS = (
    ('can_request_payout', (object(), object())),
    ('request_payout', (object(), object(), Decimal('-999.00'), 'invalid', {})),
    ('approve_payout', (-1, -1, 'ignored')),
    ('reject_payout', (-1, -1, 'ignored')),
    ('mark_as_paid', (-1, 'ignored')),
    ('get_user_payouts', (-1, 'invalid')),
    ('get_pending_payouts', ()),
    ('get_payout_statistics', ()),
)


@pytest.fixture
def ui4_payout_app():
    from src.app import create_app
    app = create_app('testing', config_overrides={
        'EXPANDED_HIERARCHY_ENABLED': True, 'PLATFORM_ROOT_USER_ID': 1,
        'PROPAGATE_EXCEPTIONS': False,
    })
    tables = [Tenant.__table__, User.__table__, TokenBlacklist.__table__,
              TradingProgram.__table__, PayoutRequest.__table__]
    original_type = Tenant.__table__.c.settings.type
    with app.app_context():
        Tenant.__table__.c.settings.type = JSON()
        db.metadata.create_all(bind=db.engine, tables=tables)
        db.session.add(Tenant(id=1, name='Synthetic payout tenant', subdomain='payout-test'))
        db.session.add_all([
            User(id=1, email='root@example.invalid', password_hash='not-a-credential',
                 first_name='Synthetic', last_name='Root', role='supermaster', tenant_id=1,
                 parent_id=None, tree_path='1', level=0, can_create_same_role=True,
                 is_active=True, is_verified=True),
            User(id=3, email='trader@example.invalid', password_hash='not-a-credential',
                 first_name='Synthetic', last_name='Trader', role='trader', tenant_id=1,
                 parent_id=1, tree_path='1/3', level=1, is_active=True, is_verified=True,
                 available_balance=Decimal('999.99'), total_withdrawn=Decimal('88.88'), payout_count=7),
        ])
        db.session.flush()
        db.session.add(PayoutRequest(id=999, user_id=3, amount=Decimal('50.00'),
                                    profit_split_amount=Decimal('45.00'), status='approved',
                                    payout_mode='standard', payment_method='synthetic',
                                    payment_details={'private': 'never returned'}, notes='private-note'))
        db.session.commit()
        app.payout_tokens = {i: db.session.get(User, i).generate_access_token() for i in (1, 3)}
    try:
        yield app
    finally:
        with app.app_context():
            db.session.remove()
            db.metadata.drop_all(bind=db.engine, tables=list(reversed(tables)))
            Tenant.__table__.c.settings.type = original_type


def _snapshot():
    return {
        'payouts': [dict(row) for row in db.session.execute(select(PayoutRequest.__table__)).mappings()],
        'users': [dict(row) for row in db.session.execute(select(User.__table__)).mappings()],
    }


@pytest.mark.parametrize('method,path,admin', ENDPOINTS)
def test_ui4_payout_routes_refuse_before_body_resource_sql_and_preserve_rows(ui4_payout_app, method, path, admin, monkeypatch):
    app = ui4_payout_app
    actor = 1 if admin else 3
    with app.app_context():
        before = _snapshot()
        statements = []
        def observe(_conn, _cursor, statement, *_args):
            statements.append(statement.lower())
        def forbidden(*_args, **_kwargs):
            raise AssertionError('Financial resource/service used by blocked route')
        monkeypatch.setattr(PayoutRequest, 'to_dict', forbidden)
        for name, _ in SERVICE_CALLS:
            monkeypatch.setattr(PayoutService, name, forbidden)
        event.listen(db.engine, 'before_cursor_execute', observe)
        try:
            response = app.test_client().open(path + '?untrusted=1', method=method,
                data='{', content_type='application/json',
                headers={'Authorization': 'Bearer ' + app.payout_tokens[actor]})
        finally:
            event.remove(db.engine, 'before_cursor_execute', observe)
        assert response.status_code == 503
        assert response.get_json() == DENIAL
        assert not any('payout_requests' in sql or 'trading_programs' in sql for sql in statements)
        assert not any(sql.lstrip().startswith(('insert', 'update', 'delete')) for sql in statements)
        db.session.expire_all()
        assert _snapshot() == before


@pytest.mark.parametrize('method,path,admin', ENDPOINTS)
def test_ui4_payout_routes_check_auth_and_admin_before_denial(ui4_payout_app, method, path, admin):
    app = ui4_payout_app
    assert app.test_client().open(path, method=method).status_code == 401
    response = app.test_client().open(path, method=method,
        headers={'Authorization': 'Bearer ' + app.payout_tokens[3]})
    assert response.status_code == (403 if admin else 503)


@pytest.mark.parametrize('path', [p for method, p, _ in ENDPOINTS if method == 'POST'])
def test_ui4_payout_cookie_csrf_is_required_before_refusal(ui4_payout_app, path):
    from src.middleware.csrf_middleware import generate_csrf_token
    app = ui4_payout_app
    actor = 1 if '/admin/' in path else 3
    token = app.payout_tokens[actor]
    client = app.test_client()
    client.set_cookie('access_token', token)
    response = client.post(path, json={})
    assert response.status_code == 403
    assert response.get_json()['code'] == 'CSRF_INVALID'
    with app.app_context():
        csrf = generate_csrf_token(token)
    client.set_cookie('csrf_token', csrf)
    response = client.post(path, data='{', content_type='application/json', headers={'X-CSRF-Token': csrf})
    assert response.status_code == 503 and response.get_json() == DENIAL


@pytest.mark.parametrize('name,args', SERVICE_CALLS)
def test_ui4_payout_internal_service_refuses_without_any_sql(ui4_payout_app, name, args, monkeypatch):
    with ui4_payout_app.app_context():
        before = _snapshot()
        def forbidden(*_args, **_kwargs):
            raise AssertionError('Blocked payout service touched session')
        with monkeypatch.context() as patch:
            for method in ('query', 'get', 'add', 'flush', 'execute', 'commit', 'rollback'):
                patch.setattr(db.session, method, forbidden)
            with pytest.raises(WalletLedgerNotConfigured) as caught:
                getattr(PayoutService, name)(*args)
        assert caught.value.code == DENIAL['code'] and caught.value.status == 503
        assert _snapshot() == before
