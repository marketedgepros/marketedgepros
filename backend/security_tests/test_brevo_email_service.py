"""Isolated Brevo account-email boundary tests; no provider request is allowed."""
from types import SimpleNamespace

import pytest
from flask import Flask

from src.services import email_service
from src.services.email_service import EmailService, send_course_welcome_email


_API_KEY = "xkeysib-9K8m7N6p5Q4r3S2t1V0wXyZaBcDeFgHiJkLmNoPq"


@pytest.fixture
def app():
    flask_app = Flask("brevo-email-service")
    flask_app.config.update(
        TESTING=True,
        EMAIL_PROVIDER="brevo",
        BREVO_API_KEY=_API_KEY,
        EMAIL_FROM_ADDRESS="info@marketedgepros.com",
        EMAIL_FROM_NAME="MarketEdgePros",
        EMAIL_SENDER_VERIFIED=True,
        EMAIL_DOMAIN_AUTHENTICATED=True,
        FRONTEND_URL="https://marketedgepros.com",
    )
    return flask_app


@pytest.fixture
def user():
    return SimpleNamespace(email="member@example.test", first_name="Maya")


class _Response:
    def __init__(self, status_code=201, body=None, error=None):
        self.status_code = status_code
        self._body = {"messageId": "brevo-message-123"} if body is None else body
        self._error = error

    def json(self):
        if self._error is not None:
            raise self._error
        return self._body


