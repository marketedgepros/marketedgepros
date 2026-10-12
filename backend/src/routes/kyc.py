"""Canonical KYC document, private download, and recorded-review routes."""
from datetime import datetime

from flask import Blueprint, current_app, g, jsonify, request

from src.database import db
from src.models.user import User
from src.constants.roles import Roles
from src.services.admin_closure_kyc import (
    AdminClosureKycNotFound,
    AdminClosureKycQueryInvalid,
    AdminClosureKycReviewConflict,
    AdminClosureKycReviewInvalid,
    AdminClosureKycScopeRequired,
    AdminClosureKycService,
)
from src.services.kyc_document_service import DOCUMENT_FIELDS, KycDocumentService
from src.utils.decorators import admin_required, token_required


kyc_bp = Blueprint("kyc", __name__)

DOCUMENT_TYPES = {
    "id_proof": "ID Proof",
    "address_proof": "Address Proof",
    "selfie": "Selfie with ID",
    "bank_statement": "Bank Statement",
}


def _kyc_users_for_actor(actor):
    """Compatibility helper retained for the legacy admin blueprint integration patch."""
    return AdminClosureKycService.scoped_user_query(actor)


def _document_url(user, document_type):
    """Return only an authenticated canonical path, never a storage reference."""
    if KycDocumentService.reference(user, document_type) is None:
        return None
    return f"/api/v1/kyc/documents/{user.id}/{document_type}/download"


def _document_metadata(user, document_type):
    field = DOCUMENT_FIELDS[document_type]
    return {
        "type": document_type,
        "name": DOCUMENT_TYPES[document_type],
        "status": getattr(user, field + "_status", None) or "not_uploaded",
        "uploaded_at": (
            getattr(user, field + "_uploaded_at", None).isoformat()
            if getattr(user, field + "_uploaded_at", None) else None
        ),
        "notes": getattr(user, field + "_notes", None),
        "url": _document_url(user, document_type),
    }


def _kyc_error_response(error):
    if isinstance(error, AdminClosureKycQueryInvalid):
        return jsonify({"error": "Invalid KYC submissions query", "code": "INVALID_ADMIN_KYC_QUERY"}), 400
    if isinstance(error, AdminClosureKycScopeRequired):
        return jsonify({"error": "KYC administration scope is required", "code": "ADMIN_KYC_SCOPE_REQUIRED"}), 403
    if isinstance(error, AdminClosureKycNotFound):
        return jsonify({"error": "KYC submission not found", "code": "ADMIN_KYC_SUBMISSION_NOT_FOUND"}), 404
    if isinstance(error, AdminClosureKycReviewInvalid):
        return jsonify({"error": "Invalid recorded document review", "code": "INVALID_KYC_DOCUMENT_REVIEW"}), 400
    if isinstance(error, AdminClosureKycReviewConflict):
        return jsonify({"error": "The recorded document is no longer pending review", "code": "KYC_DOCUMENT_REVIEW_STALE"}), 409
    return None


def _safe_rollback():
    try:
        db.session.rollback()
    except Exception:
        pass


@kyc_bp.route("/documents", methods=["GET"])
@token_required
def get_user_documents(current_user):
    """Return the authenticated account's own document metadata and canonical URLs."""
    try:
        user = g.current_user
        documents = [_document_metadata(user, document_type) for document_type in DOCUMENT_TYPES]
        statuses = [document["status"] for document in documents]
        return jsonify({
            "overall_status": user.kyc_status,
            "statistics": {
                "total": len(DOCUMENT_TYPES),
                "uploaded": sum(status != "not_uploaded" for status in statuses),
                "approved": sum(status == "approved" for status in statuses),
                "pending": sum(status == "pending" for status in statuses),
                "rejected": sum(status == "rejected" for status in statuses),
            },
            "documents": documents,
        }), 200
    except Exception:
        current_app.logger.error("KYC operation failed")
        return jsonify({"error": "KYC operation failed"}), 500


