"""Secure UI-4 admin program-catalog projections and mutations.

This service owns only program rows.  It never selects a tenant from request data,
changes quote/order snapshots, calls a provider, or makes settlement decisions.
The calling route must authenticate, enforce the existing admin gate, and roll back
on every write failure.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import re
from typing import Any

from sqlalchemy import and_, func, null, select, text, true
from sqlalchemy.orm import aliased
from src.constants.roles import Roles
from src.database import db
from src.models.trading_program import Challenge, ProgramAddOn, TradingProgram
from src.utils.hierarchy_scoping import (
    complete_hierarchy_scope,
    platform_root_scope,
    tenant_hierarchy_scope,
)


_MAX_PAGE = 10_000
_MAX_PER_PAGE = 50
_MAX_OFFSET = 10_000
_MAX_INTEGER_DIGITS = 10
_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_MAX_JSON_BYTES = 65_536
_MAX_DESCRIPTION = 65_536
_MAX_NAME = 255
_MAX_CODE = 50
_DECIMAL_RE = re.compile(r"(?:0|[1-9][0-9]*)\.[0-9]{2}\Z")
_MONEY_MAX = Decimal("99999999.99")
_ACCOUNT_SIZE_MAX = Decimal("9999999999.99")
_PERCENT_MAX = Decimal("100.00")


class AdminProgramsQueryInvalid(ValueError):
    """The list query is malformed, duplicated, or outside the fixed bounds."""


class AdminProgramsValidationError(ValueError):
    """A mutation field is absent, unknown, or cannot be represented safely."""


class AdminProgramsScopeRequired(PermissionError):
    """The principal lacks an admin role plus coherent root or tenant scope."""


class AdminProgramsNotFound(LookupError):
    """The program does not exist inside the caller's explicit scope."""


class AdminProgramsConflict(RuntimeError):
    """A supported mutation conflicts with an existing program relationship."""


@dataclass(frozen=True)
class AdminProgramsReadArguments:
    page: int
    per_page: int
    offset: int


@dataclass(frozen=True)
class _Scope:
    owner: dict[str, object]
    program_predicate: object
    is_root: bool


