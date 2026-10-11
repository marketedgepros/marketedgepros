"""Decorators for authentication and authorization"""
from functools import wraps
from inspect import signature, Parameter
from flask import request, jsonify, g
from src.models import User
from src.services.auth_service import AuthService
from src.constants.roles import Roles
from src.utils.hierarchy_scoping import set_request_hierarchy_scope
from src.database import db

def token_required(f):
    """Decorator to require valid JWT token (supports both cookies and headers)"""
    # Both handler styles exist: explicit current_user and request-local g.
    # Inspect once at registration, never catch/retry a handler TypeError.
    parameters = signature(f).parameters
    user_argument = 'current_user' if 'current_user' in parameters else 'user' if 'user' in parameters else None
    user_parameter = parameters.get(user_argument)
    first_parameter = next(iter(parameters), None)
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        
        # Try to get token from cookies first (new method)
        token = request.cookies.get('access_token')
        
        # Fallback to Authorization header (backward compatibility)
        if not token and 'Authorization' in request.headers:
            parts = request.headers['Authorization'].split()
            if len(parts) != 2 or parts[0].lower() != 'bearer':
                return jsonify({'error': 'Invalid token format'}), 401
            token = parts[1]

        if not token:
            return jsonify({'error': 'Token is missing'}), 401
        
        try:
            from src.services.session_service import SessionService
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

        # Store user in g
        g.current_user = current_user
        g.token = token
        
        # Enable hierarchy scoping for this request
        set_request_hierarchy_scope(db.session, current_user)
        
        if user_parameter is not None:
            if first_parameter == user_argument and user_parameter.kind in {Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD}:
                return f(current_user, *args, **kwargs)
            kwargs[user_argument] = current_user
        return f(*args, **kwargs)
    
    return decorated

def role_required(*roles):
    """Decorator to require specific role(s)"""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if not hasattr(g, 'current_user'):
                return jsonify({'error': 'Authentication required'}), 401
            
            if g.current_user.role not in roles:
                return jsonify({'error': 'Insufficient permissions'}), 403
            
            return f(*args, **kwargs)
        
        return decorated
    return decorator

def tenant_required(f):
    """Decorator to ensure user belongs to a tenant"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not hasattr(g, 'current_user'):
            return jsonify({'error': 'Authentication required'}), 401
        
        if not g.current_user.tenant_id:
            return jsonify({'error': 'User must belong to a tenant'}), 403
        
        return f(*args, **kwargs)
    
    return decorated

def verified_email_required(f):
    """Decorator to require verified email"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not hasattr(g, 'current_user'):
            return jsonify({'error': 'Authentication required'}), 401
        
        if not g.current_user.is_verified:
            return jsonify({'error': 'Email verification required'}), 403
        
        return f(*args, **kwargs)
    
    return decorated

def admin_required(f):
    """Decorator to require admin role"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not hasattr(g, 'current_user'):
            return jsonify({'error': 'Authentication required'}), 401
        
        if not Roles.is_admin(g.current_user.role):
            return jsonify({'error': 'Admin access required'}), 403
        
        return f(*args, **kwargs)
    
    return decorated
