from src.services.mt5_challenge_service import mt5_challenge_service
from src.services.mt5_service import mt5_service
import asyncio
import logging

logger = logging.getLogger(__name__)
"""
Challenge routes for managing trading challenges
"""
from flask import Blueprint, request, jsonify, g
from src.database import db
from src.models.trading_program import Challenge
from src.models.trading_program import TradingProgram as Program
from src.models.trade import Trade
from src.models.payment import Payment
from src.utils.decorators import token_required, admin_required
from datetime import datetime
from sqlalchemy import desc, and_

challenges_bp = Blueprint('challenges', __name__)


@challenges_bp.route('/', methods=['POST'])
@token_required
def create_challenge(current_user):
    """Legacy direct challenge creation disabled pending canonical settlement."""
    # Legacy direct creation is disabled until a valid canonical order and
    # verified settlement event grants entitlement. Request fields cannot
    # create an unpaid challenge or substitute for settlement verification.
    return jsonify({
        'error': 'Order settlement is not configured',
        'code': 'ORDER_SETTLEMENT_NOT_CONFIGURED'
    }), 503

    try:
        user_id = g.current_user.id
        data = request.get_json()
        
        # Validate required fields
        if not data.get('program_id'):
            return jsonify({'error': 'Program ID is required'}), 400
        
        # Get program
        program = Program.query.get_or_404(data['program_id'])
        
        if not program.is_active:
            return jsonify({'error': 'Program is not active'}), 400
        
        # Check if user has already paid for this program
        # In a real implementation, verify payment first
        
        # Create challenge
        challenge = Challenge(
            user_id=user_id,
            program_id=program.id,
            status='pending',  # Will be 'active' after payment
            phase=1 if program.type == 'two_phase' else 0,
            initial_balance=program.account_size,
            current_balance=program.account_size,
            max_balance=program.account_size,
            profit_target=program.profit_target,
            max_daily_loss=program.max_daily_loss,
            max_total_drawdown=program.max_total_drawdown,
            min_trading_days=program.min_trading_days,
            trading_days=0
        )
        
        db.session.add(challenge)
        db.session.commit()
        
        return jsonify({
            'message': 'Challenge created successfully',
            'challenge': {
                'id': challenge.id,
                'program_id': challenge.program_id,
                'status': challenge.status,
                'phase': challenge.phase,
                'initial_balance': float(challenge.initial_balance),
                'created_at': challenge.created_at.isoformat()
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@challenges_bp.route('/<int:challenge_id>/start', methods=['POST'])
@token_required
def start_challenge(current_user, challenge_id):
    """Legacy challenge activation disabled pending canonical settlement."""
    # Legacy activation is disabled until a valid canonical order and verified
    # settlement event grants entitlement. This must happen before loading the
    # requested challenge so foreign identifiers do not disclose its existence.
    return jsonify({
        'error': 'Order settlement is not configured',
        'code': 'ORDER_SETTLEMENT_NOT_CONFIGURED'
    }), 503

    try:
        user_id = g.current_user.id
        
        challenge = Challenge.query.filter_by(
            id=challenge_id,
            user_id=user_id
        ).first_or_404()
        
        if challenge.status != 'pending':
            return jsonify({'error': 'Challenge cannot be started'}), 400
        
        # Update challenge status
        challenge.status = 'active'
        challenge.started_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'message': 'Challenge started successfully',
            'challenge': {
                'id': challenge.id,
                'status': challenge.status,
                'started_at': challenge.started_at.isoformat()
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@challenges_bp.route('/<int:challenge_id>/evaluate', methods=['POST'])
@token_required
@admin_required
def evaluate_challenge(challenge_id):
    """Evaluate a challenge and update status"""
    try:
        challenge = Challenge.query.get_or_404(challenge_id)
        
        if challenge.status != 'active':
            return jsonify({'error': 'Challenge is not active'}), 400
        
        # Get all trades for this challenge
        trades = Trade.query.filter_by(challenge_id=challenge_id).all()
        
        # Calculate metrics
        initial_balance = float(challenge.initial_balance)
        current_balance = float(challenge.current_balance)
        max_balance = float(challenge.max_balance or initial_balance)
        
        # Calculate profit
        profit = current_balance - initial_balance
        profit_percentage = (profit / initial_balance) * 100
        
        # Calculate drawdown
        drawdown = ((max_balance - current_balance) / max_balance) * 100
        
        # Check if profit target is met
        profit_target = float(challenge.profit_target)
        profit_target_met = profit >= profit_target
        
        # Check if minimum trading days are met
        min_days = challenge.min_trading_days or 5
        trading_days = challenge.trading_days or 0
        days_requirement_met = trading_days >= min_days
        
        # Check if drawdown limits are violated
        max_drawdown = float(challenge.max_total_drawdown)
        drawdown_violated = drawdown > max_drawdown
        
        # Determine challenge outcome
        if drawdown_violated:
            challenge.status = 'failed'
            challenge.failure_reason = f'Maximum drawdown exceeded: {drawdown:.2f}%'
            challenge.completed_at = datetime.utcnow()
        elif profit_target_met and days_requirement_met:
            # Check if this is a two-phase challenge
            program = Program.query.get(challenge.program_id)
            
            if program.type == 'two_phase' and challenge.phase == 1:
                # Move to phase 2
                challenge.phase = 2
                challenge.profit_target = program.profit_target  # Reset for phase 2
                challenge.trading_days = 0  # Reset trading days
                message = 'Phase 1 completed! Moving to Phase 2'
            else:
                # Challenge completed successfully
                challenge.status = 'completed'
                challenge.completed_at = datetime.utcnow()
                message = 'Challenge completed successfully! Awaiting funding'
        else:
            message = f'Challenge in progress. Profit: {profit_percentage:.2f}%, Days: {trading_days}/{min_days}'
        
        db.session.commit()
        
        return jsonify({
            'message': message,
            'challenge': {
                'id': challenge.id,
                'status': challenge.status,
                'phase': challenge.phase,
                'profit': profit,
                'profit_percentage': round(profit_percentage, 2),
                'drawdown': round(drawdown, 2),
                'trading_days': trading_days,
                'profit_target_met': profit_target_met,
                'days_requirement_met': days_requirement_met
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@challenges_bp.route('/<int:challenge_id>/fund', methods=['POST'])
@token_required
@admin_required
def fund_challenge(challenge_id):
    """Fund a completed challenge"""
    try:
        challenge = Challenge.query.get_or_404(challenge_id)
        
        if challenge.status != 'completed':
            return jsonify({'error': 'Challenge must be completed first'}), 400
        
        # Update challenge status to funded
        challenge.status = 'funded'
        challenge.funded_at = datetime.utcnow()
        
        # Reset balance for funded account
        program = Program.query.get(challenge.program_id)
        challenge.initial_balance = program.account_size
        challenge.current_balance = program.account_size
        challenge.max_balance = program.account_size
        
        db.session.commit()
        
        # TODO (Phase 4 - Email Notifications): Send funding notification email to trader
        # TODO (Phase 12 - MT4/MT5 Integration): Provision MT5 account automatically
        
        return jsonify({
            'message': 'Challenge funded successfully',
            'challenge': {
                'id': challenge.id,
                'status': challenge.status,
                'funded_at': challenge.funded_at.isoformat(),
                'initial_balance': float(challenge.initial_balance)
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@challenges_bp.route('/<int:challenge_id>/trades', methods=['POST'])
@token_required
def add_trade(current_user, challenge_id):
    """Add a trade to a challenge (for testing/simulation)"""
    try:
        user_id = g.current_user.id
        
        challenge = Challenge.query.filter_by(
            id=challenge_id,
            user_id=user_id
        ).first_or_404()
        
        if challenge.status not in ['active', 'funded']:
            return jsonify({'error': 'Challenge is not active'}), 400
        
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['symbol', 'type', 'lots', 'open_price', 'close_price']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'{field} is required'}), 400
        
        # Calculate profit and pips
        lots = float(data['lots'])
        open_price = float(data['open_price'])
        close_price = float(data['close_price'])
        
        # Simple profit calculation (needs to be more sophisticated for real trading)
        if data['type'] == 'buy':
            pips = (close_price - open_price) * 10000  # For forex
            profit = pips * lots * 10  # Simplified
        else:  # sell
            pips = (open_price - close_price) * 10000
            profit = pips * lots * 10
        
        # Create trade
        trade = Trade(
            challenge_id=challenge_id,
            symbol=data['symbol'],
            trade_type=data['type'],
            lots=lots,
            open_price=open_price,
            close_price=close_price,
            profit=profit,
            pips=pips,
            open_time=datetime.fromisoformat(data['open_time']) if 'open_time' in data else datetime.utcnow(),
            close_time=datetime.fromisoformat(data['close_time']) if 'close_time' in data else datetime.utcnow(),
            commission=data.get('commission', 0),
            swap=data.get('swap', 0)
        )
        
        db.session.add(trade)
        
        # Update challenge balance
        challenge.current_balance = float(challenge.current_balance) + profit
        
        # Update max balance if needed
        if challenge.current_balance > challenge.max_balance:
            challenge.max_balance = challenge.current_balance
        
        # Increment trading days (simplified - should check if it's a new day)
        if not challenge.trading_days:
            challenge.trading_days = 1
        
        db.session.commit()
        
        return jsonify({
            'message': 'Trade added successfully',
            'trade': {
                'id': trade.id,
                'symbol': trade.symbol,
                'type': trade.trade_type,
                'profit': float(trade.profit),
                'pips': float(trade.pips)
            },
            'challenge': {
                'current_balance': float(challenge.current_balance)
            }
        }), 201
        
    except ValueError as e:
        return jsonify({'error': f'Invalid data: {str(e)}'}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@challenges_bp.route('/admin/all', methods=['GET'])
@token_required
@admin_required
def get_all_challenges():
    """Get all challenges with MT5 data (admin only)"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        status = request.args.get('status')
        include_mt5 = request.args.get('include_mt5', 'true').lower() == 'true'
        
        query = db.session.query(Challenge, User, TradingProgram, MT5Account).join(
            User, Challenge.user_id == User.id
        ).join(
            TradingProgram, Challenge.program_id == TradingProgram.id
        ).outerjoin(
            MT5Account, Challenge.id == MT5Account.challenge_id
        )
        
        if status:
            query = query.filter(Challenge.status == status)
        
        query = query.order_by(desc(Challenge.created_at))
        
        pagination = query.paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        challenges_data = []
        
        for challenge, user, program, mt5_account in pagination.items:
            challenge_dict = {
                'id': challenge.id,
                'user_id': challenge.user_id,
                'user_name': f"{user.first_name} {user.last_name}",
                'user_email': user.email,
                'program_id': challenge.program_id,
                'program_name': program.name,
                'status': challenge.status,
                'phase': challenge.phase,
                'initial_balance': float(challenge.initial_balance),
                'current_balance': float(challenge.current_balance),
                'profit_target': float(challenge.profit_target),
                'trading_days': challenge.trading_days,
                'created_at': challenge.created_at.isoformat(),
                'started_at': challenge.started_at.isoformat() if challenge.started_at else None,
                'completed_at': challenge.completed_at.isoformat() if challenge.completed_at else None,
                'payment_status': challenge.payment_status,
                'max_drawdown': float(challenge.max_drawdown) if challenge.max_drawdown else 0
            }
            
            initial = float(challenge.initial_balance)
            current = float(challenge.current_balance)
            target = float(challenge.profit_target)
            profit = current - initial
            
            challenge_dict['progress'] = {
                'profit': profit,
                'profit_percentage': (profit / initial * 100) if initial > 0 else 0,
                'target_percentage': (target / initial * 100) if initial > 0 else 0,
                'progress_percentage': (profit / target * 100) if target > 0 else 0,
                'drawdown': float(challenge.max_drawdown) if challenge.max_drawdown else 0,
                'drawdown_percentage': (float(challenge.max_drawdown) / initial * 100) if (challenge.max_drawdown and initial > 0) else 0
            }
            
            if include_mt5 and mt5_account:
                try:
                    if mt5_account.status == 'active':
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        
                        try:
                            mt5_data = loop.run_until_complete(
                                mt5_service.get_account_info(mt5_account.mt5_login)
                            )
                            
                            if mt5_data:
                                mt5_account.balance = mt5_data.get('balance', mt5_account.balance)
                                mt5_account.equity = mt5_data.get('equity', mt5_account.equity)
                                mt5_account.margin = mt5_data.get('margin', mt5_account.margin)
                                mt5_account.free_margin = mt5_data.get('freeMargin', mt5_account.free_margin)
                                mt5_account.margin_level = mt5_data.get('marginLevel', mt5_account.margin_level)
                                
                                challenge.current_balance = mt5_data.get('balance', challenge.current_balance)
                                
                                current = float(mt5_data.get('balance', current))
                                profit = current - initial
                                challenge_dict['current_balance'] = current
                                challenge_dict['progress'] = {
                                    'profit': profit,
                                    'profit_percentage': (profit / initial * 100) if initial > 0 else 0,
                                    'target_percentage': (target / initial * 100) if initial > 0 else 0,
                                    'progress_percentage': (profit / target * 100) if target > 0 else 0,
                                    'drawdown': float(challenge.max_drawdown) if challenge.max_drawdown else 0,
                                    'drawdown_percentage': (float(challenge.max_drawdown) / initial * 100) if (challenge.max_drawdown and initial > 0) else 0
                                }
                        finally:
                            loop.close()
                    
                    challenge_dict['mt5_account'] = {
                        'login': mt5_account.mt5_login,
                        'balance': float(mt5_account.balance) if mt5_account.balance else 0,
                        'equity': float(mt5_account.equity) if mt5_account.equity else 0,
                        'margin': float(mt5_account.margin) if mt5_account.margin else 0,
                        'free_margin': float(mt5_account.free_margin) if mt5_account.free_margin else 0,
                        'margin_level': float(mt5_account.margin_level) if mt5_account.margin_level else None,
                        'status': mt5_account.status,
                        'server': mt5_account.mt5_server
                    }
                except Exception as e:
                    logger.warning(f"Failed to get MT5 data for challenge {challenge.id}: {e}")
                    challenge_dict['mt5_account'] = {
                        'login': mt5_account.mt5_login,
                        'balance': float(mt5_account.balance) if mt5_account.balance else 0,
                        'equity': float(mt5_account.equity) if mt5_account.equity else 0,
                        'status': mt5_account.status,
                        'error': 'Failed to fetch live data'
                    }
            else:
                challenge_dict['mt5_account'] = None
            
            challenges_data.append(challenge_dict)
        
        try:
            db.session.commit()
        except:
            db.session.rollback()
        
        return jsonify({
            'challenges': challenges_data,
            'pagination': {
                'page': pagination.page,
                'per_page': pagination.per_page,
                'total': pagination.total,
                'pages': pagination.pages
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Failed to get all challenges: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@challenges_bp.route('/admin/<int:challenge_id>', methods=['DELETE'])
@token_required
@admin_required
def delete_challenge(challenge_id):
    """Delete a challenge (admin only)"""
    try:
        challenge = Challenge.query.get_or_404(challenge_id)
        
        # Don't allow deleting funded challenges
        if challenge.status == 'funded':
            return jsonify({'error': 'Cannot delete funded challenges'}), 400
        
        # Delete associated trades first
        Trade.query.filter_by(challenge_id=challenge_id).delete()
        
        # Delete challenge
        db.session.delete(challenge)
        db.session.commit()
        
        return jsonify({'message': 'Challenge deleted successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500



# ===== MT5 Integration Endpoints =====

@challenges_bp.route("/<int:challenge_id>/mt5-credentials", methods=["GET"])
@token_required
def get_mt5_credentials(current_user, challenge_id):
    """Get MT5 login credentials for a challenge"""
    try:
        challenge = Challenge.query.get_or_404(challenge_id)
        
        if challenge.user_id != g.current_user.id:
            return jsonify({"error": "Access denied"}), 403
        
        if challenge.payment_status != "paid":
            return jsonify({"error": "Challenge not paid yet"}), 400
        
        credentials = mt5_challenge_service.get_mt5_credentials(
            challenge_id, g.current_user.id
        )
        
        if not credentials:
            return jsonify({"error": "MT5 account not found"}), 404
        
        return jsonify({
            "message": "MT5 credentials retrieved",
            "credentials": credentials
        }), 200
        
    except Exception as e:
        logger.error(f"Failed to get MT5 credentials: {e}")
        return jsonify({"error": "Failed to retrieve credentials"}), 500


@challenges_bp.route("/<int:challenge_id>/create-mt5-account", methods=["POST"])
@token_required
def create_mt5_account_manual(current_user, challenge_id):
    """Manually create MT5 account for a paid challenge"""
    try:
        challenge = Challenge.query.get_or_404(challenge_id)
        
        if challenge.user_id != g.current_user.id:
            return jsonify({"error": "Access denied"}), 403
        
        if challenge.payment_status != "paid":
            return jsonify({"error": "Challenge must be paid first"}), 400
        
        from src.models.mt5_models import MT5Account
        existing = MT5Account.query.filter_by(challenge_id=challenge_id).first()
        if existing:
            return jsonify({"error": "MT5 account already exists"}), 400
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        mt5_data = loop.run_until_complete(
            mt5_challenge_service.create_mt5_account_for_challenge(challenge_id)
        )
        loop.close()
        
        if not mt5_data:
            return jsonify({"error": "Failed to create MT5 account"}), 500
        
        return jsonify({
            "message": "MT5 account created successfully",
            "credentials": mt5_data
        }), 201
        
    except Exception as e:
        logger.error(f"Failed to create MT5 account: {e}")
        return jsonify({"error": "Failed to create MT5 account"}), 500


@challenges_bp.route("/<int:challenge_id>/progress", methods=["GET"])
@token_required
def get_challenge_progress(current_user, challenge_id):
    """Get challenge progress with live MT5 data"""
    try:
        challenge = Challenge.query.get_or_404(challenge_id)
        
        if challenge.user_id != g.current_user.id:
            return jsonify({"error": "Access denied"}), 403
        
        from src.models.mt5_models import MT5Account
        mt5_account = MT5Account.query.filter_by(challenge_id=challenge_id).first()
        
        if mt5_account and mt5_account.status == "active":
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(
                mt5_challenge_service.update_challenge_from_mt5(challenge_id)
            )
            loop.close()
            db.session.refresh(challenge)
        
        program = TradingProgram.query.get(challenge.program_id)
        
        initial_balance = challenge.initial_balance or program.account_size
        current_balance = challenge.current_balance or initial_balance
        profit_target = program.profit_target
        max_drawdown_limit = program.max_total_drawdown
        
        profit_loss = current_balance - initial_balance
        profit_progress = (profit_loss / profit_target * 100) if profit_target else 0
        drawdown_used = (challenge.max_drawdown / max_drawdown_limit * 100) if max_drawdown_limit else 0
        
        return jsonify({
            "challenge": challenge.to_dict(),
            "progress": {
                "initial_balance": initial_balance,
                "current_balance": current_balance,
                "profit_loss": profit_loss,
                "profit_target": profit_target,
                "profit_progress": round(profit_progress, 2),
                "max_drawdown": challenge.max_drawdown or 0,
                "max_drawdown_limit": max_drawdown_limit,
                "drawdown_used": round(drawdown_used, 2),
                "trading_days": challenge.trading_days or 0,
                "min_trading_days": program.min_trading_days
            },
            "mt5_account": mt5_account.to_dict() if mt5_account else None
        }), 200
        
    except Exception as e:
        logger.error(f"Failed to get challenge progress: {e}")
        return jsonify({"error": "Failed to retrieve progress"}), 500
