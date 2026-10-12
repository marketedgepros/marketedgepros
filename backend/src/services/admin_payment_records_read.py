"""Read-only, tenant-safe UI-4 admin payment record projections.

Legacy payment and approval rows are compatibility records only.  This module never
settles, mutates, enriches with personal data, or derives payment authority from a
row.  It is deliberately the single backend read path for the two UI-4 screens.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from math import ceil
from typing import Any

from sqlalchemy import and_, func, or_, select, text, true
from sqlalchemy.orm import aliased

from src.database import db
from src.models.payment import Payment
from src.models.payment_approval import PaymentApprovalRequest
from src.models.trading_program import Challenge, TradingProgram
from src.models.user import User
from src.utils.hierarchy_scoping import (
    complete_hierarchy_scope,
    platform_root_scope,
    tenant_hierarchy_scope,
)


_MAX_PAGE = 10_000
_MAX_PER_PAGE = 50
_MAX_OFFSET = 10_000
_MAX_INTEGER_DIGITS = 10
_PAYMENT_STATUSES = frozenset({"pending", "completed", "failed", "refunded"})
_PAYMENT_PURPOSES = frozenset({"challenge_purchase", "withdrawal", "refund"})
_APPROVAL_PAYMENT_TYPES = frozenset({"cash", "free"})


class AdminPaymentQueryInvalid(ValueError):
    """The query was duplicate, noncanonical, unknown, or exceeds a fixed bound."""


class AdminPaymentScopeRequired(PermissionError):
    """The principal lacks a positive tenant, explicit root, or coherent hierarchy."""


class AdminPaymentRecordNotFound(LookupError):
    """The requested record does not exist inside the caller's read predicate."""


@dataclass(frozen=True)
class AdminPaymentReadArguments:
    page: int
    per_page: int
    offset: int
    status: str | None = None
    payment_type: str | None = None


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
        raise AdminPaymentQueryInvalid()
    value = int(raw)
    if not minimum <= value <= maximum or str(value) != raw:
        raise AdminPaymentQueryInvalid()
    return value


def _parse_page(arguments: Any, *, allowed_names: frozenset[str]) -> tuple[int, int, int]:
    """Validate all query syntax before any payment/approval resource SQL."""
    for name in arguments.keys():
        if name not in allowed_names or len(arguments.getlist(name)) != 1:
            raise AdminPaymentQueryInvalid()
    page_values = arguments.getlist("page")
    per_page_values = arguments.getlist("per_page")
    page = 1 if not page_values else _canonical_integer(page_values[0], minimum=1, maximum=_MAX_PAGE)
    per_page = 20 if not per_page_values else _canonical_integer(
        per_page_values[0], minimum=1, maximum=_MAX_PER_PAGE,
    )
    offset = (page - 1) * per_page
    if offset > _MAX_OFFSET:
        raise AdminPaymentQueryInvalid()
    return page, per_page, offset


def _owner_context(actor: object) -> dict[str, int]:
    user_id = getattr(actor, "id", None)
    tenant_id = getattr(actor, "tenant_id", None)
    if not (_positive_identifier(user_id) and _positive_identifier(tenant_id)):
        raise AdminPaymentScopeRequired()
    return {"user_id": user_id, "tenant_id": tenant_id}


def _metadata(actor: object) -> dict[str, object]:
    return {
        "owner_context": _owner_context(actor),
        "record_verification": "unverified_legacy",
        "settlement_enabled": False,
    }


def _set_statement_timeout() -> None:
    """Bound PostgreSQL read work without issuing unsupported SQLite syntax."""
    bind = db.session.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        db.session.execute(text("SET LOCAL statement_timeout = 1500"))


