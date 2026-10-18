"""Opt-in PostgreSQL CRM closure verification; run only by the staging integrator."""
from datetime import timedelta
from decimal import Decimal

import pytest
from flask import Flask
from sqlalchemy import event, select


@pytest.fixture
def ui4_closure_crm_pg_app(staging_resources):
    """Use the runner's private PostgreSQL socket and real mapped CRM tables."""
    from src.database import db
    from src.models.lead import Lead, LeadActivity, LeadNote
    from src.models.tenant import Tenant
    from src.models.token_blacklist import TokenBlacklist
    from src.models.user import User
    from src.routes.crm import crm_bp
    from src.utils.hierarchy_scoping import init_hierarchy_scoping

    app = Flask("ui4-closure-crm-postgresql")
    app.config.update(
        TESTING=True,
        EXPANDED_HIERARCHY_ENABLED=True,
        SQLALCHEMY_DATABASE_URI=staging_resources["pg_url"],
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY="ui4-closure-crm-staging-synthetic-key",
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=10),
        JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=1),
    )
    db.init_app(app)
    init_hierarchy_scoping(db, User)
    app.register_blueprint(crm_bp, url_prefix="/api/v1/crm")
    tables = [Tenant.__table__, User.__table__, TokenBlacklist.__table__, Lead.__table__, LeadActivity.__table__, LeadNote.__table__]
    with app.app_context():
        # The staging runner first inventories the real Alembic migrations. These
        # focused tables are then created solely in its disposable synthetic DB.
        db.metadata.create_all(bind=db.engine, tables=[LeadActivity.__table__, LeadNote.__table__])
        db.session.add_all([
            Tenant(id=1, name="CRM PG tenant", subdomain="ui4-crm-pg", status="active"),
            Tenant(id=2, name="CRM PG foreign", subdomain="ui4-crm-pg-foreign", status="active"),
        ])
        db.session.flush()
        db.session.add_all([
            User(id=1, email="crm-pg-root@example.invalid", password_hash="x", first_name="Root", last_name="One", role="master", tenant_id=1, tree_path="1", level=0, is_active=True, is_verified=True),
            User(id=2, email="crm-pg-child@example.invalid", password_hash="x", first_name="Child", last_name="One", role="agent", tenant_id=1, parent_id=1, tree_path="1/2", level=1, is_active=True, is_verified=True),
            User(id=3, email="crm-pg-foreign@example.invalid", password_hash="x", first_name="Foreign", last_name="Two", role="master", tenant_id=2, tree_path="3", level=0, is_active=True, is_verified=True),
        ])
        db.session.flush()
        db.session.add_all([
            Lead(id=1, first_name="Owned", last_name="PG", email="owned-pg@example.invalid", assigned_to=1, source="website", status="new", score=1, budget=Decimal("10.50")),
            Lead(id=2, first_name="Child", last_name="PG", email="child-pg@example.invalid", assigned_to=2, source="referral", status="proposal", score=2, budget=Decimal("0.00")),
            Lead(id=3, first_name="Foreign", last_name="PG", email="foreign-pg@example.invalid", assigned_to=3, source="website", status="new", score=3, budget=Decimal("88.88")),
        ])
        db.session.commit()
        app.crm_headers = {"Authorization": "Bearer " + db.session.get(User, 1).generate_access_token()}
    try:
        yield app
    finally:
        with app.app_context():
            db.session.rollback()
            db.metadata.drop_all(bind=db.engine, tables=[LeadNote.__table__, LeadActivity.__table__])
            db.session.remove()
            db.engine.dispose()


def test_ui4_closure_crm_postgresql_snapshot_timeout_scope_and_no_read_dml(ui4_closure_crm_pg_app):
    from src.database import db
    from src.models.lead import Lead

    app = ui4_closure_crm_pg_app
    with app.app_context():
        assert db.engine.dialect.name == "postgresql"
        before = [dict(row) for row in db.session.execute(select(Lead.__table__).order_by(Lead.id)).mappings()]
        statements, writes = [], []

        def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append((statement, _parameters))
            if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
                writes.append(statement)

        event.listen(db.engine, "before_cursor_execute", observe)
        try:
            list_response = app.test_client().get("/api/v1/crm/leads?page=1&per_page=20", headers=app.crm_headers)
            detail_response = app.test_client().get("/api/v1/crm/leads/1", headers=app.crm_headers)
        finally:
            event.remove(db.engine, "before_cursor_execute", observe)
        assert list_response.status_code == detail_response.status_code == 200
        body = list_response.get_json()
        assert body["owner_context"] == {"user_id": 1, "tenant_id": 1}
        assert body["pagination"] == {"page": 1, "per_page": 20, "total": 2, "pages": 1}
        assert [row["id"] for row in body["leads"]] == [2, 1]
        assert [row["budget"] for row in body["leads"]] == ["0.00", "10.50"]
        assert detail_response.get_json()["owner_context"] == {"user_id": 1, "tenant_id": 1}
        assert writes == []
        assert sum("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY" in statement for statement, _params in statements) >= 2
        assert sum("SET LOCAL statement_timeout" in statement and "1500ms" in str(params) for statement, params in statements) >= 2
        db.session.expire_all()
        after = [dict(row) for row in db.session.execute(select(Lead.__table__).order_by(Lead.id)).mappings()]
        assert after == before
