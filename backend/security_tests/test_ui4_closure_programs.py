"""Focused UI-4 program-management service regressions using synthetic SQLite only.

The canonical HTTP handlers are intentionally supplied by integration.patch because
routes/admin.py is shared.  These tests exercise the exact service they call.
"""
from decimal import Decimal

import pytest
from sqlalchemy import JSON, event
from sqlalchemy.dialects.postgresql import JSONB
from werkzeug.datastructures import MultiDict

from src.database import db
from src.models.lead import Lead
from src.models.tenant import Tenant
from src.models.token_blacklist import TokenBlacklist
from src.models.trading_program import Challenge, ProgramAddOn, TradingProgram
from src.models.user import User
from src.services.admin_closure_programs import (
    AdminClosureProgramsService,
    AdminProgramsConflict,
    AdminProgramsNotFound,
    AdminProgramsQueryInvalid,
    AdminProgramsScopeRequired,
    AdminProgramsValidationError,
)


@pytest.fixture
def programs_closure_app():
    from src.app import create_app

    app = create_app('testing', config_overrides={
        'EXPANDED_HIERARCHY_ENABLED': False,
        'PLATFORM_ROOT_USER_ID': 1,
        'ORDER_QUOTE_CURRENCY': 'USD',
        'PROPAGATE_EXCEPTIONS': False,
    })
    tables = [
        Tenant.__table__, User.__table__, TokenBlacklist.__table__, TradingProgram.__table__, ProgramAddOn.__table__,
        Challenge.__table__, Lead.__table__,
    ]
    portable_columns = [
        column for table in tables for column in table.c if isinstance(column.type, JSONB)
    ]
    original_types = {column: column.type for column in portable_columns}
    with app.app_context():
        if db.engine.dialect.name == 'sqlite':
            for column in portable_columns:
                column.type = JSON()
        db.metadata.create_all(bind=db.engine, tables=tables)
        db.session.add_all([
            Tenant(id=1, name='Tenant One', subdomain='one', status='active'),
            Tenant(id=2, name='Tenant Two', subdomain='two', status='active'),
            User(
                id=1, email='root@programs.invalid', password_hash='not-a-credential', first_name='Root', last_name='One',
                tenant_id=1, role='supermaster', parent_id=None, level=0, tree_path='1', is_active=True,
                is_verified=True, can_create_same_role=True,
            ),
            User(
                id=2, email='master@programs.invalid', password_hash='not-a-credential', first_name='Master', last_name='One',
                tenant_id=1, role='master', parent_id=1, level=1, tree_path='1/2', is_active=True,
                is_verified=True, can_create_same_role=False,
            ),
            User(
                id=3, email='foreign@programs.invalid', password_hash='not-a-credential', first_name='Foreign', last_name='Master',
                tenant_id=2, role='master', parent_id=None, level=0, tree_path='3', is_active=True,
                is_verified=True, can_create_same_role=False,
            ),
            User(
                id=4, email='trader@programs.invalid', password_hash='not-a-credential', first_name='Trader', last_name='One',
                tenant_id=1, role='trader', parent_id=2, level=2, tree_path='1/2/4', is_active=True,
                is_verified=True, can_create_same_role=False,
            ),
            TradingProgram(
                id=10, tenant_id=1, name='Tenant One Zeroes', type='future_label', description=None,
                account_size=Decimal('10000.00'), profit_target=Decimal('0.00'), max_daily_loss=Decimal('0.00'),
                max_total_loss=Decimal('10.00'), price=Decimal('19.99'), profit_split=Decimal('0.00'),
                profit_split_percentage=Decimal('0.00'), minimum_payout_amount=Decimal('0.00'),
                payout_mode='on_demand', rules={'nested': {'value': None}}, is_active=True,
            ),
            TradingProgram(
                id=11, tenant_id=2, name='Tenant Two', type='one_phase', account_size=Decimal('20000.00'),
                price=Decimal('29.99'), rules={}, is_active=True,
            ),
        ])
        db.session.add(Challenge(
            id=100, user_id=4, program_id=10, status='active', initial_balance=Decimal('10000.00'),
            current_balance=Decimal('10000.00'), payment_type='credit_card', approval_status='approved',
        ))
        db.session.commit()
    yield app
    with app.app_context():
        db.session.remove()
        db.metadata.drop_all(bind=db.engine, tables=list(reversed(tables)))
        for column, original_type in original_types.items():
            column.type = original_type
        db.engine.dispose()


def _actor(identity):
    return db.session.get(User, identity)


def _page(page='1', per_page='20'):
    return AdminClosureProgramsService.parse_list_query(MultiDict([('page', page), ('per_page', per_page)]))


def _create_body(name='New Persisted Program'):
    return {
        'name': name,
        'type': 'stored_unknown_type',
        'description': None,
        'account_size': '50000.00',
        'profit_target': '0.00',
        'max_daily_loss': None,
        'max_total_loss': '10.00',
        'price': '199.99',
        'profit_split': None,
        'profit_split_percentage': '0.00',
        'minimum_payout_amount': None,
        'payout_mode': None,
        'rules': {'uninterpreted': {'zero': '0.00'}},
        'is_active': True,
    }


