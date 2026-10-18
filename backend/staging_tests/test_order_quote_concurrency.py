"""Exact service concurrency on private PostgreSQL, without financial settlement."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from decimal import Decimal
from threading import Barrier
from uuid import uuid4
from pathlib import Path
import os
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


@contextmanager
def quote_database(resources, monkeypatch, revision='20261011_000006'):
    from src.app import create_app
    from src.database import db
    from src.models.user import User
    from src.models.tenant import Tenant
    from src.models.token_blacklist import TokenBlacklist
    from src.models.trading_program import TradingProgram, ProgramAddOn
    from src.models.purchase_order import PurchaseOrder
    database = 'marketedgepros_test_' + uuid4().hex
    url = make_url(resources['pg_url']).set(database=database)
    rendered = url.render_as_string(hide_password=False)
    admin = create_engine(make_url(resources['pg_url']).set(database='postgres'), isolation_level='AUTOCOMMIT')
    app = None
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database}"'))
        monkeypatch.setenv('TEST_DATABASE_URL', rendered)
        backend = Path(__file__).resolve().parents[1]
        migration_config = Config(str(backend / 'migrations/alembic.ini'))
        migration_config.set_main_option('script_location', str(backend / 'migrations'))
        migration_config.set_main_option('sqlalchemy.url', rendered.replace('%', '%%'))
        migration_engine = create_engine(url)
        try:
            with migration_engine.connect() as connection:
                migration_config.attributes['connection'] = connection
                command.upgrade(migration_config, revision)
        finally:
            migration_engine.dispose()
        app = create_app('testing', config_overrides={
            'SQLALCHEMY_DATABASE_URI': rendered, 'ISOLATED_STAGING_DATABASE': True,
            'ORDER_QUOTES_ENABLED': True, 'ORDER_QUOTE_CURRENCY': 'USD',
            'PLATFORM_ROOT_USER_ID': 1, 'EXPANDED_HIERARCHY_ENABLED': False,
            'SQLALCHEMY_ENGINE_OPTIONS': {'pool_size': 4, 'max_overflow': 0, 'pool_timeout': 5},
        })
        with app.app_context():
            # Real frozen migration DDL also exercises the runtime readiness gate.
            db.session.execute(text("INSERT INTO tenants (id, name, slug, subdomain, status) VALUES (1, 'Synthetic Quote Brand', 'synthetic-quote', 'quote', 'active')"))
            db.session.add_all([
                User(id=1, email='owner@quote.invalid', password_hash='not-a-credential', first_name='Synthetic', last_name='Owner',
                     role='supermaster', tenant_id=1, parent_id=None, level=0, tree_path='1', is_active=True, is_verified=True, can_create_same_role=True),
                User(id=2, email='user@quote.invalid', password_hash='not-a-credential', first_name='Synthetic', last_name='User',
                     role='trader', tenant_id=1, parent_id=1, level=1, tree_path='1/2', is_active=True, is_verified=True, can_create_same_role=False),
            ])
            db.session.execute(text("""INSERT INTO trading_programs
                (id, tenant_id, name, program_type, type, account_size, price, rules, is_active,
                 profit_target, max_daily_loss, max_total_loss, profit_split)
                VALUES (10, 1, 'Synthetic Program', 'one_phase', 'one_phase', 10000, 19.99, CAST(:rules AS jsonb), true,
                        10, 5, 10, 80)"""), {'rules': '{"unknown":null}'})
            db.session.execute(text("""INSERT INTO program_addons
                (id, program_id, name, price, price_type, addon_type, benefits, is_active)
                VALUES (20, 10, 'Synthetic Add-on', 10.00, 'percentage', 'synthetic', '{}'::jsonb, true)"""))
            db.session.commit()
        yield app
    finally:
        if app is not None:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        admin.dispose()


def _concurrent(app, requests):
    from src.database import db
    from src.models.user import User
    from src.services.order_service import OrderService, OrderError
    barrier = Barrier(len(requests), timeout=10)
    def worker(body):
        with app.app_context(), app.test_request_context('/api/v1/orders/'):
            db.session.execute(text("SET statement_timeout = '10s'"))
            actor = db.session.get(User, 2)
            barrier.wait()
            try:
                order, created = OrderService.create_quote(actor, body, 'synthetic_concurrency_key_0001')
                identity, amount = order.id, order.amount_minor
                db.session.commit()
                return ('ok', identity, amount, created)
            except OrderError as exc:
                db.session.rollback()
                return ('refused', exc.code)
            finally:
                db.session.remove()
    with ThreadPoolExecutor(max_workers=len(requests)) as executor:
        futures = [executor.submit(worker, body) for body in requests]
        return [future.result(timeout=20) for future in futures]


def test_concurrent_identical_quote_key_has_one_winner_and_one_replay(staging_resources, monkeypatch):
    from src.database import db
    from src.models.purchase_order import PurchaseOrder
    with quote_database(staging_resources, monkeypatch) as app:
        results = _concurrent(app, [{'program_id': 10, 'addon_ids': [20]}] * 2)
        assert all(row[0] == 'ok' for row in results)
        assert results[0][1] == results[1][1] and results[0][2] == results[1][2] == 2199
        assert sorted(row[3] for row in results) == [False, True]
        with app.app_context():
            assert db.session.query(PurchaseOrder).count() == 1


def test_concurrent_different_request_same_key_refuses_loser_without_second_quote(staging_resources, monkeypatch):
    from src.database import db
    from src.models.purchase_order import PurchaseOrder
    with quote_database(staging_resources, monkeypatch) as app:
        results = _concurrent(app, [{'program_id': 10, 'addon_ids': [20]}, {'program_id': 10, 'addon_ids': []}])
        assert len([row for row in results if row[0] == 'ok']) == 1
        assert ('refused', 'ORDER_IDEMPOTENCY_CONFLICT') in results
        with app.app_context():
            assert db.session.query(PurchaseOrder).count() == 1


def test_quote_insert_rolls_back_as_part_of_outer_transaction(staging_resources, monkeypatch):
    from src.database import db
    from src.models.user import User
    from src.models.purchase_order import PurchaseOrder
    from src.services.order_service import OrderService
    with quote_database(staging_resources, monkeypatch) as app:
        with app.app_context(), app.test_request_context('/api/v1/orders/'):
            OrderService.create_quote(db.session.get(User, 2), {'program_id': 10}, 'synthetic_rollback_key_0001')
            db.session.rollback()
            assert db.session.query(PurchaseOrder).count() == 0


@pytest.mark.parametrize('case', ['old_revision', 'disabled_trigger', 'modified_function', 'conditional_trigger'])
def test_runtime_quote_refuses_unready_immutable_database_before_insert(staging_resources, monkeypatch, case):
    from src.database import db
    from src.models.user import User
    from src.models.purchase_order import PurchaseOrder
    from src.services.order_service import OrderService, OrderError
    with quote_database(staging_resources, monkeypatch) as app:
        with app.app_context(), app.test_request_context('/api/v1/orders/'):
            if case == 'old_revision':
                db.session.execute(text("UPDATE alembic_version SET version_num = '20261011_000005'"))
            elif case == 'disabled_trigger':
                db.session.execute(text('ALTER TABLE purchase_orders DISABLE TRIGGER purchase_orders_immutable'))
            elif case == 'modified_function':
                db.session.execute(text('CREATE OR REPLACE FUNCTION marketedgepros_purchase_orders_immutable() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END; $$'))
            else:
                db.session.execute(text('DROP TRIGGER purchase_orders_immutable ON purchase_orders'))
                db.session.execute(text('CREATE TRIGGER purchase_orders_immutable BEFORE UPDATE OR DELETE ON purchase_orders FOR EACH ROW WHEN (false) EXECUTE FUNCTION marketedgepros_purchase_orders_immutable()'))
            db.session.commit()
            with pytest.raises(OrderError) as error:
                OrderService.create_quote(db.session.get(User, 2), {'program_id': 10}, 'synthetic_readiness_key_0001')
            assert error.value.code == 'ORDER_STORAGE_NOT_READY'
            db.session.rollback()
            assert db.session.query(PurchaseOrder).count() == 0
