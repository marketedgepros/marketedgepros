"""
Admin routes for system management
"""
from flask import Blueprint, request, jsonify, g
from src import cache
import logging
from src.database import db
from src.models.user import User
from src.models.trading_program import Challenge
from src.models.payment import Payment
from src.models.trading_program import TradingProgram as Program
from src.utils.decorators import token_required, admin_required
from src.utils.validators import validate_required_fields, validate_email_format
from src.utils.error_messages import format_error_response
from src.utils.hierarchy_scoping import without_hierarchy_scope
from src.routes.kyc import _document_url, _kyc_users_for_actor, _kyc_error_response
from src.services.admin_closure_kyc import (
    AdminClosureKycNotFound,
    AdminClosureKycQueryInvalid,
    AdminClosureKycReviewConflict,
    AdminClosureKycReviewInvalid,
    AdminClosureKycScopeRequired,
    AdminClosureKycService,
)
from src.services.admin_payment_records_read import (
    AdminPaymentQueryInvalid,
    AdminPaymentScopeRequired,
    AdminPaymentRecordsReadService,
)
from src.services.admin_closure_programs import (
    AdminClosureProgramsService,
    AdminProgramsConflict,
    AdminProgramsNotFound,
    AdminProgramsQueryInvalid,
    AdminProgramsScopeRequired,
    AdminProgramsValidationError,
)
from src.services.admin_insights_read import (
    AdminInsightsQueryInvalid,
    AdminInsightsScopeRequired,
    AdminInsightsReadService,
)
from src.services.admin_closure_users import (
    AdminClosureUsersNotFound,
    AdminClosureUsersPermissionDenied,
    AdminClosureUsersProductNotConfigured,
    AdminClosureUsersQueryInvalid,
    AdminClosureUsersScopeRequired,
    AdminClosureUsersService,
    AdminClosureUsersTreeTooLarge,
    AdminClosureUsersValidationError,
)
from src.services.admin_closure_settings import (
    AdminClosureSettingsInvalid,
    AdminClosureSettingsNotConfigured,
    AdminClosureSettingsScopeRequired,
    AdminClosureSettingsService,
    AdminClosureSettingsWriteFailed,
)
from datetime import datetime, timedelta
from sqlalchemy import func, and_, or_

admin_bp = Blueprint('admin', __name__)


def _closure_users_error(error):
    """Map UI-4 users service failures without exposing implementation details."""
    db.session.rollback()
    if isinstance(error, AdminClosureUsersQueryInvalid):
        return jsonify({'error': 'Invalid user-management query', 'code': 'INVALID_ADMIN_USERS_QUERY'}), 400
    if isinstance(error, AdminClosureUsersScopeRequired):
        return jsonify({'error': 'Admin user scope is required', 'code': 'ADMIN_USERS_SCOPE_REQUIRED'}), 403
    if isinstance(error, AdminClosureUsersNotFound):
        return jsonify({'error': 'User not found', 'code': 'ADMIN_USER_NOT_FOUND'}), 404
    if isinstance(error, AdminClosureUsersValidationError):
        return jsonify({'error': str(error), 'code': 'INVALID_ADMIN_USER_INPUT'}), 400
    if isinstance(error, AdminClosureUsersPermissionDenied):
        return jsonify({'error': 'This account action is not permitted', 'code': 'ADMIN_USER_ACTION_FORBIDDEN'}), 403
    if isinstance(error, AdminClosureUsersProductNotConfigured):
        return jsonify({'error': 'Affiliate activation requires configured terms', 'code': 'AFFILIATE_PROGRAM_NOT_CONFIGURED'}), 409
    if isinstance(error, AdminClosureUsersTreeTooLarge):
        return jsonify({'error': 'User hierarchy exceeds the response limit', 'code': 'ADMIN_USER_HIERARCHY_TOO_LARGE'}), 413
    return jsonify({'error': 'User management is temporarily unavailable', 'code': 'ADMIN_USERS_UNAVAILABLE'}), 503


@admin_bp.route("/dashboard/stats", methods=["GET"])
@token_required
@admin_required
def get_dashboard_stats(current_user):
    """Return the bounded, hierarchy-scoped UI-4 dashboard insight projection."""
    try:
        # Syntax is checked before the service constructs any users/challenges/
        # payments SQL.  Authentication and the existing admin gate are above.
        AdminInsightsReadService.parse_dashboard_query(request.args)
        return jsonify(AdminInsightsReadService.dashboard(current_user)), 200
    except AdminInsightsQueryInvalid:
        return jsonify({'error': 'Invalid admin insights query', 'code': 'INVALID_ADMIN_INSIGHTS_QUERY'}), 400
    except AdminInsightsScopeRequired:
        return jsonify({'error': 'Admin insights scope is required', 'code': 'ADMIN_INSIGHTS_SCOPE_REQUIRED'}), 403
    except Exception:
        db.session.rollback()
        return jsonify({'error': 'Admin insights are temporarily unavailable',
                        'code': 'ADMIN_INSIGHTS_READ_FAILED'}), 503


