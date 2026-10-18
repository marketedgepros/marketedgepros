"""Tenant-safe, bounded admin challenge closure reads and mutation gates.

Persisted challenge and MT5 values are legacy snapshots.  This service does not
calculate an outcome, infer a payment entitlement, call a provider, or mutate a
challenge.  It is the single admin read boundary used by ``routes/challenges``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from math import ceil
from typing import Any

from sqlalchemy import and_, func, select, text, true
from sqlalchemy.orm import aliased

from src.database import db
from src.models.mt5_models import MT5Account
from src.models.trading_program import Challenge, TradingProgram
from src.models.user import User
from src.utils.hierarchy_scoping import (
    complete_hierarchy_scope,
    platform_root_scope,
    tenant_hierarchy_scope,
)


_UNVERIFIED_LEGACY = "unverified_legacy"
_MAX_PAGE = 1000
_MAX_PER_PAGE = 100
_MAX_OFFSET = 10_000
_MAX_INTEGER_DIGITS = 10
_MAX_CHALLENGE_ID = 2_147_483_647


class AdminClosureChallengesQueryInvalid(ValueError):
    """The admin challenge query is unknown, duplicate, or outside fixed bounds."""


class AdminClosureChallengesPaginationInvalid(AdminClosureChallengesQueryInvalid):
    """The requested page/per-page pair is noncanonical or beyond a fixed bound."""


class AdminClosureChallengesScopeRequired(PermissionError):
    """The authenticated administrator lacks a coherent root or tenant scope."""


class AdminClosureChallengeNotFound(LookupError):
    """The requested challenge does not exist in the caller's permitted scope."""


@dataclass(frozen=True)
class AdminClosureChallengeMutationUnavailable(Exception):
    """A legacy mutation has no authoritative operation behind it."""

    message: str
    code: str
    status: int = 503


@dataclass(frozen=True)
class AdminClosureChallengeListArguments:
    page: int
    per_page: int
    offset: int
    status: str | None
    include_mt5: bool


@dataclass(frozen=True)
class AdminClosureChallengeDetailArguments:
    include_mt5: bool


