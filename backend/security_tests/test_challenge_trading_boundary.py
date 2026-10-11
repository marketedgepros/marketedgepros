"""Focused regressions for the Stage5a challenge/trading containment boundary.

The fixtures exercise real Flask blueprint registration, SQLite rows and signed
JWTs.  They intentionally use no provider mock as an invoked provider would be
a test failure: the boundary must refuse before any provider or resource lookup.
"""
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles


PROVIDER_CODE = 'MT5_PROVIDER_NOT_CONFIGURED'
EVIDENCE_CODE = 'TRADING_EVIDENCE_NOT_CONFIGURED'
AMBIGUOUS_CODE = 'MT5_ACCOUNT_BINDING_AMBIGUOUS'


@pytest.fixture(scope='session', autouse=True)
def sqlite_jsonb_compiler():
    @compiles(JSONB, 'sqlite')
    def compile_jsonb(_element, _compiler, **_kwargs):
        return 'JSON'


@pytest.fixture
def application(sqlite_jsonb_compiler):
    """Use the full application factory with only this boundary's tables."""
    from src.app import create_app
    from src.database import db
    from src.models.tenant import Tenant
    from src.models.token_blacklist import TokenBlacklist
    from src.models.trading_program import Challenge, TradingProgram
    from src.models.user import User
    from src.models.mt5_models import MT5Account

    app = create_app(
        'testing',
        config_overrides={
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'JWT_ACCESS_TOKEN_EXPIRES': timedelta(hours=1),
            # Start in actual single-brand launch mode; one test explicitly
            # enables the future hierarchy branch for CRM-scope coverage.
            'EXPANDED_HIERARCHY_ENABLED': False,
        },
    )
    tables = [
        Tenant.__table__, User.__table__, TokenBlacklist.__table__,
        TradingProgram.__table__, Challenge.__table__, MT5Account.__table__,
    ]
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=tables)
    try:
        yield app
    finally:
        with app.app_context():
            db.session.remove()
            db.metadata.drop_all(bind=db.engine, tables=list(reversed(tables)))
            db.engine.dispose()


@pytest.fixture
def actors(application):
    """Persist a valid MVP root plus two future master branches and two traders."""
    from src.database import db
    from src.models.tenant import Tenant
    from src.models.trading_program import Challenge, TradingProgram
    from src.models.user import User

    def user(email, role, tenant_id, parent_id=None, same_role=False):
        return User(
            email=email,
            password_hash='test-only-password-hash',
            first_name=email.split('@')[0],
            last_name='Boundary',
            role=role,
            is_active=True,
            is_verified=True,
            can_create_same_role=same_role,
            tenant_id=tenant_id,
            parent_id=parent_id,
        )

    with application.app_context():
        tenant = Tenant(name='Challenge Boundary Brand', subdomain='challenge-boundary-brand')
        foreign_tenant = Tenant(name='Foreign Challenge Brand', subdomain='challenge-boundary-foreign')
        db.session.add_all([tenant, foreign_tenant])
        db.session.flush()

        root = user('root@challenge.test', 'supermaster', tenant.id, same_role=True)
        db.session.add(root)
        db.session.flush()
        root.tree_path = str(root.id)
        application.config['PLATFORM_ROOT_USER_ID'] = root.id

        master_a = user('master-a@challenge.test', 'master', tenant.id, root.id)
        master_b = user('master-b@challenge.test', 'master', tenant.id, root.id)
        db.session.add_all([master_a, master_b])
        db.session.flush()
        master_a.tree_path = f'{root.id}/{master_a.id}'
        master_b.tree_path = f'{root.id}/{master_b.id}'

        trader_a = user('trader-a@challenge.test', 'trader', tenant.id, master_a.id)
        trader_b = user('trader-b@challenge.test', 'trader', tenant.id, master_b.id)
        db.session.add_all([trader_a, trader_b])
        db.session.flush()
        trader_a.tree_path = f'{master_a.tree_path}/{trader_a.id}'
        trader_b.tree_path = f'{master_b.tree_path}/{trader_b.id}'

        program = TradingProgram(
            tenant_id=tenant.id,
            name='Declared percentage program',
            type='one_phase',
            account_size=Decimal('10000.00'),
            profit_target=Decimal('10.00'),
            max_daily_loss=Decimal('5.00'),
            max_total_loss=Decimal('10.00'),
            price=Decimal('100.00'),
            is_active=True,
        )
        foreign_program = TradingProgram(
            tenant_id=foreign_tenant.id,
            name='Foreign program',
            type='one_phase',
            account_size=Decimal('20000.00'),
            profit_target=Decimal('8.00'),
            max_daily_loss=Decimal('4.00'),
            max_total_loss=Decimal('8.00'),
            price=Decimal('200.00'),
            is_active=True,
        )
        db.session.add_all([program, foreign_program])
        db.session.flush()

        challenge_a = Challenge(
            user_id=trader_a.id,
            program_id=program.id,
            status='active',
            payment_status='paid',
            initial_balance=Decimal('10000.00'),
            current_balance=Decimal('10125.50'),
            max_drawdown=Decimal('42.50'),
        )
        challenge_b = Challenge(
            user_id=trader_b.id,
            program_id=program.id,
            status='active',
            initial_balance=Decimal('5000.00'),
            current_balance=Decimal('5000.00'),
        )
        cross_tenant_program = Challenge(
            user_id=trader_a.id,
            program_id=foreign_program.id,
            status='active',
            initial_balance=Decimal('20000.00'),
            current_balance=Decimal('20000.00'),
        )
        db.session.add_all([challenge_a, challenge_b, cross_tenant_program])
        db.session.commit()

        return {
            'root_headers': {'Authorization': f'Bearer {root.generate_access_token()}'},
            'master_a_headers': {'Authorization': f'Bearer {master_a.generate_access_token()}'},
            'master_b_headers': {'Authorization': f'Bearer {master_b.generate_access_token()}'},
            'trader_a_headers': {'Authorization': f'Bearer {trader_a.generate_access_token()}'},
            'trader_b_headers': {'Authorization': f'Bearer {trader_b.generate_access_token()}'},
            'root_id': root.id,
            'trader_a_id': trader_a.id,
            'trader_b_id': trader_b.id,
            'challenge_a_id': challenge_a.id,
            'challenge_b_id': challenge_b.id,
            'cross_tenant_challenge_id': cross_tenant_program.id,
        }


