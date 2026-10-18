"""Authenticated in-app notification API.

This blueprint intentionally keeps user inbox state separate from the legacy
monitoring notification service.  It never sends messages externally.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import func, select

from src.database import db
from src.middleware.auth import admin_required, get_current_user, jwt_required
from src.models.notification import Notification
from src.models.tenant import Tenant
from src.models.user import User
from src.services.in_app_notification_service import (
    EMAIL_FREQUENCIES,
    NOTIFICATION_PRIORITIES,
    NOTIFICATION_TYPES,
    PREFERENCE_CATEGORIES,
    InAppNotificationService,
)
from src.utils import crm_scope
from src.utils.hierarchy_scoping import platform_root_scope


notifications_bp = Blueprint("notifications", __name__)
logger = logging.getLogger(__name__)

_MAX_BODY_BYTES = 64 * 1024
_ALLOWED_PREFERENCE_TOP_LEVEL = frozenset({"in_app", "email", "settings"})
_ALLOWED_PREFERENCE_SETTINGS = frozenset({"email_enabled", "email_frequency"})


class _DuplicateJSONKey(ValueError):
    """Raised when a JSON object repeats a key at any nesting level."""


def _error(message: str, status: int, code: str | None = None):
    payload: dict[str, Any] = {"error": message}
    if code:
        payload["code"] = code
    return jsonify(payload), status


def _internal_error():
    """One deliberately generic response for every unexpected route failure."""
    return _error("Unable to process notification request", 500, "NOTIFICATION_ERROR")


def _strict_query(allowed: set[str] | frozenset[str]):
    """Return a single-value query map or a safe validation response.

    Flask's ``get`` silently accepts duplicate query keys; that ambiguity is
    dangerous for filters and pagination, so every supplied key is single-use.
    """
    result: dict[str, str] = {}
    for key, values in request.args.lists():
        if key not in allowed or len(values) != 1:
            return None, _error("Invalid query parameters", 400, "QUERY_INVALID")
        result[key] = values[0]
    return result, None


def _positive_page(value: str | None, *, default: int, maximum: int):
    if value is None:
        return default
    # Strict canonical positive decimal: no booleans, signs, whitespace, or
    # leading zero alternate representations.
    if len(value) > len(str(maximum)) or not value.isascii() or not value.isdecimal() or value.startswith("0"):
        return None
    parsed = int(value)
    if parsed < 1 or parsed > maximum:
        return None
    return parsed


def _small_request_body():
    """Bound request bodies before JSON parsing or a disabled delivery action."""
    content_length = request.content_length
    if content_length is not None and content_length > _MAX_BODY_BYTES:
        return _error("Request body is too large", 413, "BODY_TOO_LARGE")
    # Content-Length is optional and client-controlled.  Reading this bounded
    # payload makes the limit real for chunked requests as well.
    raw = request.stream.read(_MAX_BODY_BYTES + 1)
    if len(raw) > _MAX_BODY_BYTES:
        return _error("Request body is too large", 413, "BODY_TOO_LARGE")
    request._cached_data = raw
    return None


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJSONKey(key)
        result[key] = value
    return result


def _strict_json_object():
    """Parse one <=64 KiB JSON object, refusing malformed and duplicate keys."""
    oversized = _small_request_body()
    if oversized:
        return None, oversized
    if request.mimetype != "application/json":
        return None, _error("A JSON object is required", 400, "BODY_INVALID")
    raw = request.get_data(cache=True)
    if not raw:
        return None, _error("A JSON object is required", 400, "BODY_INVALID")
    try:
        data = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateJSONKey, ValueError, RecursionError):
        return None, _error("A valid JSON object is required", 400, "BODY_INVALID")
    if not isinstance(data, dict):
        return None, _error("A JSON object is required", 400, "BODY_INVALID")
    return data, None


def _valid_actor():
    """Return a verified active user with an active, matching tenant.

    Authentication establishes identity; this additional joined ownership check
    is the notification data boundary.  It works in expanded hierarchy tests as
    well as the single-brand launch without accepting an HTTP-selected tenant.
    """
    actor = get_current_user()
    user_id = getattr(actor, "id", None)
    tenant_id = getattr(actor, "tenant_id", None)
    if (
        isinstance(user_id, bool)
        or not isinstance(user_id, int)
        or user_id < 1
        or isinstance(tenant_id, bool)
        or not isinstance(tenant_id, int)
        or tenant_id < 1
        or not getattr(actor, "is_active", False)
        or not getattr(actor, "is_verified", False)
    ):
        return None, _error("Notification access is unavailable", 403, "NOTIFICATION_SCOPE_DENIED")

    with db.session.no_autoflush:
        statement = (
            select(User.id)
            .join(Tenant, Tenant.id == User.tenant_id)
            .where(
                User.id == user_id,
                User.tenant_id == tenant_id,
                User.is_active.is_(True),
                User.is_verified.is_(True),
                Tenant.status == "active",
            )
        )
        valid = db.session.execute(statement).scalar_one_or_none()
    if valid is None:
        return None, _error("Notification access is unavailable", 403, "NOTIFICATION_SCOPE_DENIED")
    return actor, None


def _owner_context(actor):
    """Return only the verified JWT principal binding for user-facing payloads."""
    user_id = getattr(actor, "id", None)
    tenant_id = getattr(actor, "tenant_id", None)
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id < 1:
        raise RuntimeError("Authenticated notification principal has no valid user id")
    if isinstance(tenant_id, bool) or not isinstance(tenant_id, int) or tenant_id < 1:
        tenant_id = None
    return {"user_id": user_id, "tenant_id": tenant_id}


def _customer_response(actor, payload: dict[str, Any]):
    """Attach the server-derived principal receipt to one user API response."""
    payload["owner_context"] = _owner_context(actor)
    return payload


def _owned_notifications(actor, *, include_deleted: bool = False):
    """A personal-only query; even the configured root is never global here."""
    query = (
        db.session.query(Notification)
        .join(User, Notification.user_id == User.id)
        .join(Tenant, Tenant.id == User.tenant_id)
        .filter(
            Notification.user_id == actor.id,
            User.id == actor.id,
            User.tenant_id == actor.tenant_id,
            User.is_active.is_(True),
            User.is_verified.is_(True),
            Tenant.status == "active",
        )
    )
    if not include_deleted:
        query = query.filter(Notification.is_deleted.is_(False))
    return query


def _owned_notification(actor, notification_id: int, *, include_deleted: bool = False):
    with db.session.no_autoflush:
        return _owned_notifications(actor, include_deleted=include_deleted).filter(
            Notification.id == notification_id
        ).one_or_none()


def _notification_dict(notification: Notification, *, include_deletion: bool = False):
    value = notification.to_dict()
    if include_deletion:
        value["is_deleted"] = notification.is_deleted
        value["deleted_at"] = (
            notification.deleted_at.isoformat() if notification.deleted_at else None
        )
    return value


def _parse_notification_filters():
    params, failure = _strict_query({"page", "per_page", "type", "is_read", "priority"})
    if failure:
        return None, failure
    page = _positive_page(params.get("page"), default=1, maximum=1000)
    per_page = _positive_page(params.get("per_page"), default=50, maximum=100)
    if page is None or per_page is None:
        return None, _error("Invalid pagination", 400, "PAGINATION_INVALID")

    notification_type = params.get("type")
    if notification_type is not None and notification_type not in NOTIFICATION_TYPES:
        return None, _error("Invalid notification type", 400, "QUERY_INVALID")
    priority = params.get("priority")
    if priority is not None and priority not in NOTIFICATION_PRIORITIES:
        return None, _error("Invalid notification priority", 400, "QUERY_INVALID")
    is_read = params.get("is_read")
    if is_read is not None:
        if is_read not in {"true", "false"}:
            return None, _error("is_read must be true or false", 400, "QUERY_INVALID")
        is_read = is_read == "true"
    return {
        "page": page,
        "per_page": per_page,
        "type": notification_type,
        "priority": priority,
        "is_read": is_read,
    }, None


def _validate_preference_update(data: dict[str, Any]):
    """Accept only existing preference fields and primitive, explicit values."""
    if not data or set(data) - _ALLOWED_PREFERENCE_TOP_LEVEL:
        return None, _error("Invalid preference fields", 400, "PREFERENCE_INVALID")

    normalized: dict[str, Any] = {}
    for channel in ("in_app", "email"):
        if channel not in data:
            continue
        values = data[channel]
        if not isinstance(values, dict) or not values:
            return None, _error("Invalid preference fields", 400, "PREFERENCE_INVALID")
        if set(values) - set(PREFERENCE_CATEGORIES):
            return None, _error("Invalid preference category", 400, "PREFERENCE_INVALID")
        if any(type(value) is not bool for value in values.values()):
            return None, _error("Preference values must be booleans", 400, "PREFERENCE_INVALID")
        normalized[channel] = values

    if "settings" in data:
        settings = data["settings"]
        if not isinstance(settings, dict) or not settings:
            return None, _error("Invalid preference settings", 400, "PREFERENCE_INVALID")
        if set(settings) - _ALLOWED_PREFERENCE_SETTINGS:
            return None, _error("Invalid preference settings", 400, "PREFERENCE_INVALID")
        if "email_enabled" in settings and type(settings["email_enabled"]) is not bool:
            return None, _error("email_enabled must be a boolean", 400, "PREFERENCE_INVALID")
        if (
            "email_frequency" in settings
            and (
                not isinstance(settings["email_frequency"], str)
                or settings["email_frequency"] not in EMAIL_FREQUENCIES
            )
        ):
            return None, _error("Invalid email_frequency", 400, "PREFERENCE_INVALID")
        normalized["settings"] = settings

    if not normalized:
        return None, _error("Invalid preference fields", 400, "PREFERENCE_INVALID")
    return normalized, None


# ==================== USER ENDPOINTS ====================

@notifications_bp.route("/", methods=["GET"])
@jwt_required
def get_notifications():
    """Return only the authenticated user's non-deleted, tenant-valid inbox."""
    filters, failure = _parse_notification_filters()
    if failure:
        return failure
    try:
        actor, failure = _valid_actor()
        if failure:
            return failure
        with db.session.no_autoflush:
            query = _owned_notifications(actor)
            if filters["type"] is not None:
                query = query.filter(Notification.type == filters["type"])
            if filters["is_read"] is not None:
                query = query.filter(Notification.is_read.is_(filters["is_read"]))
            if filters["priority"] is not None:
                query = query.filter(Notification.priority == filters["priority"])
            total = query.order_by(None).count()
            rows = (
                query.order_by(Notification.created_at.desc(), Notification.id.desc())
                .offset((filters["page"] - 1) * filters["per_page"])
                .limit(filters["per_page"])
                .all()
            )
        return jsonify(_customer_response(actor, {
            "notifications": [_notification_dict(row) for row in rows],
            "total": total,
            "page": filters["page"],
            "per_page": filters["per_page"],
            "pages": (total + filters["per_page"] - 1) // filters["per_page"],
        })), 200
    except Exception:
        logger.exception("Unable to list in-app notifications")
        return _internal_error()


