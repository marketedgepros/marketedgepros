"""
Configuration management for MarketEdgePros
Supports multiple environments: development, staging, production
"""
import os
from datetime import timedelta
from sqlalchemy.pool import NullPool
from dotenv import load_dotenv

# Load environment variables from .env file
if os.environ.get('FLASK_TESTING', '').lower() != 'true':
    load_dotenv()


import secrets

class Config:
    WTF_CSRF_ENABLED = True
    """Base configuration"""
    
    # Application
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    DEBUG = False
    TESTING = False
    # Single-brand ownership is pinned by a reviewed stable DB ID, not email.
    PLATFORM_ROOT_USER_ID = os.getenv('PLATFORM_ROOT_USER_ID')
    EXPANDED_HIERARCHY_ENABLED = False
    # Quote-only foundation: explicit opt-in and no implied merchant currency.
    ORDER_QUOTES_ENABLED = os.getenv('ORDER_QUOTES_ENABLED', 'false').lower() == 'true'
    ORDER_QUOTE_CURRENCY = os.getenv('ORDER_QUOTE_CURRENCY')
    # Not environment-controlled: no provider settlement is activated by this package.
    SYNTHETIC_SETTLEMENT_ENABLED = False
    # Rehearsal-only durable protocol; never a production dispatcher/adapter.
    TRADING_PROTOCOL_REHEARSAL_ENABLED = False
    
    # Database
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False
    
    # Redis
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    
    # Flask-Caching configuration
    CACHE_TYPE = 'RedisCache'
    CACHE_REDIS_URL = REDIS_URL
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
    
    # SendGrid
    SENDGRID_API_KEY = os.getenv('SENDGRID_API_KEY')
    SENDGRID_FROM_EMAIL = os.getenv('SENDGRID_FROM_EMAIL', 'noreply@marketedgepros.com')
    
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
    RATELIMIT_STORAGE_URL = REDIS_URL


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.getenv(
        'DATABASE_URL',
        'postgresql://postgres:postgres@localhost:5432/proptradepro_dev'
    )
    SQLALCHEMY_ECHO = True
    RATELIMIT_ENABLED = False


class TestingConfig(Config):
    """Isolated defaults; PostgreSQL requires an explicit per-run test URL."""
    TESTING = True
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
    SENDGRID_API_KEY = None
    STRIPE_SECRET_KEY = None
    STRIPE_WEBHOOK_SECRET = None
    MT_SERVER = None
    MT_LOGIN = None
    MT_PASSWORD = None
    KYC_ALLOW_PRIVATE_LOCAL_STORAGE = True


class ProductionConfig(Config):
    """Production configuration"""
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')
    
    # Override to ensure SECRET_KEY is set
    SECRET_KEY = os.getenv('SECRET_KEY') or Config.SECRET_KEY
    
    # Database connection pooling - OPTIMIZED FOR PGBOUNCER
    # PgBouncer handles the real DB connections (20 max)
    # We can have many more app-level connections
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 100,  # Large pool (PgBouncer will manage real DB connections)
        'max_overflow': 200,  # Allow bursts (PgBouncer handles it)
        'pool_timeout': 30,  # Shorter timeout (fail fast)
        'pool_recycle': 1800,  # Recycle every 30 min
        'pool_pre_ping': True,  # Test connections before use
        'connect_args': {
            'connect_timeout': 10,
            'application_name': 'MarketEdgePros',
            'options': '-c statement_timeout=30000'  # 30s query timeout
        }
    }
    
    # Ensure critical settings are set in production
    @classmethod
    def init_app(cls, app):
        Config.init_app(app)
        
        # Check for required environment variables
        required_vars = [
            'SECRET_KEY',
            'DATABASE_URL',
            'REDIS_URL',
            'STRIPE_SECRET_KEY',
            'SENDGRID_API_KEY'
        ]
        
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        if missing_vars:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing_vars)}"
            )


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
