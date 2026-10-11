"""Read-only routes for unverified legacy wallet records.

Legacy balances and history are display data only.  No route in this module may
create a wallet, mutate a legacy balance, approve a payout, or notify a user
until a separate ledger protocol is available.
"""
from flask import Blueprint, jsonify, request
from sqlalchemy import and_, or_
from sqlalchemy.orm import joinedload

from src.database import db
from src.middleware.auth import admin_required, get_current_user, jwt_required
from src.models.agent import Agent
from src.models.user import User
from src.models.wallet import Wallet
from src.models.withdrawal import Withdrawal
from src.services.wallet_service import (
    WalletLedgerNotConfigured,
    WalletNotFound,
    WalletService,
)
from src.utils.hierarchy_scoping import (
    complete_hierarchy_scope,
    platform_root_scope,
    tenant_hierarchy_scope,
)


wallet_bp = Blueprint('wallet', __name__)

_MAX_QUERY_INTEGER_DIGITS = 10
_MAX_HISTORY_OFFSET = 10_000
_LEGACY_BALANCE_TYPES = frozenset({'main', 'commission', 'bonus'})
_WITHDRAWAL_STATUSES = frozenset({'pending', 'approved', 'processing', 'completed', 'rejected'})


class _WalletScopeNotAuthorized(ValueError):
    code = 'WALLET_SCOPE_NOT_AUTHORIZED'
    status = 403


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
    if isinstance(error, _WalletScopeNotAuthorized):
        return jsonify({
            'error': 'Wallet scope is not authorized',
            'code': error.code,
        }), error.status
    return jsonify({'error': 'Invalid wallet request'}), 400


def _ledger_not_configured_response():
    """The HTTP gate runs before JSON parsing, lookup, writes, or notifications."""
    return _error_response(WalletLedgerNotConfigured())


def _parse_ascii_bounded_integer(name, default, minimum, maximum):
    """Parse one unambiguous query integer without Flask's silent fallback."""
    values = request.args.getlist(name)
    if not values:
        return default
    if len(values) != 1:
        raise ValueError('Invalid pagination')
    raw = values[0]
    if (
        not isinstance(raw, str)
        or not raw
        or len(raw) > _MAX_QUERY_INTEGER_DIGITS
        or not raw.isascii()
        or not raw.isdecimal()
    ):
        raise ValueError('Invalid pagination')
    value = int(raw)
    if not minimum <= value <= maximum:
        raise ValueError('Invalid pagination')
    return value


def _parse_history_pagination():
    page = _parse_ascii_bounded_integer('page', 1, 1, 10 ** _MAX_QUERY_INTEGER_DIGITS - 1)
    per_page = _parse_ascii_bounded_integer('per_page', 50, 1, WalletService._MAX_HISTORY_LIMIT)
    offset = (page - 1) * per_page
    if offset > _MAX_HISTORY_OFFSET:
        raise ValueError('Invalid pagination')
    return page, per_page, offset


def _single_optional_balance_type():
    values = request.args.getlist('balance_type')
    if not values:
        return None
    if len(values) != 1:
        raise ValueError('Invalid balance type')
    balance_type = values[0]
    if balance_type not in _LEGACY_BALANCE_TYPES:
        raise ValueError('Invalid balance type')
    return balance_type


def _allowed_user_ids(actor):
    """Return the one explicit owner set allowed to the admin request.

    Only the canonical configured platform root receives an all-user set.  A
    non-root actor must have complete tenant-bound hierarchy data; malformed or
    unknown scope is rejected rather than broadened to a global listing.
    """
    if not complete_hierarchy_scope(actor):
        raise _WalletScopeNotAuthorized()
    if platform_root_scope(actor):
        query = db.session.query(User.id)
    elif tenant_hierarchy_scope(actor):
        condition = User.hierarchy_filter_for_entity(actor)
        if condition is None:
            # A ``None`` condition means global access in the helper and is only
            # allowed for the canonical root branch above.
            raise _WalletScopeNotAuthorized()
        query = db.session.query(User.id).filter(condition)
    else:
        raise _WalletScopeNotAuthorized()
    return query.distinct().subquery(name='wallet_allowed_users')


def _admin_pagination():
    # The admin lists are also bounded; their count is an actual scoped count,
    # unlike a history page where a page length was formerly mislabeled total.
    return _parse_history_pagination()


@wallet_bp.route('/balance', methods=['GET'])
@jwt_required
def get_balance():
    """Return an existing legacy wallet record without implying available funds."""
    try:
        wallet = WalletService.get_or_create_wallet(get_current_user().id)
        return jsonify({
            'wallet': wallet.to_dict(),
            'balance_verification': 'unverified_legacy',
        }), 200
    except (WalletNotFound, ValueError) as error:
        return _error_response(error)
    except Exception:
        return jsonify({'error': 'Internal server error'}), 500


