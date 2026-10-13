"""Focused transaction regressions for ``AuthTokenService``.

These tests intentionally instantiate real Flask-SQLAlchemy models against only
an in-memory SQLite database.  They call the lifecycle service directly because
route delegation is owned by the parent integration change.
"""
from datetime import datetime, timedelta

from flask import Flask
import jwt
import pytest

from src.database import db
from src.models import EmailVerificationToken, PasswordResetToken, User
from src.services.auth_token_service import AuthTokenService


_AUTH_TABLES = [
    User.__table__,
    EmailVerificationToken.__table__,
    PasswordResetToken.__table__,
]


@pytest.fixture
def lifecycle_app():
    """A real Flask app and real models with no networked or credentialed resources."""
    app = Flask("auth-token-lifecycle")
    app.config.update(
        EXPANDED_HIERARCHY_ENABLED=True,
        TESTING=True,
        SECRET_KEY="focused-test-key-only",
        JWT_SECRET_KEY="focused-test-jwt-key-only",
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(hours=1),
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        REDIS_URL=None,
        SENDGRID_API_KEY=None,
        RATELIMIT_STORAGE_URL="memory://",
    )
    db.init_app(app)
    with app.app_context():
        # Other legacy models contain an unrelated duplicate SQLite index.  This
        # remains a real Flask-SQLAlchemy test of the complete auth table set.
        db.metadata.create_all(bind=db.engine, tables=_AUTH_TABLES)
        try:
            yield app
        finally:
            db.session.remove()
            db.metadata.drop_all(bind=db.engine, tables=list(reversed(_AUTH_TABLES)))


def _new_user(email, *, active=True):
    user = User(
        email=email,
        first_name="Lifecycle",
        last_name="Test",
        is_active=active,
    )
    user.set_password("OldPassword1!")
    db.session.add(user)
    db.session.commit()
    return user


def _safe_url_token(kind, user_id, marker):
    """Generate a deterministic valid-shaped token without using sensitive data."""
    return (f"{kind}-{user_id}-{marker}-" + ("x" * 64))[:43]


def _stored_token(
    model,
    user,
    *,
    kind,
    marker,
    code="123456",
    expires_at=None,
    created_at=None,
    used=False,
):
    token = model(user.id)
    token.token = _safe_url_token(kind, user.id, marker)
    token.code = code
    token.expires_at = expires_at or (datetime.utcnow() + timedelta(hours=1))
    token.created_at = created_at or datetime.utcnow()
    token.used = used
    db.session.add(token)
    db.session.commit()
    return token


def _get(model, identity):
    return db.session.query(model).filter(model.id == identity).one()


def test_real_flask_sqlite_fixture_has_no_credentials_or_network_resources(lifecycle_app):
    assert lifecycle_app.config["SQLALCHEMY_DATABASE_URI"] == "sqlite:///:memory:"
    assert lifecycle_app.config["REDIS_URL"] is None
    assert lifecycle_app.config["SENDGRID_API_KEY"] is None
    assert db.engine.url.database == ":memory:"


def test_verification_issue_cooldown_invalidates_siblings_and_never_reuses_expired(lifecycle_app):
    with lifecycle_app.app_context():
        user = _new_user("issue@example.test")
        stale = _stored_token(
            EmailVerificationToken,
            user,
            kind="verify",
            marker="stale",
            created_at=datetime.utcnow() - timedelta(minutes=3),
        )

        issued = AuthTokenService.resend_verification_code(user.email)
        assert issued is not None
        assert issued.id != stale.id
        assert _get(EmailVerificationToken, stale.id).used is True
        assert _get(EmailVerificationToken, issued.id).used is False

        # A still-valid delivery token in the two-minute cooldown is reused.
        cooldown_result = AuthTokenService.resend_verification_code(user.email)
        assert cooldown_result.id == issued.id
        assert db.session.query(EmailVerificationToken).count() == 2

        # An expired latest token must not be returned merely because it is recent.
        current = _get(EmailVerificationToken, issued.id)
        current.expires_at = datetime.utcnow() - timedelta(seconds=1)
        current.created_at = datetime.utcnow()
        db.session.commit()
        replacement = AuthTokenService.resend_verification_code(user.email)
        assert replacement.id != issued.id
        assert _get(EmailVerificationToken, issued.id).used is True
        assert _get(EmailVerificationToken, replacement.id).used is False


