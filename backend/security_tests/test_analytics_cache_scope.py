"""Security regressions for authorization-aware, tenant-scoped analytics caching."""
from datetime import datetime

import pytest
from flask import Flask


@pytest.fixture
def analytics_app(tmp_path):
    """A real HTTP blueprint with SQLite tables only for the models under test."""
    from src import cache
    from src.database import db
    from src.models.payment import Payment
    from src.models.user import User
    from src.routes.analytics import analytics_bp

    app = Flask(__name__)
    app.config.update(
        EXPANDED_HIERARCHY_ENABLED=True,
        TESTING=True,
        SECRET_KEY="analytics-scope-test",
        JWT_SECRET_KEY="analytics-scope-test",
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{tmp_path / 'analytics.sqlite'}",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        CACHE_TYPE="SimpleCache",
        CACHE_DEFAULT_TIMEOUT=300,
        WTF_CSRF_ENABLED=False,
    )
    db.init_app(app)
    cache.init_app(app)
    app.register_blueprint(analytics_bp, url_prefix="/api/v1/analytics")

    with app.app_context():
        # User and Payment are the actual production models used by the core
        # revenue query. SQLite does not need the unrelated JSONB tenant table
        # to exercise the users.tenant_id ownership foreign key.
        db.metadata.create_all(bind=db.engine, tables=[User.__table__, Payment.__table__])
        cache.clear()

    yield app

    with app.app_context():
        cache.clear()
        db.session.remove()
        db.metadata.drop_all(bind=db.engine, tables=[Payment.__table__, User.__table__])


def _user(email, *, role="master", tenant_id=1):
    from src.models.user import User

    return User(
        email=email,
        password_hash="not-used-by-token-decorator-test",
        first_name="Analytics",
        last_name="Admin",
        is_active=True,
        is_verified=True,
        role=role,
        tenant_id=tenant_id,
        tree_path="1",
    )


def _seed_users(app):
    from src.database import db

    with app.app_context():
        admin_a = _user("admin-a@example.test", tenant_id=1)
        admin_a_peer = _user(
            "admin-a-peer@example.test", role="supermaster", tenant_id=1
        )
        admin_b = _user("admin-b@example.test", tenant_id=2)
        trader = _user("trader@example.test", role="trader", tenant_id=1)
        no_tenant = _user("no-tenant@example.test", tenant_id=None)
        db.session.add_all([admin_a, admin_a_peer, admin_b, trader, no_tenant])
        db.session.commit()
        return {
            "admin-a": admin_a.id,
            "admin-a-peer": admin_a_peer.id,
            "admin-b": admin_b.id,
            "trader": trader.id,
            "no-tenant": no_tenant.id,
        }


def _install_token_lookup(monkeypatch, token_users):
    """Mock signature verification only; token_required still performs User.query.get."""
    from src.models.user import User

    def verify_token(token, token_type="access"):
        if token_type != "access" or token not in token_users:
            return None
        return {"user_id": token_users[token]}

    monkeypatch.setattr(User, "verify_token", staticmethod(verify_token))


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_analytics_cache_is_after_real_authz_and_partitioned_by_actor_tenant_role(
    analytics_app, monkeypatch
):
    """A cache hit never bypasses real token/admin/tenant policy or actor partitioning."""
    from src.services.analytics_service import AnalyticsService

    user_ids = _seed_users(analytics_app)
    _install_token_lookup(monkeypatch, user_ids)
    calls = []

    def fake_kyc_statistics(*, tenant_id=None, current_user=None):
        calls.append(tenant_id)
        return {"tenant_marker": tenant_id, "service_call": len(calls)}

    monkeypatch.setattr(
        AnalyticsService, "get_kyc_statistics", staticmethod(fake_kyc_statistics)
    )
    client = analytics_app.test_client()

    warm_a = client.get("/api/v1/analytics/kyc-statistics", headers=_auth("admin-a"))
    assert warm_a.status_code == 200
    assert warm_a.get_json()["data"] == {"tenant_marker": 1, "service_call": 1}
    hit_a = client.get("/api/v1/analytics/kyc-statistics", headers=_auth("admin-a"))
    assert hit_a.status_code == 200
    assert hit_a.get_json() == warm_a.get_json()
    assert calls == [1]

    # Existing cached success cannot satisfy unauthenticated or non-admin callers.
    assert client.get("/api/v1/analytics/kyc-statistics").status_code == 401
    assert (
        client.get("/api/v1/analytics/kyc-statistics", headers=_auth("trader")).status_code
        == 403
    )
    assert calls == [1]

    # A second tenant and a second admin in tenant A must each miss their own key.
    tenant_b = client.get("/api/v1/analytics/kyc-statistics", headers=_auth("admin-b"))
    assert tenant_b.status_code == 200
    assert tenant_b.get_json()["data"] == {"tenant_marker": 2, "service_call": 2}
    peer_a = client.get(
        "/api/v1/analytics/kyc-statistics", headers=_auth("admin-a-peer")
    )
    assert peer_a.status_code == 200
    assert peer_a.get_json()["data"] == {"tenant_marker": 1, "service_call": 3}

    # Request-selected tenants cannot replace the authenticated user's tenant.
    spoof_header = client.get(
        "/api/v1/analytics/kyc-statistics",
        headers={**_auth("admin-a"), "X-Tenant-ID": "2"},
    )
    assert spoof_header.status_code == 200
    assert spoof_header.get_json()["data"] == {"tenant_marker": 1, "service_call": 1}
    spoof_query = client.get(
        "/api/v1/analytics/kyc-statistics?tenant_id=2", headers=_auth("admin-a")
    )
    assert spoof_query.status_code == 400
    assert client.get(
        "/api/v1/analytics/kyc-statistics", headers=_auth("no-tenant")
    ).status_code == 403
    assert calls == [1, 2, 1]