@kyc_bp.route("/documents/<document_type>/upload", methods=["POST"])
@token_required
def upload_document(current_user, document_type):
    """Store a user-owned private KYC file and record only its pending document status."""
    try:
        if document_type not in DOCUMENT_TYPES:
            return jsonify({"error": "Invalid document type"}), 400
        user = g.current_user
        if not user.tenant_id:
            return jsonify({"error": "Tenant membership required"}), 403
        if "file" not in request.files:
            return jsonify({"error": "No file provided"}), 400
        file = request.files["file"]
        if not file or not file.filename:
            return jsonify({"error": "No file selected"}), 400

        reference = KycDocumentService.store(file, user.id, document_type)
        field = DOCUMENT_FIELDS[document_type]
        recorded_at = datetime.utcnow()
        setattr(user, field + "_status", "pending")
        setattr(user, field + "_uploaded_at", recorded_at)
        setattr(user, field + "_url", reference)
        # Replacement uploads begin a fresh manual review and must not retain a
        # previous reviewer note for an earlier file.
        setattr(user, field + "_notes", None)

        required_fields = ("kyc_id_status", "kyc_address_status", "kyc_selfie_status")
        if all(getattr(user, field_name, None) == "pending" for field_name in required_fields):
            user.kyc_status = "pending"
            user.kyc_submitted_at = recorded_at
        user.updated_at = recorded_at
        db.session.commit()
        return jsonify({
            "message": "Document uploaded successfully",
            "document": {
                "type": document_type,
                "name": DOCUMENT_TYPES[document_type],
                "status": "pending",
                "uploaded_at": recorded_at.isoformat(),
            },
        }), 200
    except ValueError:
        _safe_rollback()
        return jsonify({"error": "Invalid document data"}), 400
    except Exception:
        _safe_rollback()
        current_app.logger.error("KYC operation failed")
        return jsonify({"error": "KYC operation failed"}), 500


@kyc_bp.route("/admin/submissions", methods=["GET"])
@token_required
@admin_required
def get_kyc_submissions(current_user):
    """Return one bounded, hierarchy-scoped snapshot of recorded KYC submissions."""
    try:
        arguments = AdminClosureKycService.parse_submissions_query(request.args)
        return jsonify(AdminClosureKycService.submissions(current_user, arguments)), 200
    except (AdminClosureKycQueryInvalid, AdminClosureKycScopeRequired) as error:
        return _kyc_error_response(error)
    except Exception:
        _safe_rollback()
        current_app.logger.error("KYC administration read failed")
        return jsonify({"error": "KYC submissions are temporarily unavailable", "code": "ADMIN_KYC_READ_FAILED"}), 503


@kyc_bp.route("/admin/submissions/<int:user_id>", methods=["GET"])
@token_required
@admin_required
def get_kyc_submission_details(current_user, user_id):
    """Return minimal detail and private canonical download routes for one scoped subject."""
    try:
        return jsonify(AdminClosureKycService.submission_detail(current_user, user_id)), 200
    except (AdminClosureKycScopeRequired, AdminClosureKycNotFound) as error:
        return _kyc_error_response(error)
    except Exception:
        _safe_rollback()
        current_app.logger.error("KYC administration detail read failed")
        return jsonify({"error": "KYC submission detail is temporarily unavailable", "code": "ADMIN_KYC_DETAIL_READ_FAILED"}), 503


@kyc_bp.route("/admin/submissions/<int:user_id>/documents/<document_type>", methods=["PUT"])
@token_required
@admin_required
def update_document_status(current_user, user_id, document_type):
    """Persist one typed-acknowledged, manual recorded document review."""
    try:
        review = AdminClosureKycService.parse_document_review(
            request.get_json(silent=True), user_id=user_id, document_type=document_type,
        )
        return jsonify(AdminClosureKycService.review_document(current_user, user_id, document_type, review)), 200
    except (
        AdminClosureKycScopeRequired,
        AdminClosureKycNotFound,
        AdminClosureKycReviewInvalid,
        AdminClosureKycReviewConflict,
    ) as error:
        _safe_rollback()
        return _kyc_error_response(error)
    except Exception:
        _safe_rollback()
        current_app.logger.error("KYC recorded document review failed")
        return jsonify({"error": "KYC recorded document review could not be saved", "code": "ADMIN_KYC_REVIEW_FAILED"}), 503


