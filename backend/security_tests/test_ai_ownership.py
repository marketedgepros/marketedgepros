"""Ownership containment for AI performance analysis.

These tests deliberately use the real Flask route, token decorator, and
SQLAlchemy User -> Challenge -> TradingProgram -> Tenant chain. The only mock
is the OpenAI provider method, so no request can contact an external service.
"""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles


@pytest.fixture(scope="session", autouse=True)
def sqlite_jsonb_compiler():
    """Compile PostgreSQL JSONB model columns for this isolated SQLite suite."""
    @compiles(JSONB, "sqlite")
    def compile_jsonb(_element, _compiler, **_kwargs):
        return "JSON"


@pytest.fixture
def application(sqlite_jsonb_compiler):
    """A real full application with only ownership/auth tables in SQLite."""
    from src.app import create_app
    from src.database import db
    from src.models import Challenge, Tenant, TokenBlacklist, Trade, TradingProgram, User

    app = create_app(
        "testing",
        config_overrides={"SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"},
    )
    tables = [
        Tenant.__table__,
        User.__table__,
        TradingProgram.__table__,
        Challenge.__table__,
        Trade.__table__,
        TokenBlacklist.__table__,
    ]
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=tables)

    try:
        yield app
    finally:
        with app.app_context():
            db.session.remove()
            db.metadata.drop_all(bind=db.engine, tables=list(reversed(tables)))
            db.engine.dispose()


@pytest.fixture
def ownership_data(application):
    """Persist real actors, tenants, programs, challenges, and trades."""
    from src.database import db
    from src.models import Challenge, Tenant, Trade, TradingProgram, User

    with application.app_context():
        tenant_a = Tenant(name="Tenant A", subdomain="tenant-a", status="active")
        tenant_b = Tenant(name="Tenant B", subdomain="tenant-b", status="active")
        db.session.add_all([tenant_a, tenant_b])
        db.session.flush()

        def user(email, tenant_id):
            return User(
                email=email,
                password_hash="test-only-not-used-for-token-auth",
                first_name="Security",
                last_name="Test",
                role="trader",
                is_active=True,
                is_verified=True,
                tenant_id=tenant_id,
            )

        owner = user("ai-owner@tenant-a.test", tenant_a.id)
        peer = user("ai-peer@tenant-a.test", tenant_a.id)
        other_tenant_user = user("ai-user@tenant-b.test", tenant_b.id)
        missing_tenant_user = user("ai-missing-tenant@test.invalid", None)
        db.session.add_all([owner, peer, other_tenant_user, missing_tenant_user])
        db.session.flush()

        def program(name, tenant_id):
            return TradingProgram(
                tenant_id=tenant_id,
                name=name,
                type="one_phase",
                description="test-only program",
                account_size=10000,
                profit_target=10,
                max_daily_loss=5,
                max_total_loss=10,
                price=100,
                profit_split=80,
                is_active=True,
            )

        tenant_a_program = program("Tenant A Program", tenant_a.id)
        tenant_b_program = program("Tenant B Program", tenant_b.id)
        db.session.add_all([tenant_a_program, tenant_b_program])
        db.session.flush()

        def challenge(user_id, program_id):
            return Challenge(
                user_id=user_id,
                program_id=program_id,
                status="active",
                initial_balance=10000,
                current_balance=10000,
            )

        owned = challenge(owner.id, tenant_a_program.id)
        foreign_actor = challenge(peer.id, tenant_a_program.id)
        # The owner ID matches here, but the authoritative program tenant does
        # not. This proves the tenant check is not inferred from Challenge.
        tenant_mismatch = challenge(owner.id, tenant_b_program.id)
        missing_tenant = challenge(missing_tenant_user.id, tenant_a_program.id)
        db.session.add_all([owned, foreign_actor, tenant_mismatch, missing_tenant])
        db.session.flush()

        def trade(challenge_id, ticket, profit):
            return Trade(
                challenge_id=challenge_id,
                ticket=ticket,
                symbol="EURUSD",
                trade_type="buy",
                volume=1,
                open_price=1.10000,
                close_price=1.10100,
                profit=profit,
                status="closed",
                open_time=datetime(2026, 1, 1, 12, 0, 0),
                close_time=datetime(2026, 1, 1, 12, 5, 0),
            )

        db.session.add_all([
            trade(owned.id, "owned-trade", 125),
            trade(foreign_actor.id, "foreign-actor-trade", 225),
            trade(tenant_mismatch.id, "tenant-mismatch-trade", 325),
            trade(missing_tenant.id, "missing-tenant-trade", 425),
        ])
        db.session.commit()

        return {
            "ids": {
                "tenant_a": tenant_a.id,
                "tenant_b": tenant_b.id,
                "owner": owner.id,
                "peer": peer.id,
                "other_tenant_user": other_tenant_user.id,
                "missing_tenant_user": missing_tenant_user.id,
                "owned": owned.id,
                "foreign_actor": foreign_actor.id,
                "tenant_mismatch": tenant_mismatch.id,
                "missing_tenant": missing_tenant.id,
            },
            "headers": {
                "owner": {"Authorization": f"Bearer {owner.generate_access_token()}"},
                "peer": {"Authorization": f"Bearer {peer.generate_access_token()}"},
                "other_tenant_user": {
                    "Authorization": f"Bearer {other_tenant_user.generate_access_token()}"
                },
                "missing_tenant_user": {
                    "Authorization": f"Bearer {missing_tenant_user.generate_access_token()}"
                },
            },
        }


