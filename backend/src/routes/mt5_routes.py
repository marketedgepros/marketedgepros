"""Bounded legacy MT5 read routes.

The deployed MT5 tables are retained as unverified historical data only.  This
module deliberately does not provision, mutate, or synchronize a provider until
a reviewed provider protocol is available.
"""
import logging

from flask import Blueprint, current_app, jsonify, request
from sqlalchemy import and_, case, false, func, or_

from src.database import db
from src.middleware.tenant_middleware import get_current_tenant
from src.models.mt5_models import MT5Account, MT5Position, MT5Trade
from src.models.tenant import Tenant
from src.models.trading_program import Challenge, TradingProgram
from src.models.user import User
from src.utils.crm_scope import scoped_users
from src.utils.decorators import admin_required, token_required
from src.utils.hierarchy_scoping import platform_root_scope

logger = logging.getLogger(__name__)

mt5_bp = Blueprint("mt5", __name__, url_prefix="/api/mt5")

_PAGE_MIN = 1
_PAGE_MAX = 1000
_PER_PAGE_MIN = 1
_PER_PAGE_MAX = 100
_MT5_NOT_CONFIGURED_CODE = "MT5_PROVIDER_NOT_CONFIGURED"
_MT5_NOT_CONFIGURED_MESSAGE = "MT5 provider is not configured"


def _not_configured_response():
    """Refuse every legacy mutator before parsing a body or querying a row."""
    return jsonify({
        "success": False,
        "message": _MT5_NOT_CONFIGURED_MESSAGE,
        "code": _MT5_NOT_CONFIGURED_CODE,
    }), 503


def _invalid_query_response():
    """Keep malformed list input separate from provider/read failure details."""
    return jsonify({
        "success": False,
        "message": "Invalid MT5 query parameters",
        "code": "INVALID_MT5_QUERY",
    }), 400


def _parse_bounded_positive_int(name, default, minimum, maximum):
    """Parse exactly one canonical decimal query value, or return ``None``."""
    values = request.args.getlist(name)
    if not values:
        return default
    if len(values) != 1:
        return None
    value = values[0]
    if not value or len(value) > len(str(maximum)) or not value.isascii() or not value.isdecimal():
        return None
    parsed = int(value)
    if str(parsed) != value or not minimum <= parsed <= maximum:
        return None
    return parsed


def _pagination_parameters():
    page = _parse_bounded_positive_int("page", 1, _PAGE_MIN, _PAGE_MAX)
    per_page = _parse_bounded_positive_int(
        "per_page", 50, _PER_PAGE_MIN, _PER_PAGE_MAX,
    )
    if page is None or per_page is None:
        return None
    return page, per_page


def _trade_status_parameter():
    values = request.args.getlist("status")
    if not values:
        return "all"
    if len(values) != 1 or values[0] not in {"all", "open", "closed"}:
        return None
    return values[0]


def _pagination_payload(page_result, page, per_page):
    return {
        "total": page_result.total,
        "page": page,
        "pages": page_result.pages,
        "per_page": per_page,
        "returned_count": len(page_result.items),
    }


def _legacy_metadata(account=None, *, profit_data_status=None):
    """Describe persisted rows without suggesting a live MT5 verification."""
    metadata = {
        "source": "persisted_legacy",
        "mt5_freshness": "not_verified",
    }
    if account is not None:
        # An account without a challenge is historical data, not a reconstructed
        # entitlement.  It is readable only because the real owner/tenant joins
        # below remain valid.
        metadata["challenge_link"] = (
            "legacy_unlinked" if account.challenge_id is None else "stored"
        )
        metadata["entitlement"] = "not_verified"
    if profit_data_status is not None:
        metadata["profit_data_status"] = profit_data_status
    return metadata


def _replace_unknown_numbers(data, model, fields):
    """The legacy model serializes ``None`` like zero; restore unknown to null."""
    for field in fields:
        if getattr(model, field) is None:
            data[field] = None
    return data


def _serialize_account(account):
    data = account.to_dict(include_password=False)
    # Defensive deletion protects callers if the model's serializer later grows
    # a compatibility password option again.
    data.pop("mt5_password", None)
    _replace_unknown_numbers(
        data,
        account,
        ("balance", "equity", "margin", "free_margin", "margin_level"),
    )
    data["data_status"] = "unverified_legacy"
    data["metadata"] = _legacy_metadata(account)
    return data


