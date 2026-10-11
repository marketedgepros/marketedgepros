"""Configured-root tenant context for the single-brand launch.

The launch mode deliberately has no request-selected tenant.  A tenant is only
trusted when it is the active brand owned by the configured platform root.
Expanded hierarchy/white-label routing remains a future feature and this module
does not implement its legacy Host, header, or query-string routing.
"""
from functools import wraps
import logging

from flask import abort, current_app, g
from sqlalchemy import false, select

from src.database import db

logger = logging.getLogger(__name__)


class TenantContextError(ValueError):
    """Base error for a missing or invalid trusted tenant context."""


class TenantScopeError(TenantContextError):
    """Raised when tenant filtering is requested for an unscoped model."""


class TenantIsolationError(TenantContextError):
    """Raised when caller-controlled data conflicts with trusted tenancy."""


def _valid_tenant_id(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _mvp_single_brand_mode(app=None):
    """Return true only for the explicitly configured single-brand launch mode."""
    app = app or current_app
    return app.config.get("EXPANDED_HIERARCHY_ENABLED", False) is False


def get_tenant_from_request():
    """Resolve the one launch brand, never a client-selected tenant.

    This performs one joined owner-and-tenant query for the configured root.  It
    intentionally does not inspect Host, ``X-Tenant-ID``, query parameters, or
    any default/first-active row.  The explicit hierarchy bypass is confined to
    this configuration bootstrap lookup; it is not an HTTP-selectable bypass.
    """
    # Imports stay local because this middleware runs before authentication and
    # model/service import order is otherwise easy to couple into an auth loop.
    from src.models.tenant import Tenant
    from src.models.user import User
    from src.utils.hierarchy_scoping import (
        configured_platform_root_id,
        platform_root_scope,
        tenant_hierarchy_scope,
        without_hierarchy_scope,
    )

    owner_id = configured_platform_root_id()
    if owner_id is None:
        return None

    statement = (
        select(User, Tenant)
        .join(Tenant, Tenant.id == User.tenant_id)
        .where(User.id == owner_id, Tenant.status == "active")
    )
    # This middleware runs before token_required establishes a request scope.
    # Keep the configuration lookup explicitly unscoped even if a prior handler
    # set one, and do not retain either object beyond this request.
    with db.session.no_autoflush, without_hierarchy_scope(db.session):
        row = db.session.execute(
            statement.execution_options(skip_hierarchy_scope=True, populate_existing=True)
        ).one_or_none()

    if row is None:
        return None

    owner, tenant = row
    if (
        not platform_root_scope(owner)
        or not tenant_hierarchy_scope(owner)
        or owner.tenant_id != tenant.id
        or tenant.status != "active"
    ):
        return None
    return tenant


def tenant_context():
    """Set only the configured launch-brand context for this request.

    Missing configuration or an unavailable brand is intentionally non-fatal:
    public health and configuration endpoints can respond, while callers that
    require a tenant must use ``require_tenant`` or the fail-closed helpers.
    """
    tenant = get_tenant_from_request()
    if tenant is None:
        g.tenant = None
        g.tenant_id = None
        logger.warning("Configured single-brand tenant is unavailable")
        return

    g.tenant = tenant
    g.tenant_id = tenant.id
    logger.debug("Configured single-brand tenant context set")


def require_tenant(f):
    """Require an already resolved tenant context for a route."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if getattr(g, "tenant", None) is None:
            logger.error("Tenant required but unavailable")
            abort(400, description="Tenant context is unavailable.")
        return f(*args, **kwargs)
    return decorated_function


def tenant_required(f):
    """Alias for :func:`require_tenant`."""
    return require_tenant(f)


def get_current_tenant():
    """Return the request's configured launch tenant, if available."""
    return getattr(g, "tenant", None)


def get_current_tenant_id():
    """Return the request's configured launch tenant ID, if available."""
    return getattr(g, "tenant_id", None)


def filter_by_tenant(query, model_class):
    """Apply the trusted tenant predicate or refuse the query.

    A model without a ``tenant_id`` attribute has no safe implicit global
    interpretation.  A tenant-aware model without a resolved request tenant is
    filtered by SQL false, rather than being returned unfiltered.
    """
    if not hasattr(model_class, "tenant_id"):
        raise TenantScopeError("Tenant-scoped filtering requires a tenant-aware model")

    tenant_id = get_current_tenant_id()
    if not _valid_tenant_id(tenant_id):
        return query.filter(false())
    return query.filter(getattr(model_class, "tenant_id") == tenant_id)


def ensure_tenant_isolation(data, user=None):
    """Return a copy of ``data`` bound to a trusted tenant.

    Request context and an explicitly supplied authenticated user are both
    trusted server-side sources.  They must agree when both are supplied; a
    body-provided ``tenant_id`` is never allowed to choose or override either.
    Errors happen before the caller's mapping is changed and contain no tenant
    identifiers.
    """
    if not isinstance(data, dict):
        raise TenantIsolationError("Tenant-isolated input must be a dictionary")

    context_tenant = get_current_tenant()
    context_id = get_current_tenant_id()
    if (
        context_tenant is None
        or getattr(context_tenant, "id", None) != context_id
        or not _valid_tenant_id(context_id)
    ):
        context_id = None

    user_id = None
    if user is not None:
        candidate_id = getattr(user, "tenant_id", None)
        if not _valid_tenant_id(candidate_id):
            raise TenantIsolationError("Trusted user tenant is required")
        user_id = candidate_id

    if context_id is not None and user_id is not None and context_id != user_id:
        raise TenantIsolationError("Trusted tenant sources disagree")

    trusted_tenant_id = context_id if context_id is not None else user_id
    if trusted_tenant_id is None:
        raise TenantIsolationError("Trusted tenant context is required")

    if "tenant_id" in data and data["tenant_id"] != trusted_tenant_id:
        raise TenantIsolationError("Tenant selection is not permitted")

    isolated = dict(data)
    isolated["tenant_id"] = trusted_tenant_id
    return isolated


def init_tenant_middleware(app):
    """Register configured-root context in MVP mode, including opted-in tests.

    Standard test fixtures use ``EXPANDED_HIERARCHY_ENABLED=True`` to retain
    legacy hierarchy coverage, so they intentionally receive no middleware
    registration.  Tests that explicitly opt into the launch mode with
    ``False`` exercise the real before-request handler even when ``TESTING`` is
    true.  No expanded-mode public brand routing is launched here.
    """
    if not _mvp_single_brand_mode(app):
        logger.info("Tenant middleware not registered outside single-brand MVP mode")
        return

    @app.before_request
    def set_tenant_context():
        tenant_context()

    logger.info("Configured-root tenant middleware initialized")