@admin_bp.route('/users', methods=['GET'])
@token_required
@admin_required
def get_users(current_user):
    """Return the bounded, owner-scoped UI-4 user-management page."""
    try:
        arguments = AdminClosureUsersService.parse_list_query(request.args)
        return jsonify(AdminClosureUsersService.list_users(current_user, arguments)), 200
    except Exception as error:
        return _closure_users_error(error)

@admin_bp.route('/users/hierarchy', methods=['GET'])
@token_required
@admin_required
def get_users_tree(current_user):
    """Return the bounded, owner-scoped UI-4 hierarchy projection."""
    try:
        AdminClosureUsersService.parse_hierarchy_query(request.args)
        return jsonify(AdminClosureUsersService.hierarchy(current_user)), 200
    except Exception as error:
        return _closure_users_error(error)

@admin_bp.route('/users/<int:user_id>', methods=['GET'])
@token_required
@admin_required
def get_user(current_user, user_id):
    """Return one scoped operational user record; no credentials or sessions."""
    try:
        AdminClosureUsersService.parse_hierarchy_query(request.args)
        return jsonify(AdminClosureUsersService.get_user(current_user, user_id)), 200
    except Exception as error:
        return _closure_users_error(error)

@admin_bp.route('/users', methods=['POST'])
@token_required
@admin_required
def create_user(current_user):
    """Create only an allow-listed scoped hierarchy child."""
    try:
        AdminClosureUsersService.parse_hierarchy_query(request.args)
        return jsonify(AdminClosureUsersService.create_user(current_user, request.get_json(silent=True))), 201
    except Exception as error:
        return _closure_users_error(error)

@admin_bp.route('/users/<int:user_id>', methods=['PUT'])
@token_required
@admin_required
def update_user(current_user, user_id):
    """Persist only allow-listed operational account fields in scope."""
    try:
        AdminClosureUsersService.parse_hierarchy_query(request.args)
        return jsonify(AdminClosureUsersService.update_user(current_user, user_id, request.get_json(silent=True))), 200
    except Exception as error:
        return _closure_users_error(error)

@admin_bp.route('/users/<int:user_id>', methods=['DELETE'])
@token_required
@admin_required
def delete_user(current_user, user_id):
    """Deactivate a scoped account; this route never permanently deletes it."""
    try:
        AdminClosureUsersService.parse_hierarchy_query(request.args)
        return jsonify(AdminClosureUsersService.deactivate_user(current_user, user_id)), 200
    except Exception as error:
        return _closure_users_error(error)

@admin_bp.route('/users/<int:user_id>/reset-password', methods=['POST'])
@token_required
@admin_required
def admin_reset_password(current_user, user_id):
    """Reset a scoped account password and invalidate its extant tokens."""
    try:
        AdminClosureUsersService.parse_hierarchy_query(request.args)
        return jsonify(AdminClosureUsersService.reset_password(current_user, user_id, request.get_json(silent=True))), 200
    except Exception as error:
        return _closure_users_error(error)

@admin_bp.route('/programs', methods=['GET'])
@token_required
@admin_required
def get_programs(current_user):
    """Return one bounded, owner-scoped UI-4 program catalog page."""
    try:
        arguments = AdminClosureProgramsService.parse_list_query(request.args)
        return jsonify(AdminClosureProgramsService.list_programs(current_user, arguments)), 200
    except AdminProgramsQueryInvalid:
        return jsonify({'error': 'Invalid program catalog query', 'code': 'INVALID_ADMIN_PROGRAMS_QUERY'}), 400
    except AdminProgramsScopeRequired:
        return jsonify({'error': 'Program catalog scope is required', 'code': 'ADMIN_PROGRAMS_SCOPE_REQUIRED'}), 403
    except Exception:
        db.session.rollback()
        return jsonify({'error': 'Program catalog is temporarily unavailable', 'code': 'ADMIN_PROGRAMS_READ_FAILED'}), 503


