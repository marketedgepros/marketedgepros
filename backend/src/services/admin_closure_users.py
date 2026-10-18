"""Tenant- and hierarchy-scoped user-management contracts for UI-4 closure.

The service is intentionally the sole implementation for the existing canonical
``/admin/users`` routes.  It returns only the operational user fields required by
that screen, refuses malformed scopes and inputs before resource SQL, and keeps
password/session/provider data out of every projection.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from math import ceil
from typing import Any

from flask import current_app
from sqlalchemy import and_, func, or_, select, text, true

from src.database import db
from src.models.payment import Payment
from src.models.trading_program import Challenge, TradingProgram
from src.models.user import PasswordResetToken, User
from src.utils.hierarchy_scoping import (
    complete_hierarchy_scope,
    platform_root_scope,
    tenant_hierarchy_scope,
    without_hierarchy_scope,
)
from src.utils.validators import validate_email_format, validate_password_strength


_MAX_PAGE = 10_000
_MAX_PER_PAGE = 50
_MAX_OFFSET = 10_000
_MAX_SEARCH = 100
_MAX_TREE_NODES = 500
_MAX_DETAIL_ROWS = 50
_MAX_INTEGER_DIGITS = 10
_ROLES = frozenset({"supermaster", "master", "affiliate", "trader", "guest"})
_CREATABLE_ROLES = frozenset({"supermaster", "master", "affiliate", "trader"})
_KYC_STATUSES = frozenset({"not_submitted", "pending", "approved", "rejected", "incomplete", "verified", "unverified"})
_CHALLENGE_STATUSES = frozenset({"pending", "active", "completed", "passed", "failed", "funded", "cancelled"})
_PAYMENT_STATUSES = frozenset({"pending", "completed", "failed", "refunded"})
_PAYMENT_PURPOSES = frozenset({"challenge_purchase", "withdrawal", "refund"})


class AdminClosureUsersQueryInvalid(ValueError):
    """A list or hierarchy request is malformed, duplicate, or out of bounds."""


class AdminClosureUsersScopeRequired(PermissionError):
    """The authenticated principal has no explicit permitted hierarchy scope."""


class AdminClosureUsersNotFound(LookupError):
    """The target is not visible inside the authenticated principal's scope."""


class AdminClosureUsersValidationError(ValueError):
    """A write payload is not the strict supported user-management contract."""


class AdminClosureUsersPermissionDenied(PermissionError):
    """A scoped target exists but the requested account action is not permitted."""


class AdminClosureUsersProductNotConfigured(ValueError):
    """The existing MVP affiliate activation boundary remains closed."""


class AdminClosureUsersTreeTooLarge(ValueError):
    """The bounded hierarchy view cannot safely return the requested tree."""


@dataclass(frozen=True)
class AdminClosureUsersListArguments:
    page: int
    per_page: int
    offset: int
    role: str | None
    status: str | None
    search: str | None