def _serialize_trade(trade):
    data = trade.to_dict()
    _replace_unknown_numbers(
        data,
        trade,
        (
            "volume", "open_price", "close_price", "stop_loss", "take_profit",
            "profit", "commission", "swap",
        ),
    )
    data["data_status"] = "unverified_legacy"
    data["metadata"] = _legacy_metadata()
    return data


def _serialize_position(position):
    data = position.to_dict()
    _replace_unknown_numbers(
        data,
        position,
        (
            "volume", "price_open", "price_current", "stop_loss", "take_profit",
            "profit", "swap", "commission",
        ),
    )
    data["data_status"] = "unverified_legacy"
    data["metadata"] = _legacy_metadata()
    return data


def _valid_current_tenant_id(current_user):
    tenant_id = getattr(current_user, "tenant_id", None)
    if isinstance(tenant_id, bool) or not isinstance(tenant_id, int) or tenant_id < 1:
        return None
    return tenant_id


def _valid_current_user_id(current_user):
    user_id = getattr(current_user, "id", None)
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id < 1:
        return None
    return user_id


def _base_account_query(current_user, *, all_active_tenants=False):
    """Return only accounts whose user/challenge/program tenant chain is valid.

    ``MT5Account`` has no tenant column and does not participate in the generic
    hierarchy model hook.  Every read therefore joins the actual owner and, for
    challenge-linked rows, the actual challenge and program.  Null challenge IDs
    are an explicit legacy case rather than an implicit cross-tenant fallback.
    """
    tenant_id = _valid_current_tenant_id(current_user)
    if tenant_id is None:
        return MT5Account.query.filter(false())

    challenge_chain_is_valid = or_(
        MT5Account.challenge_id.is_(None),
        and_(
            Challenge.id.is_not(None),
            Challenge.user_id == MT5Account.user_id,
            TradingProgram.id.is_not(None),
            TradingProgram.tenant_id == User.tenant_id,
        ),
    )
    filters = [
        User.is_active.is_(True),
        User.is_verified.is_(True),
        Tenant.status == "active",
        challenge_chain_is_valid,
    ]
    if not all_active_tenants:
        filters.insert(0, User.tenant_id == tenant_id)

    return (
        MT5Account.query
        .join(User, User.id == MT5Account.user_id)
        .join(Tenant, Tenant.id == User.tenant_id)
        .outerjoin(Challenge, Challenge.id == MT5Account.challenge_id)
        .outerjoin(TradingProgram, TradingProgram.id == Challenge.program_id)
        .filter(*filters)
    )


def _owner_account_query(current_user):
    user_id = _valid_current_user_id(current_user)
    query = _base_account_query(current_user)
    if user_id is None:
        return query.filter(false())
    return query.filter(User.id == user_id)


def _configured_root_can_read_wide(current_user):
    """Allow the one configured platform root the documented broad admin view."""
    if not platform_root_scope(current_user):
        return False
    if current_app.config.get("EXPANDED_HIERARCHY_ENABLED", False):
        return True

    # The launch-mode root exception remains tied to the same active configured
    # brand used by session authentication; it is never a generic all-row bypass.
    tenant = get_current_tenant()
    return (
        tenant is not None
        and tenant.status == "active"
        and tenant.id == _valid_current_tenant_id(current_user)
    )


def _admin_account_query(current_user):
    if _configured_root_can_read_wide(current_user):
        return _base_account_query(current_user, all_active_tenants=True)
    # Future-mode administrators receive the existing CRM tenant/downline scope,
    # rather than relying on the generic User loader criterion or reading all MT5
    # rows simply because this model predates tenant_id.
    return scoped_users(current_user, _base_account_query(current_user))


def _scoped_owner_account(current_user, account_id):
    with db.session.no_autoflush:
        return _owner_account_query(current_user).filter(
            MT5Account.id == account_id,
        ).first()


@mt5_bp.route("/accounts", methods=["GET"])
@token_required
def get_user_mt5_accounts(current_user):
    """Return a bounded page of the caller's verified-owner legacy accounts."""
    pagination = _pagination_parameters()
    if pagination is None:
        return _invalid_query_response()
    page, per_page = pagination
    try:
        with db.session.no_autoflush:
            accounts = _owner_account_query(current_user).order_by(
                MT5Account.id.asc(),
            ).paginate(page=page, per_page=per_page, error_out=False)
        payload = {
            "success": True,
            "accounts": [_serialize_account(account) for account in accounts.items],
            "data_status": "unverified_legacy",
            "metadata": _legacy_metadata(),
        }
        payload.update(_pagination_payload(accounts, page, per_page))
        return jsonify(payload), 200
    except Exception:
        logger.error("MT5 account list read failed")
        return jsonify({
            "success": False,
            "message": "Unable to retrieve MT5 data",
            "code": "MT5_READ_UNAVAILABLE",
        }), 500