@admin_bp.route('/programs', methods=['POST'])
@token_required
@admin_required
def create_program(current_user):
    """Create a tenant-owned program from a strict persisted-field allow-list."""
    try:
        result = AdminClosureProgramsService.create_program(current_user, request.get_json(silent=True))
        db.session.commit()
        return jsonify(result), 201
    except AdminProgramsValidationError as error:
        db.session.rollback()
        return jsonify({'error': str(error), 'code': 'INVALID_ADMIN_PROGRAM'}), 400
    except AdminProgramsScopeRequired:
        db.session.rollback()
        return jsonify({'error': 'Program catalog scope is required', 'code': 'ADMIN_PROGRAMS_SCOPE_REQUIRED'}), 403
    except Exception:
        db.session.rollback()
        return jsonify({'error': 'Program was not created', 'code': 'ADMIN_PROGRAM_CREATE_FAILED'}), 500


@admin_bp.route('/programs/<int:program_id>', methods=['PUT'])
@token_required
@admin_required
def update_program(current_user, program_id):
    """Update only exact persisted program fields in the caller's scope."""
    try:
        result = AdminClosureProgramsService.update_program(
            current_user, program_id, request.get_json(silent=True),
        )
        db.session.commit()
        return jsonify(result), 200
    except AdminProgramsValidationError as error:
        db.session.rollback()
        return jsonify({'error': str(error), 'code': 'INVALID_ADMIN_PROGRAM'}), 400
    except AdminProgramsNotFound:
        db.session.rollback()
        return jsonify({'error': 'Resource not found'}), 404
    except AdminProgramsScopeRequired:
        db.session.rollback()
        return jsonify({'error': 'Program catalog scope is required', 'code': 'ADMIN_PROGRAMS_SCOPE_REQUIRED'}), 403
    except Exception:
        db.session.rollback()
        return jsonify({'error': 'Program was not updated', 'code': 'ADMIN_PROGRAM_UPDATE_FAILED'}), 500


@admin_bp.route('/programs/<int:program_id>', methods=['DELETE'])
@token_required
@admin_required
def delete_program(current_user, program_id):
    """Delete one scoped program only when no persisted dependency remains."""
    try:
        result = AdminClosureProgramsService.delete_program(current_user, program_id)
        db.session.commit()
        return jsonify(result), 200
    except AdminProgramsNotFound:
        db.session.rollback()
        return jsonify({'error': 'Resource not found'}), 404
    except AdminProgramsConflict:
        db.session.rollback()
        return jsonify({'error': 'Cannot delete program with dependent records', 'code': 'PROGRAM_HAS_DEPENDENT_RECORDS'}), 409
    except AdminProgramsScopeRequired:
        db.session.rollback()
        return jsonify({'error': 'Program catalog scope is required', 'code': 'ADMIN_PROGRAMS_SCOPE_REQUIRED'}), 403
    except Exception:
        db.session.rollback()
        return jsonify({'error': 'Program was not deleted', 'code': 'ADMIN_PROGRAM_DELETE_FAILED'}), 500


@admin_bp.route('/payments', methods=['GET'])
@token_required
@admin_required
def get_payments(current_user):
    """Return the bounded, privacy-safe UI-4 admin payment projection."""
    try:
        # Syntax is intentionally parsed before the read service can construct a
        # payments/users statement.  Authentication and the existing admin role
        # gate have already run via decorators above.
        arguments = AdminPaymentRecordsReadService.parse_payments_query(request.args)
        return jsonify(AdminPaymentRecordsReadService.payments(current_user, arguments)), 200
    except AdminPaymentQueryInvalid:
        return jsonify({'error': 'Invalid admin payment query', 'code': 'INVALID_ADMIN_PAYMENT_QUERY'}), 400
    except AdminPaymentScopeRequired:
        return jsonify({'error': 'Admin payment scope is required', 'code': 'ADMIN_PAYMENT_SCOPE_REQUIRED'}), 403
    except Exception:
        db.session.rollback()
        return jsonify({'error': 'Admin payment records are temporarily unavailable',
                        'code': 'ADMIN_PAYMENT_READ_FAILED'}), 500


@admin_bp.route('/kyc/pending', methods=['GET'])
@token_required
@admin_required
def get_pending_kyc(current_user):
    """Compatibility path backed by the canonical bounded KYC submission projection."""
    try:
        arguments = AdminClosureKycService.parse_submissions_query(request.args)
        return jsonify(AdminClosureKycService.submissions(current_user, arguments)), 200
    except (AdminClosureKycQueryInvalid, AdminClosureKycScopeRequired) as error:
        return _kyc_error_response(error)
    except Exception:
        db.session.rollback()
        return jsonify({'error': 'KYC submissions are temporarily unavailable', 'code': 'ADMIN_KYC_READ_FAILED'}), 503


