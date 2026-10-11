"""Real PostgreSQL concurrency regression for the parent-owned AuthTokenService."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import threading


def test_auth_token_service_consumes_a_reset_token_once_under_postgresql_concurrency(app):
    """Two simultaneous reset_password calls for one URL token yield one success."""
    from src.database import db
    from src.models.tenant import Tenant
    from src.models.user import PasswordResetToken, User
    from src.services.auth_token_service import AuthTokenService

    # Token input is intentionally synthetic but matches the service's URL-safe
    # length/character validator.  Construct via the production model so the
    # model's current constructor remains the source of truth, then make its
    # values deterministic for the two concurrent consumers.
    raw_token = "synthetic_reset_token_abcdefghijklmnop"
    with app.app_context():
        db.session.add(Tenant(id=1, name="Synthetic", subdomain="synthetic"))
        db.session.add(User(
            id=1, email="reset@example.test", password_hash="synthetic-not-real",
            first_name="Reset", last_name="User", is_active=True, is_verified=True,
            role="trader", tenant_id=1, tree_path="1",
        ))
        token = PasswordResetToken(1)
        token.code = "123456"
        token.token = raw_token
        token.expires_at = datetime.utcnow() + timedelta(minutes=5)
        token.used = False
        db.session.add(token)
        db.session.commit()

    barrier = threading.Barrier(2)

    def contender():
        with app.app_context():
            barrier.wait(timeout=10)
            try:
                result = AuthTokenService.reset_password(raw_token, "StagingOnly!Password123")
                return result is not None
            except ValueError:
                db.session.rollback()
                return False
            finally:
                db.session.remove()

    with ThreadPoolExecutor(max_workers=2) as executor:
        successes = list(executor.map(lambda _: contender(), range(2)))
    assert successes.count(True) == 1, successes

    with app.app_context():
        token = PasswordResetToken.query.filter_by(token=raw_token).one()
        user = db.session.get(User, 1)
        assert token.used is True
        assert user.token_version == 1


def test_session_service_rotates_one_refresh_token_once_under_postgresql_concurrency(app):
    """The same real refresh JWT cannot be consumed twice by concurrent requests."""
    from src.database import db
    from src.models.tenant import Tenant
    from src.models.token_blacklist import TokenBlacklist
    from src.models.user import User
    from src.services.session_service import SessionService

    with app.app_context():
        db.session.add(Tenant(id=1, name="Synthetic", subdomain="synthetic"))
        user = User(
            id=1, email="session@example.test", password_hash="synthetic-not-real",
            first_name="Session", last_name="User", is_active=True, is_verified=True,
            role="trader", tenant_id=1, tree_path="1",
        )
        db.session.add(user)
        db.session.commit()
        _, refresh = SessionService.issue(user)
        original_payload = User.verify_token(refresh, token_type="refresh")
        assert original_payload and original_payload.get("jti") and original_payload.get("sid")

    barrier = threading.Barrier(2)

    def contender():
        with app.app_context():
            barrier.wait(timeout=10)
            try:
                access, rotated = SessionService.rotate(refresh)
                assert access and rotated and rotated != refresh
                return True
            except ValueError:
                return False
            finally:
                db.session.remove()

    with ThreadPoolExecutor(max_workers=2) as executor:
        successes = list(executor.map(lambda _: contender(), range(2)))
    assert successes.count(True) == 1, successes

    with app.app_context():
        assert TokenBlacklist.query.filter_by(jti=original_payload["jti"]).count() == 1