def _assert_code(response, status, code):
    assert response.status_code == status
    assert response.get_json()['code'] == code


def test_mutators_are_authenticated_then_refused_without_challenge_writes(application, actors):
    """No body, ID or paid flag can mutate challenge evidence, funding or history."""
    from src.database import db
    from src.models.trading_program import Challenge

    client = application.test_client()
    challenge_id = actors['challenge_a_id']
    with application.app_context():
        before = db.session.query(Challenge).filter_by(id=challenge_id).one()
        snapshot = (before.status, before.current_balance, before.payment_status)

    assert client.post(f'/api/v1/challenges/{challenge_id}/evaluate').status_code == 401
    assert client.post(
        f'/api/v1/challenges/{challenge_id}/evaluate', headers=actors['trader_a_headers']
    ).status_code == 403

    for path, headers, code in (
        (f'/api/v1/challenges/{challenge_id}/evaluate', actors['root_headers'], EVIDENCE_CODE),
        (f'/api/v1/challenges/{challenge_id}/fund', actors['root_headers'], PROVIDER_CODE),
        (f'/api/v1/challenges/{challenge_id}/trades', actors['trader_a_headers'], EVIDENCE_CODE),
        (f'/api/v1/challenges/{challenge_id}/create-mt5-account', actors['trader_a_headers'], PROVIDER_CODE),
        (f'/api/v1/challenges/{challenge_id}/mt5-credentials', actors['trader_a_headers'], PROVIDER_CODE),
        (f'/api/v1/challenges/admin/{challenge_id}', actors['root_headers'], EVIDENCE_CODE),
    ):
        method_name = 'GET' if path.endswith('mt5-credentials') else (
            'DELETE' if '/admin/' in path else 'POST'
        )
        response = client.open(path, method=method_name, headers=headers, json={'forged': 'body'})
        _assert_code(response, 503, code)
        malformed = client.open(path, method=method_name, headers=headers,
                                data='{', content_type='application/json')
        _assert_code(malformed, 503, code)

    for path in ('/api/v1/challenges/', f'/api/v1/challenges/{challenge_id}/start'):
        _assert_code(client.post(path, headers=actors['trader_a_headers'], json={'program_id': 1}), 503,
                     'ORDER_SETTLEMENT_NOT_CONFIGURED')

    with application.app_context():
        after = db.session.query(Challenge).filter_by(id=challenge_id).one()
        assert (after.status, after.current_balance, after.payment_status) == snapshot


