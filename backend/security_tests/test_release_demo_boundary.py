"""Focused request-boundary regressions for the constrained demo release."""
from types import SimpleNamespace

import pytest
from flask.wrappers import Request

from src.app import create_app
from src.database import db
from src.routes import auth as auth_routes
from src.routes import chat as chat_routes


AUTH_ACTION_UNAVAILABLE = {
    "error": "Registration and email actions are unavailable in this demo release.",
    "code": "DEMO_ACTION_UNAVAILABLE",
}
CHAT_ACTION_UNAVAILABLE = {
    "error": "Chat provider is unavailable in this demo release.",
    "code": "DEMO_ACTION_UNAVAILABLE",
}


@pytest.fixture
def demo_app():
    """Use the real factory with its explicit test-only demo override."""
    app = create_app(
        "testing",
        config_overrides={
            "DEMO_RELEASE_ENABLED": True,
            # Keep the test request path free of the tenant DB middleware.  A
            # separate regression verifies registration ordering with it enabled.
            "EXPANDED_HIERARCHY_ENABLED": True,
        },
    )
    yield app
    with app.app_context():
        db.session.remove()


@pytest.fixture
def demo_client(demo_app):
    return demo_app.test_client()


def _forbidden(name):
    def fail(*_args, **_kwargs):
        raise AssertionError(f"demo boundary reached forbidden {name}")

    return fail


def _install_blocked_action_canaries(monkeypatch):
    """Any route/decorator work after the boundary makes this test fail loudly."""
    monkeypatch.setattr(Request, "get_json", _forbidden("request body parser"))
    monkeypatch.setattr(auth_routes.db.session, "commit", _forbidden("user commit"))
    for method in (
        "register_user",
        "resend_verification_code",
        "request_password_reset",
        "verify_email",
        "verify_email_with_code",
    ):
        monkeypatch.setattr(auth_routes.AuthService, method, _forbidden(f"AuthService.{method}"))
    for method in (
        "send_verification_email",
        "send_password_reset_email",
        "send_welcome_email",
    ):
        monkeypatch.setattr(auth_routes.EmailService, method, _forbidden(f"EmailService.{method}"))


@pytest.mark.parametrize(
    ("path", "method", "payload"),
    [
        (
            "/api/v1/auth/register",
            "post",
            {
                "email": "valid-register@example.test",
                "password": "ValidPassword1!",
                "first_name": "Valid",
                "last_name": "Register",
            },
        ),
        (
            "/api/v1/auth/resend-verification",
            "post",
            {"email": "valid-resend@example.test"},
        ),
        (
            "/api/v1/auth/password/reset-request",
            "post",
            {"email": "valid-reset@example.test"},
        ),
        (
            "/api/v1/auth/password/reset",
            "post",
            {"token": "opaque-reset-token", "new_password": "ValidPassword1!"},
        ),
        (
            "/api/v1/auth/password/verify-code",
            "post",
            {"email": "valid-code@example.test", "code": "482913"},
        ),
        (
            "/api/v1/auth/password/reset-with-code",
            "post",
            {
                "email": "valid-reset-code@example.test",
                "code": "482913",
                "new_password": "ValidPassword1!",
            },
        ),
        (
            "/api/v1/auth/verify-email",
            "post",
            {"email": "valid-verify@example.test", "code": "482913"},
        ),
        ("/api/v1/auth/verify-email/opaque-verification-token", "get", None),
    ],
)
def test_demo_refuses_email_actions_before_body_services_email_or_commit(
    demo_client, monkeypatch, path, method, payload
):
    _install_blocked_action_canaries(monkeypatch)

    response = getattr(demo_client, method)(path, json=payload) if payload else getattr(
        demo_client, method
    )(path)

    assert response.status_code == 503
    assert response.get_json() == AUTH_ACTION_UNAVAILABLE


def test_demo_refuses_every_chat_prefix_before_body_or_provider(demo_client, monkeypatch):
    monkeypatch.setattr(Request, "get_json", _forbidden("request body parser"))
    monkeypatch.setattr(chat_routes, "get_openai_service", _forbidden("chat provider"))

    response = demo_client.post(
        "/api/v1/chat/faq",
        json={"question": "Will this reach the configured provider?"},
    )

    assert response.status_code == 503
    assert response.get_json() == CHAT_ACTION_UNAVAILABLE
    assert "Registration and email" not in response.get_json()["error"]


