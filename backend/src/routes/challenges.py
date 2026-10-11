"""Bounded, non-authorizing challenge and MT5 legacy views.

No route in this module may manufacture trading evidence, funding, provisioning,
or credentials from mutable legacy rows.  Provider-backed workflows remain
explicitly unavailable until their authoritative contracts exist.
"""
from decimal import Decimal, InvalidOperation
from functools import wraps
import logging

from flask import Blueprint, g, jsonify, request
from sqlalchemy import desc, select
from sqlalchemy.orm import aliased

from src.database import db
from src.models.mt5_models import MT5Account
from src.models.trading_program import Challenge, TradingProgram
from src.models.user import User
from src.services.mt5_challenge_service import mt5_challenge_service
from src.services.mt5_service import MT5ProviderNotConfigured, mt5_service
from src.utils import crm_scope
from src.utils.decorators import admin_required, token_required
from src.utils.hierarchy_scoping import platform_root_scope


logger = logging.getLogger(__name__)
challenges_bp = Blueprint('challenges', __name__)

_PROVIDER_CODE = MT5ProviderNotConfigured.code
_TRADING_EVIDENCE_CODE = 'TRADING_EVIDENCE_NOT_CONFIGURED'
_AMBIGUOUS_BINDING_CODE = 'MT5_ACCOUNT_BINDING_AMBIGUOUS'
_UNVERIFIED_LEGACY = 'unverified_legacy'


