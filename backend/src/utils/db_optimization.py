"""
Database optimization configuration for MarketEdgePros
Connection pooling, query optimization, and performance tuning
"""

from sqlalchemy import event
from sqlalchemy.engine import Engine
import time
import logging

logger = logging.getLogger(__name__)

def init_db_optimization(app):
    """Initialize database optimizations"""
    
    # Connection pooling configuration
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_size': 20,  # Number of connections to maintain
        'pool_recycle': 3600,  # Recycle connections after 1 hour
        'pool_pre_ping': True,  # Test connections before using
        'max_overflow': 10,  # Additional connections if pool is full
        'pool_timeout': 30,  # Timeout for getting connection from pool
        'echo_pool': False,  # Don't log pool events
    }
    
    # Query performance logging (development only)
    if app.config.get('FLASK_ENV') == 'development':
        @event.listens_for(Engine, "before_cursor_execute")
        def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            conn.info.setdefault('query_start_time', []).append(time.time())
            logger.debug("Start Query: %s", statement)
        
        @event.listens_for(Engine, "after_cursor_execute")
        def after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
            total = time.time() - conn.info['query_start_time'].pop(-1)
            if total > 0.1:  # Log slow queries (> 100ms)
                logger.warning("Slow Query (%.2fs): %s", total, statement)
    
    app.logger.info('Database optimizations initialized')

# Eager loading helpers
from sqlalchemy.orm import joinedload, selectinload

def load_challenge_with_relations(query):
    """Load challenge with all related data in one query"""
    return query.options(
        joinedload('user'),
        joinedload('program'),
        selectinload('mt5_account')
    )

def load_user_with_relations(query):
    """Load user with all related data"""
    return query.options(
        joinedload('parent'),
        selectinload('challenges'),
        selectinload('commissions')
    )

# Usage examples:
"""
# Instead of:
challenge = Challenge.query.get(challenge_id)
user = challenge.user  # N+1 query!
program = challenge.program  # N+1 query!

# Use:
challenge = load_challenge_with_relations(
    Challenge.query.filter_by(id=challenge_id)
).first()
user = challenge.user  # Already loaded!
program = challenge.program  # Already loaded!
"""

# Batch loading helper
def batch_load_challenges(challenge_ids):
    """Load multiple challenges efficiently"""
    return load_challenge_with_relations(
        Challenge.query.filter(Challenge.id.in_(challenge_ids))
    ).all()

# Query result caching
from functools import wraps
from flask import g

def cache_query_result(timeout=300):
    """Cache database query results in request context"""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            cache_key = f'query_{f.__name__}_{args}_{kwargs}'
            
            if not hasattr(g, 'query_cache'):
                g.query_cache = {}
            
            if cache_key in g.query_cache:
                return g.query_cache[cache_key]
            
            result = f(*args, **kwargs)
            g.query_cache[cache_key] = result
            return result
        return wrapper
    return decorator

# Example:
"""
@cache_query_result(timeout=300)
def get_active_programs():
    return TradingProgram.query.filter_by(is_active=True).all()
"""
