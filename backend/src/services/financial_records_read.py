"""Bounded read projections for legacy wallet and withdrawal records.

These records are explicitly unverified compatibility data.  This service never
creates, updates, aggregates, or treats any legacy value as payout availability.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from math import ceil
from typing import Any

from sqlalchemy import and_, case, func, or_, select, text, true
from sqlalchemy.orm import aliased, load_only

from src.database import db
from src.models.agent import Agent
from src.models.trading_program import Challenge, TradingProgram
from src.models.user import User
from src.models.wallet import Transaction, Wallet
from src.models.withdrawal import Withdrawal
from src.services.wallet_service import WalletNotFound
from src.utils.hierarchy_scoping import (
    complete_hierarchy_scope,
    platform_root_scope,
    tenant_hierarchy_scope,
)


_MAX_PAGE = 10_000
_MAX_PER_PAGE = 50
_MAX_OFFSET = 10_000
_MAX_QUERY_INTEGER_DIGITS = 10
_BALANCE_TYPES = frozenset({"main", "commission", "bonus"})
_TRANSACTION_TYPES = frozenset({"deposit", "withdrawal", "commission", "bonus", "adjustment"})
_WITHDRAWAL_STATUSES = frozenset({"pending", "approved", "processing", "completed", "rejected"})


class FinancialRecordsQueryInvalid(ValueError):
    """The query is ambiguous, noncanonical, unknown, or out of its fixed bounds."""


class FinancialRecordsTenantRequired(ValueError):
    """The authenticated principal lacks a safe positive tenant context."""


class FinancialRecordsScopeNotAuthorized(ValueError):
    """An admin principal has no explicit, complete hierarchy scope."""


@dataclass(frozen=True)
class FinancialReadArguments:
    """A fully validated bounded page and its sole optional list filter."""

    page: int
    per_page: int
    offset: int
    filter_value: str | None


def _positive_identifier(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _owner_context(actor: object) -> dict[str, int]:
    """Validate the principal before any wallet/withdrawal resource SQL exists."""
    user_id = getattr(actor, "id", None)
    tenant_id = getattr(actor, "tenant_id", None)
    if not (_positive_identifier(user_id) and _positive_identifier(tenant_id)):
        raise FinancialRecordsTenantRequired()
    return {"user_id": user_id, "tenant_id": tenant_id}


def _read_flags(actor: object) -> dict[str, object]:
    return {
        "owner_context": _owner_context(actor),
        "balance_verification": "unverified_legacy",
        "payouts_enabled": False,
        "available_for_payout": None,
        "currency": None,
    }


def _canonical_ascii_integer(raw: object, *, minimum: int, maximum: int) -> int:
    if (
        not isinstance(raw, str)
        or not raw
        or len(raw) > _MAX_QUERY_INTEGER_DIGITS
        or not raw.isascii()
        or not raw.isdecimal()
    ):
        raise FinancialRecordsQueryInvalid()
    value = int(raw)
    if not minimum <= value <= maximum or str(value) != raw:
        raise FinancialRecordsQueryInvalid()
    return value


def parse_financial_query(arguments: Any, *, filter_name: str | None,
                          allowed_filter_values: frozenset[str]) -> FinancialReadArguments:
    """Reject every noncanonical/duplicate/unknown query before resource SQL."""
    allowed_names = {"page", "per_page"}
    if filter_name is not None:
        allowed_names.add(filter_name)
    for name in arguments.keys():
        if name not in allowed_names or len(arguments.getlist(name)) != 1:
            raise FinancialRecordsQueryInvalid()

    page_values = arguments.getlist("page")
    per_page_values = arguments.getlist("per_page")
    page = 1 if not page_values else _canonical_ascii_integer(
        page_values[0], minimum=1, maximum=_MAX_PAGE,
    )
    per_page = 20 if not per_page_values else _canonical_ascii_integer(
        per_page_values[0], minimum=1, maximum=_MAX_PER_PAGE,
    )
    offset = (page - 1) * per_page
    if offset > _MAX_OFFSET:
        raise FinancialRecordsQueryInvalid()

    filter_value = None
    if filter_name is not None:
        values = arguments.getlist(filter_name)
        if values:
            filter_value = values[0]
            if filter_value not in allowed_filter_values:
                raise FinancialRecordsQueryInvalid()
    return FinancialReadArguments(page, per_page, offset, filter_value)


def _apply_postgresql_timeout() -> None:
    """Bound every financial read transaction on PostgreSQL without affecting SQLite."""
    bind = db.session.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        db.session.execute(text("SET LOCAL statement_timeout = 1500"))


def _decimal_string(value: object) -> str | None:
    """Return only finite decimal text; legacy malformed values stay unknown."""
    if value is None:
        return None
    try:
        decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not decimal_value.is_finite():
        return None
    return format(decimal_value, "f")


def _timestamp(value: object) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _identifier(value: object) -> int | None:
    return value if _positive_identifier(value) else None


def _safe_code(value: object, *, allowed: frozenset[str] | None = None,
               maximum_length: int = 50) -> str | None:
    """Prevent legacy free text from being projected as a financial code."""
    if not isinstance(value, str) or not value or len(value) > maximum_length or not value.isascii():
        return None
    if allowed is not None:
        return value if value in allowed else None
    if not all(character.islower() or character.isdigit() or character in {"_", "-"} for character in value):
        return None
    return value


def _wallet_projection(wallet: Wallet) -> dict[str, object]:
    return {
        "id": _identifier(wallet.id),
        "user_id": _identifier(wallet.user_id),
        "main_balance": _decimal_string(wallet.main_balance),
        "commission_balance": _decimal_string(wallet.commission_balance),
        "bonus_balance": _decimal_string(wallet.bonus_balance),
        "is_active": wallet.is_active if isinstance(wallet.is_active, bool) else None,
        "last_transaction_at": _timestamp(wallet.last_transaction_at),
        "created_at": _timestamp(wallet.created_at),
    }


def _transaction_projection(transaction: Transaction) -> dict[str, object]:
    return {
        "id": _identifier(transaction.id),
        "wallet_id": _identifier(transaction.wallet_id),
        "type": _safe_code(transaction.type, allowed=_TRANSACTION_TYPES),
        "balance_type": _safe_code(transaction.balance_type, allowed=_BALANCE_TYPES),
        "amount": _decimal_string(transaction.amount),
        "balance_before": _decimal_string(transaction.balance_before),
        "balance_after": _decimal_string(transaction.balance_after),
        "created_at": _timestamp(transaction.created_at),
    }


def _withdrawal_projection(row: Any) -> dict[str, object]:
    return {
        "id": _identifier(row.id),
        "user_id": _identifier(row.owner_user_id),
        "amount": _decimal_string(row.amount),
        "fee": _decimal_string(row.fee),
        "net_amount": _decimal_string(row.net_amount),
        "payment_method": _safe_code(row.payment_method),
        "status": _safe_code(row.status, allowed=_WITHDRAWAL_STATUSES),
        "created_at": _timestamp(row.created_at),
        "approved_at": _timestamp(row.approved_at),
        "processed_at": _timestamp(row.processed_at),
        "completed_at": _timestamp(row.completed_at),
    }


def _pagination(arguments: FinancialReadArguments, total: int) -> dict[str, int]:
    return {
        "page": arguments.page,
        "per_page": arguments.per_page,
        "total": total,
        "pages": ceil(total / arguments.per_page) if total else 0,
    }


def _snapshot_page(query, arguments: FinancialReadArguments) -> tuple[int, list[Any]]:
    """Return a count and bounded page from one SQL statement snapshot.

    PostgreSQL's READ COMMITTED transaction level gives each statement its own
    snapshot.  A separate ``count()`` and ``all()`` can therefore disagree if a
    legacy record changes between them.  Keep the scoped, allowlisted scalar
    projection in a CTE and derive both the aggregate and the ordered page in
    one statement instead.  The total CTE has exactly one row; the LEFT JOIN
    deliberately preserves that row when an otherwise valid offset is beyond
    the end of the page, yielding a null-ID sentinel and its real total.

    ``MATERIALIZED`` is PostgreSQL-only here: it retains one explicitly shared
    scoped relation without changing SQLite compatibility.  Snapshot coherence
    itself comes from the one statement, not from a transaction-isolation
    change.
    """
    scoped = query.order_by(None).cte(name="financial_scoped")
    scoped = scoped.prefix_with("MATERIALIZED", dialect="postgresql")
    total = (
        select(func.count().label("_financial_total"))
        .select_from(scoped)
        .cte(name="financial_total")
    )
    page = (
        select(*scoped.c)
        .order_by(scoped.c.created_at.desc().nullslast(), scoped.c.id.desc())
        .limit(arguments.per_page)
        .offset(arguments.offset)
        .cte(name="financial_page")
    )
    statement = (
        select(total.c._financial_total, *page.c)
        .select_from(total.outerjoin(page, true()))
        # The scoped projection already contains the direct owner or explicit
        # allowed-user predicates.  Without this outer option, the request
        # hook can append an unrelated non-aliased ``users`` table to the CTE
        # wrapper rather than to the deliberately aliased owner query.
        .execution_options(skip_hierarchy_scope=True)
    )
    records = db.session.execute(statement).all()
    # COUNT without GROUP BY and the LEFT JOIN always supply a total row.
    # A broken driver/result must surface as a read failure, never invented zero.
    if not records:
        raise RuntimeError("Financial snapshot did not return its total row")
    total_value = int(records[0]._mapping["_financial_total"])
    return total_value, [record for record in records if record._mapping["id"] is not None]


def _allowed_user_ids(actor: object):
    """Return the repository's existing explicit root-or-hierarchy owner scope."""
    if not complete_hierarchy_scope(actor):
        raise FinancialRecordsScopeNotAuthorized()
    if platform_root_scope(actor):
        query = db.session.query(User.id)
    elif tenant_hierarchy_scope(actor):
        condition = User.hierarchy_filter_for_entity(actor)
        if condition is None:
            raise FinancialRecordsScopeNotAuthorized()
        query = db.session.query(User.id).filter(condition)
    else:
        raise FinancialRecordsScopeNotAuthorized()
    # The caller applies this exact user-ID subquery to the financial projection.
    # Bypass the request hook only here so it cannot add a non-aliased ``users``
    # criterion beside the two deliberately aliased withdrawal owners.
    return query.execution_options(skip_hierarchy_scope=True).distinct().subquery(name="financial_allowed_users")


