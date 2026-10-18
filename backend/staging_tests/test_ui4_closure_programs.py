"""PostgreSQL migration-head canary for UI-4 admin program management.

Run only through backend/scripts/run_staging_integration.py by the integrator.
"""
from decimal import Decimal

from sqlalchemy import text

from test_order_quote_concurrency import quote_database


def _body():
    return {
        'name': 'Staging persisted program',
        'type': 'staging_future_label',
        'description': 'Synthetic migration-head canary only.',
        'account_size': '50000.00',
        'profit_target': '8.00',
        'max_daily_loss': '5.00',
        'max_total_loss': '10.00',
        'price': '199.99',
        'profit_split': '80.00',
        'profit_split_percentage': '80.00',
        'minimum_payout_amount': '0.00',
        'payout_mode': 'on_demand',
        'rules': {'synthetic': {'no_provider': True}},
        'is_active': True,
    }


def test_ui4_programs_postgresql_head_preserves_type_alias_exact_decimals_and_catalog_parity(
    staging_resources, monkeypatch,
):
    """A real migration head retains public catalog compatibility after admin writes."""
    from src.database import db
    from src.models.trading_program import TradingProgram
    from src.models.user import User
    from src.services.admin_closure_programs import AdminClosureProgramsService
    from src.services.program_catalog_service import ProgramCatalogService

    with quote_database(staging_resources, monkeypatch, revision='heads') as app:
        with app.app_context(), app.test_request_context('/api/v1/admin/programs'):
            assert db.session.execute(text('SELECT version_num FROM alembic_version')).scalars().all() == [
                '20261013_000002'
            ]
            root = db.session.get(User, 1)
            created = AdminClosureProgramsService.create_program(root, _body())
            db.session.commit()
            program_id = created['program']['id']
            assert created['program']['account_size'] == '50000.00'
            assert created['program']['price'] == '199.99'
            assert created['program']['profit_target'] == '8.00'
            assert db.session.execute(text('''
                SELECT program_type, type, account_size, price
                FROM trading_programs WHERE id = :program_id
            '''), {'program_id': program_id}).one() == (
                'staging_future_label', 'staging_future_label', Decimal('50000.00'), Decimal('199.99'),
            )

            updated = AdminClosureProgramsService.update_program(root, program_id, {'type': 'staging_renamed_label'})
            db.session.commit()
            assert updated['program']['type'] == 'staging_renamed_label'
            assert db.session.execute(text('SELECT program_type, type FROM trading_programs WHERE id = :program_id'), {
                'program_id': program_id,
            }).one() == ('staging_renamed_label', 'staging_renamed_label')

        with app.app_context(), app.test_request_context(f'/api/v1/programs/{program_id}'):
            catalog = ProgramCatalogService.get_program(program_id)
            assert catalog['tenant_id'] == 1
            assert catalog['type'] == catalog['terms']['type'] == 'staging_renamed_label'
            assert catalog['account_size'] == catalog['terms']['account_size'] == '50000.00'
            assert catalog['price'] == '199.99'
            assert catalog['rules'] == catalog['terms']['rules'] == {'synthetic': {'no_provider': True}}
            assert db.session.get(TradingProgram, program_id).price == Decimal('199.99')
