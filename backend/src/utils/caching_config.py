"""
Flask Caching Configuration for MarketEdgePros
Adds Redis caching to improve API performance
"""

from flask_caching import Cache
from functools import wraps
import hashlib
import json

# Initialize cache
cache = Cache()

def init_cache(app):
    """Initialize Flask-Caching with Redis backend"""
    cache.init_app(app, config={
        'CACHE_TYPE': 'RedisCache',
        'CACHE_REDIS_HOST': 'localhost',
        'CACHE_REDIS_PORT': 6379,
        'CACHE_REDIS_DB': 1,  # Use DB 1 for caching (DB 0 for Celery)
        'CACHE_DEFAULT_TIMEOUT': 300,  # 5 minutes default
        'CACHE_KEY_PREFIX': 'marketedgepros_'
    })
    return cache

def cache_key_with_user(*args, **kwargs):
    """Generate cache key including user context"""
    from flask import request
    from flask_jwt_extended import get_jwt_identity
    
    try:
        user_id = get_jwt_identity()
    except:
        user_id = 'anonymous'
    
    # Include request args in cache key
    request_args = str(sorted(request.args.items()))
    
    # Create unique key
    key_data = f"{request.path}:{user_id}:{request_args}"
    key_hash = hashlib.md5(key_data.encode()).hexdigest()
    
    return f"view_{key_hash}"

# Decorator for caching API responses
def cached_api(timeout=300, key_prefix=None):
    """
    Decorator to cache API responses
    
    Usage:
        @cached_api(timeout=600, key_prefix='programs')
        def get_programs():
            return jsonify(programs)
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Generate cache key
            if key_prefix:
                cache_key = f"{key_prefix}_{cache_key_with_user()}"
            else:
                cache_key = cache_key_with_user()
            
            # Try to get from cache
            cached_response = cache.get(cache_key)
            if cached_response is not None:
                return cached_response
            
            # Execute function and cache result
            response = f(*args, **kwargs)
            cache.set(cache_key, response, timeout=timeout)
            
            return response
        
        return decorated_function
    return decorator

# Cache invalidation helpers
def invalidate_programs_cache():
    """Invalidate all programs-related cache"""
    cache.delete_memoized('get_all_programs')
    cache.delete_memoized('get_program')
    # Delete all keys with programs prefix
    for key in cache.cache._write_client.keys('marketedgepros_programs_*'):
        cache.delete(key)

def invalidate_user_cache(user_id):
    """Invalidate cache for specific user"""
    for key in cache.cache._write_client.keys(f'marketedgepros_*{user_id}*'):
        cache.delete(key)

def invalidate_challenge_cache(challenge_id):
    """Invalidate cache for specific challenge"""
    for key in cache.cache._write_client.keys(f'marketedgepros_*challenge_{challenge_id}*'):
        cache.delete(key)

# Example usage in routes:
"""
from src.utils.caching import cache, cached_api, invalidate_programs_cache

@programs_bp.route('/', methods=['GET'], strict_slashes=False)
@cached_api(timeout=600, key_prefix='programs_list')
def get_programs():
    programs = TradingProgram.query.filter_by(is_active=True).all()
    return jsonify({'programs': [p.to_dict() for p in programs]})

@programs_bp.route('/', methods=['POST'])
@jwt_required()
@role_required(['admin', 'supermaster'])
def create_program():
    # ... create program logic ...
    
    # Invalidate cache after creating
    invalidate_programs_cache()
    
    return jsonify(new_program.to_dict()), 201
"""