@notifications_bp.route("/unread-count", methods=["GET"])
@jwt_required
def get_unread_count():
    """Return a personal unread count, excluding soft-deleted records."""
    _, failure = _strict_query(set())
    if failure:
        return failure
    try:
        actor, failure = _valid_actor()
        if failure:
            return failure
        with db.session.no_autoflush:
            count = _owned_notifications(actor).filter(
                Notification.is_read.is_(False)
            ).count()
        return jsonify(_customer_response(actor, {"count": count})), 200
    except Exception:
        logger.exception("Unable to count in-app notifications")
        return _internal_error()


@notifications_bp.route("/<int:notification_id>/read", methods=["POST"])
@jwt_required
def mark_as_read(notification_id):
    """Mark one owned non-deleted notification as read."""
    oversized = _small_request_body()
    if oversized:
        return oversized
    try:
        actor, failure = _valid_actor()
        if failure:
            return failure
        notification = _owned_notification(actor, notification_id)
        if notification is None:
            return _error("Notification not found", 404, "NOTIFICATION_NOT_FOUND")
        changed = InAppNotificationService.mark_read(notification)
        if changed:
            db.session.commit()
        return jsonify(_customer_response(actor, {
            "message": "Notification marked as read",
            "notification": _notification_dict(notification),
        })), 200
    except Exception:
        db.session.rollback()
        logger.exception("Unable to mark in-app notification as read")
        return _internal_error()


