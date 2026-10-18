"""Configured-root tenant-context MVP regressions.

These tests use real Tenant/User rows and Flask request handling.  They cover
request tenant selection only; they are not a claim of complete route-level
RBAC coverage.
"""
from datetime import timedelta

from flask import Flask, g, jsonify
import pytest
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from src.database import db
from src.middleware.tenant_middleware import (
    TenantIsolationError,
    TenantScopeError,
    ensure_tenant_isolation,
    filter_by_tenant,
    get_current_tenant,
    get_current_tenant_id,
    init_tenant_middleware,
)
from src.models.tenant import Tenant
from src.models.token_blacklist import TokenBlacklist
from src.models.user import User
from src.utils.decorators import token_required


@compiles(JSONB, "sqlite")
def _jsonb_as_json_for_scratch_sqlite(type_, compiler, **kwargs):
    """Keep the production model's JSONB column usable in the isolated scratch DB."""
    return "JSON"


_ROOT_ID = 101
_ROOT_TENANT_ID = 10
_OTHER_TENANT_ID = 20
_INACTIVE_TENANT_ID = 30


@pytest.fixture
def mvp_app():
    """A real request app explicitly opted into MVP middleware while testing."""
    app = Flask("mvp-tenant-context")
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY="mvp-tenant-context-test-signing-key-only",
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=10),
        JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=1),
        PLATFORM_ROOT_USER_ID=_ROOT_ID,
        EXPANDED_HIERARCHY_ENABLED=False,
    )
    db.init_app(app)
    init_tenant_middleware(app)

    @app.get("/_tenant-context")
    def tenant_context_view():
        tenant = get_current_tenant()
        return jsonify({
            "has_tenant": tenant is not None,
            "tenant_id": get_current_tenant_id(),
        })

    @app.get("/_tenant-context/authenticated")
    @token_required
    def authenticated_tenant_context(current_user):
        return jsonify({
            "tenant_id": get_current_tenant_id(),
            "user_tenant_id": current_user.tenant_id,
        })

    tables = (Tenant.__table__, User.__table__, TokenBlacklist.__table__)
    with app.app_context():
        for table in tables:
            table.create(db.engine)
        db.session.add_all([
            Tenant(id=_ROOT_TENANT_ID, name="Launch", subdomain="launch", status="active"),
            Tenant(id=_OTHER_TENANT_ID, name="Other", subdomain="other", status="active"),
            Tenant(id=_INACTIVE_TENANT_ID, name="Inactive", subdomain="inactive", status="inactive"),
        ])
        db.session.flush()
        db.session.add_all([
            User(
                id=_ROOT_ID,
                email="root@mvp.invalid",
                password_hash="not-a-login-credential",
                first_name="Configured",
                last_name="Root",
                role="supermaster",
                tree_path=str(_ROOT_ID),
                tenant_id=_ROOT_TENANT_ID,
                is_active=True,
                is_verified=True,
                can_create_same_role=True,
            ),
            User(
                id=102,
                email="member@mvp.invalid",
                password_hash="not-a-login-credential",
                first_name="Launch",
                last_name="Member",
                role="trader",
                parent_id=_ROOT_ID,
                tree_path=f"{_ROOT_ID}/102",
                tenant_id=_ROOT_TENANT_ID,
                is_active=True,
                is_verified=True,
            ),
            # A valid-looking alternate root and its member prove that the
            # configured identity, rather than any first active row, is used.
            User(
                id=201,
                email="alternate-root@mvp.invalid",
                password_hash="not-a-login-credential",
                first_name="Alternate",
                last_name="Root",
                role="supermaster",
                tree_path="201",
                tenant_id=_OTHER_TENANT_ID,
                is_active=True,
                is_verified=True,
                can_create_same_role=True,
            ),
            User(
                id=202,
                email="other-member@mvp.invalid",
                password_hash="not-a-login-credential",
                first_name="Other",
                last_name="Member",
                role="trader",
                parent_id=201,
                tree_path="201/202",
                tenant_id=_OTHER_TENANT_ID,
                is_active=True,
                is_verified=True,
            ),
        ])
        db.session.commit()

    try:
        yield app
    finally:
        with app.app_context():
            db.session.remove()
            for table in reversed(tables):
                table.drop(db.engine)


def _context_response(app, **kwargs):
    return app.test_client().get("/_tenant-context", **kwargs)


def test_testing_true_explicit_mvp_mode_registers_real_request_middleware(mvp_app):
    """Legacy tests may skip it; an explicit launch-mode test must not."""
    response = _context_response(mvp_app)
    assert response.status_code == 200
    assert response.get_json() == {"has_tenant": True, "tenant_id": _ROOT_TENANT_ID}


def test_expanded_hierarchy_legacy_testing_mode_keeps_middleware_unregistered():
    """Existing future-feature fixtures do not accidentally launch MVP routing."""
    app = Flask("legacy-expanded-hierarchy")
    app.config.update(TESTING=True, EXPANDED_HIERARCHY_ENABLED=True)
    init_tenant_middleware(app)

    @app.get("/_tenant-context")
    def legacy_context_view():
        return jsonify({"has_tenant": get_current_tenant() is not None})

    response = app.test_client().get("/_tenant-context")
    assert response.status_code == 200
    assert response.get_json() == {"has_tenant": False}


