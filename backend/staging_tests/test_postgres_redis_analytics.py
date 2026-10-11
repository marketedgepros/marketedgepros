"""Focused real-protocol staging coverage; all rows are synthetic and per-test."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import text


def _user(User, user_id: int, email: str, *, tenant_id: int, role: str = "supermaster"):
    return User(
        id=user_id,
        email=email,
        password_hash="synthetic-not-a-real-password",
        first_name="Stage",
        last_name=f"User{user_id}",
        is_active=True,
        is_verified=True,
        role=role,
        tenant_id=tenant_id,
        tree_path=str(user_id),
        token_version=0,
    )


def _seed_auth_users(app):
    from src.database import db
    from src.models.tenant import Tenant
    from src.models.user import User

    with app.app_context():
        db.session.add_all([
            Tenant(id=1, name="Synthetic Tenant A", subdomain="synthetic-a"),
            Tenant(id=2, name="Synthetic Tenant B", subdomain="synthetic-b"),
            _user(User, 1, "admin-a@example.test", tenant_id=1),
            _user(User, 2, "admin-a-peer@example.test", tenant_id=1),
            _user(User, 3, "admin-b@example.test", tenant_id=2),
            _user(User, 4, "trader-a@example.test", tenant_id=1, role="trader"),
        ])
        db.session.commit()
        tokens = {
            "admin-a": db.session.get(User, 1).generate_access_token(),
            "admin-a-peer": db.session.get(User, 2).generate_access_token(),
            "admin-b": db.session.get(User, 3).generate_access_token(),
            "trader-a": db.session.get(User, 4).generate_access_token(),
        }
    return tokens


def _auth(token: str):
    return {"Authorization": f"Bearer {token}"}


def test_postgresql_18_focused_model_schema_and_unix_socket_guard(app, staging_resources):
    """Create only the relevant production model tables on a real PG18 cluster."""
    from src.database import db

    expected = {
        "tenants", "users", "token_blacklist", "email_verification_tokens",
        "password_reset_tokens", "trading_programs", "challenges", "payments",
        "agents", "referrals", "commissions", "leads",
    }
    with app.app_context():
        current_db, version_num = db.session.execute(
            text("SELECT current_database(), current_setting('server_version_num')")
        ).one()
        assert current_db == staging_resources["db_name"]
        assert int(version_num) >= 180000
        tables = {
            row[0]
            for row in db.session.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
            )
        }
        assert expected.issubset(tables)
        json_columns = dict(db.session.execute(text("""
            SELECT table_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND (table_name, column_name) IN
                (('tenants', 'settings'), ('trading_programs', 'rules'))
        """)).all())
        assert json_columns == {"tenants": "jsonb", "trading_programs": "jsonb"}


def test_actual_analytics_queries_scope_tenants_and_referral_links_on_postgresql(app):
    """Exercise the service's real PG joins/aggregates, not a mocked SELECT 1."""
    from src.database import db
    from src.models.agent import Agent
    from src.models.commission import Commission
    from src.models.lead import Lead
    from src.models.payment import Payment
    from src.models.referral import Referral
    from src.models.tenant import Tenant
    from src.models.trading_program import Challenge, TradingProgram
    from src.models.user import User
    from src.services.analytics_service import AnalyticsService

    now = datetime.utcnow()
    with app.app_context():
        tenant_a = Tenant(id=1, name="Synthetic A", subdomain="a")
        tenant_b = Tenant(id=2, name="Synthetic B", subdomain="b")
        owner_a = _user(User, 1, "owner-a@example.test", tenant_id=1)
        referred_a = _user(User, 2, "referred-a@example.test", tenant_id=1, role="trader")
        owner_b = _user(User, 3, "owner-b@example.test", tenant_id=2)
        program_a = TradingProgram(id=1, tenant_id=1, name="A Program", type="one_phase",
                                   account_size=Decimal("10000"), price=Decimal("100"), rules={})
        program_b = TradingProgram(id=2, tenant_id=2, name="B Program", type="one_phase",
                                   account_size=Decimal("10000"), price=Decimal("100"), rules={})
        valid_a = Challenge(id=1, user_id=1, program_id=1, status="active",
                            initial_balance=Decimal("10000"), current_balance=Decimal("10000"),
                            created_at=now)
        valid_b = Challenge(id=2, user_id=3, program_id=2, status="funded",
                            initial_balance=Decimal("10000"), current_balance=Decimal("10000"),
                            created_at=now)
        # Cross-tenant program link must be excluded by the actual service query.
        invalid_cross_link = Challenge(id=3, user_id=1, program_id=2, status="completed",
                                       initial_balance=Decimal("10000"), current_balance=Decimal("10000"),
                                       created_at=now)
        agent_a = Agent(id=1, user_id=1, agent_code="STAGEA")
        agent_b = Agent(id=2, user_id=3, agent_code="STAGEB")
        referral_a = Referral(id=1, agent_id=1, referred_user_id=2, referral_code="a", status="active")
        referral_b = Referral(id=2, agent_id=2, referred_user_id=3, referral_code="b", status="active")
        # A's agent pointing at tenant B must be omitted from counts and commissions.
        referral_cross = Referral(id=3, agent_id=1, referred_user_id=3, referral_code="cross", status="active")
        db.session.add_all([
            tenant_a, tenant_b, owner_a, referred_a, owner_b, program_a, program_b,
            valid_a, valid_b, invalid_cross_link, agent_a, agent_b, referral_a,
            referral_b, referral_cross,
            Payment(id=1, user_id=1, amount=Decimal("11"), status="completed",
                    payment_method="card", created_at=now),
            Payment(id=2, user_id=3, amount=Decimal("22"), status="completed",
                    payment_method="card", created_at=now),
            Commission(id=1, agent_id=1, referral_id=1, challenge_id=1,
                       sale_amount=Decimal("100"), commission_rate=Decimal("10"),
                       commission_amount=Decimal("10")),
            Commission(id=2, agent_id=1, referral_id=3, challenge_id=2,
                       sale_amount=Decimal("900"), commission_rate=Decimal("10"),
                       commission_amount=Decimal("90")),
            Commission(id=3, agent_id=1, referral_id=1, challenge_id=3,
                       sale_amount=Decimal("800"), commission_rate=Decimal("10"),
                       commission_amount=Decimal("80")),
            Lead(id=1, first_name="Synthetic", last_name="Lead", email="lead@example.test",
                 status="qualified", assigned_to=1, interested_program_id=1),
        ])
        db.session.commit()

        revenue_a = AnalyticsService.get_revenue_over_time(30, tenant_id=1, current_user=owner_a)
        revenue_b = AnalyticsService.get_revenue_over_time(30, tenant_id=2, current_user=owner_b)
        assert sum(row["revenue"] for row in revenue_a) == 11.0
        assert sum(row["revenue"] for row in revenue_b) == 22.0

        challenges_a = AnalyticsService.get_challenge_statistics(30, tenant_id=1, current_user=owner_a)
        assert challenges_a["status_distribution"] == [{"status": "active", "count": 1}]

        referrals_a = AnalyticsService.get_referral_statistics(tenant_id=1, current_user=owner_a)
        referrals_b = AnalyticsService.get_referral_statistics(tenant_id=2, current_user=owner_b)
        assert referrals_a["total_referrals"] == referrals_a["active_referrals"] == 1
        assert referrals_a["top_agents"][0]["total_commission"] == 10.0
        assert referrals_b["total_referrals"] == referrals_b["active_referrals"] == 1
        assert referrals_b["top_agents"][0]["total_commission"] == 0.0