def _decimal_string(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return format(decimal_value, "f") if decimal_value.is_finite() else None


def _timestamp(value: object) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _identifier(value: object) -> int | None:
    return value if _positive_identifier(value) else None


def _safe_code(value: object, *, allowed: frozenset[str] | None = None,
               maximum_length: int = 50) -> str | None:
    """Return a bounded, non-free-text legacy code; unknown values stay unknown."""
    if not isinstance(value, str) or not value or len(value) > maximum_length or not value.isascii():
        return None
    if allowed is not None:
        return value if value in allowed else None
    if not all(character.isalnum() or character in {"_", "-"} for character in value):
        return None
    return value


def _recorded_currency(value: object) -> str | None:
    """Do not normalize, infer, or convert legacy currency values."""
    if not isinstance(value, str) or len(value) != 3 or not value.isascii():
        return None
    return value if value.isalpha() and value == value.upper() else None


def _pagination(arguments: AdminPaymentReadArguments, total: int) -> dict[str, int]:
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise RuntimeError("admin payment snapshot returned an invalid total")
    return {
        "page": arguments.page,
        "per_page": arguments.per_page,
        "total": total,
        "pages": ceil(total / arguments.per_page) if total else 0,
    }


def _snapshot_page(query, arguments: AdminPaymentReadArguments, *, name: str) -> tuple[int, list[Any]]:
    """Return total and page from one CTE-backed SQL statement snapshot.

    The count CTE has one row and is outer joined to the page CTE so a valid page
    past the end retains the real total with a null-ID sentinel.  A missing total
    is a storage failure, never an invented zero.
    """
    scoped = query.order_by(None).cte(name=f"{name}_scoped")
    scoped = scoped.prefix_with("MATERIALIZED", dialect="postgresql")
    total = select(func.count().label("_total")).select_from(scoped).cte(name=f"{name}_total")
    page = (
        select(*scoped.c)
        .order_by(scoped.c.created_at.desc().nullslast(), scoped.c.id.desc())
        .limit(arguments.per_page)
        .offset(arguments.offset)
        .cte(name=f"{name}_page")
    )
    statement = (
        select(total.c._total, *page.c)
        .select_from(total.outerjoin(page, true()))
        .execution_options(skip_hierarchy_scope=True, autoflush=False)
    )
    records = db.session.execute(statement).all()
    if not records:
        raise RuntimeError("admin payment snapshot did not return a total row")
    total_value = records[0]._mapping["_total"]
    if isinstance(total_value, bool) or not isinstance(total_value, int) or total_value < 0:
        raise RuntimeError("admin payment snapshot total was invalid")
    return total_value, [record for record in records if record._mapping["id"] is not None]


def _allowed_user_ids(actor: object):
    """Build the only explicit global-root or tenant/downline user predicate."""
    if not complete_hierarchy_scope(actor):
        raise AdminPaymentScopeRequired()
    if platform_root_scope(actor):
        users = db.session.query(User.id).filter(User.tenant_id.is_not(None), User.tenant_id > 0)
    elif tenant_hierarchy_scope(actor):
        condition = User.hierarchy_filter_for_entity(actor)
        if condition is None:
            raise AdminPaymentScopeRequired()
        users = db.session.query(User.id).filter(condition, User.tenant_id == actor.tenant_id)
    else:
        raise AdminPaymentScopeRequired()
    return users.execution_options(skip_hierarchy_scope=True).distinct().subquery("admin_payment_allowed_users")


def _require_root(actor: object) -> None:
    if not platform_root_scope(actor):
        raise AdminPaymentScopeRequired()


def _payments_query(actor: object, allowed_users):
    owner = aliased(User, name="admin_payment_owner")
    return (
        db.session.query(
            Payment.id.label("id"),
            Payment.user_id.label("user_id"),
            Payment.amount.label("amount"),
            Payment.currency.label("currency"),
            Payment.purpose.label("payment_type"),
            Payment.payment_method.label("payment_method"),
            Payment.status.label("status"),
            Payment.created_at.label("created_at"),
        )
        .join(owner, Payment.user_id == owner.id)
        .join(allowed_users, owner.id == allowed_users.c.id)
        .filter(owner.tenant_id.is_not(None), owner.tenant_id > 0)
        .execution_options(skip_hierarchy_scope=True, autoflush=False)
    )


def _approval_query(*, requester_id: int | None = None):
    """Return coherent approval rows only; nullable historic FKs remain nullable."""
    requester = aliased(User, name="admin_approval_requester")
    requested_for = aliased(User, name="admin_approval_requested_for")
    challenge = aliased(Challenge, name="admin_approval_challenge")
    program = aliased(TradingProgram, name="admin_approval_program")
    payment = aliased(Payment, name="admin_approval_payment")
    query = (
        db.session.query(
            PaymentApprovalRequest.id.label("id"),
            PaymentApprovalRequest.requested_by.label("requested_by"),
            PaymentApprovalRequest.requested_for.label("requested_for"),
            PaymentApprovalRequest.challenge_id.label("challenge_id"),
            PaymentApprovalRequest.payment_id.label("payment_id"),
            PaymentApprovalRequest.amount.label("amount"),
            PaymentApprovalRequest.payment_type.label("payment_type"),
            PaymentApprovalRequest.status.label("status"),
            PaymentApprovalRequest.created_at.label("created_at"),
            PaymentApprovalRequest.reviewed_at.label("reviewed_at"),
        )
        .join(requester, PaymentApprovalRequest.requested_by == requester.id)
        .join(requested_for, PaymentApprovalRequest.requested_for == requested_for.id)
        .outerjoin(challenge, PaymentApprovalRequest.challenge_id == challenge.id)
        .outerjoin(program, challenge.program_id == program.id)
        .outerjoin(payment, PaymentApprovalRequest.payment_id == payment.id)
        .filter(
            requester.tenant_id.is_not(None),
            requester.tenant_id > 0,
            requested_for.tenant_id == requester.tenant_id,
            or_(
                PaymentApprovalRequest.challenge_id.is_(None),
                and_(
                    challenge.id.is_not(None),
                    challenge.user_id == PaymentApprovalRequest.requested_for,
                    program.id.is_not(None),
                    program.tenant_id == requester.tenant_id,
                ),
            ),
            or_(
                PaymentApprovalRequest.payment_id.is_(None),
                and_(payment.id.is_not(None), payment.user_id == PaymentApprovalRequest.requested_for),
            ),
        )
        .execution_options(skip_hierarchy_scope=True, autoflush=False)
    )
    if requester_id is not None:
        query = query.filter(PaymentApprovalRequest.requested_by == requester_id)
    return query


def _payment_projection(row: Any) -> dict[str, object]:
    # payment_method is an expressly allowed legacy scalar, not a provider
    # payload or an enum whose value may be rewritten.  The model itself bounds
    # it to 50 characters; malformed non-string data remains unknown.
    payment_method = row.payment_method if isinstance(row.payment_method, str) else None
    return {
        "id": _identifier(row.id),
        "user_id": _identifier(row.user_id),
        "amount": _decimal_string(row.amount),
        "currency": _recorded_currency(row.currency),
        "payment_type": _safe_code(row.payment_type, allowed=_PAYMENT_PURPOSES, maximum_length=100),
        "payment_method": payment_method,
        "status": _safe_code(row.status, allowed=_PAYMENT_STATUSES),
        "created_at": _timestamp(row.created_at),
    }


def _approval_projection(row: Any) -> dict[str, object]:
    return {
        "id": _identifier(row.id),
        "requested_by": _identifier(row.requested_by),
        "requested_for": _identifier(row.requested_for),
        "challenge_id": _identifier(row.challenge_id),
        "payment_id": _identifier(row.payment_id),
        "amount": _decimal_string(row.amount),
        "payment_type": _safe_code(row.payment_type, allowed=_APPROVAL_PAYMENT_TYPES),
        "status": _safe_code(row.status, allowed=frozenset({"pending", "approved", "rejected"})),
        "created_at": _timestamp(row.created_at),
        "reviewed_at": _timestamp(row.reviewed_at),
    }


class AdminPaymentRecordsReadService:
    """The sole read implementation for UI-4 payment records and approvals."""

    @staticmethod
    def parse_payments_query(arguments: Any) -> AdminPaymentReadArguments:
        page, per_page, offset = _parse_page(
            arguments, allowed_names=frozenset({"page", "per_page", "status", "type"}),
        )
        status_values = arguments.getlist("status")
        type_values = arguments.getlist("type")
        status = None if not status_values else status_values[0]
        payment_type = None if not type_values else type_values[0]
        if status is not None and status not in _PAYMENT_STATUSES:
            raise AdminPaymentQueryInvalid()
        if payment_type is not None and payment_type not in _PAYMENT_PURPOSES:
            raise AdminPaymentQueryInvalid()
        return AdminPaymentReadArguments(page, per_page, offset, status, payment_type)

    @staticmethod
    def parse_approval_query(arguments: Any) -> AdminPaymentReadArguments:
        page, per_page, offset = _parse_page(arguments, allowed_names=frozenset({"page", "per_page"}))
        return AdminPaymentReadArguments(page, per_page, offset)

    @classmethod
    def payments(cls, actor: object, arguments: AdminPaymentReadArguments) -> dict[str, object]:
        metadata = _metadata(actor)
        with db.session.no_autoflush:
            allowed_users = _allowed_user_ids(actor)
            _set_statement_timeout()
            query = _payments_query(actor, allowed_users)
            if arguments.status is not None:
                query = query.filter(Payment.status == arguments.status)
            if arguments.payment_type is not None:
                query = query.filter(Payment.purpose == arguments.payment_type)
            total, rows = _snapshot_page(query, arguments, name="admin_payments")
        return {
            **metadata,
            "payments": [_payment_projection(row) for row in rows],
            "pagination": _pagination(arguments, total),
            "filters": {"status": arguments.status, "type": arguments.payment_type},
        }

    @classmethod
    def pending_approval_requests(cls, actor: object, arguments: AdminPaymentReadArguments) -> dict[str, object]:
        metadata = _metadata(actor)
        _require_root(actor)
        with db.session.no_autoflush:
            _set_statement_timeout()
            query = _approval_query().filter(PaymentApprovalRequest.status == "pending")
            total, rows = _snapshot_page(query, arguments, name="admin_approval_pending")
        return {
            **metadata,
            "requests": [_approval_projection(row) for row in rows],
            "pagination": _pagination(arguments, total),
            "filters": {"status": "pending"},
        }

    @classmethod
    def my_approval_requests(cls, actor: object, arguments: AdminPaymentReadArguments) -> dict[str, object]:
        metadata = _metadata(actor)
        owner = metadata["owner_context"]
        with db.session.no_autoflush:
            _set_statement_timeout()
            query = _approval_query(requester_id=owner["user_id"])
            total, rows = _snapshot_page(query, arguments, name="admin_approval_mine")
        return {
            **metadata,
            "requests": [_approval_projection(row) for row in rows],
            "pagination": _pagination(arguments, total),
            "filters": {"status": None},
        }

    @classmethod
    def approval_request_detail(cls, actor: object, request_id: int) -> dict[str, object]:
        metadata = _metadata(actor)
        owner = metadata["owner_context"]
        actor_is_root = platform_root_scope(actor)
        if not actor_is_root and getattr(actor, "role", None) not in {"master", "supermaster"}:
            raise AdminPaymentRecordNotFound()
        with db.session.no_autoflush:
            _set_statement_timeout()
            query = _approval_query()
            if not actor_is_root:
                query = query.filter(PaymentApprovalRequest.requested_by == owner["user_id"])
            row = query.filter(PaymentApprovalRequest.id == request_id).one_or_none()
        if row is None:
            raise AdminPaymentRecordNotFound()
        return {**metadata, "request": _approval_projection(row)}

    @classmethod
    def approval_stats(cls, actor: object) -> dict[str, object]:
        metadata = _metadata(actor)
        _require_root(actor)
        with db.session.no_autoflush:
            _set_statement_timeout()
            # One aggregate from the same coherent pending predicate; no money is read.
            pending = _approval_query().filter(PaymentApprovalRequest.status == "pending").with_entities(
                func.count(PaymentApprovalRequest.id)
            ).scalar()
        if isinstance(pending, bool) or not isinstance(pending, int) or pending < 0:
            raise RuntimeError("admin approval pending count was invalid")
        return {**metadata, "pending": pending}
