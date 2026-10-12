"""Focused regressions for the bounded, read-only legacy wallet boundary."""
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import JSON, event

from src.database import db
from src.models.agent import Agent
from src.models.tenant import Tenant
from src.models.token_blacklist import TokenBlacklist
from src.models.trading_program import Challenge, TradingProgram
from src.models.user import User
from src.models.wallet import Transaction, Wallet
from src.models.withdrawal import Withdrawal
from src.services.notification_service import NotificationService
from src.services.wallet_service import (
    WalletLedgerNotConfigured,
    WalletNotFound,
    WalletService,
)


def _make_app(*, expanded_hierarchy):
    from src.app import create_app

    app = create_app('testing', config_overrides={
        'EXPANDED_HIERARCHY_ENABLED': expanded_hierarchy,
        'PLATFORM_ROOT_USER_ID': 1,
        'PROPAGATE_EXCEPTIONS': False,
    })
    tables = [
        Tenant.__table__, User.__table__, TokenBlacklist.__table__, Wallet.__table__,
        Transaction.__table__, Agent.__table__, TradingProgram.__table__, Challenge.__table__,
        Withdrawal.__table__,
    ]
    # Only this isolated SQLite fixture renders PostgreSQL JSONB as portable JSON.
    # Every affected metadata column is restored after the fixture drops its rows.
    portable_column_types = [
        (Tenant.__table__.c.settings, Tenant.__table__.c.settings.type),
        (TradingProgram.__table__.c.rules, TradingProgram.__table__.c.rules.type),
        (Challenge.__table__.c.addons, Challenge.__table__.c.addons.type),
        (Challenge.__table__.c.daily_drawdown_history, Challenge.__table__.c.daily_drawdown_history.type),
    ]
    with app.app_context():
        if db.engine.dialect.name == 'sqlite':
            for column, _original_type in portable_column_types:
                column.type = JSON()
        db.metadata.create_all(bind=db.engine, tables=tables)
        db.session.add_all([
            Tenant(id=1, name='Synthetic Wallet Brand', subdomain='wallet-brand', status='active'),
            Tenant(id=2, name='Other Synthetic Brand', subdomain='other-wallet-brand', status='active'),
            User(
                id=1, email='wallet-root@example.invalid', password_hash='not-a-credential',
                first_name='Synthetic', last_name='Root', tenant_id=1, role='supermaster',
                is_active=True, is_verified=True, can_create_same_role=True,
                parent_id=None, tree_path='1', level=0,
            ),
            User(
                id=2, email='wallet-admin@example.invalid', password_hash='not-a-credential',
                first_name='Synthetic', last_name='Admin', tenant_id=1, role='master',
                is_active=True, is_verified=True, can_create_same_role=False,
                parent_id=1, tree_path='1/2', level=1,
            ),
            User(
                id=3, email='wallet-descendant@example.invalid', password_hash='not-a-credential',
                first_name='Synthetic', last_name='Descendant', tenant_id=1, role='trader',
                is_active=True, is_verified=True, can_create_same_role=False,
                parent_id=2, tree_path='1/2/3', level=2,
            ),
            User(
                id=4, email='wallet-foreign@example.invalid', password_hash='not-a-credential',
                first_name='Synthetic', last_name='Foreign', tenant_id=2, role='trader',
                is_active=True, is_verified=True, can_create_same_role=False,
                parent_id=None, tree_path='4', level=0,
            ),
        ])
        db.session.commit()
        app.wallet_tokens = {
            identity: db.session.get(User, identity).generate_access_token()
            for identity in (1, 2, 3, 4)
        }
    return app, tables, portable_column_types


@pytest.fixture
def wallet_boundary_app():
    """Launch-mode factory: canonical root/tenant configuration is real."""
    app, tables, portable_column_types = _make_app(expanded_hierarchy=False)
    yield app
    with app.app_context():
        db.session.remove()
        db.metadata.drop_all(bind=db.engine, tables=list(reversed(tables)))
        for column, original_type in portable_column_types:
            column.type = original_type


@pytest.fixture
def scoped_wallet_boundary_app():
    """Expanded hierarchy factory solely for tenant/hierarchy list proof."""
    app, tables, portable_column_types = _make_app(expanded_hierarchy=True)
    yield app
    with app.app_context():
        db.session.remove()
        db.metadata.drop_all(bind=db.engine, tables=list(reversed(tables)))
        for column, original_type in portable_column_types:
            column.type = original_type


