"""UI-4 trading/scaling routes against runner-owned PostgreSQL and Redis only."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest


@pytest.fixture
def ui4_staging_app(staging_resources, monkeypatch):
    """A module-local real Flask host so the shared staging fixture remains unchanged."""
    import src.database as database_module
    from flask import Flask
    import redis

    from src.database import db
    from src.models.account_scaling import AccountScaling
    from src.models.trade import Trade
    from src.routes.scaling import scaling_bp
    from src.routes.traders import traders_bp
    from src.utils.hierarchy_scoping import init_hierarchy_scoping
    from src.models.user import User

    app = Flask("ui4-trading-scaling-staging")
    app.config.update(
        TESTING=True,
        EXPANDED_HIERARCHY_ENABLED=True,
        PLATFORM_ROOT_USER_ID=1,
        JWT_SECRET_KEY="staging-runner-public-synthetic-jwt",
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=10),
        JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=1),
        SQLALCHEMY_DATABASE_URI=staging_resources["pg_url"],
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )
    db.init_app(app)
    app.register_blueprint(traders_bp, url_prefix="/api/v1/traders")
    app.register_blueprint(scaling_bp)
    # Other isolated app fixtures may reset this optional module-global client.
    # Own a private bounded Unix-socket client for this test, then restore it.
    client = redis.Redis(unix_socket_path=str(staging_resources["redis_socket"]),
                         decode_responses=True, socket_timeout=2, socket_connect_timeout=2)
    assert client.ping() is True
    monkeypatch.setattr(database_module, "redis_client", client)
    # The legacy model declares this index twice.  Keep one physical index for
    # this isolated create_all harness; model and migration sources are untouched.
    seen = set()
    for index in tuple(AccountScaling.__table__.indexes):
        if index.name in seen:
            AccountScaling.__table__.indexes.remove(index)
        else:
            seen.add(index.name)
    with app.app_context():
        init_hierarchy_scoping(db, User)
        db.metadata.create_all(bind=db.engine, tables=(Trade.__table__, AccountScaling.__table__))
    yield app
    with app.app_context():
        db.session.remove()
        db.metadata.drop_all(
            bind=db.engine, tables=(AccountScaling.__table__, Trade.__table__)
        )
    assert database_module.redis_client is client
    client.close()


def _seed(app):
    from src.database import db
    from src.models.account_scaling import AccountScaling
    from src.models.tenant import Tenant
    from src.models.trade import Trade
    from src.models.trading_program import Challenge, TradingProgram
    from src.models.user import User

    now = datetime.utcnow().replace(microsecond=0)
    with app.app_context():
        db.session.add_all([
            Tenant(id=1, name="Stage tenant A", subdomain="ui4-stage-a"),
            Tenant(id=2, name="Stage tenant B", subdomain="ui4-stage-b"),
            User(id=1, email="ui4-root@stage.test", password_hash="x", first_name="Root", last_name="A",
                 tenant_id=1, role="supermaster", parent_id=None, tree_path="1", level=0,
                 is_active=True, is_verified=True, can_create_same_role=True),
            User(id=2, email="ui4-master@stage.test", password_hash="x", first_name="Master", last_name="A",
                 tenant_id=1, role="master", parent_id=1, tree_path="1/2", level=1,
                 is_active=True, is_verified=True),
            User(id=3, email="ui4-trader@stage.test", password_hash="x", first_name="Trader", last_name="A",
                 tenant_id=1, role="trader", parent_id=2, tree_path="1/2/3", level=2,
                 is_active=True, is_verified=True),
            User(id=4, email="ui4-other@stage.test", password_hash="x", first_name="Other", last_name="A",
                 tenant_id=1, role="trader", parent_id=1, tree_path="1/4", level=1,
                 is_active=True, is_verified=True),
            User(id=5, email="ui4-affiliate@stage.test", password_hash="x", first_name="Affiliate", last_name="A",
                 tenant_id=1, role="affiliate", parent_id=1, tree_path="1/5", level=1,
                 is_active=True, is_verified=True),
            TradingProgram(id=10, tenant_id=1, name="Stage A", type="one_phase",
                           account_size=Decimal("10000.00"), price=Decimal("1.00"), rules={}),
            TradingProgram(id=11, tenant_id=2, name="Stage B", type="one_phase",
                           account_size=Decimal("10000.00"), price=Decimal("1.00"), rules={}),
        ])
        db.session.flush()
        db.session.add_all([
            Challenge(id=100, user_id=3, program_id=10, status="active",
                      initial_balance=Decimal("10000.00"), current_balance=Decimal("10000.00")),
            Challenge(id=101, user_id=4, program_id=10, status="active",
                      initial_balance=Decimal("10000.00"), current_balance=Decimal("10000.00")),
            Challenge(id=102, user_id=3, program_id=11, status="active",
                      initial_balance=Decimal("10000.00"), current_balance=Decimal("10000.00")),
        ])
        db.session.flush()
        db.session.add_all([
            Trade(id=1000, ticket="STAGE-OWN", challenge_id=100, symbol="EURUSD", trade_type="buy",
                  volume=Decimal("0.00"), open_price=Decimal("0.00000"), close_price=Decimal("1.25000"),
                  profit=Decimal("0.00"), commission=Decimal("0.00"), swap=Decimal("0.00"), status="closed",
                  open_time=now - timedelta(days=1), close_time=now),
            Trade(id=1001, ticket="STAGE-FOREIGN", challenge_id=101, symbol="EURUSD", trade_type="buy",
                  volume=Decimal("1.00"), open_price=Decimal("1.00000"), close_price=Decimal("2.00000"),
                  profit=Decimal("99.00"), commission=Decimal("0.00"), swap=Decimal("0.00"), status="closed",
                  open_time=now, close_time=now),
            Trade(id=1002, ticket="STAGE-CROSS", challenge_id=102, symbol="EURUSD", trade_type="buy",
                  volume=Decimal("1.00"), open_price=Decimal("1.00000"), close_price=Decimal("2.00000"),
                  profit=Decimal("88.00"), commission=Decimal("0.00"), swap=Decimal("0.00"), status="closed",
                  open_time=now, close_time=now),
            AccountScaling(id=200, user_id=3, current_tier=1,
                           current_account_size=Decimal("10000.00"), next_tier=2,
                           next_account_size=Decimal("25000.00"), total_profit=Decimal("0.00"),
                           target_profit=Decimal("800.00"), progress_percentage=Decimal("0.00"),
                           times_scaled=0, is_eligible_for_scaling=True, status="active"),
            AccountScaling(id=201, user_id=4, current_tier=1,
                           current_account_size=Decimal("10000.00"), next_tier=2,
                           next_account_size=Decimal("25000.00"), total_profit=Decimal("12.00"),
                           target_profit=Decimal("800.00"), progress_percentage=Decimal("1.50"),
                           times_scaled=0, is_eligible_for_scaling=True, status="active"),
        ])
        db.session.commit()
        return {identity: db.session.get(User, identity).generate_access_token() for identity in range(1, 6)}


def _auth(tokens, actor):
    return {"Authorization": "Bearer " + tokens[actor]}


def test_ui4_trading_scaling_real_postgresql_redis_routes_are_scoped_and_read_only(ui4_staging_app):
    """Exercise actual JWT/Redis checks, PostgreSQL NUMERIC and HTTP endpoints."""
    from src.database import db
    from src.models.account_scaling import AccountScaling

    tokens = _seed(ui4_staging_app)
    client = ui4_staging_app.test_client()

    history = client.get("/api/v1/traders/history?symbol=eurusd", headers=_auth(tokens, 3))
    assert history.status_code == 200
    body = history.get_json()
    assert [row["id"] for row in body["trades"]] == [1000]
    assert body["statistics"] == {
        "total_trades": 1,
        "winning_trades": 0,
        "losing_trades": 0,
        "total_profit": "0.00",
    }
    assert body["trades"][0]["volume"] == "0.00"
    assert body["currency"] is None and body["provider_authenticated"] is False

    mine = client.get("/api/v1/scaling/my-progress", headers=_auth(tokens, 3))
    assert mine.status_code == 200
    assert mine.get_json()["data"]["is_eligible_for_scaling"] is False
    assert mine.get_json()["data"]["total_profit"] == "0.00"
    scoped = client.get("/api/v1/scaling/admin/all-users", headers=_auth(tokens, 2))
    assert scoped.status_code == 200
    assert [row["user_id"] for row in scoped.get_json()["data"]] == [3]
    assert client.get("/api/v1/scaling/admin/all-users", headers=_auth(tokens, 5)).status_code == 403

    blocked = client.post("/api/v1/scaling/admin/user/3/update-profit", json={"profit_amount": "999"}, headers=_auth(tokens, 2))
    assert blocked.status_code == 503
    assert blocked.get_json()["code"] == "SCALING_EVIDENCE_NOT_CONFIGURED"
    with ui4_staging_app.app_context():
        persisted = db.session.get(AccountScaling, 200)
        assert persisted.total_profit == Decimal("0.00")
        assert persisted.is_eligible_for_scaling is True