def _positive_identifier(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value <= _MAX_CHALLENGE_ID


def _canonical_positive_integer(raw: object, *, minimum: int, maximum: int) -> int:
    if (
        not isinstance(raw, str)
        or not raw
        or len(raw) > _MAX_INTEGER_DIGITS
        or not raw.isascii()
        or not raw.isdecimal()
    ):
        raise AdminClosureChallengesPaginationInvalid()
    value = int(raw)
    if not minimum <= value <= maximum or str(value) != raw:
        raise AdminClosureChallengesPaginationInvalid()
    return value


def _parse_include_mt5(arguments: Any) -> bool:
    values = arguments.getlist("include_mt5")
    if not values:
        return True
    if len(values) != 1 or values[0] not in {"true", "false"}:
        raise AdminClosureChallengesQueryInvalid()
    return values[0] == "true"


def _parse_status(arguments: Any) -> str | None:
    values = arguments.getlist("status")
    if not values:
        return None
    if len(values) != 1:
        raise AdminClosureChallengesQueryInvalid()
    value = values[0]
    # It remains a recorded legacy label, not an enum that could imply policy.
    if not isinstance(value, str) or not value or len(value) > 20 or not value.strip():
        raise AdminClosureChallengesQueryInvalid()
    return value


def _owner_context(actor: object) -> dict[str, int]:
    user_id = getattr(actor, "id", None)
    tenant_id = getattr(actor, "tenant_id", None)
    if not (_positive_identifier(user_id) and _positive_identifier(tenant_id)):
        raise AdminClosureChallengesScopeRequired()
    return {"user_id": user_id, "tenant_id": tenant_id}


def _metadata(actor: object) -> dict[str, object]:
    return {
        "owner_context": _owner_context(actor),
        "data_status": _UNVERIFIED_LEGACY,
        "provider_authenticated": False,
    }


def _set_statement_timeout() -> None:
    """Bound PostgreSQL read work without issuing unsupported SQLite SQL."""
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


def _text_or_null(value: object, maximum: int) -> str | None:
    if not isinstance(value, str) or not value or len(value) > maximum:
        return None
    if any(ord(character) < 32 and character not in {"\n", "\t"} for character in value):
        return None
    return value


def _allowed_user_ids(actor: object):
    """Build root-or-tenant/downline authorization before any challenge SQL."""
    _owner_context(actor)
    if not complete_hierarchy_scope(actor):
        raise AdminClosureChallengesScopeRequired()
    if platform_root_scope(actor):
        predicate = and_(User.tenant_id.is_not(None), User.tenant_id > 0)
    elif tenant_hierarchy_scope(actor):
        predicate = User.hierarchy_filter_for_entity(actor)
        if predicate is None:
            raise AdminClosureChallengesScopeRequired()
        predicate = and_(predicate, User.tenant_id == actor.tenant_id)
    else:
        raise AdminClosureChallengesScopeRequired()
    return (
        select(User.id.label("id"))
        .where(predicate)
        .distinct()
        .cte("admin_closure_challenge_allowed_users")
        .prefix_with("MATERIALIZED", dialect="postgresql")
    )


def _challenge_select(actor: object):
    """Select only coherent challenge/user/program legacy fields in scope."""
    allowed_users = _allowed_user_ids(actor)
    owner = aliased(User, name="admin_closure_challenge_owner")
    program = aliased(TradingProgram, name="admin_closure_challenge_program")
    # A foreign account binding is not proof of ownership.  Hide the challenge
    # completely rather than presenting it as an unlinked account.
    bound_challenge = aliased(Challenge, name="admin_closure_bound_challenge")
    foreign_binding_ids = select(MT5Account.challenge_id).join(
        bound_challenge, MT5Account.challenge_id == bound_challenge.id
    ).where(MT5Account.user_id != bound_challenge.user_id)
    return (
        select(
            Challenge.id.label("id"),
            Challenge.user_id.label("user_id"),
            Challenge.status.label("legacy_status"),
            Challenge.payment_status.label("legacy_payment_status"),
            Challenge.current_phase.label("current_phase"),
            Challenge.total_phases.label("total_phases"),
            Challenge.initial_balance.label("initial_balance"),
            Challenge.current_balance.label("current_balance"),
            Challenge.max_drawdown.label("max_drawdown_observed"),
            Challenge.start_date.label("start_date"),
            Challenge.end_date.label("end_date"),
            Challenge.passed_at.label("passed_at"),
            Challenge.created_at.label("created_at"),
            owner.id.label("owner_id"),
            owner.first_name.label("owner_first_name"),
            owner.last_name.label("owner_last_name"),
            owner.email.label("owner_email"),
            program.id.label("program_id"),
            program.name.label("program_name"),
        )
        .select_from(Challenge)
        .join(owner, Challenge.user_id == owner.id)
        .join(allowed_users, owner.id == allowed_users.c.id)
        .join(program, Challenge.program_id == program.id)
        .where(
            owner.tenant_id.is_not(None),
            owner.tenant_id > 0,
            program.tenant_id == owner.tenant_id,
            ~Challenge.id.in_(foreign_binding_ids),
        )
        .execution_options(skip_hierarchy_scope=True, autoflush=False)
    )


def _snapshot_page(statement, arguments: AdminClosureChallengeListArguments) -> tuple[int, list[Any]]:
    """Return the count and ordered page from one CTE-backed SQL statement."""
    scoped = statement.order_by(None).cte("admin_closure_challenge_scoped")
    scoped = scoped.prefix_with("MATERIALIZED", dialect="postgresql")
    total = select(func.count().label("_total")).select_from(scoped).cte("admin_closure_challenge_total")
    page = (
        select(*scoped.c)
        .order_by(scoped.c.created_at.desc().nullslast(), scoped.c.id.desc())
        .limit(arguments.per_page)
        .offset(arguments.offset)
        .cte("admin_closure_challenge_page")
    )
    result = db.session.execute(
        select(total.c._total, *page.c)
        .select_from(total.outerjoin(page, true()))
        .execution_options(skip_hierarchy_scope=True, autoflush=False)
    ).all()
    if not result:
        raise RuntimeError("admin challenge snapshot did not return a total row")
    total_value = result[0]._mapping["_total"]
    if isinstance(total_value, bool) or not isinstance(total_value, int) or total_value < 0:
        raise RuntimeError("admin challenge snapshot returned an invalid total")
    return total_value, [row for row in result if row._mapping["id"] is not None]


def _mt5_accounts_for_rows(rows: list[Any]) -> dict[int, list[MT5Account]]:
    ids = [row._mapping["id"] for row in rows]
    if not ids:
        return {}
    # Two rows per visible challenge are sufficient to detect every ambiguous
    # binding. The extra row catches an impossible unbounded legacy fan-out.
    bound = len(ids) * 2 + 1
    accounts = db.session.execute(
        select(MT5Account)
        .join(Challenge, MT5Account.challenge_id == Challenge.id)
        .where(
            MT5Account.challenge_id.in_(ids),
            MT5Account.user_id == Challenge.user_id,
        )
        .order_by(MT5Account.challenge_id, MT5Account.id)
        .limit(bound)
        .execution_options(skip_hierarchy_scope=True, autoflush=False)
    ).scalars().all()
    if len(accounts) >= bound:
        raise RuntimeError("admin challenge MT5 binding exceeded its fixed bound")
    result: dict[int, list[MT5Account]] = {}
    for account in accounts:
        if account.challenge_id is not None:
            result.setdefault(account.challenge_id, []).append(account)
    return result


def _mt5_projection(account: MT5Account) -> dict[str, object]:
    return {
        "login": _text_or_null(account.mt5_login, 50),
        "server": _text_or_null(account.mt5_server, 100),
        "group": _text_or_null(account.mt5_group, 100),
        "status": _text_or_null(account.status, 20),
        "balance": _decimal_string(account.balance),
        "equity": _decimal_string(account.equity),
        "margin": _decimal_string(account.margin),
        "free_margin": _decimal_string(account.free_margin),
        "margin_level": _decimal_string(account.margin_level),
        "updated_at": _timestamp(account.updated_at),
        "data_status": _UNVERIFIED_LEGACY,
        "provider_authenticated": False,
    }


def _row_projection(row: Any, accounts: list[MT5Account], include_mt5: bool) -> dict[str, object]:
    source = row._mapping
    if source["owner_id"] != source["user_id"]:
        raise RuntimeError("admin challenge owner projection was incoherent")
    first_name = _text_or_null(source["owner_first_name"], 255)
    last_name = _text_or_null(source["owner_last_name"], 255)
    name = " ".join(part for part in (first_name, last_name) if part) or None
    item = {
        "id": source["id"],
        "user_id": source["user_id"],
        "program": {
            "id": source["program_id"],
            "name": _text_or_null(source["program_name"], 255),
        },
        "user": {
            "id": source["owner_id"],
            "name": name,
            "email": _text_or_null(source["owner_email"], 255),
        },
        "legacy_status": _text_or_null(source["legacy_status"], 20),
        "legacy_payment_status": _text_or_null(source["legacy_payment_status"], 20),
        "current_phase": source["current_phase"] if isinstance(source["current_phase"], int) and source["current_phase"] >= 0 else None,
        "total_phases": source["total_phases"] if isinstance(source["total_phases"], int) and source["total_phases"] >= 0 else None,
        "initial_balance": _decimal_string(source["initial_balance"]),
        "current_balance": _decimal_string(source["current_balance"]),
        "max_drawdown_observed": _decimal_string(source["max_drawdown_observed"]),
        "start_date": _timestamp(source["start_date"]),
        "end_date": _timestamp(source["end_date"]),
        "passed_at": _timestamp(source["passed_at"]),
        "created_at": _timestamp(source["created_at"]),
        "data_status": _UNVERIFIED_LEGACY,
        "provider_authenticated": False,
    }
    if not include_mt5:
        item.update({"mt5_account_binding": "not_requested", "mt5_account": None})
    elif len(accounts) == 1:
        item.update({"mt5_account_binding": "single_unverified_legacy", "mt5_account": _mt5_projection(accounts[0])})
    elif len(accounts) > 1:
        item.update({"mt5_account_binding": "ambiguous", "mt5_account": None})
    else:
        item.update({"mt5_account_binding": "not_linked", "mt5_account": None})
    return item


class AdminClosureChallengesService:
    """The only admin closure read/mutation-boundary implementation for challenges."""

    @staticmethod
    def parse_list_query(arguments: Any) -> AdminClosureChallengeListArguments:
        allowed = {"page", "per_page", "status", "include_mt5"}
        if any(name not in allowed or len(arguments.getlist(name)) != 1 for name in arguments.keys()):
            raise AdminClosureChallengesQueryInvalid()
        page_values = arguments.getlist("page")
        per_page_values = arguments.getlist("per_page")
        page = 1 if not page_values else _canonical_positive_integer(page_values[0], minimum=1, maximum=_MAX_PAGE)
        per_page = 20 if not per_page_values else _canonical_positive_integer(
            per_page_values[0], minimum=1, maximum=_MAX_PER_PAGE,
        )
        offset = (page - 1) * per_page
        if offset > _MAX_OFFSET:
            raise AdminClosureChallengesPaginationInvalid()
        return AdminClosureChallengeListArguments(page, per_page, offset, _parse_status(arguments), _parse_include_mt5(arguments))

    @staticmethod
    def parse_detail_query(arguments: Any) -> AdminClosureChallengeDetailArguments:
        if any(name != "include_mt5" or len(arguments.getlist(name)) != 1 for name in arguments.keys()):
            raise AdminClosureChallengesQueryInvalid()
        return AdminClosureChallengeDetailArguments(_parse_include_mt5(arguments))

    @classmethod
    def list(cls, actor: object, arguments: AdminClosureChallengeListArguments) -> dict[str, object]:
        metadata = _metadata(actor)
        with db.session.no_autoflush:
            _set_statement_timeout()
            statement = _challenge_select(actor)
            if arguments.status is not None:
                statement = statement.where(Challenge.status == arguments.status)
            total, rows = _snapshot_page(statement, arguments)
            accounts_by_challenge = _mt5_accounts_for_rows(rows) if arguments.include_mt5 else {}
        challenges = [
            _row_projection(row, accounts_by_challenge.get(row._mapping["id"], []), arguments.include_mt5)
            for row in rows
        ]
        return {
            **metadata,
            "filters": {"status": arguments.status, "include_mt5": arguments.include_mt5},
            "challenges": challenges,
            "pagination": {
                "page": arguments.page,
                "per_page": arguments.per_page,
                "total": total,
                "pages": ceil(total / arguments.per_page) if total else 0,
            },
        }

    @classmethod
    def detail(cls, actor: object, challenge_id: int, arguments: AdminClosureChallengeDetailArguments) -> dict[str, object]:
        if not _positive_identifier(challenge_id):
            raise AdminClosureChallengeNotFound()
        metadata = _metadata(actor)
        with db.session.no_autoflush:
            _set_statement_timeout()
            row = db.session.execute(
                _challenge_select(actor)
                .where(Challenge.id == challenge_id)
                .execution_options(skip_hierarchy_scope=True, autoflush=False)
            ).one_or_none()
            if row is None:
                raise AdminClosureChallengeNotFound()
            accounts = _mt5_accounts_for_rows([row]).get(challenge_id, []) if arguments.include_mt5 else []
        return {
            **metadata,
            "filters": {"include_mt5": arguments.include_mt5},
            "challenge": _row_projection(row, accounts, arguments.include_mt5),
        }

    @staticmethod
    def refuse_unverified_mutation(kind: str) -> AdminClosureChallengeMutationUnavailable:
        """Return a fixed refusal before request-body parsing or resource SQL."""
        messages = {
            "order_settlement": ("Order settlement is not configured", "ORDER_SETTLEMENT_NOT_CONFIGURED"),
            "trading_evidence": ("Verified trading evidence integration is not configured", "TRADING_EVIDENCE_NOT_CONFIGURED"),
            "provider": ("MT5 provider is not configured", "MT5_PROVIDER_NOT_CONFIGURED"),
        }
        message, code = messages.get(kind, messages["trading_evidence"])
        return AdminClosureChallengeMutationUnavailable(message=message, code=code)