class _Session:
    def __init__(self, response=None, error=None):
        self.response = response or _Response()
        self.error = error
        self.calls = []
        self.closed = False
        self.trust_env = True

    def post(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self.error is not None:
            raise self.error
        return self.response

    def close(self):
        self.closed = True


def _install_session(monkeypatch, session):
    monkeypatch.setattr(email_service.requests, "Session", lambda: session)


def test_is_configured_requires_every_reviewed_value(app):
    with app.app_context():
        assert EmailService.is_configured() is True
        invalid_values = [
            ("EMAIL_PROVIDER", "sendgrid"),
            ("BREVO_API_KEY", "a" * 31),
            ("BREVO_API_KEY", "placeholder-key-with-more-than-thirty-two-chars"),
            ("BREVO_API_KEY", _API_KEY + "\n"),
            ("EMAIL_FROM_ADDRESS", "info@evil.example"),
            ("EMAIL_FROM_ADDRESS", "info@marketedgepros.com,other@example.test"),
            ("EMAIL_FROM_NAME", "Market Edge Pros"),
            ("EMAIL_SENDER_VERIFIED", "true"),
            ("EMAIL_DOMAIN_AUTHENTICATED", 1),
            ("FRONTEND_URL", "http://marketedgepros.com"),
            ("FRONTEND_URL", "https://marketedgepros.com/reset"),
            ("FRONTEND_URL", "https://marketedgepros.com/" + "x" * 2048),
        ]
        for key, value in invalid_values:
            original = app.config[key]
            app.config[key] = value
            assert EmailService.is_configured() is False, key
            app.config[key] = original


def test_verification_payload_is_fixed_bounded_and_code_first(app, user, monkeypatch):
    session = _Session()
    _install_session(monkeypatch, session)
    user.first_name = '<script>alert("name")</script>'

    with app.app_context():
        assert EmailService.send_verification_email(user, "482913") is True

    assert session.trust_env is False
    assert session.closed is True
    assert len(session.calls) == 1
    args, kwargs = session.calls[0]
    assert args == ("https://api.brevo.com/v3/smtp/email",)
    assert kwargs["timeout"] == (3.05, 10)
    assert kwargs["allow_redirects"] is False
    assert kwargs["headers"]["api-key"] == _API_KEY
    assert "tracking" not in {name.lower() for name in kwargs["headers"]}
    payload = kwargs["json"]
    assert payload["sender"] == {
        "email": "info@marketedgepros.com",
        "name": "MarketEdgePros",
    }
    assert payload["to"] == [{"email": "member@example.test"}]
    assert payload["subject"] == "Verify your email | MarketEdgePros"
    assert set(payload) == {"sender", "to", "subject", "htmlContent", "textContent"}
    assert "&lt;script&gt;alert(&quot;name&quot;)&lt;/script&gt;" in payload["htmlContent"]
    assert '<script>alert("name")</script>' not in payload["htmlContent"]
    assert "482913" in payload["htmlContent"]
    assert "https://marketedgepros.com/verify-email?email=member%40example.test" in payload["htmlContent"]
    assert "<a " not in payload["htmlContent"].lower()
    assert "<img" not in payload["htmlContent"].lower()
    assert "482913" in payload["textContent"]


@pytest.mark.parametrize(
    "response",
    [
        _Response(status_code=202),
        _Response(status_code=400),
        _Response(status_code=302),
        _Response(body={}),
        _Response(body={"messageId": ""}),
        _Response(body={"messageId": "   "}),
        _Response(body={"messageId": "m" * 513}),
        _Response(error=ValueError("malformed provider body")),
    ],
)
def test_only_201_with_bounded_nonempty_message_id_is_accepted(
    app, user, monkeypatch, response
):
    session = _Session(response=response)
    _install_session(monkeypatch, session)
    with app.app_context():
        assert EmailService.send_password_reset_email(user, "482913") is False
    assert len(session.calls) == 1


def test_timeout_returns_false_without_retry(app, user, monkeypatch):
    session = _Session(error=email_service.requests.Timeout("synthetic timeout"))
    _install_session(monkeypatch, session)
    with app.app_context():
        assert EmailService.send_password_reset_email(user, "482913") is False
    assert len(session.calls) == 1


def test_timeout_and_secret_bearing_exception_return_false_without_sensitive_logs(
    app, user, monkeypatch, caplog
):
    sensitive_code = "482913"
    error = RuntimeError(f"provider body key={_API_KEY} to={user.email} code={sensitive_code}")
    session = _Session(error=error)
    _install_session(monkeypatch, session)

    with app.app_context(), caplog.at_level("INFO"):
        assert EmailService.send_password_reset_email(user, sensitive_code) is False

    log_text = caplog.text
    assert _API_KEY not in log_text
    assert user.email not in log_text
    assert sensitive_code not in log_text
    assert "provider body" not in log_text
    assert len(session.calls) == 1


def test_invalid_code_or_legacy_reset_token_never_constructs_a_session(app, user, monkeypatch):
    def no_session():
        raise AssertionError("invalid input attempted a provider request")

    monkeypatch.setattr(email_service.requests, "Session", no_session)
    with app.app_context():
        assert EmailService.send_verification_email(user, "48<913") is False
        assert EmailService.send_verification_email(user, "short-token") is False
        assert EmailService.send_password_reset_email(user, "not-a-six-digit-code") is False
        assert EmailService.send_password_reset_email(user, "A" * 43) is False


def test_legacy_verification_uses_only_the_existing_backend_get_path(app, user, monkeypatch):
    session = _Session()
    _install_session(monkeypatch, session)
    token = "A" * 43
    with app.app_context():
        assert EmailService.send_verification_email(user, token) is True

    payload = session.calls[0][1]["json"]
    actual_path = "https://marketedgepros.com/api/v1/auth/verify-email/" + token
    assert actual_path in payload["htmlContent"]
    assert actual_path in payload["textContent"]
    assert "https://marketedgepros.com/verify-email/" + token not in payload["htmlContent"]


def test_welcome_is_account_only_and_makes_no_financial_or_activation_claims(
    app, user, monkeypatch
):
    session = _Session()
    _install_session(monkeypatch, session)
    user.first_name = "MarketEdgePros"
    with app.app_context():
        assert EmailService.send_welcome_email(user) is True

    payload = session.calls[0][1]["json"]
    assert "Hi MarketEdgePros" in payload["htmlContent"]
    combined = (payload["htmlContent"] + payload["textContent"]).lower()
    for unsupported_claim in ("active account", "mt5", "funding", "commission", "payout"):
        assert unsupported_claim not in combined


def test_legacy_nonaccount_paths_are_blocked_without_network(app, user, monkeypatch):
    def no_session():
        raise AssertionError("legacy delivery attempted a provider request")

    monkeypatch.setattr(email_service.requests, "Session", no_session)
    with app.app_context():
        assert EmailService._send_email(
            user.email, "legacy", "<p>legacy</p>", text_content="legacy"
        ) is False
        assert EmailService.send_challenge_purchased_email(user, object(), object()) is False
        assert EmailService.send_commission_earned_email(user, 1, user) is False
        assert EmailService.send_withdrawal_approved_email(user, 1) is False
        assert EmailService.send_notification_email(object()) is False
        assert EmailService.process_email_queue() is False
        assert send_course_welcome_email(user.email, "Maya") is False


@pytest.mark.parametrize("key", [
    "a" * 40,
    "synthetic-brevo-key-1234567890\tabcdef",
    "synthetic-brevo-key-1234567890\u00a0abcdef",
    "synthetic-brevo-key-1234567890\x7fabcdef",
    "example-brevo-key-1234567890abcdef",
    "your_brevo_key_1234567890abcdef",
])
def test_transport_and_shared_release_validator_reject_same_invalid_keys(key):
    from src.production_safety import is_valid_brevo_api_key

    assert EmailService._is_valid_api_key(key) is False
    assert is_valid_brevo_api_key(key) is False


def test_transport_and_shared_release_validator_accept_same_valid_key():
    from src.production_safety import is_valid_brevo_api_key

    key = "synthetic-brevo-key-1234567890-ABC"
    assert EmailService._is_valid_api_key(key) is True
    assert is_valid_brevo_api_key(key) is True
