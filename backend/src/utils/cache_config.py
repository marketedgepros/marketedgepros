"""
Redis Caching configuration for MarketEdgePros
Add this to app.py after app creation
"""

from flask_caching import Cache

def init_cache(app):
    """Initialize Redis caching"""
    
    cache_config = {
        'CACHE_TYPE': 'RedisCache',
        'CACHE_REDIS_URL': app.config.get('REDIS_URL', 'redis://localhost:6379/2'),
        'CACHE_DEFAULT_TIMEOUT': 300,  # 5 minutes default
        'CACHE_KEY_PREFIX': 'marketedgepros_',
    }
    
    app.config.from_mapping(cache_config)
    cache = Cache(app)
    
    app.logger.info('Redis caching initialized')
    
    return cache

# Usage in routes:
"""
from src.utils.cache_config import cache

# Cache a view for 5 minutes
@app.route('/api/challenges')
@cache.cached(timeout=300, query_string=True)
def get_challenges():
    # Your code here
    pass

# Cache with custom key
@app.route('/api/users/<int:user_id>')
@cache.cached(timeout=600, key_prefix='user_details')
def get_user(user_id):
    # Your code here
    pass

# Memoize a function (cache based on arguments)
@cache.memoize(timeout=300)
def get_user_challenges(user_id, status=None):
    # Your code here
    pass

# Clear cache
cache.clear()

# Delete specific key
cache.delete('user_details_123')

# Delete by pattern
cache.delete_memoized(get_user_challenges, user_id=123)
"""

# Cache decorators for common patterns:
def cache_user_data(timeout=600):
    """Cache user-specific data"""
    def decorator(f):
        return cache.cached(
            timeout=timeout,
            key_prefix=f'user_{f.__name__}',
            unless=lambda: request.method != 'GET'
        )(f)
    return decorator

def cache_public_data(timeout=300):
    """Cache public data (no authentication required)"""
    def decorator(f):
        return cache.cached(
            timeout=timeout,
            query_string=True,
            unless=lambda: request.method != 'GET'
        )(f)
    return decorator

# Example usage:
"""
@app.route('/api/programs')
@cache_public_data(timeout=3600)  # Cache for 1 hour
def get_programs():
    programs = TradingProgram.query.all()
    return jsonify([p.to_dict() for p in programs])

@app.route('/api/user/challenges')
@cache_user_data(timeout=300)  # Cache for 5 minutes
def get_user_challenges():
    user_id = get_jwt_identity()
    challenges = Challenge.query.filter_by(user_id=user_id).all()
    return jsonify([c.to_dict() for c in challenges])
"""
