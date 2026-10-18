"""Read-only routes for unverified legacy wallet records.

Legacy balances and history are display data only.  No route in this module may
create a wallet, mutate a legacy balance, approve a payout, or notify a user
until a separate ledger protocol is available.
"""
from flask import Blueprint, jsonify, request
from src.middleware.auth import admin_required, get_current_user, jwt_required
from src.services.financial_records_read import (
    FinancialRecordsQueryInvalid,
    FinancialRecordsReadService,
    FinancialRecordsScopeNotAuthorized,
    FinancialRecordsTenantRequired,
)
from src.services.wallet_service import (
    WalletLedgerNotConfigured,
    WalletNotFound,
)


wallet_bp = Blueprint('wallet', __name__)

def _error_response(error):
    """Expose only stable public errors; never serialize an exception string."""
    if isinstance(error, WalletLedgerNotConfigured):
        return jsonify({
            'error': 'Wallet ledger is not configured',
            'code': error.code,
        }), error.status
    if isinstance(error, WalletNotFound):
        return jsonify({
            'error': 'Wallet not found',
            'code': error.code,
            'reason': 'unverified_legacy',
        }), error.status
    if isinstance(error, FinancialRecordsScopeNotAuthorized):
        return jsonify({
            'error': 'Wallet scope is not authorized',
            'code': 'WALLET_SCOPE_NOT_AUTHORIZED',
        }), 403
    if isinstance(error, FinancialRecordsTenantRequired):
        return jsonify({
            'error': 'Tenant context is required',
            'code': 'TENANT_CONTEXT_REQUIRED',
        }), 403
    return jsonify({'error': 'Invalid wallet request'}), 400


def _ledger_not_configured_response():
    """The HTTP gate runs before JSON parsing, lookup, writes, or notifications."""
    return _error_response(WalletLedgerNotConfigured())


@wallet_bp.route('/balance', methods=['GET'])
@jwt_required
def get_balance():
    """Return an existing legacy wallet record without implying available funds."""
    try:
        FinancialRecordsReadService.parse_balance_query(request.args)
        return jsonify(FinancialRecordsReadService.wallet_balance(get_current_user())), 200
    except (WalletNotFound, FinancialRecordsQueryInvalid, FinancialRecordsTenantRequired) as error:
        return _error_response(error)
    except Exception:
        return jsonify({'error': 'Internal server error'}), 500


@wallet_bp.route('/transactions', methods=['GET'])
@jwt_required
def get_transactions():
    """Return one bounded page of an existing wallet's historical entries."""
    try:
        arguments = FinancialRecordsReadService.parse_transactions_query(request.args)
        return jsonify(FinancialRecordsReadService.wallet_transactions(get_current_user(), arguments)), 200
    except (WalletNotFound, FinancialRecordsQueryInvalid, FinancialRecordsTenantRequired) as error:
        return _error_response(error)
    except Exception:
        return jsonify({'error': 'Internal server error'}), 500


@wallet_bp.route('/admin/wallets', methods=['GET'])
@admin_required
def get_all_wallets():
    """List wallets only for a canonical root or the actor's tenant hierarchy."""
    try:
        arguments = FinancialRecordsReadService.parse_admin_wallets_query(request.args)
        return jsonify(FinancialRecordsReadService.admin_wallets(get_current_user(), arguments)), 200
    except (FinancialRecordsScopeNotAuthorized, FinancialRecordsQueryInvalid,
            FinancialRecordsTenantRequired) as error:
        return _error_response(error)
    except Exception:
        return jsonify({'error': 'Internal server error'}), 500


@wallet_bp.route('/admin/adjust', methods=['POST'])
@admin_required
def adjust_balance():
    """Refuse legacy balance adjustments before the request body is read."""
    return _ledger_not_configured_response()


@wallet_bp.route('/admin/withdrawals', methods=['GET'])
@admin_required
def get_all_withdrawals():
    """List only scope-owned, non-ambiguous historical withdrawal records."""
    try:
        arguments = FinancialRecordsReadService.parse_withdrawals_query(request.args)
        return jsonify(FinancialRecordsReadService.admin_withdrawals(get_current_user(), arguments)), 200
    except (FinancialRecordsScopeNotAuthorized, FinancialRecordsQueryInvalid,
            FinancialRecordsTenantRequired) as error:
        return _error_response(error)
    except Exception:
        return jsonify({'error': 'Internal server error'}), 500


@wallet_bp.route('/admin/withdrawals/<int:withdrawal_id>/approve', methods=['POST'])
@admin_required
def approve_withdrawal(withdrawal_id):
    """Refuse legacy approval before lookup, status mutation, or notification."""
    return _ledger_not_configured_response()


@wallet_bp.route('/admin/withdrawals/<int:withdrawal_id>/reject', methods=['POST'])
@admin_required
def reject_withdrawal(withdrawal_id):
    """Refuse legacy rejection before request parsing or any state transition."""
    return _ledger_not_configured_response()


@wallet_bp.route('/admin/withdrawals/<int:withdrawal_id>/complete', methods=['POST'])
@admin_required
def complete_withdrawal(withdrawal_id):
    """Refuse legacy completion before request parsing or notification."""
    return _ledger_not_configured_response()
