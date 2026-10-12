"""Fail-closed validation for the production deployment configuration."""
import re
from urllib.parse import urlparse

from sqlalchemy.engine import make_url


MINIMUM_SECRET_LENGTH = 32
MAX_SIGNED_INT32 = 2**31 - 1
_CANONICAL_POSITIVE_ID = re.compile(r"[1-9][0-9]*\Z")
_KNOWN_WEAK_SECRETS = frozenset({
    "dev-secret-key-change-in-production",
    "change-me",
    "secret",
    "default",
})
_DEMO_DATABASE_NAMES = frozenset({
    "marketedgepros_demo_20261012",
    "marketedgepros_candidate_20261012",
})
_DEMO_PROVIDER_SETTINGS = frozenset({
    "STRIPE_SECRET_KEY",
    "STRIPE_PUBLISHABLE_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "SENDGRID_API_KEY",
    "NOWPAYMENTS_API_KEY",
    "NOWPAYMENTS_IPN_SECRET",
    "MT_SERVER",
    "MT_LOGIN",
    "MT_PASSWORD",
    "OPENAI_API_KEY",
    "DO_SPACES_KEY",
    "DO_SPACES_SECRET",
    "SPACES_ACCESS_KEY",
    "SPACES_SECRET_KEY",
    "DISCORD_BOT_TOKEN",
    "TWILIO_AUTH_TOKEN",
    "VAULT_TOKEN",
})


def _is_strong_secret(value):
    """Accept a non-default, deployment-sized signing secret without logging it."""
    return (
        isinstance(value, str)
        and len(value) >= MINIMUM_SECRET_LENGTH
        and value not in _KNOWN_WEAK_SECRETS
    )


def _is_postgresql_url(value):
    """Check only URL shape; this function must never open a database connection."""
    if not isinstance(value, str) or not value:
        return False
    try:
        url = make_url(value)
    except Exception:
        return False
    return (
        url.drivername.startswith("postgresql")
        and bool(url.host)
        and bool(url.database)
    )


def _is_redis_url(value):
    """Check Redis URL syntax only; no name resolution or connection is attempted."""
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = urlparse(value)
        # Accessing ``port`` also rejects malformed non-numeric ports.
        parsed.port
    except ValueError:
        return False
    return parsed.scheme in {"redis", "rediss"} and bool(parsed.hostname)


def _is_canonical_positive_id(value):
    """Permit positive signed-32-bit IDs or canonical environment strings."""
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return 0 < value <= MAX_SIGNED_INT32
    return (
        isinstance(value, str)
        and bool(_CANONICAL_POSITIVE_ID.fullmatch(value))
        and (
            len(value) < len(str(MAX_SIGNED_INT32))
            or (len(value) == len(str(MAX_SIGNED_INT32)) and value <= str(MAX_SIGNED_INT32))
        )
    )


def _is_demo_database_url(value):
    """Validate the one local, separately named demo database target."""
    if not isinstance(value, str) or not value:
        return False
    try:
        url = make_url(value)
    except Exception:
        return False
    return (
        url.drivername.startswith("postgresql")
        and url.host in {"localhost", "127.0.0.1"}
        and url.port == 5432
        and url.username == "marketedgepros_demo"
        and url.database in _DEMO_DATABASE_NAMES
        # libpq-style query parameters can redirect a target despite an
        # otherwise acceptable URL, so demo endpoints have no overrides.
        and not url.query
    )


def _is_demo_redis_url(value, database):
    """Validate an exact local demo Redis endpoint without connecting to it."""
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "redis"
        and parsed.hostname == "127.0.0.1"
        and port == 6380
        and parsed.path == f"/{database}"
        and not parsed.params
        and not parsed.query
        and not parsed.fragment
        # Dedicated Redis at 6380 has its own freshly generated password.
        and parsed.username in {None, ""}
        and isinstance(parsed.password, str)
        and len(parsed.password) >= MINIMUM_SECRET_LENGTH
    )


def validate_demo_release_configuration(config):
    """Fail closed for the intentionally narrow, locally isolated demo release.

    This validation is semantic only: it parses configuration values but never
    resolves names or opens a database, Redis, or provider connection.  Unit
    test applications use in-memory resources guarded by ``testing_safety``;
    they exercise the request boundary separately and are not deployments.
    """
    if config.get("DEMO_RELEASE_ENABLED") is not True:
        return
    if config.get("TESTING") is True:
        return

    invalid = []
    if not _is_demo_database_url(config.get("SQLALCHEMY_DATABASE_URI")):
        invalid.append("SQLALCHEMY_DATABASE_URI")
    for setting, database in (
        ("REDIS_URL", 0),
        ("CACHE_REDIS_URL", 1),
        ("RATELIMIT_STORAGE_URL", 2),
    ):
        if not _is_demo_redis_url(config.get(setting), database):
            invalid.append(setting)
    if not _is_canonical_positive_id(config.get("PLATFORM_ROOT_USER_ID")):
        invalid.append("PLATFORM_ROOT_USER_ID")
    for setting in sorted(_DEMO_PROVIDER_SETTINGS):
        if config.get(setting) is not None:
            invalid.append(setting)

    if invalid:
        raise ValueError("Invalid demo release configuration: " + ", ".join(invalid))


def validate_production_configuration(config):
    """Validate only a production-marked Flask config before extension setup.

    Error messages name invalid settings but deliberately never include URL or secret
    values. Provider credentials are absent by design: disabled providers do not
    participate in deployment readiness.
    """
    if config.get("PRODUCTION") is not True:
        return

    invalid = []
    if config.get("DEBUG"):
        invalid.append("DEBUG")
    if config.get("RATELIMIT_ENABLED") is not True:
        invalid.append("RATELIMIT_ENABLED")
    if config.get("CACHE_TYPE") not in {"RedisCache", "redis"}:
        invalid.append("CACHE_TYPE")
    if not _is_strong_secret(config.get("SECRET_KEY")):
        invalid.append("SECRET_KEY")
    if not _is_strong_secret(config.get("JWT_SECRET_KEY")):
        invalid.append("JWT_SECRET_KEY")
    if not _is_postgresql_url(config.get("SQLALCHEMY_DATABASE_URI")):
        invalid.append("SQLALCHEMY_DATABASE_URI")
    for setting in ("REDIS_URL", "CACHE_REDIS_URL", "RATELIMIT_STORAGE_URL"):
        if not _is_redis_url(config.get(setting)):
            invalid.append(setting)
    if not _is_canonical_positive_id(config.get("PLATFORM_ROOT_USER_ID")):
        invalid.append("PLATFORM_ROOT_USER_ID")

    if invalid:
        raise ValueError(
            "Invalid production configuration: " + ", ".join(invalid)
        )
