"""Focused isolated regressions for the UI-4 persisted tenant settings boundary."""
from datetime import timedelta
from types import SimpleNamespace

import pytest
from flask import Flask
from sqlalchemy import JSON, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from src.database import db
from src.models.tenant import Tenant
from src.models.user import User
from src.services.admin_closure_settings import (
    AdminClosureSettingsInvalid,
    AdminClosureSettingsScopeRequired,
    AdminClosureSettingsService,
    AdminClosureSettingsWriteFailed,
)
from src.utils.hierarchy_scoping import init_hierarchy_scoping


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_element, _compiler, **_kwargs):
    return "JSON"


@pytest.fixture
def ui4_closure_settings_app():
    app = Flask("ui4-closure-settings-security")
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY="ui4-closure-settings-security-synthetic-key",
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=10),
        PLATFORM_ROOT_USER_ID=1,
        EXPANDED_HIERARCHY_ENABLED=True,
    )
    db.init_app(app)
    init_hierarchy_scoping(db, User)
    tables = [Tenant.__table__, User.__table__]
    portable_column = Tenant.__table__.c.settings
    original_type = portable_column.type
    with app.app_context():
        if db.engine.dialect.name == "sqlite":
            portable_column.type = JSON()
        db.metadata.create_all(bind=db.engine, tables=tables)
        db.session.add_all([
            Tenant(
                id=1,
                name="Synthetic tenant",
                subdomain="ui4-closure-settings-one",
                status="active",
                contact_email="before@example.invalid",
                contact_phone="+10000000000",
                settings={"legacy": "must-not-be-exposed-or-changed"},
            ),
            Tenant(id=2, name="Foreign tenant", subdomain="ui4-closure-settings-two", status="active"),
            User(
                id=1, email="root@example.invalid", password_hash="x", first_name="Root", last_name="One",
                role="supermaster", tenant_id=1, parent_id=None, tree_path="1", level=0,
                can_create_same_role=True, is_active=True, is_verified=True,
            ),
            User(
                id=2, email="master@example.invalid", password_hash="x", first_name="Master", last_name="Two",
                role="master", tenant_id=1, parent_id=1, tree_path="1/2", level=1,
                can_create_same_role=False, is_active=True, is_verified=True,
            ),
            User(
                id=3, email="foreign-root@example.invalid", password_hash="x", first_name="Foreign", last_name="Root",
                role="supermaster", tenant_id=2, parent_id=None, tree_path="3", level=0,
                can_create_same_role=True, is_active=True, is_verified=True,
            ),
        ])
        db.session.commit()
    try:
        yield app
    finally:
        with app.app_context():
            db.session.remove()
            db.metadata.drop_all(bind=db.engine, tables=list(reversed(tables)))
            portable_column.type = original_type
            db.engine.dispose()


def _actor(identity, *, tenant_id=1, root=True):
    return SimpleNamespace(
        id=identity,
        tenant_id=tenant_id,
        role="supermaster" if root else "master",
        parent_id=None if root else 1,
        tree_path=str(identity) if root else "1/2",
        can_create_same_role=root,
        is_active=True,
        is_verified=True,
    )


def _draft(**changes):
    return {
        "name": "Persisted tenant",
        "contact_email": "persisted@example.invalid",
        "contact_phone": "+19999999999",
        **changes,
    }


def test_ui4_closure_settings_reads_only_the_root_tenant_projection(ui4_closure_settings_app):
    with ui4_closure_settings_app.app_context():
        payload = AdminClosureSettingsService.read(_actor(1))
    assert payload == {
        "owner_context": {"user_id": 1, "tenant_id": 1},
        "scope": {"kind": "tenant", "tenant_id": 1},
        "tenant_settings": {
            "name": "Synthetic tenant",
            "contact_email": "before@example.invalid",
            "contact_phone": "+10000000000",
        },
        "capabilities": {
            "tenant_contact": "persisted",
            "global_system": "unavailable_no_persistence",
            "payment_providers": "unavailable_no_persistence",
        },
    }
    assert "settings" not in payload["tenant_settings"]
    assert "legacy" not in repr(payload)