@mt5_bp.route("/accounts/<int:account_id>", methods=["GET"])
@token_required
def get_mt5_account(current_user, account_id):
    """Return a caller-owned persisted row; no provider call is made."""
    try:
        account = _scoped_owner_account(current_user, account_id)
        if account is None:
            return jsonify({"success": False, "message": "Account not found"}), 404
        return jsonify({
            "success": True,
            "account": _serialize_account(account),
            "data_status": "unverified_legacy",
            "metadata": _legacy_metadata(),
        }), 200
    except Exception:
        logger.error("MT5 account detail read failed")
        return jsonify({
            "success": False,
            "message": "Unable to retrieve MT5 data",
            "code": "MT5_READ_UNAVAILABLE",
        }), 500


@mt5_bp.route("/accounts/create", methods=["POST"])
@token_required
def create_mt5_account(current_user):
    """Refuse provisioning until a reviewed MT5 provider protocol exists."""
    return _not_configured_response()


@mt5_bp.route("/accounts/<int:account_id>/trades", methods=["GET"])
@token_required
def get_account_trades(current_user, account_id):
    """Return a bounded, exact-status page of persisted legacy trades."""
    pagination = _pagination_parameters()
    status = _trade_status_parameter()
    if pagination is None or status is None:
        return _invalid_query_response()
    page, per_page = pagination
    try:
        account = _scoped_owner_account(current_user, account_id)
        if account is None:
            return jsonify({"success": False, "message": "Account not found"}), 404
        with db.session.no_autoflush:
            query = MT5Trade.query.filter(MT5Trade.mt5_account_id == account.id)
            if status != "all":
                query = query.filter(MT5Trade.status == status)
            trades = query.order_by(
                MT5Trade.open_time.desc(), MT5Trade.id.desc(),
            ).paginate(page=page, per_page=per_page, error_out=False)
        payload = {
            "success": True,
            "trades": [_serialize_trade(trade) for trade in trades.items],
            "status": status,
            "data_status": "unverified_legacy",
            "metadata": _legacy_metadata(),
        }
        payload.update(_pagination_payload(trades, page, per_page))
        return jsonify(payload), 200
    except Exception:
        logger.error("MT5 trade list read failed")
        return jsonify({
            "success": False,
            "message": "Unable to retrieve MT5 data",
            "code": "MT5_READ_UNAVAILABLE",
        }), 500


@mt5_bp.route("/accounts/<int:account_id>/positions", methods=["GET"])
@token_required
def get_account_positions(current_user, account_id):
    """Return a bounded page of persisted open-position rows."""
    pagination = _pagination_parameters()
    if pagination is None:
        return _invalid_query_response()
    page, per_page = pagination
    try:
        account = _scoped_owner_account(current_user, account_id)
        if account is None:
            return jsonify({"success": False, "message": "Account not found"}), 404
        with db.session.no_autoflush:
            positions = MT5Position.query.filter(
                MT5Position.mt5_account_id == account.id,
            ).order_by(
                MT5Position.open_time.desc(), MT5Position.id.desc(),
            ).paginate(page=page, per_page=per_page, error_out=False)
        payload = {
            "success": True,
            "positions": [_serialize_position(position) for position in positions.items],
            "data_status": "unverified_legacy",
            "metadata": _legacy_metadata(),
        }
        payload.update(_pagination_payload(positions, page, per_page))
        return jsonify(payload), 200
    except Exception:
        logger.error("MT5 position list read failed")
        return jsonify({
            "success": False,
            "message": "Unable to retrieve MT5 data",
            "code": "MT5_READ_UNAVAILABLE",
        }), 500


