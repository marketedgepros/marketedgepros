"""Payout refusal on runner-owned PostgreSQL/Redis; no provider or production."""
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import event, select


@pytest.fixture
def ui4_payout_pg_app(staging_resources, monkeypatch):
    from flask import Flask
    import redis
    import src.database as database_module
    from src.database import db
    from src.models.payout_request import PayoutRequest
    from src.models.user import User
    from src.routes.payouts import payouts_bp
    from src.utils.hierarchy_scoping import init_hierarchy_scoping

    app = Flask('ui4-payout-refusal-pg')
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI=staging_resources['pg_url'],
        SQLALCHEMY_TRACK_MODIFICATIONS=False, JWT_SECRET_KEY='synthetic-payout-pg',
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=10), JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=1),
        EXPANDED_HIERARCHY_ENABLED=True, PLATFORM_ROOT_USER_ID=1)
    db.init_app(app)
    init_hierarchy_scoping(db, User)
    app.register_blueprint(payouts_bp)
    client = redis.Redis(unix_socket_path=str(staging_resources['redis_socket']),
        decode_responses=True, socket_timeout=2, socket_connect_timeout=2)
    assert client.ping()
    monkeypatch.setattr(database_module, 'redis_client', client)
    # Shared autouse fixture owns parent tables. This test owns only this legacy table;
    # it asserts the refusal, not migration correctness (tested by migration rehearsal).
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=[PayoutRequest.__table__])
    try:
        yield app
    finally:
        with app.app_context():
            db.session.rollback()
            db.session.remove()
            db.metadata.drop_all(bind=db.engine, tables=[PayoutRequest.__table__])
        client.close()


def test_ui4_payout_postgresql_refusal_preserves_raw_rows_and_user_balances(ui4_payout_pg_app):
    from src.database import db
    from src.models.payout_request import PayoutRequest
    from src.models.tenant import Tenant
    from src.models.user import User
    from src.services.payout_service import PayoutService
    from src.services.wallet_service import WalletLedgerNotConfigured

    app = ui4_payout_pg_app
    with app.app_context():
        assert db.engine.dialect.name == 'postgresql'
        db.session.add(Tenant(id=1, name='Synthetic payout PG', subdomain='payout-pg'))
        db.session.add(User(id=1, email='payout-pg@example.invalid', password_hash='x', first_name='Synthetic',
            last_name='Root', tenant_id=1, role='supermaster', parent_id=None, tree_path='1', level=0,
            can_create_same_role=True, is_active=True, is_verified=True,
            available_balance=Decimal('999.99'), total_withdrawn=Decimal('88.88'), payout_count=7))
        db.session.flush()
        db.session.add(PayoutRequest(id=1, user_id=1, amount=Decimal('10.00'), profit_split_amount=Decimal('9.00'),
            status='approved', payout_mode='standard', payment_method='synthetic',
            payment_details={'private': 'not returned'}, notes='private'))
        db.session.commit()
        token = db.session.get(User, 1).generate_access_token()
        def snapshot():
            return {
                'payouts': [dict(row) for row in db.session.execute(select(PayoutRequest.__table__)).mappings()],
                'users': [dict(row) for row in db.session.execute(select(User.__table__)).mappings()],
            }
        before = snapshot()
        statements = []
        def observe(_conn, _cursor, statement, *_args):
            statements.append(statement.lower())
        event.listen(db.engine, 'before_cursor_execute', observe)
        try:
            client = app.test_client()
            for method, path in (
                ('GET', '/api/payouts'), ('GET', '/api/payouts/check-eligibility'),
                ('GET', '/api/payouts/1'), ('GET', '/api/payouts/my-statistics'),
                ('GET', '/api/payouts/my-payouts'), ('GET', '/api/payouts/admin/pending'),
                ('GET', '/api/payouts/admin/statistics'), ('POST', '/api/payouts/request'),
                ('POST', '/api/payouts/admin/1/approve'), ('POST', '/api/payouts/admin/1/reject'),
                ('POST', '/api/payouts/admin/1/mark-paid'),
            ):
                response = client.open(path, method=method, data='{', content_type='application/json',
                    headers={'Authorization': 'Bearer ' + token})
                assert response.status_code == 503
                assert response.get_json() == {'error': 'Wallet ledger is not configured',
                                               'code': 'WALLET_LEDGER_NOT_CONFIGURED'}
            for name, args in (
                ('can_request_payout', (object(), object())),
                ('request_payout', (object(), object(), Decimal('999'), 'ignored')),
                ('approve_payout', (1, 1)), ('reject_payout', (1, 1, 'ignored')),
                ('mark_as_paid', (1,)), ('get_user_payouts', (1,)),
                ('get_pending_payouts', ()), ('get_payout_statistics', ()),
            ):
                with pytest.raises(WalletLedgerNotConfigured):
                    getattr(PayoutService, name)(*args)
        finally:
            event.remove(db.engine, 'before_cursor_execute', observe)
        assert not any('payout_requests' in sql or 'trading_programs' in sql for sql in statements)
        assert not any(sql.lstrip().startswith(('insert', 'update', 'delete')) for sql in statements)
        db.session.expire_all()
        assert snapshot() == before