def test_ui4_closure_settings_persists_exact_allowlisted_tenant_columns_only(ui4_closure_settings_app):
    with ui4_closure_settings_app.app_context():
        payload = AdminClosureSettingsService.update(_actor(1), _draft(contact_email=None, contact_phone=None))
        db.session.expire_all()
        tenant = db.session.scalar(select(Tenant).where(Tenant.id == 1))
        foreign = db.session.scalar(select(Tenant).where(Tenant.id == 2))
    assert payload["tenant_settings"] == _draft(contact_email=None, contact_phone=None)
    assert tenant.name == "Persisted tenant"
    assert tenant.contact_email is None and tenant.contact_phone is None
    assert tenant.settings == {"legacy": "must-not-be-exposed-or-changed"}
    assert foreign.name == "Foreign tenant"


def test_ui4_closure_settings_refuses_nonroot_or_wrong_configured_root_before_tenant_sql(ui4_closure_settings_app):
    with ui4_closure_settings_app.app_context():
        statements = []

        def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement.lower())

        event.listen(db.engine, "before_cursor_execute", observe)
        try:
            with pytest.raises(AdminClosureSettingsScopeRequired):
                AdminClosureSettingsService.read(_actor(2, root=False))
            with pytest.raises(AdminClosureSettingsScopeRequired):
                AdminClosureSettingsService.read(_actor(3, tenant_id=2))
        finally:
            event.remove(db.engine, "before_cursor_execute", observe)
    assert not any("tenants" in statement for statement in statements)


@pytest.mark.parametrize("payload", [
    {},
    {"tenant_settings": {}},
    {"tenant_settings": {**_draft(), "unexpected": True}},
    {"tenant_settings": _draft(name="")},
    {"tenant_settings": _draft(name=True)},
    {"tenant_settings": _draft(contact_email=7)},
    {"tenant_settings": _draft(contact_phone="x" * 21)},
])
def test_ui4_closure_settings_rejects_invalid_or_unallowlisted_payload_before_resource_sql(
        ui4_closure_settings_app, payload):
    with ui4_closure_settings_app.app_context():
        statements = []

        def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement.lower())

        event.listen(db.engine, "before_cursor_execute", observe)
        try:
            with pytest.raises(AdminClosureSettingsInvalid):
                AdminClosureSettingsService.parse_update_payload(payload)
        finally:
            event.remove(db.engine, "before_cursor_execute", observe)
    assert statements == []


def test_ui4_closure_settings_rolls_back_when_commit_fails(ui4_closure_settings_app, monkeypatch):
    with ui4_closure_settings_app.app_context():
        original_commit = db.session.commit

        def fail_commit():
            raise RuntimeError("synthetic commit failure")

        monkeypatch.setattr(db.session, "commit", fail_commit)
        with pytest.raises(AdminClosureSettingsWriteFailed):
            AdminClosureSettingsService.update(_actor(1), _draft())
        monkeypatch.setattr(db.session, "commit", original_commit)
        db.session.expire_all()
        tenant = db.session.scalar(select(Tenant).where(Tenant.id == 1))
    assert tenant.name == "Synthetic tenant"
    assert tenant.contact_email == "before@example.invalid"
    assert tenant.contact_phone == "+10000000000"


def test_ui4_closure_settings_parameterless_read_contract_rejects_query_before_sql(ui4_closure_settings_app):
    with ui4_closure_settings_app.app_context():
        statements = []

        def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement.lower())

        event.listen(db.engine, "before_cursor_execute", observe)
        try:
            with pytest.raises(AdminClosureSettingsInvalid):
                AdminClosureSettingsService.parse_query({"tenant_id": "2"})
        finally:
            event.remove(db.engine, "before_cursor_execute", observe)
    assert statements == []
