"""Authorization-aware caching helpers for tenant-scoped analytics routes."""
from __future__ import annotations

from functools import wraps
import hashlib
import json
import logging
import re
from typing import Callable

from flask import jsonify, request, make_response, current_app

from src import cache

logger = logging.getLogger(__name__)

_MAX_QUERY_STRING_BYTES = 256
_DAY_PATTERN = re.compile(r"^[0-9]+$")


class AnalyticsRequestValidationError(ValueError):
    """Raised when an analytics endpoint receives unsupported cache filters."""


def _reject_unexpected_query_parameters(allowed: set[str]) -> None:
    """Reject parameters the endpoint does not implement instead of keying on them."""
    if len(request.query_string) > _MAX_QUERY_STRING_BYTES:
        raise AnalyticsRequestValidationError("Query string is too long")

    unexpected = set(request.args.keys()) - allowed
    if unexpected:
        raise AnalyticsRequestValidationError("Unsupported analytics query parameter")


def bounded_days_filter() -> dict[str, int]:
    """Return the canonical, bounded ``days`` filter used by time-series routes."""
    _reject_unexpected_query_parameters({"days"})
    values = request.args.getlist("days")
    if not values:
        return {"days": 30}
    if len(values) != 1 or not _DAY_PATTERN.fullmatch(values[0]):
        raise AnalyticsRequestValidationError("Days must be an integer between 1 and 365")

    days = int(values[0])
    if not 1 <= days <= 365:
        raise AnalyticsRequestValidationError("Days must be between 1 and 365")
    return {"days": days}


def no_query_filters() -> dict[str, object]:
    """Assert that an aggregate endpoint is requested without ignored filters."""
    _reject_unexpected_query_parameters(set())
    return {}


def _cache_key(current_user, filters: dict[str, object]) -> str:
    """Build a non-reversible cache key from the authenticated authorization context."""
    user_id = getattr(current_user, "id", None)
    tenant_id = getattr(current_user, "tenant_id", None)
    role = getattr(current_user, "role", None)
    if user_id is None or tenant_id is None or not role:
        # The route also has tenant_required, but never allow a direct use of this
        # wrapper to turn a missing authorization context into a shared cache key.
        raise PermissionError("Authenticated user with tenant and role is required")

    key_material = {
        "version": 1,
        "endpoint": request.endpoint,
        "method": request.method,
        "user_id": int(user_id),
        "tenant_id": int(tenant_id),
        "role": str(role),
        "tree_path": getattr(current_user, "tree_path", None),
        "parent_id": getattr(current_user, "parent_id", None),
        "token_version": getattr(current_user, "token_version", None),
        "filters": filters,
    }
    encoded = json.dumps(key_material, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "analytics:v1:" + hashlib.sha256(encoded).hexdigest()


def _response_status(response) -> int | None:
    """Extract a Flask view status without forcing response construction twice."""
    if isinstance(response, tuple):
        if len(response) < 2:
            return 200
        status = response[1]
        if isinstance(status, int):
            return status
        return getattr(status, "code", None)
    return getattr(response, "status_code", 200)


def analytics_cached(*, filters: Callable[[], dict[str, object]], timeout: int = 300):
    """Cache only authorized successful analytics responses under an actor-specific key.

    This decorator must be placed *inside* token/admin/tenant decorators so those
    checks finish before it parses filters or calls the cache backend.
    """
    def decorator(view):
        @wraps(view)
        def decorated(current_user, *args, **kwargs):
            try:
                canonical_filters = filters()
            except AnalyticsRequestValidationError as exc:
                return jsonify({"error": str(exc)}), 400

            try:
                key = _cache_key(current_user, canonical_filters)
            except (PermissionError, TypeError, ValueError):
                return jsonify({"error": "User must belong to a tenant"}), 403

            try:
                cached_response = cache.get(key)
            except Exception:
                logger.warning("Analytics cache read failed", exc_info=True)
                cached_response = None
            if isinstance(cached_response, dict) and cached_response.get('format') == 2:
                restored = current_app.response_class(cached_response['body'], status=cached_response['status'])
                for name, value in cached_response['headers']:
                    restored.headers[name] = value
                return restored

            response = view(current_user, *args, **kwargs)
            status = _response_status(response)
            if status is not None and 200 <= status < 300:
                try:
                    concrete = make_response(response)
                    payload = {
                        'format': 2,
                        'body': concrete.get_data(),
                        'status': concrete.status_code,
                        'headers': [(name, value) for name, value in concrete.headers.items()
                                    if name.lower() in {'content-type', 'cache-control'}],
                    }
                    cache.set(key, payload, timeout=timeout)
                except Exception:
                    logger.warning("Analytics cache write failed", exc_info=True)
            return response

        return decorated
    return decorator