def test_progress_is_owner_only_and_never_uses_default_balance_or_rules(application, actors):
    """Progress is a labelled read-only legacy diagnostic, not a funding/risk decision."""
    from src.database import db
    from src.models.mt5_models import MT5Account

    with application.app_context():
        account = MT5Account(
            user_id=actors['trader_a_id'],
            challenge_id=actors['challenge_a_id'],
            mt5_login='legacy-empty-snapshot',
            mt5_password_encrypted='not-decrypted-by-this-route',
            balance=None,
            equity=None,
            margin=None,
            free_margin=None,
        )
        db.session.add(account)
        db.session.commit()
        # SQL defaults may materialize zero on insert; explicitly clear it to
        # prove a NULL snapshot stays unknown in the response.
        account.balance = None
        db.session.commit()

    client = application.test_client()
    response = client.get(
        f"/api/v1/challenges/{actors['challenge_a_id']}/progress",
        headers=actors['trader_a_headers'],
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body['data_status'] == 'unverified_legacy'
    assert body['provider_authenticated'] is False
    assert body['challenge']['legacy_payment_status'] == 'paid'
    assert body['challenge']['initial_balance'] == '10000.00'
    assert body['progress']['profit_loss'] == '125.50'
    assert body['progress']['trading_days'] is None
    assert body['progress']['min_trading_days'] is None
    assert body['mt5_account']['balance'] is None
    assert body['mt5_account']['provider_authenticated'] is False

    foreign = client.get(
        f"/api/v1/challenges/{actors['challenge_b_id']}/progress",
        headers=actors['trader_a_headers'],
    )
    _assert_code(foreign, 404, 'CHALLENGE_NOT_FOUND')


def test_admin_listing_is_bounded_read_only_and_hides_bad_bindings(application, actors):
    """The actual configured root can list only tenant-consistent, non-corrupt rows."""
    from src.database import db
    from src.models.mt5_models import MT5Account

    with application.app_context():
        # A linked account owned by someone else makes the challenge fail closed.
        db.session.add(MT5Account(
            user_id=actors['trader_a_id'],
            challenge_id=actors['challenge_b_id'],
            mt5_login='foreign-owner-binding',
            mt5_password_encrypted='not-decrypted-by-this-route',
        ))
        db.session.commit()

    client = application.test_client()
    response = client.get('/api/v1/challenges/admin/all?page=1&per_page=100&include_mt5=true',
                          headers=actors['root_headers'])
    assert response.status_code == 200
    body = response.get_json()
    ids = {item['id'] for item in body['challenges']}
    assert actors['challenge_a_id'] in ids
    assert actors['challenge_b_id'] not in ids
    assert actors['cross_tenant_challenge_id'] not in ids
    item = next(item for item in body['challenges'] if item['id'] == actors['challenge_a_id'])
    assert item['data_status'] == 'unverified_legacy'
    assert item['provider_authenticated'] is False
    assert item['mt5_account'] is None
    assert item['mt5_account_binding'] == 'not_linked'

    for query, code in (
        ('page=0', 'PAGINATION_INVALID'),
        ('page=1001', 'PAGINATION_INVALID'),
        ('per_page=101', 'PAGINATION_INVALID'),
        ('page=1&page=2', 'QUERY_INVALID'),
        ('include_mt5=TRUE', 'QUERY_INVALID'),
        ('unexpected=x', 'QUERY_INVALID'),
        ('page=' + '9' * 5000, 'PAGINATION_INVALID'),
        ('per_page=' + '0' * 5000 + '1', 'PAGINATION_INVALID'),
        ('page=01', 'PAGINATION_INVALID'),
    ):
        _assert_code(client.get('/api/v1/challenges/admin/all?' + query, headers=actors['root_headers']), 400, code)


def test_future_master_is_limited_to_own_crm_branch(application, actors):
    """In the future hierarchy branch, a master cannot enumerate a sibling branch."""
    application.config['EXPANDED_HIERARCHY_ENABLED'] = True
    client = application.test_client()

    response = client.get('/api/v1/challenges/admin/all?include_mt5=false',
                          headers=actors['master_a_headers'])
    assert response.status_code == 200
    body = response.get_json()
    assert {item['id'] for item in body['challenges']} == {actors['challenge_a_id']}
    assert {item['user']['id'] for item in body['challenges']} == {actors['trader_a_id']}
