"""Read-only legacy AccountScaling projections for UI-4.

Scaling evidence is not configured.  This module therefore never derives
eligibility, creates tiers, or writes AccountScaling rows.
"""
from __future__ import annotations

from decimal import Decimal
from math import ceil
from typing import Any

from sqlalchemy import func

from src.database import db
from src.models.account_scaling import AccountScaling
from src.models.user import User
from src.utils import crm_scope
from src.utils.hierarchy_scoping import platform_root_scope


class ScalingDataConflict(Exception):
    """More than one legacy AccountScaling row exists for one owner."""


class ScalingScopeNotAuthorized(Exception):
    """A non-root admin lacks the existing CRM tenant/downline scope."""


class ScalingService:
    """Safely read existing legacy rows; all scaling changes are disabled."""

    _UNAVAILABLE_CODE = "SCALING_EVIDENCE_NOT_CONFIGURED"
    _CONFLICT_CODE = "SCALING_OWNER_CONFLICT"

    @classmethod
    def evidence_not_configured(cls) -> dict[str, Any]:
        """Canonical response shared by every unsupported scaling operation."""
        return {
            "success": False,
            "error": "Scaling evidence is not configured",
            "code": cls._UNAVAILABLE_CODE,
        }

    # Mutation entrypoints remain callable by existing code, but they are hard
    # stops before any account/user/resource query, flush, or transaction write.
    @classmethod
    def initialize_scaling_for_user(cls, *_args, **_kwargs):
        return cls.evidence_not_configured()

    @classmethod
    def update_profit(cls, *_args, **_kwargs):
        return cls.evidence_not_configured()

    @classmethod
    def perform_scale_up(cls, *_args, **_kwargs):
        return cls.evidence_not_configured()

    @classmethod
    def pause_scaling(cls, *_args, **_kwargs):
        return cls.evidence_not_configured()

    @classmethod
    def resume_scaling(cls, *_args, **_kwargs):
        return cls.evidence_not_configured()

    @classmethod
    def check_eligibility(cls, *_args, **_kwargs):
        """No verified policy exists from which eligibility could be inferred."""
        return cls.evidence_not_configured()

    @classmethod
    def get_all_tiers(cls):
        """Do not expose retired DEFAULT_TIERS as an active scaling policy."""
        return cls.evidence_not_configured()

    @classmethod
    def get_user_scaling(cls, user_id: int):
        """Fetch exactly one owner row, failing closed on legacy duplicates."""
        with db.session.no_autoflush:
            rows = db.session.query(AccountScaling).filter(
                AccountScaling.user_id == user_id
            ).order_by(AccountScaling.id.asc()).limit(2).all()
        if len(rows) > 1:
            raise ScalingDataConflict()
        return rows[0] if rows else None

    @classmethod
    def get_scaling_history(cls, user_id: int):
        """Return null for no row, or the canonical legacy projection."""
        scaling = cls.get_user_scaling(user_id)
        return cls.projection(scaling) if scaling is not None else None

    @staticmethod
    def projection(scaling: AccountScaling) -> dict[str, Any]:
        """Serialize only contract fields and never trust legacy eligibility."""
        return {
            "user_id": scaling.user_id,
            "current_tier": scaling.current_tier,
            "current_account_size": decimal_string(scaling.current_account_size),
            "next_tier": scaling.next_tier,
            "next_account_size": decimal_string(scaling.next_account_size),
            "total_profit": decimal_string(scaling.total_profit),
            "target_profit": decimal_string(scaling.target_profit),
            "progress_percentage": decimal_string(scaling.progress_percentage),
            "times_scaled": scaling.times_scaled,
            "last_scaled_at": isoformat_or_none(scaling.last_scaled_at),
            "status": scaling.status,
            "created_at": isoformat_or_none(scaling.created_at),
            "is_eligible_for_scaling": False,
        }

    @classmethod
    def get_admin_user_history(cls, actor, user_id: int):
        """Read a scoped user's projection; invisible targets are indistinguishable."""
        with db.session.no_autoflush:
            if platform_root_scope(actor):
                visible = db.session.query(User.id).filter(User.id == user_id).first()
            else:
                if crm_scope.tenant_id_for(actor) is None:
                    raise ScalingScopeNotAuthorized()
                visible = crm_scope.scoped_users(actor).filter(User.id == user_id).with_entities(
                    User.id
                ).first()
        if visible is None:
            return None
        return cls.get_scaling_history(user_id)

    @classmethod
    def get_all_users_history(cls, actor, *, page: int, per_page: int):
        """Return a bounded root-or-CRM scoped admin page with duplicate refusal."""
        with db.session.no_autoflush:
            query = db.session.query(User, AccountScaling).join(
                AccountScaling, AccountScaling.user_id == User.id
            )
            if not platform_root_scope(actor):
                if crm_scope.tenant_id_for(actor) is None:
                    raise ScalingScopeNotAuthorized()
                scoped_user_ids = crm_scope.scoped_users(actor).with_entities(User.id)
                query = query.filter(User.id.in_(scoped_user_ids))

            # A legacy duplicate has no deterministic correct projection.  Refuse
            # the entire scoped response rather than selecting an arbitrary first.
            duplicate = query.with_entities(AccountScaling.user_id).group_by(
                AccountScaling.user_id
            ).having(func.count(AccountScaling.id) > 1).limit(1).first()
            if duplicate is not None:
                raise ScalingDataConflict()

            total = query.with_entities(func.count(AccountScaling.id)).scalar() or 0
            rows = query.order_by(User.id.asc(), AccountScaling.id.asc()).offset(
                (page - 1) * per_page
            ).limit(per_page).all()

        data = []
        for user, scaling in rows:
            projection = cls.projection(scaling)
            projection.update({
                "name": " ".join(part for part in (user.first_name, user.last_name) if part).strip()
                or None,
                "email": user.email,
            })
            data.append(projection)
        return {
            "data": data,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": int(total),
                "pages": ceil(total / per_page) if total else 0,
            },
        }


def decimal_string(value):
    """Return nullable SQL NUMERIC values exactly, without floats or falsey loss."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def isoformat_or_none(value):
    return value.isoformat() if value is not None else None
