"""Fail-closed resource validation before a testing application initializes I/O."""
import os
import re

from sqlalchemy.engine import make_url


def validate_testing_resources(config):
    """Only ephemeral SQLite or an explicitly named local test DB is allowed.

    This guard is intentionally independent of pytest. It also protects CLI and
    integration runners that create the application outside the test suite.
    It does not replace network isolation of the process running the tests.
    """
    if not config.get('TESTING'):
        if os.environ.get('FLASK_TESTING', '').lower() == 'true':
            raise ValueError('Testing runner requires explicit testing configuration')
        return

    value = config.get('SQLALCHEMY_DATABASE_URI')
    try:
        url = make_url(value)
    except Exception:
        raise ValueError('Testing requires a valid isolated database URL') from None

    production = os.environ.get('DATABASE_URL')
    if production:
        try:
            prod = make_url(production)
            same_target = (
                url.get_backend_name(), url.host, url.port, url.database
            ) == (
                prod.get_backend_name(), prod.host, prod.port, prod.database
            )
        except Exception:
            same_target = False
        if same_target:
            raise ValueError('Testing database must not target DATABASE_URL')

    if url.get_backend_name() == 'sqlite':
        if url.database not in (None, '', ':memory:') or url.query:
            raise ValueError('Testing SQLite must be an in-memory database')
    elif url.get_backend_name() == 'postgresql':
        declared = os.environ.get('TEST_DATABASE_URL')
        if not declared or make_url(declared) != url:
            raise ValueError('Testing PostgreSQL requires explicit TEST_DATABASE_URL')
        if config.get('ISOLATED_STAGING_DATABASE'):
            # This opt-in is not a URL exemption: validate namespace, UUID DB,
            # UID, private directory, socket identity and the exact URL first.
            from src.isolated_postgresql_target import validate_isolated_postgresql_target
            validate_isolated_postgresql_target(value)
        else:
            if url.host not in ('127.0.0.1', '::1'):
                raise ValueError('Testing PostgreSQL must be on loopback')
            if not re.fullmatch(r'marketedgepros_test_[a-zA-Z0-9_]+', url.database or ''):
                raise ValueError('Testing PostgreSQL requires a dedicated per-run database name')
            # libpq connection options can override the host/database in the URL.
            if url.query:
                raise ValueError('Testing PostgreSQL URL must not contain connection overrides')
    else:
        raise ValueError('Unsupported testing database backend')

    if config.get('SQLALCHEMY_BINDS'):
        raise ValueError('Testing database binds are not permitted')
    engine_options = config.get('SQLALCHEMY_ENGINE_OPTIONS') or {}
    allowed_options = {'pool_size', 'max_overflow', 'pool_timeout', 'pool_recycle', 'pool_pre_ping', 'echo'}
    if set(engine_options) - allowed_options:
        raise ValueError('Testing engine connection overrides are not permitted')
    if config.get('REDIS_URL'):
        raise ValueError('Testing must not initialize a network Redis client')
    if config.get('CACHE_TYPE') not in ('SimpleCache', 'NullCache', 'simple', 'null'):
        raise ValueError('Testing requires an in-process cache')
    if config.get('RATELIMIT_STORAGE_URL') != 'memory://':
        raise ValueError('Testing requires an in-process rate limiter')
