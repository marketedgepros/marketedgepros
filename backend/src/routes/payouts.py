"""Fail-closed compatibility routes for the unverified legacy payout API.

No public read can assert eligibility or expose unscoped payment details; no
mutation can reserve funds or mark a transfer paid without a source-bound ledger.
Existing route names are preserved, with authentication/admin/CSRF gates first.
"""
from flask import Blueprint, jsonify

from src.middleware.auth import admin_required, jwt_required
from src.services.wallet_service import WalletLedgerNotConfigured

payouts_bp = Blueprint('payouts', __name__, url_prefix='/api/payouts')


def _not_configured():
    error = WalletLedgerNotConfigured()
    return jsonify({
        'error': 'Wallet ledger is not configured',
        'code': error.code,
    }), error.status


@payouts_bp.route('/', methods=['GET'], strict_slashes=False)
@jwt_required
def list_payouts():
    return _not_configured()


@payouts_bp.route('/check-eligibility', methods=['GET'])
@jwt_required
def check_payout_eligibility():
    return _not_configured()


@payouts_bp.route('/request', methods=['POST'])
@jwt_required
def request_payout():
    return _not_configured()


@payouts_bp.route('/my-payouts', methods=['GET'])
@jwt_required
def get_my_payouts():
    return _not_configured()


@payouts_bp.route('/my-statistics', methods=['GET'])
@jwt_required
def get_my_payout_statistics():
    return _not_configured()


@payouts_bp.route('/<int:payout_id>', methods=['GET'])
@jwt_required
def get_payout(payout_id):
    return _not_configured()


@payouts_bp.route('/admin/pending', methods=['GET'])
@admin_required
def get_pending_payouts():
    return _not_configured()


@payouts_bp.route('/admin/<int:payout_id>/approve', methods=['POST'])
@admin_required
def approve_payout(payout_id):
    return _not_configured()


@payouts_bp.route('/admin/<int:payout_id>/reject', methods=['POST'])
@admin_required
def reject_payout(payout_id):
    return _not_configured()


@payouts_bp.route('/admin/<int:payout_id>/mark-paid', methods=['POST'])
@admin_required
def mark_payout_paid(payout_id):
    return _not_configured()


@payouts_bp.route('/admin/statistics', methods=['GET'])
@admin_required
def get_all_payout_statistics():
    return _not_configured()