def test_reset_request_has_the_same_cooldown_and_expired_token_rules(lifecycle_app):
    with lifecycle_app.app_context():
        user = _new_user("request-reset@example.test")
        stale = _stored_token(
            PasswordResetToken,
            user,
            kind="reset",
            marker="stale",
            created_at=datetime.utcnow() - timedelta(minutes=3),
        )

        issued = AuthTokenService.request_password_reset(user.email)
        assert issued is not None
        assert issued.id != stale.id
        assert _get(PasswordResetToken, stale.id).used is True
        assert AuthTokenService.request_password_reset(user.email).id == issued.id

        current = _get(PasswordResetToken, issued.id)
        current.expires_at = datetime.utcnow() - timedelta(seconds=1)
        current.created_at = datetime.utcnow()
        db.session.commit()
        replacement = AuthTokenService.request_password_reset(user.email)
        assert replacement.id != issued.id
        assert _get(PasswordResetToken, issued.id).used is True


def test_email_url_consumption_is_single_use_invalidates_siblings_and_requires_active(lifecycle_app):
    with lifecycle_app.app_context():
        user = _new_user("verify@example.test")
        consumed = _stored_token(EmailVerificationToken, user, kind="verify", marker="one")
        sibling = _stored_token(EmailVerificationToken, user, kind="verify", marker="two")

        verified_user = AuthTokenService.verify_email(consumed.token)
        assert verified_user.id == user.id
        assert verified_user.is_verified is True
        assert verified_user.email_verified_at is not None
        assert _get(EmailVerificationToken, consumed.id).used is True
        assert _get(EmailVerificationToken, sibling.id).used is True

        with pytest.raises(ValueError, match="Invalid or expired token"):
            AuthTokenService.verify_email(consumed.token)
        # A caller controls rollback after an invalid request; nothing was persisted.
        db.session.rollback()
        assert _get(User, user.id).is_verified is True

        inactive = _new_user("inactive-verify@example.test", active=False)
        inactive_token = _stored_token(
            EmailVerificationToken, inactive, kind="verify", marker="inactive"
        )
        with pytest.raises(ValueError, match="Invalid or expired token"):
            AuthTokenService.verify_email(inactive_token.token)
        db.session.rollback()
        assert _get(User, inactive.id).is_active is False
        assert _get(User, inactive.id).is_verified is False
        assert _get(EmailVerificationToken, inactive_token.id).used is False


def test_duplicate_verification_codes_are_scoped_to_the_locked_email_owner(lifecycle_app):
    with lifecycle_app.app_context():
        first = _new_user("first-code@example.test")
        second = _new_user("second-code@example.test")
        first_token = _stored_token(
            EmailVerificationToken, first, kind="verify", marker="first", code="555555"
        )
        second_token = _stored_token(
            EmailVerificationToken, second, kind="verify", marker="second", code="555555"
        )

        AuthTokenService.verify_email_with_code(first.email, "555555")
        assert _get(User, first.id).is_verified is True
        assert _get(EmailVerificationToken, first_token.id).used is True
        assert _get(User, second.id).is_verified is False
        assert _get(EmailVerificationToken, second_token.id).used is False


def test_reset_code_check_is_non_consuming_then_reset_bumps_token_version(lifecycle_app):
    with lifecycle_app.app_context():
        user = _new_user("reset-code@example.test")
        reset = _stored_token(
            PasswordResetToken, user, kind="reset", marker="code", code="246810"
        )
        old_access_token = user.generate_access_token()
        old_claims = jwt.decode(
            old_access_token,
            lifecycle_app.config["JWT_SECRET_KEY"],
            algorithms=["HS256"],
        )

        checked = AuthTokenService.verify_reset_code(user.email, reset.code)
        assert checked.id == reset.id
        assert _get(PasswordResetToken, reset.id).used is False

        reset_user = AuthTokenService.reset_password_with_code(
            user.email, reset.code, "NewPassword2!"
        )
        assert reset_user.check_password("NewPassword2!") is True
        assert reset_user.token_version == old_claims["token_version"] + 1
        assert _get(PasswordResetToken, reset.id).used is True


