"""
Authentication routes
"""
from flask import Blueprint, current_app, request, jsonify, g, make_response
from src.middleware.csrf_middleware import generate_csrf_token, set_csrf_cookie
from src.middleware.login_monitor import (
    check_rate_limit, record_failed_login, record_successful_login, get_client_ip
)
from src.extensions import limiter
from src import limiter
from src.database import db
from src.services.auth_service import AuthService
from src.services.session_service import SessionService
from src.services.two_factor_service import TwoFactorService
from src.middleware.csrf_middleware import validate_session_csrf
from src.services.email_service import EmailService
from src.utils.decorators import token_required
from src.utils.validators import (
    validate_email_format,
    validate_password_strength,
    validate_required_fields
)
from src.schemas.auth_schemas import RegisterSchema, LoginSchema, Login2FASchema, PasswordResetRequestSchema, PasswordResetSchema
from src.utils.schema_validator import validate_schema

auth_bp = Blueprint('auth', __name__)

_ACCOUNT_EMAIL_UNAVAILABLE = {
    'error': 'Account email delivery is unavailable.',
    'code': 'ACCOUNT_EMAIL_UNAVAILABLE',
}
_RESEND_NEUTRAL_MESSAGE = (
    'If the account is eligible, a verification email has been requested. '
    'If nothing arrives, try again later.'
)
_RESET_NEUTRAL_MESSAGE = (
    'If the account is eligible, a password reset email has been requested. '
    'If nothing arrives, try again later.'
)


def _account_email_delivery_ready():
    """Check delivery readiness only for the new explicit account-access path."""
    if current_app.config.get('PUBLIC_ACCOUNT_ACCESS_ENABLED') is not True:
        return True
    try:
        return EmailService.is_configured() is True
    except Exception:
        current_app.logger.warning('Account email delivery configuration is unavailable')
        return False


def _account_email_unavailable_response():
    """Use one non-enumerating response before an email-address lookup occurs."""
    return jsonify(_ACCOUNT_EMAIL_UNAVAILABLE), 503


def _json_object_or_error():
    """Reject malformed JSON consistently without exposing parser details."""
    data = request.get_json(silent=True)
    if request.is_json and data is None:
        return None, (jsonify({'error': 'Invalid request data'}), 400)
    if data is not None and not isinstance(data, dict):
        return None, (jsonify({'error': 'Invalid request data'}), 400)
    return data or {}, None


@auth_bp.route("/register", methods=["POST"])
@limiter.limit("5 per hour")
@validate_schema(RegisterSchema)
def register():
    """Register a new user"""
    data = request.validated_data
    # Data is already validated by RegisterSchema

    # The account-access profile must have a usable transactional sender before
    # a pending account can be committed. Legacy non-demo callers retain their
    # historical route contract until they explicitly enable this feature.
    if not _account_email_delivery_ready():
        return _account_email_unavailable_response()

    try:
        registration_kwargs = {
            'email': data['email'],
            'password': data['password'],
            'first_name': data['first_name'],
            'last_name': data['last_name'],
            'phone': data.get('phone'),
            'country_code': data.get('country_code'),
            'referral_code': data.get('referral_code'),
        }
        # ``None`` means no tenant was selected. Omitting it preserves the
        # service's root-brand assignment while an explicit foreign ID remains
        # a rejected client ownership attempt.
        if data.get('tenant_id') is not None:
            registration_kwargs['tenant_id'] = data['tenant_id']
        # Register user
        user, verification_token = AuthService.register_user(**registration_kwargs)

        # User and token are committed atomically by AuthService before any
        # provider call. Acceptance is not mailbox delivery; a failure leaves
        # the pending account recoverable through resend once delivery returns.
        try:
            email_accepted = EmailService.send_verification_email(
                user, verification_token.code
            ) is True
        except Exception:
            current_app.logger.warning('Verification email request was unavailable')
            email_accepted = False

        if email_accepted:
            return jsonify({
                'message': 'Account created. Verify your email to continue.',
                'user': user.to_dict(),
                'verification_email_status': 'accepted',
            }), 201
        return jsonify({
            'message': 'Account created and pending email verification. Use resend verification when email delivery is available.',
            'user': user.to_dict(),
            'verification_email_status': 'unavailable',
        }), 202
        
    except ValueError as e:
        db.session.rollback()
        return jsonify({'error': 'Registration failed'}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'Registration failed'}), 500


