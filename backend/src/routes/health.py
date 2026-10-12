"""
Health Check Endpoint
Monitors system health: database, Redis, Celery, disk space
"""
import re
from datetime import datetime

from flask import Blueprint, current_app, jsonify
from sqlalchemy import text

from src import database
from src.database import db
import redis
import psutil

health_bp = Blueprint('health', __name__)

_RELEASE_SHA = re.compile(r"[0-9a-fA-F]{40}\Z")
_DEPENDENCY_FAILURE = {'status': 'not_ready', 'reason': 'dependency_unavailable'}


@health_bp.route('/health', methods=['GET'])
def health_check():
    """
    Comprehensive health check endpoint
    Returns system status and component health
    """
    health_status = {
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'checks': {}
    }
    
    # Check Database
    try:
        db.session.execute(db.text('SELECT 1'))
        health_status['checks']['database'] = {
            'status': 'healthy',
            'message': 'Database connection OK'
        }
    except Exception:
        health_status['status'] = 'unhealthy'
        health_status['checks']['database'] = {
            'status': 'unhealthy',
            'message': 'Database check failed'
        }
    
    # Check Redis
    try:
        r = redis.Redis(host='localhost', port=6379, db=0)
        r.ping()
        health_status['checks']['redis'] = {
            'status': 'healthy',
            'message': 'Redis connection OK'
        }
    except Exception:
        health_status['status'] = 'degraded'
        health_status['checks']['redis'] = {
            'status': 'unhealthy',
            'message': 'Redis check failed'
        }
    
    # Check Disk Space
    try:
        disk = psutil.disk_usage('/')
        disk_percent = disk.percent
        
        if disk_percent > 90:
            health_status['status'] = 'degraded'
            disk_status = 'critical'
        elif disk_percent > 80:
            disk_status = 'warning'
        else:
            disk_status = 'healthy'
        
        health_status['checks']['disk'] = {
            'status': disk_status,
            'used_percent': disk_percent,
            'free_gb': round(disk.free / (1024**3), 2),
            'total_gb': round(disk.total / (1024**3), 2)
        }
    except Exception:
        health_status['checks']['disk'] = {
            'status': 'unknown',
            'message': 'Disk check unavailable'
        }
    
    # Check Memory
    try:
        memory = psutil.virtual_memory()
        memory_percent = memory.percent
        
        if memory_percent > 90:
            health_status['status'] = 'degraded'
            memory_status = 'critical'
        elif memory_percent > 80:
            memory_status = 'warning'
        else:
            memory_status = 'healthy'
        
        health_status['checks']['memory'] = {
            'status': memory_status,
            'used_percent': memory_percent,
            'available_gb': round(memory.available / (1024**3), 2),
            'total_gb': round(memory.total / (1024**3), 2)
        }
    except Exception:
        health_status['checks']['memory'] = {
            'status': 'unknown',
            'message': 'Memory check unavailable'
        }
    
    # Check CPU
    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        
        if cpu_percent > 90:
            cpu_status = 'critical'
        elif cpu_percent > 80:
            cpu_status = 'warning'
        else:
            cpu_status = 'healthy'
        
        health_status['checks']['cpu'] = {
            'status': cpu_status,
            'usage_percent': cpu_percent,
            'cores': psutil.cpu_count()
        }
    except Exception:
        health_status['checks']['cpu'] = {
            'status': 'unknown',
            'message': 'CPU check unavailable'
        }
    
    # Determine HTTP status code
    if health_status['status'] == 'healthy':
        status_code = 200
    elif health_status['status'] == 'degraded':
        status_code = 200  # Still operational
    else:
        status_code = 503  # Service unavailable
    
    return jsonify(health_status), status_code


@health_bp.route('/health/live', methods=['GET'])
def liveness():
    """Return a minimal process-liveness response without dependency access."""
    response = {'status': 'alive'}
    release_sha = current_app.config.get('DEPLOYMENT_SHA')
    if isinstance(release_sha, str) and _RELEASE_SHA.fullmatch(release_sha):
        response['release_sha'] = release_sha
    return jsonify(response), 200


@health_bp.route('/health/ready', methods=['GET'])
def readiness():
    """Check configured dependencies with read-only probes only."""
    try:
        db.session.execute(text('SELECT 1'))

        expected_revision = current_app.config.get('EXPECTED_SCHEMA_REVISION')
        if expected_revision is not None:
            revision = db.session.execute(
                text('SELECT version_num FROM public.alembic_version')
            ).scalar_one_or_none()
            if revision != expected_revision:
                return jsonify(_DEPENDENCY_FAILURE), 503

        if current_app.config.get('REDIS_URL'):
            redis_client = database.get_redis()
            if redis_client is None or not redis_client.ping():
                return jsonify(_DEPENDENCY_FAILURE), 503
    except Exception:
        return jsonify(_DEPENDENCY_FAILURE), 503

    return jsonify({'status': 'ready'}), 200


def _register_root_probe_routes(state):
    """Expose unauthenticated probes outside the versioned API prefix."""
    state.app.add_url_rule(
        '/health/live', endpoint='health_live', view_func=liveness, methods=['GET']
    )
    state.app.add_url_rule(
        '/health/ready', endpoint='health_ready', view_func=readiness, methods=['GET']
    )


# The application mounts this blueprint under /api/v1. Register root probes as
# well so orchestration can use the stable, versionless health contract.
health_bp.record_once(_register_root_probe_routes)