def test_analytics_cache_canonical_filters_are_separate_and_never_store_errors(
    analytics_app, monkeypatch
):
    """Days is a bounded canonical cache filter; 500 responses are always misses."""
    from src.services.analytics_service import AnalyticsService

    user_ids = _seed_users(analytics_app)
    _install_token_lookup(monkeypatch, user_ids)
    growth_calls = []

    def fake_user_growth(days=30, tenant_id=None, current_user=None):
        growth_calls.append((days, tenant_id))
        return [{"days": days, "tenant": tenant_id, "call": len(growth_calls)}]

    monkeypatch.setattr(AnalyticsService, "get_user_growth", staticmethod(fake_user_growth))
    client = analytics_app.test_client()

    first_day = client.get(
        "/api/v1/analytics/user-growth?days=1", headers=_auth("admin-a")
    )
    day_one_hit = client.get(
        "/api/v1/analytics/user-growth?days=01", headers=_auth("admin-a")
    )
    second_day = client.get(
        "/api/v1/analytics/user-growth?days=2", headers=_auth("admin-a")
    )
    assert first_day.status_code == day_one_hit.status_code == second_day.status_code == 200
    assert first_day.get_json() == day_one_hit.get_json()
    assert first_day.get_json()["data"][0]["days"] == 1
    assert second_day.get_json()["data"][0]["days"] == 2
    assert growth_calls == [(1, 1), (2, 1)]
    assert client.get(
        "/api/v1/analytics/user-growth?days=0", headers=_auth("admin-a")
    ).status_code == 400
    assert client.get(
        "/api/v1/analytics/user-growth?days=1&days=2", headers=_auth("admin-a")
    ).status_code == 400

    errors = []

    def failing_kyc_statistics(*, tenant_id=None, current_user=None):
        errors.append(tenant_id)
        raise RuntimeError("test-only service failure")

    monkeypatch.setattr(
        AnalyticsService, "get_kyc_statistics", staticmethod(failing_kyc_statistics)
    )
    first_error = client.get(
        "/api/v1/analytics/kyc-statistics", headers=_auth("admin-a-peer")
    )
    second_error = client.get(
        "/api/v1/analytics/kyc-statistics", headers=_auth("admin-a-peer")
    )
    assert first_error.status_code == second_error.status_code == 500
    assert errors == [1, 1]


