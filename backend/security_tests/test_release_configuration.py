"""Isolated regressions for release-ready production configuration."""
import pytest
from flask import Flask

from src.production_safety import (
    MAX_SIGNED_INT32,
    validate_demo_release_configuration,
    validate_production_configuration,
)


_SYNTHETIC_NOWPAYMENTS_API_KEY_31 = "synthetic-np-api-A1b2C3d4E5f6G7"


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


def _account_access_demo_profile(**overrides):
    """Return the only narrow Demo profile allowed to contain Brevo access."""
    config = synthetic_demo_config(
        PUBLIC_ACCOUNT_ACCESS_ENABLED=True,
        EMAIL_PROVIDER="brevo",
        BREVO_API_KEY="synthetic-brevo-key-" + "b" * 40,
        EMAIL_FROM_ADDRESS="accounts@marketedgepros.com",
        EMAIL_FROM_NAME="MarketEdgePros",
        EMAIL_SENDER_VERIFIED=True,
        EMAIL_DOMAIN_AUTHENTICATED=True,
        FRONTEND_URL="https://marketedgepros.com",
    )
    config.update(overrides)
    return config


def test_demo_account_access_profile_allows_only_validated_brevo_delivery():
    validate_demo_release_configuration(_account_access_demo_profile())
    validate_demo_release_configuration(
        _account_access_demo_profile(FRONTEND_URL="https://www.marketedgepros.com/")
    )


@pytest.mark.parametrize("setting", ["SENDGRID_API_KEY", "STRIPE_SECRET_KEY"])
def test_demo_account_access_profile_still_rejects_other_provider_credentials(setting):
    provider_value = "synthetic-provider-key-must-not-be-echoed"
    with pytest.raises(ValueError, match=setting) as error:
        validate_demo_release_configuration(
            _account_access_demo_profile(**{setting: provider_value})
        )
    assert provider_value not in str(error.value)


@pytest.mark.parametrize(
    ("overrides", "setting"),
    [
        ({"EMAIL_PROVIDER": "sendgrid"}, "PUBLIC_ACCOUNT_ACCESS_PROFILE"),
        ({"EMAIL_PROVIDER": 1}, "PUBLIC_ACCOUNT_ACCESS_PROFILE"),
        ({"EMAIL_PROVIDER": None}, "PUBLIC_ACCOUNT_ACCESS_PROFILE"),
        ({"EMAIL_FROM_ADDRESS": "not-a-mailbox"}, "PUBLIC_ACCOUNT_ACCESS_PROFILE"),
        ({"EMAIL_FROM_ADDRESS": "accounts@sub.marketedgepros.com"}, "PUBLIC_ACCOUNT_ACCESS_PROFILE"),
        ({"EMAIL_FROM_ADDRESS": "a" * 65 + "@marketedgepros.com"}, "PUBLIC_ACCOUNT_ACCESS_PROFILE"),
        ({"EMAIL_FROM_ADDRESS": None}, "PUBLIC_ACCOUNT_ACCESS_PROFILE"),
        ({"EMAIL_FROM_NAME": "Market Edge Pros"}, "PUBLIC_ACCOUNT_ACCESS_PROFILE"),
        ({"EMAIL_SENDER_VERIFIED": False}, "PUBLIC_ACCOUNT_ACCESS_PROFILE"),
        ({"EMAIL_SENDER_VERIFIED": "true"}, "EMAIL_SENDER_VERIFIED"),
        ({"EMAIL_DOMAIN_AUTHENTICATED": False}, "PUBLIC_ACCOUNT_ACCESS_PROFILE"),
        ({"EMAIL_DOMAIN_AUTHENTICATED": "true"}, "EMAIL_DOMAIN_AUTHENTICATED"),
        ({"FRONTEND_URL": "http://marketedgepros.com"}, "PUBLIC_ACCOUNT_ACCESS_PROFILE"),
        ({"FRONTEND_URL": "https://marketedgepros.com/reset"}, "PUBLIC_ACCOUNT_ACCESS_PROFILE"),
        ({"FRONTEND_URL": "https://example.invalid"}, "PUBLIC_ACCOUNT_ACCESS_PROFILE"),
        ({"FRONTEND_URL": "https://marketedgepros.com/" + "a" * 2048}, "PUBLIC_ACCOUNT_ACCESS_PROFILE"),
        ({"BREVO_API_KEY": "short"}, "PUBLIC_ACCOUNT_ACCESS_PROFILE"),
        ({"BREVO_API_KEY": " " + "b" * 40}, "PUBLIC_ACCOUNT_ACCESS_PROFILE"),
        ({"BREVO_API_KEY": "b" * 513}, "PUBLIC_ACCOUNT_ACCESS_PROFILE"),
    ],
)
def test_demo_account_access_profile_rejects_invalid_sender_or_origin(overrides, setting):
    with pytest.raises(ValueError, match=setting) as error:
        validate_demo_release_configuration(_account_access_demo_profile(**overrides))
    assert "synthetic-brevo-key" not in str(error.value)


