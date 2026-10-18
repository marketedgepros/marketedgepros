"""
Main Flask application factory
"""
import os
# GPT-5 FIX #3: Make gevent cooperative for true async concurrency
# MUST be at the very top before any other imports
if os.environ.get('FLASK_TESTING', '').lower() != 'true':
    import gevent.monkey
    gevent.monkey.patch_all()

    # Production-only cooperative I/O. Tests retain normal socket semantics
    # so their outbound-network deny fixture cannot be bypassed by patching.
    from psycogreen.gevent import patch_psycopg
    patch_psycopg()

from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_wtf.csrf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from src.extensions import limiter
from src.config import get_config
from src.database import db, init_db
from src.production_safety import (
    validate_demo_release_configuration,
    validate_production_configuration,
)
from src.middleware.tenant_middleware import init_tenant_middleware
import logging
from prometheus_flask_exporter import PrometheusMetrics


def create_app(config_name=None, *, config_overrides=None):
    """Create and configure Flask application"""
    app = Flask(__name__)
    
    # Load configuration
    if config_name:
        from src.config import config
        app.config.from_object(config[config_name])
    else:
        config_class = get_config()
        app.config.from_object(config_class)

    # Overrides must precede extension initialization (not be applied later by
    # a fixture, when the production engine has already been constructed).
    testing_requested = bool(app.config.get('TESTING')) or config_name == 'testing'
    if config_overrides is not None:
        if testing_requested and not config_overrides.get('TESTING', True):
            raise ValueError('Testing configuration cannot be disabled by overrides')
        app.config.update(config_overrides)
    from src.testing_safety import validate_testing_resources
    validate_testing_resources(app.config)
    # Validate the final application config, including controlled test overrides,
    # before an extension can construct a database or Redis client.
    validate_production_configuration(app.config)
    validate_demo_release_configuration(app.config)

    # This must precede tenant middleware and route decorators.  In particular,
    # a blocked request cannot deserialize its body, resolve a tenant, touch SQL,
    # invoke an auth service, or contact an email/provider service.
    if app.config.get('DEMO_RELEASE_ENABLED') is True:
        @app.before_request
        def enforce_demo_release_boundary():
            path = request.path
            blocked_auth_action = (
                path in {
                    '/api/v1/auth/register',
                    '/api/v1/auth/resend-verification',
                    '/api/v1/auth/password/reset-request',
                    '/api/v1/auth/password/reset',
                    '/api/v1/auth/password/verify-code',
                    '/api/v1/auth/password/reset-with-code',
                }
                or path == '/api/v1/auth/verify-email'
                or path.startswith('/api/v1/auth/verify-email/')
            )
            # Demo remains closed unless the independently validated account
            # access profile is deliberately enabled. This does not relax
            # chat, payment, order, or MT5 containment in any way.
            if blocked_auth_action and app.config.get('PUBLIC_ACCOUNT_ACCESS_ENABLED') is not True:
                return jsonify({
                    'error': 'Registration and email actions are unavailable in this demo release.',
                    'code': 'DEMO_ACTION_UNAVAILABLE',
                }), 503
            if path == '/api/v1/chat' or path.startswith('/api/v1/chat/'):
                return jsonify({
                    'error': 'Chat provider is unavailable in this demo release.',
                    'code': 'DEMO_ACTION_UNAVAILABLE',
                }), 503

    # Initialize extensions
    # Initialize Prometheus metrics
    metrics = PrometheusMetrics(app, group_by="endpoint") if not app.testing else None
    init_db(app)
    
    # Initialize hierarchy scoping system
    with app.app_context():
        from src.utils.hierarchy_scoping import init_hierarchy_scoping
        from src.models.user import User
        init_hierarchy_scoping(db, User)
    
    # Initialize caching
    from src import cache
    cache.init_app(app)
    
    # Initialize tenant middleware
    init_tenant_middleware(app)
    
    # Enable CORS
    csrf = CSRFProtect(app)
    
    # Exempt API endpoints from CSRF protection (they use JWT authentication)
    # This is the standard approach for JWT-based APIs
    app.config['WTF_CSRF_CHECK_DEFAULT'] = False
    cors_origins = app.config.get('CORS_ORIGINS', ['http://localhost:3000'])
    if isinstance(cors_origins, str):
        cors_origins = cors_origins.split(',')
    elif not isinstance(cors_origins, list):
        cors_origins = ['*']
    CORS(app, 
         resources={r"/api/*": {
             "origins": cors_origins,
             "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
             "allow_headers": ["Content-Type", "Authorization", "X-CSRF-Token", "Idempotency-Key"],
             "supports_credentials": True
         }})
    
    # Rate Limiting
    if app.config.get('RATELIMIT_ENABLED'):
        limiter = Limiter(
            app=app,
            key_func=get_remote_address,
            storage_uri=app.config.get('RATELIMIT_STORAGE_URL'),
            default_limits=["5000 per day", "1000 per hour"]
        )
        limiter.init_app(app)
        app.limiter = limiter
    
    # Initialize Talisman for security headers (skip in testing)
    if not app.testing:
        Talisman(app, force_https=False)

    @app.after_request
    def add_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self' https://api.marketedgepros.com"
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        return response
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Register blueprints
    from src.routes.auth import auth_bp
    from src.routes.health import health_bp
    from src.routes.users import users_bp
    from src.routes.profile import profile_bp
    from src.routes.programs import programs_bp
    from src.routes.payments import payments_bp
    from src.routes.orders import orders_bp
    from src.routes.uploads import uploads_bp
    from src.routes.agents import agents_bp
    from src.routes.admin import admin_bp
    from src.routes.payouts import payouts_bp
    from src.routes.scaling import scaling_bp
    from src.routes.traders import traders_bp
    from src.routes.kyc import kyc_bp
    from src.routes.challenges import challenges_bp
    from src.routes.mt5_routes import mt5_bp
    from src.routes.reports import reports_bp
    from src.routes.hierarchy import hierarchy_bp
    from src.routes.crm import crm_bp
    from src.routes.security import security_bp
    from src.routes.payment_approvals import bp as payment_approvals_bp
    from src.routes.chat import chat_bp
    from src.routes.tenants import tenants_bp
    from src.routes.roles import roles_bp
    from src.routes.analytics import analytics_bp
    from src.routes.commissions import commissions_bp
    from src.routes.wallet import wallet_bp
    from src.routes.notifications import notifications_bp
    from src.routes.leads import leads_bp
    from src.routes.blog import blog_bp
    from src.routes.support import support_bp
    from src.routes.affiliate import affiliate_bp
    from src.routes.nowpayments import nowpayments_bp
    
    app.register_blueprint(auth_bp, url_prefix='/api/v1/auth')
    app.register_blueprint(health_bp, url_prefix='/api/v1')
    app.register_blueprint(users_bp, url_prefix='/api/v1/users')
    app.register_blueprint(profile_bp, url_prefix='/api/v1/profile')
    app.register_blueprint(programs_bp, url_prefix='/api/v1/programs')
    app.register_blueprint(payments_bp, url_prefix='/api/v1/payments')
    app.register_blueprint(orders_bp, url_prefix='/api/v1/orders')
    app.register_blueprint(payouts_bp)
    app.register_blueprint(scaling_bp)
    app.register_blueprint(uploads_bp, url_prefix='/api/v1/uploads')
    app.register_blueprint(agents_bp, url_prefix='/api/v1/agents')
    app.register_blueprint(admin_bp, url_prefix='/api/v1/admin')
    app.register_blueprint(traders_bp, url_prefix='/api/v1/traders')
    app.register_blueprint(kyc_bp, url_prefix='/api/v1/kyc')
    app.register_blueprint(challenges_bp, url_prefix='/api/v1/challenges')
    app.register_blueprint(mt5_bp)  # MT5 has its own prefix defined in the blueprint
    app.register_blueprint(reports_bp, url_prefix='/api/v1/reports')
    app.register_blueprint(hierarchy_bp, url_prefix='/api/v1/hierarchy')
    app.register_blueprint(crm_bp, url_prefix='/api/v1/crm')
    app.register_blueprint(security_bp, url_prefix='/api/v1/security')
    app.register_blueprint(payment_approvals_bp)
    app.register_blueprint(chat_bp, url_prefix='/api/v1/chat')
    app.register_blueprint(tenants_bp, url_prefix='/api/v1/tenants')
    app.register_blueprint(roles_bp, url_prefix='/api/v1')
    app.register_blueprint(analytics_bp, url_prefix='/api/v1/analytics')
    app.register_blueprint(commissions_bp)
    app.register_blueprint(wallet_bp, url_prefix='/api/v1/wallet')
    app.register_blueprint(notifications_bp, url_prefix='/api/v1/notifications')
    app.register_blueprint(leads_bp, url_prefix='/api/v1/leads')
    app.register_blueprint(blog_bp, url_prefix='/api/v1/blog')
    app.register_blueprint(support_bp, url_prefix='/api/v1/support')
    app.register_blueprint(affiliate_bp, url_prefix='/api/v1/affiliate')
    app.register_blueprint(nowpayments_bp)
    
    # Health check endpoint
    @app.route('/health', methods=['GET'])
    def health_check():
        return jsonify({
            'status': 'healthy',
            'service': 'MarketEdgePros API',
            'version': '1.0.0'
        }), 200
    
    # Root endpoint
    @app.route('/', methods=['GET'])
    def index():
        return jsonify({
            'message': 'MarketEdgePros API',
            'version': '1.0.0',
            'endpoints': {
                'health': '/health',
                'auth': '/api/v1/auth',
                'profile': '/api/v1/profile',
                'programs': '/api/v1/programs',
                'payments': '/api/v1/payments',
                'uploads': '/api/v1/uploads',
                'agents': '/api/v1/agents',
                'admin': '/api/v1/admin',
                'traders': '/api/v1/traders',
                'kyc': '/api/v1/kyc',
                'challenges': '/api/v1/challenges',
                'mt5': '/api/mt5',
                'reports': '/api/v1/reports',
                'hierarchy': '/api/v1/hierarchy',
                'crm': '/api/v1/crm',
                'payment_approvals': '/api/v1/payment-approvals',
                'chat': '/api/v1/chat',
                'tenants': '/api/v1/tenants'
            }
        }), 200
    
    # Error handlers
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({'error': 'Resource not found'}), 404
    
    @app.errorhandler(500)
    def internal_error(error):
        return jsonify({'error': 'Internal server error'}), 500
    
    @app.errorhandler(Exception)
    def handle_exception(error):
        # Don't catch HTTP exceptions (like validation errors)
        from werkzeug.exceptions import HTTPException
        if isinstance(error, HTTPException):
            return error
        
        # Log and return generic error for real exceptions
        app.logger.error(f'Unhandled exception: {str(error)}', exc_info=True)
        return jsonify({'error': 'An unexpected error occurred'}), 500
    
    return app


if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000, debug=True)
