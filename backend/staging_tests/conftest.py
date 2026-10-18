"""Fixtures for the opt-in Unix-socket PostgreSQL/Redis staging runner only."""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat
from datetime import timedelta

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy import text


DATABASE_RE = re.compile(r"marketedgepros_test_[0-9a-f]{32}\Z")
PROVIDER_SECRET_NAMES = {
    "DATABASE_URL", "REDIS_URL", "SECRET_KEY", "JWT_SECRET_KEY",
    "STRIPE_SECRET_KEY", "STRIPE_PUBLISHABLE_KEY", "STRIPE_WEBHOOK_SECRET",
    "SENDGRID_API_KEY", "MT_PASSWORD", "MT_LOGIN", "MT_SERVER",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "GOOGLE_APPLICATION_CREDENTIALS",
}


@pytest.fixture(scope="session")
def staging_resources():
    """Validate the runner-issued resources before any model import or I/O."""
    assert os.environ.get("FLASK_TESTING") == "true"
    assert os.environ.get("MARKETEDGEPROS_STAGING_INNER") == "1"
    assert int(os.environ["STAGING_RUNTIME_UID"]) == os.geteuid()
    leaked = PROVIDER_SECRET_NAMES.intersection(os.environ)
    assert not leaked, f"staging runner inherited forbidden secret/resource variables: {leaked}"

    root = Path(os.environ["STAGING_RUN_ROOT"]).resolve()
    db_name = os.environ["STAGING_DATABASE_NAME"]
    pg_socket_dir = Path(os.environ["STAGING_PG_SOCKET"]).resolve()
    redis_socket = Path(os.environ["STAGING_REDIS_SOCKET"]).resolve()
    assert DATABASE_RE.fullmatch(db_name)
    assert root.name.startswith("marketedgepros-staging-")
    assert root.parent == Path("/tmp").resolve()
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert pg_socket_dir.parent == root and pg_socket_dir.name == "pgsocket"
    assert redis_socket.parent == root and redis_socket.name == "redis.sock"
    assert stat.S_ISSOCK(redis_socket.stat().st_mode)

    pg_url = make_url(os.environ["STAGING_PG_URL"])
    assert pg_url.get_backend_name() == "postgresql"
    assert pg_url.database == db_name
    assert pg_url.host is None and pg_url.password is None
    assert pg_url.username == os.environ["STAGING_RUNTIME_USER"]
    assert dict(pg_url.query) == {"host": str(pg_socket_dir), "port": os.environ["STAGING_PG_PORT"]}
    pg_server_socket = pg_socket_dir / f".s.PGSQL.{os.environ['STAGING_PG_PORT']}"
    assert stat.S_ISSOCK(pg_server_socket.stat().st_mode)
    return {
        "root": root,
        "db_name": db_name,
        "pg_url": os.environ["STAGING_PG_URL"],
        "redis_url": os.environ["STAGING_REDIS_URL"],
        "redis_socket": redis_socket,
    }


@pytest.fixture(scope="session")
def app(staging_resources):
    """A deliberately minimal Flask host for real application route/model modules.

    ``create_app`` remains protected by testing_safety and must not be altered for
    this opt-in harness.  This fixture activates only analytics, support, and
    in-app notification blueprints plus their real decorators on runner-validated
    Unix sockets.
    """
    from flask import Flask
    import redis

    from src import cache
    from src.database import db
    import src.database as database_module
    from src.models.agent import Agent
    from src.models.commission import Commission
    from src.models.lead import Lead
    from src.models.payment import Payment
    from src.models.referral import Referral
    from src.models.notification import EmailQueue, Notification, NotificationPreference
    from src.models.support_ticket import SupportTicket, TicketMessage
    from src.models.tenant import Tenant
    from src.models.token_blacklist import TokenBlacklist
    from src.models.trading_program import Challenge, TradingProgram
    from src.models.user import EmailVerificationToken, PasswordResetToken, User
    from src.routes.analytics import analytics_bp
    from src.routes.notifications import notifications_bp
    from src.routes.support import support_bp
    from src.utils.hierarchy_scoping import init_hierarchy_scoping

    flask_app = Flask("marketedgepros-staging-integration")
    flask_app.config.update(
        TESTING=True,
        EXPANDED_HIERARCHY_ENABLED=True,
        SECRET_KEY="staging-runner-public-synthetic-secret",
        JWT_SECRET_KEY="staging-runner-public-synthetic-jwt",
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=10),
        JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=1),
        SQLALCHEMY_DATABASE_URI=staging_resources["pg_url"],
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
        CACHE_TYPE="RedisCache",
        CACHE_REDIS_URL=staging_resources["redis_url"],
        CACHE_DEFAULT_TIMEOUT=300,
        CACHE_KEY_PREFIX="staging-integration:",
        RATELIMIT_ENABLED=False,
        RATELIMIT_STORAGE_URL="memory://",
        WTF_CSRF_ENABLED=False,
    )
    db.init_app(flask_app)
    cache.init_app(flask_app)
    # AuthService calls get_redis() independently of Flask-Caching.  Give it the
    # same private Unix-domain Redis instance; no network URL is used.
    database_module.redis_client = redis.Redis(
        unix_socket_path=str(staging_resources["redis_socket"]), decode_responses=True
    )
    database_module.redis_client.ping()
    flask_app.register_blueprint(analytics_bp, url_prefix="/api/v1/analytics")
    flask_app.register_blueprint(notifications_bp, url_prefix="/api/v1/notifications")
    flask_app.register_blueprint(support_bp, url_prefix="/api/v1/support")
    tables = [
        Tenant.__table__, User.__table__, TokenBlacklist.__table__,
        EmailVerificationToken.__table__, PasswordResetToken.__table__,
        TradingProgram.__table__, Challenge.__table__, Payment.__table__,
        Agent.__table__, Referral.__table__, Commission.__table__, Lead.__table__,
        SupportTicket.__table__, TicketMessage.__table__, Notification.__table__,
        NotificationPreference.__table__, EmailQueue.__table__,
    ]
    flask_app.extensions["staging_tables"] = tables

    with flask_app.app_context():
        # Match the production factory's hierarchy request integration while only
        # creating the focused synthetic table set above.
        init_hierarchy_scoping(db, User)
        db.metadata.create_all(bind=db.engine, tables=tables)
        cache.clear()

    yield flask_app

    with flask_app.app_context():
        cache.clear()
        db.session.remove()
        db.metadata.drop_all(bind=db.engine, tables=list(reversed(tables)))
        db.engine.dispose()
    database_module.redis_client = None


@pytest.fixture(autouse=True)
def _empty_synthetic_database(app):
    """Each test receives only synthetic rows and an empty real Redis cache."""
    from src import cache
    from src.database import db

    with app.app_context():
        cache.clear()
        names = ", ".join(table.name for table in app.extensions["staging_tables"])
        db.session.execute(text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))
        db.session.commit()
    yield
    with app.app_context():
        db.session.rollback()
        cache.clear()
        db.session.remove()