def test_malformed_account_access_boolean_fails_closed_in_production_validation():
    with pytest.raises(ValueError, match="PUBLIC_ACCOUNT_ACCESS_ENABLED"):
        validate_production_configuration(
            synthetic_production_config(PUBLIC_ACCOUNT_ACCESS_ENABLED="true")
        )


@pytest.mark.parametrize("setting", ["EMAIL_SENDER_VERIFIED", "EMAIL_DOMAIN_AUTHENTICATED"])
def test_malformed_account_email_verification_flags_fail_closed_in_production_validation(setting):
    with pytest.raises(ValueError, match=setting):
        validate_production_configuration(synthetic_production_config(**{setting: "true"}))


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
        "BREVO_API_KEY",
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
    from src.config import Config, TestingConfig

    assert Config.EMAIL_PROVIDER == "brevo"
    assert Config.BREVO_API_KEY is None
    assert Config.EMAIL_FROM_ADDRESS is None
    assert Config.EMAIL_FROM_NAME == "MarketEdgePros"
    assert Config.EMAIL_SENDER_VERIFIED is False
    assert Config.EMAIL_DOMAIN_AUTHENTICATED is False
    assert TestingConfig.DEMO_RELEASE_ENABLED is False
    assert TestingConfig.STRIPE_SECRET_KEY is None
    assert TestingConfig.STRIPE_PUBLISHABLE_KEY is None
    assert TestingConfig.STRIPE_WEBHOOK_SECRET is None
    assert TestingConfig.EMAIL_PROVIDER == "brevo"
    assert TestingConfig.BREVO_API_KEY is None
    assert TestingConfig.EMAIL_FROM_ADDRESS is None
    assert TestingConfig.EMAIL_FROM_NAME == "MarketEdgePros"
    assert TestingConfig.EMAIL_SENDER_VERIFIED is False
    assert TestingConfig.EMAIL_DOMAIN_AUTHENTICATED is False
    assert TestingConfig.SENDGRID_API_KEY is None
    assert TestingConfig.PUBLIC_ACCOUNT_ACCESS_ENABLED is False
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


@pytest.mark.parametrize("key", [
    "a" * 40,
    "synthetic-key-1234567890\tabcdefghijk",
    "synthetic-key-1234567890\u00a0abcdefghijk",
    "synthetic-key-1234567890\x7fabcdefghijk",
    "example-brevo-key-1234567890abcdef",
    "your_brevo_key_1234567890abcdef",
])
def test_brevo_key_validator_rejects_transport_invalid_keys(key):
    from src.production_safety import is_valid_brevo_api_key

    assert is_valid_brevo_api_key(key) is False


def test_brevo_key_validator_accepts_shared_valid_shape():
    from src.production_safety import is_valid_brevo_api_key

    assert is_valid_brevo_api_key("synthetic-brevo-key-1234567890-ABC") is True


def _account_access_production_profile(**overrides):
    config = synthetic_production_config(
        PUBLIC_ACCOUNT_ACCESS_ENABLED=True,
        EMAIL_PROVIDER="brevo",
        BREVO_API_KEY="synthetic-brevo-key-1234567890-ABC",
        EMAIL_FROM_ADDRESS="accounts@marketedgepros.com",
        EMAIL_FROM_NAME="MarketEdgePros",
        EMAIL_SENDER_VERIFIED=True,
        EMAIL_DOMAIN_AUTHENTICATED=True,
        FRONTEND_URL="https://marketedgepros.com",
    )
    config.update(overrides)
    return config