@notifications_bp.route("/read-all", methods=["POST"])
@jwt_required
def mark_all_as_read():
    """Atomically mark every unread non-deleted notification in the actor's inbox."""
    oversized = _small_request_body()
    if oversized:
        return oversized
    try:
        actor, failure = _valid_actor()
        if failure:
            return failure
        now = datetime.utcnow()
        # This update is personal by construction.  _valid_actor above joins the
        # actor to an active tenant; no hierarchy/global query can widen user_id.
        count = (
            db.session.query(Notification)
            .filter(
                Notification.user_id == actor.id,
                Notification.is_deleted.is_(False),
                Notification.is_read.is_(False),
            )
            .update(
                {Notification.is_read: True, Notification.read_at: now},
                synchronize_session=False,
            )
        )
        db.session.commit()
        return jsonify(_customer_response(actor, {
            "message": "Notifications marked as read",
            "count": count,
        })), 200
    except Exception:
        db.session.rollback()
        logger.exception("Unable to mark all in-app notifications as read")
        return _internal_error()


@notifications_bp.route("/<int:notification_id>", methods=["DELETE"])
@jwt_required
def delete_notification(notification_id):
    """Soft-delete one owned notification without leaking another user's record."""
    oversized = _small_request_body()
    if oversized:
        return oversized
    try:
        actor, failure = _valid_actor()
        if failure:
            return failure
        notification = _owned_notification(actor, notification_id)
        if notification is None:
            return _error("Notification not found", 404, "NOTIFICATION_NOT_FOUND")
        InAppNotificationService.soft_delete(notification)
        db.session.commit()
        return jsonify(_customer_response(actor, {
            "message": "Notification deleted",
            "notification": _notification_dict(notification, include_deletion=True),
        })), 200
    except Exception:
        db.session.rollback()
        logger.exception("Unable to delete in-app notification")
        return _internal_error()