def test_testing_factory_explicit_demo_override_registers_guard_before_tenant_middleware():
    app = create_app(
        "testing",
        config_overrides={
            "DEMO_RELEASE_ENABLED": True,
            "EXPANDED_HIERARCHY_ENABLED": False,
        },
    )
    try:
        handlers = app.before_request_funcs[None]
        handler_names = [handler.__name__ for handler in handlers]
        assert app.config["DEMO_RELEASE_ENABLED"] is True
        assert handler_names.index("enforce_demo_release_boundary") < handler_names.index(
            "set_tenant_context"
        )
    finally:
        with app.app_context():
            db.session.remove()


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/auth/login",
        "/api/v1/auth/login/2fa",
        "/api/v1/profile",
    ],
)
def test_demo_boundary_does_not_broadly_block_existing_owner_actions(demo_app, path):
    guard = next(
        handler
        for handler in demo_app.before_request_funcs[None]
        if handler.__name__ == "enforce_demo_release_boundary"
    )
    with demo_app.test_request_context(path, method="POST"):
        assert guard() is None


def test_historical_register_route_is_not_refused_when_demo_is_off(monkeypatch):
    app = create_app("testing")
    try:
        user = SimpleNamespace(to_dict=lambda: {"email": "owner@example.test"})
        token = SimpleNamespace(user=user, code="482913")
        monkeypatch.setattr(
            auth_routes.AuthService,
            "register_user",
            lambda **_kwargs: (user, token),
        )
        monkeypatch.setattr(
            auth_routes.EmailService,
            "send_verification_email",
            lambda *_args: True,
        )

        response = app.test_client().post(
            "/api/v1/auth/register",
            json={
                "email": "owner@example.test",
                "password": "ValidPassword1!",
                "first_name": "Owner",
                "last_name": "Existing",
            },
        )

        assert response.status_code == 201
        assert response.get_json()["user"]["email"] == "owner@example.test"
        assert response.get_json()["verification_email_status"] == "accepted"
        assert "DEMO_ACTION_UNAVAILABLE" not in response.get_data(as_text=True)
    finally:
        with app.app_context():
            db.session.remove()


def test_demo_account_access_opt_in_allows_auth_but_not_chat_or_money(monkeypatch):
    """The new profile is narrow: registration opens, provider/settlement does not."""
    app = create_app(
        "testing",
        config_overrides={
            "DEMO_RELEASE_ENABLED": True,
            "PUBLIC_ACCOUNT_ACCESS_ENABLED": True,
            "EXPANDED_HIERARCHY_ENABLED": True,
        },
    )
    try:
        user = SimpleNamespace(to_dict=lambda: {"email": "opt-in@example.test"})
        token = SimpleNamespace(user=user, code="482913")
        monkeypatch.setattr(
            auth_routes.EmailService, "is_configured", lambda: True, raising=False
        )
        monkeypatch.setattr(
            auth_routes.AuthService, "register_user", lambda **_kwargs: (user, token)
        )
        monkeypatch.setattr(
            auth_routes.EmailService, "send_verification_email", lambda *_args: True
        )

        registration = app.test_client().post(
            "/api/v1/auth/register",
            json={
                "email": "opt-in@example.test",
                "password": "ValidPassword1!",
                "first_name": "Opt",
                "last_name": "In",
            },
        )
        chat = app.test_client().post("/api/v1/chat/faq", json={"question": "test"})

        assert registration.status_code == 201
        assert registration.get_json()["verification_email_status"] == "accepted"
        assert chat.status_code == 503
        assert chat.get_json() == CHAT_ACTION_UNAVAILABLE
        # Account access has no coupling to any monetary/provider opt-in.
        assert app.config["NOWPAYMENTS_PILOT_ENABLED"] is False
        assert app.config["STRIPE_SECRET_KEY"] is None
        assert app.config["MT_SERVER"] is None
    finally:
        with app.app_context():
            db.session.remove()
