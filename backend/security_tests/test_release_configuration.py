"""Isolated regressions for release-ready production configuration."""
import pytest
from flask import Flask

from src.production_safety import (
    MAX_SIGNED_INT32,
    validate_demo_release_configuration,
    validate_production_configuration,
)


def synthetic_production_config(**overrides):
    """Return synthetic .invalid endpoints that are never contacted by these tests."""
    config = {
        "PRODUCTION": True,
        "TESTING": False,
        "DEBUG": False,
        "SECRET_KEY": "unit-test-signing-secret-" + "a" * 40,
        "JWT_SECRET_KEY": "unit-test-jwt-secret-" + "b" * 40,
        "SQLALCHEMY_DATABASE_URI": (
            "postgresql://unit_user:unit_password@database.invalid:5432/unit_release"
        ),
        "REDIS_URL": "redis://redis.invalid:6379/0",
        "CACHE_TYPE": "RedisCache",
        "CACHE_REDIS_URL": "redis://cache.invalid:6379/1",
        "RATELIMIT_ENABLED": True,
        "RATELIMIT_STORAGE_URL": "redis://limiter.invalid:6379/2",
        "PLATFORM_ROOT_USER_ID": "17",
    }
    config.update(overrides)
    return config


def synthetic_demo_config(**overrides):
    """Return a syntactically valid demo target; validation never contacts it."""
    config = synthetic_production_config(
        DEMO_RELEASE_ENABLED=True,
        SQLALCHEMY_DATABASE_URI=(
            "postgresql://marketedgepros_demo:demo-password@127.0.0.1:5432/"
            "marketedgepros_demo_20261012"
        ),
        REDIS_URL="redis://:synthetic-dedicated-redis-password-0123456789@127.0.0.1:6380/0",
        CACHE_REDIS_URL="redis://:synthetic-dedicated-redis-password-0123456789@127.0.0.1:6380/1",
        RATELIMIT_STORAGE_URL="redis://:synthetic-dedicated-redis-password-0123456789@127.0.0.1:6380/2",
        PLATFORM_ROOT_USER_ID=str(MAX_SIGNED_INT32),
    )
    config.update(overrides)
    return config


def test_synthetic_complete_production_config_is_accepted():
    app = Flask("synthetic-production-config")
    app.config.update(synthetic_production_config())
    validate_production_configuration(app.config)


@pytest.mark.parametrize(
    ("overrides", "setting"),
    [
        ({"SECRET_KEY": "short"}, "SECRET_KEY"),
        ({"JWT_SECRET_KEY": "short"}, "JWT_SECRET_KEY"),
        ({"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"}, "SQLALCHEMY_DATABASE_URI"),
        ({"REDIS_URL": "https://redis.invalid"}, "REDIS_URL"),
        ({"CACHE_REDIS_URL": "https://cache.invalid"}, "CACHE_REDIS_URL"),
        ({"RATELIMIT_STORAGE_URL": "https://limiter.invalid"}, "RATELIMIT_STORAGE_URL"),
        ({"PLATFORM_ROOT_USER_ID": "01"}, "PLATFORM_ROOT_USER_ID"),
        ({"DEBUG": True}, "DEBUG"),
        ({"RATELIMIT_ENABLED": False}, "RATELIMIT_ENABLED"),
        ({"CACHE_TYPE": "SimpleCache"}, "CACHE_TYPE"),
    ],
)
def test_synthetic_invalid_production_settings_fail_closed(overrides, setting):
    with pytest.raises(ValueError, match=setting) as error:
        validate_production_configuration(synthetic_production_config(**overrides))
    assert "unit_" not in str(error.value)


def test_disabled_provider_credentials_are_not_deployment_requirements():
    config = synthetic_production_config()
    assert "STRIPE_SECRET_KEY" not in config
    assert "SENDGRID_API_KEY" not in config
    validate_production_configuration(config)


def test_non_production_config_is_not_subject_to_deployment_checks():
    validate_production_configuration({"PRODUCTION": False, "DEBUG": True})


def test_synthetic_complete_demo_config_is_accepted_without_network_access():
    validate_demo_release_configuration(synthetic_demo_config())


