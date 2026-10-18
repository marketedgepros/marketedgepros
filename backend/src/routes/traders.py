"""
Trader routes for trading operations and account management
"""
from flask import Blueprint, request, jsonify, g
from src.database import db
from src.models.user import User
from src.models.trading_program import Challenge
from src.models.trade import Trade
from src.models.withdrawal import Withdrawal
from src.utils.decorators import token_required
from src.services.trading_history_service import (
    TradingHistoryArgumentError,
    TradingHistoryService,
)
from datetime import datetime, timedelta
from sqlalchemy import func, and_, desc

traders_bp = Blueprint('traders', __name__)


@traders_bp.route('/dashboard', methods=['GET'])
@token_required
def get_trader_dashboard():
    """Get trader dashboard data"""
    try:
        user_id = g.current_user.id
        
        # Get active challenge
        active_challenge = Challenge.query.filter_by(
            user_id=user_id,
            status='active'
        ).first()
        
        if not active_challenge:
            return jsonify({
                'message': 'No active challenge found',
                'has_challenge': False
            }), 200
        
        # Calculate account metrics
        balance = float(active_challenge.current_balance)
        initial_balance = float(active_challenge.initial_balance)
        equity = balance  # In real scenario, calculate with open positions
        total_pnl = balance - initial_balance
        total_pnl_percentage = (total_pnl / initial_balance) * 100 if initial_balance > 0 else 0
        
        # Calculate drawdown (relative to initial balance)
        max_balance = float(active_challenge.max_balance or initial_balance)
        current_drawdown = ((max_balance - balance) / initial_balance) * 100 if initial_balance > 0 else 0
        max_drawdown = float(active_challenge.max_total_drawdown)
        
        # Get trading statistics
        trades = Trade.query.filter_by(challenge_id=active_challenge.id).all()
        total_trades = len(trades)
        winning_trades = len([t for t in trades if t.profit > 0])
        losing_trades = len([t for t in trades if t.profit < 0])
        win_rate = (winning_trades / total_trades * 100) if total_trades > 0 else 0
        
        # Calculate average win/loss
        wins = [float(t.profit) for t in trades if t.profit > 0]
        losses = [float(t.profit) for t in trades if t.profit < 0]
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        
        # Calculate profit factor
        total_wins = sum(wins)
        total_losses = abs(sum(losses))
        profit_factor = total_wins / total_losses if total_losses > 0 else 0
        
        # Challenge progress
        profit_target = float(active_challenge.profit_target)
        profit_achieved = total_pnl
        profit_progress = (profit_achieved / profit_target * 100) if profit_target > 0 else 0
        
        # Trading days
        trading_days = active_challenge.trading_days or 0
        min_trading_days = active_challenge.min_trading_days or 5
        days_progress = (trading_days / min_trading_days * 100) if min_trading_days > 0 else 0
        
        # Recent trades (last 5)
        recent_trades = Trade.query.filter_by(
            challenge_id=active_challenge.id
        ).order_by(desc(Trade.close_time)).limit(5).all()
        
        return jsonify({
            'has_challenge': True,
            'challenge': {
                'id': active_challenge.id,
                'status': active_challenge.status,
                'phase': active_challenge.phase,
                'created_at': active_challenge.created_at.isoformat()
            },
            'account': {
                'balance': balance,
                'equity': equity,
                'total_pnl': total_pnl,
                'total_pnl_percentage': round(total_pnl_percentage, 2)
            },
            'drawdown': {
                'current': round(current_drawdown, 2),
                'max_allowed': max_drawdown
            },
            'progress': {
                'profit': {
                    'target': profit_target,
                    'achieved': profit_achieved,
                    'remaining': profit_target - profit_achieved,
                    'percentage': round(profit_progress, 2)
                },
                'days': {
                    'completed': trading_days,
                    'required': min_trading_days,
                    'remaining': max(0, min_trading_days - trading_days),
                    'percentage': round(days_progress, 2)
                }
            },
            'statistics': {
                'total_trades': total_trades,
                'winning_trades': winning_trades,
                'losing_trades': losing_trades,
                'win_rate': round(win_rate, 2),
                'average_win': round(avg_win, 2),
                'average_loss': round(avg_loss, 2),
                'profit_factor': round(profit_factor, 2)
            },
            'recent_trades': [{
                'id': trade.id,
                'symbol': trade.symbol,
                'type': trade.trade_type,
                'lots': float(trade.lots),
                'open_price': float(trade.open_price),
                'close_price': float(trade.close_price),
                'profit': float(trade.profit),
                'pips': float(trade.pips) if trade.pips else 0,
                'open_time': trade.open_time.isoformat(),
                'close_time': trade.close_time.isoformat() if trade.close_time else None
            } for trade in recent_trades]
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@traders_bp.route('/history', methods=['GET'])
@token_required
def get_trading_history():
    """Return the JWT owner's bounded, tenant-consistent legacy trade records."""
    actor = g.current_user
    # Do not inspect Challenge, TradingProgram, or Trade when tenant identity is
    # absent.  Admin role is deliberately not a bypass for this personal route.
    if actor.tenant_id is None:
        return jsonify({
            'error': 'Tenant context is required',
            'code': 'TENANT_CONTEXT_REQUIRED',
        }), 403

    try:
        arguments = TradingHistoryService.parse_arguments(request.args)
    except TradingHistoryArgumentError:
        return jsonify({
            'error': 'Invalid trading history query',
            'code': 'TRADING_HISTORY_QUERY_INVALID',
        }), 400

    try:
        return jsonify(TradingHistoryService.get_history(actor, arguments)), 200
    except Exception:
        # Legacy data must never expose a provider/database exception verbatim.
        return jsonify({
            'error': 'Trading history is unavailable',
            'code': 'TRADING_HISTORY_UNAVAILABLE',
        }), 503


@traders_bp.route('/withdrawals', methods=['GET'])
@token_required
def get_withdrawals():
    """Return one safe, tenant-owned page of legacy withdrawal records."""
    try:
        from src.services.financial_records_read import (
            FinancialRecordsQueryInvalid,
            FinancialRecordsReadService,
            FinancialRecordsTenantRequired,
        )

        arguments = FinancialRecordsReadService.parse_withdrawals_query(request.args)
        return jsonify(FinancialRecordsReadService.withdrawals_for_owner(g.current_user, arguments)), 200
    except FinancialRecordsTenantRequired:
        return jsonify({
            'error': 'Tenant context is required',
            'code': 'TENANT_CONTEXT_REQUIRED',
        }), 403
    except FinancialRecordsQueryInvalid:
        return jsonify({
            'error': 'Invalid withdrawal request',
            'code': 'FINANCIAL_RECORDS_QUERY_INVALID',
        }), 400
    except Exception:
        return jsonify({
            'error': 'Withdrawal records are unavailable',
            'code': 'FINANCIAL_RECORDS_UNAVAILABLE',
        }), 503


@traders_bp.route('/withdrawals', methods=['POST'])
@token_required
def request_withdrawal():
    """Refuse legacy withdrawal creation after token/CSRF checks and before body I/O."""
    from src.services.wallet_service import WalletLedgerNotConfigured

    refusal = WalletLedgerNotConfigured()
    return jsonify({
        'error': 'Wallet ledger is not configured',
        'code': refusal.code,
    }), refusal.status


@traders_bp.route('/challenges', methods=['GET'])
@token_required
def get_trader_challenges():
    """Get all challenges for the trader"""
    try:
        user_id = g.current_user.id
        
        challenges = Challenge.query.filter_by(
            user_id=user_id
        ).order_by(desc(Challenge.created_at)).all()
        
        return jsonify({
            'challenges': [{
                'id': challenge.id,
                'program_id': challenge.program_id,
                'status': challenge.status,
                'phase': challenge.phase,
                'initial_balance': float(challenge.initial_balance),
                'current_balance': float(challenge.current_balance),
                'profit_target': float(challenge.profit_target),
                'max_daily_loss': float(challenge.max_daily_loss),
                'max_total_drawdown': float(challenge.max_total_drawdown),
                'trading_days': challenge.trading_days,
                'min_trading_days': challenge.min_trading_days,
                'created_at': challenge.created_at.isoformat(),
                'started_at': challenge.started_at.isoformat() if challenge.started_at else None,
                'completed_at': challenge.completed_at.isoformat() if challenge.completed_at else None
            } for challenge in challenges]
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@traders_bp.route('/challenges/<int:challenge_id>', methods=['GET'])
@token_required
def get_challenge_details(challenge_id):
    """Get detailed information about a specific challenge"""
    try:
        user_id = g.current_user.id
        
        challenge = Challenge.query.filter_by(
            id=challenge_id,
            user_id=user_id
        ).first_or_404()
        
        # Get trades for this challenge
        trades = Trade.query.filter_by(
            challenge_id=challenge_id
        ).order_by(desc(Trade.close_time)).limit(10).all()
        
        # Calculate metrics
        total_trades = Trade.query.filter_by(challenge_id=challenge_id).count()
        winning_trades = Trade.query.filter(
            and_(Trade.challenge_id == challenge_id, Trade.profit > 0)
        ).count()
        
        return jsonify({
            'challenge': {
                'id': challenge.id,
                'program_id': challenge.program_id,
                'status': challenge.status,
                'phase': challenge.phase,
                'initial_balance': float(challenge.initial_balance),
                'current_balance': float(challenge.current_balance),
                'max_balance': float(challenge.max_balance or challenge.initial_balance),
                'profit_target': float(challenge.profit_target),
                'max_daily_loss': float(challenge.max_daily_loss),
                'max_total_drawdown': float(challenge.max_total_drawdown),
                'trading_days': challenge.trading_days,
                'min_trading_days': challenge.min_trading_days,
                'created_at': challenge.created_at.isoformat(),
                'started_at': challenge.started_at.isoformat() if challenge.started_at else None,
                'completed_at': challenge.completed_at.isoformat() if challenge.completed_at else None
            },
            'statistics': {
                'total_trades': total_trades,
                'winning_trades': winning_trades,
                'win_rate': (winning_trades / total_trades * 100) if total_trades > 0 else 0
            },
            'recent_trades': [{
                'id': trade.id,
                'symbol': trade.symbol,
                'type': trade.trade_type,
                'lots': float(trade.lots),
                'profit': float(trade.profit),
                'close_time': trade.close_time.isoformat() if trade.close_time else None
            } for trade in trades]
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
