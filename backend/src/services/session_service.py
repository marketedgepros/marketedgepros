"""JWT principal validation and single-use refresh rotation (existing schema)."""
from datetime import datetime, timezone
import uuid

from flask import current_app
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from src.database import db, get_redis
from src.models.user import User
from src.models.token_blacklist import TokenBlacklist
from src.utils.hierarchy_scoping import without_hierarchy_scope


class SessionService:
    @staticmethod
    def issue(user, session_id=None):
        sid = session_id or str(uuid.uuid4())
        return user.generate_access_token(sid), user.generate_refresh_token(sid)

    @staticmethod
    def payload(token, kind='access'):
        if not isinstance(token, str) or not token or len(token) > 8192:
            raise ValueError('Invalid session')
        payload = User.verify_token(token, token_type=kind)
        if not isinstance(payload, dict):
            raise ValueError('Invalid session')
        identity = payload.get('user_id')
        version = payload.get('token_version', 0)
        if isinstance(identity, bool) or not isinstance(identity, int) or identity < 1:
            raise ValueError('Invalid session')
        if isinstance(version, bool) or not isinstance(version, int) or version < 0:
            raise ValueError('Invalid session')
        return payload

    @staticmethod
    def principal(payload, *, lock=False):
        # Authentication lookup must not inherit a preceding actor's ORM scope.
        # Only this exact principal lookup bypasses hierarchy, not resource data.
        with without_hierarchy_scope(db.session):
            query = select(User).where(User.id == payload['user_id'])
            if lock:
                query = query.with_for_update()
            user = db.session.execute(query.execution_options(populate_existing=True)).scalar_one_or_none()
        if user is None or not user.is_active:
            raise ValueError('Invalid session')
        if not current_app.config.get('EXPANDED_HIERARCHY_ENABLED', False):
            from src.utils.hierarchy_scoping import platform_root_scope
            if user.role == 'supermaster':
                if not platform_root_scope(user):
                    raise ValueError('Role unavailable in launch mode')
            elif user.role not in {'trader', 'affiliate', 'agent', 'guest'}:
                raise ValueError('Role unavailable in launch mode')
            from src.middleware.tenant_middleware import get_tenant_from_request
            brand = get_tenant_from_request()
            if brand is None or user.tenant_id != brand.id:
                raise ValueError('Brand unavailable in launch mode')
        if payload.get('token_version', 0) != (user.token_version or 0):
            raise ValueError('Session revoked')
        return user

    @staticmethod
    def authenticate(token, kind='access'):
        payload = SessionService.payload(token, kind)
        user = SessionService.principal(payload)
        if SessionService.is_revoked(token, payload=payload):
            raise ValueError('Session revoked')
        return user, payload

    @staticmethod
    def is_revoked(token, *, payload=None):
        payload = payload or SessionService.payload(token)
        jti = payload.get('jti')
        # Existing access tokens with no jti are version-bound. New refresh
        # tokens require jti below and legacy refresh credentials are rejected.
        if not jti:
            return False
        if not isinstance(jti, str) or len(jti) > 36:
            raise ValueError('Invalid session')
        redis = get_redis()
        if redis is not None:
            try:
                if redis.exists('blacklist:' + jti):
                    return True
            except Exception:
                current_app.logger.warning('Revocation cache unavailable; checking database')
        # Do not swallow DB failures: a revocation outage cannot authenticate.
        sid = payload.get('sid')
        identifiers = [jti]
        if sid is not None:
            if not isinstance(sid, str) or not sid or len(sid) > 36:
                raise ValueError('Invalid session')
            identifiers.append(sid)
        return TokenBlacklist.query.filter(TokenBlacklist.jti.in_(identifiers)).first() is not None

    @staticmethod
    def _record(payload):
        jti = payload.get('jti')
        if not isinstance(jti, str) or not jti or len(jti) > 36:
            raise ValueError('Session cannot be revoked')
        expiry = payload.get('exp')
        if not isinstance(expiry, (int, float)):
            raise ValueError('Invalid session expiry')
        return TokenBlacklist(jti=jti, token_type=payload['type'], user_id=payload['user_id'],
                              expires_at=datetime.fromtimestamp(expiry, timezone.utc).replace(tzinfo=None))

    @staticmethod
    def rotate(refresh_token):
        payload = SessionService.payload(refresh_token, 'refresh')
        if not payload.get('jti') or not payload.get('sid') or 'token_version' not in payload:
            raise ValueError('Legacy refresh requires login')
        try:
            user = SessionService.principal(payload, lock=True)
            if not user.is_verified or SessionService.is_revoked(refresh_token, payload=payload):
                raise ValueError('Session revoked')
            # Unique jti index is the consume-once gate even when row locks are
            # unavailable (SQLite). The User row serializes refresh/security ops.
            db.session.add(SessionService._record(payload))
            db.session.flush()
            access, refreshed = SessionService.issue(user, payload['sid'])
            db.session.commit()
            return access, refreshed
        except IntegrityError:
            db.session.rollback()
            raise ValueError('Session revoked') from None
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def logout(user, access_token):
        payload = SessionService.payload(access_token)
        if payload['user_id'] != user.id:
            raise ValueError('Invalid session')
        try:
            SessionService.principal(payload, lock=True)
            sid = payload.get('sid')
            if sid:
                # A family blacklist row revokes access and every rotated
                # refresh in this login without revoking unrelated devices.
                if not isinstance(sid, str) or len(sid) > 36:
                    raise ValueError('Invalid session')
                if TokenBlacklist.query.filter_by(jti=sid).first() is None:
                    db.session.add(TokenBlacklist(jti=sid, token_type='family',user_id=user.id,
                        expires_at=datetime.now(timezone.utc).replace(tzinfo=None) + current_app.config['JWT_REFRESH_TOKEN_EXPIRES']))
            elif payload.get('jti'):
                # Legacy access has no family; legacy refresh is rejected by
                # rotation. Keep logout scoped, never silently revoke all users.
                if not SessionService.is_revoked(access_token,payload=payload):
                    db.session.add(SessionService._record(payload))
            else:
                raise ValueError('Session cannot be revoked')
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def revoke(token):
        import jwt
        try:
            payload = jwt.decode(token, current_app.config['JWT_SECRET_KEY'], algorithms=['HS256'],
                                 options={'verify_exp': False, 'require':['exp','user_id','type']})
            if TokenBlacklist.query.filter_by(jti=payload.get('jti')).first() is None:
                db.session.add(SessionService._record(payload))
                db.session.commit()
            return True
        except Exception:
            db.session.rollback()
            raise