def _positive_identifier(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _owner_context(actor: object) -> dict[str, int]:
    user_id = getattr(actor, "id", None)
    tenant_id = getattr(actor, "tenant_id", None)
    if not (_positive_identifier(user_id) and _positive_identifier(tenant_id)):
        raise AdminClosureUsersScopeRequired()
    return {"user_id": user_id, "tenant_id": tenant_id}


def _require_scope(actor: object) -> dict[str, int]:
    owner = _owner_context(actor)
    if not complete_hierarchy_scope(actor):
        raise AdminClosureUsersScopeRequired()
    if not (platform_root_scope(actor) or tenant_hierarchy_scope(actor)):
        raise AdminClosureUsersScopeRequired()
    return owner


def _set_statement_timeout() -> None:
    """Keep PostgreSQL reads bounded while remaining compatible with SQLite tests."""
    bind = db.session.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        db.session.execute(text("SET LOCAL statement_timeout = 1500"))


def _canonical_integer(raw: object, *, minimum: int, maximum: int) -> int:
    if (
        not isinstance(raw, str)
        or not raw
        or len(raw) > _MAX_INTEGER_DIGITS
        or not raw.isascii()
        or not raw.isdecimal()
    ):
        raise AdminClosureUsersQueryInvalid()
    value = int(raw)
    if not minimum <= value <= maximum or str(value) != raw:
        raise AdminClosureUsersQueryInvalid()
    return value


def _parse_list_query(arguments: Any) -> AdminClosureUsersListArguments:
    allowed = frozenset({"page", "per_page", "role", "status", "search"})
    for name in arguments.keys():
        if name not in allowed or len(arguments.getlist(name)) != 1:
            raise AdminClosureUsersQueryInvalid()
    page_values = arguments.getlist("page")
    per_page_values = arguments.getlist("per_page")
    page = 1 if not page_values else _canonical_integer(page_values[0], minimum=1, maximum=_MAX_PAGE)
    per_page = 20 if not per_page_values else _canonical_integer(per_page_values[0], minimum=1, maximum=_MAX_PER_PAGE)
    offset = (page - 1) * per_page
    if offset > _MAX_OFFSET:
        raise AdminClosureUsersQueryInvalid()
    role_values = arguments.getlist("role")
    status_values = arguments.getlist("status")
    search_values = arguments.getlist("search")
    role = None if not role_values else role_values[0]
    status = None if not status_values else status_values[0]
    search = None if not search_values else search_values[0]
    if role is not None and role not in _ROLES:
        raise AdminClosureUsersQueryInvalid()
    if status is not None and status not in {"active", "inactive"}:
        raise AdminClosureUsersQueryInvalid()
    if search is not None:
        if (
            not isinstance(search, str)
            or not search
            or len(search) > _MAX_SEARCH
            or any(ord(character) < 32 for character in search)
        ):
            raise AdminClosureUsersQueryInvalid()
    return AdminClosureUsersListArguments(page, per_page, offset, role, status, search)


def _parse_parameterless_query(arguments: Any) -> None:
    if any(True for _name in arguments.keys()):
        raise AdminClosureUsersQueryInvalid()


def _allowed_user_ids(actor: object):
    """Build the only explicit platform-root or tenant/downline user predicate."""
    _require_scope(actor)
    if platform_root_scope(actor):
        query = db.session.query(User.id).filter(User.tenant_id.is_not(None), User.tenant_id > 0)
    else:
        condition = User.hierarchy_filter_for_entity(actor)
        if condition is None:
            raise AdminClosureUsersScopeRequired()
        query = db.session.query(User.id).filter(condition, User.tenant_id == actor.tenant_id)
    return query.execution_options(skip_hierarchy_scope=True, autoflush=False).distinct().subquery(
        "admin_closure_users_allowed"
    )


def _scoped_users(actor: object, allowed_users):
    return (
        db.session.query(User)
        .join(allowed_users, User.id == allowed_users.c.id)
        .filter(User.tenant_id.is_not(None), User.tenant_id > 0)
        .execution_options(skip_hierarchy_scope=True, autoflush=False)
    )


def _safe_code(value: object, allowed: frozenset[str]) -> str | None:
    return value if isinstance(value, str) and value in allowed else None


def _safe_text(value: object, maximum: int) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        return None
    return value


def _timestamp(value: object) -> str | None:
    return value.isoformat() + "Z" if isinstance(value, datetime) else None


def _decimal_string(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return format(decimal_value, "f") if decimal_value.is_finite() else None


def _currency(value: object) -> str | None:
    if not isinstance(value, str) or len(value) != 3 or not value.isascii():
        return None
    return value if value.isalpha() and value == value.upper() else None


def _list_projection(row: Any) -> dict[str, object]:
    return {
        "id": row.id if _positive_identifier(row.id) else None,
        "first_name": _safe_text(row.first_name, 100),
        "last_name": _safe_text(row.last_name, 100),
        "email": _safe_text(row.email, 255),
        "role": _safe_code(row.role, _ROLES),
        "is_active": row.is_active if isinstance(row.is_active, bool) else None,
        "kyc_status": _safe_code(row.kyc_status, _KYC_STATUSES),
        "created_at": _timestamp(row.created_at),
        "last_login_at": _timestamp(row.last_login_at),
    }


def _detail_projection(user: User) -> dict[str, object]:
    return {
        "id": user.id if _positive_identifier(user.id) else None,
        "first_name": _safe_text(user.first_name, 100),
        "last_name": _safe_text(user.last_name, 100),
        "email": _safe_text(user.email, 255),
        "phone": _safe_text(user.phone, 20),
        "country_code": _safe_text(user.country_code, 20),
        "role": _safe_code(user.role, _ROLES),
        "is_active": user.is_active if isinstance(user.is_active, bool) else None,
        "kyc_status": _safe_code(user.kyc_status, _KYC_STATUSES),
        "is_verified": user.is_verified if isinstance(user.is_verified, bool) else None,
        "two_factor_enabled": user.two_factor_enabled if isinstance(user.two_factor_enabled, bool) else None,
        "created_at": _timestamp(user.created_at),
        "updated_at": _timestamp(user.updated_at),
        "last_login_at": _timestamp(user.last_login_at),
    }


def _pagination(arguments: AdminClosureUsersListArguments, total: int) -> dict[str, int]:
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise RuntimeError("user list returned an invalid total")
    return {
        "page": arguments.page,
        "per_page": arguments.per_page,
        "total": total,
        "pages": ceil(total / arguments.per_page) if total else 0,
    }


def _snapshot_list(query, arguments: AdminClosureUsersListArguments) -> tuple[int, list[Any]]:
    """Read count and rows from one CTE-backed statement snapshot."""
    scoped = query.order_by(None).cte("admin_closure_users_scoped")
    scoped = scoped.prefix_with("MATERIALIZED", dialect="postgresql")
    total = select(func.count().label("_total")).select_from(scoped).cte("admin_closure_users_total")
    page = (
        select(*scoped.c)
        .order_by(scoped.c.created_at.desc().nullslast(), scoped.c.id.desc())
        .limit(arguments.per_page)
        .offset(arguments.offset)
        .cte("admin_closure_users_page")
    )
    statement = (
        select(total.c._total, *page.c)
        .select_from(total.outerjoin(page, true()))
        .execution_options(skip_hierarchy_scope=True, autoflush=False)
    )
    rows = db.session.execute(statement).all()
    if not rows:
        raise RuntimeError("user list snapshot omitted its total")
    total_value = rows[0]._mapping["_total"]
    if isinstance(total_value, bool) or not isinstance(total_value, int) or total_value < 0:
        raise RuntimeError("user list snapshot total was invalid")
    return total_value, [row for row in rows if row._mapping["id"] is not None]


def _target(actor: object, user_id: object, *, lock: bool = False) -> User:
    if not _positive_identifier(user_id):
        raise AdminClosureUsersNotFound()
    allowed = _allowed_user_ids(actor)
    query = _scoped_users(actor, allowed).filter(User.id == user_id)
    if lock:
        _set_statement_timeout()
        if db.session.get_bind().dialect.name == "postgresql":
            db.session.execute(text("SET LOCAL lock_timeout = 1500"))
        # Lock only the actual User relation, not the DISTINCT authorization
        # subquery. PostgreSQL cannot lock that derived relation.
        query = query.with_for_update(of=User).populate_existing()
    user = query.one_or_none()
    if user is None:
        raise AdminClosureUsersNotFound()
    return user


def _require_object(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise AdminClosureUsersValidationError("A JSON object is required.")
    return payload


def _require_exact_fields(payload: dict[str, object], allowed: frozenset[str], required: frozenset[str]) -> None:
    actual = set(payload)
    unsupported = actual - allowed
    missing = required - actual
    if unsupported or missing:
        raise AdminClosureUsersValidationError("The request contains unsupported or missing account fields.")


def _required_text(payload: dict[str, object], field: str, maximum: int) -> str:
    value = payload.get(field)
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value.strip()) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise AdminClosureUsersValidationError(f"{field} is invalid.")
    return value.strip()


def _optional_text(payload: dict[str, object], field: str, maximum: int) -> str | None:
    if field not in payload:
        return None
    value = payload[field]
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or len(value.strip()) > maximum
        or any(ord(character) < 32 for character in value)
    ):
        raise AdminClosureUsersValidationError(f"{field} is invalid.")
    return value.strip() or None


def _required_role(payload: dict[str, object]) -> str:
    value = payload.get("role")
    if not isinstance(value, str) or value not in _CREATABLE_ROLES:
        raise AdminClosureUsersValidationError("role is invalid.")
    return value


def _existing_role(payload: dict[str, object]) -> str:
    value = payload.get("role")
    if not isinstance(value, str) or value not in _ROLES:
        raise AdminClosureUsersValidationError("role is invalid.")
    return value


def _create_input(payload: object) -> dict[str, object]:
    data = _require_object(payload)
    allowed = frozenset({"email", "password", "first_name", "last_name", "phone", "country_code", "role"})
    _require_exact_fields(data, allowed, frozenset({"email", "password", "first_name", "last_name", "role"}))
    email = _required_text(data, "email", 255)
    valid, _result = validate_email_format(email)
    if not valid:
        raise AdminClosureUsersValidationError("email is invalid.")
    password = _required_text(data, "password", 512)
    valid_password, password_error = validate_password_strength(password)
    if not valid_password:
        raise AdminClosureUsersValidationError(password_error or "password is invalid.")
    return {
        "email": email,
        "password": password,
        "first_name": _required_text(data, "first_name", 100),
        "last_name": _required_text(data, "last_name", 100),
        "phone": _optional_text(data, "phone", 20),
        # The persisted model is String(2); do not silently truncate a caller value.
        "country_code": _optional_text(data, "country_code", 2),
        "role": _required_role(data),
    }


def _update_input(payload: object) -> dict[str, object]:
    data = _require_object(payload)
    allowed = frozenset({"first_name", "last_name", "phone", "country_code", "role", "is_active"})
    _require_exact_fields(data, allowed, frozenset())
    if not data:
        raise AdminClosureUsersValidationError("At least one supported account field is required.")
    result: dict[str, object] = {}
    if "first_name" in data:
        result["first_name"] = _required_text(data, "first_name", 100)
    if "last_name" in data:
        result["last_name"] = _required_text(data, "last_name", 100)
    if "phone" in data:
        result["phone"] = _optional_text(data, "phone", 20)
    if "country_code" in data:
        result["country_code"] = _optional_text(data, "country_code", 2)
    if "role" in data:
        result["role"] = _existing_role(data)
    if "is_active" in data:
        if not isinstance(data["is_active"], bool):
            raise AdminClosureUsersValidationError("is_active is invalid.")
        result["is_active"] = data["is_active"]
    return result


def _password_input(payload: object) -> str:
    data = _require_object(payload)
    _require_exact_fields(data, frozenset({"new_password"}), frozenset({"new_password"}))
    password = _required_text(data, "new_password", 512)
    valid_password, password_error = validate_password_strength(password)
    if not valid_password:
        raise AdminClosureUsersValidationError(password_error or "new_password is invalid.")
    return password


def _write_result(owner: dict[str, int], *, action: str, message: str, user: User) -> dict[str, object]:
    return {
        "owner_context": owner,
        "action": action,
        "message": message,
        "user": {
            "id": user.id if _positive_identifier(user.id) else None,
            "role": _safe_code(user.role, _ROLES),
            "is_active": user.is_active if isinstance(user.is_active, bool) else None,
        },
    }


class AdminClosureUsersService:
    """Strict contracts for the existing admin user-management API endpoints."""

    @staticmethod
    def parse_list_query(arguments: Any) -> AdminClosureUsersListArguments:
        return _parse_list_query(arguments)

    @staticmethod
    def parse_hierarchy_query(arguments: Any) -> None:
        _parse_parameterless_query(arguments)

    @classmethod
    def list_users(cls, actor: object, arguments: AdminClosureUsersListArguments) -> dict[str, object]:
        owner = _require_scope(actor)
        if not isinstance(arguments, AdminClosureUsersListArguments):
            raise AdminClosureUsersQueryInvalid()
        with db.session.no_autoflush:
            allowed = _allowed_user_ids(actor)
            _set_statement_timeout()
            query = (
                db.session.query(
                    User.id.label("id"), User.first_name.label("first_name"), User.last_name.label("last_name"),
                    User.email.label("email"), User.role.label("role"), User.is_active.label("is_active"),
                    User.kyc_status.label("kyc_status"), User.created_at.label("created_at"),
                    User.last_login_at.label("last_login_at"),
                )
                .join(allowed, User.id == allowed.c.id)
                .filter(User.tenant_id.is_not(None), User.tenant_id > 0)
                .execution_options(skip_hierarchy_scope=True, autoflush=False)
            )
            if arguments.role is not None:
                query = query.filter(User.role == arguments.role)
            if arguments.status is not None:
                query = query.filter(User.is_active.is_(arguments.status == "active"))
            if arguments.search is not None:
                pattern = f"%{arguments.search}%"
                query = query.filter(or_(
                    User.email.ilike(pattern), User.first_name.ilike(pattern), User.last_name.ilike(pattern),
                ))
            total, rows = _snapshot_list(query, arguments)
        users = [_list_projection(row) for row in rows]
        if any(user["id"] is None for user in users):
            raise RuntimeError("user list contained an invalid identifier")
        return {
            "owner_context": owner,
            "users": users,
            "pagination": _pagination(arguments, total),
            "filters": {"role": arguments.role, "status": arguments.status, "search": arguments.search},
        }

    @classmethod
    def hierarchy(cls, actor: object) -> dict[str, object]:
        owner = _require_scope(actor)
        with db.session.no_autoflush:
            allowed = _allowed_user_ids(actor)
            _set_statement_timeout()
            rows = (
                _scoped_users(actor, allowed)
                .order_by(User.tree_path.asc().nullslast(), User.id.asc())
                .limit(_MAX_TREE_NODES + 1)
                .all()
            )
        if len(rows) > _MAX_TREE_NODES:
            raise AdminClosureUsersTreeTooLarge()
        nodes: dict[int, dict[str, object]] = {}
        for user in rows:
            if not _positive_identifier(user.id):
                raise RuntimeError("hierarchy returned an invalid identifier")
            item = _list_projection(user)
            nodes[user.id] = {**item, "children": []}
        roots: list[dict[str, object]] = []
        for user in rows:
            node = nodes[user.id]
            parent_id = user.parent_id if _positive_identifier(user.parent_id) else None
            if parent_id is not None and parent_id in nodes:
                nodes[parent_id]["children"].append(node)
            else:
                roots.append(node)
        return {"owner_context": owner, "users": roots, "total_users": len(rows)}

    @classmethod
    def get_user(cls, actor: object, user_id: int) -> dict[str, object]:
        owner = _require_scope(actor)
        with db.session.no_autoflush:
            _set_statement_timeout()
            user = _target(actor, user_id)
            result = _detail_projection(user)
        if result["id"] is None:
            raise RuntimeError("user detail contained an invalid identifier")
        return {"owner_context": owner, "user": result}

    @classmethod
    def full_details(cls, actor: object, user_id: int) -> dict[str, object]:
        owner = _require_scope(actor)
        with db.session.no_autoflush:
            _set_statement_timeout()
            user = _target(actor, user_id)
            details = _detail_projection(user)
            downline_rows = (
                db.session.query(
                    User.id.label("id"), User.first_name.label("first_name"), User.last_name.label("last_name"),
                    User.email.label("email"), User.role.label("role"), User.is_active.label("is_active"),
                    User.created_at.label("created_at"),
                )
                .filter(User.parent_id == user.id, User.tenant_id == user.tenant_id)
                .order_by(User.created_at.desc().nullslast(), User.id.desc())
                .limit(_MAX_DETAIL_ROWS + 1)
                .execution_options(skip_hierarchy_scope=True, autoflush=False)
                .all()
            )
            challenge_rows = (
                db.session.query(
                    Challenge.id.label("id"), TradingProgram.name.label("program_name"), Challenge.status.label("status"),
                    Challenge.initial_balance.label("initial_balance"), Challenge.current_balance.label("current_balance"),
                    Challenge.total_profit.label("total_profit"), Challenge.created_at.label("created_at"),
                )
                .join(TradingProgram, Challenge.program_id == TradingProgram.id)
                .filter(Challenge.user_id == user.id, TradingProgram.tenant_id == user.tenant_id)
                .order_by(Challenge.created_at.desc().nullslast(), Challenge.id.desc())
                .limit(_MAX_DETAIL_ROWS + 1)
                .execution_options(skip_hierarchy_scope=True, autoflush=False)
                .all()
            )
            payment_rows = (
                db.session.query(
                    Payment.id.label("id"), Payment.amount.label("amount"), Payment.currency.label("currency"),
                    Payment.status.label("status"), Payment.purpose.label("payment_type"), Payment.created_at.label("created_at"),
                )
                .filter(Payment.user_id == user.id)
                .order_by(Payment.created_at.desc().nullslast(), Payment.id.desc())
                .limit(_MAX_DETAIL_ROWS + 1)
                .execution_options(skip_hierarchy_scope=True, autoflush=False)
                .all()
            )
        if details["id"] is None:
            raise RuntimeError("user detail contained an invalid identifier")
        downline_truncated = len(downline_rows) > _MAX_DETAIL_ROWS
        challenge_truncated = len(challenge_rows) > _MAX_DETAIL_ROWS
        payment_truncated = len(payment_rows) > _MAX_DETAIL_ROWS
        downline = [{
            "id": row.id if _positive_identifier(row.id) else None,
            "first_name": _safe_text(row.first_name, 100),
            "last_name": _safe_text(row.last_name, 100),
            "email": _safe_text(row.email, 255),
            "role": _safe_code(row.role, _ROLES),
            "is_active": row.is_active if isinstance(row.is_active, bool) else None,
            "created_at": _timestamp(row.created_at),
        } for row in downline_rows[:_MAX_DETAIL_ROWS]]
        challenges = [{
            "id": row.id if _positive_identifier(row.id) else None,
            "program_name": _safe_text(row.program_name, 255),
            "status": _safe_code(row.status, _CHALLENGE_STATUSES),
            "initial_balance": _decimal_string(row.initial_balance),
            "current_balance": _decimal_string(row.current_balance),
            "total_profit": _decimal_string(row.total_profit),
            "created_at": _timestamp(row.created_at),
        } for row in challenge_rows[:_MAX_DETAIL_ROWS]]
        payments = [{
            "id": row.id if _positive_identifier(row.id) else None,
            "amount": _decimal_string(row.amount),
            "currency": _currency(row.currency),
            "status": _safe_code(row.status, _PAYMENT_STATUSES),
            "payment_type": _safe_code(row.payment_type, _PAYMENT_PURPOSES),
            "created_at": _timestamp(row.created_at),
        } for row in payment_rows[:_MAX_DETAIL_ROWS]]
        if any(item["id"] is None for item in downline + challenges + payments):
            raise RuntimeError("user detail contained an invalid related identifier")
        return {
            "owner_context": owner,
            "record_verification": "unverified_legacy",
            "settlement_enabled": False,
            "user": details,
            "downline": {"items": downline, "truncated": downline_truncated},
            "challenges": {"items": challenges, "truncated": challenge_truncated},
            "payments": {"items": payments, "truncated": payment_truncated},
        }

    @classmethod
    def create_user(cls, actor: object, payload: object) -> dict[str, object]:
        owner = _require_scope(actor)
        values = _create_input(payload)
        if values["role"] == "affiliate" and not current_app.config.get("EXPANDED_HIERARCHY_ENABLED", False):
            raise AdminClosureUsersProductNotConfigured()
        try:
            with db.session.no_autoflush, without_hierarchy_scope(db.session):
                if db.session.query(User.id).filter(User.email == values["email"]).first() is not None:
                    raise AdminClosureUsersValidationError("An account with this email already exists.")
                if not actor.can_create_user(values["role"]):
                    raise AdminClosureUsersPermissionDenied()
                # Preserve the established verification behavior without accepting a caller-controlled flag.
                is_verified = getattr(actor, "role", None) == "supermaster"
                if not is_verified and values["role"] == "trader":
                    if not values["phone"]:
                        raise AdminClosureUsersValidationError("phone is required for this role.")
                    is_verified = True
                user = User(
                    email=values["email"], first_name=values["first_name"], last_name=values["last_name"],
                    role=values["role"], is_active=True, phone=values["phone"], country_code=values["country_code"],
                    is_verified=is_verified, parent_id=actor.id, tenant_id=actor.tenant_id,
                )
                user.set_password(values["password"])
                db.session.add(user)
                db.session.flush()
                try:
                    user.update_tree_path()
                except ValueError as error:
                    raise AdminClosureUsersValidationError("The parent hierarchy path is invalid.") from error
                if user.role in {"supermaster", "master", "affiliate"}:
                    user.generate_referral_code()
                db.session.commit()
            return _write_result(owner, action="created", message="User created successfully.", user=user)
        except Exception:
            db.session.rollback()
            raise

    @classmethod
    def update_user(cls, actor: object, user_id: int, payload: object) -> dict[str, object]:
        owner = _require_scope(actor)
        values = _update_input(payload)
        try:
            with db.session.no_autoflush:
                user = _target(actor, user_id, lock=True)
                if user.id == actor.id and ("role" in values or "is_active" in values):
                    raise AdminClosureUsersPermissionDenied()
                if "role" in values and values["role"] != user.role and not actor.can_create_user(values["role"]):
                    raise AdminClosureUsersPermissionDenied()
                for field, value in values.items():
                    setattr(user, field, value)
                user.updated_at = datetime.utcnow()
                db.session.commit()
            return _write_result(owner, action="updated", message="User updated successfully.", user=user)
        except Exception:
            db.session.rollback()
            raise

    @classmethod
    def deactivate_user(cls, actor: object, user_id: int) -> dict[str, object]:
        owner = _require_scope(actor)
        try:
            with db.session.no_autoflush:
                user = _target(actor, user_id, lock=True)
                if user.id == actor.id:
                    raise AdminClosureUsersPermissionDenied()
                if user.is_active is False:
                    return _write_result(owner, action="deactivated", message="User account is already inactive.", user=user)
                user.is_active = False
                user.updated_at = datetime.utcnow()
                db.session.commit()
            return _write_result(owner, action="deactivated", message="User account deactivated.", user=user)
        except Exception:
            db.session.rollback()
            raise

    @classmethod
    def reset_password(cls, actor: object, user_id: int, payload: object) -> dict[str, object]:
        owner = _require_scope(actor)
        password = _password_input(payload)
        try:
            with db.session.no_autoflush:
                user = _target(actor, user_id, lock=True)
                user.set_password(password)
                user.token_version = (user.token_version or 0) + 1
                db.session.query(PasswordResetToken).filter(
                    PasswordResetToken.user_id == user.id, PasswordResetToken.used.is_(False)
                ).update({"used": True}, synchronize_session=False)
                user.updated_at = datetime.utcnow()
                db.session.commit()
            return _write_result(owner, action="password_reset", message="Password reset successfully.", user=user)
        except Exception:
            db.session.rollback()
            raise