@auth_bp.route('/login', methods=['POST'])
@limiter.limit("10 per minute")
@validate_schema(LoginSchema)
def login():
    """Login user"""
    data = request.get_json(silent=True) or {}
    
    # Validate required fields
    valid, message = validate_required_fields(data, ['email', 'password'])
    if not valid:
        return jsonify({'error': message}), 400
    
    try:
        # Get IP address
        ip_address = request.remote_addr
        
        # Login user
        user = AuthService.login_user(
            email=data['email'],
            password=data['password'],
            ip_address=ip_address
        )
        
        # Check if 2FA is enabled
        if user.two_factor_enabled:
            # Don't generate tokens yet, wait for 2FA
            challenge_token = TwoFactorService.issue(user)
            db.session.commit()
            return jsonify({
                'message': '2FA required',
                'requires_2fa': True,
                'user_id': user.id,
                'challenge_token': challenge_token
            }), 200
        
        # Generate tokens
        access_token, refresh_token = SessionService.issue(user)
        db.session.commit()
        
        # Record successful login
        ip_address = get_client_ip()
        record_successful_login(ip_address)
        
        # Generate CSRF token
        csrf_token = generate_csrf_token(access_token, refresh_token)
        
        # Create response with httpOnly cookies
        response = make_response(jsonify({
            'message': 'Login successful',
            'user': user.to_dict(),
            'csrf_token': csrf_token,
            'access_token': access_token,  # Also send in response for backward compatibility
            'refresh_token': refresh_token  # Also send in response for backward compatibility
        }), 200)
        
        # Set httpOnly cookies for tokens
        response.set_cookie(
            'access_token',
            value=access_token,
            httponly=True,
            secure=True,  # HTTPS only
            samesite='Lax',  # CSRF protection
            max_age=3600  # 1 hour
        )
        
        response.set_cookie(
            'refresh_token',
            value=refresh_token,
            httponly=True,
            secure=True,
            samesite='Lax',
            max_age=2592000  # 30 days
        )
        
        return set_csrf_cookie(response, csrf_token)
        
    except ValueError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 401
    except Exception as e:
        db.session.rollback()
        import traceback
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f'Login error: {str(e)}')
        logger.error(traceback.format_exc())
        return jsonify({'error': 'Login unavailable'}), 503