def _read_only(f):
    """Do not flush pending ORM state while serving a legacy diagnostic read."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        with db.session.no_autoflush:
            return f(*args, **kwargs)
    return wrapped


def _error(message, status, code):
    return jsonify({'error': message, 'code': code}), status


def _provider_not_configured():
    """Return the provider boundary without inspecting request data or rows."""
    error = MT5ProviderNotConfigured()
    return _error(str(error), error.status, error.code)


def _trading_evidence_not_configured():
    """Refuse local rows as evidence before any resource lookup or mutation."""
    return _error(
        'Verified trading evidence integration is not configured',
        503,
        _TRADING_EVIDENCE_CODE,
    )


def _ambiguous_mt5_binding():
    """Do not choose an arbitrary legacy MT5 row where bindings are ambiguous."""
    return _error(
        'MT5 account binding is ambiguous',
        503,
        _AMBIGUOUS_BINDING_CODE,
    )


def _decimal_value(value):
    """Return a finite Decimal only; malformed legacy values stay unknown."""
    if value is None or isinstance(value, bool):
        return None
    try:
        value = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return value if value.is_finite() else None


def _decimal_string(value):
    """Preserve a known decimal exactly without JSON float conversion."""
    value = _decimal_value(value)
    return format(value, 'f') if value is not None else None


def _timestamp(value):
    return value.isoformat() if value is not None else None


def _legacy_challenge_projection(challenge, program, *, user=None):
    """Project only declared legacy columns; never invoke Challenge.to_dict()."""
    data = {
        'id': challenge.id,
        'user_id': challenge.user_id,
        'program': {
            'id': program.id,
            'name': program.name,
        },
        # These are observed legacy values, not server-authorized outcomes.
        'legacy_status': challenge.status,
        'legacy_payment_status': challenge.payment_status,
        'current_phase': challenge.current_phase,
        'total_phases': challenge.total_phases,
        'initial_balance': _decimal_string(challenge.initial_balance),
        'current_balance': _decimal_string(challenge.current_balance),
        'max_drawdown_observed': _decimal_string(challenge.max_drawdown),
        'start_date': _timestamp(challenge.start_date),
        'end_date': _timestamp(challenge.end_date),
        'passed_at': _timestamp(challenge.passed_at),
        'created_at': _timestamp(challenge.created_at),
        'data_status': _UNVERIFIED_LEGACY,
        'provider_authenticated': False,
    }
    if user is not None:
        data['user'] = {
            'id': user.id,
            'name': f'{user.first_name} {user.last_name}',
            'email': user.email,
        }
    return data


def _legacy_progress(challenge, program):
    """Bounded diagnostics only; legacy values cannot evaluate challenge rules."""
    initial = _decimal_value(challenge.initial_balance)
    current = _decimal_value(challenge.current_balance)
    target_percent = _decimal_value(program.profit_target)

    bounded_metrics = (
        initial is not None and initial > 0
        and target_percent is not None and target_percent > 0
    )
    profit_loss = current - initial if bounded_metrics and current is not None else None
    target_amount = None
    progress_percent = None
    if bounded_metrics:
        target_amount = initial * target_percent / Decimal('100')
        if profit_loss is not None and target_amount > 0:
            progress_percent = profit_loss * Decimal('100') / target_amount

    return {
        'initial_balance': _decimal_string(initial),
        'current_balance': _decimal_string(current),
        'profit_loss': _decimal_string(profit_loss),
        'profit_target_percent': _decimal_string(target_percent) if bounded_metrics else None,
        'profit_target_amount': _decimal_string(target_amount),
        'profit_progress_percent': _decimal_string(progress_percent),
        # There is no declared Challenge.trading_days column.  Do not invent a
        # five-day rule or an observed count from a mutable local record.
        'trading_days': None,
        'min_trading_days': None,
        'data_status': _UNVERIFIED_LEGACY,
        'provider_authenticated': False,
    }


def _legacy_mt5_projection(account):
    """Return stored metadata only, never decrypt credentials or synchronize."""
    return {
        'login': account.mt5_login,
        'server': account.mt5_server,
        'group': account.mt5_group,
        'status': account.status,
        # A missing stored snapshot is unknown, not zero or the initial balance.
        'balance': _decimal_string(account.balance),
        'equity': _decimal_string(account.equity),
        'margin': _decimal_string(account.margin),
        'free_margin': _decimal_string(account.free_margin),
        'margin_level': _decimal_string(account.margin_level),
        'updated_at': _timestamp(account.updated_at),
        'data_status': _UNVERIFIED_LEGACY,
        'provider_authenticated': False,
    }


def _strict_positive_query_integer(name, default, maximum):
    values = request.args.getlist(name)
    if len(values) > 1:
        return None
    value = default if not values else values[0]
    if not isinstance(value, str) or len(value) > len(str(maximum)) or not value.isascii() or not value.isdecimal():
        return None
    parsed = int(value)
    if str(parsed) != value or not 1 <= parsed <= maximum:
        return None
    return parsed


def _admin_list_arguments():
    """Accept a deliberately small, duplicate-free query surface."""
    allowed = {'page', 'per_page', 'status', 'include_mt5'}
    if any(key not in allowed for key in request.args):
        return None, _error('Invalid query parameters', 400, 'QUERY_INVALID')
    if any(len(request.args.getlist(key)) > 1 for key in allowed):
        return None, _error('Duplicate query parameters are not allowed', 400, 'QUERY_INVALID')

    page = _strict_positive_query_integer('page', '1', 1000)
    per_page = _strict_positive_query_integer('per_page', '20', 100)
    if page is None or per_page is None:
        return None, _error('Invalid pagination', 400, 'PAGINATION_INVALID')

    include_mt5 = request.args.get('include_mt5', 'true')
    if include_mt5 not in {'true', 'false'}:
        return None, _error('include_mt5 must be true or false', 400, 'QUERY_INVALID')

    status = request.args.get('status')
    if status is not None and (not status or len(status) > 20):
        return None, _error('Invalid status', 400, 'QUERY_INVALID')
    return {
        'page': page,
        'per_page': per_page,
        'status': status,
        'include_mt5': include_mt5 == 'true',
    }, None


def _my_challenge_list_arguments():
    """Accept only bounded owner-list filters, without MT5 lookup controls."""
    allowed = {'page', 'per_page', 'status'}
    if any(key not in allowed for key in request.args):
        return None, _error('Invalid query parameters', 400, 'QUERY_INVALID')
    if any(len(request.args.getlist(key)) > 1 for key in allowed):
        return None, _error('Duplicate query parameters are not allowed', 400, 'QUERY_INVALID')

    page = _strict_positive_query_integer('page', '1', 1000)
    per_page = _strict_positive_query_integer('per_page', '20', 100)
    if page is None or per_page is None:
        return None, _error('Invalid pagination', 400, 'PAGINATION_INVALID')

    status = request.args.get('status')
    if status is not None and (not status or len(status) > 20):
        return None, _error('Invalid status', 400, 'QUERY_INVALID')
    return {
        'page': page,
        'per_page': per_page,
        'status': status,
    }, None


def _admin_challenge_query(actor):
    """Build the explicit root-or-CRM scope and require a matching program tenant."""
    query = db.session.query(Challenge, User, TradingProgram).join(
        User, Challenge.user_id == User.id
    ).join(
        TradingProgram, Challenge.program_id == TradingProgram.id
    ).filter(
        User.tenant_id == TradingProgram.tenant_id,
    )

    # A corrupted account binding is not an authorization proof.  Use an alias
    # in the subquery so its Challenge columns cannot self-correlate away.
    # Hide that challenge rather than attaching another user's account to it.
    bound_challenge = aliased(Challenge)
    foreign_binding_ids = select(MT5Account.challenge_id).join(
        bound_challenge, MT5Account.challenge_id == bound_challenge.id
    ).filter(
        MT5Account.user_id != bound_challenge.user_id,
    )
    query = query.filter(~Challenge.id.in_(foreign_binding_ids))

    if not platform_root_scope(actor):
        # CRM's current tenant/downline predicate is the non-root authority.
        # It returns no rows when the actor lacks a valid tenant scope.
        scoped_user_ids = crm_scope.scoped_users(actor).with_entities(User.id)
        query = query.filter(Challenge.user_id.in_(scoped_user_ids))
    return query


@challenges_bp.route('/', methods=['POST'])
@token_required
def create_challenge(current_user):
    """Legacy direct creation remains disabled pending canonical settlement."""
    return _error(
        'Order settlement is not configured',
        503,
        'ORDER_SETTLEMENT_NOT_CONFIGURED',
    )


@challenges_bp.route('/my-challenges', methods=['GET'])
@_read_only
@token_required
def get_my_challenges(current_user):
    """List the caller's tenant-consistent legacy challenge snapshots only."""
    arguments, argument_error = _my_challenge_list_arguments()
    if argument_error:
        return argument_error

    try:
        query = db.session.query(Challenge, TradingProgram).join(
            TradingProgram, Challenge.program_id == TradingProgram.id
        ).filter(
            Challenge.user_id == current_user.id,
            TradingProgram.tenant_id == current_user.tenant_id,
        )
        if arguments['status'] is not None:
            query = query.filter(Challenge.status == arguments['status'])

        total = query.order_by(None).count()
        offset = (arguments['page'] - 1) * arguments['per_page']
        rows = query.order_by(desc(Challenge.created_at), desc(Challenge.id)).offset(offset).limit(
            arguments['per_page']
        ).all()
        challenges = [
            _legacy_challenge_projection(challenge, program)
            for challenge, program in rows
        ]
        pages = (total + arguments['per_page'] - 1) // arguments['per_page']
        return jsonify({
            'challenges': challenges,
            'pagination': {
                'page': arguments['page'],
                'per_page': arguments['per_page'],
                'total': total,
                'pages': pages,
            },
            'data_status': _UNVERIFIED_LEGACY,
            'provider_authenticated': False,
        }), 200
    except Exception:
        logger.exception('Owner challenge listing failed')
        return _error('Unable to retrieve challenges', 500, 'CHALLENGE_READ_FAILED')