@kyc_bp.route("/admin/submissions/<int:user_id>/approve", methods=["POST"])
@token_required
@admin_required
def approve_kyc(current_user, user_id):
    """Compatibility endpoint for a typed acknowledged overall recorded-review status."""
    try:
        AdminClosureKycService.require_visible_submission(current_user, user_id)
        review = AdminClosureKycService.parse_submission_review(
            request.get_json(silent=True), user_id=user_id, status="approved",
        )
        return jsonify(AdminClosureKycService.review_submission(current_user, user_id, review)), 200
    except (
        AdminClosureKycScopeRequired,
        AdminClosureKycNotFound,
        AdminClosureKycReviewInvalid,
        AdminClosureKycReviewConflict,
    ) as error:
        _safe_rollback()
        return _kyc_error_response(error)
    except Exception:
        _safe_rollback()
        current_app.logger.error("KYC recorded review failed")
        return jsonify({"error": "KYC recorded review could not be saved", "code": "ADMIN_KYC_REVIEW_FAILED"}), 503


@kyc_bp.route("/admin/submissions/<int:user_id>/reject", methods=["POST"])
@token_required
@admin_required
def reject_kyc(current_user, user_id):
    """Compatibility endpoint for a typed acknowledged overall recorded-review status."""
    try:
        AdminClosureKycService.require_visible_submission(current_user, user_id)
        review = AdminClosureKycService.parse_submission_review(
            request.get_json(silent=True), user_id=user_id, status="rejected",
        )
        return jsonify(AdminClosureKycService.review_submission(current_user, user_id, review)), 200
    except (
        AdminClosureKycScopeRequired,
        AdminClosureKycNotFound,
        AdminClosureKycReviewInvalid,
        AdminClosureKycReviewConflict,
    ) as error:
        _safe_rollback()
        return _kyc_error_response(error)
    except Exception:
        _safe_rollback()
        current_app.logger.error("KYC recorded review failed")
        return jsonify({"error": "KYC recorded review could not be saved", "code": "ADMIN_KYC_REVIEW_FAILED"}), 503


@kyc_bp.route("/documents/<int:user_id>/<document_type>/download", methods=["GET"])
@token_required
def download_document(current_user, user_id, document_type):
    """Serve a private file only to its owner or a tenant/downline scoped reviewer."""
    if document_type not in DOCUMENT_FIELDS or user_id <= 0 or not current_user.tenant_id:
        return jsonify({"error": "Document not found"}), 404
    try:
        if user_id == current_user.id:
            user = current_user
        elif Roles.is_admin(current_user.role):
            # Scope and hierarchy are validated before the subject lookup SQL.
            user = AdminClosureKycService.scoped_user_query(current_user).filter(User.id == user_id).one_or_none()
            if user is None:
                return jsonify({"error": "Document not found"}), 404
        else:
            return jsonify({"error": "Document not found"}), 404
        response = KycDocumentService.download(user, document_type)
        current_app.logger.info(
            "KYC download actor=%s subject=%s type=%s tenant=%s",
            current_user.id, user.id, document_type, current_user.tenant_id,
        )
        return response
    except (AdminClosureKycScopeRequired, FileNotFoundError, ValueError):
        return jsonify({"error": "Document not found"}), 404
    except Exception:
        current_app.logger.warning("KYC document unavailable actor=%s subject=%s", current_user.id, user_id)
        return jsonify({"error": "Document not found"}), 404