@pytest.mark.parametrize(
    ("overrides", "setting"),
    [
        (
            {
                "SQLALCHEMY_DATABASE_URI": (
                    "postgresql://marketedgepros_demo:demo-password@127.0.0.1:5432/"
                    "marketedgepros_demo_20260901"
                )
            },
            "SQLALCHEMY_DATABASE_URI",
        ),
        (
            {
                "SQLALCHEMY_DATABASE_URI": (
                    "postgresql://marketedgepros_demo:demo-password@database.invalid:5432/"
                    "marketedgepros_demo_20261012"
                )
            },
            "SQLALCHEMY_DATABASE_URI",
        ),
        (
            {
                "SQLALCHEMY_DATABASE_URI": (
                    "postgresql://another_user:demo-password@127.0.0.1:5432/"
                    "marketedgepros_demo_20261012"
                )
            },
            "SQLALCHEMY_DATABASE_URI",
        ),
        ({"REDIS_URL": "redis://127.0.0.1:6380/1"}, "REDIS_URL"),
        ({"CACHE_REDIS_URL": "redis://localhost:6380/1"}, "CACHE_REDIS_URL"),
        ({"RATELIMIT_STORAGE_URL": "redis://127.0.0.1:6379/2"}, "RATELIMIT_STORAGE_URL"),
        ({"REDIS_URL": "redis://demo:password@127.0.0.1:6380/0"}, "REDIS_URL"),
        ({"PLATFORM_ROOT_USER_ID": str(MAX_SIGNED_INT32 + 1)}, "PLATFORM_ROOT_USER_ID"),
        ({"PLATFORM_ROOT_USER_ID": "01"}, "PLATFORM_ROOT_USER_ID"),
        ({"PLATFORM_ROOT_USER_ID": "100000000000000000000"}, "PLATFORM_ROOT_USER_ID"),
        ({"REDIS_URL": "redis://127.0.0.1:6380/0"}, "REDIS_URL"),
    ],
)
def test_demo_configuration_rejects_non_allowlisted_targets(overrides, setting):
    with pytest.raises(ValueError, match=setting) as error:
        validate_demo_release_configuration(synthetic_demo_config(**overrides))
    assert "demo-password" not in str(error.value)


@pytest.mark.parametrize(
    "setting",
    [
        "STRIPE_SECRET_KEY",
        "SENDGRID_API_KEY",
        "NOWPAYMENTS_API_KEY",
        "MT_LOGIN",
        "OPENAI_API_KEY",
    ],
)
def test_demo_configuration_rejects_provider_settings_without_echoing_values(setting):
    provider_value = "demo-provider-value-must-not-be-echoed"
    with pytest.raises(ValueError, match=setting) as error:
        validate_demo_release_configuration(
            synthetic_demo_config(**{setting: provider_value})
        )
    assert provider_value not in str(error.value)


def test_demo_validation_is_disabled_when_the_explicit_demo_flag_is_off():
    # The historical generic deployment validator retains its non-demo contract.
    config = synthetic_production_config(DEMO_RELEASE_ENABLED=False)
    validate_production_configuration(config)
    validate_demo_release_configuration(config)


def test_testing_config_does_not_inherit_demo_or_provider_credentials():
    from src.config import TestingConfig

    assert TestingConfig.DEMO_RELEASE_ENABLED is False
    assert TestingConfig.STRIPE_SECRET_KEY is None
    assert TestingConfig.STRIPE_PUBLISHABLE_KEY is None
    assert TestingConfig.STRIPE_WEBHOOK_SECRET is None
    assert TestingConfig.SENDGRID_API_KEY is None
    assert TestingConfig.NOWPAYMENTS_API_KEY is None
    assert TestingConfig.NOWPAYMENTS_IPN_SECRET is None
    assert TestingConfig.MT_LOGIN is None


def test_get_config_keeps_production_as_default(monkeypatch):
    import src.config as config_module

    monkeypatch.delenv("FLASK_ENV", raising=False)
    assert config_module.get_config() is config_module.ProductionConfig


def test_direct_postgresql_pool_is_bounded_and_deadlines_are_retained():
    from src.config import ProductionConfig

    options = ProductionConfig.SQLALCHEMY_ENGINE_OPTIONS
    assert options["pool_size"] == 5
    assert options["max_overflow"] == 5
    assert options["pool_timeout"] == 30
    assert options["connect_args"]["connect_timeout"] == 10
    assert options["connect_args"]["options"] == "-c statement_timeout=30000"


def test_factory_preserves_testing_guard_before_production_validation(monkeypatch):
    import src.app as app_module

    monkeypatch.setattr(
        app_module,
        "validate_production_configuration",
        lambda config: pytest.fail("production validation ran before testing guard"),
    )
    monkeypatch.setattr(
        app_module,
        "init_db",
        lambda app: pytest.fail("extension initialization reached"),
    )

    with pytest.raises(ValueError, match="explicit testing configuration"):
        app_module.create_app("production")


def test_factory_validates_actual_config_before_extensions(monkeypatch):
    import src.app as app_module

    monkeypatch.setattr(
        app_module,
        "init_db",
        lambda app: pytest.fail("extension initialization reached"),
    )

    with pytest.raises(ValueError, match="DEBUG"):
        app_module.create_app(
            "testing",
            config_overrides={"PRODUCTION": True, "DEBUG": True},
        )