def test_revenue_route_and_service_are_actually_tenant_scoped(analytics_app, monkeypatch):
    """The core payment aggregate uses the real SQLite models and user-tenant join."""
    from src.database import db
    from src.models.payment import Payment
    from src.services.analytics_service import AnalyticsService

    user_ids = _seed_users(analytics_app)
    _install_token_lookup(monkeypatch, user_ids)
    with analytics_app.app_context():
        db.session.add_all([
            Payment(
                user_id=user_ids["admin-a"],
                amount=11,
                status="completed",
                payment_method="card",
                created_at=datetime.utcnow(),
            ),
            Payment(
                user_id=user_ids["admin-b"],
                amount=22,
                status="completed",
                payment_method="card",
                created_at=datetime.utcnow(),
            ),
        ])
        db.session.commit()

        tenant_a_rows = AnalyticsService.get_revenue_over_time(30, tenant_id=1)
        tenant_b_rows = AnalyticsService.get_revenue_over_time(30, tenant_id=2)
        assert sum(row["revenue"] for row in tenant_a_rows) == 11.0
        assert sum(row["revenue"] for row in tenant_b_rows) == 22.0
        with pytest.raises(ValueError):
            AnalyticsService.get_revenue_over_time(30)

    client = analytics_app.test_client()
    response_a = client.get(
        "/api/v1/analytics/revenue-over-time?days=30", headers=_auth("admin-a")
    )
    response_b = client.get(
        "/api/v1/analytics/revenue-over-time?days=30", headers=_auth("admin-b")
    )
    assert response_a.status_code == response_b.status_code == 200
    assert sum(row["revenue"] for row in response_a.get_json()["data"]) == 11.0
    assert sum(row["revenue"] for row in response_b.get_json()["data"]) == 22.0


def test_actual_database_failure_is_not_zero_data_or_cached(analytics_app, monkeypatch):
    from src.database import db
    from src.models.payment import Payment
    user_ids = _seed_users(analytics_app)
    _install_token_lookup(monkeypatch, user_ids)
    with analytics_app.app_context():
        Payment.__table__.drop(db.engine)
    client = analytics_app.test_client()
    for _ in range(2):
        response = client.get('/api/v1/analytics/revenue-over-time', headers=_auth('admin-a'))
        assert response.status_code == 500
        assert response.get_json() == {'error': 'Failed to fetch revenue data'}
    with analytics_app.app_context():
        Payment.__table__.create(db.engine)
    response = client.get('/api/v1/analytics/revenue-over-time', headers=_auth('admin-a'))
    assert response.status_code == 200
    assert response.get_json()['data'] == []


def test_real_challenge_and_referral_aggregates_respect_all_tenant_links(analytics_app):
    from src.database import db
    from src.models import Challenge, TradingProgram
    from src.models.agent import Agent
    from src.models.referral import Referral
    from src.models.commission import Commission
    from src.services.analytics_service import AnalyticsService
    user_ids = _seed_users(analytics_app)
    with analytics_app.app_context():
        tables=[TradingProgram.__table__,Challenge.__table__,Agent.__table__,Referral.__table__,Commission.__table__]
        db.metadata.create_all(db.engine,tables=tables)
        pa=TradingProgram(id=1,tenant_id=1,name='A',type='one_phase',account_size=10000,price=100)
        pb=TradingProgram(id=2,tenant_id=2,name='B',type='one_phase',account_size=10000,price=100)
        ca=Challenge(id=1,user_id=user_ids['admin-a'],program_id=1,initial_balance=10000,current_balance=10000,status='active')
        cb=Challenge(id=2,user_id=user_ids['admin-b'],program_id=2,initial_balance=10000,current_balance=10000,status='funded')
        invalid=Challenge(id=3,user_id=user_ids['admin-a'],program_id=2,initial_balance=10000,current_balance=10000,status='completed')
        aa=Agent(id=1,user_id=user_ids['admin-a'],agent_code='agent-a')
        ab=Agent(id=2,user_id=user_ids['admin-b'],agent_code='agent-b')
        ra=Referral(id=1,agent_id=1,referred_user_id=user_ids['trader'],referral_code='a',status='active')
        ra2=Referral(id=2,agent_id=1,referred_user_id=user_ids['admin-a-peer'],referral_code='a2',status='active')
        foreign=Referral(id=3,agent_id=1,referred_user_id=user_ids['admin-b'],referral_code='foreign',status='active')
        rb=Referral(id=4,agent_id=2,referred_user_id=user_ids['admin-b'],referral_code='b',status='active')
        commissions=[Commission(id=i,agent_id=agent,referral_id=ref,challenge_id=challenge,
                     sale_amount=1000,commission_rate=10,commission_amount=amount)
                     for i,agent,ref,challenge,amount in [(1,1,1,1,10),(2,1,2,1,20),(3,1,3,2,900),(4,1,1,3,800),(5,2,4,2,40),(6,1,3,1,700),(7,1,4,1,600)]]
        db.session.add_all([pa,pb,ca,cb,invalid,aa,ab,ra,ra2,foreign,rb,*commissions])
        db.session.commit()
        try:
            astat=AnalyticsService.get_challenge_statistics(30,tenant_id=1)
            bstat=AnalyticsService.get_challenge_statistics(30,tenant_id=2)
            assert astat['status_distribution']==[{'status':'active','count':1}]
            assert bstat['status_distribution']==[{'status':'funded','count':1}]
            ar=AnalyticsService.get_referral_statistics(tenant_id=1)
            br=AnalyticsService.get_referral_statistics(tenant_id=2)
            assert ar['total_referrals']==2 and ar['active_referrals']==2
            assert ar['top_agents'][0]['total_commission']==30
            assert br['total_referrals']==1 and br['top_agents'][0]['total_commission']==40
            assert {r['agent_id'] for r in ar['top_agents']}=={1}
            assert {r['agent_id'] for r in br['top_agents']}=={2}
        finally:
            db.session.remove()
            db.metadata.drop_all(db.engine,tables=list(reversed(tables)))