def _approved_nowpayments_profile(scope="pilot", **overrides):
    """Return an explicit, synthetic NOWPayments policy without provider access."""
    config = {
        "NOWPAYMENTS_API_KEY": _SYNTHETIC_NOWPAYMENTS_API_KEY_31,
        "NOWPAYMENTS_IPN_SECRET": "synthetic-nowpayments-ipn-secret-" + "b" * 40,
        "NOWPAYMENTS_PILOT_ENABLED": True,
        "NOWPAYMENTS_ACCEPT_EXISTING_IPN": False,
        "NOWPAYMENTS_CHECKOUT_SCOPE": scope,
        "NOWPAYMENTS_APPROVED_POLICY_VERSION": "2026-10-17",
        "NOWPAYMENTS_MERCHANT_CONTEXT": "marketedgepros-pilot",
        "NOWPAYMENTS_CALLBACK_ORIGIN": "https://marketedgepros.com",
        "NOWPAYMENTS_CALLBACK_PATH": "/api/v1/orders/webhooks/nowpayments",
        "NOWPAYMENTS_API_BASE": "https://api.nowpayments.io/v1",
        "NOWPAYMENTS_STORAGE_REVISION": "20261013_000002",
        "NOWPAYMENTS_PILOT_TENANT_IDS": (202,),
        "NOWPAYMENTS_PILOT_ROLES": ("trader",),
        "NOWPAYMENTS_ALLOWED_CURRENCIES": (
            {
                "code": "usdttrc20",
                "label": "USDT on TRC20",
                "network": "TRC20",
                "decimals": 6,
            },
        ),
        "NOWPAYMENTS_OUTCOME_CURRENCY": "usdt",
        "NOWPAYMENTS_FIXED_RATE": False,
        "NOWPAYMENTS_FEE_PAID_BY_USER": False,
    }
    if scope == "pilot":
        config["NOWPAYMENTS_PILOT_PRINCIPAL_IDS"] = (101,)
    config.update(overrides)
    return config


@pytest.mark.parametrize("api_key", [
    None,
    "",
    _SYNTHETIC_NOWPAYMENTS_API_KEY_31[:-1] + "\x7f",
    "placeholder-nowpayments-key-A1b2C3d4",
    "change-me",
    "A1b2C3d4" * 65,
], ids=["blank-none", "blank-empty", "control", "placeholder", "weak", "oversize"])
def test_nowpayments_api_credential_validator_rejects_unsafe_or_placeholder_values(api_key):
    from src.nowpayments_credentials import is_valid_nowpayments_api_key

    assert is_valid_nowpayments_api_key(api_key) is False


def test_complete_nowpayments_profiles_accept_synthetic_31_character_api_credential():
    from src.nowpayments_credentials import is_valid_nowpayments_api_key

    assert len(_SYNTHETIC_NOWPAYMENTS_API_KEY_31) == 31
    assert is_valid_nowpayments_api_key(_SYNTHETIC_NOWPAYMENTS_API_KEY_31) is True
    nowpayments = _approved_nowpayments_profile()
    for validator, profile in (
        (validate_demo_release_configuration, _account_access_demo_profile),
        (validate_production_configuration, _account_access_production_profile),
    ):
        validator(profile(**nowpayments))


def test_complete_nowpayments_profiles_reject_31_character_ipn_signing_secret():
    short_ipn_secret = "synthetic-np-ipn-A1b2C3d4E5f6G7"
    assert len(short_ipn_secret) == 31
    nowpayments = _approved_nowpayments_profile(NOWPAYMENTS_IPN_SECRET=short_ipn_secret)
    for validator, profile in (
        (validate_demo_release_configuration, _account_access_demo_profile),
        (validate_production_configuration, _account_access_production_profile),
    ):
        with pytest.raises(ValueError, match="NOWPAYMENTS_PILOT_POLICY"):
            validator(profile(**nowpayments))


