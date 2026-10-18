"""Isolated MarketEdgePros regressions for the active-brand boundary."""
from configparser import ConfigParser
from pathlib import Path
from types import SimpleNamespace


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ACTIVE_BRAND_PATHS = (
    "backend/src/utils/vault_client.py",
    "backend/src/utils/swagger_config.py",
    "backend/src/utils/sentry_integration.py",
    "backend/src/utils/logging_config.py",
    "backend/src/utils/db_optimization.py",
    "backend/src/utils/compression_config.py",
    "backend/src/utils/caching_config.py",
    "backend/src/utils/cache_config.py",
    "backend/src/middleware/security_headers_middleware.py",
    "backend/src/middleware/performance_middleware.py",
    "backend/src/services/notification_service.py",
    "backend/src/services/notification_service.py.backup_20251202_193018",
    "backend/src/config.py",
    "backend/alembic.ini",
    "frontend/nginx.conf",
    "backend/tests/integration/routes/test_mt5_routes.py",
)
LEGACY_MARKERS = (
    "prop" + "trade" + "pro",
    "prop" + "_" + "trade",
    "prop" + "trade",
)


def read_repository_file(relative_path):
    """Read a tracked MarketEdgePros source file as UTF-8 text."""
    return (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")


def test_active_brand_sources_have_no_legacy_identity_markers():
    """Active MarketEdgePros configuration cannot retain the retired identity."""
    for relative_path in ACTIVE_BRAND_PATHS:
        content = read_repository_file(relative_path).lower()
        assert all(marker not in content for marker in LEGACY_MARKERS), relative_path


def test_vault_uses_the_configurable_marketedgepros_mount_without_a_network_call():
    """Vault defaults to the new MarketEdgePros mount while retaining explicit configuration."""
    content = read_repository_file("backend/src/utils/vault_client.py")
    assert "os.getenv('VAULT_MOUNT', 'marketedgepros')" in content
    assert "mount_point=self.vault_mount" in content
    assert "self.get_secret('flask')" in content
    assert "self.get_secret('database')" in content


def test_swagger_exposes_only_the_canonical_marketedgepros_origin():
    """Swagger metadata uses the canonical MarketEdgePros project and API origin."""
    content = read_repository_file("backend/src/utils/swagger_config.py")
    assert '"title": "MarketEdgePros API"' in content
    assert '"url": "https://marketedgepros.com"' in content
    assert '"host": "marketedgepros.com"' in content
    assert '"email":' not in content


def test_nginx_uses_the_documented_backend_service_not_a_legacy_proxy():
    """The historical Nginx configuration proxies API requests to the backend service."""
    content = read_repository_file("frontend/nginx.conf")
    assert "proxy_pass http://backend:5000/api/;" in content


def test_alembic_has_no_hardcoded_database_target():
    """Alembic waits for runtime configuration instead of selecting a database implicitly."""
    parser = ConfigParser()
    parser.read_string(read_repository_file("backend/alembic.ini"))
    assert parser.get("alembic", "sqlalchemy.url") == ""


def test_missing_admin_email_skips_email_provider_invocation():
    """Admin alerts require an explicit MarketEdgePros administrator address."""
    from src.services.notification_service import NotificationService

    class FailingMail:
        called = False

        def send(self, message):
            self.called = True
            raise AssertionError("mail provider must not be invoked without ADMIN_EMAIL")

    service = NotificationService()
    service.app = SimpleNamespace(config={})
    service.mail = FailingMail()

    assert service.send_admin_alert(SimpleNamespace(), []) is False
    assert service.mail.called is False
