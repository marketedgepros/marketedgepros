"""PostgreSQL staging contract for the UI-4 persisted tenant-settings boundary.

Run only through backend/scripts/run_staging_integration.py. The runner inventories the
real migration chain before this test and provisions an isolated Unix-socket PostgreSQL.
"""
from datetime import timedelta

from flask import Flask
from sqlalchemy import event, select


def test_ui4_closure_settings_postgresql_root_scope_timeout_and_persistence(staging_resources):
    from src.database import db
    from src.models.tenant import Tenant
    from src.models.user import User
    from src.services.admin_closure_settings import AdminClosureSettingsService
    from src.utils.hierarchy_scoping import init_hierarchy_scoping

    app = Flask("ui4-closure-settings-postgresql")
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI=staging_resources["pg_url"],
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY="ui4-closure-settings-staging-synthetic-key",
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=10),
        PLATFORM_ROOT_USER_ID=1,
        EXPANDED_HIERARCHY_ENABLED=True,
    )
    db.init_app(app)
    init_hierarchy_scoping(db, User)
    tables = [Tenant.__table__, User.__table__]
    with app.app_context():
        assert db.engine.dialect.name == "postgresql"
        db.metadata.create_all(bind=db.engine, tables=tables)
        db.session.add_all([
            Tenant(
                id=1,
                name="PG tenant before",
                subdomain="ui4-closure-settings-pg",
                status="active",
                contact_email="before@example.invalid",
                contact_phone="+10000000000",
                settings={"legacy": "unchanged"},
            ),
            User(
                id=1, email="pg-root@example.invalid", password_hash="x", first_name="Root", last_name="One",
                role="supermaster", tenant_id=1, parent_id=None, tree_path="1", level=0,
                can_create_same_role=True, is_active=True, is_verified=True,
            ),
        ])
        db.session.commit()
        actor = db.session.get(User, 1)
        statements = []

        def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)

        event.listen(db.engine, "before_cursor_execute", observe)
        try:
            before = AdminClosureSettingsService.read(actor)
            acknowledged = AdminClosureSettingsService.update(actor, {
                "name": "PG tenant after",
                "contact_email": None,
                "contact_phone": "+19999999999",
            })
        finally:
            event.remove(db.engine, "before_cursor_execute", observe)
        db.session.expire_all()
        persisted = db.session.scalar(select(Tenant).where(Tenant.id == 1))

        assert before["owner_context"] == {"user_id": 1, "tenant_id": 1}
        assert before["tenant_settings"]["name"] == "PG tenant before"
        assert acknowledged["tenant_settings"] == {
            "name": "PG tenant after",
            "contact_email": None,
            "contact_phone": "+19999999999",
        }
        assert acknowledged["capabilities"] == {
            "tenant_contact": "persisted",
            "global_system": "unavailable_no_persistence",
            "payment_providers": "unavailable_no_persistence",
        }
        assert persisted.name == "PG tenant after"
        assert persisted.contact_email is None
        assert persisted.contact_phone == "+19999999999"
        assert persisted.settings == {"legacy": "unchanged"}
        assert sum("SET LOCAL statement_timeout = 1500" in statement for statement in statements) == 2
    with app.app_context():
        db.session.remove()