@pytest.mark.parametrize("overrides", [
    {"EMAIL_PROVIDER": "sendgrid", "SENDGRID_API_KEY": "synthetic"},
    {"BREVO_API_KEY": "a" * 40},
    {"EMAIL_FROM_ADDRESS": "bad"},
    {"EMAIL_SENDER_VERIFIED": False},
    {"EMAIL_DOMAIN_AUTHENTICATED": False},
    {"FRONTEND_URL": "https://evil.invalid"},
])
def test_production_public_account_rejects_incomplete_brevo_profile(overrides):
    with pytest.raises(ValueError):
        validate_production_configuration(_account_access_production_profile(**overrides))


def test_production_public_account_accepts_complete_brevo_profile():
    validate_production_configuration(_account_access_production_profile())


@pytest.mark.parametrize(("scope", "has_principal_whitelist"), [
    ("pilot", True),
    ("customers", False),
])
def test_public_account_accepts_complete_brevo_and_nowpayments_profiles(
    scope, has_principal_whitelist,
):
    nowpayments = _approved_nowpayments_profile(scope)
    assert nowpayments["NOWPAYMENTS_CALLBACK_PATH"] == "/api/v1/orders/webhooks/nowpayments"
    assert ("NOWPAYMENTS_PILOT_PRINCIPAL_IDS" in nowpayments) is has_principal_whitelist
    for validator, profile in (
        (validate_demo_release_configuration, _account_access_demo_profile),
        (validate_production_configuration, _account_access_production_profile),
    ):
        validator(profile(**nowpayments))


@pytest.mark.parametrize("nowpayments", [
    {"NOWPAYMENTS_PILOT_ENABLED": True},
    _approved_nowpayments_profile(NOWPAYMENTS_PILOT_PRINCIPAL_IDS=()),
    _approved_nowpayments_profile(
        "customers", NOWPAYMENTS_PILOT_TENANT_IDS=(),
    ),
])
def test_public_account_rejects_partial_or_invalid_nowpayments_profiles(nowpayments):
    for validator, profile in (
        (validate_demo_release_configuration, _account_access_demo_profile),
        (validate_production_configuration, _account_access_production_profile),
    ):
        with pytest.raises(ValueError, match="NOWPAYMENTS_PILOT_POLICY"):
            validator(profile(**nowpayments))


@pytest.mark.parametrize("activation", [
    {},
    {"NOWPAYMENTS_PILOT_ENABLED": True},
    {"NOWPAYMENTS_ACCEPT_EXISTING_IPN": True},
])
def test_nowpayments_credentials_without_policy_are_rejected_including_callback_only(
    activation,
):
    credentials_without_policy = {
        "NOWPAYMENTS_API_KEY": "synthetic-nowpayments-api-key-" + "a" * 40,
        "NOWPAYMENTS_IPN_SECRET": "synthetic-nowpayments-ipn-secret-" + "b" * 40,
        **activation,
    }
    for validator, profile in (
        (validate_demo_release_configuration, _account_access_demo_profile),
        (validate_production_configuration, _account_access_production_profile),
    ):
        with pytest.raises(ValueError) as error:
            validator(profile(**credentials_without_policy))
        if activation or validator is validate_production_configuration:
            assert "NOWPAYMENTS_PILOT_POLICY" in str(error.value)
        else:
            assert "NOWPAYMENTS_API_KEY" in str(error.value)


@pytest.mark.parametrize("setting", [
    "STRIPE_SECRET_KEY",
    "STRIPE_PUBLISHABLE_KEY",
    "STRIPE_WEBHOOK_SECRET",
])
def test_public_account_still_rejects_stripe_settings(setting):
    for validator, profile in (
        (validate_demo_release_configuration, _account_access_demo_profile),
        (validate_production_configuration, _account_access_production_profile),
    ):
        with pytest.raises(ValueError, match="PUBLIC_ACCOUNT_ACCESS_PAYMENT_SETTINGS"):
            validator(profile(**{setting: "synthetic-stripe-value"}))


def test_demo_standalone_approved_nowpayments_pilot_validation_remains_independent():
    config = synthetic_demo_config(NOWPAYMENTS_PILOT_ENABLED=True)
    # Existing detailed pilot policy validator still independently gates payment activation.
    with pytest.raises(ValueError, match="NOWPAYMENTS_PILOT_POLICY"):
        validate_demo_release_configuration(config)
