"""Focused security regressions for public authentication responses.

Run without loading the legacy backend/conftest.py:
    cd backend && ../.venv/bin/python -m pytest --confcutdir=security_tests \
        -c /dev/null -q security_tests/test_auth_disclosure.py
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from src.extensions import limiter
from src.routes import auth as auth_routes
from src.routes.auth import auth_bp


VERIFICATION_CODE = "483921"
RESET_CODE = "715204"
PROVIDER_SECRET = "sendgrid-provider-secret-must-not-appear"


class FakeUser:
    """Minimal user serializer that reflects the nested response shape exercised here."""

    def __init__(self, email="existing@example.test"):
        self.email = email
        self.first_name = "Security"
        self.last_name = "Tester"

    def to_dict(self):
        return {
            "id": 17,
            "profile": {
                "email": self.email,
                "name": {
                    "first": self.first_name,
                    "last": self.last_name,
                },
            },
        }


@pytest.fixture
def app():
    """Use the real auth blueprint, with no DB, real provider, or active rate limits."""
    app = Flask(__name__)
    app.config.update(
        EXPANDED_HIERARCHY_ENABLED=True,
        TESTING=True,
        SECRET_KEY="security-suite-only-key",
        RATELIMIT_ENABLED=False,
    )
    limiter.init_app(app)
    app.register_blueprint(auth_bp, url_prefix="/api/v1/auth")
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def _token(user, code):
    return SimpleNamespace(user=user, code=code)


def _assert_code_is_absent(payload, code):
    """Check both serialized values and every nested response key."""
    forbidden_keys = {"verification_code", "reset_code", "code"}
    assert code not in json.dumps(payload)

    def walk(value):
        if isinstance(value, dict):
            for key, nested_value in value.items():
                assert key not in forbidden_keys
                walk(nested_value)
        elif isinstance(value, list):
            for nested_value in value:
                walk(nested_value)

    walk(payload)


def test_register_delivers_code_out_of_band_without_serializing_it(client, monkeypatch):
    user = FakeUser("registered@example.test")
    token = _token(user, VERIFICATION_CODE)
    mail_calls = []

    monkeypatch.setattr(
        auth_routes.AuthService,
        "register_user",
        lambda **kwargs: (user, token),
    )
    monkeypatch.setattr(
        auth_routes.EmailService,
        "send_verification_email",
        lambda recipient, code: mail_calls.append((recipient, code)) or True,
    )

    response = client.post(
        "/api/v1/auth/register",
        json={
            "email": user.email,
            "password": "SecurePassword1!",
            "first_name": user.first_name,
            "last_name": user.last_name,
        },
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["user"]["profile"]["email"] == user.email
    _assert_code_is_absent(payload, VERIFICATION_CODE)
    assert mail_calls == [(user, VERIFICATION_CODE)]


@pytest.mark.parametrize(
    ("endpoint", "service_method", "code"),
    [
        ("/api/v1/auth/resend-verification", "resend_verification_code", VERIFICATION_CODE),
        ("/api/v1/auth/password/reset-request", "request_password_reset", RESET_CODE),
    ],
)
def test_email_requests_have_uniform_existence_response_and_send_only_out_of_band(
    client, monkeypatch, endpoint, service_method, code
):
    user = FakeUser()
    token = _token(user, code)
    mail_calls = []

    monkeypatch.setattr(
        auth_routes.AuthService,
        service_method,
        lambda email: token if email == user.email else None,
    )
    email_method = (
        "send_verification_email"
        if service_method == "resend_verification_code"
        else "send_password_reset_email"
    )
    monkeypatch.setattr(
        auth_routes.EmailService,
        email_method,
        lambda recipient, delivered_code: mail_calls.append((recipient, delivered_code)) or True,
    )

    existing = client.post(endpoint, json={"email": user.email})
    nonexistent = client.post(endpoint, json={"email": "absent@example.test"})

    assert existing.status_code == nonexistent.status_code == 200
    assert existing.get_json() == nonexistent.get_json()
    _assert_code_is_absent(existing.get_json(), code)
    _assert_code_is_absent(nonexistent.get_json(), code)
    assert mail_calls == [(user, code)]


def test_verified_resend_request_matches_nonexistent_account(client, monkeypatch):
    def resend_verification_code(email):
        if email == "verified@example.test":
            raise ValueError("Email is already verified")
        return None

    monkeypatch.setattr(
        auth_routes.AuthService,
        "resend_verification_code",
        resend_verification_code,
    )

    verified = client.post(
        "/api/v1/auth/resend-verification",
        json={"email": "verified@example.test"},
    )
    nonexistent = client.post(
        "/api/v1/auth/resend-verification",
        json={"email": "absent@example.test"},
    )

    assert verified.status_code == nonexistent.status_code == 200
    assert verified.get_json() == nonexistent.get_json()
    assert "already verified" not in verified.get_data(as_text=True).lower()


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/v1/auth/register",
        "/api/v1/auth/resend-verification",
        "/api/v1/auth/password/reset-request",
    ],
)
def test_affected_endpoints_reject_malformed_json_consistently(client, endpoint):
    response = client.post(
        endpoint,
        data='{"email":',
        content_type="application/json",
    )

    assert response.status_code == 400
    assert response.is_json
    assert response.get_json() == {"error": "Invalid request data"}


@pytest.mark.parametrize(
    "endpoint",
    [
        "/api/v1/auth/resend-verification",
        "/api/v1/auth/password/reset-request",
    ],
)
def test_email_request_endpoints_reject_invalid_email_before_service(client, endpoint):
    response = client.post(endpoint, json={"email": "not-an-email"})

    assert response.status_code == 400
    assert response.get_json()["error"] == "Validation failed"


@pytest.mark.parametrize(
    ("endpoint", "service_method", "email_method", "payload", "status", "message", "code"),
    [
        (
            "/api/v1/auth/register",
            "register_user",
            "send_verification_email",
            {
                "email": "registered@example.test",
                "password": "SecurePassword1!",
                "first_name": "Security",
                "last_name": "Tester",
            },
            202,
            "Account created and pending email verification. Use resend verification when email delivery is available.",
            VERIFICATION_CODE,
        ),
        (
            "/api/v1/auth/resend-verification",
            "resend_verification_code",
            "send_verification_email",
            {"email": "existing@example.test"},
            200,
            "If the account is eligible, a verification email has been requested. If nothing arrives, try again later.",
            VERIFICATION_CODE,
        ),
        (
            "/api/v1/auth/password/reset-request",
            "request_password_reset",
            "send_password_reset_email",
            {"email": "existing@example.test"},
            200,
            "If the account is eligible, a password reset email has been requested. If nothing arrives, try again later.",
            RESET_CODE,
        ),
    ],
)
def test_email_provider_exceptions_remain_neutral_and_do_not_disclose_secrets(
    client,
    monkeypatch,
    endpoint,
    service_method,
    email_method,
    payload,
    status,
    message,
    code,
):
    user = FakeUser()
    token = _token(user, code)

    if service_method == "register_user":
        monkeypatch.setattr(
            auth_routes.AuthService,
            service_method,
            lambda **kwargs: (user, token),
        )
    else:
        monkeypatch.setattr(auth_routes.AuthService, service_method, lambda email: token)

    def fail_delivery(*args, **kwargs):
        raise RuntimeError(PROVIDER_SECRET)

    monkeypatch.setattr(auth_routes.EmailService, email_method, fail_delivery)

    response = client.post(endpoint, json=payload)

    assert response.status_code == status
    assert response.get_json()["message"] == message
    if endpoint == "/api/v1/auth/register":
        assert response.get_json()["verification_email_status"] == "unavailable"
    assert PROVIDER_SECRET not in response.get_data(as_text=True)
    assert code not in response.get_data(as_text=True)
