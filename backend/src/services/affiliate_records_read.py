"""Bounded, owner-scoped affiliate referral and commission projections for UI-4."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import and_, desc, func, or_, text
from sqlalchemy.orm import aliased

from src.database import db
from src.models.affiliate import (
    AffiliateCommission,
    AffiliateLink,
    AffiliatePayout,
    AffiliateReferral,
)
from src.models.trading_program import TradingProgram
from src.models.user import User


class AffiliateRecordsArgumentError(ValueError):
    """Raised before a records-resource query for an ambiguous or invalid query."""


@dataclass(frozen=True)
class AffiliateRecordsArguments:
    """Canonical, bounded query arguments for one records page."""

    page: int
    per_page: int
    status: str | None


class AffiliateRecordsReadService:
    """Read only coherent, tenant-scoped legacy affiliate records.

    These projections deliberately do not make any legacy record payment authority.
    Every displayed referral has a same-owner link; a non-null referred-user or
    program parent must resolve currently in the actor's tenant. Nullable historic
    parents remain incomplete source records, never inferred authority. Every
    displayed commission additionally has that coherent referral and, when set, a
    same-owner payout parent.
    """

    _ALLOWED_ARGUMENTS = frozenset({"page", "per_page", "status"})
    _REFERRAL_STATUSES = frozenset({"pending", "converted", "cancelled"})
    _COMMISSION_STATUSES = frozenset({"pending", "approved", "paid", "cancelled"})
    _COMMISSION_TYPES = frozenset({"one_time", "recurring", "lifetime"})
    _POSTGRES_STATEMENT_TIMEOUT_MS = 1500

    @classmethod
    def parse_referral_arguments(cls, arguments) -> AffiliateRecordsArguments:
        """Parse exactly one supported referral query value before resource SQL."""
        return cls._parse_arguments(arguments, cls._REFERRAL_STATUSES)

    @classmethod
    def parse_commission_arguments(cls, arguments) -> AffiliateRecordsArguments:
        """Parse exactly one supported commission query value before resource SQL."""
        return cls._parse_arguments(arguments, cls._COMMISSION_STATUSES)

    @classmethod
    def _parse_arguments(cls, arguments, allowed_statuses: frozenset[str]) -> AffiliateRecordsArguments:
        for name in arguments.keys():
            if name not in cls._ALLOWED_ARGUMENTS or len(arguments.getlist(name)) != 1:
                raise AffiliateRecordsArgumentError("invalid query")

        page = cls._bounded_integer(arguments, "page", default=1, minimum=1, maximum=10000)
        per_page = cls._bounded_integer(arguments, "per_page", default=20, minimum=1, maximum=50)
        status = arguments.get("status") if "status" in arguments else None
        if status is not None and status not in allowed_statuses:
            raise AffiliateRecordsArgumentError("invalid query")
        return AffiliateRecordsArguments(page=page, per_page=per_page, status=status)

    @staticmethod
    def _bounded_integer(arguments, name: str, *, default: int, minimum: int, maximum: int) -> int:
        if name not in arguments:
            return default
        raw_value = arguments.get(name)
        if (
            not isinstance(raw_value, str)
            or len(raw_value) > len(str(maximum))
            or not raw_value.isascii()
            or not raw_value.isdecimal()
        ):
            raise AffiliateRecordsArgumentError("invalid query")
        value = int(raw_value)
        if str(value) != raw_value or not minimum <= value <= maximum:
            raise AffiliateRecordsArgumentError("invalid query")
        return value

    @staticmethod
    def has_positive_tenant(actor) -> bool:
        """Do not infer tenant ownership from any legacy affiliate parent."""
        tenant_id = getattr(actor, "tenant_id", None)
        return not isinstance(tenant_id, bool) and isinstance(tenant_id, int) and tenant_id >= 1

    @classmethod
    def get_referrals(cls, actor, arguments: AffiliateRecordsArguments) -> dict[str, Any]:
        """Return one stable page of referrals with only the UI-4 allow-list."""
        cls._require_positive_tenant(actor)
        with db.session.no_autoflush:
            cls._set_postgresql_statement_timeout()
            query = cls._coherent_referrals_query(actor)
            if arguments.status is not None:
                query = query.filter(AffiliateReferral.status == arguments.status)
            total = cls._count(query, AffiliateReferral.id)
            rows = (
                query.execution_options(autoflush=False)
                .order_by(desc(AffiliateReferral.click_date).nullslast(), desc(AffiliateReferral.id))
                .offset((arguments.page - 1) * arguments.per_page)
                .limit(arguments.per_page)
                .all()
            )

        return {
            "owner_context": {"user_id": actor.id, "tenant_id": actor.tenant_id},
            "verification": "unverified_legacy",
            "payouts_enabled": False,
            "available_for_payout": None,
            "currency": None,
            "referrals": [cls._serialize_referral(row) for row in rows],
            "pagination": cls._pagination(arguments, total),
            "filters": {"status": arguments.status},
        }

    @classmethod
    def get_commissions(cls, actor, arguments: AffiliateRecordsArguments) -> dict[str, Any]:
        """Return one stable page of commissions with only the UI-4 allow-list."""
        cls._require_positive_tenant(actor)
        with db.session.no_autoflush:
            cls._set_postgresql_statement_timeout()
            query = cls._coherent_commissions_query(actor)
            if arguments.status is not None:
                query = query.filter(AffiliateCommission.status == arguments.status)
            total = cls._count(query, AffiliateCommission.id)
            rows = (
                query.execution_options(autoflush=False)
                .order_by(desc(AffiliateCommission.created_at).nullslast(), desc(AffiliateCommission.id))
                .offset((arguments.page - 1) * arguments.per_page)
                .limit(arguments.per_page)
                .all()
            )

        return {
            "owner_context": {"user_id": actor.id, "tenant_id": actor.tenant_id},
            "verification": "unverified_legacy",
            "payouts_enabled": False,
            "available_for_payout": None,
            "currency": None,
            "commissions": [cls._serialize_commission(row) for row in rows],
            "pagination": cls._pagination(arguments, total),
            "filters": {"status": arguments.status},
        }

    @classmethod
    def _coherent_referrals_query(cls, actor):
        """Return referrals sharing the one legacy-coherence predicate."""
        referred_user = User.__table__.alias("affiliate_records_referred_user")
        referral_program = aliased(TradingProgram, name="affiliate_records_referral_program")
        return (
            db.session.query(AffiliateReferral)
            .join(
                AffiliateLink,
                and_(
                    AffiliateReferral.affiliate_link_id == AffiliateLink.id,
                ),
            )
            .outerjoin(
                referred_user,
                AffiliateReferral.referred_user_id == referred_user.c.id,
            )
            .outerjoin(
                referral_program,
                AffiliateReferral.program_id == referral_program.id,
            )
            .filter(*cls._coherent_referral_filters(actor, referred_user, referral_program))
        )

    @classmethod
    def _coherent_commissions_query(cls, actor):
        """Require the shared coherent referral and an owned payout when set."""
        referred_user = User.__table__.alias("affiliate_records_commission_referred_user")
        referral_program = aliased(TradingProgram, name="affiliate_records_commission_program")
        return (
            db.session.query(AffiliateCommission)
            .join(
                AffiliateReferral,
                and_(
                    AffiliateCommission.referral_id == AffiliateReferral.id,
                ),
            )
            .join(
                AffiliateLink,
                and_(
                    AffiliateReferral.affiliate_link_id == AffiliateLink.id,
                ),
            )
            .outerjoin(
                referred_user,
                AffiliateReferral.referred_user_id == referred_user.c.id,
            )
            .outerjoin(
                referral_program,
                AffiliateReferral.program_id == referral_program.id,
            )
            .outerjoin(AffiliatePayout, AffiliateCommission.payout_id == AffiliatePayout.id)
            .filter(
                AffiliateCommission.affiliate_user_id == actor.id,
                AffiliateCommission.referral_id.is_not(None),
                AffiliateCommission.status.in_(cls._COMMISSION_STATUSES),
                AffiliateCommission.type.in_(cls._COMMISSION_TYPES),
                or_(
                    AffiliateCommission.payout_id.is_(None),
                    AffiliatePayout.affiliate_user_id == actor.id,
                ),
                *cls._coherent_referral_filters(actor, referred_user, referral_program),
            )
        )

    @classmethod
    def _coherent_referral_filters(cls, actor, referred_user, referral_program):
        """Accept only an owner-consistent referral and permitted historic gaps.

        A nullable historical FK is not manufactured into a parent. A non-null FK
        must resolve to a current same-tenant user/program, and a referred user can
        never be the affiliate actor. This predicate is deliberately shared by the
        standalone referral page, commission page, and dashboard projections.
        """
        return (
            AffiliateReferral.affiliate_user_id == actor.id,
            AffiliateLink.user_id == actor.id,
            AffiliateReferral.status.in_(cls._REFERRAL_STATUSES),
            or_(
                AffiliateReferral.referred_user_id.is_(None),
                and_(
                    referred_user.c.id.is_not(None),
                    referred_user.c.id != actor.id,
                    referred_user.c.tenant_id == actor.tenant_id,
                ),
            ),
            or_(
                AffiliateReferral.program_id.is_(None),
                and_(
                    referral_program.id.is_not(None),
                    referral_program.tenant_id == actor.tenant_id,
                ),
            ),
        )

    @classmethod
    def _set_postgresql_statement_timeout(cls) -> None:
        """Bound this transaction's PostgreSQL work once; SQLite has no equivalent."""
        if db.session.get_bind().dialect.name == "postgresql":
            db.session.execute(
                text("SET LOCAL statement_timeout = :timeout"),
                {"timeout": f"{cls._POSTGRES_STATEMENT_TIMEOUT_MS}ms"},
            )

    @staticmethod
    def _count(query, identifier) -> int:
        total = query.order_by(None).with_entities(func.count(identifier)).scalar()
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise RuntimeError("affiliate records count was invalid")
        return total

    @staticmethod
    def _pagination(arguments: AffiliateRecordsArguments, total: int) -> dict[str, int]:
        return {
            "page": arguments.page,
            "per_page": arguments.per_page,
            "total": total,
            "pages": (total + arguments.per_page - 1) // arguments.per_page if total else 0,
        }

    @staticmethod
    def _serialize_referral(referral: AffiliateReferral) -> dict[str, Any]:
        return {
            "id": referral.id,
            "status": referral.status,
            "click_date": referral.click_date.isoformat() if referral.click_date else None,
            "conversion_date": referral.conversion_date.isoformat() if referral.conversion_date else None,
            "purchase_amount": decimal_string(referral.purchase_amount),
            "commission_amount": decimal_string(referral.commission_amount),
            "currency": None,
        }

    @staticmethod
    def _serialize_commission(commission: AffiliateCommission) -> dict[str, Any]:
        return {
            "id": commission.id,
            "amount": decimal_string(commission.amount),
            "type": commission.type,
            "status": commission.status,
            "created_at": commission.created_at.isoformat() if commission.created_at else None,
            "approved_at": commission.approved_at.isoformat() if commission.approved_at else None,
            "paid_at": commission.paid_at.isoformat() if commission.paid_at else None,
            "currency": None,
        }

    @classmethod
    def _require_positive_tenant(cls, actor) -> None:
        if not cls.has_positive_tenant(actor):
            raise PermissionError("tenant context required")


def decimal_string(value) -> str | None:
    """Expose only finite stored NUMERIC values, never floats or invented zeros."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return format(result, "f") if result.is_finite() else None