def _headers(app, actor=1):
    return {'Authorization': 'Bearer ' + app.wallet_tokens[actor]}


def _seed_wallet(user_id, main='12.34', commission='5.66', bonus='1.00'):
    wallet = Wallet(
        user_id=user_id,
        main_balance=Decimal(main),
        commission_balance=Decimal(commission),
        bonus_balance=Decimal(bonus),
    )
    db.session.add(wallet)
    db.session.commit()
    return wallet


def _counts():
    return {
        'wallets': db.session.query(Wallet).count(),
        'transactions': db.session.query(Transaction).count(),
        'withdrawals': db.session.query(Withdrawal).count(),
    }


def test_wallet_boundary_missing_read_is_404_unverified_and_never_inserts(wallet_boundary_app):
    writes = []

    def observe_write(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(statement)

    with wallet_boundary_app.app_context():
        before = _counts()
        event.listen(db.engine, 'before_cursor_execute', observe_write)
        try:
            response = wallet_boundary_app.test_client().get('/api/v1/wallet/balance', headers=_headers(wallet_boundary_app))
        finally:
            event.remove(db.engine, 'before_cursor_execute', observe_write)
        assert response.status_code == 404
        assert response.get_json() == {
            'error': 'Wallet not found',
            'code': 'WALLET_NOT_FOUND',
            'reason': 'unverified_legacy',
        }
        assert _counts() == before == {'wallets': 0, 'transactions': 0, 'withdrawals': 0}
        assert writes == []


def test_wallet_boundary_existing_decimal_read_and_history_are_bounded_stable_and_unverified(wallet_boundary_app):
    with wallet_boundary_app.app_context():
        wallet = _seed_wallet(1)
        instant = datetime(2026, 10, 11, 12, 0, 0)
        db.session.add_all([
            Transaction(
                wallet_id=wallet.id, type='deposit', amount=Decimal('1.00'), balance_type='main',
                balance_before=Decimal('11.34'), balance_after=Decimal('12.34'), created_at=instant,
            ),
            Transaction(
                wallet_id=wallet.id, type='commission', amount=Decimal('5.66'), balance_type='commission',
                balance_before=Decimal('0.00'), balance_after=Decimal('5.66'), created_at=instant,
            ),
        ])
        db.session.commit()

        assert WalletService.get_balance(1, 'main') == Decimal('12.34')
        assert WalletService.get_balance(1, 'commission') == Decimal('5.66')
        assert WalletService.get_balance(1, 'total') == Decimal('18.00')
        history = WalletService.get_transaction_history(1, limit=2, offset=0)
        assert [entry.id for entry in history] == sorted((entry.id for entry in history), reverse=True)

        response = wallet_boundary_app.test_client().get('/api/v1/wallet/transactions?per_page=1', headers=_headers(wallet_boundary_app))
        assert response.status_code == 200
        payload = response.get_json()
        assert payload['balance_verification'] == 'unverified_legacy'
        assert payload['owner_context'] == {'user_id': 1, 'tenant_id': 1}
        assert payload['payouts_enabled'] is False
        assert payload['available_for_payout'] is None and payload['currency'] is None
        assert payload['pagination'] == {'page': 1, 'per_page': 1, 'total': 2, 'pages': 2}
        assert payload['filters'] == {'balance_type': None}
        assert payload['transactions'][0]['amount'] == '5.66'
        assert payload['transactions'][0]['id'] == history[0].id


@pytest.mark.parametrize('limit,offset,balance_type', [
    (True, 0, None), (0, 0, None), (101, 0, None), (1, True, None),
    (1, -1, None), (1, 10_001, None), (1, 0, True), (1, 0, 'total'),
])
def test_wallet_boundary_service_history_validation_happens_before_lookup(wallet_boundary_app, monkeypatch, limit, offset, balance_type):
    with wallet_boundary_app.app_context():
        def unexpected_lookup(*args, **kwargs):
            raise AssertionError('wallet lookup must not happen for invalid history input')

        monkeypatch.setattr(WalletService, 'get_or_create_wallet', unexpected_lookup)
        with pytest.raises(ValueError):
            WalletService.get_transaction_history(1, limit=limit, offset=offset, balance_type=balance_type)


@pytest.mark.parametrize('query', [
    '?page=true', '?page=-1', '?page=1.0', '?page=10000000000', '?per_page=0',
    '?per_page=101', '?per_page=true', '?page=2&per_page=10000', '?balance_type=total',
    '?page=1&page=2',
])
def test_wallet_boundary_malformed_history_request_is_400_before_wallet_io(wallet_boundary_app, monkeypatch, query):
    with wallet_boundary_app.app_context():
        def unexpected_history(*args, **kwargs):
            raise AssertionError('history service must not be called for malformed pagination')

        monkeypatch.setattr(WalletService, 'get_transaction_history', unexpected_history)
        response = wallet_boundary_app.test_client().get('/api/v1/wallet/transactions' + query, headers=_headers(wallet_boundary_app))
        assert response.status_code == 400
        assert response.get_json() == {'error': 'Invalid wallet request'}


def test_wallet_boundary_direct_mutators_and_model_gate_refuse_before_session_use(wallet_boundary_app, monkeypatch):
    with wallet_boundary_app.app_context():
        wallet = _seed_wallet(1)
        before = _counts()

        def sql_forbidden(*args, **kwargs):
            raise AssertionError('a legacy wallet mutator must not call the session')

        monkeypatch.setattr(db.session, 'query', sql_forbidden)
        monkeypatch.setattr(db.session, 'add', sql_forbidden)
        monkeypatch.setattr(db.session, 'commit', sql_forbidden)
        for method, args in [
            (WalletService.add_funds, (1, -999)),
            (WalletService.deduct_funds, (1, -999)),
            (WalletService.transfer_funds, (1, 2, -999)),
            (WalletService.adjust_balance, (1, -999)),
            # Parent-owned model gate: even an invalid legacy amount must fail
            # before row lock/query arithmetic.
            (wallet.add_funds, (-999,)),
            (wallet.deduct_funds, (-999,)),
        ]:
            with pytest.raises(WalletLedgerNotConfigured) as caught:
                method(*args)
            assert caught.value.code == 'WALLET_LEDGER_NOT_CONFIGURED'
            assert caught.value.status == 503
        # The captured rows were inserted before the session canary was armed.
        assert before == {'wallets': 1, 'transactions': 0, 'withdrawals': 0}


def test_wallet_boundary_authenticated_mutators_are_503_before_body_lookup_or_notification(wallet_boundary_app, monkeypatch):
    with wallet_boundary_app.app_context():
        before = _counts()
        notifications = []

        def notification_forbidden(*args, **kwargs):
            notifications.append((args, kwargs))
            raise AssertionError('legacy withdrawal route must not notify')

        monkeypatch.setattr(NotificationService, 'create_notification', notification_forbidden)
        client = wallet_boundary_app.test_client()
        for path in [
            '/api/v1/wallet/admin/adjust',
            '/api/v1/wallet/admin/withdrawals/999/approve',
            '/api/v1/wallet/admin/withdrawals/999/reject',
            '/api/v1/wallet/admin/withdrawals/999/complete',
        ]:
            # Invalid JSON proves the fixed ledger refusal is before body parsing.
            response = client.post(path, data='{', content_type='application/json', headers=_headers(wallet_boundary_app))
            assert response.status_code == 503
            assert response.get_json() == {
                'error': 'Wallet ledger is not configured',
                'code': 'WALLET_LEDGER_NOT_CONFIGURED',
            }
        assert _counts() == before
        assert notifications == []


def test_wallet_boundary_missing_wallet_service_never_returns_or_creates_zero(wallet_boundary_app):
    with wallet_boundary_app.app_context():
        with pytest.raises(WalletNotFound) as caught:
            WalletService.get_or_create_wallet(1)
        assert caught.value.code == 'WALLET_NOT_FOUND' and caught.value.status == 404
        with pytest.raises(WalletNotFound):
            WalletService.get_balance(1, 'main')
        assert _counts()['wallets'] == 0


def test_wallet_boundary_read_does_not_autoflush_unrelated_pending_legacy_state(wallet_boundary_app):
    with wallet_boundary_app.app_context():
        _seed_wallet(1)
        pending = Wallet(
            user_id=2,
            main_balance=Decimal('999.99'),
            commission_balance=Decimal('0.00'),
            bonus_balance=Decimal('0.00'),
        )
        db.session.add(pending)
        writes = []

        def observe_write(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
                writes.append(statement)

        event.listen(db.engine, 'before_cursor_execute', observe_write)
        try:
            assert WalletService.get_balance(1, 'main') == Decimal('12.34')
            assert WalletService.get_transaction_history(1, limit=1) == []
        finally:
            event.remove(db.engine, 'before_cursor_execute', observe_write)
            db.session.rollback()
        assert pending.id is None
        assert writes == []


def test_wallet_boundary_admin_wallet_scope_uses_tenant_hierarchy_owner_set(scoped_wallet_boundary_app):
    with scoped_wallet_boundary_app.app_context():
        _seed_wallet(2, main='2.00')
        _seed_wallet(3, main='3.00')
        _seed_wallet(4, main='4.00')
        response = scoped_wallet_boundary_app.test_client().get(
            '/api/v1/wallet/admin/wallets', headers=_headers(scoped_wallet_boundary_app, actor=2),
        )
        assert response.status_code == 200
        payload = response.get_json()
        assert payload['balance_verification'] == 'unverified_legacy'
        assert payload['owner_context'] == {'user_id': 2, 'tenant_id': 1}
        assert payload['payouts_enabled'] is False
        assert {item['user_id'] for item in payload['wallets']} == {2, 3}
        assert all('user' not in item and 'total_balance' not in item for item in payload['wallets'])
        assert payload['pagination']['total'] == 2


def test_wallet_boundary_withdrawal_scope_allows_only_unambiguous_direct_or_agent_owner(scoped_wallet_boundary_app):
    with scoped_wallet_boundary_app.app_context():
        agent_descendant = Agent(id=31, agent_code='SYNTH031', user_id=3)
        agent_foreign = Agent(id=41, agent_code='SYNTH041', user_id=4)
        db.session.add_all([agent_descendant, agent_foreign])
        db.session.flush()
        db.session.add_all([
            Withdrawal(id=101, user_id=2, amount=Decimal('10.00'), fee=Decimal('0.00'), net_amount=Decimal('10.00'), payment_method='synthetic'),
            Withdrawal(id=102, agent_id=31, amount=Decimal('11.00'), fee=Decimal('0.00'), net_amount=Decimal('11.00'), payment_method='synthetic'),
            # Actor direct-owner plus foreign agent is ambiguous and must not leak.
            Withdrawal(id=103, user_id=2, agent_id=41, amount=Decimal('12.00'), fee=Decimal('0.00'), net_amount=Decimal('12.00'), payment_method='synthetic'),
            Withdrawal(id=104, user_id=4, amount=Decimal('13.00'), fee=Decimal('0.00'), net_amount=Decimal('13.00'), payment_method='synthetic'),
        ])
        db.session.commit()
        response = scoped_wallet_boundary_app.test_client().get(
            '/api/v1/wallet/admin/withdrawals', headers=_headers(scoped_wallet_boundary_app, actor=2),
        )
        assert response.status_code == 200
        payload = response.get_json()
        assert payload['owner_context'] == {'user_id': 2, 'tenant_id': 1}
        assert {item['id'] for item in payload['withdrawals']} == {101, 102}
        assert all('user' not in item and 'transaction_id' not in item for item in payload['withdrawals'])


def test_wallet_boundary_auth_and_csrf_are_checked_before_ledger_refusal(wallet_boundary_app):
    endpoint = '/api/v1/wallet/admin/adjust'
    anonymous = wallet_boundary_app.test_client().post(endpoint, json={})
    assert anonymous.status_code == 401
    ordinary = wallet_boundary_app.test_client().post(endpoint, json={}, headers=_headers(wallet_boundary_app, actor=3))
    assert ordinary.status_code == 403
    assert ordinary.get_json()['error'] == 'Admin access required'
    cookie_client = wallet_boundary_app.test_client()
    cookie_client.set_cookie('access_token', wallet_boundary_app.wallet_tokens[1])
    cookie_response = cookie_client.post(endpoint, json={})
    assert cookie_response.status_code == 403
    assert cookie_response.get_json()['code'] == 'CSRF_INVALID'
    with wallet_boundary_app.app_context():
        assert _counts() == {'wallets': 0, 'transactions': 0, 'withdrawals': 0}