def test_programs_service_returns_owner_scoped_exact_decimal_snapshot(programs_closure_app):
    with programs_closure_app.app_context(), programs_closure_app.test_request_context('/api/v1/admin/programs?page=1&per_page=20'):
        statements = []

        def observe(_, __, statement, *___):
            if 'trading_programs' in statement.lower():
                statements.append(statement.lower())

        event.listen(db.engine, 'before_cursor_execute', observe)
        try:
            master = AdminClosureProgramsService.list_programs(_actor(2), _page())
            root = AdminClosureProgramsService.list_programs(_actor(1), _page())
        finally:
            event.remove(db.engine, 'before_cursor_execute', observe)

        assert master['owner_context'] == {'user_id': 2, 'tenant_id': 1, 'role': 'master'}
        assert root['owner_context'] == {'user_id': 1, 'tenant_id': 1, 'role': 'supermaster'}
        assert [program['id'] for program in master['programs']] == [10]
        assert [program['id'] for program in root['programs']] == [10, 11]
        record = master['programs'][0]
        assert record['account_size'] == '10000.00'
        assert record['profit_target'] == record['max_daily_loss'] == record['profit_split'] == '0.00'
        assert record['description'] is None and record['rules'] == {'nested': {'value': None}}
        assert record['tenant_id'] == 1 and record['type'] == 'future_label'
        assert master['pagination'] == {'page': 1, 'per_page': 20, 'total': 1, 'pages': 1}
        # One CTE statement per response: no count/page drift and no N+1 re-read.
        assert len(statements) == 2
        assert all('limit' in statement and 'count' in statement for statement in statements)


def test_programs_service_rejects_query_scope_and_mutation_coercion_before_program_sql(programs_closure_app):
    with programs_closure_app.app_context(), programs_closure_app.test_request_context('/api/v1/admin/programs'):
        with pytest.raises(AdminProgramsQueryInvalid):
            AdminClosureProgramsService.parse_list_query(MultiDict([('page', '01')]))
        with pytest.raises(AdminProgramsQueryInvalid):
            AdminClosureProgramsService.parse_list_query(MultiDict([('page', '1'), ('page', '2')]))

        statements = []

        def observe(_, __, statement, *___):
            if 'trading_programs' in statement.lower():
                statements.append(statement)

        event.listen(db.engine, 'before_cursor_execute', observe)
        try:
            foreign = _actor(3)
            foreign.tenant_id = None
            with pytest.raises(AdminProgramsScopeRequired):
                AdminClosureProgramsService.list_programs(foreign, _page())
            with pytest.raises(AdminProgramsValidationError):
                AdminClosureProgramsService.create_program(_actor(2), {**_create_body(), 'price': 199.99})
            with pytest.raises(AdminProgramsValidationError):
                AdminClosureProgramsService.create_program(_actor(2), {**_create_body(), 'tenant_id': 2})
        finally:
            db.session.rollback()
            event.remove(db.engine, 'before_cursor_execute', observe)
        assert statements == []


def test_programs_service_create_update_and_rollback_keep_tenant_and_exact_strings(programs_closure_app):
    with programs_closure_app.app_context(), programs_closure_app.test_request_context('/api/v1/admin/programs'):
        result = AdminClosureProgramsService.create_program(_actor(2), _create_body())
        assert result['program']['tenant_id'] == 1
        assert result['program']['price'] == '199.99'
        assert result['program']['profit_target'] == '0.00'
        created_id = result['program']['id']
        db.session.commit()

        updated = AdminClosureProgramsService.update_program(_actor(2), created_id, {
            'price': '200.00', 'profit_target': None, 'rules': {'legacy': {'kept': True}}, 'is_active': False,
        })
        db.session.commit()
        assert updated['program']['price'] == '200.00'
        assert updated['program']['profit_target'] is None
        assert updated['program']['rules'] == {'legacy': {'kept': True}}
        assert updated['program']['is_active'] is False

        with pytest.raises(AdminProgramsNotFound):
            AdminClosureProgramsService.update_program(_actor(2), 11, {'price': '30.00'})
        db.session.rollback()

        pending = AdminClosureProgramsService.create_program(_actor(2), _create_body('Rolled Back'))
        assert db.session.get(TradingProgram, pending['program']['id']) is not None
        db.session.rollback()
        assert db.session.query(TradingProgram).filter_by(name='Rolled Back').count() == 0


def test_programs_service_delete_preserves_active_challenge_guard(programs_closure_app):
    with programs_closure_app.app_context(), programs_closure_app.test_request_context('/api/v1/admin/programs/10'):
        with pytest.raises(AdminProgramsConflict):
            AdminClosureProgramsService.delete_program(_actor(2), 10)
        db.session.rollback()
        challenge = db.session.get(Challenge, 100)
        challenge.status = 'failed'
        db.session.commit()
        with pytest.raises(AdminProgramsConflict):
            AdminClosureProgramsService.delete_program(_actor(2), 10)
        assert db.session.get(TradingProgram, 10) is not None

        unattached = AdminClosureProgramsService.create_program(_actor(2), _create_body('Unattached program'))
        db.session.commit()
        deleted = AdminClosureProgramsService.delete_program(_actor(2), unattached['program']['id'])
        db.session.commit()
        assert deleted == {
            'owner_context': {'user_id': 2, 'tenant_id': 1, 'role': 'master'},
            'deleted_program_id': unattached['program']['id'],
        }
        assert db.session.get(TradingProgram, unattached['program']['id']) is None
