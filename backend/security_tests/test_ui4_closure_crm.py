"""Focused UI-4 CRM closure route regressions with synthetic SQLite records only."""
from datetime import timedelta
from decimal import Decimal

import pytest
from flask import Flask
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from src.database import db
from src.models.lead import Lead, LeadActivity, LeadNote
from src.models.tenant import Tenant
from src.models.token_blacklist import TokenBlacklist
from src.models.trading_program import TradingProgram
from src.models.user import User
from src.routes.crm import crm_bp
from src.utils.hierarchy_scoping import init_hierarchy_scoping


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


_TABLES = (
    Tenant.__table__, User.__table__, TokenBlacklist.__table__, TradingProgram.__table__,
    Lead.__table__, LeadActivity.__table__, LeadNote.__table__,
)


@pytest.fixture
def ui4_closure_crm_app():
    app = Flask("ui4-closure-crm")
    app.config.update(
        TESTING=True,
        EXPANDED_HIERARCHY_ENABLED=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY="ui4-closure-crm-synthetic-key",
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=10),
        JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=1),
    )
    db.init_app(app)
    app.register_blueprint(crm_bp, url_prefix="/api/v1/crm")
    with app.app_context():
        init_hierarchy_scoping(db, User)
        for table in _TABLES:
            table.create(bind=db.engine, checkfirst=False)
        tenant_a = Tenant(id=1, name="CRM tenant A", subdomain="ui4-crm-a", status="active")
        tenant_b = Tenant(id=2, name="CRM tenant B", subdomain="ui4-crm-b", status="active")
        root = User(id=1, email="crm-root@example.invalid", password_hash="x", first_name="Root", last_name="A",
                    role="master", tenant_id=1, tree_path="1", level=0, is_active=True, is_verified=True)
        child = User(id=2, email="crm-child@example.invalid", password_hash="x", first_name="Child", last_name="A",
                     role="agent", tenant_id=1, parent_id=1, tree_path="1/2", level=1, is_active=True, is_verified=True)
        sibling = User(id=3, email="crm-sibling@example.invalid", password_hash="x", first_name="Sibling", last_name="A",
                       role="master", tenant_id=1, tree_path="3", level=0, is_active=True, is_verified=True)
        foreign = User(id=4, email="crm-foreign@example.invalid", password_hash="x", first_name="Foreign", last_name="B",
                       role="master", tenant_id=2, tree_path="4", level=0, is_active=True, is_verified=True)
        db.session.add_all([tenant_a, tenant_b, root, child, sibling, foreign])
        db.session.flush()
        db.session.add_all([
            Lead(id=11, first_name="Owned", last_name="Lead", email="owned@example.invalid", status="new",
                 source="website", score=25, budget=Decimal("10.50"), assigned_to=1),
            Lead(id=12, first_name="Child", last_name="Lead", email="child@example.invalid", status="proposal",
                 source="referral", score=30, budget=Decimal("0.00"), assigned_to=2),
            Lead(id=13, first_name="Sibling", last_name="Lead", email="sibling@example.invalid", status="new",
                 source="website", score=40, budget=Decimal("99.99"), assigned_to=3),
            Lead(id=14, first_name="Foreign", last_name="Lead", email="foreign@example.invalid", status="new",
                 source="website", score=50, budget=Decimal("88.88"), assigned_to=4),
        ])
        db.session.commit()
        app.crm_headers = {"Authorization": "Bearer " + db.session.get(User, 1).generate_access_token()}
    try:
        yield app
    finally:
        with app.app_context():
            db.session.remove()
            for table in reversed(_TABLES):
                table.drop(bind=db.engine, checkfirst=True)


def _client(app):
    return app.test_client()


