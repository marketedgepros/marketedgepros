"""Narrow, persisted UI-4 tenant contact settings boundary.

This service deliberately has no global configuration or payment-provider configuration.
Those categories lack a persisted model and approved write contract in this repository.
Only the configured platform root may read or update the tenant identified by that
root's own authenticated ``tenant_id``; callers never supply a target tenant.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select, text

from src.database import db
from src.models.tenant import Tenant
from src.utils.hierarchy_scoping import platform_root_scope


_MAX_REQUEST_BYTES = 2048
_MAX_NAME_LENGTH = 255
_MAX_EMAIL_LENGTH = 255
_MAX_PHONE_LENGTH = 20
_ALLOWED_TENANT_FIELDS = frozenset({"name", "contact_email", "contact_phone"})
_CONTROL_CHARACTERS = frozenset(chr(value) for value in range(0, 32)) | {chr(127)}


class AdminClosureSettingsInvalid(ValueError):
    """The request is not the small canonical tenant-settings payload."""


class AdminClosureSettingsScopeRequired(PermissionError):
    """The authenticated actor is not the configured active platform root."""


class AdminClosureSettingsNotConfigured(LookupError):
    """The root has no tenant row that can persist the supported fields."""


class AdminClosureSettingsWriteFailed(RuntimeError):
    """The transaction did not commit, so no settings acknowledgement is returned."""


def _positive_identifier(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _has_control_characters(value: str) -> bool:
    return any(character in _CONTROL_CHARACTERS for character in value)


def _require_text(value: object, field: str, maximum: int, *, nullable: bool) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or len(value) > maximum or _has_control_characters(value):
        raise AdminClosureSettingsInvalid()
    if not nullable and len(value) < 1:
        raise AdminClosureSettingsInvalid()
    return value


def _owner_context(actor: object) -> dict[str, int]:
    """Authorize root and its explicit tenant before any resource SQL."""
    user_id = getattr(actor, "id", None)
    tenant_id = getattr(actor, "tenant_id", None)
    if not (
        _positive_identifier(user_id)
        and _positive_identifier(tenant_id)
        and platform_root_scope(actor)
    ):
        raise AdminClosureSettingsScopeRequired()
    return {"user_id": user_id, "tenant_id": tenant_id}


def _set_statement_timeout() -> None:
    """Bound PostgreSQL work without emitting unsupported SQLite syntax."""
    bind = db.session.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        db.session.execute(text("SET LOCAL statement_timeout = 1500"))


def _tenant_projection(tenant: Tenant, owner: dict[str, int]) -> dict[str, object]:
    """Return only the three confirmed Tenant columns; never expose JSON/settings secrets."""
    return {
        "owner_context": owner,
        "scope": {"kind": "tenant", "tenant_id": owner["tenant_id"]},
        "tenant_settings": {
            "name": _require_text(tenant.name, "name", _MAX_NAME_LENGTH, nullable=False),
            "contact_email": _require_text(tenant.contact_email, "contact_email", _MAX_EMAIL_LENGTH, nullable=True),
            "contact_phone": _require_text(tenant.contact_phone, "contact_phone", _MAX_PHONE_LENGTH, nullable=True),
        },
        "capabilities": {
            "tenant_contact": "persisted",
            "global_system": "unavailable_no_persistence",
            "payment_providers": "unavailable_no_persistence",
        },
    }


def _tenant_for_owner(owner: dict[str, int], *, lock: bool) -> Tenant:
    statement = select(Tenant).where(Tenant.id == owner["tenant_id"]).execution_options(autoflush=False)
    if lock:
        statement = statement.with_for_update()
    tenant = db.session.execute(statement).scalar_one_or_none()
    if tenant is None:
        raise AdminClosureSettingsNotConfigured()
    return tenant


class AdminClosureSettingsService:
    """Single service implementation for the canonical ``/admin/settings`` route."""

    max_request_bytes = _MAX_REQUEST_BYTES

    @staticmethod
    def parse_query(arguments: Any) -> None:
        """The settings endpoint is parameterless; reject aliases and duplicates before SQL."""
        if any(True for _name in arguments.keys()):
            raise AdminClosureSettingsInvalid()

    @staticmethod
    def parse_update_payload(payload: Any) -> dict[str, str | None]:
        """Accept exactly the supported Tenant contact columns, all typed and bounded."""
        if not isinstance(payload, dict) or set(payload) != {"tenant_settings"}:
            raise AdminClosureSettingsInvalid()
        values = payload["tenant_settings"]
        if not isinstance(values, dict) or set(values) != _ALLOWED_TENANT_FIELDS:
            raise AdminClosureSettingsInvalid()
        return {
            "name": _require_text(values["name"], "name", _MAX_NAME_LENGTH, nullable=False),
            "contact_email": _require_text(values["contact_email"], "contact_email", _MAX_EMAIL_LENGTH, nullable=True),
            "contact_phone": _require_text(values["contact_phone"], "contact_phone", _MAX_PHONE_LENGTH, nullable=True),
        }

    @classmethod
    def read(cls, actor: object) -> dict[str, object]:
        owner = _owner_context(actor)
        with db.session.no_autoflush:
            _set_statement_timeout()
            tenant = _tenant_for_owner(owner, lock=False)
            return _tenant_projection(tenant, owner)

    @classmethod
    def update(cls, actor: object, values: dict[str, str | None]) -> dict[str, object]:
        owner = _owner_context(actor)
        # Re-parse trusted direct callers so they cannot bypass the route's strict shape.
        normalized = cls.parse_update_payload({"tenant_settings": values})
        try:
            with db.session.no_autoflush:
                _set_statement_timeout()
                tenant = _tenant_for_owner(owner, lock=True)
                tenant.name = normalized["name"]
                tenant.contact_email = normalized["contact_email"]
                tenant.contact_phone = normalized["contact_phone"]
                acknowledgement = _tenant_projection(tenant, owner)
            db.session.commit()
            return acknowledgement
        except (AdminClosureSettingsInvalid, AdminClosureSettingsNotConfigured):
            db.session.rollback()
            raise
        except Exception as exc:
            db.session.rollback()
            raise AdminClosureSettingsWriteFailed() from exc