@challenges_bp.route('/<int:challenge_id>/start', methods=['POST'])
@token_required
def start_challenge(current_user, challenge_id):
    """Legacy activation remains disabled pending canonical settlement."""
    return _error(
        'Order settlement is not configured',
        503,
        'ORDER_SETTLEMENT_NOT_CONFIGURED',
    )


@challenges_bp.route('/<int:challenge_id>/evaluate', methods=['POST'])
@token_required
@admin_required
def evaluate_challenge(challenge_id):
    """Never evaluate mutable local balances as trading evidence."""
    return _trading_evidence_not_configured()


@challenges_bp.route('/<int:challenge_id>/fund', methods=['POST'])
@token_required
@admin_required
def fund_challenge(challenge_id):
    """Never fund a challenge without an authenticated provider command."""
    return _provider_not_configured()


@challenges_bp.route('/<int:challenge_id>/trades', methods=['POST'])
@token_required
def add_trade(current_user, challenge_id):
    """Never accept client-supplied trades as trading evidence."""
    return _trading_evidence_not_configured()


@challenges_bp.route('/admin/all', methods=['GET'])
@token_required
@admin_required
@_read_only
def get_all_challenges():
    """List bounded, explicitly scoped legacy snapshots without provider I/O."""
    arguments, argument_error = _admin_list_arguments()
    if argument_error:
        return argument_error

    try:
        query = _admin_challenge_query(g.current_user)
        if arguments['status'] is not None:
            query = query.filter(Challenge.status == arguments['status'])

        total = query.order_by(None).count()
        offset = (arguments['page'] - 1) * arguments['per_page']
        rows = query.order_by(desc(Challenge.created_at), desc(Challenge.id)).offset(offset).limit(
            arguments['per_page']
        ).all()

        accounts_by_challenge = {}
        if arguments['include_mt5'] and rows:
            challenge_ids = [challenge.id for challenge, _user, _program in rows]
            # At most one account is expected per challenge.  Reading 201 rather
            # than silently truncating detects an unbounded corrupt legacy set.
            accounts = db.session.query(MT5Account).join(
                Challenge, MT5Account.challenge_id == Challenge.id
            ).filter(
                MT5Account.challenge_id.in_(challenge_ids),
                MT5Account.user_id == Challenge.user_id,
            ).order_by(MT5Account.id).limit(201).all()
            if len(accounts) >= 201:
                return _ambiguous_mt5_binding()
            for account in accounts:
                accounts_by_challenge.setdefault(account.challenge_id, []).append(account)

        challenges = []
        for challenge, user, program in rows:
            item = _legacy_challenge_projection(challenge, program, user=user)
            accounts = accounts_by_challenge.get(challenge.id, [])
            if not arguments['include_mt5']:
                item['mt5_account'] = None
                item['mt5_account_binding'] = 'not_requested'
            elif len(accounts) == 1:
                item['mt5_account'] = _legacy_mt5_projection(accounts[0])
                item['mt5_account_binding'] = 'single_unverified_legacy'
            elif len(accounts) > 1:
                # Never select the first row from a corrupted one-to-many link.
                item['mt5_account'] = None
                item['mt5_account_binding'] = 'ambiguous'
            else:
                item['mt5_account'] = None
                item['mt5_account_binding'] = 'not_linked'
            challenges.append(item)

        pages = (total + arguments['per_page'] - 1) // arguments['per_page']
        return jsonify({
            'challenges': challenges,
            'pagination': {
                'page': arguments['page'],
                'per_page': arguments['per_page'],
                'total': total,
                'pages': pages,
            },
            'data_status': _UNVERIFIED_LEGACY,
            'provider_authenticated': False,
        }), 200
    except Exception:
        logger.exception('Scoped challenge listing failed')
        return _error('Unable to retrieve challenges', 500, 'CHALLENGE_READ_FAILED')


