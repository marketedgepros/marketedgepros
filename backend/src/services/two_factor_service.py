"""Password-bound, single-use second-factor login challenge."""
from datetime import datetime, timedelta, timezone
import uuid
import jwt
from flask import current_app
from sqlalchemy.exc import IntegrityError
from src.database import db
from src.services.session_service import SessionService
from src.models.token_blacklist import TokenBlacklist


class TwoFactorService:
    @staticmethod
    def issue(user):
        now = datetime.now(timezone.utc)
        claims = {'user_id': user.id, 'type': 'preauth', 'jti': str(uuid.uuid4()),
                  'token_version': user.token_version or 0,
                  'iat': now, 'exp': now + timedelta(minutes=5)}
        return jwt.encode(claims, current_app.config['JWT_SECRET_KEY'], algorithm='HS256')

    @staticmethod
    def complete(challenge_token, code, user_id=None):
        if not isinstance(challenge_token, str) or len(challenge_token) > 8192:
            raise ValueError('Invalid second factor')
        if not isinstance(code, str) or len(code) != 6 or not code.isascii() or not code.isdigit():
            raise ValueError('Invalid second factor')
        try:
            claims = jwt.decode(challenge_token, current_app.config['JWT_SECRET_KEY'],
                                algorithms=['HS256'], options={'require':['user_id','type','jti','exp','iat','token_version']})
            if claims['type'] != 'preauth' or type(claims['user_id']) is not int or claims['user_id'] < 1:
                raise ValueError('Invalid second factor')
            if type(claims['token_version']) is not int or claims['token_version'] < 0:
                raise ValueError('Invalid second factor')
            if type(claims['iat']) is not int or claims['iat'] <= 0:
                raise ValueError('Invalid second factor')
            if type(claims['exp']) is not int or not 0 < claims['exp'] - claims['iat'] <= 300:
                raise ValueError('Invalid second factor')
            if not isinstance(claims['jti'],str) or len(claims['jti']) != 36:
                raise ValueError('Invalid second factor')
            if user_id is not None and (isinstance(user_id, bool) or user_id != claims['user_id']):
                raise ValueError('Invalid second factor')
            user = SessionService.principal(claims, lock=True)
            if not user.is_verified or not user.two_factor_enabled:
                raise ValueError('Invalid second factor')
            if TokenBlacklist.query.filter_by(jti=claims['jti']).first():
                raise ValueError('Invalid second factor')
            if not user.verify_2fa_token(code):
                raise ValueError('Invalid second factor')
            db.session.add(SessionService._record(claims))
            db.session.flush()
            access, refresh = SessionService.issue(user)
            db.session.commit()
            return user, access, refresh
        except (jwt.InvalidTokenError, IntegrityError, KeyError, TypeError):
            db.session.rollback()
            raise ValueError('Invalid second factor') from None
        except Exception:
            db.session.rollback()
            raise