def test_ui4_closure_crm_list_and_detail_are_snapshot_scoped_with_exact_budget_strings(ui4_closure_crm_app):
    response = _client(ui4_closure_crm_app).get("/api/v1/crm/leads?page=1&per_page=20", headers=ui4_closure_crm_app.crm_headers)
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["owner_context"] == {"user_id": 1, "tenant_id": 1}
    assert payload["pagination"] == {"page": 1, "per_page": 20, "total": 2, "pages": 1}
    assert payload["filters"] == {"status": None, "source": None, "search": ""}
    assert {row["id"] for row in payload["leads"]} == {11, 12}
    assert {row["budget"] for row in payload["leads"]} == {"10.50", "0.00"}
    assert all(isinstance(row["budget"], str) for row in payload["leads"])

    detail = _client(ui4_closure_crm_app).get("/api/v1/crm/leads/11", headers=ui4_closure_crm_app.crm_headers)
    assert detail.status_code == 200
    assert detail.get_json()["id"] == 11
    assert detail.get_json()["owner_context"] == {"user_id": 1, "tenant_id": 1}
    assert detail.get_json()["budget"] == "10.50"

    for hidden_id in (13, 14):
        hidden = _client(ui4_closure_crm_app).get(f"/api/v1/crm/leads/{hidden_id}", headers=ui4_closure_crm_app.crm_headers)
        assert hidden.status_code == 404


def test_ui4_closure_crm_note_activity_and_versioned_save_return_persisted_owner_scoped_rows(ui4_closure_crm_app):
    client = _client(ui4_closure_crm_app)
    headers = ui4_closure_crm_app.crm_headers
    before = client.get("/api/v1/crm/leads/11", headers=headers).get_json()

    note = client.post("/api/v1/crm/leads/11/notes", headers=headers, json={"content": "Synthetic internal note"})
    assert note.status_code == 201
    assert note.get_json()["note"]["lead_id"] == 11
    assert note.get_json()["owner_context"] == {"user_id": 1, "tenant_id": 1}

    activity = client.post("/api/v1/crm/leads/11/activities", headers=headers, json={
        "activity_type": "follow_up", "description": "Synthetic follow-up", "scheduled_at": "2026-10-12T14:00:00",
    })
    assert activity.status_code == 201
    assert activity.get_json()["activity"]["lead_id"] == 11
    assert activity.get_json()["activity"]["scheduled_at"] == "2026-10-12T14:00:00"

    saved = client.patch("/api/v1/crm/leads/11", headers=headers, json={
        "status": "contacted", "budget": "12.75", "expected_updated_at": before["updated_at"],
    })
    assert saved.status_code == 200
    saved_payload = saved.get_json()
    assert saved_payload["lead"]["id"] == 11
    assert saved_payload["lead"]["status"] == "contacted"
    assert saved_payload["lead"]["budget"] == "12.75"
    assert saved_payload["owner_context"] == {"user_id": 1, "tenant_id": 1}

    stale = client.patch("/api/v1/crm/leads/11", headers=headers, json={
        "status": "lost", "expected_updated_at": before["updated_at"],
    })
    assert stale.status_code == 409
    assert stale.get_json()["code"] == "CRM_LEAD_STALE"

    notes = client.get("/api/v1/crm/leads/11/notes?page=1&per_page=20", headers=headers)
    activities = client.get("/api/v1/crm/leads/11/activities?page=1&per_page=20", headers=headers)
    assert notes.status_code == activities.status_code == 200
    assert notes.get_json()["owner_context"] == activities.get_json()["owner_context"] == {"user_id": 1, "tenant_id": 1}
    assert all(row["lead_id"] == 11 for row in notes.get_json()["notes"])
    assert all(row["lead_id"] == 11 for row in activities.get_json()["activities"])


def test_ui4_closure_crm_rejects_duplicate_query_and_cross_scope_write_before_dml(ui4_closure_crm_app):
    client = _client(ui4_closure_crm_app)
    headers = ui4_closure_crm_app.crm_headers
    invalid = client.get("/api/v1/crm/leads?page=1&page=2", headers=headers)
    assert invalid.status_code == 400
    assert invalid.get_json()["code"] == "INVALID_CRM_QUERY"

    denied = client.post("/api/v1/crm/leads/13/activities", headers=headers, json={
        "activity_type": "call", "description": "Must not persist",
    })
    assert denied.status_code == 404
    with ui4_closure_crm_app.app_context():
        assert db.session.query(LeadActivity).filter(LeadActivity.lead_id == 13).count() == 0
