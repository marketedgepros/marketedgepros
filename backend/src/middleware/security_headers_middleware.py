"""
Enhanced Security Headers Middleware for MarketEdgePros
Adds comprehensive security headers to all responses
"""

from flask import request, make_response
from functools import wraps
import secrets

class SecurityHeadersMiddleware:
    """Middleware to add security headers to all responses"""
    
    def __init__(self, app=None):
        self.app = app
        if app is not None:
            self.init_app(app)
    
    def init_app(self, app):
        """Initialize middleware with Flask app"""
        app.after_request(self.add_security_headers)
        
        # Generate nonce for CSP
        @app.before_request
        def generate_csp_nonce():
            request.csp_nonce = secrets.token_urlsafe(16)
    
    def add_security_headers(self, response):
        """Add comprehensive security headers to response"""
        
        # Strict-Transport-Security (HSTS)
        # Force HTTPS for 1 year, including subdomains
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains; preload'
        
        # X-Frame-Options
        # Prevent clickjacking by disallowing iframe embedding
        response.headers['X-Frame-Options'] = 'DENY'
        
        # X-Content-Type-Options
        # Prevent MIME type sniffing
        response.headers['X-Content-Type-Options'] = 'nosniff'
        
        # X-XSS-Protection
        # Enable browser's XSS filter (legacy, but still useful)
        response.headers['X-XSS-Protection'] = '1; mode=block'
        
        # Referrer-Policy
        # Control how much referrer information is sent
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        
        # Permissions-Policy (formerly Feature-Policy)
        # Disable unnecessary browser features
        response.headers['Permissions-Policy'] = (
            'geolocation=(), '
            'microphone=(), '
            'camera=(), '
            'payment=(self), '
            'usb=(), '
            'magnetometer=(), '
            'gyroscope=(), '
            'speaker=()'
        )
        
        # Content-Security-Policy (CSP)
        # Prevent XSS and other code injection attacks
        nonce = getattr(request, 'csp_nonce', '')
        csp_directives = [
            "default-src 'self'",
            f"script-src 'self' 'nonce-{nonce}' https://cdn.jsdelivr.net https://www.googletagmanager.com",
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
            "font-src 'self' https://fonts.gstatic.com",
            "img-src 'self' data: https:",
            "connect-src 'self' https://marketedgepros.com https://www.google-analytics.com",
            "frame-ancestors 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "object-src 'none'",
            "upgrade-insecure-requests"
        ]
        response.headers['Content-Security-Policy'] = '; '.join(csp_directives)
        
        # X-Permitted-Cross-Domain-Policies
        # Restrict Adobe Flash and PDF cross-domain requests
        response.headers['X-Permitted-Cross-Domain-Policies'] = 'none'
        
        # Cross-Origin-Embedder-Policy
        response.headers['Cross-Origin-Embedder-Policy'] = 'require-corp'
        
        # Cross-Origin-Opener-Policy
        response.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
        
        # Cross-Origin-Resource-Policy
        response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
        
        # Remove server header (already done in nginx, but double-check)
        response.headers.pop('Server', None)
        
        # Remove X-Powered-By header
        response.headers.pop('X-Powered-By', None)
        
        return response

def require_https(f):
    """
    Decorator to ensure endpoint is only accessible via HTTPS
    
    Usage:
        @app.route('/api/sensitive')
        @require_https
        def sensitive_endpoint():
            return jsonify({'data': 'sensitive'})
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not request.is_secure and not request.headers.get('X-Forwarded-Proto') == 'https':
            return make_response({
                'error': 'HTTPS required'
            }, 403)
        return f(*args, **kwargs)
    return decorated_function

# Example usage in app.py:
"""
from src.middleware.security_headers import SecurityHeadersMiddleware

# Initialize security headers middleware
security_headers = SecurityHeadersMiddleware(app)

# Or manually:
@app.after_request
def add_security_headers(response):
    middleware = SecurityHeadersMiddleware()
    return middleware.add_security_headers(response)
"""
