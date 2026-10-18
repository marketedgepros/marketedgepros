"""
Configuration management for MarketEdgePros
Supports multiple environments: development, staging, production
"""
import os
import json
from datetime import timedelta
from sqlalchemy.pool import NullPool
from dotenv import load_dotenv

# Load environment variables from .env file
if os.environ.get('FLASK_TESTING', '').lower() != 'true':
    load_dotenv()


import secrets


def _strict_boolean_env(name, default=False):
    """Read a feature flag without treating malformed values as an opt-in."""
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized == 'true':
        return True
    if normalized == 'false':
        return False
    # Validators reject this in a deployment; callers also see a falsey value.
    return None


def _payment_policy_json(name, default=None):
    """Bounded server-only configuration; error messages never contain values."""
    raw = os.getenv(name)
    if not raw:
        return default
    if len(raw) > 8192:
        raise ValueError("Invalid payment configuration field: " + name)
    try:
        return json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, RecursionError):
        raise ValueError("Invalid payment configuration field: " + name) from None

class Config:
    WTF_CSRF_ENABLED = True
    """Base configuration"""

    # Production-only deployment checks key off this explicit profile marker.
    PRODUCTION = False

    # Application
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    DEBUG = False
    TESTING = False
    # Demo mode is an explicit, deployment-scoped feature flag.  It defaults
    # closed so a normal release retains its established route behavior.
    DEMO_RELEASE_ENABLED = os.getenv('DEMO_RELEASE_ENABLED', 'false').lower() == 'true'
    # Public registration and recovery are separately reviewed from the demo
    # release itself. An invalid environment value cannot enable the feature.
    PUBLIC_ACCOUNT_ACCESS_ENABLED = _strict_boolean_env(
        'PUBLIC_ACCOUNT_ACCESS_ENABLED', False
    )
    # Single-brand ownership is pinned by a reviewed stable DB ID, not email.
    PLATFORM_ROOT_USER_ID = os.getenv('PLATFORM_ROOT_USER_ID')
    EXPANDED_HIERARCHY_ENABLED = False
    DEPLOYMENT_SHA = os.getenv('DEPLOYMENT_SHA')
    EXPECTED_SCHEMA_REVISION = os.getenv('EXPECTED_SCHEMA_REVISION')
    # Quote-only foundation: explicit opt-in and no implied merchant currency.
    ORDER_QUOTES_ENABLED = os.getenv('ORDER_QUOTES_ENABLED', 'false').lower() == 'true'
    ORDER_QUOTE_CURRENCY = os.getenv('ORDER_QUOTE_CURRENCY')
    # Not environment-controlled: no provider settlement is activated by this package.
    SYNTHETIC_SETTLEMENT_ENABLED = False
    # Rehearsal-only durable protocol; never a production dispatcher/adapter.
    TRADING_PROTOCOL_REHEARSAL_ENABLED = False
    # Internal synthetic affiliate rehearsal only; no environment activation.
    AFFILIATE_LIFECYCLE_REHEARSAL_ENABLED = False
    
    # Database
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False
    
    # Redis
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    
    # Flask-Caching configuration
    CACHE_TYPE = 'RedisCache'
    # Cache and limiter may be routed independently in deployment. They retain
    # the shared Redis default unless their dedicated environment variables are set.
    CACHE_REDIS_URL = os.getenv('CACHE_REDIS_URL', REDIS_URL)
    CACHE_DEFAULT_TIMEOUT = 600  # 10 minutes
    CACHE_KEY_PREFIX = 'marketedgepros_'
    
    # JWT
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', SECRET_KEY)
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=30)
    
    # CORS
    CORS_ORIGINS = os.getenv('CORS_ORIGINS', 'http://localhost:3000,http://localhost:5173,http://146.190.21.113,http://146.190.21.113:3000,http://marketedgepros.com,https://marketedgepros.com').split(',')
    
    # Stripe
    STRIPE_SECRET_KEY = os.getenv('STRIPE_SECRET_KEY')
    STRIPE_PUBLISHABLE_KEY = os.getenv('STRIPE_PUBLISHABLE_KEY')
    STRIPE_WEBHOOK_SECRET = os.getenv('STRIPE_WEBHOOK_SECRET')

    # Server-only credential binding. Presence never enables checkout/settlement.
    NOWPAYMENTS_API_KEY = os.getenv('NOWPAYMENTS_API_KEY') or None
    NOWPAYMENTS_IPN_SECRET = os.getenv('NOWPAYMENTS_IPN_SECRET') or None
    # Custom checkout remains closed until a reviewed deployment supplies every
    # server-only policy field.  There are intentionally no monetary, asset,
    # outcome-wallet, fee, or allowlist defaults in this source tree.
    NOWPAYMENTS_PILOT_ENABLED = os.getenv('NOWPAYMENTS_PILOT_ENABLED', 'false').lower() == 'true'
    NOWPAYMENTS_ACCEPT_EXISTING_IPN = os.getenv('NOWPAYMENTS_ACCEPT_EXISTING_IPN', 'false').lower() == 'true'
    NOWPAYMENTS_CHECKOUT_SCOPE = os.getenv('NOWPAYMENTS_CHECKOUT_SCOPE', 'pilot')
    NOWPAYMENTS_APPROVED_POLICY_VERSION = os.getenv('NOWPAYMENTS_APPROVED_POLICY_VERSION') or None
    NOWPAYMENTS_MERCHANT_CONTEXT = os.getenv('NOWPAYMENTS_MERCHANT_CONTEXT') or None
    NOWPAYMENTS_CALLBACK_ORIGIN = os.getenv('NOWPAYMENTS_CALLBACK_ORIGIN') or None
    NOWPAYMENTS_CALLBACK_PATH = '/api/v1/orders/webhooks/nowpayments'
    NOWPAYMENTS_API_BASE = 'https://api.nowpayments.io/v1'
    NOWPAYMENTS_STORAGE_REVISION = os.getenv('NOWPAYMENTS_STORAGE_REVISION') or None
    NOWPAYMENTS_PILOT_PRINCIPAL_IDS = _payment_policy_json('NOWPAYMENTS_PILOT_PRINCIPAL_IDS', ())
    NOWPAYMENTS_PILOT_TENANT_IDS = _payment_policy_json('NOWPAYMENTS_PILOT_TENANT_IDS', ())
    NOWPAYMENTS_PILOT_ROLES = _payment_policy_json('NOWPAYMENTS_PILOT_ROLES', ())
    NOWPAYMENTS_ALLOWED_CURRENCIES = _payment_policy_json('NOWPAYMENTS_ALLOWED_CURRENCIES', ())
    NOWPAYMENTS_OUTCOME_CURRENCY = os.getenv('NOWPAYMENTS_OUTCOME_CURRENCY') or None
    NOWPAYMENTS_FIXED_RATE = _payment_policy_json('NOWPAYMENTS_FIXED_RATE')
    NOWPAYMENTS_FEE_PAID_BY_USER = _payment_policy_json('NOWPAYMENTS_FEE_PAID_BY_USER')
    NOWPAYMENTS_REFRESH_MIN_SECONDS = 30

    # Account-access delivery is Brevo-only and never relies on an implicit
    # sender or origin. The narrow Demo profile validates every outbound
    # value before a public account-access opt-in is accepted.
    EMAIL_PROVIDER = os.getenv('EMAIL_PROVIDER', 'brevo')
    BREVO_API_KEY = os.getenv('BREVO_API_KEY') or None
    EMAIL_FROM_ADDRESS = os.getenv('EMAIL_FROM_ADDRESS') or None
    EMAIL_FROM_NAME = os.getenv('EMAIL_FROM_NAME', 'MarketEdgePros')
    EMAIL_SENDER_VERIFIED = _strict_boolean_env('EMAIL_SENDER_VERIFIED', False)
    EMAIL_DOMAIN_AUTHENTICATED = _strict_boolean_env(
        'EMAIL_DOMAIN_AUTHENTICATED', False
    )
    # Retained only to detect and reject the explicitly disallowed legacy
    # credential in a Demo deployment; it is not a supported email profile.
    SENDGRID_API_KEY = os.getenv('SENDGRID_API_KEY') or None
    FRONTEND_URL = os.getenv('FRONTEND_URL') or None

    # MetaTrader (placeholder for future implementation)
    MT_SERVER = os.getenv('MT_SERVER')
    MT_LOGIN = os.getenv('MT_LOGIN')
    MT_PASSWORD = os.getenv('MT_PASSWORD')
    
    # File Upload
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max file size
    UPLOAD_FOLDER = os.getenv('UPLOAD_FOLDER', '/tmp/uploads')
    KYC_PRIVATE_UPLOAD_FOLDER = os.getenv('KYC_PRIVATE_UPLOAD_FOLDER', '/var/lib/marketedgepros/private-kyc')
    KYC_ALLOW_PRIVATE_LOCAL_STORAGE = os.getenv('KYC_ALLOW_PRIVATE_LOCAL_STORAGE', 'false').lower() == 'true'
    
    # Pagination
    ITEMS_PER_PAGE = 20
    
    # Rate Limiting
    RATELIMIT_ENABLED = True
    RATELIMIT_STORAGE_URL = os.getenv('RATELIMIT_STORAGE_URL', REDIS_URL)


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.getenv(
        'DATABASE_URL',
        'postgresql://postgres:postgres@localhost:5432/marketedgepros_dev'
    )
    SQLALCHEMY_ECHO = True
    RATELIMIT_ENABLED = False


