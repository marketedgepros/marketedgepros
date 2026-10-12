"""Read-only payment approval API routes for the two UI-4 admin screens."""
from flask import Blueprint, jsonify, request, g

from src.database import db
from src.services.admin_payment_records_read import (
    AdminPaymentQueryInvalid,
    AdminPaymentRecordNotFound,
    AdminPaymentRecordsReadService,
    AdminPaymentScopeRequired,
)
from src.services.payment_approval_service import PaymentApprovalService
from src.utils.decorators import role_required, token_required


bp = Blueprint('payment_approvals', __name__, url_prefix='/api/v1/payment-approvals')


def _read_error(error):
    """Canonical, non-diagnostic errors for every approval read endpoint."""
    if isinstance(error, AdminPaymentQueryInvalid):
        return jsonify({'error': 'Invalid admin payment query', 'code': 'INVALID_ADMIN_PAYMENT_QUERY'}), 400
    if isinstance(error, AdminPaymentScopeRequired):
        return jsonify({'error': 'Admin payment scope is required', 'code': 'ADMIN_PAYMENT_SCOPE_REQUIRED'}), 403
    if isinstance(error, AdminPaymentRecordNotFound):
        return jsonify({'error': 'Admin payment record was not found', 'code': 'ADMIN_PAYMENT_RECORD_NOT_FOUND'}), 404
    db.session.rollback()
    return jsonify({'error': 'Admin payment records are temporarily unavailable',
                    'code': 'ADMIN_PAYMENT_READ_FAILED'}), 500


def _no_query_arguments():
    """Details/stats have no query contract; reject unknown syntax before SQL."""
    if list(request.args.keys()):
        raise AdminPaymentQueryInvalid()


@bp.route('/pending', methods=['GET'])
@token_required
@role_required('supermaster')
def get_pending_approvals():
    """List coherent pending legacy requests for the configured platform root only."""
    try:
        arguments = AdminPaymentRecordsReadService.parse_approval_query(request.args)
        return jsonify(AdminPaymentRecordsReadService.pending_approval_requests(g.current_user, arguments)), 200
    except (AdminPaymentQueryInvalid, AdminPaymentScopeRequired, AdminPaymentRecordNotFound) as error:
        return _read_error(error)
    except Exception as error:
        return _read_error(error)


@bp.route('/my-requests', methods=['GET'])
@token_required
@role_required('supermaster', 'master')
def get_my_requests():
    """List only the caller's own coherent requests with bounded pagination."""
    try:
        arguments = AdminPaymentRecordsReadService.parse_approval_query(request.args)
        return jsonify(AdminPaymentRecordsReadService.my_approval_requests(g.current_user, arguments)), 200
    except (AdminPaymentQueryInvalid, AdminPaymentScopeRequired, AdminPaymentRecordNotFound) as error:
        return _read_error(error)
    except Exception as error:
        return _read_error(error)


@bp.route('/create', methods=['POST'])
@token_required
@role_required('supermaster', 'master')
def create_approval_request():
    """Legacy settlement remains unavailable until a verified command exists."""
    return jsonify({
        'error': 'Order settlement is not configured',
        'code': 'ORDER_SETTLEMENT_NOT_CONFIGURED',
    }), 503


@bp.route('/<int:request_id>/approve', methods=['POST'])
@token_required
@role_required('supermaster')
def approve_request(request_id):
    """Legacy settlement remains unavailable until a verified command exists."""
    return jsonify({
        'error': 'Order settlement is not configured',
        'code': 'ORDER_SETTLEMENT_NOT_CONFIGURED',
    }), 503


@bp.route('/<int:request_id>/reject', methods=['POST'])
@token_required
@role_required('supermaster')
def reject_request(request_id):
    """Block legacy rejection before body parsing, ORM work, writes, or mail."""
    # token_required has already checked JWT and cookie-CSRF; role_required has
    # already checked supermaster.  Do not inspect ``request`` body afterwards.
    return PaymentApprovalService.reject_unavailable_response()


@bp.route('/<int:request_id>', methods=['GET'])
@token_required
def get_request_details(request_id):
    """Return the allow-listed record to its requester or the explicit root only."""
    try:
        _no_query_arguments()
        return jsonify(AdminPaymentRecordsReadService.approval_request_detail(g.current_user, request_id)), 200
    except (AdminPaymentQueryInvalid, AdminPaymentScopeRequired, AdminPaymentRecordNotFound) as error:
        return _read_error(error)
    except Exception as error:
        return _read_error(error)


@bp.route('/stats', methods=['GET'])
@token_required
@role_required('supermaster')
def get_approval_stats():
    """Expose only the coherent pending count to the configured root."""
    try:
        _no_query_arguments()
        return jsonify(AdminPaymentRecordsReadService.approval_stats(g.current_user)), 200
    except (AdminPaymentQueryInvalid, AdminPaymentScopeRequired, AdminPaymentRecordNotFound) as error:
        return _read_error(error)
    except Exception as error:
        return _read_error(error)
