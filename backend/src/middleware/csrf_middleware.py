"""Session-bound double-submit CSRF for cookie-authenticated mutations."""
from functools import wraps
import hashlib
import hmac
import secrets
from flask import current_app, request, jsonify, g


def generate_csrf_token(access_token=None, refresh_token=None):
    nonce = secrets.token_urlsafe(32)
    if not access_token:
        # Callers issuing a session must supply its access token. This form is
        # retained only for unauthenticated/non-session uses and is never valid
        # for cookie-authenticated mutations.
        return nonce
    signature = hmac.new(str(current_app.config['JWT_SECRET_KEY']).encode(),
                         (nonce + '|' + access_token).encode(), hashlib.sha256).hexdigest()
    if refresh_token:
        refresh_signature = hmac.new(str(current_app.config['JWT_SECRET_KEY']).encode(),
                                     (nonce + '|' + refresh_token).encode(), hashlib.sha256).hexdigest()
        return nonce + '.' + signature + '.' + refresh_signature
    return nonce + '.' + signature


def validate_session_csrf(access_token):
    cookie = request.cookies.get('csrf_token')
    header = request.headers.get('X-CSRF-Token')
    if not cookie or not header or len(cookie) > 256 or len(header) > 256:
        return False
    if not cookie.isascii() or not header.isascii():
        return False
    if not secrets.compare_digest(cookie, header):
        return False
    parts = header.split('.')
    if len(parts) not in (2, 3):
        return False
    nonce, signatures = parts[0], parts[1:]
    expected = hmac.new(str(current_app.config['JWT_SECRET_KEY']).encode(),
                        (nonce + '|' + access_token).encode(), hashlib.sha256).hexdigest()
    return any(secrets.compare_digest(signature, expected) for signature in signatures)


def csrf_protect(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            token = request.cookies.get('access_token')
            if token and not validate_session_csrf(token):
                return jsonify({'error': 'CSRF validation failed', 'code': 'CSRF_INVALID'}), 403
        return f(*args, **kwargs)
    return decorated


def set_csrf_cookie(response, csrf_token):
    response.set_cookie('csrf_token', csrf_token, httponly=True, secure=True,
                        samesite='Lax', max_age=2592000)
    return response