@pytest.fixture
def provider_service(monkeypatch):
    """Use the actual service with only its outbound provider method mocked."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-a-real-secret")
    from src.services.openai_service import OpenAIService

    service = OpenAIService()
    provider_create = Mock(return_value=SimpleNamespace(
        output="Mocked performance analysis",
        prompt_tokens=10,
        completion_tokens=5,
        total_tokens=15,
    ))
    monkeypatch.setattr(service.client.responses, "create", provider_create)
    monkeypatch.setattr("src.routes.chat.get_openai_service", lambda: service)
    return service, provider_create


@pytest.fixture
def trade_selects(application):
    """Record actual SQL SELECTs against trades after fixture setup."""
    from src.database import db

    statements = []
    with application.app_context():
        engine = db.engine

    def record(_conn, _cursor, statement, _parameters, _context, _executemany):
        normalized = " ".join(statement.lower().split())
        if normalized.startswith("select") and (
            "from trades" in normalized or "join trades" in normalized
        ):
            statements.append(normalized)

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", record)


def _assert_not_found_without_access(response, provider_create, trade_selects):
    assert response.status_code == 404
    assert response.get_json() == {"error": "Resource not found"}
    assert provider_create.call_count == 0
    assert trade_selects == []


@pytest.mark.parametrize(
    ("actor", "challenge", "spoof_tenant"),
    [
        ("peer", "owned", "tenant_b"),
        ("owner", "tenant_mismatch", "tenant_b"),
    ],
)
def test_foreign_actor_or_program_tenant_is_uniformly_hidden_before_trade_or_ai(
    application, ownership_data, provider_service, trade_selects,
    actor, challenge, spoof_tenant,
):
    """Foreign ownership and tenant-chain failures cannot read trades or call AI."""
    _service, provider_create = provider_service
    ids = ownership_data["ids"]
    client = application.test_client()

    response = client.post(
        f"/api/v1/chat/performance-analysis?tenant_id={ids[spoof_tenant]}",
        json={
            "challenge_id": ids[challenge],
            "tenant_id": ids[spoof_tenant],
            "user_id": ids["owner"],
            "email": "ai-owner@tenant-a.test",
        },
        headers={
            **ownership_data["headers"][actor],
            "X-Tenant-ID": str(ids[spoof_tenant]),
        },
    )

    _assert_not_found_without_access(response, provider_create, trade_selects)


def test_nonexistent_and_invalid_challenge_ids_are_uniformly_hidden_before_ai(
    application, ownership_data, provider_service, trade_selects,
):
    """Unknown and malformed IDs have the same non-enumerating 404 response."""
    _service, provider_create = provider_service
    client = application.test_client()

    for challenge_id in (999999, "not-an-id", 0, True):
        response = client.post(
            "/api/v1/chat/performance-analysis",
            json={"challenge_id": challenge_id},
            headers=ownership_data["headers"]["owner"],
        )
        _assert_not_found_without_access(response, provider_create, trade_selects)


def test_missing_authentication_cannot_read_trades_or_call_ai(
    application, provider_service, trade_selects,
):
    """The real token decorator rejects anonymous requests before the route."""
    _service, provider_create = provider_service
    response = application.test_client().post(
        "/api/v1/chat/performance-analysis", json={"challenge_id": 1}
    )

    assert response.status_code == 401
    assert provider_create.call_count == 0
    assert trade_selects == []


def test_missing_authenticated_tenant_fails_closed_before_trade_or_ai(
    application, ownership_data, provider_service, trade_selects,
):
    """A signed-in user with no authoritative tenant cannot use the endpoint."""
    _service, provider_create = provider_service
    ids = ownership_data["ids"]
    response = application.test_client().post(
        "/api/v1/chat/performance-analysis",
        json={"challenge_id": ids["missing_tenant"]},
        headers=ownership_data["headers"]["missing_tenant_user"],
    )

    _assert_not_found_without_access(response, provider_create, trade_selects)


def test_owned_challenge_uses_real_owner_chain_and_provider_once(
    application, ownership_data, provider_service, trade_selects,
):
    """An owned challenge reaches the provider only after the scoped trade read."""
    _service, provider_create = provider_service
    ids = ownership_data["ids"]
    response = application.test_client().post(
        "/api/v1/chat/performance-analysis",
        json={"challenge_id": ids["owned"]},
        headers=ownership_data["headers"]["owner"],
    )

    assert response.status_code == 200
    assert response.get_json()["analysis"] == "Mocked performance analysis"
    assert response.get_json()["performance"]["total_trades"] == 1
    assert provider_create.call_count == 1
    assert len(trade_selects) == 1


def test_service_boundary_rechecks_foreign_scope_without_provider_access(
    application, ownership_data, provider_service, trade_selects,
):
    """Calling the service directly cannot bypass its owner/tenant guard."""
    from src.database import db
    from src.models import User

    service, provider_create = provider_service
    ids = ownership_data["ids"]
    with application.app_context():
        peer = db.session.get(User, ids["peer"])
        response = service.analyze_trading_performance(
            {"total_trades": 1},
            current_user=peer,
            challenge_ids=[ids["owned"]],
        )

    assert response == {
        "success": False,
        "not_found": True,
        "error": "Resource not found",
    }
    assert provider_create.call_count == 0
    assert trade_selects == []