def _withdrawal_query(*, actor_owner_id: int | None = None,
                      actor_tenant_id: int | None = None, allowed_users=None):
    """Select only tenant-consistent direct/agent owners and validated challenges."""
    direct_owner = aliased(User, name="financial_direct_owner")
    agent_owner = aliased(User, name="financial_agent_owner")
    challenge = aliased(Challenge, name="financial_withdrawal_challenge")
    program = aliased(TradingProgram, name="financial_withdrawal_program")

    owner_user_id = case(
        (Withdrawal.user_id.isnot(None), direct_owner.id),
        else_=agent_owner.id,
    ).label("owner_user_id")

    def challenge_matches(owner_id, tenant_id):
        return or_(
            Withdrawal.challenge_id.is_(None),
            and_(
                challenge.id.isnot(None),
                program.id.isnot(None),
                challenge.user_id == owner_id,
                program.tenant_id == tenant_id,
            ),
        )

    direct_only = and_(
        Withdrawal.user_id.isnot(None),
        Withdrawal.agent_id.is_(None),
        direct_owner.id.isnot(None),
        direct_owner.tenant_id.isnot(None),
        challenge_matches(direct_owner.id, direct_owner.tenant_id),
    )
    agent_only = and_(
        Withdrawal.user_id.is_(None),
        Withdrawal.agent_id.isnot(None),
        Agent.id.isnot(None),
        Agent.user_id.isnot(None),
        agent_owner.id.isnot(None),
        agent_owner.tenant_id.isnot(None),
        challenge_matches(agent_owner.id, agent_owner.tenant_id),
    )
    both_owners = and_(
        Withdrawal.user_id.isnot(None),
        Withdrawal.agent_id.isnot(None),
        direct_owner.id.isnot(None),
        Agent.id.isnot(None),
        Agent.user_id.isnot(None),
        agent_owner.id.isnot(None),
        direct_owner.id == agent_owner.id,
        direct_owner.tenant_id.isnot(None),
        direct_owner.tenant_id == agent_owner.tenant_id,
        challenge_matches(direct_owner.id, direct_owner.tenant_id),
    )

    query = (
        db.session.query(
            Withdrawal.id,
            owner_user_id,
            Withdrawal.amount,
            Withdrawal.fee,
            Withdrawal.net_amount,
            Withdrawal.payment_method,
            Withdrawal.status,
            Withdrawal.created_at,
            Withdrawal.approved_at,
            Withdrawal.processed_at,
            Withdrawal.completed_at,
        )
        .outerjoin(direct_owner, Withdrawal.user_id == direct_owner.id)
        .outerjoin(Agent, Withdrawal.agent_id == Agent.id)
        .outerjoin(agent_owner, Agent.user_id == agent_owner.id)
        .outerjoin(challenge, Withdrawal.challenge_id == challenge.id)
        .outerjoin(program, challenge.program_id == program.id)
        .filter(
            Withdrawal.status.in_(_WITHDRAWAL_STATUSES),
            or_(direct_only, agent_only, both_owners),
        )
        # All owner/tenant/challenge predicates are explicit above.  The request
        # hierarchy hook cannot safely infer them through these aliases.
        .execution_options(skip_hierarchy_scope=True)
    )
    owner_tenant_id = case(
        (Withdrawal.user_id.isnot(None), direct_owner.tenant_id),
        else_=agent_owner.tenant_id,
    )
    if actor_owner_id is not None:
        query = query.filter(
            owner_user_id == actor_owner_id,
            owner_tenant_id == actor_tenant_id,
        )
    if allowed_users is not None:
        query = query.join(allowed_users, owner_user_id == allowed_users.c.id)
    return query


