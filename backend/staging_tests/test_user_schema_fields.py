"""Real PostgreSQL checks for additive user fields; no real money/user data."""
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
import pytest

BACKEND = Path(__file__).resolve().parents[1]
PREVIOUS = '20261011_000003'
REVISION = '20261011_000004'
FIELDS = ('can_create_same_role', 'available_balance', 'total_withdrawn', 'payout_count')


@contextmanager
def user_field_database(resources):
    name = 'marketedgepros_test_' + uuid4().hex
    url = make_url(resources['pg_url']).set(database=name)
    admin = create_engine(make_url(resources['pg_url']).set(database='postgres'), isolation_level='AUTOCOMMIT')
    engine = None
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        engine = create_engine(url)
        config = Config(str(BACKEND / 'migrations/alembic.ini'))
        config.set_main_option('script_location', str(BACKEND / 'migrations'))
        config.set_main_option('sqlalchemy.url', url.render_as_string(hide_password=False).replace('%', '%%'))
        with engine.connect() as connection:
            config.attributes['connection'] = connection
            command.upgrade(config, PREVIOUS)
            yield connection, config
    finally:
        if engine is not None:
            engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        admin.dispose()


def insert_disabled_user(connection):
    connection.execute(text("""
        INSERT INTO users (id, email, password_hash, first_name, last_name,
            is_active, is_verified, role, tenant_id, token_version)
        VALUES (990001, 'user-field-sentinel@example.invalid', 'not-a-login-credential',
            'Field', 'Sentinel', false, false, 'trader', NULL, 7)
    """))
    connection.commit()


def test_user_fields_preserve_identity_unknown_money_and_existing_token_version(staging_resources):
    with user_field_database(staging_resources) as (connection, config):
        insert_disabled_user(connection)
        command.upgrade(config, REVISION)
        row = connection.execute(text('SELECT role, tenant_id, token_version, can_create_same_role, available_balance, total_withdrawn, payout_count FROM users WHERE id=990001')).one()
        assert tuple(row) == ('trader', None, 7, False, None, None, None)
        connection.commit()
        fields = {item['name']: item for item in inspect(connection).get_columns('users')}
        assert fields['can_create_same_role']['nullable'] is False
        for name in FIELDS[1:]:
            assert fields[name]['nullable'] is True and fields[name]['default'] is None
        connection.commit()
        command.downgrade(config, PREVIOUS)
        assert not set(FIELDS).intersection(item['name'] for item in inspect(connection).get_columns('users'))
        assert connection.execute(text('SELECT token_version FROM users WHERE id=990001')).scalar_one() == 7
        connection.commit()
        command.upgrade(config, REVISION)
        assert connection.execute(text('SELECT available_balance FROM users WHERE id=990001')).scalar_one() is None


@pytest.mark.parametrize('field,value', [('available_balance','12.34'),('total_withdrawn','0'),('payout_count','0'),('can_create_same_role','true')])
def test_user_field_downgrade_refuses_populated_data(staging_resources, field, value):
    with user_field_database(staging_resources) as (connection, config):
        insert_disabled_user(connection)
        command.upgrade(config, REVISION)
        connection.execute(text(f'UPDATE users SET {field}={value} WHERE id=990001'))
        connection.commit()
        with pytest.raises(RuntimeError, match='downgrade refused'):
            command.downgrade(config, PREVIOUS)
        connection.rollback()
        assert set(FIELDS).issubset(item['name'] for item in inspect(connection).get_columns('users'))
        assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == REVISION
        stored = connection.execute(text(f'SELECT {field} FROM users WHERE id=990001')).scalar_one()
        if field == 'can_create_same_role':
            assert stored is True
        else:
            from decimal import Decimal
            assert Decimal(str(stored)) == Decimal(value)


def test_user_field_collision_refuses_before_any_new_column(staging_resources):
    with user_field_database(staging_resources) as (connection, config):
        connection.execute(text('ALTER TABLE users ADD COLUMN available_balance numeric(12,2)'))
        connection.commit()
        with pytest.raises(RuntimeError, match='reconciliation required'):
            command.upgrade(config, REVISION)
        connection.rollback()
        columns = {item['name'] for item in inspect(connection).get_columns('users')}
        assert 'available_balance' in columns
        assert not {'can_create_same_role','total_withdrawn','payout_count'}.intersection(columns)
        assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == PREVIOUS