def test_header_query_and_host_cannot_select_a_different_tenant(mvp_app):
    response = _context_response(
        mvp_app,
        headers={"Host": "other.example.invalid", "X-Tenant-ID": str(_OTHER_TENANT_ID)},
        query_string={"tenant_id": _OTHER_TENANT_ID},
    )
    assert response.status_code == 200
    assert response.get_json() == {"has_tenant": True, "tenant_id": _ROOT_TENANT_ID}


@pytest.mark.parametrize("configured_root", [None, 0, "not-a-root", 999])
def test_missing_or_invalid_configured_owner_fails_closed_without_first_row_fallback(
    mvp_app, configured_root
):
    mvp_app.config["PLATFORM_ROOT_USER_ID"] = configured_root
    response = _context_response(mvp_app)
    assert response.status_code == 200  # Public routes remain available.
    assert response.get_json() == {"has_tenant": False, "tenant_id": None}


@pytest.mark.parametrize("field,value", [
    ("is_verified", False),
    ("is_active", False),
    ("can_create_same_role", False),
    ("role", "trader"),
    ("parent_id", 201),
])
def test_invalid_configured_owner_flags_leave_context_unset(mvp_app, field, value):
    with mvp_app.app_context():
        setattr(db.session.get(User, _ROOT_ID), field, value)
        db.session.commit()

    response = _context_response(mvp_app)
    assert response.status_code == 200
    assert response.get_json() == {"has_tenant": False, "tenant_id": None}


def test_inactive_owner_brand_fails_closed_without_active_tenant_fallback(mvp_app):
    with mvp_app.app_context():
        db.session.get(User, _ROOT_ID).tenant_id = _INACTIVE_TENANT_ID
        db.session.commit()

    response = _context_response(mvp_app)
    assert response.status_code == 200
    assert response.get_json() == {"has_tenant": False, "tenant_id": None}


def test_each_request_requeries_current_configured_brand_without_privilege_cache(mvp_app):
    assert _context_response(mvp_app).get_json()["tenant_id"] == _ROOT_TENANT_ID

    with mvp_app.app_context():
        db.session.get(User, _ROOT_ID).tenant_id = _OTHER_TENANT_ID
        db.session.commit()
        # Simulate the next request getting a fresh scoped session, rather than
        # allowing an identity-map instance to stand in for middleware caching.
        db.session.remove()

    assert _context_response(mvp_app).get_json()["tenant_id"] == _OTHER_TENANT_ID


def test_tenant_filters_fail_closed_and_unscoped_models_are_explicit_errors(mvp_app):
    with mvp_app.test_request_context("/_direct-boundary"):
        g.tenant = None
        g.tenant_id = None
        assert filter_by_tenant(User.query, User).count() == 0
        with pytest.raises(TenantScopeError, match="tenant-aware model") as error:
            filter_by_tenant(Tenant.query, Tenant)
        assert str(_ROOT_TENANT_ID) not in str(error.value)


def test_tenant_isolation_rejects_injection_conflicts_and_never_mutates_input(mvp_app):
    with mvp_app.test_request_context("/_direct-boundary"):
        root_tenant = db.session.get(Tenant, _ROOT_TENANT_ID)
        root_user = db.session.get(User, _ROOT_ID)
        other_user = db.session.get(User, 202)
        g.tenant = root_tenant
        g.tenant_id = _ROOT_TENANT_ID

        injected = {"name": "attempt", "tenant_id": _OTHER_TENANT_ID}
        original = dict(injected)
        with pytest.raises(TenantIsolationError, match="not permitted") as error:
            ensure_tenant_isolation(injected, user=root_user)
        assert injected == original
        assert str(_OTHER_TENANT_ID) not in str(error.value)

        conflict = {"name": "attempt"}
        with pytest.raises(TenantIsolationError, match="disagree"):
            ensure_tenant_isolation(conflict, user=other_user)
        assert conflict == {"name": "attempt"}

        isolated = ensure_tenant_isolation({"name": "safe"}, user=root_user)
        assert isolated == {"name": "safe", "tenant_id": _ROOT_TENANT_ID}

        g.tenant = None
        g.tenant_id = None
        missing = {"name": "no-trusted-tenant"}
        with pytest.raises(TenantIsolationError, match="required"):
            ensure_tenant_isolation(missing)
        assert missing == {"name": "no-trusted-tenant"}


def test_signed_jwt_principal_must_match_owner_brand_after_context_resolution(mvp_app):
    with mvp_app.app_context():
        launch_token = db.session.get(User, 102).generate_access_token()
        other_brand_token = db.session.get(User, 202).generate_access_token()

    accepted = mvp_app.test_client().get(
        "/_tenant-context/authenticated",
        headers={"Authorization": f"Bearer {launch_token}"},
    )
    assert accepted.status_code == 200
    assert accepted.get_json() == {
        "tenant_id": _ROOT_TENANT_ID,
        "user_tenant_id": _ROOT_TENANT_ID,
    }

    rejected = mvp_app.test_client().get(
        "/_tenant-context/authenticated",
        headers={"Authorization": f"Bearer {other_brand_token}"},
    )
    assert rejected.status_code == 401
    assert "tenant_id" not in rejected.get_json()