def test_real_analytics_route_auth_and_rediscache_warm_hit_headers_ttl_and_isolation(app, monkeypatch):
    """Cache a real Flask route only after its actual JWT/admin/tenant checks."""
    import redis

    from src.services.analytics_service import AnalyticsService

    tokens = _seed_auth_users(app)
    actual = AnalyticsService.get_kyc_statistics
    calls: list[int] = []

    def counted(*args, **kwargs):
        calls.append(kwargs["tenant_id"])
        return actual(*args, **kwargs)

    monkeypatch.setattr(AnalyticsService, "get_kyc_statistics", staticmethod(counted))
    client = app.test_client()
    path = "/api/v1/analytics/kyc-statistics"

    warm = client.get(path, headers=_auth(tokens["admin-a"]))
    hit = client.get(path, headers=_auth(tokens["admin-a"]))
    assert warm.status_code == hit.status_code == 200
    assert warm.data == hit.data
    assert warm.headers["Content-Type"] == hit.headers["Content-Type"] == "application/json"
    assert calls == [1], "second response must be an actual Redis cache hit"

    # Authorization decorators remain outside the cache decorator: a warm entry
    # cannot become an unauthenticated or trader response.
    assert client.get(path).status_code == 401
    assert client.get(path, headers=_auth(tokens["trader-a"])).status_code == 403
    assert client.get(path + "?tenant_id=2", headers=_auth(tokens["admin-a"])).status_code == 400
    assert calls == [1]

    tenant_b = client.get(path, headers=_auth(tokens["admin-b"]))
    peer_a = client.get(path, headers=_auth(tokens["admin-a-peer"]))
    assert tenant_b.status_code == peer_a.status_code == 200
    assert calls == [1, 2, 1], "tenant and actor identity must partition cache keys"

    redis_client = redis.Redis.from_url(app.config["CACHE_REDIS_URL"], decode_responses=False)
    keys = list(redis_client.scan_iter(match="staging-integration:analytics:v1:*"))
    assert len(keys) == 3
    ttl_values = [redis_client.ttl(key) for key in keys]
    assert all(0 < ttl <= 300 for ttl in ttl_values), ttl_values
    # Assert the actual Redis protocol/backend honors an independent short TTL too.
    redis_client.setex("staging-integration:ttl-proof", 1, b"synthetic")
    assert redis_client.ttl("staging-integration:ttl-proof") in (1, 0)
