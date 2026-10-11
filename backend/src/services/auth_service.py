"""
Authentication service with JWT and 2FA support
"""
from src.database import db, get_redis
from src.models import User, EmailVerificationToken, PasswordResetToken
from datetime import datetime, timedelta
from flask import current_app
import secrets


class AuthService:
    """Authentication service"""
    
    @staticmethod
    def register_user(email, password, first_name, last_name, referral_code=None, **kwargs):
        """Atomically register within the configured owner's existing brand."""
        from src.models import Agent, Referral
        from flask import has_request_context, request
        from src.utils.hierarchy_scoping import configured_platform_root_id, platform_root_scope, tenant_hierarchy_scope

        notify_upline = None
        try:
            root_id = configured_platform_root_id()
            root_user = User.query.filter(User.id == root_id).first() if root_id else None
            if root_user is None or not platform_root_scope(root_user) or not tenant_hierarchy_scope(root_user):
                raise ValueError('Registration is unavailable until platform ownership is configured')
            if 'tenant_id' in kwargs and kwargs['tenant_id'] != root_user.tenant_id:
                raise ValueError('Invalid registration ownership')
            kwargs.setdefault('role', 'trader')
            if kwargs.get('role', 'guest') not in {'guest', 'trader'}:
                raise ValueError('Invalid registration role')
            if User.query.filter_by(email=email).first():
                raise ValueError('Email already registered')
            kwargs['tenant_id'] = root_user.tenant_id
            parent = root_user
            agent = None
            if referral_code:
                agent = Agent.query.filter_by(agent_code=referral_code, is_active=True).with_for_update().first()
                if agent is not None:
                    parent = User.query.filter(User.id == agent.user_id, User.tenant_id == root_user.tenant_id).first()
                    if parent is None or not parent.is_active or not tenant_hierarchy_scope(parent):
                        raise ValueError('Invalid registration ownership')
                    if not current_app.config.get('EXPANDED_HIERARCHY_ENABLED', False) and parent.role not in {'affiliate', 'agent'}:
                        raise ValueError('Referral owner is unavailable in launch mode')
            user = User(email=email, first_name=first_name, last_name=last_name, **kwargs)
            user.set_password(password)
            user.parent_id = parent.id
            db.session.add(user)
            db.session.flush()
            user.update_tree_path()
            if agent is not None:
                db.session.add(Referral(
                    agent_id=agent.id, referred_user_id=user.id, referral_code=referral_code,
                    ip_address=request.remote_addr if has_request_context() else None,
                    user_agent=request.headers.get('User-Agent') if has_request_context() else None,
                    status='pending'
                ))
                agent.referral_count += 1
                notify_upline = parent
            verification_token = EmailVerificationToken(user.id)
            db.session.add(verification_token)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        # External notification occurs only after successful commit.
        if notify_upline is not None:
            try:
                from src.services.email_service import EmailService
                EmailService.send_new_downline_email(notify_upline, user)
            except Exception:
                current_app.logger.warning('Downline notification unavailable after registration')
        return user, verification_token

    @staticmethod
    def login_user(email, password, ip_address=None):
        """Login user with email and password"""
        user = User.query.filter_by(email=email).with_for_update().populate_existing().first()
        
        if not user or not user.check_password(password):
            raise ValueError('Invalid email or password')
        
        if not user.is_active:
            raise ValueError('Account is deactivated')
        
        if not user.is_verified:
            raise ValueError("Please verify your email address before logging in")
        from src.services.session_service import SessionService
        user = SessionService.principal({'user_id': user.id, 'token_version': user.token_version or 0})
        
        # Update last login
        user.last_login_at = datetime.utcnow()
        if ip_address:
            user.last_login_ip = ip_address
        # Caller signs tokens/challenge then commits while the User lock is held.
        
        return user
    
    @staticmethod
    def verify_2fa(user, token):
        """Verify 2FA token"""
        if not user.two_factor_enabled:
            raise ValueError('2FA is not enabled for this user')
        
        if not user.verify_2fa_token(token):
            raise ValueError('Invalid 2FA token')
        
        return True
    
    @staticmethod
    def enable_2fa(user):
        """Enable 2FA for user"""
        user = User.query.filter_by(id=user.id).with_for_update().populate_existing().one()
        if user.two_factor_enabled:
            raise ValueError('2FA is already enabled')
        
        # Generate secret
        secret = user.generate_2fa_secret()
        db.session.commit()
        
        return user.get_2fa_uri()
    
    @staticmethod
    def confirm_2fa(user, token):
        """Confirm and activate 2FA"""
        user = User.query.filter_by(id=user.id).with_for_update().populate_existing().one()
        if user.two_factor_enabled:
            raise ValueError('2FA is already enabled')
        
        if not user.two_factor_secret:
            raise ValueError('2FA secret not generated')
        
        if not user.verify_2fa_token(token):
            raise ValueError('Invalid 2FA token')
        
        user.two_factor_enabled = True
        user.token_version = (user.token_version or 0) + 1
        db.session.commit()
        
        return True
    
    @staticmethod
    def disable_2fa(user, password):
        """Disable 2FA for user"""
        user = User.query.filter_by(id=user.id).with_for_update().populate_existing().one()
        if not user.check_password(password):
            raise ValueError('Invalid password')
        
        user.two_factor_enabled = False
        user.two_factor_secret = None
        user.token_version = (user.token_version or 0) + 1
        db.session.commit()
        
        return True
    
    @staticmethod
    def verify_email(token_string):
        from src.services.auth_token_service import AuthTokenService
        return AuthTokenService.verify_email(token_string)

    @staticmethod
    def verify_email_with_code(email, code):
        from src.services.auth_token_service import AuthTokenService
        return AuthTokenService.verify_email_with_code(email, code)

    @staticmethod
    def resend_verification_code(email):
        from src.services.auth_token_service import AuthTokenService
        return AuthTokenService.resend_verification_code(email)

    @staticmethod
    def request_password_reset(email):
        from src.services.auth_token_service import AuthTokenService
        return AuthTokenService.request_password_reset(email)

    @staticmethod
    def reset_password(token_string, new_password):
        from src.services.auth_token_service import AuthTokenService
        return AuthTokenService.reset_password(token_string, new_password)

    @staticmethod
    def verify_reset_code(email, code):
        from src.services.auth_token_service import AuthTokenService
        return AuthTokenService.verify_reset_code(email, code)

    @staticmethod
    def reset_password_with_code(email, code, new_password):
        from src.services.auth_token_service import AuthTokenService
        return AuthTokenService.reset_password_with_code(email, code, new_password)

    @staticmethod
    def refresh_access_token(refresh_token):
        # Legacy callers receive access only; public refresh returns both tokens.
        from src.services.session_service import SessionService
        access, rotated = SessionService.rotate(refresh_token)
        return access

    @staticmethod
    def revoke_token(token):
        from src.services.session_service import SessionService
        return SessionService.revoke(token)

    @staticmethod
    def is_token_blacklisted(token):
        from src.services.session_service import SessionService
        return SessionService.is_revoked(token)
