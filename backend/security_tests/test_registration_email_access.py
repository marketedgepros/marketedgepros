"""Isolated route regressions for public account-access email handling.

The fixture uses only in-memory SQLite and monkeypatched email calls. It never
loads a provider credential, opens a network connection, or writes shared data.
"""
import json
from types import SimpleNamespace

import pytest
from flask import Flask
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from src.database import db
from src.extensions import limiter
from src.middleware.tenant_middleware import init_tenant_middleware
from src.models.tenant import Tenant
from src.models.user import EmailVerificationToken, PasswordResetToken, User
from src.routes import auth as auth_routes
from src.routes.auth import auth_bp
from src.utils.hierarchy_scoping import init_hierarchy_scoping


@compiles(JSONB, "sqlite")
def _jsonb_as_json_for_scratch_sqlite(_type, _compiler, **_kwargs):
    """Keep the production tenant model usable in an isolated SQLite fixture."""
    return "JSON"


_ROOT_ID = 9601
_ROOT_TENANT_ID = 9602
_FOREIGN_TENANT_ID = 9603
_TABLES = (
    Tenant.__table__,
    User.__table__,
    EmailVerificationToken.__table__,
    PasswordResetToken.__table__,
)
_ACCOUNT_EMAIL_UNAVAILABLE = {
    "error": "Account email delivery is unavailable.",
    "code": "ACCOUNT_EMAIL_UNAVAILABLE",
}
_RESEND_MESSAGE = (
    "If the account is eligible, a verification email has been requested. "
    "If nothing arrives, try again later."
)
_RESET_MESSAGE = (
    "If the account is eligible, a password reset email has been requested. "
    "If nothing arrives, try again later."
)


@pytest.fixture
def account_access_app():
    """Register the real auth blueprint against a one-brand in-memory database."""
    app = Flask("registration-email-access")
    app.config.update(
        TESTING=True,
        SECRET_KEY="registration-email-access-test-secret",
        JWT_SECRET_KEY="registration-email-access-test-jwt-secret",
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        RATELIMIT_ENABLED=False,
        RATELIMIT_STORAGE_URL="memory://",
        REDIS_URL=None,
        PLATFORM_ROOT_USER_ID=_ROOT_ID,
        EXPANDED_HIERARCHY_ENABLED=False,
        PUBLIC_ACCOUNT_ACCESS_ENABLED=True,
        EMAIL_PROVIDER="brevo",
        BREVO_API_KEY=None,
    )
    db.init_app(app)
    init_hierarchy_scoping(db, User)
    init_tenant_middleware(app)
    limiter.init_app(app)
    app.register_blueprint(auth_bp, url_prefix="/api/v1/auth")

    with app.app_context():
        for table in _TABLES:
            table.create(db.engine)
        db.session.add_all([
            Tenant(
                id=_ROOT_TENANT_ID,
                name="Root brand",
                subdomain="root-brand",
                status="active",
            ),
            Tenant(
                id=_FOREIGN_TENANT_ID,
                name="Foreign brand",
                subdomain="foreign-brand",
                status="active",
            ),
        ])
        root = User(
            id=_ROOT_ID,
            email="root@registration-email.invalid",
            first_name="Configured",
            last_name="Root",
            role="supermaster",
            parent_id=None,
            tree_path=str(_ROOT_ID),
            level=0,
            tenant_id=_ROOT_TENANT_ID,
            is_active=True,
            is_verified=True,
            can_create_same_role=True,
        )
        root.set_password("RootPassword1!")
        db.session.add(root)
        db.session.commit()

    try:
        yield app
    finally:
        with app.app_context():
            db.session.remove()
            for table in reversed(_TABLES):
                table.drop(db.engine)


def _register_payload(email, **overrides):
    payload = {
        "email": email,
        "password": "ValidPassword1!",
        "first_name": "Pending",
        "last_name": "Account",
    }
    payload.update(overrides)
    return payload


def test_real_registration_omits_none_tenant_and_keeps_pending_root_account(
    account_access_app, monkeypatch
):
    """Explicit JSON null is not client tenant selection; a foreign ID still is."""
    monkeypatch.setattr(
        auth_routes.EmailService, "is_configured", lambda: True, raising=False
    )
    monkeypatch.setattr(
        auth_routes.EmailService, "send_verification_email", lambda *_args: False
    )

    client = account_access_app.test_client()
    response = client.post(
        "/api/v1/auth/register",
        json=_register_payload("pending@example.test", tenant_id=None),
    )

    assert response.status_code == 202
    payload = response.get_json()
    assert payload["verification_email_status"] == "unavailable"
    assert payload["message"] == (
        "Account created and pending email verification. Use resend verification "
        "when email delivery is available."
    )
    assert "token" not in json.dumps(payload).lower()
    assert "code" not in payload

    with account_access_app.app_context():
        user = User.query.filter_by(email="pending@example.test").one()
        token = EmailVerificationToken.query.filter_by(user_id=user.id).one()
        assert (
            user.role,
            user.parent_id,
            user.tenant_id,
            user.is_verified,
            user.tree_path,
        ) == ("trader", _ROOT_ID, _ROOT_TENANT_ID, False, f"{_ROOT_ID}/{user.id}")
        assert token.used is False

    foreign = client.post(
        "/api/v1/auth/register",
        json=_register_payload("foreign@example.test", tenant_id=_FOREIGN_TENANT_ID),
    )
    assert foreign.status_code == 400
    assert foreign.get_json() == {"error": "Registration failed"}
    with account_access_app.app_context():
        assert User.query.filter_by(email="foreign@example.test").count() == 0


