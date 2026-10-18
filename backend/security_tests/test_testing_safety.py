"""Runtime regressions for factory initialization order and fail-closed I/O."""
import pytest
from src.testing_safety import validate_testing_resources


def safe_config(**overrides):
    result = {
        'TESTING': True,
        'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
        'REDIS_URL': None,
        'CACHE_TYPE': 'SimpleCache',
        'RATELIMIT_STORAGE_URL': 'memory://',
    }
    result.update(overrides)
    return result


def test_memory_database_is_allowed():
    validate_testing_resources(safe_config())


@pytest.mark.parametrize('url', [
    'postgresql://user:password@146.190.21.113:5432/marketedgepros',
    'postgresql://user:password@localhost/marketedgepros',
    'sqlite:////tmp/existing-database.db',
    'mysql://user:password@localhost/marketedgepros_test_run',
    'sqlite:///:memory:?uri=true',
    None,
])
def test_unapproved_database_is_rejected(url):
    with pytest.raises(ValueError):
        validate_testing_resources(safe_config(SQLALCHEMY_DATABASE_URI=url))


def test_local_postgres_requires_explicit_per_run_name(monkeypatch):
    url = 'postgresql://testuser:testpass@127.0.0.1:55432/marketedgepros_test_run42'
    monkeypatch.setenv('TEST_DATABASE_URL', url)
    validate_testing_resources(safe_config(SQLALCHEMY_DATABASE_URI=url))


@pytest.mark.parametrize('url', [
    'postgresql://testuser:testpass@localhost/marketedgepros_test',
    'postgresql://testuser:testpass@db.example.org/marketedgepros_test_run42',
    'postgresql://testuser:testpass@localhost/marketedgepros_test_run42?host=146.190.21.113',
])
def test_postgres_name_host_and_override_checks(monkeypatch, url):
    monkeypatch.setenv('TEST_DATABASE_URL', url)
    with pytest.raises(ValueError):
        validate_testing_resources(safe_config(SQLALCHEMY_DATABASE_URI=url))


def test_different_credentials_cannot_bypass_production_target_check(monkeypatch):
    url = 'postgresql://testuser:testpass@127.0.0.1:55432/marketedgepros_test_run42'
    monkeypatch.setenv('TEST_DATABASE_URL', url)
    monkeypatch.setenv('DATABASE_URL', url.replace('testuser:testpass', 'real:credential'))
    with pytest.raises(ValueError, match='DATABASE_URL'):
        validate_testing_resources(safe_config(SQLALCHEMY_DATABASE_URI=url))


@pytest.mark.parametrize('overrides', [
    {'REDIS_URL': 'redis://127.0.0.1:6379/0'},
    {'CACHE_TYPE': 'RedisCache'},
    {'RATELIMIT_STORAGE_URL': 'redis://127.0.0.1:6379/0'},
    {'SQLALCHEMY_BINDS': {'other': 'postgresql://user:password@db/prod'}},
    {'SQLALCHEMY_ENGINE_OPTIONS': {'connect_args': {'host': '146.190.21.113'}}},
    {'SQLALCHEMY_ENGINE_OPTIONS': {'creator': lambda: None}},
])
def test_network_extensions_and_binds_are_rejected(overrides):
    with pytest.raises(ValueError):
        validate_testing_resources(safe_config(**overrides))


def test_factory_rejects_unsafe_override_before_database_init(monkeypatch):
    import src.app as app_module
    def never_initialize(app):
        pytest.fail('DB initialization happened before resource validation')
    monkeypatch.setattr(app_module, 'init_db', never_initialize)
    with pytest.raises(ValueError):
        app_module.create_app('testing', config_overrides={
            'SQLALCHEMY_DATABASE_URI': 'postgresql://root:secret@146.190.21.113/marketedgepros'
        })


def test_testing_flag_cannot_be_applied_after_production_factory(monkeypatch):
    import src.app as app_module
    def never_initialize(app):
        pytest.fail('Production initialization reached from testing runner')
    monkeypatch.setattr(app_module, 'init_db', never_initialize)
    with pytest.raises(ValueError, match='explicit testing'):
        app_module.create_app('production')


def test_full_factory_builds_without_network_and_health_works():
    from src.app import create_app
    from src.database import get_redis, db
    app = create_app('testing')
    assert app.testing
    assert get_redis() is None
    assert app.config['CACHE_TYPE'] == 'SimpleCache'
    with app.app_context():
        assert db.engine.url.database == ':memory:'
    response = app.test_client().get('/health')
    assert response.status_code == 200
    assert response.get_json()['status'] == 'healthy'


def test_testing_override_cannot_turn_off_guard_without_env(monkeypatch):
    import src.app as app_module
    monkeypatch.delenv('FLASK_TESTING', raising=False)
    monkeypatch.setattr(app_module, 'init_db', lambda app: pytest.fail('DB init reached'))
    with pytest.raises(ValueError, match='cannot be disabled'):
        app_module.create_app('testing', config_overrides={
            'TESTING': False,
            'SQLALCHEMY_DATABASE_URI': 'postgresql://root:secret@146.190.21.113/marketedgepros',
        })


def test_localhost_dns_alias_is_not_accepted(monkeypatch):
    url = 'postgresql://testuser:testpass@localhost/marketedgepros_test_run42'
    monkeypatch.setenv('TEST_DATABASE_URL', url)
    with pytest.raises(ValueError, match='loopback'):
        validate_testing_resources(safe_config(SQLALCHEMY_DATABASE_URI=url))
