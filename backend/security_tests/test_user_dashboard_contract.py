"""Security contracts for the bounded, legacy-only user dashboard."""
from collections import Counter
from datetime import datetime, timedelta

import pytest
from flask import Flask
from sqlalchemy import event, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from src.database import db
from src.models.tenant import Tenant
from src.models.token_blacklist import TokenBlacklist
from src.models.trading_program import Challenge, TradingProgram
from src.models.user import User
from src.routes.users import users_bp


@compiles(JSONB, 'sqlite')
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    """Test-only SQLite type adapter; production PostgreSQL types are unchanged."""
    return 'JSON'


_TABLES = (
    Tenant.__table__, User.__table__, TradingProgram.__table__,
    Challenge.__table__, TokenBlacklist.__table__,
)


@pytest.fixture
def dashboard_app():
    """A neutral, in-memory Flask/JWT host with no provider or production calls."""
    app = Flask('user-dashboard-security')
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY='dashboard-contract-synthetic-key',
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=10),
        JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=1),
        EXPANDED_HIERARCHY_ENABLED=True,
    )
    db.init_app(app)
    app.register_blueprint(users_bp, url_prefix='/api/v1/users')

    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        tenant_a = Tenant(id=1, name='Dashboard Tenant A', subdomain='dashboard-a', status='active')
        tenant_b = Tenant(id=2, name='Dashboard Tenant B', subdomain='dashboard-b', status='active')
        owner = User(
            id=1, email='owner@dashboard.invalid', password_hash='x', first_name='Owner', last_name='A',
            role='trader', tenant_id=1, tree_path='1', level=0, is_active=True, is_verified=True,
        )
        same_tenant_other_user = User(
            id=2, email='other@dashboard.invalid', password_hash='x', first_name='Other', last_name='A',
            role='trader', tenant_id=1, tree_path='2', level=0, is_active=True, is_verified=True,
        )
        foreign_tenant_user = User(
            id=3, email='foreign@dashboard.invalid', password_hash='x', first_name='Foreign', last_name='B',
            role='trader', tenant_id=2, tree_path='3', level=0, is_active=True, is_verified=True,
        )
        program_a = TradingProgram(
            id=1, tenant_id=1, name='Tenant A Program', type='one_phase',
            account_size='1000.00', price='99.00', is_active=True,
        )
        program_b = TradingProgram(
            id=2, tenant_id=2, name='Tenant B Program', type='one_phase',
            account_size='1000.00', price='99.00', is_active=True,
        )
        db.session.add_all([
            tenant_a, tenant_b, owner, same_tenant_other_user, foreign_tenant_user, program_a, program_b,
        ])
        created = datetime(2026, 10, 1, 12, 0, 0)
        # Six owned Tenant-A challenge rows produce every recorded status count.
        # IDs 2-6 are the bounded recent result and cover zero, null, and loss values.
        db.session.add_all([
            Challenge(id=1, user_id=1, program_id=1, status='active', current_phase=1, total_phases=1,
                      initial_balance='1000.00', current_balance='1050.00', created_at=created),
            Challenge(id=2, user_id=1, program_id=1, status='passed', current_phase=1, total_phases=1,
                      initial_balance='1000.00', current_balance='1000.00', created_at=created + timedelta(minutes=1)),
            Challenge(id=3, user_id=1, program_id=1, status='failed', current_phase=1, total_phases=1,
                      initial_balance='1000.00', current_balance=None, created_at=created + timedelta(minutes=2)),
            Challenge(id=4, user_id=1, program_id=1, status='funded', current_phase=1, total_phases=1,
                      initial_balance=None, current_balance='1100.00', created_at=created + timedelta(minutes=3)),
            Challenge(id=5, user_id=1, program_id=1, status='pending', current_phase=1, total_phases=1,
                      initial_balance='1000.00', current_balance='900.00', created_at=created + timedelta(minutes=4)),
            Challenge(id=6, user_id=1, program_id=1, status='active', current_phase=1, total_phases=1,
                      initial_balance='1000.00', current_balance='950.00', created_at=created + timedelta(minutes=5)),
            # These must not be visible in the owner's aggregate or recent list.
            Challenge(id=7, user_id=2, program_id=1, status='active', initial_balance='1.00', current_balance='2.00', created_at=created + timedelta(minutes=6)),
            Challenge(id=8, user_id=1, program_id=2, status='active', initial_balance='1.00', current_balance='2.00', created_at=created + timedelta(minutes=7)),
            Challenge(id=9, user_id=3, program_id=2, status='active', initial_balance='1.00', current_balance='2.00', created_at=created + timedelta(minutes=8)),
        ])
        db.session.commit()
        app.owner_token = db.session.get(User, 1).generate_access_token()
        app.other_user_token = db.session.get(User, 2).generate_access_token()
        db.session.remove()

    yield app

    with app.app_context():
        db.session.remove()
        db.metadata.drop_all(bind=db.engine, tables=_TABLES)


