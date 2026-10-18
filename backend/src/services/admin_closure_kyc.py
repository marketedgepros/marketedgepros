"""Bounded, tenant-scoped KYC administration projections and recorded reviews.

This service deliberately treats KYC as a local record of document review.  It never
contacts an identity provider and never grants wallet, payout, trading, or MT5
eligibility.  File bytes continue to be served only through the authenticated
canonical KYC download route.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import ceil
from typing import Any

from sqlalchemy import func, select, text, true

from src.database import db
from src.models.user import User
from src.services.kyc_document_service import DOCUMENT_FIELDS, KycDocumentService
from src.utils.hierarchy_scoping import platform_root_scope, tenant_hierarchy_scope


_MAX_PAGE = 10_000
_MAX_PER_PAGE = 50
_MAX_OFFSET = 10_000
_MAX_INTEGER_DIGITS = 10
_SUBMISSION_STATUSES = frozenset({"pending", "approved", "rejected", "not_submitted"})
_DOCUMENT_STATUSES = frozenset({"not_uploaded", "pending", "approved", "rejected"})
_REVIEWABLE_STATUSES = frozenset({"approved", "rejected"})
_DOCUMENT_NAMES = {
    "id_proof": "ID Proof",
    "address_proof": "Address Proof",
    "selfie": "Selfie with ID",
    "bank_statement": "Bank Statement",
}


class AdminClosureKycQueryInvalid(ValueError):
    """A KYC administration query was non-canonical, duplicate, or out of range."""


class AdminClosureKycScopeRequired(PermissionError):
    """The authenticated administrator has no complete, tenant-bound hierarchy scope."""


class AdminClosureKycNotFound(LookupError):
    """A submission is absent from the caller's scoped KYC view."""


class AdminClosureKycReviewInvalid(ValueError):
    """A manual recorded-review request did not meet the narrow write contract."""


class AdminClosureKycReviewConflict(RuntimeError):
    """The selected document is no longer the pending record originally reviewed."""


@dataclass(frozen=True)
class AdminClosureKycListArguments:
    page: int
    per_page: int
    offset: int
    status: str


@dataclass(frozen=True)
class AdminClosureKycDocumentReview:
    status: str
    notes: str | None
    acknowledgement: str
    expected_uploaded_at: str


@dataclass(frozen=True)
class AdminClosureKycSubmissionReview:
    status: str
    notes: str | None
    acknowledgement: str


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
        raise AdminClosureKycQueryInvalid()
    value = int(raw)
    if not minimum <= value <= maximum or str(value) != raw:
        raise AdminClosureKycQueryInvalid()
    return value


def _timestamp(value: object) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _recorded_status(value: object, allowed: frozenset[str]) -> str | None:
    return value if isinstance(value, str) and value in allowed else None


def _bounded_note(value: object, *, required: bool) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise AdminClosureKycReviewInvalid()
    note = value.strip()
    if (required and not note) or len(note) > 500:
        raise AdminClosureKycReviewInvalid()
    return note or None


def _owner_context(actor: object) -> dict[str, int]:
    user_id = getattr(actor, "id", None)
    tenant_id = getattr(actor, "tenant_id", None)
    if not (_positive_identifier(user_id) and _positive_identifier(tenant_id)):
        raise AdminClosureKycScopeRequired()
    return {"user_id": user_id, "tenant_id": tenant_id}


def _require_scope(actor: object) -> dict[str, int]:
    owner = _owner_context(actor)
    # The route's existing admin decorator has already verified the role.  Repeat
    # the real role set here so callers of this service cannot obtain a wider query.
    if getattr(actor, "role", None) not in {"supermaster", "master"}:
        raise AdminClosureKycScopeRequired()
    if not tenant_hierarchy_scope(actor):
        raise AdminClosureKycScopeRequired()
    return owner


def _scoped_users(actor: object):
    """Return only the explicit tenant/root or tenant/downline User predicate."""
    _require_scope(actor)
    query = db.session.query(User).filter(User.tenant_id == actor.tenant_id)
    if platform_root_scope(actor):
        return query.execution_options(skip_hierarchy_scope=True, autoflush=False)
    condition = User.hierarchy_filter_for_entity(actor)
    if condition is None:
        # A global predicate is valid only for the configured platform root above.
        raise AdminClosureKycScopeRequired()
    return query.filter(condition).execution_options(skip_hierarchy_scope=True, autoflush=False)