def test_duplicate_reset_codes_are_scoped_and_inactive_reset_never_reactivates(lifecycle_app):
    with lifecycle_app.app_context():
        first = _new_user("first-reset@example.test")
        second = _new_user("second-reset@example.test")
        first_token = _stored_token(
            PasswordResetToken, first, kind="reset", marker="first", code="112233"
        )
        second_token = _stored_token(
            PasswordResetToken, second, kind="reset", marker="second", code="112233"
        )

        AuthTokenService.reset_password_with_code(first.email, "112233", "ChangedPassword3!")
        assert _get(PasswordResetToken, first_token.id).used is True
        assert _get(PasswordResetToken, second_token.id).used is False
        assert _get(User, second.id).check_password("OldPassword1!") is True

        inactive = _new_user("inactive-reset@example.test", active=False)
        inactive_token = _stored_token(
            PasswordResetToken, inactive, kind="reset", marker="inactive", code="998877"
        )
        reset_user = AuthTokenService.reset_password(
            inactive_token.token, "InactivePassword4!"
        )
        assert reset_user.is_active is False
        assert _get(User, inactive.id).is_active is False
        assert _get(User, inactive.id).check_password("InactivePassword4!") is True


def test_url_reset_invalidates_siblings_and_guarded_invalid_paths_have_no_partial_state(lifecycle_app):
    with lifecycle_app.app_context():
        user = _new_user("url-reset@example.test")
        consumed = _stored_token(PasswordResetToken, user, kind="reset", marker="one")
        sibling = _stored_token(PasswordResetToken, user, kind="reset", marker="two")

        AuthTokenService.reset_password(consumed.token, "NewPassword5!")
        assert _get(PasswordResetToken, consumed.id).used is True
        assert _get(PasswordResetToken, sibling.id).used is True
        assert _get(User, user.id).token_version == 1

        untouched = _new_user("untouched@example.test")
        expired = _stored_token(
            PasswordResetToken,
            untouched,
            kind="reset",
            marker="expired",
            expires_at=datetime.utcnow() - timedelta(seconds=1),
        )
        original_hash = _get(User, untouched.id).password_hash
        original_version = _get(User, untouched.id).token_version
        with pytest.raises(ValueError, match="Invalid or expired token"):
            AuthTokenService.reset_password(expired.token, "ChangedPassword6!")
        # The failed guarded UPDATE did not change any persistent auth state.
        db.session.rollback()
        db.session.expire_all()
        assert _get(User, untouched.id).password_hash == original_hash
        assert _get(User, untouched.id).token_version == original_version
        assert _get(PasswordResetToken, expired.id).used is False


def test_malformed_service_inputs_are_rejected_before_token_lookup(lifecycle_app):
    with lifecycle_app.app_context():
        user = _new_user("malformed@example.test")
        token = _stored_token(PasswordResetToken, user, kind="reset", marker="malformed")

        with pytest.raises(ValueError):
            AuthTokenService.request_password_reset("not an email")
        with pytest.raises(ValueError):
            AuthTokenService.verify_email_with_code(user.email, "12x456")
        with pytest.raises(ValueError):
            AuthTokenService.reset_password("short", "NewPassword7!")
        with pytest.raises(ValueError):
            AuthTokenService.reset_password(token.token, "weak")

        assert _get(PasswordResetToken, token.id).used is False
        assert _get(User, user.id).check_password("OldPassword1!") is True


@pytest.mark.parametrize('mode', ['url', 'code'])
def test_symbol_optional_reset_revokes_prior_tokens_and_preserves_other_accounts(lifecycle_app, mode):
    with lifecycle_app.app_context():
        user = _new_user('policy-reset@example.test')
        other = _new_user('policy-untouched@example.test')
        before = (user.role, user.tenant_id, user.is_active, user.is_verified, user.two_factor_enabled)
        other_hash = other.password_hash
        prior = jwt.decode(user.generate_access_token(), lifecycle_app.config['JWT_SECRET_KEY'], algorithms=['HS256'])
        chosen = _stored_token(PasswordResetToken, user, kind='reset', marker='chosen')
        sibling = _stored_token(PasswordResetToken, user, kind='reset', marker='sibling')
        if mode == 'url':
            result = AuthTokenService.reset_password(chosen.token, 'SyntheticNew8')
        else:
            result = AuthTokenService.reset_password_with_code(user.email, chosen.code, 'SyntheticNew8')
        assert result.check_password('SyntheticNew8')
        assert not result.check_password('OldPassword1!')
        assert result.token_version == prior['token_version'] + 1
        assert (result.role, result.tenant_id, result.is_active, result.is_verified, result.two_factor_enabled) == before
        assert _get(PasswordResetToken, chosen.id).used
        assert _get(PasswordResetToken, sibling.id).used
        assert _get(User, other.id).password_hash == other_hash
        assert _get(User, other.id).token_version == 0