def test_cache_misses_after_authenticated_hierarchy_change(analytics_app,monkeypatch):
    from src.database import db
    from src.models.user import User
    from src.services.analytics_service import AnalyticsService
    users=_seed_users(analytics_app)
    _install_token_lookup(monkeypatch,users)
    calls=[]
    def stats(*,tenant_id,current_user=None):
        calls.append(tenant_id)
        return {'call':len(calls)}
    monkeypatch.setattr(AnalyticsService,'get_kyc_statistics',staticmethod(stats))
    client=analytics_app.test_client()
    path='/api/v1/analytics/kyc-statistics'
    assert client.get(path,headers=_auth('admin-a')).get_json()['data']['call']==1
    with analytics_app.app_context():
        db.session.get(User,users['admin-a']).tree_path='other-tree'
        db.session.commit()
    assert client.get(path,headers=_auth('admin-a')).get_json()['data']['call']==2


def test_two_masters_same_tenant_do_not_share_aggregate_ownership(analytics_app,monkeypatch):
    from src.database import db
    from src.models.user import User
    from src.models.payment import Payment
    ids=_seed_users(analytics_app)
    _install_token_lookup(monkeypatch,ids)
    with analytics_app.app_context():
        db.session.get(User,ids['admin-a']).tree_path='a'
        db.session.get(User,ids['admin-a-peer']).tree_path='b'
        db.session.get(User,ids['admin-a-peer']).role='master'
        db.session.add_all([Payment(user_id=ids['admin-a'],amount=11,status='completed'),
                            Payment(user_id=ids['admin-a-peer'],amount=22,status='completed')])
        db.session.commit()
    client=analytics_app.test_client()
    for actor,total in [('admin-a',11),('admin-a-peer',22)]:
        response=client.get('/api/v1/analytics/revenue-over-time',headers=_auth(actor))
        assert response.status_code==200
        assert sum(row['revenue'] for row in response.get_json()['data'])==total


def test_cached_payload_roundtrips_through_actual_redis_serializer(analytics_app,monkeypatch):
    from cachelib.serializers import RedisSerializer
    from src import cache
    from src.services.analytics_service import AnalyticsService
    ids=_seed_users(analytics_app)
    _install_token_lookup(monkeypatch,ids)
    serialized={}
    codec=RedisSerializer()
    calls=[]
    def get(key):
        return codec.loads(serialized[key]) if key in serialized else None
    def set_value(key,value,timeout=None):
        assert isinstance(value,dict) and isinstance(value['body'],bytes)
        serialized[key]=codec.dumps(value)
        return True
    def service(*,tenant_id,current_user):
        calls.append(tenant_id)
        return {'marker':tenant_id}
    monkeypatch.setattr(cache,'get',get)
    monkeypatch.setattr(cache,'set',set_value)
    monkeypatch.setattr(AnalyticsService,'get_kyc_statistics',staticmethod(service))
    client=analytics_app.test_client()
    first=client.get('/api/v1/analytics/kyc-statistics',headers=_auth('admin-a'))
    second=client.get('/api/v1/analytics/kyc-statistics',headers=_auth('admin-a'))
    assert first.status_code==second.status_code==200
    assert first.data==second.data and first.content_type==second.content_type=='application/json'
    assert calls==[1] and len(serialized)==1