def _set_statement_timeout() -> None:
    bind = db.session.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        db.session.execute(text("SET LOCAL statement_timeout = 1500"))


def _pagination(arguments: AdminClosureKycListArguments, total: int) -> dict[str, int]:
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise RuntimeError("KYC submission snapshot returned an invalid total")
    return {
        "page": arguments.page,
        "per_page": arguments.per_page,
        "total": total,
        "pages": ceil(total / arguments.per_page) if total else 0,
    }


def _snapshot_page(query, arguments: AdminClosureKycListArguments) -> tuple[int, list[Any]]:
    """Read count and bounded page in one CTE-backed database statement."""
    scoped = query.order_by(None).cte(name="admin_closure_kyc_scoped")
    scoped = scoped.prefix_with("MATERIALIZED", dialect="postgresql")
    total = select(func.count().label("_total")).select_from(scoped).cte(name="admin_closure_kyc_total")
    page = (
        select(*scoped.c)
        .order_by(scoped.c.submitted_at.desc().nullslast(), scoped.c.user_id.desc())
        .limit(arguments.per_page)
        .offset(arguments.offset)
        .cte(name="admin_closure_kyc_page")
    )
    statement = (
        select(total.c._total, *page.c)
        .select_from(total.outerjoin(page, true()))
        .execution_options(skip_hierarchy_scope=True, autoflush=False)
    )
    rows = db.session.execute(statement).all()
    if not rows:
        raise RuntimeError("KYC submission snapshot did not return a total row")
    total_value = rows[0]._mapping["_total"]
    if isinstance(total_value, bool) or not isinstance(total_value, int) or total_value < 0:
        raise RuntimeError("KYC submission snapshot total was invalid")
    return total_value, [row for row in rows if row._mapping["user_id"] is not None]


def _documents_projection(user: object, *, include_notes: bool) -> list[dict[str, object]]:
    documents = []
    for document_type, field in DOCUMENT_FIELDS.items():
        download_url = _document_download_url(user, document_type)
        item = {
            "type": document_type,
            "name": _DOCUMENT_NAMES[document_type],
            "status": _recorded_status(getattr(user, field + "_status", None), _DOCUMENT_STATUSES),
            "uploaded_at": _timestamp(getattr(user, field + "_uploaded_at", None)),
            "download_url": download_url,
            # Existing reviewer clients used `url`; keep that value canonical.
            "url": download_url,
        }
        if include_notes:
            notes = getattr(user, field + "_notes", None)
            item["notes"] = notes if isinstance(notes, str) else None
        documents.append(item)
    return documents


def _document_download_url(user: object, document_type: str) -> str | None:
    # Metadata reveals only a canonical same-origin API route.  Storage references,
    # object keys, filenames, and presigned URLs never leave the server.
    if KycDocumentService.reference(user, document_type) is None:
        return None
    return f"/api/v1/kyc/documents/{user.id}/{document_type}/download"


def _submission_projection(row: Any) -> dict[str, object]:
    return {
        "user_id": row.user_id if _positive_identifier(row.user_id) else None,
        "kyc_status": _recorded_status(row.kyc_status, _SUBMISSION_STATUSES),
        "submitted_at": _timestamp(row.submitted_at),
        "documents": {
            "id_proof": _recorded_status(row.kyc_id_status, _DOCUMENT_STATUSES),
            "address_proof": _recorded_status(row.kyc_address_status, _DOCUMENT_STATUSES),
            "selfie": _recorded_status(row.kyc_selfie_status, _DOCUMENT_STATUSES),
            "bank_statement": _recorded_status(row.kyc_bank_status, _DOCUMENT_STATUSES),
        },
    }


def _detail_projection(user: User, owner: dict[str, int]) -> dict[str, object]:
    display_name = " ".join(part for part in (user.first_name, user.last_name) if isinstance(part, str) and part.strip())
    return {
        "owner_context": owner,
        "review_scope": "recorded_document_only",
        "user": {
            "id": user.id,
            # Do not provide email, phone, country, birth date, or any provider data.
            "display_name": display_name or f"User {user.id}",
        },
        "kyc_status": _recorded_status(user.kyc_status, _SUBMISSION_STATUSES),
        "submitted_at": _timestamp(user.kyc_submitted_at),
        "documents": _documents_projection(user, include_notes=True),
    }


