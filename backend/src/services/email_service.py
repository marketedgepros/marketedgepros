"""Fail-closed Brevo delivery for reviewed account-access email only.

The service intentionally does not send the repository's older financial,
marketing, course, or notification messages.  They require separate reviewed
scope before they can use a transactional sender.
"""
import html
import logging
import re
from urllib.parse import urlencode, urlparse

import requests
from flask import current_app

from src.production_safety import is_valid_brevo_api_key


logger = logging.getLogger(__name__)


class EmailService:
    """Send only verification, password-reset, and welcome account messages."""

    BREVO_SEND_ENDPOINT = "https://api.brevo.com/v3/smtp/email"
    CONNECT_TIMEOUT_SECONDS = 3.05
    READ_TIMEOUT_SECONDS = 10
    MAX_API_KEY_LENGTH = 512
    MAX_EMAIL_LENGTH = 254
    MAX_SUBJECT_LENGTH = 255
    MAX_HTML_LENGTH = 100_000
    MAX_TEXT_LENGTH = 20_000
    MAX_MESSAGE_ID_LENGTH = 512
    MAX_FRONTEND_URL_LENGTH = 2048
    _ACCOUNT_EMAIL_KINDS = frozenset({
        "verification",
        "password_reset",
        "welcome",
    })
    _EMAIL_PATTERN = re.compile(
        r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
        r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
        r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+\Z"
    )
    _KNOWN_WEAK_KEYS = frozenset({
        "change-me",
        "secret",
        "default",
        "placeholder",
        "your-brevo-api-key",
    })

    @staticmethod
    def _configuration():
        """Read the reviewed account-mail settings without falling back to env."""
        try:
            return current_app.config
        except RuntimeError:
            return None

    @classmethod
    def _is_valid_email(cls, value):
        """Accept exactly one bounded ASCII mailbox, never a display address."""
        return (
            isinstance(value, str)
            and 3 <= len(value) <= cls.MAX_EMAIL_LENGTH
            and value.isascii()
            and "\r" not in value
            and "\n" not in value
            and bool(cls._EMAIL_PATTERN.fullmatch(value))
            and len(value.rsplit("@", 1)[0]) <= 64
        )

    @classmethod
    def _is_valid_sender(cls, value):
        return (
            cls._is_valid_email(value)
            and value.rsplit("@", 1)[1] == "marketedgepros.com"
        )

    @classmethod
    def _is_valid_api_key(cls, value):
        """Use the same pure credential contract as release validation."""
        return is_valid_brevo_api_key(value)

    @classmethod
    def _is_canonical_frontend_url(cls, value):
        """Allow only the reviewed public brand origin, with no supplied path."""
        if (
            not isinstance(value, str)
            or not value
            or len(value) > cls.MAX_FRONTEND_URL_LENGTH
            or "\r" in value
            or "\n" in value
        ):
            return False
        try:
            parsed = urlparse(value)
            port = parsed.port
        except (TypeError, ValueError):
            return False
        return (
            parsed.scheme == "https"
            and parsed.hostname in {"marketedgepros.com", "www.marketedgepros.com"}
            and port is None
            and parsed.path in {"", "/"}
            and not parsed.params
            and not parsed.query
            and not parsed.fragment
            and parsed.username is None
            and parsed.password is None
        )

    @staticmethod
    def _is_bounded_text(value, maximum):
        return (
            isinstance(value, str)
            and bool(value.strip())
            and len(value) <= maximum
            and "\x00" not in value
            and "\r" not in value
        )

    @classmethod
    def is_configured(cls):
        """Return whether the complete reviewed Brevo sender configuration exists."""
        config = cls._configuration()
        if config is None:
            return False
        return (
            config.get("EMAIL_PROVIDER") == "brevo"
            and cls._is_valid_api_key(config.get("BREVO_API_KEY"))
            and cls._is_valid_sender(config.get("EMAIL_FROM_ADDRESS"))
            and config.get("EMAIL_FROM_NAME") == "MarketEdgePros"
            and config.get("EMAIL_SENDER_VERIFIED") is True
            and config.get("EMAIL_DOMAIN_AUTHENTICATED") is True
            and cls._is_canonical_frontend_url(config.get("FRONTEND_URL"))
        )

    @classmethod
    def _frontend_url(cls):
        config = cls._configuration()
        if config is None:
            return None
        value = config.get("FRONTEND_URL")
        if not cls._is_canonical_frontend_url(value):
            return None
        return value.rstrip("/")

    @staticmethod
    def _code(value):
        return (
            value
            if isinstance(value, str)
            and value.isascii()
            and len(value) == 6
            and value.isdigit()
            else None
        )

    @staticmethod
    def _legacy_verification_token(value):
        """Validate the URL-safe token produced by EmailVerificationToken."""
        return (
            value
            if isinstance(value, str)
            and 32 <= len(value) <= 128
            and value.isascii()
            and re.fullmatch(r"[A-Za-z0-9_-]+", value)
            else None
        )

    @staticmethod
    def _display_name(user):
        """Keep personalized copy bounded and safe for both HTML and plain text."""
        try:
            value = getattr(user, "first_name", None)
        except Exception:
            return "there"
        if not isinstance(value, str):
            return "there"
        value = " ".join(value.split())[:100]
        return value or "there"

    @classmethod
    def _recipient(cls, user):
        try:
            value = getattr(user, "email", None)
        except Exception:
            return None
        return value if cls._is_valid_email(value) else None

    @classmethod
    def _send_email(
        cls,
        to_email,
        subject,
        html_content,
        from_email=None,
        text_content=None,
        email_kind=None,
    ):
        """Make one non-retrying Brevo request for an approved account message."""
        if (
            email_kind not in cls._ACCOUNT_EMAIL_KINDS
            or not cls.is_configured()
            or not cls._is_valid_email(to_email)
            or not cls._is_bounded_text(subject, cls.MAX_SUBJECT_LENGTH)
            or not cls._is_bounded_text(html_content, cls.MAX_HTML_LENGTH)
            or not cls._is_bounded_text(text_content, cls.MAX_TEXT_LENGTH)
        ):
            return False

        config = cls._configuration()
        sender_email = config.get("EMAIL_FROM_ADDRESS")
        if from_email is not None and from_email != sender_email:
            return False

        payload = {
            "sender": {"email": sender_email, "name": "MarketEdgePros"},
            "to": [{"email": to_email}],
            "subject": subject,
            "htmlContent": html_content,
            "textContent": text_content,
        }
        session = None
        try:
            session = requests.Session()
            # Requests otherwise inherits HTTP(S)_PROXY and similar environment
            # settings. Account mail must connect only to the fixed HTTPS host.
            session.trust_env = False
            logger.info("Account email delivery attempt")
            response = session.post(
                cls.BREVO_SEND_ENDPOINT,
                headers={
                    "api-key": config.get("BREVO_API_KEY"),
                    "accept": "application/json",
                    "content-type": "application/json",
                },
                json=payload,
                timeout=(cls.CONNECT_TIMEOUT_SECONDS, cls.READ_TIMEOUT_SECONDS),
                allow_redirects=False,
            )
        except Exception:
            # Do not log exception text: providers can include request details.
            return False
        finally:
            # A close error cannot alter the accepted/failed outcome and must not
            # be logged with provider details.
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass

        status = getattr(response, "status_code", None)
        if not isinstance(status, int):
            return False
        logger.info("Account email delivery status=%s", status)
        if status != 201:
            return False
        try:
            response_data = response.json()
        except Exception:
            return False
        message_id = response_data.get("messageId") if isinstance(response_data, dict) else None
        return (
            isinstance(message_id, str)
            and bool(message_id)
            and len(message_id) <= cls.MAX_MESSAGE_ID_LENGTH
            and message_id == message_id.strip()
            and message_id.isascii()
            and message_id.isprintable()
        )

    @classmethod
    def send_verification_email(cls, user, code_or_token):
        """Send the code-first verification message, or the real legacy API URL."""
        recipient = cls._recipient(user)
        code = cls._code(code_or_token)
        name = cls._display_name(user)
        if recipient is None:
            return False

        if code is not None:
            frontend_url = cls._frontend_url()
            if frontend_url is None:
                return False
            instructions_url = frontend_url + "/verify-email?" + urlencode({"email": recipient})
            if len(instructions_url) > cls.MAX_FRONTEND_URL_LENGTH:
                return False
            safe_name = html.escape(name, quote=True)
            safe_code = html.escape(code, quote=True)
            safe_url = html.escape(instructions_url, quote=True)
            html_content = f"""<!doctype html>
<html><body style="margin:0;background:#f0fdfa;color:#17324d;font-family:Arial,sans-serif;font-size:16px;line-height:1.55;">
  <div style="max-width:600px;margin:0 auto;padding:24px;">
    <div style="background:linear-gradient(135deg,#0891b2,#0f766e);color:#fff;padding:24px;border-radius:12px 12px 0 0;"><h1 style="margin:0;font-size:24px;">MarketEdgePros</h1></div>
    <div style="background:#fff;padding:28px;border-radius:0 0 12px 12px;"><p>Hi {safe_name},</p><p>Enter this 6-digit code to verify your email address:</p>
      <p style="margin:24px 0;padding:18px;border:2px solid #0891b2;border-radius:8px;color:#0f766e;font-family:monospace;font-size:30px;font-weight:bold;letter-spacing:6px;text-align:center;">{safe_code}</p>
      <p>This code expires in 24 hours. Open this verification page and enter the code:</p><p style="font-size:14px;overflow-wrap:anywhere;">{safe_url}</p><p>If you did not create this account, you can ignore this email.</p></div>
  </div>
</body></html>"""
            text_content = (
                f"MarketEdgePros\n\nHi {name},\n\nVerify your email with code: {code}\n"
                f"This code expires in 24 hours.\nVerification page: {instructions_url}\n\n"
                "If you did not create this account, you can ignore this email."
            )
            return cls._send_email(
                recipient,
                "Verify your email | MarketEdgePros",
                html_content,
                text_content=text_content,
                email_kind="verification",
            )

        token = cls._legacy_verification_token(code_or_token)
        frontend_url = cls._frontend_url()
        if token is None or frontend_url is None:
            return False
        # The only legacy verification URL is an existing GET API route, not a
        # guessed frontend route. It intentionally makes no client-UX promise.
        verification_url = frontend_url + "/api/v1/auth/verify-email/" + token
        if len(verification_url) > cls.MAX_FRONTEND_URL_LENGTH:
            return False
        safe_name = html.escape(name, quote=True)
        safe_url = html.escape(verification_url, quote=True)
        html_content = f"""<!doctype html>
<html><body style="margin:0;background:#f0fdfa;color:#17324d;font-family:Arial,sans-serif;font-size:16px;line-height:1.55;">
  <div style="max-width:600px;margin:0 auto;padding:24px;"><div style="background:linear-gradient(135deg,#0891b2,#0f766e);color:#fff;padding:24px;border-radius:12px 12px 0 0;"><h1 style="margin:0;font-size:24px;">MarketEdgePros</h1></div>
  <div style="background:#fff;padding:28px;border-radius:0 0 12px 12px;"><p>Hi {safe_name},</p><p>Open this verification address to complete the legacy email-verification request. This link expires in 24 hours.</p><p style="font-size:14px;overflow-wrap:anywhere;">{safe_url}</p><p>If you did not create this account, you can ignore this email.</p></div></div>
</body></html>"""
        text_content = (
            f"MarketEdgePros\n\nHi {name},\n\nLegacy verification address: {verification_url}\n"
            "This link expires in 24 hours. If you did not create this account, you can ignore this email."
        )
        return cls._send_email(
            recipient,
            "Verify your email | MarketEdgePros",
            html_content,
            text_content=text_content,
            email_kind="verification",
        )

    @classmethod
    def send_password_reset_email(cls, user, code_or_token):
        """Send the implemented six-digit password-reset-code flow only."""
        recipient = cls._recipient(user)
        code = cls._code(code_or_token)
        if recipient is None or code is None:
            # The legacy token reset endpoint is JSON-only; never advertise a
            # guessed or nonexistent frontend token URL.
            return False
        name = cls._display_name(user)
        safe_name = html.escape(name, quote=True)
        safe_code = html.escape(code, quote=True)
        html_content = f"""<!doctype html>
<html><body style="margin:0;background:#f0fdfa;color:#17324d;font-family:Arial,sans-serif;font-size:16px;line-height:1.55;">
  <div style="max-width:600px;margin:0 auto;padding:24px;"><div style="background:linear-gradient(135deg,#0891b2,#0f766e);color:#fff;padding:24px;border-radius:12px 12px 0 0;"><h1 style="margin:0;font-size:24px;">MarketEdgePros</h1></div>
  <div style="background:#fff;padding:28px;border-radius:0 0 12px 12px;"><p>Hi {safe_name},</p><p>We received a request to reset your password. Enter this 6-digit code on the password-reset page:</p>
  <p style="margin:24px 0;padding:18px;border:2px solid #0891b2;border-radius:8px;color:#0f766e;font-family:monospace;font-size:30px;font-weight:bold;letter-spacing:6px;text-align:center;">{safe_code}</p><p>This code expires in 15 minutes.</p><p>If you did not request a password reset, you can ignore this email.</p></div></div>
</body></html>"""
        text_content = (
            f"MarketEdgePros\n\nHi {name},\n\nPassword reset code: {code}\n"
            "This code expires in 15 minutes. If you did not request a password reset, you can ignore this email."
        )
        return cls._send_email(
            recipient,
            "Reset your password | MarketEdgePros",
            html_content,
            text_content=text_content,
            email_kind="password_reset",
        )

    @classmethod
    def send_welcome_email(cls, user):
        """Send a factual welcome after a completed verification transaction."""
        recipient = cls._recipient(user)
        if recipient is None:
            return False
        name = cls._display_name(user)
        safe_name = html.escape(name, quote=True)
        html_content = f"""<!doctype html>
<html><body style="margin:0;background:#f0fdfa;color:#17324d;font-family:Arial,sans-serif;font-size:16px;line-height:1.55;">
  <div style="max-width:600px;margin:0 auto;padding:24px;"><div style="background:linear-gradient(135deg,#0891b2,#0f766e);color:#fff;padding:24px;border-radius:12px 12px 0 0;"><h1 style="margin:0;font-size:24px;">Welcome to MarketEdgePros</h1></div>
  <div style="background:#fff;padding:28px;border-radius:0 0 12px 12px;"><p>Hi {safe_name},</p><p>Your email address has been verified.</p><p>You can sign in to MarketEdgePros when you are ready.</p><p>Thank you,<br>MarketEdgePros</p></div></div>
</body></html>"""
        text_content = (
            f"Welcome to MarketEdgePros\n\nHi {name},\n\nYour email address has been verified. "
            "You can sign in to MarketEdgePros when you are ready.\n\nThank you,\nMarketEdgePros"
        )
        return cls._send_email(
            recipient,
            "Welcome to MarketEdgePros",
            html_content,
            text_content=text_content,
            email_kind="welcome",
        )

    # Legacy mail is deliberately unsupported. These methods remain as harmless
    # compatibility stubs for existing callers while their scopes are reviewed.
    @staticmethod
    def _get_client():
        return False

    @staticmethod
    def send_challenge_purchased_email(user, challenge, program):
        return False

    @staticmethod
    def send_commission_earned_email(user, commission_amount, source_user):
        return False

    @staticmethod
    def send_withdrawal_approved_email(user, withdrawal_amount):
        return False

    @staticmethod
    def send_withdrawal_rejected_email(user, withdrawal_amount, reason):
        return False

    @staticmethod
    def send_kyc_approved_email(user):
        return False

    @staticmethod
    def send_kyc_rejected_email(user, reason):
        return False

    @staticmethod
    def send_new_downline_email(user, new_downline):
        return False

    @staticmethod
    def send_notification_email(notification):
        return False

    @staticmethod
    def _generate_notification_html(notification, user):
        return False

    @staticmethod
    def queue_email(user_id, to_email, subject, html_body):
        return False

    @staticmethod
    def process_email_queue(batch_size=10):
        return False

    @staticmethod
    def send_email(*args, **kwargs):
        return False

    @staticmethod
    def send_payment_approval_notification(*args, **kwargs):
        return False

    @staticmethod
    def send_payment_approved_notification(*args, **kwargs):
        return False

    @staticmethod
    def send_challenge_activated_notification(*args, **kwargs):
        return False

    @staticmethod
    def send_payment_rejected_notification(*args, **kwargs):
        return False


def send_course_welcome_email(to_email, name):
    """Course marketing delivery is outside the reviewed account-email scope."""
    return False