@mt5_bp.route("/accounts/<int:account_id>/stats", methods=["GET"])
@token_required
def get_account_stats(current_user, account_id):
    """Aggregate closed-trade statistics in SQL without treating null profit as 0."""
    try:
        account = _scoped_owner_account(current_user, account_id)
        if account is None:
            return jsonify({"success": False, "message": "Account not found"}), 404

        with db.session.no_autoflush:
            aggregate = (
                MT5Trade.query
                .filter(
                    MT5Trade.mt5_account_id == account.id,
                    MT5Trade.status == "closed",
                )
                .with_entities(
                    func.count(MT5Trade.id).label("total_trades"),
                    func.coalesce(func.sum(case((MT5Trade.profit > 0, 1), else_=0)), 0).label("winning_trades"),
                    func.coalesce(func.sum(case((MT5Trade.profit < 0, 1), else_=0)), 0).label("losing_trades"),
                    func.coalesce(func.sum(case((MT5Trade.profit.is_not(None), MT5Trade.profit), else_=0)), 0).label("net_profit"),
                    func.coalesce(func.sum(case((MT5Trade.profit > 0, MT5Trade.profit), else_=0)), 0).label("gross_profit"),
                    func.coalesce(func.sum(case((MT5Trade.profit < 0, MT5Trade.profit), else_=0)), 0).label("gross_loss"),
                    func.coalesce(func.sum(case((MT5Trade.profit.is_(None), 1), else_=0)), 0).label("missing_profit_rows"),
                )
                .one()
            )
            open_positions = MT5Position.query.filter(
                MT5Position.mt5_account_id == account.id,
            ).count()

        total_trades = int(aggregate.total_trades or 0)
        winning_trades = int(aggregate.winning_trades or 0)
        losing_trades = int(aggregate.losing_trades or 0)
        missing_profit_rows = int(aggregate.missing_profit_rows or 0)
        profit_data_status = "unknown" if missing_profit_rows else "unverified_legacy"

        if missing_profit_rows:
            net_profit = None
            gross_profit = None
            gross_loss = None
            win_rate = None
            profit_factor = None
        else:
            net_profit = float(aggregate.net_profit)
            gross_profit = float(aggregate.gross_profit)
            gross_loss = float(aggregate.gross_loss)
            win_rate = round((winning_trades / total_trades) * 100, 2) if total_trades else 0
            profit_factor = (
                round(gross_profit / abs(gross_loss), 2)
                if gross_loss < 0
                else None
            )

        stats = {
            "total_trades": total_trades,
            "winning_trades": winning_trades,
            "losing_trades": losing_trades,
            "missing_profit_rows": missing_profit_rows,
            "win_rate": win_rate,
            "total_profit": net_profit,
            "gross_profit": gross_profit,
            "total_loss": gross_loss,
            "gross_loss": gross_loss,
            "profit_factor": profit_factor,
            "open_positions": open_positions,
            "current_balance": float(account.balance) if account.balance is not None else None,
            "current_equity": float(account.equity) if account.equity is not None else None,
            "profit_data_status": profit_data_status,
        }
        return jsonify({
            "success": True,
            "stats": stats,
            "data_status": "unverified_legacy",
            "metadata": _legacy_metadata(
                account,
                profit_data_status=profit_data_status,
            ),
        }), 200
    except Exception:
        logger.error("MT5 statistics read failed")
        return jsonify({
            "success": False,
            "message": "Unable to retrieve MT5 data",
            "code": "MT5_READ_UNAVAILABLE",
        }), 500


@mt5_bp.route("/admin/accounts", methods=["GET"])
@token_required
@admin_required
def admin_get_all_accounts(current_user):
    """List bounded valid account rows within explicit root/CRM scope."""
    pagination = _pagination_parameters()
    if pagination is None:
        return _invalid_query_response()
    page, per_page = pagination
    try:
        with db.session.no_autoflush:
            accounts = _admin_account_query(current_user).order_by(
                MT5Account.id.asc(),
            ).paginate(page=page, per_page=per_page, error_out=False)
        payload = {
            "success": True,
            "accounts": [_serialize_account(account) for account in accounts.items],
            "data_status": "unverified_legacy",
            "metadata": _legacy_metadata(),
        }
        payload.update(_pagination_payload(accounts, page, per_page))
        return jsonify(payload), 200
    except Exception:
        logger.error("MT5 administrator account list read failed")
        return jsonify({
            "success": False,
            "message": "Unable to retrieve MT5 data",
            "code": "MT5_READ_UNAVAILABLE",
        }), 500


@mt5_bp.route("/admin/accounts/<int:account_id>/disable", methods=["POST"])
@token_required
@admin_required
def admin_disable_account(current_user, account_id):
    """Refuse local status changes without an approved provider workflow."""
    return _not_configured_response()


@mt5_bp.route("/admin/accounts/<int:account_id>/balance", methods=["POST"])
@token_required
@admin_required
def admin_update_balance(current_user, account_id):
    """Refuse local balance writes without an approved provider workflow."""
    return _not_configured_response()


@mt5_bp.route("/sync/<int:account_id>", methods=["POST"])
@token_required
def sync_account_data(current_user, account_id):
    """Refuse fake timestamp sync success until a provider protocol exists."""
    return _not_configured_response()