@admin_bp.route('/kyc/<int:user_id>/approve', methods=['POST'])
@token_required
@admin_required
def approve_kyc(current_user, user_id):
    """Compatibility path for a typed acknowledged recorded-review status only."""
    try:
        AdminClosureKycService.require_visible_submission(current_user, user_id)
        review = AdminClosureKycService.parse_submission_review(
            request.get_json(silent=True), user_id=user_id, status='approved',
        )
        return jsonify(AdminClosureKycService.review_submission(current_user, user_id, review)), 200
    except (
        AdminClosureKycScopeRequired,
        AdminClosureKycNotFound,
        AdminClosureKycReviewInvalid,
        AdminClosureKycReviewConflict,
    ) as error:
        db.session.rollback()
        return _kyc_error_response(error)
    except Exception:
        db.session.rollback()
        return jsonify({'error': 'KYC recorded review could not be saved', 'code': 'ADMIN_KYC_REVIEW_FAILED'}), 503


@admin_bp.route('/kyc/<int:user_id>/reject', methods=['POST'])
@token_required
@admin_required
def reject_kyc(current_user, user_id):
    """Compatibility path for a typed acknowledged recorded-review status only."""
    try:
        AdminClosureKycService.require_visible_submission(current_user, user_id)
        review = AdminClosureKycService.parse_submission_review(
            request.get_json(silent=True), user_id=user_id, status='rejected',
        )
        return jsonify(AdminClosureKycService.review_submission(current_user, user_id, review)), 200
    except (
        AdminClosureKycScopeRequired,
        AdminClosureKycNotFound,
        AdminClosureKycReviewInvalid,
        AdminClosureKycReviewConflict,
    ) as error:
        db.session.rollback()
        return _kyc_error_response(error)
    except Exception:
        db.session.rollback()
        return jsonify({'error': 'KYC recorded review could not be saved', 'code': 'ADMIN_KYC_REVIEW_FAILED'}), 503




@admin_bp.route('/users/<int:user_id>/full-details', methods=['GET'])
@token_required
@admin_required
def get_user_full_details(current_user, user_id):
    """Return bounded scoped operational details without credential/provider disclosure."""
    try:
        AdminClosureUsersService.parse_hierarchy_query(request.args)
        return jsonify(AdminClosureUsersService.full_details(current_user, user_id)), 200
    except Exception as error:
        return _closure_users_error(error)


@admin_bp.route('/settings', methods=['GET', 'PUT'])
@token_required
@admin_required
def manage_closure_settings(current_user):
    """Read or persist the root-owned tenant contact settings boundary."""
    try:
        # Query syntax and authenticated root/tenant checks occur before tenant SQL.
        AdminClosureSettingsService.parse_query(request.args)
        if request.method == 'GET':
            return jsonify(AdminClosureSettingsService.read(current_user)), 200

        if (
            request.content_length is not None
            and request.content_length > AdminClosureSettingsService.max_request_bytes
        ):
            return jsonify({
                'error': 'Settings request is too large',
                'code': 'ADMIN_CLOSURE_SETTINGS_INVALID',
            }), 413
        values = AdminClosureSettingsService.parse_update_payload(request.get_json(silent=True))
        return jsonify(AdminClosureSettingsService.update(current_user, values)), 200
    except AdminClosureSettingsInvalid:
        return jsonify({
            'error': 'Invalid tenant settings request',
            'code': 'ADMIN_CLOSURE_SETTINGS_INVALID',
        }), 400
    except AdminClosureSettingsScopeRequired:
        return jsonify({
            'error': 'Configured platform-root tenant scope is required',
            'code': 'ADMIN_CLOSURE_SETTINGS_SCOPE_REQUIRED',
        }), 403
    except AdminClosureSettingsNotConfigured:
        return jsonify({
            'error': 'Tenant settings are not configured',
            'code': 'ADMIN_CLOSURE_SETTINGS_NOT_CONFIGURED',
        }), 404
    except AdminClosureSettingsWriteFailed:
        return jsonify({
            'error': 'Tenant settings could not be persisted',
            'code': 'ADMIN_CLOSURE_SETTINGS_WRITE_FAILED',
        }), 503
    except Exception:
        db.session.rollback()
        return jsonify({
            'error': 'Tenant settings are temporarily unavailable',
            'code': 'ADMIN_CLOSURE_SETTINGS_UNAVAILABLE',
        }), 503