@challenges_bp.route('/admin/<int:challenge_id>', methods=['DELETE'])
@token_required
@admin_required
def delete_challenge(challenge_id):
    """Keep challenge and trade history immutable until an evidence policy exists."""
    return _trading_evidence_not_configured()


@challenges_bp.route('/<int:challenge_id>/mt5-credentials', methods=['GET'])
@token_required
def get_mt5_credentials(current_user, challenge_id):
    """Credentials require a provider-authenticated, encrypted delivery contract."""
    return _provider_not_configured()


@challenges_bp.route('/<int:challenge_id>/create-mt5-account', methods=['POST'])
@token_required
def create_mt5_account_manual(current_user, challenge_id):
    """Manual provisioning cannot rely on a mutable paid flag or local account row."""
    return _provider_not_configured()


@challenges_bp.route('/<int:challenge_id>/progress', methods=['GET'])
@token_required
@_read_only
def get_challenge_progress(current_user, challenge_id):
    """Show an owner-only, non-synchronizing legacy diagnostic snapshot."""
    try:
        # Normal progress views deliberately have no administrator/root bypass.
        row = db.session.query(Challenge, TradingProgram).join(
            TradingProgram, Challenge.program_id == TradingProgram.id
        ).filter(
            Challenge.id == challenge_id,
            Challenge.user_id == current_user.id,
            TradingProgram.tenant_id == current_user.tenant_id,
        ).first()
        if row is None:
            return _error('Challenge not found', 404, 'CHALLENGE_NOT_FOUND')
        challenge, program = row

        # Query at most two owner-bound rows so ambiguity cannot become a
        # first-row credential/account selection.  A foreign owner is excluded.
        accounts = MT5Account.query.filter(
            MT5Account.challenge_id == challenge.id,
            MT5Account.user_id == current_user.id,
        ).order_by(MT5Account.id).limit(2).all()
        if len(accounts) > 1:
            return _ambiguous_mt5_binding()

        return jsonify({
            'challenge': _legacy_challenge_projection(challenge, program),
            'progress': _legacy_progress(challenge, program),
            'mt5_account': _legacy_mt5_projection(accounts[0]) if accounts else None,
            'data_status': _UNVERIFIED_LEGACY,
            'provider_authenticated': False,
        }), 200
    except Exception:
        logger.exception('Scoped challenge progress lookup failed')
        return _error('Unable to retrieve challenge progress', 500, 'CHALLENGE_READ_FAILED')
