"""Read-only, hierarchy-scoped UI-4 admin insight projections.

This service intentionally exposes record counts and a tightly bounded set of legacy
record scalars only.  It neither calculates financial aggregates nor makes identity,
settlement, provider, or entitlement decisions.  Each successful projection is built
from one CTE/UNION SQL statement, so counts, distributions, recent rows, and daily
activity observe the same database statement snapshot.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    Numeric,
    String,
    and_,
    case,
    cast,
    func,
    literal,
    null,
    or_,
    select,
    text,
    union_all,
)
from sqlalchemy.orm import aliased

from src.database import db
from src.models.payment import Payment
from src.models.trading_program import Challenge, TradingProgram
from src.models.user import User
from src.utils.hierarchy_scoping import (
    complete_hierarchy_scope,
    platform_root_scope,
    tenant_hierarchy_scope,
)


_ALLOWED_DAYS = frozenset({7, 30, 90, 180, 365})
_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_MAX_INTEGER_DIGITS = 10
_RECENT_LIMIT = 5
_USER_ROLES = ("supermaster", "master", "affiliate", "trader", "guest")
_KYC_STATUSES = (
    "not_submitted", "pending", "approved", "rejected", "incomplete", "verified", "unverified",
)
_CHALLENGE_STATUSES = ("pending", "active", "completed", "passed", "failed", "funded", "cancelled")
_PAYMENT_STATUSES = ("pending", "completed", "failed", "refunded")
_PAYMENT_TYPES = ("challenge_purchase", "withdrawal", "refund")


class AdminInsightsQueryInvalid(ValueError):
    """The query is duplicate, noncanonical, unknown, or outside fixed bounds."""


class AdminInsightsScopeRequired(PermissionError):
    """The principal lacks a positive tenant or a coherent permitted hierarchy."""


def _positive_identifier(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _owner_context(actor: object) -> dict[str, int]:
    user_id = getattr(actor, "id", None)
    tenant_id = getattr(actor, "tenant_id", None)
    if not (_positive_identifier(user_id) and _positive_identifier(tenant_id)):
        raise AdminInsightsScopeRequired()
    return {"user_id": user_id, "tenant_id": tenant_id}


def _metadata(actor: object, *, as_of: datetime, days: int | None) -> dict[str, object]:
    return {
        "owner_context": _owner_context(actor),
        "record_verification": "unverified_legacy",
        "settlement_enabled": False,
        "as_of": as_of.isoformat() + "Z",
        "filters": {"days": days},
    }


def _set_statement_timeout() -> None:
    """Bound PostgreSQL work without issuing unsupported SQLite syntax."""
    bind = db.session.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        db.session.execute(text("SET LOCAL statement_timeout = 1500"))


def _parse_days(arguments: Any) -> int:
    """Accept only the one canonical ``days`` query value before resource SQL."""
    for name in arguments.keys():
        if name != "days" or len(arguments.getlist(name)) != 1:
            raise AdminInsightsQueryInvalid()
    values = arguments.getlist("days")
    if not values:
        return 30
    raw = values[0]
    if (
        not isinstance(raw, str)
        or not raw
        or len(raw) > _MAX_INTEGER_DIGITS
        or not raw.isascii()
        or not raw.isdecimal()
    ):
        raise AdminInsightsQueryInvalid()
    value = int(raw)
    if str(value) != raw or value not in _ALLOWED_DAYS:
        raise AdminInsightsQueryInvalid()
    return value


def _parse_dashboard(arguments: Any) -> None:
    """The dashboard endpoint is deliberately parameterless."""
    if any(True for _name in arguments.keys()):
        raise AdminInsightsQueryInvalid()


def _allowed_users(actor: object):
    """Build the sole explicit root-or-tenant/downline predicate before records SQL."""
    # Owner metadata validates the positive tenant first.  This check preserves the
    # existing hierarchy helper as the source of truth for root/downline eligibility.
    _owner_context(actor)
    if not complete_hierarchy_scope(actor):
        raise AdminInsightsScopeRequired()
    if platform_root_scope(actor):
        predicate = and_(User.tenant_id.is_not(None), User.tenant_id > 0)
    elif tenant_hierarchy_scope(actor):
        predicate = User.hierarchy_filter_for_entity(actor)
        if predicate is None:
            raise AdminInsightsScopeRequired()
        predicate = and_(predicate, User.tenant_id == actor.tenant_id)
    else:
        raise AdminInsightsScopeRequired()
    return (
        select(User.id.label("id"))
        .where(predicate)
        .distinct()
        .cte("admin_insight_allowed_users")
        .prefix_with("MATERIALIZED", dialect="postgresql")
    )


def _materialized(statement, name: str):
    return statement.cte(name).prefix_with("MATERIALIZED", dialect="postgresql")


def _known_code(column, allowed: tuple[str, ...]):
    return case((column.in_(allowed), column), else_=None)


def _created_predicate(column, *, as_of: datetime, start: datetime | None):
    # Dashboard counts tolerate a legacy null date but never include an observed
    # future date.  Analytics is a bounded UTC calendar window and requires a date.
    if start is None:
        return or_(column.is_(None), column <= as_of)
    return and_(column.is_not(None), column >= start, column <= as_of)


def _normalized_sources(actor: object, *, as_of: datetime, start: datetime | None):
    allowed_users = _allowed_users(actor)
    owner = aliased(User, name="admin_insight_owner")
    program = aliased(TradingProgram, name="admin_insight_program")

    users = _materialized(
        select(
            User.id.label("id"),
            _known_code(User.role, _USER_ROLES).label("role"),
            User.is_active.label("is_active"),
            _known_code(User.kyc_status, _KYC_STATUSES).label("kyc_status"),
            User.created_at.label("created_at"),
        )
        .join(allowed_users, User.id == allowed_users.c.id)
        .where(
            User.tenant_id.is_not(None),
            User.tenant_id > 0,
            _created_predicate(User.created_at, as_of=as_of, start=start),
        ),
        "admin_insight_users",
    )
    challenges = _materialized(
        select(
            Challenge.id.label("id"),
            _known_code(Challenge.status, _CHALLENGE_STATUSES).label("status"),
            Challenge.created_at.label("created_at"),
        )
        .select_from(Challenge)
        .join(owner, Challenge.user_id == owner.id)
        .join(allowed_users, owner.id == allowed_users.c.id)
        .join(program, Challenge.program_id == program.id)
        .where(
            owner.tenant_id.is_not(None),
            owner.tenant_id > 0,
            program.tenant_id == owner.tenant_id,
            _created_predicate(Challenge.created_at, as_of=as_of, start=start),
        ),
        "admin_insight_challenges",
    )
    payments = _materialized(
        select(
            Payment.id.label("id"),
            Payment.user_id.label("user_id"),
            Payment.amount.label("amount"),
            Payment.currency.label("currency"),
            _known_code(Payment.purpose, _PAYMENT_TYPES).label("payment_type"),
            _known_code(Payment.status, _PAYMENT_STATUSES).label("status"),
            Payment.created_at.label("created_at"),
        )
        .select_from(Payment)
        .join(owner, Payment.user_id == owner.id)
        .join(allowed_users, owner.id == allowed_users.c.id)
        .where(
            owner.tenant_id.is_not(None),
            owner.tenant_id > 0,
            _created_predicate(Payment.created_at, as_of=as_of, start=start),
        ),
        "admin_insight_payments",
    )
    return users, challenges, payments


def _empty_output_column(column_type):
    return cast(null(), column_type)


def _output_select(
    *,
    kind: str,
    collection: str,
    code=None,
    count=None,
    identifier=None,
    user_id=None,
    role=None,
    is_active=None,
    kyc_status=None,
    amount=None,
    currency=None,
    payment_type=None,
    status=None,
    created_at=None,
    activity_date=None,
    daily_users=None,
    daily_challenges=None,
    daily_payments=None,
):
    """Give every UNION arm the same bounded, non-PII record schema."""
    return select(
        literal(kind, type_=String()).label("kind"),
        literal(collection, type_=String()).label("collection"),
        (code if code is not None else _empty_output_column(String())).label("code"),
        (count if count is not None else _empty_output_column(Integer())).label("count"),
        (identifier if identifier is not None else _empty_output_column(Integer())).label("id"),
        (user_id if user_id is not None else _empty_output_column(Integer())).label("user_id"),
        (role if role is not None else _empty_output_column(String())).label("role"),
        (is_active if is_active is not None else _empty_output_column(Boolean())).label("is_active"),
        (kyc_status if kyc_status is not None else _empty_output_column(String())).label("kyc_status"),
        (amount if amount is not None else _empty_output_column(Numeric())).label("amount"),
        (currency if currency is not None else _empty_output_column(String())).label("currency"),
        (payment_type if payment_type is not None else _empty_output_column(String())).label("payment_type"),
        (status if status is not None else _empty_output_column(String())).label("status"),
        (created_at if created_at is not None else _empty_output_column(DateTime())).label("created_at"),
        (activity_date if activity_date is not None else _empty_output_column(String())).label("activity_date"),
        (daily_users if daily_users is not None else _empty_output_column(Integer())).label("daily_users"),
        (daily_challenges if daily_challenges is not None else _empty_output_column(Integer())).label("daily_challenges"),
        (daily_payments if daily_payments is not None else _empty_output_column(Integer())).label("daily_payments"),
    )


def _distribution_output(source, *, collection: str, name: str):
    distribution = _materialized(
        select(source.c.code.label("code"), func.count(source.c.id).label("count"))
        .group_by(source.c.code),
        name,
    )
    return _output_select(
        kind="distribution", collection=collection, code=distribution.c.code, count=distribution.c.count,
    ).select_from(distribution)


def _count_output(source, collection: str):
    return _output_select(kind="count", collection=collection, count=func.count(source.c.id)).select_from(source)


def _dashboard_recent_outputs(users, payments):
    ranked_users = _materialized(
        select(
            users.c.id,
            users.c.role,
            users.c.is_active,
            users.c.kyc_status,
            users.c.created_at,
            func.row_number().over(
                order_by=(users.c.created_at.desc().nullslast(), users.c.id.desc())
            ).label("row_number"),
        ),
        "admin_insight_ranked_users",
    )
    ranked_payments = _materialized(
        select(
            payments.c.id,
            payments.c.user_id,
            payments.c.amount,
            payments.c.currency,
            payments.c.payment_type,
            payments.c.status,
            payments.c.created_at,
            func.row_number().over(
                order_by=(payments.c.created_at.desc().nullslast(), payments.c.id.desc())
            ).label("row_number"),
        ),
        "admin_insight_ranked_payments",
    )
    recent_users = _output_select(
        kind="recent_user",
        collection="recent_users",
        identifier=ranked_users.c.id,
        role=ranked_users.c.role,
        is_active=ranked_users.c.is_active,
        kyc_status=ranked_users.c.kyc_status,
        created_at=ranked_users.c.created_at,
    ).select_from(ranked_users).where(ranked_users.c.row_number <= _RECENT_LIMIT)
    recent_payments = _output_select(
        kind="recent_payment",
        collection="recent_payments",
        identifier=ranked_payments.c.id,
        user_id=ranked_payments.c.user_id,
        amount=ranked_payments.c.amount,
        currency=ranked_payments.c.currency,
        payment_type=ranked_payments.c.payment_type,
        status=ranked_payments.c.status,
        created_at=ranked_payments.c.created_at,
    ).select_from(ranked_payments).where(ranked_payments.c.row_number <= _RECENT_LIMIT)
    return recent_users, recent_payments


def _calendar(start: datetime, days: int):
    # A fixed maximum of 365 literal dates avoids database-specific generate_series
    # while keeping the entire calendar in the one read statement.
    first = start.date()
    days_selects = [
        select(literal((first + timedelta(days=offset)).isoformat(), type_=String()).label("activity_date"))
        for offset in range(days)
    ]
    return union_all(*days_selects).cte("admin_insight_calendar")


def _daily_output(users, challenges, payments, *, start: datetime, days: int):
    calendar = _calendar(start, days)

    def aggregate(source, name: str):
        return _materialized(
            select(
                cast(func.date(source.c.created_at), String()).label("activity_date"),
                func.count(source.c.id).label("count"),
            )
            .group_by(cast(func.date(source.c.created_at), String())),
            name,
        )

    daily_users = aggregate(users, "admin_insight_daily_users")
    daily_challenges = aggregate(challenges, "admin_insight_daily_challenges")
    daily_payments = aggregate(payments, "admin_insight_daily_payments")
    daily = _materialized(
        select(
            calendar.c.activity_date,
            func.coalesce(daily_users.c.count, 0).label("users"),
            func.coalesce(daily_challenges.c.count, 0).label("challenges"),
            func.coalesce(daily_payments.c.count, 0).label("payments"),
        )
        .select_from(calendar)
        .outerjoin(daily_users, daily_users.c.activity_date == calendar.c.activity_date)
        .outerjoin(daily_challenges, daily_challenges.c.activity_date == calendar.c.activity_date)
        .outerjoin(daily_payments, daily_payments.c.activity_date == calendar.c.activity_date),
        "admin_insight_daily",
    )
    return _output_select(
        kind="daily",
        collection="daily_activity",
        activity_date=daily.c.activity_date,
        daily_users=daily.c.users,
        daily_challenges=daily.c.challenges,
        daily_payments=daily.c.payments,
    ).select_from(daily)


def _snapshot_statement(actor: object, *, as_of: datetime, days: int | None):
    start = None if days is None else datetime.combine(
        (as_of - timedelta(days=days - 1)).date(), datetime.min.time()
    )
    users, challenges, payments = _normalized_sources(actor, as_of=as_of, start=start)
    outputs = [
        _count_output(users, "users"),
        _count_output(challenges, "challenges"),
        _count_output(payments, "payments"),
        _distribution_output(
            _materialized(select(users.c.id, users.c.role.label("code")), "admin_insight_user_roles"),
            collection="user_roles", name="admin_insight_user_role_distribution",
        ),
        _distribution_output(
            _materialized(select(users.c.id, users.c.kyc_status.label("code")), "admin_insight_user_kyc"),
            collection="user_kyc", name="admin_insight_user_kyc_distribution",
        ),
        _distribution_output(
            _materialized(select(challenges.c.id, challenges.c.status.label("code")), "admin_insight_challenge_status"),
            collection="challenge_status", name="admin_insight_challenge_status_distribution",
        ),
        _distribution_output(
            _materialized(select(payments.c.id, payments.c.status.label("code")), "admin_insight_payment_status"),
            collection="payment_status", name="admin_insight_payment_status_distribution",
        ),
    ]
    if days is None:
        outputs.extend(_dashboard_recent_outputs(users, payments))
    else:
        outputs.append(_daily_output(users, challenges, payments, start=start, days=days))
    rows = union_all(*outputs).cte("admin_insight_rows")
    return select(*rows.c).execution_options(skip_hierarchy_scope=True, autoflush=False)


def _safe_count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= _MAX_SAFE_INTEGER:
        raise RuntimeError("admin insight snapshot returned an unsafe count")
    return value


def _safe_identifier(value: object) -> int:
    if not _positive_identifier(value):
        raise RuntimeError("admin insight snapshot returned an invalid identifier")
    return value


def _safe_code(value: object, allowed: tuple[str, ...]) -> str | None:
    return value if isinstance(value, str) and value in allowed else None


def _safe_boolean(value: object) -> bool | None:
    return value if isinstance(value, bool) else None


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


def _timestamp(value: object) -> str | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None).isoformat() + "Z"
    # Legacy model timestamps are stored as naive UTC; expose that contract explicitly.
    return value.isoformat() + "Z"


def _row_value(row: Any, key: str):
    return row._mapping[key]


def _parse_snapshot(rows: Iterable[Any], *, days: int | None, as_of: datetime) -> dict[str, object]:
    counts: dict[str, int] = {}
    distributions: dict[str, list[dict[str, object]]] = {
        "user_roles": [], "user_kyc": [], "challenge_status": [], "payment_status": [],
    }
    recent_users: list[dict[str, object]] = []
    recent_payments: list[dict[str, object]] = []
    daily_activity: list[dict[str, object]] = []
    distribution_allowed = {
        "user_roles": _USER_ROLES,
        "user_kyc": _KYC_STATUSES,
        "challenge_status": _CHALLENGE_STATUSES,
        "payment_status": _PAYMENT_STATUSES,
    }

    for row in rows:
        kind = _row_value(row, "kind")
        collection = _row_value(row, "collection")
        if kind == "count" and collection in {"users", "challenges", "payments"}:
            if collection in counts:
                raise RuntimeError("admin insight snapshot repeated a count")
            counts[collection] = _safe_count(_row_value(row, "count"))
        elif kind == "distribution" and collection in distributions:
            allowed = distribution_allowed[collection]
            code = _safe_code(_row_value(row, "code"), allowed)
            item = {"code": code, "count": _safe_count(_row_value(row, "count"))}
            if any(existing["code"] == code for existing in distributions[collection]):
                raise RuntimeError("admin insight snapshot repeated a distribution code")
            distributions[collection].append(item)
        elif days is None and kind == "recent_user" and collection == "recent_users":
            recent_users.append({
                "id": _safe_identifier(_row_value(row, "id")),
                "role": _safe_code(_row_value(row, "role"), _USER_ROLES),
                "is_active": _safe_boolean(_row_value(row, "is_active")),
                "kyc_status": _safe_code(_row_value(row, "kyc_status"), _KYC_STATUSES),
                "created_at": _timestamp(_row_value(row, "created_at")),
            })
        elif days is None and kind == "recent_payment" and collection == "recent_payments":
            recent_payments.append({
                "id": _safe_identifier(_row_value(row, "id")),
                "user_id": _safe_identifier(_row_value(row, "user_id")),
                "amount": _decimal_string(_row_value(row, "amount")),
                "currency": _currency(_row_value(row, "currency")),
                "payment_type": _safe_code(_row_value(row, "payment_type"), _PAYMENT_TYPES),
                "status": _safe_code(_row_value(row, "status"), _PAYMENT_STATUSES),
                "created_at": _timestamp(_row_value(row, "created_at")),
            })
        elif days is not None and kind == "daily" and collection == "daily_activity":
            activity_date = _row_value(row, "activity_date")
            if not isinstance(activity_date, str):
                raise RuntimeError("admin insight snapshot returned an invalid activity date")
            daily_activity.append({
                "date": activity_date,
                "users": _safe_count(_row_value(row, "daily_users")),
                "challenges": _safe_count(_row_value(row, "daily_challenges")),
                "payments": _safe_count(_row_value(row, "daily_payments")),
            })
        else:
            raise RuntimeError("admin insight snapshot returned an unknown row")

    if set(counts) != {"users", "challenges", "payments"}:
        raise RuntimeError("admin insight snapshot omitted a count")
    for collection, values in distributions.items():
        if sum(item["count"] for item in values) != counts[{"user_roles": "users", "user_kyc": "users", "challenge_status": "challenges", "payment_status": "payments"}[collection]]:
            raise RuntimeError("admin insight snapshot distribution did not match its count")
        values.sort(key=lambda item: (item["code"] is None, item["code"] or ""))

    if days is None:
        def stable_recent(values: list[dict[str, object]]) -> None:
            # The SQL window function is the authority for the five-row bound.
            # Sort the bounded UNION output as created_at DESC NULLS LAST, id DESC.
            dated = [item for item in values if item["created_at"] is not None]
            undated = [item for item in values if item["created_at"] is None]
            dated.sort(key=lambda item: (
                datetime.fromisoformat(item["created_at"].replace("Z", "+00:00")), item["id"]
            ), reverse=True)
            undated.sort(key=lambda item: item["id"], reverse=True)
            values[:] = dated + undated

        stable_recent(recent_users)
        stable_recent(recent_payments)
        # SQL is the ordering authority.  These bounds only reject malformed output,
        # rather than silently trimming or inventing a partial response.
        if len(recent_users) != min(counts["users"], _RECENT_LIMIT):
            raise RuntimeError("admin insight snapshot recent user count did not match")
        if len(recent_payments) != min(counts["payments"], _RECENT_LIMIT):
            raise RuntimeError("admin insight snapshot recent payment count did not match")
        return {
            "counts": counts,
            "distributions": distributions,
            "recent_users": recent_users,
            "recent_payments": recent_payments,
            "daily_activity": [],
        }

    assert days is not None
    daily_activity.sort(key=lambda item: item["date"])
    expected_dates = [
        ((as_of - timedelta(days=days - 1)).date() + timedelta(days=offset)).isoformat()
        for offset in range(days)
    ]
    if [item["date"] for item in daily_activity] != expected_dates:
        raise RuntimeError("admin insight snapshot daily calendar was incomplete")
    if any(not isinstance(item["date"], str) for item in daily_activity):
        raise RuntimeError("admin insight snapshot daily date was invalid")
    if {
        key: sum(item[key] for item in daily_activity)
        for key in ("users", "challenges", "payments")
    } != counts:
        raise RuntimeError("admin insight snapshot daily totals did not match")
    return {
        "counts": counts,
        "distributions": distributions,
        "recent_users": [],
        "recent_payments": [],
        "daily_activity": daily_activity,
    }


class AdminInsightsReadService:
    """The sole read implementation for the two UI-4 admin insight HTTP routes."""

    @staticmethod
    def parse_dashboard_query(arguments: Any) -> None:
        _parse_dashboard(arguments)

    @staticmethod
    def parse_comprehensive_query(arguments: Any) -> int:
        return _parse_days(arguments)

    @classmethod
    def dashboard(cls, actor: object) -> dict[str, object]:
        # UTC is captured once and bound into every CTE predicate in this response.
        as_of = datetime.now(timezone.utc).replace(tzinfo=None)
        metadata = _metadata(actor, as_of=as_of, days=None)
        with db.session.no_autoflush:
            _set_statement_timeout()
            rows = db.session.execute(_snapshot_statement(actor, as_of=as_of, days=None)).all()
        return {**metadata, **_parse_snapshot(rows, days=None, as_of=as_of)}

    @classmethod
    def comprehensive(cls, actor: object, days: int) -> dict[str, object]:
        if isinstance(days, bool) or not isinstance(days, int) or days not in _ALLOWED_DAYS:
            raise AdminInsightsQueryInvalid()
        as_of = datetime.now(timezone.utc).replace(tzinfo=None)
        metadata = _metadata(actor, as_of=as_of, days=days)
        with db.session.no_autoflush:
            _set_statement_timeout()
            rows = db.session.execute(_snapshot_statement(actor, as_of=as_of, days=days)).all()
        return {**metadata, **_parse_snapshot(rows, days=days, as_of=as_of)}