class TestingConfig(Config):
    """Isolated defaults; PostgreSQL requires an explicit per-run test URL."""
    TESTING = True
    # Tests must opt into the boundary explicitly; do not inherit a parent
    # deployment's demo flag when constructing an in-process application.
    DEMO_RELEASE_ENABLED = False
    # Existing legacy-feature suites remain explicit future-mode regressions.
    EXPANDED_HIERARCHY_ENABLED = True
    ORDER_QUOTES_ENABLED = False
    ORDER_QUOTE_CURRENCY = None
    SECRET_KEY = 'isolated-test-secret-not-for-production'
    JWT_SECRET_KEY = 'isolated-test-jwt-secret-not-for-production'
    SQLALCHEMY_DATABASE_URI = os.getenv('TEST_DATABASE_URL', 'sqlite:///:memory:')
    SQLALCHEMY_ENGINE_OPTIONS = {}
    REDIS_URL = None
    CACHE_TYPE = 'SimpleCache'
    CACHE_REDIS_URL = None
    RATELIMIT_ENABLED = False
    RATELIMIT_STORAGE_URL = 'memory://'
    WTF_CSRF_ENABLED = False
    MAIL_SUPPRESS_SEND = True
    EMAIL_PROVIDER = 'brevo'
    BREVO_API_KEY = None
    EMAIL_FROM_ADDRESS = None
    EMAIL_FROM_NAME = 'MarketEdgePros'
    EMAIL_SENDER_VERIFIED = False
    EMAIL_DOMAIN_AUTHENTICATED = False
    SENDGRID_API_KEY = None
    FRONTEND_URL = None
    PUBLIC_ACCOUNT_ACCESS_ENABLED = False
    STRIPE_SECRET_KEY = None
    STRIPE_PUBLISHABLE_KEY = None
    STRIPE_WEBHOOK_SECRET = None
    NOWPAYMENTS_API_KEY = None
    NOWPAYMENTS_IPN_SECRET = None
    NOWPAYMENTS_PILOT_ENABLED = False
    NOWPAYMENTS_ACCEPT_EXISTING_IPN = False
    NOWPAYMENTS_CHECKOUT_SCOPE = 'pilot'
    NOWPAYMENTS_APPROVED_POLICY_VERSION = None
    NOWPAYMENTS_MERCHANT_CONTEXT = None
    NOWPAYMENTS_CALLBACK_ORIGIN = None
    NOWPAYMENTS_STORAGE_REVISION = None
    NOWPAYMENTS_PILOT_PRINCIPAL_IDS = ()
    NOWPAYMENTS_PILOT_TENANT_IDS = ()
    NOWPAYMENTS_PILOT_ROLES = ()
    NOWPAYMENTS_ALLOWED_CURRENCIES = ()
    NOWPAYMENTS_OUTCOME_CURRENCY = None
    NOWPAYMENTS_FIXED_RATE = None
    NOWPAYMENTS_FEE_PAID_BY_USER = None
    MT_SERVER = None
    MT_LOGIN = None
    MT_PASSWORD = None
    KYC_ALLOW_PRIVATE_LOCAL_STORAGE = True


class ProductionConfig(Config):
    """Production configuration"""
    PRODUCTION = True
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')

    # Missing values remain missing so production validation can fail closed.
    SECRET_KEY = os.getenv('SECRET_KEY')
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', SECRET_KEY)
    REDIS_URL = os.getenv('REDIS_URL')
    CACHE_REDIS_URL = os.getenv('CACHE_REDIS_URL', REDIS_URL)
    RATELIMIT_STORAGE_URL = os.getenv('RATELIMIT_STORAGE_URL', REDIS_URL)

    # Direct PostgreSQL deployment: bound the application pool to at most ten
    # checked-out/overflow connections while preserving connection/query deadlines.
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 5,
        'max_overflow': 5,
        'pool_timeout': 30,  # Shorter timeout (fail fast)
        'pool_recycle': 1800,  # Recycle every 30 min
        'pool_pre_ping': True,  # Test connections before use
        'connect_args': {
            'connect_timeout': 10,
            'application_name': 'MarketEdgePros',
            'options': '-c statement_timeout=30000'  # 30s query timeout
        }
    }


# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}


def get_config():
    """Get configuration based on environment"""
    env = os.getenv('FLASK_ENV', 'production')  # Default to production
    config_class = config.get(env, config['production'])
    return config_class
