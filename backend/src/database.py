"""
Database initialization and utilities
"""
from src.extensions import db  # Import from extensions to use single instance
from flask_migrate import Migrate
from datetime import datetime
import redis
import os

migrate = Migrate()

# Redis connection
redis_client = None

def init_db(app):
    """Initialize database with Flask app"""
    from src.testing_safety import validate_testing_resources
    validate_testing_resources(app.config)
    db.init_app(app)
    migrate.init_app(app, db)
    
    # Initialize Redis
    global redis_client
    redis_client = None
    redis_url = app.config.get("REDIS_URL")
    if redis_url:
        try:
            redis_client = redis.from_url(redis_url, decode_responses=True)
            # Test connection
            redis_client.ping()
            app.logger.info("Redis connection established")
        except Exception as e:
            app.logger.warning(f"Redis connection failed: {e}. Continuing without Redis.")
            redis_client = None
    
    return db

def get_redis():
    """Get Redis client instance"""
    return redis_client

class TimestampMixin:
    """Mixin for created_at and updated_at timestamps"""
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
