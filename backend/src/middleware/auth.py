"""Authentication middleware"""
from functools import wraps
from flask import request, jsonify, g
from src.models import User
from src.models.token_blacklist import TokenBlacklist
import jwt
from flask import current_app
from src.constants.roles import Roles

def jwt_required(f):
    """JWT authentication decorator with token revocation check"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = None
        
        # Try to get token from httpOnly cookie first (most secure)
        token = request.cookies.get('access_token')
        
        # Fallback to Authorization header for API clients
        if not token and 'Authorization' in request.headers:
            parts = request.headers['Authorization'].split()
            if len(parts) != 2 or parts[0].lower() != 'bearer':
                return jsonify({'error': 'Invalid token format'}), 401
            token = parts[1]

        if not token:
            return jsonify({'error': 'Authentication token is missing'}), 401
        
        try:
            from src.services.session_service import SessionService
            # Authentication is a read boundary.  It must not flush unrelated
            # pending ORM state before an authenticated read-only handler gets
            # a chance to preserve that state as well.
            from src.database import db
            with db.session.no_autoflush:
                current_user, payload = SessionService.authenticate(token, 'access')
        except ValueError:
            return jsonify({'error': 'Invalid or revoked session'}), 401
        except Exception:
            return jsonify({'error': 'Authentication unavailable'}), 503
        if request.cookies.get('access_token') and request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            from src.middleware.csrf_middleware import validate_session_csrf
            if not validate_session_csrf(token):
                return jsonify({'error': 'CSRF validation failed', 'code': 'CSRF_INVALID'}), 403
        g.current_user = current_user
        g.token = token
        from src.utils.hierarchy_scoping import set_request_hierarchy_scope
        from src.database import db
        set_request_hierarchy_scope(db.session, current_user)

        return f(*args, **kwargs)
    
    return decorated_function

def get_current_user():
    """Get current authenticated user from g object"""
    return g.get('current_user', None)

def admin_required(f):
    """Admin role required decorator"""
    @wraps(f)
    @jwt_required
    def decorated_function(*args, **kwargs):
        current_user = get_current_user()
        
        if not current_user or not Roles.is_admin(current_user.role):
            return jsonify({'error': 'Admin access required'}), 403
        
        return f(*args, **kwargs)
    
    return decorated_function

def agent_required(f):
    """Agent role required decorator"""
    @wraps(f)
    @jwt_required
    def decorated_function(*args, **kwargs):
        current_user = get_current_user()
        
        if not current_user or (current_user.role not in ['admin', 'agent'] and not current_user.agent_profile):
            return jsonify({'error': 'Agent access required'}), 403
        
        return f(*args, **kwargs)
    
    return decorated_function