@auth_bp.route("/login/2fa", methods=["POST"])
@limiter.limit("10 per minute")
def login_2fa():
    """Complete login with 2FA"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not data.get('challenge_token') or not data.get('token'):
        return jsonify({'error': 'Password-bound challenge and token are required'}), 400
    try:
        user, access_token, refresh_token = TwoFactorService.complete(
            data['challenge_token'], data['token'], data.get('user_id'))

        # Generate CSRF token
        csrf_token = generate_csrf_token(access_token, refresh_token)
        
        # Create response with httpOnly cookies
        response = make_response(jsonify({
            'message': 'Login successful',
            'user': user.to_dict(),
            'csrf_token': csrf_token,
            'access_token': access_token,  # Also send in response for backward compatibility
            'refresh_token': refresh_token  # Also send in response for backward compatibility
        }), 200)
        
        # Set httpOnly cookies for tokens
        response.set_cookie(
            'access_token',
            value=access_token,
            httponly=True,
            secure=True,  # HTTPS only
            samesite='Lax',  # CSRF protection
            max_age=3600  # 1 hour
        )
        
        response.set_cookie(
            'refresh_token',
            value=refresh_token,
            httponly=True,
            secure=True,
            samesite='Lax',
            max_age=2592000  # 30 days
        )
        
        return set_csrf_cookie(response, csrf_token)
        
    except ValueError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 401
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': '2FA verification failed'}), 500


@auth_bp.route('/logout', methods=['POST'])
@token_required
def logout(current_user):
    """Logout user (revoke token)"""
    try:
        # Revoke current token
        SessionService.logout(current_user, g.token)
        
        # Create response and clear cookies
        response = make_response(jsonify({'message': 'Logout successful'}), 200)
        response.set_cookie(
            'access_token',
            '',
            max_age=0,
            httponly=True,
            secure=True,
            samesite='Lax'
        )
        response.set_cookie(
            'refresh_token',
            '',
            max_age=0,
            httponly=True,
            secure=True,
            samesite='Lax'
        )
        response.set_cookie(
            'csrf_token',
            '',
            max_age=0,
            httponly=False,  # CSRF token needs to be readable
            secure=True,
            samesite='Lax'
        )  # Clear CSRF token
        
        return response
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'Logout failed'}), 500


@auth_bp.route("/refresh", methods=["POST"])
@limiter.limit("30 per minute")
def refresh_token():
    """Refresh access token"""
    data = request.get_json(silent=True)
    if data is not None and not isinstance(data, dict):
        return jsonify({'error': 'JSON object required'}), 400
    cookie_refresh = request.cookies.get('refresh_token')
    refresh = cookie_refresh or (data or {}).get('refresh_token')
    if not refresh:
        return jsonify({'error': 'Refresh token is required'}), 400
    if cookie_refresh and not validate_session_csrf(cookie_refresh):
        return jsonify({'error': 'CSRF validation failed', 'code': 'CSRF_INVALID'}), 403
    try:
        access_token, refresh_token = SessionService.rotate(refresh)
        csrf_token = generate_csrf_token(access_token, refresh_token)
        response = make_response(jsonify({
            'message': 'Token refreshed successfully',
            'access_token': access_token,
            'refresh_token': refresh_token,
            'csrf_token': csrf_token,
        }), 200)
        response.set_cookie('access_token',access_token,httponly=True,secure=True,samesite='Lax',max_age=3600)
        response.set_cookie('refresh_token',refresh_token,httponly=True,secure=True,samesite='Lax',max_age=2592000)
        return set_csrf_cookie(response,csrf_token)
    except ValueError:
        return jsonify({'error': 'Invalid or revoked refresh session'}), 401
    except Exception:
        return jsonify({'error': 'Token refresh unavailable'}), 503


@auth_bp.route('/verify-email/<token>', methods=['GET'])
def verify_email(token):
    """Verify email with token (URL-based)"""
    try:
        user = AuthService.verify_email(token)

        # Welcome delivery is best effort and cannot roll back a committed,
        # single-use verification transaction.
        try:
            EmailService.send_welcome_email(user)
        except Exception:
            current_app.logger.warning('Welcome email request was unavailable')

        return jsonify({
            'message': 'Email verified successfully',
            'user': user.to_dict()
        }), 200
        
    except ValueError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'Email verification failed'}), 500


@auth_bp.route('/verify-email', methods=['POST'])
def verify_email_with_code():
    """Verify email with 6-digit code"""
    from src.models.verification_attempt import VerificationAttempt
    import logging

    data, error_response = _json_object_or_error()
    if error_response:
        return error_response
    logger = logging.getLogger(__name__)

    # Get IP and User Agent
    ip_address = request.remote_addr
    user_agent = request.headers.get('User-Agent', '')
    
    # Validate required fields
    valid, message = validate_required_fields(data, ['email', 'code'])
    if not valid:
        return jsonify({'error': message}), 400
    
    # Validate code format (6 digits)
    if not isinstance(data['code'],str) or not data['code'].isascii() or not data['code'].isdigit() or len(data['code']) != 6:
        return jsonify({'error': 'Code must be 6 digits'}), 400
    
    email = data['email']
    code = data['code']
    
    # Check rate limiting
    if VerificationAttempt.is_rate_limited(email, ip_address, max_attempts=5, window_minutes=15):
        logger.warning(f'Rate limit exceeded for email verification: {email} from IP {ip_address}')
        VerificationAttempt.log_attempt(
            email=data["email"],
            code_entered='******',
            success=False,
            ip_address=ip_address,
            user_agent=user_agent,
            failure_reason='rate_limited'
        )
        return jsonify({
            'error': 'Too many failed attempts. Please try again in 15 minutes.'
        }), 429
    
    try:
        user = AuthService.verify_email_with_code(email, code)
        
        # Log successful attempt
        VerificationAttempt.log_attempt(
            email=data["email"],
            code_entered='******',
            success=True,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        logger.info(f'Email verified successfully: {email} from IP {ip_address}')

        # A welcome-email failure cannot invalidate a verified account.
        try:
            EmailService.send_welcome_email(user)
        except Exception:
            current_app.logger.warning('Welcome email request was unavailable')

        return jsonify({
            'message': 'Email verified successfully',
            'user': user.to_dict()
        }), 200
        
    except ValueError as e:
        db.session.rollback()
        # Log failed attempt
        VerificationAttempt.log_attempt(
            email=data["email"],
            code_entered='******',
            success=False,
            ip_address=ip_address,
            user_agent=user_agent,
            failure_reason='invalid_or_expired_code'
        )

        logger.warning('Email verification code rejected from IP %s', ip_address)

        return jsonify({'error': 'Invalid or expired verification code'}), 400
    except Exception as e:
        db.session.rollback()
        # Log failed attempt
        VerificationAttempt.log_attempt(
            email=data["email"],
            code_entered='******',
            success=False,
            ip_address=ip_address,
            user_agent=user_agent,
            failure_reason='system_error'
        )
        
        logger.error(f'Email verification system error for {email}: {str(e)} from IP {ip_address}')
        
        return jsonify({'error': 'Email verification failed'}), 500


@auth_bp.route("/resend-verification", methods=["POST"])
@limiter.limit("5 per hour")
@validate_schema(PasswordResetRequestSchema)
def resend_verification():
    """Resend verification code"""
    data = request.validated_data

    # Must run before the email-address lookup/token issuance below.
    if not _account_email_delivery_ready():
        return _account_email_unavailable_response()

    try:
        verification_token = AuthService.resend_verification_code(data['email'])

        if verification_token:
            try:
                EmailService.send_verification_email(
                    verification_token.user, verification_token.code
                )
            except Exception:
                current_app.logger.warning('Verification email resend request was unavailable')
    except Exception:
        db.session.rollback()
    # Keep provider failure, existing, missing, inactive, and verified accounts
    # indistinguishable. The response says only that a request was accepted.
    return jsonify({'message': _RESEND_NEUTRAL_MESSAGE}), 200


@auth_bp.route("/password/reset-request", methods=["POST"])
@limiter.limit("5 per hour")
@validate_schema(PasswordResetRequestSchema)
def request_password_reset():
    """Request password reset"""
    data = request.validated_data

    # Must run before the email-address lookup/token issuance below.
    if not _account_email_delivery_ready():
        return _account_email_unavailable_response()

    try:
        reset_token = AuthService.request_password_reset(data['email'])

        # Send password reset email with code
        if reset_token:
            try:
                EmailService.send_password_reset_email(reset_token.user, reset_token.code)
            except Exception:
                current_app.logger.warning('Password reset email request was unavailable')
    except Exception:
        db.session.rollback()
    return jsonify({'message': _RESET_NEUTRAL_MESSAGE}), 200


@auth_bp.route("/password/reset", methods=["POST"])
@limiter.limit("5 per hour")
def reset_password():
    """Reset password with token (URL-based)"""
    data, error_response = _json_object_or_error()
    if error_response:
        return error_response

    # Validate required fields
    valid, message = validate_required_fields(data, ['token', 'new_password'])
    if not valid:
        return jsonify({'error': message}), 400
    
    # Validate password
    valid, message = validate_password_strength(data['new_password'])
    if not valid:
        return jsonify({'error': message}), 400
    
    try:
        user = AuthService.reset_password(data['token'], data['new_password'])
        
        return jsonify({
            'message': 'Password reset successfully',
            'user': user.to_dict()
        }), 200
        
    except ValueError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'Password reset failed'}), 500


@auth_bp.route("/password/verify-code", methods=["POST"])
@limiter.limit("10 per minute")
def verify_reset_code():
    """Verify password reset code"""
    data, error_response = _json_object_or_error()
    if error_response:
        return error_response

    # Validate required fields
    valid, message = validate_required_fields(data, ['email', 'code'])
    if not valid:
        return jsonify({'error': message}), 400
    
    # Validate code format (6 digits)
    if not isinstance(data['code'],str) or not data['code'].isascii() or not data['code'].isdigit() or len(data['code']) != 6:
        return jsonify({'error': 'Code must be 6 digits'}), 400
    
    try:
        token = AuthService.verify_reset_code(data['email'], data['code'])
        
        return jsonify({
            'message': 'Reset code verified successfully',
            'valid': True
        }), 200
        
    except ValueError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'Code verification failed'}), 500


@auth_bp.route("/password/reset-with-code", methods=["POST"])
@limiter.limit("5 per hour")
def reset_password_with_code():
    """Reset password with 6-digit code"""
    data, error_response = _json_object_or_error()
    if error_response:
        return error_response

    # Validate required fields
    valid, message = validate_required_fields(data, ['email', 'code', 'new_password'])
    if not valid:
        return jsonify({'error': message}), 400
    
    # Validate code format (6 digits)
    if not isinstance(data['code'],str) or not data['code'].isascii() or not data['code'].isdigit() or len(data['code']) != 6:
        return jsonify({'error': 'Code must be 6 digits'}), 400
    
    # Validate password
    valid, message = validate_password_strength(data['new_password'])
    if not valid:
        return jsonify({'error': message}), 400
    
    try:
        user = AuthService.reset_password_with_code(
            data['email'],
            data['code'],
            data['new_password']
        )
        
        return jsonify({
            'message': 'Password reset successfully',
            'user': user.to_dict()
        }), 200
        
    except ValueError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'Password reset failed'}), 500


@auth_bp.route('/2fa/enable', methods=['POST'])
@token_required
def enable_2fa(current_user):
    """Enable 2FA for current user"""
    try:
        uri = AuthService.enable_2fa(g.current_user)
        
        return jsonify({
            'message': '2FA secret generated',
            'uri': uri,
            'secret': g.current_user.two_factor_secret
        }), 200
        
    except ValueError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': '2FA enable failed'}), 500


@auth_bp.route('/2fa/confirm', methods=['POST'])
@token_required
def confirm_2fa(current_user):
    """Confirm and activate 2FA"""
    data = request.get_json(silent=True) or {}
    
    if not isinstance(data,dict) or 'token' not in data:
        return jsonify({'error': 'Token is required'}), 400
    
    try:
        AuthService.confirm_2fa(g.current_user, data['token'])
        
        return jsonify({
            'message': '2FA enabled successfully',
            'user': g.current_user.to_dict()
        }), 200
        
    except ValueError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': '2FA confirmation failed'}), 500


@auth_bp.route('/2fa/disable', methods=['POST'])
@token_required
def disable_2fa(current_user):
    """Disable 2FA for current user"""
    data = request.get_json(silent=True) or {}
    
    if not isinstance(data,dict) or 'password' not in data:
        return jsonify({'error': 'Password is required'}), 400
    
    try:
        AuthService.disable_2fa(g.current_user, data['password'])
        
        return jsonify({
            'message': '2FA disabled successfully',
            'user': g.current_user.to_dict()
        }), 200
        
    except ValueError as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': '2FA disable failed'}), 500


@auth_bp.route('/me', methods=['GET'])
@token_required
def get_current_user(current_user):
    """Get current user info (exempt from rate limiting)"""
    return jsonify({
        'user': g.current_user.to_dict(include_sensitive=True)
    }), 200