class FinancialRecordsReadService:
    """The only read path used by the UI-4 legacy financial endpoints."""

    @staticmethod
    def parse_balance_query(arguments: Any) -> FinancialReadArguments:
        if list(arguments.keys()):
            raise FinancialRecordsQueryInvalid()
        return FinancialReadArguments(page=1, per_page=20, offset=0, filter_value=None)

    @staticmethod
    def parse_admin_wallets_query(arguments: Any) -> FinancialReadArguments:
        return parse_financial_query(arguments, filter_name=None, allowed_filter_values=frozenset())

    @staticmethod
    def parse_transactions_query(arguments: Any) -> FinancialReadArguments:
        return parse_financial_query(arguments, filter_name="balance_type", allowed_filter_values=_BALANCE_TYPES)

    @staticmethod
    def parse_withdrawals_query(arguments: Any) -> FinancialReadArguments:
        return parse_financial_query(arguments, filter_name="status", allowed_filter_values=_WITHDRAWAL_STATUSES)

    @staticmethod
    def wallet_balance(actor: object) -> dict[str, object]:
        flags = _read_flags(actor)
        owner = flags["owner_context"]
        with db.session.no_autoflush:
            _apply_postgresql_timeout()
            wallet = (
                db.session.query(Wallet)
                .options(load_only(
                    Wallet.id, Wallet.user_id, Wallet.main_balance, Wallet.commission_balance,
                    Wallet.bonus_balance, Wallet.is_active, Wallet.last_transaction_at, Wallet.created_at,
                ))
                .join(User, Wallet.user_id == User.id)
                .filter(
                    Wallet.user_id == owner["user_id"],
                    User.id == owner["user_id"],
                    User.tenant_id == owner["tenant_id"],
                )
                .one_or_none()
            )
        if wallet is None:
            raise WalletNotFound()
        return {**flags, "wallet": _wallet_projection(wallet)}

    @staticmethod
    def wallet_transactions(actor: object, arguments: FinancialReadArguments) -> dict[str, object]:
        flags = _read_flags(actor)
        owner = flags["owner_context"]
        with db.session.no_autoflush:
            _apply_postgresql_timeout()
            wallet = (
                db.session.query(Wallet)
                .options(load_only(Wallet.id, Wallet.user_id))
                .join(User, Wallet.user_id == User.id)
                .filter(
                    Wallet.user_id == owner["user_id"],
                    User.id == owner["user_id"],
                    User.tenant_id == owner["tenant_id"],
                )
                .one_or_none()
            )
            if wallet is None:
                raise WalletNotFound()
            query = (
                db.session.query(
                    Transaction.id.label("id"),
                    Transaction.wallet_id.label("wallet_id"),
                    Transaction.type.label("type"),
                    Transaction.balance_type.label("balance_type"),
                    Transaction.amount.label("amount"),
                    Transaction.balance_before.label("balance_before"),
                    Transaction.balance_after.label("balance_after"),
                    Transaction.created_at.label("created_at"),
                )
                .filter(
                    Transaction.wallet_id == wallet.id,
                    Transaction.balance_type.in_(_BALANCE_TYPES),
                    Transaction.type.in_(_TRANSACTION_TYPES),
                )
            )
            if arguments.filter_value is not None:
                query = query.filter(Transaction.balance_type == arguments.filter_value)
            total, transactions = _snapshot_page(query, arguments)
        return {
            **flags,
            "wallet_id": _identifier(wallet.id),
            "transactions": [_transaction_projection(transaction) for transaction in transactions],
            "pagination": _pagination(arguments, total),
            "filters": {"balance_type": arguments.filter_value},
        }

    @staticmethod
    def withdrawals_for_owner(actor: object, arguments: FinancialReadArguments) -> dict[str, object]:
        flags = _read_flags(actor)
        owner = flags["owner_context"]
        with db.session.no_autoflush:
            _apply_postgresql_timeout()
            query = _withdrawal_query(
                actor_owner_id=owner["user_id"], actor_tenant_id=owner["tenant_id"],
            )
            if arguments.filter_value is not None:
                query = query.filter(Withdrawal.status == arguments.filter_value)
            total, rows = _snapshot_page(query, arguments)
        return {
            **flags,
            "withdrawals": [_withdrawal_projection(row) for row in rows],
            "pagination": _pagination(arguments, total),
            "filters": {"status": arguments.filter_value},
        }

    @staticmethod
    def admin_wallets(actor: object, arguments: FinancialReadArguments) -> dict[str, object]:
        flags = _read_flags(actor)
        with db.session.no_autoflush:
            _apply_postgresql_timeout()
            allowed_users = _allowed_user_ids(actor)
            query = (
                db.session.query(
                    Wallet.id.label("id"),
                    Wallet.user_id.label("user_id"),
                    Wallet.main_balance.label("main_balance"),
                    Wallet.commission_balance.label("commission_balance"),
                    Wallet.bonus_balance.label("bonus_balance"),
                    Wallet.is_active.label("is_active"),
                    Wallet.last_transaction_at.label("last_transaction_at"),
                    Wallet.created_at.label("created_at"),
                )
                .join(User, Wallet.user_id == User.id)
                .join(allowed_users, User.id == allowed_users.c.id)
            )
            total, wallets = _snapshot_page(query, arguments)
        return {
            **flags,
            "wallets": [_wallet_projection(wallet) for wallet in wallets],
            "pagination": _pagination(arguments, total),
        }

    @staticmethod
    def admin_withdrawals(actor: object, arguments: FinancialReadArguments) -> dict[str, object]:
        flags = _read_flags(actor)
        with db.session.no_autoflush:
            _apply_postgresql_timeout()
            allowed_users = _allowed_user_ids(actor)
            # Keep the explicit owner-scope join inside the projection builder;
            # no User names, email addresses, or relationship serializers enter
            # this response.
            query = _withdrawal_query(allowed_users=allowed_users)
            if arguments.filter_value is not None:
                query = query.filter(Withdrawal.status == arguments.filter_value)
            total, rows = _snapshot_page(query, arguments)
        return {
            **flags,
            "withdrawals": [_withdrawal_projection(row) for row in rows],
            "pagination": _pagination(arguments, total),
            "filters": {"status": arguments.filter_value},
        }
