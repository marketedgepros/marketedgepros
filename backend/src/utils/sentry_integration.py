"""
Sentry integration for MarketEdgePros
Add this to app.py after app creation
"""

import sentry_sdk
from sentry_sdk.integrations.flask import FlaskIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from sentry_sdk.integrations.redis import RedisIntegration

def init_sentry(app):
    """Initialize Sentry error tracking"""
    sentry_dsn = app.config.get('SENTRY_DSN')
    
    if not sentry_dsn:
        app.logger.warning('Sentry DSN not configured - error tracking disabled')
        return
    
    environment = app.config.get('ENV', 'production')
    
    sentry_sdk.init(
        dsn=sentry_dsn,
        integrations=[
            FlaskIntegration(),
            SqlalchemyIntegration(),
            RedisIntegration(),
        ],
        
        # Set traces_sample_rate to 1.0 to capture 100% of transactions for performance monitoring.
        # We recommend adjusting this value in production.
        traces_sample_rate=0.1 if environment == 'production' else 1.0,
        
        # Set profiles_sample_rate to 1.0 to profile 100% of sampled transactions.
        # We recommend adjusting this value in production.
        profiles_sample_rate=0.1 if environment == 'production' else 1.0,
        
        # Environment
        environment=environment,
        
        # Release version
        release=app.config.get('VERSION', '1.0.0'),
        
        # Send default PII (Personally Identifiable Information)
        send_default_pii=False,
        
        # Before send callback to filter sensitive data
        before_send=before_send_filter,
    )
    
    app.logger.info(f'Sentry initialized for environment: {environment}')

def before_send_filter(event, hint):
    """Filter sensitive data before sending to Sentry"""
    # Remove sensitive headers
    if 'request' in event and 'headers' in event['request']:
        headers = event['request']['headers']
        sensitive_headers = ['Authorization', 'Cookie', 'X-API-Key']
        for header in sensitive_headers:
            if header in headers:
                headers[header] = '[Filtered]'
    
    # Remove sensitive POST data
    if 'request' in event and 'data' in event['request']:
        data = event['request']['data']
        if isinstance(data, dict):
            sensitive_fields = ['password', 'token', 'secret', 'api_key']
            for field in sensitive_fields:
                if field in data:
                    data[field] = '[Filtered]'
    
    return event

# Usage in app.py:
# from src.utils.sentry_integration import init_sentry
# init_sentry(app)