def _positive_identifier(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _canonical_integer(raw: object, *, minimum: int, maximum: int) -> int:
    if (
        not isinstance(raw, str)
        or not raw
        or len(raw) > _MAX_INTEGER_DIGITS
        or not raw.isascii()
        or not raw.isdecimal()
    ):
        raise AdminProgramsQueryInvalid()
    value = int(raw)
    if not minimum <= value <= maximum or str(value) != raw:
        raise AdminProgramsQueryInvalid()
    return value


def _parse_list_query(arguments: Any) -> AdminProgramsReadArguments:
    """Validate all query syntax before any TradingProgram statement."""
    for name in arguments.keys():
        if name not in {"page", "per_page"} or len(arguments.getlist(name)) != 1:
            raise AdminProgramsQueryInvalid()
    pages = arguments.getlist("page")
    per_pages = arguments.getlist("per_page")
    page = 1 if not pages else _canonical_integer(pages[0], minimum=1, maximum=_MAX_PAGE)
    per_page = 20 if not per_pages else _canonical_integer(per_pages[0], minimum=1, maximum=_MAX_PER_PAGE)
    offset = (page - 1) * per_page
    if offset > _MAX_OFFSET:
        raise AdminProgramsQueryInvalid()
    return AdminProgramsReadArguments(page=page, per_page=per_page, offset=offset)


def _owner_context(actor: object) -> dict[str, object]:
    user_id = getattr(actor, "id", None)
    tenant_id = getattr(actor, "tenant_id", None)
    role = getattr(actor, "role", None)
    if (
        not _positive_identifier(user_id)
        or not _positive_identifier(tenant_id)
        or not isinstance(role, str)
        or not role
        or not Roles.is_admin(role)
    ):
        raise AdminProgramsScopeRequired()
    return {"user_id": user_id, "tenant_id": tenant_id, "role": role}


def _scope(actor: object) -> _Scope:
    """Authorize the actor before a program or challenge SQL statement is built."""
    owner = _owner_context(actor)
    if not complete_hierarchy_scope(actor):
        raise AdminProgramsScopeRequired()
    if platform_root_scope(actor):
        # Only the stable configured supermaster can receive all positive tenants.
        return _Scope(owner=owner, program_predicate=TradingProgram.tenant_id > 0, is_root=True)
    if not tenant_hierarchy_scope(actor):
        raise AdminProgramsScopeRequired()
    return _Scope(
        owner=owner,
        program_predicate=TradingProgram.tenant_id == owner["tenant_id"],
        is_root=False,
    )


def _set_query_timeout() -> None:
    bind = db.session.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        db.session.execute(text("SET LOCAL lock_timeout = '3s'"))
        db.session.execute(text("SET LOCAL statement_timeout = '5s'"))


def _safe_json_object(value: object, field: str) -> dict:
    if not isinstance(value, dict):
        raise AdminProgramsValidationError(f"{field} must be an object")
    copied = deepcopy(value)
    try:
        encoded = json.dumps(copied, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise AdminProgramsValidationError(f"{field} must be JSON") from None
    if len(encoded.encode("utf-8")) > _MAX_JSON_BYTES:
        raise AdminProgramsValidationError(f"{field} exceeds the 64 KiB storage limit")
    return copied


def _text(value: object, field: str, *, maximum: int, required: bool = False, ascii_only: bool = False) -> str | None:
    if value is None:
        if required:
            raise AdminProgramsValidationError(f"{field} is required")
        return None
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise AdminProgramsValidationError(f"{field} is invalid")
    if ascii_only and (not value.isascii() or any(ord(character) < 32 or ord(character) > 126 for character in value)):
        raise AdminProgramsValidationError(f"{field} is invalid")
    return value


def _decimal(value: object, field: str, *, required: bool = False, positive: bool = False,
             percentage: bool = False, maximum: Decimal | None = None) -> Decimal | None:
    if value is None:
        if required:
            raise AdminProgramsValidationError(f"{field} is required")
        return None
    if not isinstance(value, str) or not _DECIMAL_RE.fullmatch(value):
        raise AdminProgramsValidationError(f"{field} must be a canonical decimal string")
    try:
        decimal_value = Decimal(value)
        if not decimal_value.is_finite() or decimal_value < 0:
            raise InvalidOperation
        if positive and decimal_value <= 0:
            raise InvalidOperation
        if percentage and decimal_value > _PERCENT_MAX:
            raise InvalidOperation
        if maximum is not None and decimal_value > maximum:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        raise AdminProgramsValidationError(f"{field} is outside the stored field bounds") from None
    return decimal_value


def _decimal_string(value: object, field: str, *, optional: bool = False,
                    positive: bool = False, percentage: bool = False,
                    maximum: Decimal | None = None) -> str | None:
    if value is None:
        if optional:
            return None
        raise RuntimeError(f"stored {field} is unexpectedly null")
    if isinstance(value, bool) or isinstance(value, float):
        raise RuntimeError(f"stored {field} is not exact")
    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
        if not decimal_value.is_finite() or decimal_value < 0:
            raise InvalidOperation
        if positive and decimal_value <= 0:
            raise InvalidOperation
        if percentage and decimal_value > _PERCENT_MAX:
            raise InvalidOperation
        if maximum is not None and decimal_value > maximum:
            raise InvalidOperation
        if decimal_value != decimal_value.quantize(Decimal("0.01")):
            raise InvalidOperation
    except (InvalidOperation, TypeError, ValueError):
        raise RuntimeError(f"stored {field} cannot be represented exactly") from None
    return format(decimal_value, ".2f")


def _timestamp(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise RuntimeError("stored timestamp is invalid")
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None).isoformat() + "Z"
    return value.isoformat() + "Z"


def _program_payload(program: TradingProgram) -> dict[str, object]:
    """Serialize every persisted management field without float coercion."""
    if not _positive_identifier(program.id) or not _positive_identifier(program.tenant_id):
        raise RuntimeError("stored program identity is invalid")
    return {
        "id": program.id,
        "tenant_id": program.tenant_id,
        "name": _text(program.name, "name", maximum=_MAX_NAME, required=True),
        "type": _text(program.type, "type", maximum=_MAX_CODE, required=True, ascii_only=True),
        "description": _text(program.description, "description", maximum=_MAX_DESCRIPTION),
        "account_size": _decimal_string(
            program.account_size, "account_size", positive=True, maximum=_ACCOUNT_SIZE_MAX,
        ),
        "profit_target": _decimal_string(
            program.profit_target, "profit_target", optional=True, percentage=True,
        ),
        "max_daily_loss": _decimal_string(
            program.max_daily_loss, "max_daily_loss", optional=True, percentage=True,
        ),
        "max_total_loss": _decimal_string(
            program.max_total_loss, "max_total_loss", optional=True, percentage=True,
        ),
        "price": _decimal_string(program.price, "price", positive=True, maximum=_MONEY_MAX),
        "profit_split": _decimal_string(
            program.profit_split, "profit_split", optional=True, percentage=True,
        ),
        "profit_split_percentage": _decimal_string(
            program.profit_split_percentage, "profit_split_percentage", optional=True, percentage=True,
        ),
        "minimum_payout_amount": _decimal_string(
            program.minimum_payout_amount, "minimum_payout_amount", optional=True, maximum=_MONEY_MAX,
        ),
        "payout_mode": _text(program.payout_mode, "payout_mode", maximum=_MAX_CODE, ascii_only=True),
        "rules": _safe_json_object(program.rules, "rules"),
        "is_active": program.is_active if isinstance(program.is_active, bool) else _invalid_boolean(),
        "created_at": _timestamp(program.created_at),
        "updated_at": _timestamp(program.updated_at),
    }


def _invalid_boolean() -> bool:
    raise RuntimeError("stored is_active is invalid")


def _pagination(arguments: AdminProgramsReadArguments, total: object) -> dict[str, int]:
    if isinstance(total, bool) or not isinstance(total, int) or not 0 <= total <= _MAX_SAFE_INTEGER:
        raise RuntimeError("program count is invalid")
    return {
        "page": arguments.page,
        "per_page": arguments.per_page,
        "total": total,
        "pages": (total + arguments.per_page - 1) // arguments.per_page if total else 0,
    }


def _list_snapshot(scope: _Scope, arguments: AdminProgramsReadArguments) -> tuple[int, list[TradingProgram]]:
    """Get count and page from one CTE-backed statement snapshot."""
    scoped = (
        select(TradingProgram)
        .where(scope.program_predicate)
        .cte("admin_programs_scoped")
        .prefix_with("MATERIALIZED", dialect="postgresql")
    )
    total = select(func.count().label("_total")).select_from(scoped).cte("admin_programs_total")
    page = (
        select(*scoped.c)
        .order_by(scoped.c.id.asc())
        .limit(arguments.per_page)
        .offset(arguments.offset)
        .cte("admin_programs_page")
    )
    page_program = aliased(TradingProgram, page)
    statement = (
        select(total.c._total, page_program)
        .select_from(total.outerjoin(page, true()))
        .execution_options(skip_hierarchy_scope=True, autoflush=False)
    )
    rows = db.session.execute(statement).all()
    if not rows:
        raise RuntimeError("program snapshot did not return a total")
    total_value = rows[0]._mapping["_total"]
    programs = [row[1] for row in rows if row[1] is not None]
    return total_value, programs


def _allowed_mutation(data: object, *, create: bool) -> dict[str, object]:
    if not isinstance(data, dict):
        raise AdminProgramsValidationError("A JSON object is required")
    allowed = {
        "name", "type", "description", "account_size", "profit_target", "max_daily_loss",
        "max_total_loss", "price", "profit_split", "profit_split_percentage",
        "minimum_payout_amount", "payout_mode", "rules", "is_active",
    }
    unknown = set(data).difference(allowed)
    if unknown:
        raise AdminProgramsValidationError("Unknown program fields are not allowed")
    if not data:
        raise AdminProgramsValidationError("At least one program field is required")
    if create:
        # These are the actual non-null persisted program columns. Optional terms
        # stay null when not configured; requests must never infer a zero/default.
        missing = {
            "name", "type", "account_size", "price",
        }.difference(data)
        if missing:
            raise AdminProgramsValidationError("Missing required program fields")

    values: dict[str, object] = {}
    if "name" in data:
        values["name"] = _text(data["name"], "name", maximum=_MAX_NAME, required=True)
    if "type" in data:
        values["type"] = _text(data["type"], "type", maximum=_MAX_CODE, required=True, ascii_only=True)
    if "description" in data:
        values["description"] = _text(data["description"], "description", maximum=_MAX_DESCRIPTION)
    if "account_size" in data:
        values["account_size"] = _decimal(
            data["account_size"], "account_size", required=True, positive=True, maximum=_ACCOUNT_SIZE_MAX,
        )
    if "profit_target" in data:
        values["profit_target"] = _decimal(
            data["profit_target"], "profit_target", percentage=True,
        )
    if "max_daily_loss" in data:
        values["max_daily_loss"] = _decimal(
            data["max_daily_loss"], "max_daily_loss", percentage=True,
        )
    if "max_total_loss" in data:
        values["max_total_loss"] = _decimal(
            data["max_total_loss"], "max_total_loss", percentage=True,
        )
    if "price" in data:
        values["price"] = _decimal(data["price"], "price", required=True, positive=True, maximum=_MONEY_MAX)
    if "profit_split" in data:
        values["profit_split"] = _decimal(
            data["profit_split"], "profit_split", percentage=True,
        )
    if "profit_split_percentage" in data:
        values["profit_split_percentage"] = _decimal(
            data["profit_split_percentage"], "profit_split_percentage", percentage=True,
        )
    if "minimum_payout_amount" in data:
        values["minimum_payout_amount"] = _decimal(
            data["minimum_payout_amount"], "minimum_payout_amount", maximum=_MONEY_MAX,
        )
    if "payout_mode" in data:
        values["payout_mode"] = _text(data["payout_mode"], "payout_mode", maximum=_MAX_CODE, ascii_only=True)
    if "rules" in data:
        values["rules"] = _safe_json_object(data["rules"], "rules")
    if "is_active" in data:
        if not isinstance(data["is_active"], bool):
            raise AdminProgramsValidationError("is_active must be boolean")
        values["is_active"] = data["is_active"]
    return values


def _legacy_program_type_column() -> bool:
    """Whether the migration-owned historic non-null alias is present.

    The ORM maps the later ``type`` column but cannot represent the original
    ``program_type`` column.  PostgreSQL migration head deliberately retains both.
    This bounded schema check occurs only after actor scope validation; it never
    reads a catalog row and never accepts a client-selected column or value.
    """
    bind = db.session.get_bind()
    if bind is None or bind.dialect.name != "postgresql":
        return False
    return db.session.execute(text("""
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'trading_programs'
              AND column_name = 'program_type'
        )
    """)).scalar_one() is True


def _insert_legacy_compatible_program(values: dict[str, object]) -> TradingProgram:
    """Insert a mapped program while retaining the exact historical type alias."""
    created_at = datetime.utcnow()
    identifier = db.session.execute(text("""
        INSERT INTO trading_programs (
            tenant_id, name, program_type, type, description, account_size,
            profit_target, max_daily_loss, max_total_loss, price, profit_split,
            profit_split_percentage, minimum_payout_amount, payout_mode, rules,
            is_active, created_at, updated_at
        ) VALUES (
            :tenant_id, :name, :program_type, :type, :description, :account_size,
            :profit_target, :max_daily_loss, :max_total_loss, :price, :profit_split,
            :profit_split_percentage, :minimum_payout_amount, :payout_mode,
            CAST(:rules AS jsonb), :is_active, :created_at, :updated_at
        )
        RETURNING id
    """), {
        **values,
        "program_type": values["type"],
        "rules": json.dumps(values.get("rules", {}), separators=(",", ":"), ensure_ascii=False, allow_nan=False),
        "created_at": created_at,
        "updated_at": created_at,
    }).scalar_one()
    program = db.session.get(
        TradingProgram, identifier, execution_options={"skip_hierarchy_scope": True, "populate_existing": True},
    )
    if program is None:
        raise RuntimeError("created program could not be reloaded")
    return program


def _sync_legacy_program_type(program_id: int, program_type: str) -> None:
    """Keep the historical storage alias equal to the persisted mapped type."""
    db.session.execute(text("""
        UPDATE trading_programs
        SET program_type = :program_type
        WHERE id = :program_id
    """), {"program_id": program_id, "program_type": program_type})


def _scoped_program(scope: _Scope, program_id: object) -> TradingProgram:
    if not _positive_identifier(program_id):
        raise AdminProgramsNotFound()
    statement = (
        select(TradingProgram)
        .where(and_(TradingProgram.id == program_id, scope.program_predicate))
        .with_for_update()
        .execution_options(skip_hierarchy_scope=True, autoflush=False, populate_existing=True)
    )
    program = db.session.execute(statement).scalar_one_or_none()
    if program is None:
        raise AdminProgramsNotFound()
    return program


class AdminClosureProgramsService:
    """The sole UI-4 admin program read/write implementation."""

    @staticmethod
    def parse_list_query(arguments: Any) -> AdminProgramsReadArguments:
        return _parse_list_query(arguments)

    @classmethod
    def list_programs(cls, actor: object, arguments: AdminProgramsReadArguments) -> dict[str, object]:
        scope = _scope(actor)
        with db.session.no_autoflush:
            _set_query_timeout()
            total, programs = _list_snapshot(scope, arguments)
        return {
            "owner_context": scope.owner,
            "programs": [_program_payload(program) for program in programs],
            "pagination": _pagination(arguments, total),
        }

    @classmethod
    def create_program(cls, actor: object, data: object) -> dict[str, object]:
        scope = _scope(actor)
        values = _allowed_mutation(data, create=True)
        # A request never selects a tenant, even for the platform root.  This keeps
        # the write owner independent of untrusted request input.
        values["tenant_id"] = scope.owner["tenant_id"]
        _set_query_timeout()
        if _legacy_program_type_column():
            program = _insert_legacy_compatible_program(values)
        else:
            # SQLAlchemy client defaults otherwise replace an explicit ``null``
            # for these nullable persisted columns. Bind SQL NULL deliberately:
            # a missing field may use its schema default, but a supplied null
            # must remain null and never become an inferred value.
            for field in (
                "profit_split", "profit_split_percentage",
                "minimum_payout_amount", "payout_mode", "rules",
            ):
                if field in values and values[field] is None:
                    values[field] = null()
            program = TradingProgram(**values)
            db.session.add(program)
            db.session.flush()
        return {"owner_context": scope.owner, "program": _program_payload(program)}

    @classmethod
    def update_program(cls, actor: object, program_id: object, data: object) -> dict[str, object]:
        scope = _scope(actor)
        values = _allowed_mutation(data, create=False)
        _set_query_timeout()
        program = _scoped_program(scope, program_id)
        for field, value in values.items():
            setattr(program, field, value)
        db.session.flush()
        if "type" in values and _legacy_program_type_column():
            _sync_legacy_program_type(program.id, values["type"])
        return {"owner_context": scope.owner, "program": _program_payload(program)}

    @classmethod
    def delete_program(cls, actor: object, program_id: object) -> dict[str, object]:
        scope = _scope(actor)
        _set_query_timeout()
        program = _scoped_program(scope, program_id)
        dependent_challenge = db.session.execute(
            select(Challenge.id)
            .where(Challenge.program_id == program.id)
            .limit(1)
            .execution_options(skip_hierarchy_scope=True, autoflush=False)
        ).scalar_one_or_none()
        if dependent_challenge is not None:
            # ``challenges.program_id`` is non-nullable. Historical challenge
            # rows are not disposable admin metadata, so deletion must fail
            # closed instead of relying on an ORM nulling update that fails late.
            raise AdminProgramsConflict("Program has associated challenges")
        dependent_addon = db.session.execute(
            select(ProgramAddOn.id)
            .where(ProgramAddOn.program_id == program.id)
            .limit(1)
            .execution_options(skip_hierarchy_scope=True, autoflush=False)
        ).scalar_one_or_none()
        if dependent_addon is not None:
            raise AdminProgramsConflict("Program has associated add-ons")
        deleted_program_id = program.id
        db.session.delete(program)
        db.session.flush()
        return {"owner_context": scope.owner, "deleted_program_id": deleted_program_id}
