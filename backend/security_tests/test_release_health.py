"""Focused release-probe regressions using only synthetic dependencies."""
from types import SimpleNamespace

import pytest
from flask import Flask
from sqlalchemy import text

from src.database import db
from src.routes import health


@pytest.fixture
def health_app():
    """A minimal testing app with a synthetic in-memory SQLite database."""
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite://",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        REDIS_URL=None,
        EXPECTED_SCHEMA_REVISION=None,
        DEPLOYMENT_SHA=None,
    )
    db.init_app(app)
    app.register_blueprint(health.health_bp, url_prefix="/api/v1")

    with app.app_context():
        db.session.execute(text("SELECT 1"))

    yield app

    with app.app_context():
        db.session.remove()


def test_release_health_liveness_returns_only_valid_release_sha(health_app):
    health_app.config["DEPLOYMENT_SHA"] = "A" * 40
    response = health_app.test_client().get("/health/live")

    assert response.status_code == 200
    assert response.get_json() == {"status": "alive", "release_sha": "A" * 40}

    health_app.config["DEPLOYMENT_SHA"] = "not-a-release-sha"
    response = health_app.test_client().get("/health/live")

    assert response.status_code == 200
    assert response.get_json() == {"status": "alive"}


def test_release_health_readiness_uses_synthetic_sqlite_without_redis(health_app):
    response = health_app.test_client().get("/health/ready")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ready"}


def test_release_health_readiness_checks_configured_redis(health_app, monkeypatch):
    class RedisProbe:
        def __init__(self):
            self.calls = 0

        def ping(self):
            self.calls += 1
            return True

    probe = RedisProbe()
    health_app.config["REDIS_URL"] = "redis://configured.example/0"
    monkeypatch.setattr(health.database, "get_redis", lambda: probe)

    response = health_app.test_client().get("/health/ready")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ready"}
    assert probe.calls == 1


def test_release_health_readiness_rejects_configured_missing_redis(health_app, monkeypatch):
    health_app.config["REDIS_URL"] = "redis://configured.example/0"
    monkeypatch.setattr(health.database, "get_redis", lambda: None)

    response = health_app.test_client().get("/health/ready")

    assert response.status_code == 503
    assert response.get_json() == {
        "status": "not_ready",
        "reason": "dependency_unavailable",
    }


def test_release_health_readiness_sanitizes_database_exception(health_app, monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise RuntimeError("postgresql://user:secret@internal-db/release")

    monkeypatch.setattr(health.db.session, "execute", unavailable)

    response = health_app.test_client().get("/health/ready")

    assert response.status_code == 503
    assert response.get_json() == {
        "status": "not_ready",
        "reason": "dependency_unavailable",
    }
    assert "secret" not in response.get_data(as_text=True)


def test_release_health_readiness_checks_exact_expected_public_schema_head(
    health_app, monkeypatch
):
    statements = []

    def execute(statement, *_args, **_kwargs):
        statements.append(str(statement))
        if str(statement) == "SELECT version_num FROM public.alembic_version":
            return SimpleNamespace(scalar_one_or_none=lambda: "release-20261011")
        return SimpleNamespace()

    health_app.config["EXPECTED_SCHEMA_REVISION"] = "release-20261011"
    monkeypatch.setattr(health.db.session, "execute", execute)

    response = health_app.test_client().get("/health/ready")

    assert response.status_code == 200
    assert response.get_json() == {"status": "ready"}
    assert statements == ["SELECT 1", "SELECT version_num FROM public.alembic_version"]
