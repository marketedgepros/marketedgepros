"""Tenant-scoped, bounded CRM projections for the UI-4 admin closure.

The existing Lead model predates a tenant column, so every projection intentionally
uses ``crm_scope`` and the assigned-user tenant/hierarchy boundary.  This module
contains read contracts only; route handlers retain the canonical write endpoints.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from math import ceil
from typing import Any, Iterator

from sqlalchemy import func, text
from sqlalchemy.orm import Session

from src.database import db
from src.models.lead import Lead, LeadActivity, LeadNote
from src.models.user import User
from src.utils import crm_scope


class AdminClosureCrmArgumentError(ValueError):
    """Raised before resource SQL for an invalid CRM list query."""


@dataclass(frozen=True)
class AdminClosureCrmListArguments:
    page: int
    per_page: int
    status: str | None
    source: str | None
    search: str


@dataclass(frozen=True)
class AdminClosureCrmChildArguments:
    page: int
    per_page: int


class AdminClosureCrmService:
    """Serialize only scoped CRM records with bounded snapshot reads."""

    _LIST_ARGUMENTS = frozenset({"page", "per_page", "status", "source", "search"})
    _CHILD_ARGUMENTS = frozenset({"page", "per_page"})
    _STATUSES = frozenset({"new", "contacted", "qualified", "proposal", "negotiation", "converted", "lost"})
    _MAX_PAGE = 10_000
    _MAX_PER_PAGE = 100
    _MAX_OFFSET = 10_000
    _STATEMENT_TIMEOUT_MS = 1_500

    @classmethod
    def parse_list_arguments(cls, arguments) -> AdminClosureCrmListArguments:
        cls._ensure_allowed_arguments(arguments, cls._LIST_ARGUMENTS)
        page = cls._bounded_integer(arguments, "page", default=1)
        per_page = cls._bounded_integer(arguments, "per_page", default=20, maximum=cls._MAX_PER_PAGE)
        if (page - 1) * per_page > cls._MAX_OFFSET:
            raise AdminClosureCrmArgumentError("invalid query")

        status = arguments.get("status") if "status" in arguments else None
        if status is not None and status not in cls._STATUSES:
            raise AdminClosureCrmArgumentError("invalid query")
        source = arguments.get("source") if "source" in arguments else None
        if source is not None and not cls._safe_text(source, maximum=50):
            raise AdminClosureCrmArgumentError("invalid query")
        search = arguments.get("search", "")
        if not isinstance(search, str) or len(search) > 100 or cls._contains_control(search):
            raise AdminClosureCrmArgumentError("invalid query")
        return AdminClosureCrmListArguments(page, per_page, status, source, search)

    @classmethod
    def parse_child_arguments(cls, arguments) -> AdminClosureCrmChildArguments:
        cls._ensure_allowed_arguments(arguments, cls._CHILD_ARGUMENTS)
        page = cls._bounded_integer(arguments, "page", default=1)
        per_page = cls._bounded_integer(arguments, "per_page", default=20, maximum=cls._MAX_PER_PAGE)
        if (page - 1) * per_page > cls._MAX_OFFSET:
            raise AdminClosureCrmArgumentError("invalid query")
        return AdminClosureCrmChildArguments(page, per_page)

    @classmethod
    def list_leads(cls, actor, arguments: AdminClosureCrmListArguments) -> dict[str, Any]:
        """Return a count and page from one read-only repeatable-read snapshot."""
        cls.require_owner(actor)
        with cls._read_snapshot() as session:
            query = cls._scoped_leads(session, actor, arguments)
            total = cls._count(query, Lead.id)
            rows = (
                query.execution_options(autoflush=False)
                .order_by(Lead.score.desc().nullslast(), Lead.created_at.desc().nullslast(), Lead.id.desc())
                .offset((arguments.page - 1) * arguments.per_page)
                .limit(arguments.per_page)
                .all()
            )
            assigned = cls._assigned_users(session, actor, rows)
            leads = [cls.serialize_lead(lead, assigned.get(lead.assigned_to)) for lead in rows]
        return {
            "owner_context": cls.owner_context(actor),
            "leads": leads,
            "pagination": cls.pagination(arguments.page, arguments.per_page, total),
            "filters": {"status": arguments.status, "source": arguments.source, "search": arguments.search},
        }

    @classmethod
    def lead_detail(cls, actor, lead_id: int) -> dict[str, Any] | None:
        cls.require_owner(actor)
        with cls._read_snapshot() as session:
            lead = cls._get_visible_lead(session, actor, lead_id)
            if lead is None:
                return None
            assigned = cls._assigned_users(session, actor, [lead]).get(lead.assigned_to)
            payload = cls.serialize_lead(lead, assigned)
            payload["notes_count"] = cls._count(session.query(LeadNote).filter(LeadNote.lead_id == lead.id), LeadNote.id)
            payload["activity_count"] = cls._count(session.query(LeadActivity).filter(LeadActivity.lead_id == lead.id), LeadActivity.id)
            payload["owner_context"] = cls.owner_context(actor)
            return payload

    @classmethod
    def list_notes(cls, actor, lead_id: int, arguments: AdminClosureCrmChildArguments) -> dict[str, Any] | None:
        cls.require_owner(actor)
        with cls._read_snapshot() as session:
            lead = cls._get_visible_lead(session, actor, lead_id)
            if lead is None:
                return None
            query = session.query(LeadNote).filter(LeadNote.lead_id == lead.id)
            total = cls._count(query, LeadNote.id)
            notes = (
                query.execution_options(autoflush=False)
                .order_by(LeadNote.created_at.desc().nullslast(), LeadNote.id.desc())
                .offset((arguments.page - 1) * arguments.per_page)
                .limit(arguments.per_page)
                .all()
            )
            creators = cls._visible_users_by_id(session, actor, {note.user_id for note in notes})
            rows = [cls.serialize_note(note, creators.get(note.user_id)) for note in notes]
        return {
            "owner_context": cls.owner_context(actor),
            "notes": rows,
            "pagination": cls.pagination(arguments.page, arguments.per_page, total),
        }

    @classmethod
    def list_activities(cls, actor, lead_id: int, arguments: AdminClosureCrmChildArguments) -> dict[str, Any] | None:
        cls.require_owner(actor)
        with cls._read_snapshot() as session:
            lead = cls._get_visible_lead(session, actor, lead_id)
            if lead is None:
                return None
            query = session.query(LeadActivity).filter(LeadActivity.lead_id == lead.id)
            total = cls._count(query, LeadActivity.id)
            activities = (
                query.execution_options(autoflush=False)
                .order_by(LeadActivity.created_at.desc().nullslast(), LeadActivity.id.desc())
                .offset((arguments.page - 1) * arguments.per_page)
                .limit(arguments.per_page)
                .all()
            )
            actors = cls._visible_users_by_id(session, actor, {item.user_id for item in activities})
            rows = [cls.serialize_activity(item, actors.get(item.user_id)) for item in activities]
        return {
            "owner_context": cls.owner_context(actor),
            "activities": rows,
            "pagination": cls.pagination(arguments.page, arguments.per_page, total),
        }

    @classmethod
    def stats(cls, actor) -> dict[str, Any]:
        """Aggregate visible lead statuses in one bounded, read-only snapshot query."""
        cls.require_owner(actor)
        with cls._read_snapshot() as session:
            status_rows = (
                crm_scope.scoped_leads(actor, query=session.query(Lead))
                .with_entities(Lead.status, func.count(Lead.id))
                .group_by(Lead.status)
                .all()
            )
        counts = {status: 0 for status in cls._STATUSES}
        for status, count in status_rows:
            if status in counts:
                counts[status] = int(count or 0)
        return {
            "owner_context": cls.owner_context(actor),
            "total_leads": sum(counts.values()),
            "new_leads": counts["new"],
            "contacted_leads": counts["contacted"],
            "qualified_leads": counts["qualified"],
            "converted_leads": counts["converted"],
            "lost_leads": counts["lost"],
        }

    @staticmethod
    def owner_context(actor) -> dict[str, int]:
        AdminClosureCrmService.require_owner(actor)
        return {"user_id": actor.id, "tenant_id": actor.tenant_id}

    @staticmethod
    def require_owner(actor) -> None:
        user_id = getattr(actor, "id", None)
        tenant_id = getattr(actor, "tenant_id", None)
        if isinstance(user_id, bool) or isinstance(tenant_id, bool) or not isinstance(user_id, int) or not isinstance(tenant_id, int) or user_id < 1 or tenant_id < 1:
            raise PermissionError("tenant context required")

    @classmethod
    def serialize_lead(cls, lead: Lead, assigned_user: User | None = None) -> dict[str, Any]:
        """Use exact decimal strings/null and native values; do not call legacy to_dict()."""
        return {
            "id": lead.id,
            "first_name": lead.first_name,
            "last_name": lead.last_name,
            "email": lead.email,
            "phone": lead.phone,
            "country_code": lead.country_code,
            "status": lead.status,
            "source": lead.source,
            "score": lead.score,
            "assigned_to": lead.assigned_to,
            "assigned_user": cls.serialize_user(assigned_user),
            "interested_program_id": lead.interested_program_id,
            "budget": cls.decimal_string(lead.budget),
            "company": lead.company,
            "job_title": lead.job_title,
            "notes": lead.notes,
            "tags": cls.tags(lead.tags),
            "next_follow_up": cls.iso_or_none(lead.next_follow_up),
            "converted_at": cls.iso_or_none(lead.converted_at),
            "lost_reason": lead.lost_reason,
            "lost_at": cls.iso_or_none(lead.lost_at),
            "created_at": cls.iso_or_none(lead.created_at),
            "updated_at": cls.iso_or_none(lead.updated_at),
        }

    @classmethod
    def serialize_note(cls, note: LeadNote, creator: User | None) -> dict[str, Any]:
        return {
            "id": note.id,
            "lead_id": note.lead_id,
            "content": note.content,
            "created_at": cls.iso_or_none(note.created_at),
            # Keep the established notes contract: this is display text, not a
            # trusted principal or a disclosure of an additional user record.
            "created_by": (
                f"{creator.first_name} {creator.last_name}".strip()
                if creator is not None else None
            ),
        }

    @classmethod
    def serialize_activity(cls, activity: LeadActivity, actor: User | None) -> dict[str, Any]:
        return {
            "id": activity.id,
            "lead_id": activity.lead_id,
            "activity_type": activity.activity_type,
            "subject": activity.subject,
            "description": activity.description,
            "outcome": activity.outcome,
            "scheduled_at": cls.iso_or_none(activity.scheduled_at),
            "completed": activity.completed is True,
            "completed_at": cls.iso_or_none(activity.completed_at),
            "created_at": cls.iso_or_none(activity.created_at),
            "created_by": cls.serialize_user(actor),
        }

    @staticmethod
    def serialize_user(user: User | None) -> dict[str, Any] | None:
        if user is None:
            return None
        return {"id": user.id, "name": f"{user.first_name} {user.last_name}".strip()}

    @staticmethod
    def decimal_string(value) -> str | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            decimal = value if isinstance(value, Decimal) else Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None
        return format(decimal, "f") if decimal.is_finite() else None

    @staticmethod
    def iso_or_none(value) -> str | None:
        return value.isoformat() if value is not None else None

    @staticmethod
    def tags(value) -> list[str]:
        if not isinstance(value, str) or not value:
            return []
        return [tag for tag in value.split(",") if tag]

    @classmethod
    def pagination(cls, page: int, per_page: int, total: int) -> dict[str, int]:
        return {
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": ceil(total / per_page) if total else 0,
        }

    @classmethod
    def _scoped_leads(cls, session: Session, actor, arguments: AdminClosureCrmListArguments):
        query = crm_scope.scoped_leads(actor, query=session.query(Lead))
        if arguments.status is not None:
            query = query.filter(Lead.status == arguments.status)
        if arguments.source is not None:
            query = query.filter(Lead.source == arguments.source)
        if arguments.search:
            escaped = arguments.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            from sqlalchemy import or_
            query = query.filter(or_(
                Lead.first_name.ilike(f"%{escaped}%", escape="\\"),
                Lead.last_name.ilike(f"%{escaped}%", escape="\\"),
                Lead.email.ilike(f"%{escaped}%", escape="\\"),
                Lead.phone.ilike(f"%{escaped}%", escape="\\"),
            ))
        return query

    @staticmethod
    def _get_visible_lead(session: Session, actor, lead_id: int) -> Lead | None:
        return crm_scope.scoped_leads(actor, query=session.query(Lead)).filter(Lead.id == lead_id).first()

    @staticmethod
    def _count(query, identifier) -> int:
        total = query.order_by(None).with_entities(func.count(identifier)).scalar()
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise RuntimeError("invalid CRM count")
        return total

    @staticmethod
    def _assigned_users(session: Session, actor, leads: list[Lead]) -> dict[int, User]:
        return AdminClosureCrmService._visible_users_by_id(session, actor, {lead.assigned_to for lead in leads if lead.assigned_to is not None})

    @staticmethod
    def _visible_users_by_id(session: Session, actor, identifiers: set[int | None]) -> dict[int, User]:
        user_ids = {identifier for identifier in identifiers if isinstance(identifier, int) and identifier > 0}
        if not user_ids:
            return {}
        users = crm_scope.scoped_users(actor, query=session.query(User)).filter(User.id.in_(user_ids)).all()
        return {user.id: user for user in users}

    @classmethod
    @contextmanager
    def _read_snapshot(cls) -> Iterator[Session]:
        """Open a separate read-only PostgreSQL snapshot after JWT authentication.

        Authentication has already used the request session before a route reaches
        this service, so snapshot isolation must use a fresh connection.  SQLite
        test databases keep their normal transaction behavior while retaining the
        same no-autoflush and bounded-query code path.
        """
        engine = db.session.get_bind()
        connection = engine.connect()
        transaction = connection.begin()
        session = Session(bind=connection, autoflush=False, expire_on_commit=False)
        try:
            if connection.dialect.name == "postgresql":
                connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
                connection.execute(text("SET LOCAL statement_timeout = :timeout"), {"timeout": f"{cls._STATEMENT_TIMEOUT_MS}ms"})
            with session.no_autoflush:
                yield session
        finally:
            session.close()
            transaction.rollback()
            connection.close()

    @classmethod
    def _ensure_allowed_arguments(cls, arguments, allowed: frozenset[str]) -> None:
        for name in arguments.keys():
            if name not in allowed or len(arguments.getlist(name)) != 1:
                raise AdminClosureCrmArgumentError("invalid query")

    @classmethod
    def _bounded_integer(cls, arguments, name: str, *, default: int, maximum: int | None = None) -> int:
        if name not in arguments:
            return default
        raw_value = arguments.get(name)
        maximum = cls._MAX_PAGE if maximum is None else maximum
        if (
            not isinstance(raw_value, str)
            or len(raw_value) > len(str(maximum))
            or not raw_value.isascii()
            or not raw_value.isdecimal()
        ):
            raise AdminClosureCrmArgumentError("invalid query")
        value = int(raw_value)
        if str(value) != raw_value or not 1 <= value <= maximum:
            raise AdminClosureCrmArgumentError("invalid query")
        return value

    @staticmethod
    def _contains_control(value: str) -> bool:
        return any(ord(character) < 32 or ord(character) == 127 for character in value)

    @classmethod
    def _safe_text(cls, value: object, *, maximum: int) -> bool:
        return isinstance(value, str) and bool(value) and len(value) <= maximum and not cls._contains_control(value)