@pytest.mark.parametrize(
    ("endpoint", "service_method", "payload"),
    [
        (
            "/api/v1/auth/register",
            "register_user",
            _register_payload("unconfigured-register@example.test"),
        ),
        (
            "/api/v1/auth/resend-verification",
            "resend_verification_code",
            {"email": "unconfigured-resend@example.test"},
        ),
        (
            "/api/v1/auth/password/reset-request",
            "request_password_reset",
            {"email": "unconfigured-reset@example.test"},
        ),
    ],
)
def test_account_email_global_gate_runs_before_user_or_token_lookup(
    account_access_app, monkeypatch, endpoint, service_method, payload
):
    """An opted-in but unconfigured delivery service creates no pending state."""
    monkeypatch.setattr(
        auth_routes.EmailService, "is_configured", lambda: False, raising=False
    )

    def _forbidden(*_args, **_kwargs):
        raise AssertionError("email configuration gate reached a user/token service")

    monkeypatch.setattr(auth_routes.AuthService, service_method, _forbidden)
    response = account_access_app.test_client().post(endpoint, json=payload)

    assert response.status_code == 503
    assert response.get_json() == _ACCOUNT_EMAIL_UNAVAILABLE


@pytest.mark.parametrize(
    ("endpoint", "service_method", "email_method", "message"),
    [
        (
            "/api/v1/auth/resend-verification",
            "resend_verification_code",
            "send_verification_email",
            _RESEND_MESSAGE,
        ),
        (
            "/api/v1/auth/password/reset-request",
            "request_password_reset",
            "send_password_reset_email",
            _RESET_MESSAGE,
        ),
    ],
)
def test_resend_and_reset_are_uniform_for_provider_and_eligibility_failures(
    account_access_app, monkeypatch, endpoint, service_method, email_method, message
):
    """No response flag distinguishes provider failure, missing, inactive, or verified."""
    user = SimpleNamespace(email="existing@example.test")
    token = SimpleNamespace(user=user, code="482913")
    monkeypatch.setattr(
        auth_routes.EmailService, "is_configured", lambda: True, raising=False
    )

    def issue_or_decline(email):
        if email == user.email:
            return token
        if email == "verified@example.test":
            raise ValueError("account state is not disclosable")
        # These stand for nonexistent and inactive accounts, both ineligible.
        return None

    def provider_failure(*_args, **_kwargs):
        raise RuntimeError("provider-secret-must-not-appear")

    monkeypatch.setattr(auth_routes.AuthService, service_method, issue_or_decline)
    monkeypatch.setattr(auth_routes.EmailService, email_method, provider_failure)

    responses = [
        account_access_app.test_client().post(endpoint, json={"email": email})
        for email in (
            "existing@example.test",
            "missing@example.test",
            "inactive@example.test",
            "verified@example.test",
        )
    ]
    assert all(response.status_code == 200 for response in responses)
    assert [response.get_json() for response in responses] == [
        {"message": message}
    ] * len(responses)
    assert all("provider-secret" not in response.get_data(as_text=True) for response in responses)
    assert all("482913" not in response.get_data(as_text=True) for response in responses)


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/v1/auth/verify-email",
        "/api/v1/auth/password/reset",
        "/api/v1/auth/password/verify-code",
        "/api/v1/auth/password/reset-with-code",
    ],
)
def test_code_and_reset_routes_reject_malformed_json_without_lookup(
    account_access_app, endpoint
):
    response = account_access_app.test_client().post(
        endpoint, data=b'{"email":', content_type="application/json"
    )
    assert response.status_code == 400
    assert response.get_json() == {"error": "Invalid request data"}


def test_verification_audit_redacts_code_and_sanitizes_failure_reason(
    account_access_app, monkeypatch
):
    from src.models.verification_attempt import VerificationAttempt

    audit_records = []
    sensitive_code = "482913"
    monkeypatch.setattr(
        VerificationAttempt, "is_rate_limited", lambda *_args, **_kwargs: False
    )
    monkeypatch.setattr(
        VerificationAttempt,
        "log_attempt",
        lambda **kwargs: audit_records.append(kwargs),
    )
    monkeypatch.setattr(
        auth_routes.AuthService,
        "verify_email_with_code",
        lambda *_args: (_ for _ in ()).throw(
            ValueError("synthetic provider detail " + sensitive_code)
        ),
    )

    response = account_access_app.test_client().post(
        "/api/v1/auth/verify-email",
        json={"email": "audit@example.test", "code": sensitive_code},
    )

    assert response.status_code == 400
    assert response.get_json() == {"error": "Invalid or expired verification code"}
    assert sensitive_code not in response.get_data(as_text=True)
    assert len(audit_records) == 1
    assert audit_records[0]["email"] == "audit@example.test"
    assert audit_records[0]["code_entered"] == "******"
    assert audit_records[0]["success"] is False
    assert audit_records[0]["ip_address"] == "127.0.0.1"
    assert audit_records[0]["failure_reason"] == "invalid_or_expired_code"
    assert sensitive_code not in repr(audit_records[0])


def test_welcome_provider_failure_does_not_turn_verified_route_into_failure(
    account_access_app, monkeypatch
):
    user = SimpleNamespace(to_dict=lambda: {"email": "verified@example.test"})
    monkeypatch.setattr(auth_routes.AuthService, "verify_email", lambda _token: user)
    monkeypatch.setattr(
        auth_routes.EmailService,
        "send_welcome_email",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("unavailable")),
    )

    response = account_access_app.test_client().get(
        "/api/v1/auth/verify-email/" + ("x" * 32)
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "message": "Email verified successfully",
        "user": {"email": "verified@example.test"},
    }
