"""Read-only legacy scaling endpoints for UI-4.

No endpoint in this blueprint provisions capital, calculates eligibility, or
changes an AccountScaling record until verified scaling evidence is configured.
"""
from flask import Blueprint, g, jsonify, request

from src.services.scaling_service import (
    ScalingDataConflict,
    ScalingScopeNotAuthorized,
    ScalingService,
)
from src.utils.decorators import admin_required, token_required


scaling_bp = Blueprint("scaling", __name__, url_prefix="/api/v1/scaling")


def _owner_context(actor):
    return {"user_id": actor.id, "tenant_id": actor.tenant_id}


def _has_tenant_context(actor):
    tenant_id = getattr(actor, "tenant_id", None)
    return isinstance(tenant_id, int) and not isinstance(tenant_id, bool) and tenant_id > 0


def _tenant_context_error():
    return jsonify({
        "success": False,
        "error": "Tenant context is required",
        "code": "TENANT_CONTEXT_REQUIRED",
    }), 403


def _evidence_not_configured():
    return jsonify(ScalingService.evidence_not_configured()), 503


def _owner_conflict():
    return jsonify({
        "success": False,
        "error": "Scaling owner records conflict",
        "code": ScalingService._CONFLICT_CODE,
    }), 409


def _parse_admin_pagination():
    allowed = {"page", "per_page"}
    for name in request.args.keys():
        if name not in allowed or len(request.args.getlist(name)) != 1:
            return None

    def bounded(name, default):
        if name not in request.args:
            return default
        raw_value = request.args.get(name)
        if (
            not isinstance(raw_value, str)
            or len(raw_value) > (4 if name == "page" else 3)
            or not raw_value.isascii()
            or not raw_value.isdecimal()
        ):
            return None
        value = int(raw_value)
        return value if str(value) == raw_value and 1 <= value <= (1000 if name == "page" else 100) else None

    page = bounded("page", 1)
    per_page = bounded("per_page", 20)
    return (page, per_page) if page is not None and per_page is not None else None


def _progress_response(actor, data):
    return {
        "success": True,
        "data": data,
        "owner_context": _owner_context(actor),
        "data_status": "unverified_legacy",
        "provider_authenticated": False,
        "scaling_enabled": False,
        "currency": None,
    }


@scaling_bp.route("/my-progress", methods=["GET"])
@token_required
def get_my_scaling_progress():
    """Expose one existing legacy projection for the authenticated owner only."""
    actor = g.current_user
    if not _has_tenant_context(actor):
        return _tenant_context_error()
    try:
        data = ScalingService.get_scaling_history(actor.id)
    except ScalingDataConflict:
        return _owner_conflict()
    except Exception:
        return jsonify({
            "success": False,
            "error": "Scaling progress is unavailable",
            "code": "SCALING_PROGRESS_UNAVAILABLE",
        }), 503
    return jsonify(_progress_response(actor, data)), 200


@scaling_bp.route("/eligibility", methods=["GET"])
@token_required
def check_scaling_eligibility():
    """Eligibility cannot be represented safely without verified evidence."""
    if not _has_tenant_context(g.current_user):
        return _tenant_context_error()
    return _evidence_not_configured()


@scaling_bp.route("/tiers", methods=["GET"])
def get_all_tiers():
    """Retired defaults are not an active public scaling policy."""
    return _evidence_not_configured()


# Mutation endpoints deliberately deny after auth/CSRF (and admin where relevant)
# but before body parsing, owner lookup, resource SQL, session flush, or writes.
@scaling_bp.route("/scale-up", methods=["POST"])
@token_required
def scale_up():
    if not _has_tenant_context(g.current_user):
        return _tenant_context_error()
    return _evidence_not_configured()


@scaling_bp.route("/pause", methods=["POST"])
@token_required
def pause_scaling():
    if not _has_tenant_context(g.current_user):
        return _tenant_context_error()
    return _evidence_not_configured()


@scaling_bp.route("/resume", methods=["POST"])
@token_required
def resume_scaling():
    if not _has_tenant_context(g.current_user):
        return _tenant_context_error()
    return _evidence_not_configured()


@scaling_bp.route("/initialize", methods=["POST"])
@token_required
def initialize_scaling():
    if not _has_tenant_context(g.current_user):
        return _tenant_context_error()
    return _evidence_not_configured()


@scaling_bp.route("/admin/user/<int:user_id>", methods=["GET"])
@token_required
@admin_required
def admin_get_user_scaling(user_id):
    """Return one scoped legacy projection; affiliates never reach this handler."""
    actor = g.current_user
    try:
        data = ScalingService.get_admin_user_history(actor, user_id)
    except ScalingScopeNotAuthorized:
        return _tenant_context_error()
    except ScalingDataConflict:
        return _owner_conflict()
    except Exception:
        return jsonify({
            "success": False,
            "error": "Scaling progress is unavailable",
            "code": "SCALING_PROGRESS_UNAVAILABLE",
        }), 503
    if data is None:
        return jsonify({
            "success": False,
            "error": "Scaling user was not found",
            "code": "SCALING_USER_NOT_FOUND",
        }), 404
    return jsonify(_progress_response(actor, data)), 200


@scaling_bp.route("/admin/user/<int:user_id>/update-profit", methods=["POST"])
@token_required
@admin_required
def admin_update_user_profit(user_id):
    """Keep the legacy mutation URL unavailable without touching its resource."""
    return _evidence_not_configured()


@scaling_bp.route("/admin/all-users", methods=["GET"])
@token_required
@admin_required
def get_all_users_scaling():
    """List only configured-root or existing CRM tenant/downline projections."""
    pagination = _parse_admin_pagination()
    if pagination is None:
        return jsonify({
            "success": False,
            "error": "Invalid scaling pagination",
            "code": "SCALING_PAGINATION_INVALID",
        }), 400
    page, per_page = pagination
    actor = g.current_user
    try:
        result = ScalingService.get_all_users_history(actor, page=page, per_page=per_page)
    except ScalingScopeNotAuthorized:
        return _tenant_context_error()
    except ScalingDataConflict:
        return _owner_conflict()
    except Exception:
        return jsonify({
            "success": False,
            "error": "Scaling progress is unavailable",
            "code": "SCALING_PROGRESS_UNAVAILABLE",
        }), 503
    return jsonify({
        "success": True,
        "data": result["data"],
        "owner_context": _owner_context(actor),
        "pagination": result["pagination"],
        "data_status": "unverified_legacy",
        "provider_authenticated": False,
        "scaling_enabled": False,
        "currency": None,
    }), 200