class AdminClosureKycService:
    """The sole scoped backend implementation for the UI-4 KYC admin screen."""

    @staticmethod
    def parse_submissions_query(arguments: Any) -> AdminClosureKycListArguments:
        allowed_names = frozenset({"page", "per_page", "status"})
        for name in arguments.keys():
            if name not in allowed_names or len(arguments.getlist(name)) != 1:
                raise AdminClosureKycQueryInvalid()
        raw_page = arguments.getlist("page")
        raw_per_page = arguments.getlist("per_page")
        raw_status = arguments.getlist("status")
        page = 1 if not raw_page else _canonical_integer(raw_page[0], minimum=1, maximum=_MAX_PAGE)
        per_page = 20 if not raw_per_page else _canonical_integer(raw_per_page[0], minimum=1, maximum=_MAX_PER_PAGE)
        offset = (page - 1) * per_page
        if offset > _MAX_OFFSET:
            raise AdminClosureKycQueryInvalid()
        status = "pending" if not raw_status else raw_status[0]
        if status not in _SUBMISSION_STATUSES:
            raise AdminClosureKycQueryInvalid()
        return AdminClosureKycListArguments(page=page, per_page=per_page, offset=offset, status=status)

    @staticmethod
    def scoped_user_query(actor: object):
        """Compatibility query helper for canonical private-download authorization."""
        return _scoped_users(actor)

    @classmethod
    def submissions(cls, actor: object, arguments: AdminClosureKycListArguments) -> dict[str, object]:
        owner = _require_scope(actor)
        with db.session.no_autoflush:
            _set_statement_timeout()
            scoped_users = _scoped_users(actor).with_entities(
                User.id.label("user_id"),
                User.kyc_status.label("kyc_status"),
                User.kyc_submitted_at.label("submitted_at"),
                User.kyc_id_status.label("kyc_id_status"),
                User.kyc_address_status.label("kyc_address_status"),
                User.kyc_selfie_status.label("kyc_selfie_status"),
                User.kyc_bank_status.label("kyc_bank_status"),
            ).filter(User.kyc_status == arguments.status)
            total, rows = _snapshot_page(scoped_users, arguments)
        return {
            "owner_context": owner,
            "review_scope": "recorded_document_only",
            "submissions": [_submission_projection(row) for row in rows],
            "pagination": _pagination(arguments, total),
            "filters": {"status": arguments.status},
        }

    @classmethod
    def submission_detail(cls, actor: object, user_id: int) -> dict[str, object]:
        owner = _require_scope(actor)
        if not _positive_identifier(user_id):
            raise AdminClosureKycNotFound()
        with db.session.no_autoflush:
            _set_statement_timeout()
            user = _scoped_users(actor).filter(User.id == user_id).populate_existing().one_or_none()
        if user is None:
            raise AdminClosureKycNotFound()
        return _detail_projection(user, owner)

    @classmethod
    def require_visible_submission(cls, actor: object, user_id: int) -> None:
        """Fail closed before parsing legacy overall-review bodies for hidden subjects."""
        _require_scope(actor)
        if not _positive_identifier(user_id):
            raise AdminClosureKycNotFound()
        with db.session.no_autoflush:
            _set_statement_timeout()
            visible = _scoped_users(actor).filter(User.id == user_id).with_entities(User.id).first()
        if visible is None:
            raise AdminClosureKycNotFound()

    @staticmethod
    def parse_document_review(data: object, *, user_id: int, document_type: str) -> AdminClosureKycDocumentReview:
        if not _positive_identifier(user_id) or document_type not in DOCUMENT_FIELDS or not isinstance(data, dict):
            raise AdminClosureKycReviewInvalid()
        if set(data) != {"status", "notes", "acknowledgement", "expected_uploaded_at"}:
            raise AdminClosureKycReviewInvalid()
        status = data.get("status")
        acknowledgement = data.get("acknowledgement")
        expected_uploaded_at = data.get("expected_uploaded_at")
        expected_acknowledgement = f"REVIEW {user_id} {document_type}"
        if status not in _REVIEWABLE_STATUSES or acknowledgement != expected_acknowledgement:
            raise AdminClosureKycReviewInvalid()
        if not isinstance(expected_uploaded_at, str) or not expected_uploaded_at or len(expected_uploaded_at) > 64:
            raise AdminClosureKycReviewInvalid()
        notes = _bounded_note(data.get("notes"), required=status == "rejected")
        return AdminClosureKycDocumentReview(status, notes, acknowledgement, expected_uploaded_at)

    @classmethod
    def review_document(cls, actor: object, user_id: int, document_type: str,
                        review: AdminClosureKycDocumentReview) -> dict[str, object]:
        owner = _require_scope(actor)
        if document_type not in DOCUMENT_FIELDS or not _positive_identifier(user_id):
            raise AdminClosureKycNotFound()
        field = DOCUMENT_FIELDS[document_type]
        with db.session.no_autoflush:
            _set_statement_timeout()
            user = (
                _scoped_users(actor)
                .filter(User.id == user_id)
                .with_for_update()
                .populate_existing()
                .one_or_none()
            )
            if user is None:
                raise AdminClosureKycNotFound()
            current_uploaded_at = _timestamp(getattr(user, field + "_uploaded_at", None))
            if (
                current_uploaded_at != review.expected_uploaded_at
                or getattr(user, field + "_status", None) != "pending"
                or KycDocumentService.reference(user, document_type) is None
            ):
                raise AdminClosureKycReviewConflict()
            setattr(user, field + "_status", review.status)
            setattr(user, field + "_notes", review.notes)
            user.updated_at = datetime.utcnow()
            db.session.commit()
        return {
            "owner_context": owner,
            "review_scope": "recorded_document_only",
            "user": {"id": user.id},
            "document": {
                "type": document_type,
                "status": review.status,
                "notes": review.notes,
                "uploaded_at": current_uploaded_at,
                "download_url": _document_download_url(user, document_type),
            },
            "review_recorded": True,
        }

    @staticmethod
    def parse_submission_review(data: object, *, user_id: int, status: str) -> AdminClosureKycSubmissionReview:
        if not _positive_identifier(user_id) or status not in _REVIEWABLE_STATUSES or not isinstance(data, dict):
            raise AdminClosureKycReviewInvalid()
        allowed = {"acknowledgement", "notes"} if status == "approved" else {"acknowledgement", "notes", "reason"}
        if set(data) != allowed:
            raise AdminClosureKycReviewInvalid()
        acknowledgement = data.get("acknowledgement")
        if acknowledgement != f"REVIEW {user_id} submission":
            raise AdminClosureKycReviewInvalid()
        note_value = data.get("notes") if "notes" in data else data.get("reason")
        notes = _bounded_note(note_value, required=status == "rejected")
        return AdminClosureKycSubmissionReview(status, notes, acknowledgement)

    @classmethod
    def review_submission(cls, actor: object, user_id: int,
                          review: AdminClosureKycSubmissionReview) -> dict[str, object]:
        """Compatibility-only overall record review; it does not update document records or eligibility."""
        owner = _require_scope(actor)
        if not _positive_identifier(user_id):
            raise AdminClosureKycNotFound()
        with db.session.no_autoflush:
            _set_statement_timeout()
            user = (
                _scoped_users(actor)
                .filter(User.id == user_id)
                .with_for_update()
                .populate_existing()
                .one_or_none()
            )
            if user is None:
                raise AdminClosureKycNotFound()
            if user.kyc_status != "pending":
                raise AdminClosureKycReviewConflict()
            user.kyc_status = review.status
            user.kyc_admin_notes = review.notes
            user.updated_at = datetime.utcnow()
            if review.status == "approved":
                user.kyc_approved_at = datetime.utcnow()
                user.kyc_approved_by = owner["user_id"]
            else:
                user.kyc_rejected_at = datetime.utcnow()
                user.kyc_rejected_by = owner["user_id"]
                user.kyc_rejection_reason = review.notes
            db.session.commit()
        return {
            "owner_context": owner,
            "review_scope": "recorded_document_only",
            "user": {"id": user.id, "kyc_status": review.status},
            "review_recorded": True,
        }
