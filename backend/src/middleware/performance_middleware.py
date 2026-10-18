"""
Performance Middleware for MarketEdgePros
Adds caching headers and optimizations
"""

from flask import request, make_response
from functools import wraps
import time

class PerformanceMiddleware:
    """Middleware to add performance optimizations"""
    
    def __init__(self, app=None):
        self.app = app
        if app is not None:
            self.init_app(app)
    
    def init_app(self, app):
        """Initialize middleware with Flask app"""
        app.before_request(self.before_request)
        app.after_request(self.after_request)
    
    def before_request(self):
        """Track request start time"""
        request.start_time = time.time()
    
    def after_request(self, response):
        """Add performance headers and caching"""
        
        # Add response time header
        if hasattr(request, 'start_time'):
            response_time = time.time() - request.start_time
            response.headers['X-Response-Time'] = f"{response_time:.3f}s"
        
        # Add caching headers based on route
        if request.method == 'GET':
            path = request.path
            
            # Static files - cache for 1 year
            if path.startswith('/static/'):
                response.cache_control.public = True
                response.cache_control.max_age = 31536000  # 1 year
                response.headers['Expires'] = 'Thu, 31 Dec 2026 23:59:59 GMT'
            
            # API endpoints - cache for 5 minutes
            elif path.startswith('/api/v1/programs'):
                response.cache_control.public = True
                response.cache_control.max_age = 300  # 5 minutes
            
            # User-specific data - private cache for 1 minute
            elif any(path.startswith(p) for p in ['/api/v1/profile', '/api/v1/traders', '/api/v1/challenges']):
                response.cache_control.private = True
                response.cache_control.max_age = 60  # 1 minute
            
            # Admin endpoints - no cache
            elif path.startswith('/api/v1/admin'):
                response.cache_control.no_cache = True
                response.cache_control.no_store = True
                response.cache_control.must_revalidate = True
        
        # Add ETag for GET requests
        if request.method == 'GET' and response.status_code == 200:
            if not response.headers.get('ETag'):
                # Generate ETag from response data
                import hashlib
                etag = hashlib.md5(response.get_data()).hexdigest()
                response.headers['ETag'] = f'"{etag}"'
                
                # Check If-None-Match header
                if request.headers.get('If-None-Match') == f'"{etag}"':
                    response = make_response('', 304)
                    response.headers['ETag'] = f'"{etag}"'
        
        # Add Vary header for proper caching
        if 'Authorization' in request.headers:
            response.headers.add('Vary', 'Authorization')
        
        return response

def cache_for(timeout=300):
    """
    Decorator to set cache headers for specific routes
    
    Usage:
        @app.route('/api/data')
        @cache_for(timeout=600)  # Cache for 10 minutes
        def get_data():
            return jsonify(data)
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            response = make_response(f(*args, **kwargs))
            response.cache_control.public = True
            response.cache_control.max_age = timeout
            return response
        return decorated_function
    return decorator

def no_cache(f):
    """
    Decorator to disable caching for specific routes
    
    Usage:
        @app.route('/api/admin/stats')
        @no_cache
        def get_stats():
            return jsonify(stats)
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        response = make_response(f(*args, **kwargs))
        response.cache_control.no_cache = True
        response.cache_control.no_store = True
        response.cache_control.must_revalidate = True
        return response
    return decorated_function

# Example usage in app.py:
"""
from src.middleware.performance import PerformanceMiddleware, cache_for, no_cache

# Initialize middleware
performance = PerformanceMiddleware(app)

# Or in routes:
@programs_bp.route('/', methods=['GET'])
@cache_for(timeout=600)
def get_programs():
    programs = TradingProgram.query.filter_by(is_active=True).all()
    return jsonify({'programs': [p.to_dict() for p in programs]})

@admin_bp.route('/stats', methods=['GET'])
@no_cache
def get_admin_stats():
    stats = calculate_stats()
    return jsonify(stats)
"""
