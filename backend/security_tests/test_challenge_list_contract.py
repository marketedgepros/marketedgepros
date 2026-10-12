"""Contract regressions for the owner-only legacy challenge list.

These tests exercise the full Flask route with real JWT authentication and a
small SQLite schema.  No provider is mocked into producing data: attempting to
consult one is a failure because this route reports only local legacy rows.
"""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles


LIST_PATH = '/api/v1/challenges/my-challenges'


@pytest.fixture(scope='session', autouse=True)
def sqlite_jsonb_compiler():
    """Render PostgreSQL JSONB fixture columns as SQLite JSON only in tests."""
    @compiles(JSONB, 'sqlite')
    def compile_jsonb(_element, _compiler, **_kwargs):
        return 'JSON'


@pytest.fixture
def application(sqlite_jsonb_compiler):
    """Create the real app with only tables required by this route and JWT."""
    from src.app import create_app
    from src.database import db
    from src.models.tenant import Tenant
    from src.models.token_blacklist import TokenBlacklist
    from src.models.trading_program import Challenge, TradingProgram
    from src.models.user import User

    app = create_app(
        'testing',
        config_overrides={
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'JWT_ACCESS_TOKEN_EXPIRES': timedelta(hours=1),
            # The endpoint itself supplies the explicit owner/tenant predicate;
            # expanded mode also avoids unrelated launch-brand middleware I/O.
            'EXPANDED_HIERARCHY_ENABLED': True,
            'PLATFORM_ROOT_USER_ID': 1,
            'RATELIMIT_ENABLED': False,
            'PROPAGATE_EXCEPTIONS': False,
        },
    )
    tables = [
        Tenant.__table__, User.__table__, TokenBlacklist.__table__,
        TradingProgram.__table__, Challenge.__table__,
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
def challenge_data(application):
    """Persist same-owner, peer, root, and cross-tenant legacy challenge rows."""
    from src.database import db
    from src.models.tenant import Tenant
    from src.models.trading_program import Challenge, TradingProgram
    from src.models.user import User

    def user(email, role, tenant_id, *, active=True):
        return User(
            email=email,
            password_hash='test-only-password-hash',
            first_name=email.split('@')[0],
            last_name='List',
            role=role,
            is_active=active,
            is_verified=True,
            tenant_id=tenant_id,
        )

    instant = datetime(2026, 10, 11, 12, 0, 0)
    with application.app_context():
        tenant = Tenant(name='Challenge List Brand', subdomain='challenge-list-brand')
        foreign_tenant = Tenant(name='Foreign Challenge List Brand', subdomain='foreign-challenge-list-brand')
        db.session.add_all([tenant, foreign_tenant])
        db.session.flush()

        root = user('root@challenge-list.test', 'supermaster', tenant.id)
        owner = user('owner@challenge-list.test', 'trader', tenant.id)
        peer = user('peer@challenge-list.test', 'trader', tenant.id)
        inactive = user('inactive@challenge-list.test', 'trader', tenant.id)
        foreign = user('foreign@challenge-list.test', 'trader', foreign_tenant.id)
        db.session.add_all([root, owner, peer, inactive, foreign])
        db.session.flush()
        root.tree_path = str(root.id)
        owner.tree_path = str(owner.id)
        peer.tree_path = str(peer.id)
        inactive.tree_path = str(inactive.id)
        foreign.tree_path = str(foreign.id)
        application.config['PLATFORM_ROOT_USER_ID'] = root.id

        program = TradingProgram(
            tenant_id=tenant.id,
            name='Owner program',
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

        root_challenge = Challenge(
            user_id=root.id,
            program_id=program.id,
            status='active',
            initial_balance=Decimal('100.00'),
            current_balance=Decimal('100.00'),
            created_at=instant,
        )
        owner_zero_null = Challenge(
            user_id=owner.id,
            program_id=program.id,
            status='active',
            initial_balance=None,
            current_balance=Decimal('0.00'),
            max_drawdown=Decimal('0.00'),
            created_at=instant + timedelta(minutes=1),
        )
        peer_challenge = Challenge(
            user_id=peer.id,
            program_id=program.id,
            status='active',
            initial_balance=Decimal('300.00'),
            current_balance=Decimal('300.00'),
            created_at=instant + timedelta(minutes=2),
        )
        owner_foreign_program = Challenge(
            user_id=owner.id,
            program_id=foreign_program.id,
            status='active',
            initial_balance=Decimal('400.00'),
            current_balance=Decimal('400.00'),
            created_at=instant + timedelta(minutes=3),
        )
        db.session.add_all([
            root_challenge, owner_zero_null, peer_challenge, owner_foreign_program,
        ])
        bulk_challenges = []
        for index in range(20):
            bulk_challenge = Challenge(
                user_id=owner.id,
                program_id=program.id,
                status='bulk',
                initial_balance=Decimal('1000.00'),
                current_balance=Decimal('1000.00'),
                created_at=instant + timedelta(minutes=10 + index),
            )
            bulk_challenges.append(bulk_challenge)
        db.session.add_all(bulk_challenges)
        db.session.commit()

        users = {'root': root, 'owner': owner, 'peer': peer, 'inactive': inactive, 'foreign': foreign}
        tokens = {name: actor.generate_access_token() for name, actor in users.items()}
        return {
            'headers': {name: {'Authorization': f'Bearer {token}'} for name, token in tokens.items()},
            'ids': {
                'root': root.id,
                'owner': owner.id,
                'peer': peer.id,
                'owner_zero_null': owner_zero_null.id,
                'root_challenge': root_challenge.id,
                'peer_challenge': peer_challenge.id,
                'owner_foreign_program': owner_foreign_program.id,
                'bulk': [challenge.id for challenge in bulk_challenges],
                'program': program.id,
            },
        }


def test_my_challenge_list_is_owner_only_tenant_safe_and_preserves_null_and_zero(application, challenge_data):
    """Neither a same-tenant peer nor a configured global root can list another owner."""
    client = application.test_client()
    owner = client.get(LIST_PATH + '?status=active', headers=challenge_data['headers']['owner'])
    assert owner.status_code == 200
    payload = owner.get_json()
    assert set(payload) == {'challenges', 'pagination', 'owner_context', 'data_status', 'provider_authenticated'}
    assert payload['owner_context']['user_id'] == challenge_data['ids']['owner']
    with application.app_context():
        from src.database import db
        from src.models.user import User
        assert payload['owner_context']['tenant_id'] == db.session.get(User, challenge_data['ids']['owner']).tenant_id
    assert payload['data_status'] == 'unverified_legacy'
    assert payload['provider_authenticated'] is False
    assert payload['pagination'] == {'page': 1, 'per_page': 20, 'total': 1, 'pages': 1}
    assert [challenge['id'] for challenge in payload['challenges']] == [challenge_data['ids']['owner_zero_null']]
    projection = payload['challenges'][0]
    assert projection['user_id'] == challenge_data['ids']['owner']
    assert projection['program'] == {'id': challenge_data['ids']['program'], 'name': 'Owner program'}
    assert projection['initial_balance'] is None
    assert projection['current_balance'] == '0.00'
    assert projection['max_drawdown_observed'] == '0.00'
    assert projection['data_status'] == 'unverified_legacy'
    assert projection['provider_authenticated'] is False
    assert 'user' not in projection and 'mt5_account' not in projection

    # Root/admin role never changes this personal list's explicit owner predicate.
    root = client.get(LIST_PATH, headers=challenge_data['headers']['root'])
    assert root.status_code == 200
    assert [challenge['id'] for challenge in root.get_json()['challenges']] == [challenge_data['ids']['root_challenge']]

    peer = client.get(LIST_PATH, headers=challenge_data['headers']['peer'])
    assert peer.status_code == 200
    assert [challenge['id'] for challenge in peer.get_json()['challenges']] == [challenge_data['ids']['peer_challenge']]

    # The owner has a malformed cross-tenant program binding; it must be absent.
    all_owner_ids = {challenge['id'] for challenge in client.get(LIST_PATH, headers=challenge_data['headers']['owner']).get_json()['challenges']}
    assert challenge_data['ids']['owner_foreign_program'] not in all_owner_ids
    assert challenge_data['ids']['root_challenge'] not in all_owner_ids
    assert challenge_data['ids']['peer_challenge'] not in all_owner_ids


def test_my_challenge_list_pagination_filter_and_query_validation(application, challenge_data):
    """Pagination is bounded and ordering is created_at/id descending without an open query surface."""
    client = application.test_client()
    headers = challenge_data['headers']['owner']

    first = client.get(LIST_PATH + '?status=bulk&per_page=2&page=1', headers=headers)
    second = client.get(LIST_PATH + '?status=bulk&per_page=2&page=2', headers=headers)
    assert first.status_code == second.status_code == 200
    assert first.get_json()['pagination'] == {'page': 1, 'per_page': 2, 'total': 20, 'pages': 10}
    assert second.get_json()['pagination'] == {'page': 2, 'per_page': 2, 'total': 20, 'pages': 10}
    assert [row['id'] for row in first.get_json()['challenges']] == challenge_data['ids']['bulk'][-1:-3:-1]
    assert [row['id'] for row in second.get_json()['challenges']] == challenge_data['ids']['bulk'][-3:-5:-1]

    for query, code in [
        ('?page=0', 'PAGINATION_INVALID'),
        ('?page=1001', 'PAGINATION_INVALID'),
        ('?page=01', 'PAGINATION_INVALID'),
        ('?per_page=0', 'PAGINATION_INVALID'),
        ('?per_page=101', 'PAGINATION_INVALID'),
        ('?page=1&page=2', 'QUERY_INVALID'),
        ('?status=active&status=bulk', 'QUERY_INVALID'),
        ('?include_mt5=true', 'QUERY_INVALID'),
        ('?unexpected=value', 'QUERY_INVALID'),
        ('?status=' + ('x' * 21), 'QUERY_INVALID'),
    ]:
        response = client.get(LIST_PATH + query, headers=headers)
        assert response.status_code == 400
        assert response.get_json()['code'] == code


def test_my_challenge_list_requires_an_active_authenticated_owner(application, challenge_data):
    """Anonymous and inactive principals are rejected by the real JWT decorator."""
    client = application.test_client()
    assert client.get(LIST_PATH).status_code == 401

    from src.database import db
    from src.models.user import User
    with application.app_context():
        inactive = db.session.get(User, challenge_data['ids']['owner'])
        inactive.is_active = False
        db.session.commit()
    response = client.get(LIST_PATH, headers=challenge_data['headers']['owner'])
    assert response.status_code == 401


class _ForbiddenProvider:
    """Fail if the list route even attempts to inspect a provider service."""
    def __getattr__(self, name):
        raise AssertionError(f'provider access is forbidden: {name}')


def test_my_challenge_list_is_no_autoflush_no_dml_and_never_touches_provider(application, challenge_data, monkeypatch):
    """The legacy snapshot list neither flushes unrelated state nor calls MT5 code."""
    from src.database import db
    from src.models.trading_program import Challenge
    from src.routes import challenges as challenge_routes

    # Provider globals were removed; retain canaries without re-importing a provider.
    monkeypatch.setattr(challenge_routes, 'mt5_service', _ForbiddenProvider(), raising=False)
    monkeypatch.setattr(challenge_routes, 'mt5_challenge_service', _ForbiddenProvider(), raising=False)
    writes = []

    def observe_write(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(statement)

    with application.app_context():
        pending = Challenge(
            user_id=challenge_data['ids']['owner'],
            program_id=challenge_data['ids']['program'],
            status='pending',
        )
        db.session.add(pending)
        event.listen(db.engine, 'before_cursor_execute', observe_write)
        try:
            response = application.test_client().get(LIST_PATH, headers=challenge_data['headers']['owner'])
        finally:
            event.remove(db.engine, 'before_cursor_execute', observe_write)
            db.session.rollback()
    assert response.status_code == 200
    assert pending.id is None
    assert writes == []


def test_my_challenge_list_uses_constant_selects_for_one_or_twenty_rows(application, challenge_data):
    """Projection from the joined program row prevents per-challenge SQL queries."""
    from src.database import db

    def request_select_count(query):
        statements = []

        def record(_conn, _cursor, statement, _parameters, _context, _executemany):
            if statement.lstrip().lower().startswith('select'):
                statements.append(' '.join(statement.lower().split()))

        with application.app_context():
            db.session.remove()
            event.listen(db.engine, 'before_cursor_execute', record)
            try:
                response = application.test_client().get(
                    LIST_PATH + query, headers=challenge_data['headers']['owner'],
                )
            finally:
                event.remove(db.engine, 'before_cursor_execute', record)
                db.session.remove()
        assert response.status_code == 200
        return statements

    one_row = request_select_count('?status=bulk&per_page=1')
    twenty_rows = request_select_count('?status=bulk&per_page=20')
    assert len(one_row) == len(twenty_rows)
    # Auth principal + blacklist, then the bounded count and joined list query.
    assert len(twenty_rows) == 4
    assert all('mt5_accounts' not in statement for statement in twenty_rows)
    assert all('wallet' not in statement for statement in twenty_rows)