# ==================== PREFERENCE ENDPOINTS ====================

@notifications_bp.route("/preferences", methods=["GET"])
@jwt_required
def get_preferences():
    """Read defaults without creating a preference row or flushing the session."""
    _, failure = _strict_query(set())
    if failure:
        return failure
    try:
        actor, failure = _valid_actor()
        if failure:
            return failure
        prefs = InAppNotificationService.get_preferences_read_only(actor.id)
        return jsonify(_customer_response(
            actor,
            InAppNotificationService.serialize_preferences(prefs, user_id=actor.id),
        )), 200
    except Exception:
        logger.exception("Unable to read notification preferences")
        return _internal_error()


@notifications_bp.route("/preferences", methods=["PUT"])
@jwt_required
def update_preferences():
    """Validate and atomically persist only schema-backed preference fields."""
    data, failure = _strict_json_object()
    if failure:
        return failure
    changes, failure = _validate_preference_update(data)
    if failure:
        return failure
    try:
        actor, failure = _valid_actor()
        if failure:
            return failure
        prefs = InAppNotificationService.update_preferences(
            user_id=actor.id, changes=changes
        )
        return jsonify(_customer_response(actor, {
            "message": "Preferences updated successfully",
            "preferences": InAppNotificationService.serialize_preferences(
                prefs, user_id=actor.id
            ),
        })), 200
    except Exception:
        # update_preferences owns its single rollback; do not expose database
        # details or invoke the legacy auto-committing model helper.
        logger.exception("Unable to update notification preferences")
        return _internal_error()


# ==================== ADMIN ENDPOINTS ====================

@notifications_bp.route("/admin/send", methods=["POST"])
@admin_required
def admin_send_notification():
    """Mass dispatch is intentionally unavailable until a durable bounded worker exists."""
    oversized = _small_request_body()
    if oversized:
        return oversized
    return _error(
        "Mass notification delivery is not configured", 503, "DELIVERY_NOT_CONFIGURED"
    )


@notifications_bp.route("/admin/broadcast", methods=["POST"])
@admin_required
def admin_broadcast_notification():
    """Broadcast remains disabled rather than looping unboundedly in a request."""
    oversized = _small_request_body()
    if oversized:
        return oversized
    return _error(
        "Mass notification delivery is not configured", 503, "DELIVERY_NOT_CONFIGURED"
    )


def _stats_notifications(actor):
    """Visible notification query for stats: root global, others CRM downline only."""
    query = (
        db.session.query(Notification)
        .join(User, Notification.user_id == User.id)
        .join(Tenant, Tenant.id == User.tenant_id)
        .filter(
            Notification.is_deleted.is_(False),
            User.is_active.is_(True),
            User.is_verified.is_(True),
            Tenant.status == "active",
        )
    )
    if not platform_root_scope(actor):
        # CRM's selector carries the reviewed tenant + self/downline predicate.
        visible_user_ids = crm_scope.scoped_users(actor).with_entities(User.id).subquery()
        query = query.filter(Notification.user_id.in_(select(visible_user_ids.c.id)))
    return query


@notifications_bp.route("/admin/stats", methods=["GET"])
@admin_required
def admin_get_stats():
    """Return stats scoped to approved global-root or CRM tenant/downline visibility."""
    _, failure = _strict_query(set())
    if failure:
        return failure
    try:
        actor, failure = _valid_actor()
        if failure:
            return failure
        with db.session.no_autoflush:
            query = _stats_notifications(actor)
            total = query.order_by(None).count()
            unread = query.filter(Notification.is_read.is_(False)).order_by(None).count()
            by_type = (
                query.with_entities(Notification.type, func.count(Notification.id))
                .group_by(Notification.type)
                .all()
            )
            by_priority = (
                query.with_entities(Notification.priority, func.count(Notification.id))
                .group_by(Notification.priority)
                .all()
            )
            recent = query.filter(
                Notification.created_at >= datetime.utcnow() - timedelta(days=1)
            ).order_by(None).count()
        return jsonify({
            "total": total,
            "unread": unread,
            "read": total - unread,
            "recent_24h": recent,
            "by_type": {name: count for name, count in by_type},
            "by_priority": {name: count for name, count in by_priority},
        }), 200
    except Exception:
        logger.exception("Unable to calculate in-app notification statistics")
        return _internal_error()
