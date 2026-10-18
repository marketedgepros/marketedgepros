"""Transactional lifecycle operations for email-verification and password-reset tokens.

This module intentionally works with the legacy plaintext ``code`` and ``token``
columns.  It is a containment layer: hashes-at-rest require a separate migration
because replacing the lookup values in the existing columns would invalidate
outstanding delivery links and codes.

Every state-changing path locks the authoritative ``User`` row before it locks
or updates either token table.  PostgreSQL receives ``FOR UPDATE`` locks;
SQLite still receives guarded SQL ``UPDATE`` statements whose row count is the
single-use authority.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import re
from typing import Optional, Tuple, Type

from sqlalchemy import update

from src.database import db
from src.models import EmailVerificationToken, PasswordResetToken, User


_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
_CODE_PATTERN = re.compile(r"^[0-9]{6}$")
_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_COOLDOWN = timedelta(minutes=2)

TokenModel = Type[EmailVerificationToken] | Type[PasswordResetToken]


class AuthTokenService:
    """Secure token issuance and consumption compatible with ``AuthService`` APIs.

    Public methods that issue or consume a token commit exactly once after all
    writes succeed.  They deliberately do not call ``session.rollback()`` on
    exceptions: the caller owns rollback and can decide how to handle an error
    without this service silently discarding its surrounding transaction.
    """

    @staticmethod
    def _email(email: object) -> str:
        """Return a bounded, syntactically safe email address for a DB lookup."""
        if not isinstance(email, str):
            raise ValueError("Invalid email")
        value = email.strip()
        if len(value) > 255 or not _EMAIL_PATTERN.fullmatch(value):
            raise ValueError("Invalid email")
        return value

    @staticmethod
    def _code(code: object) -> str:
        """Validate a six-digit out-of-band code without coercing input."""
        if not isinstance(code, str) or not _CODE_PATTERN.fullmatch(code):
            raise ValueError("Invalid verification code")
        return code

    @staticmethod
    def _token(token_string: object) -> str:
        """Validate the legacy URL-safe token shape before querying storage."""
        if not isinstance(token_string, str) or not _TOKEN_PATTERN.fullmatch(token_string):
            raise ValueError("Invalid or expired token")
        return token_string

    @staticmethod
    def _password(new_password: object) -> str:
        """Enforce the same baseline password policy for direct service callers."""
        if (
            not isinstance(new_password, str)
            or len(new_password) > 1024
            or len(new_password) < 8
            or not re.search(r"[A-Z]", new_password)
            or not re.search(r"[a-z]", new_password)
            or not re.search(r"\d", new_password)
        ):
            raise ValueError("Invalid password")
        return new_password

    @staticmethod
    def _lock_user_by_email(email: str) -> Optional[User]:
        """Lock the authoritative user first for all email-addressed operations."""
        return (
            db.session.query(User)
            .filter(User.email == email)
            .with_for_update()
            .populate_existing()
            .one_or_none()
        )

    @staticmethod
    def _lock_user_then_token_by_value(
        model: TokenModel, field_name: str, value: str
    ) -> Tuple[Optional[User], Optional[object]]:
        """Locate a user id without a token lock, then lock User before the token.

        The first small lookup is intentionally non-locking.  It only supplies
        the immutable foreign-key value needed to lock the authoritative user.
        The token is re-read *after* that user lock, so all mutations retain the
        same User -> token lock order and do not act on a stale candidate.
        """
        field = getattr(model, field_name)
        candidate_user_id = (
            db.session.query(model.user_id)
            .filter(field == value)
            .scalar()
        )
        if candidate_user_id is None:
            return None, None

        user = (
            db.session.query(User)
            .filter(User.id == candidate_user_id)
            .with_for_update()
            .populate_existing()
            .one_or_none()
        )
        if user is None:
            return None, None

        token = (
            db.session.query(model)
            .filter(model.user_id == user.id, field == value)
            .with_for_update()
            .populate_existing()
            .one_or_none()
        )
        return user, token

    @staticmethod
    def _latest_valid_token(model: TokenModel, user_id: int, now: datetime):
        """Lock the latest reusable delivery token only after its user is locked."""
        return (
            db.session.query(model)
            .filter(
                model.user_id == user_id,
                model.used.is_(False),
                model.expires_at > now,
                model.created_at > now - _COOLDOWN,
            )
            .order_by(model.created_at.desc(), model.id.desc())
            .with_for_update()
            .first()
        )

    @staticmethod
    def _issue(model: TokenModel, user: User, now: datetime):
        """Invalidate every unused sibling and create a fresh token in one commit."""
        db.session.execute(
            update(model)
            .where(model.user_id == user.id, model.used.is_(False))
            .values(used=True)
        )
        token = model(user.id)
        db.session.add(token)
        db.session.commit()
        return token

    @staticmethod
    def _consume(model: TokenModel, user: User, token: object, now: datetime) -> None:
        """Atomically consume one unexpired token and invalidate its siblings.

        The guarded UPDATE is mandatory even after ``FOR UPDATE``: it makes the
        single-use decision atomic on SQLite, where ``FOR UPDATE`` is ignored,
        as well as on PostgreSQL.
        """
        result = db.session.execute(
            update(model)
            .where(
                model.id == token.id,
                model.user_id == user.id,
                model.used.is_(False),
                model.expires_at > now,
            )
            .values(used=True)
        )
        if result.rowcount != 1:
            raise ValueError("Invalid or expired token")

        db.session.execute(
            update(model)
            .where(
                model.user_id == user.id,
                model.id != token.id,
                model.used.is_(False),
            )
            .values(used=True)
        )

    @staticmethod
    def resend_verification_code(email):
        """Return a delivery token for an existing active, unverified account.

        A valid token created during the two-minute cooldown is returned without
        creating a replacement.  An expired latest token is never returned:
        issuance marks it used and creates a fresh token instead.
        """
        normalized_email = AuthTokenService._email(email)
        user = AuthTokenService._lock_user_by_email(normalized_email)
        if user is None or not user.is_active or user.is_verified:
            db.session.commit()
            return None

        now = datetime.utcnow()
        existing = AuthTokenService._latest_valid_token(
            EmailVerificationToken, user.id, now
        )
        if existing is not None:
            db.session.commit()
            return existing
        return AuthTokenService._issue(EmailVerificationToken, user, now)

    @staticmethod
    def request_password_reset(email):
        """Return a delivery token for an existing account without enumeration.

        Inactive accounts retain the legacy ability to reset their password, but
        this method never changes ``is_active``.  Route callers must return the
        same success response for ``None`` and a real token.
        """
        normalized_email = AuthTokenService._email(email)
        user = AuthTokenService._lock_user_by_email(normalized_email)
        if user is None:
            db.session.commit()
            return None

        now = datetime.utcnow()
        existing = AuthTokenService._latest_valid_token(
            PasswordResetToken, user.id, now
        )
        if existing is not None:
            db.session.commit()
            return existing
        return AuthTokenService._issue(PasswordResetToken, user, now)

    @staticmethod
    def verify_email(token_string):
        """Consume a URL verification token for an existing active user."""
        value = AuthTokenService._token(token_string)
        user, token = AuthTokenService._lock_user_then_token_by_value(
            EmailVerificationToken, "token", value
        )
        if user is None or token is None or not user.is_active:
            raise ValueError("Invalid or expired token")

        AuthTokenService._consume(EmailVerificationToken, user, token, datetime.utcnow())
        user.is_verified = True
        user.email_verified_at = datetime.utcnow()
        db.session.commit()
        return user

    @staticmethod
    def verify_email_with_code(email, code):
        """Consume an email verification code scoped to the locked email owner."""
        normalized_email = AuthTokenService._email(email)
        normalized_code = AuthTokenService._code(code)
        user = AuthTokenService._lock_user_by_email(normalized_email)
        if user is None or not user.is_active:
            raise ValueError("Invalid or expired verification code")

        token = (
            db.session.query(EmailVerificationToken)
            .filter(
                EmailVerificationToken.user_id == user.id,
                EmailVerificationToken.code == normalized_code,
            )
            .order_by(EmailVerificationToken.created_at.desc(), EmailVerificationToken.id.desc())
            .with_for_update()
            .first()
        )
        if token is None:
            raise ValueError("Invalid or expired verification code")

        try:
            AuthTokenService._consume(EmailVerificationToken, user, token, datetime.utcnow())
        except ValueError:
            raise ValueError("Invalid or expired verification code") from None
        user.is_verified = True
        user.email_verified_at = datetime.utcnow()
        db.session.commit()
        return user

    @staticmethod
    def verify_reset_code(email, code):
        """Check a reset code without consuming it; reset verifies again atomically."""
        normalized_email = AuthTokenService._email(email)
        normalized_code = AuthTokenService._code(code)
        user = AuthTokenService._lock_user_by_email(normalized_email)
        if user is None:
            raise ValueError("Invalid or expired reset code")

        token = (
            db.session.query(PasswordResetToken)
            .filter(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.code == normalized_code,
                PasswordResetToken.used.is_(False),
                PasswordResetToken.expires_at > datetime.utcnow(),
            )
            .order_by(PasswordResetToken.created_at.desc(), PasswordResetToken.id.desc())
            .with_for_update()
            .first()
        )
        if token is None:
            raise ValueError("Invalid or expired reset code")
        db.session.commit()
        return token

    @staticmethod
    def reset_password(token_string, new_password):
        """Consume a URL reset token, change password, and revoke prior sessions."""
        value = AuthTokenService._token(token_string)
        password = AuthTokenService._password(new_password)
        user, token = AuthTokenService._lock_user_then_token_by_value(
            PasswordResetToken, "token", value
        )
        if user is None or token is None:
            raise ValueError("Invalid or expired token")

        AuthTokenService._consume(PasswordResetToken, user, token, datetime.utcnow())
        user.set_password(password)
        user.token_version = (user.token_version or 0) + 1
        db.session.commit()
        return user

    @staticmethod
    def reset_password_with_code(email, code, new_password):
        """Consume an email-scoped reset code, change password, and revoke sessions."""
        normalized_email = AuthTokenService._email(email)
        normalized_code = AuthTokenService._code(code)
        password = AuthTokenService._password(new_password)
        user = AuthTokenService._lock_user_by_email(normalized_email)
        if user is None:
            raise ValueError("Invalid or expired reset code")

        token = (
            db.session.query(PasswordResetToken)
            .filter(
                PasswordResetToken.user_id == user.id,
                PasswordResetToken.code == normalized_code,
            )
            .order_by(PasswordResetToken.created_at.desc(), PasswordResetToken.id.desc())
            .with_for_update()
            .first()
        )
        if token is None:
            raise ValueError("Invalid or expired reset code")

        try:
            AuthTokenService._consume(PasswordResetToken, user, token, datetime.utcnow())
        except ValueError:
            raise ValueError("Invalid or expired reset code") from None
        user.set_password(password)
        user.token_version = (user.token_version or 0) + 1
        db.session.commit()
        return user