@wallet_bp.route('/transactions', methods=['GET'])
@jwt_required
def get_transactions():
    """Return one bounded page of an existing wallet's historical entries."""
    try:
        # All request validation happens before the wallet/history query.
        page, per_page, offset = _parse_history_pagination()
        balance_type = _single_optional_balance_type()
        transactions = WalletService.get_transaction_history(
            get_current_user().id,
            limit=per_page,
            offset=offset,
            balance_type=balance_type,
        )
        return jsonify({
            'transactions': [transaction.to_dict() for transaction in transactions],
            'balance_verification': 'unverified_legacy',
            'pagination': {
                'page': page,
                'per_page': per_page,
                'offset': offset,
                # A bounded page is not a full history count.
                'total': None,
                'returned_count': len(transactions),
            },
        }), 200
    except (WalletNotFound, ValueError) as error:
        return _error_response(error)
    except Exception:
        return jsonify({'error': 'Internal server error'}), 500


@wallet_bp.route('/admin/wallets', methods=['GET'])
@admin_required
def get_all_wallets():
    """List wallets only for a canonical root or the actor's tenant hierarchy."""
    try:
        page, per_page, _ = _admin_pagination()
        allowed_users = _allowed_user_ids(get_current_user())
        query = (
            Wallet.query.execution_options(autoflush=False)
            .join(User, Wallet.user_id == User.id)
            .join(allowed_users, User.id == allowed_users.c.id)
            .options(joinedload(Wallet.user))
            .order_by(Wallet.created_at.desc(), Wallet.id.desc())
        )
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        wallets = []
        for wallet in pagination.items:
            owner = wallet.user
            wallet_data = wallet.to_dict()
            wallet_data['user'] = {
                'id': owner.id,
                'name': f'{owner.first_name} {owner.last_name}'.strip(),
                'email': owner.email,
                'role': owner.role,
            }
            wallets.append(wallet_data)
        return jsonify({
            'wallets': wallets,
            'balance_verification': 'unverified_legacy',
            'pagination': {
                'page': pagination.page,
                'per_page': pagination.per_page,
                'total': pagination.total,
                'pages': pagination.pages,
            },
        }), 200
    except (_WalletScopeNotAuthorized, ValueError) as error:
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
        page, per_page, _ = _admin_pagination()
        status_values = request.args.getlist('status')
        if len(status_values) > 1:
            raise ValueError('Invalid withdrawal status')
        status = status_values[0] if status_values else None
        if status is not None and (
            not isinstance(status, str)
            or not status
            or len(status) > 20
            or status not in _WITHDRAWAL_STATUSES
        ):
            raise ValueError('Invalid withdrawal status')
        allowed_users = _allowed_user_ids(get_current_user())

        # The legacy schema can identify an owner directly or through Agent.  If
        # both are present, they must resolve to the same user.  A dangling agent,
        # missing owner, or mismatch is excluded rather than guessed.
        owner_is_unambiguous = or_(
            and_(Withdrawal.user_id.isnot(None), Withdrawal.agent_id.is_(None)),
            and_(Withdrawal.user_id.is_(None), Withdrawal.agent_id.isnot(None), Agent.user_id.isnot(None)),
            and_(
                Withdrawal.user_id.isnot(None),
                Withdrawal.agent_id.isnot(None),
                Agent.user_id.isnot(None),
                Withdrawal.user_id == Agent.user_id,
            ),
        )
        query = (
            Withdrawal.query.execution_options(autoflush=False)
            .outerjoin(Agent, Withdrawal.agent_id == Agent.id)
            .join(
                allowed_users,
                or_(Withdrawal.user_id == allowed_users.c.id, Agent.user_id == allowed_users.c.id),
            )
            .options(
                joinedload(Withdrawal.user),
                joinedload(Withdrawal.agent).joinedload(Agent.user),
            )
            .filter(owner_is_unambiguous)
        )
        if status is not None:
            query = query.filter(Withdrawal.status == status)
        pagination = query.order_by(Withdrawal.created_at.desc(), Withdrawal.id.desc()).paginate(
            page=page, per_page=per_page, error_out=False,
        )

        withdrawals = []
        for withdrawal in pagination.items:
            owner = withdrawal.user or (withdrawal.agent.user if withdrawal.agent else None)
            # Owner resolution above makes this a defense-in-depth refusal rather
            # than an opportunity to expose an ambiguous relationship.
            if owner is None:
                continue
            withdrawal_data = withdrawal.to_dict()
            withdrawal_data['user'] = {
                'id': owner.id,
                'name': f'{owner.first_name} {owner.last_name}'.strip(),
                'email': owner.email,
            }
            withdrawals.append(withdrawal_data)
        return jsonify({
            'withdrawals': withdrawals,
            'balance_verification': 'unverified_legacy',
            'pagination': {
                'page': pagination.page,
                'per_page': pagination.per_page,
                'total': pagination.total,
                'pages': pagination.pages,
            },
        }), 200
    except (_WalletScopeNotAuthorized, ValueError) as error:
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