def _owner_headers(app):
    return {'Authorization': f'Bearer {app.owner_token}'}


def test_dashboard_uses_real_jwt_and_returns_only_owner_tenant_recorded_rows(dashboard_app):
    client = dashboard_app.test_client()
    assert client.get('/api/v1/users/dashboard').status_code == 401

    response = client.get('/api/v1/users/dashboard', headers=_owner_headers(dashboard_app))
    assert response.status_code == 200
    payload = response.get_json()

    assert payload['user']['id'] == 1
    assert payload['statistics']['status_counts'] == {
        'total': 6, 'pending': 1, 'active': 2, 'passed': 1, 'failed': 1, 'funded': 1,
    }
    assert payload['statistics']['status_counts_data_status'] == 'recorded_legacy_statuses'
    assert payload['statistics']['success_rate'] == 50.0
    assert payload['statistics']['total_profit'] is None
    assert payload['statistics']['total_spent'] is None
    assert payload['statistics']['total_profit_data_status'] == 'unavailable_no_verified_provenance'
    assert payload['data_quality']['provider_verification'] == 'not_available'

    # Bounded recency excludes ID 1 and all cross-owner/cross-program-tenant rows.
    recent = payload['recent_challenges']
    assert [row['id'] for row in recent] == [6, 5, 4, 3, 2]
    assert all(row['program_name'] == 'Tenant A Program' for row in recent)

    # Legacy amounts preserve decimal strings: a zero is distinct from unknown,
    # and a recorded loss stays negative rather than being discarded.
    by_id = {row['id']: row for row in recent}
    assert by_id[2]['initial_balance'] == '1000.00'
    assert by_id[2]['current_balance'] == '1000.00'
    assert by_id[2]['profit'] == '0.00'
    assert by_id[6]['profit'] == '-50.00'
    assert by_id[6]['profit_data_status'] == 'recorded_not_verified'
    assert by_id[3]['current_balance'] is None and by_id[3]['profit'] is None
    assert by_id[3]['profit_data_status'] == 'unavailable_missing_recorded_balance'
    assert all(row['progress'] is None for row in recent)
    assert all(row['progress_data_status'] == 'unavailable_no_approved_rule_source' for row in recent)

    no_outcomes = client.get(
        '/api/v1/users/dashboard',
        headers={'Authorization': f'Bearer {dashboard_app.other_user_token}'},
    )
    assert no_outcomes.status_code == 200
    assert no_outcomes.get_json()['statistics']['status_counts'] == {
        'total': 1, 'pending': 0, 'active': 1, 'passed': 0, 'failed': 0, 'funded': 0,
    }
    assert no_outcomes.get_json()['statistics']['success_rate'] is None
    assert no_outcomes.get_json()['statistics']['success_rate_data_status'] == 'unavailable_no_recorded_outcomes'


def test_dashboard_has_fixed_read_sql_and_no_implicit_write(dashboard_app):
    statements = Counter()

    def observe_sql(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements[statement] += 1

    with dashboard_app.app_context():
        engine = db.engine
    event.listen(engine, 'before_cursor_execute', observe_sql)
    try:
        response = dashboard_app.test_client().get(
            '/api/v1/users/dashboard', headers=_owner_headers(dashboard_app),
        )
    finally:
        event.remove(engine, 'before_cursor_execute', observe_sql)

    assert response.status_code == 200
    # JWT principal + revocation lookup + grouped aggregate + five-row eager load.
    assert sum(statements.values()) == 4
    assert not any(
        statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE'))
        for statement in statements
    )


def test_dashboard_database_failure_rolls_back_and_returns_generic_503(dashboard_app):
    rollbacks = []

    def fail_dashboard_read(_connection, _cursor, statement, _parameters, _context, _executemany):
        if 'FROM challenges' in statement:
            raise RuntimeError('synthetic internal database detail')

    def observe_rollback(_connection):
        rollbacks.append(True)

    with dashboard_app.app_context():
        engine = db.engine
    event.listen(engine, 'before_cursor_execute', fail_dashboard_read)
    event.listen(engine, 'rollback', observe_rollback)
    try:
        response = dashboard_app.test_client().get(
            '/api/v1/users/dashboard', headers=_owner_headers(dashboard_app),
        )
    finally:
        event.remove(engine, 'before_cursor_execute', fail_dashboard_read)
        event.remove(engine, 'rollback', observe_rollback)

    assert response.status_code == 503
    assert response.get_json() == {
        'error': 'Dashboard is temporarily unavailable',
        'code': 'USER_DASHBOARD_UNAVAILABLE',
    }
    assert rollbacks
    with dashboard_app.app_context():
        assert db.session.execute(text('SELECT 1')).scalar_one() == 1
