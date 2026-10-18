"""
Chat routes for OpenAI GPT-5 integration
"""
from flask import Blueprint, request, jsonify
from src.services.openai_service import OpenAIService, get_openai_service
from src.utils.decorators import token_required
from src.models import Challenge
import logging

logger = logging.getLogger(__name__)

chat_bp = Blueprint('chat', __name__)


@chat_bp.route('/message', methods=['POST'])
@token_required
def send_message(current_user):
    """
    Send a message to GPT-5 and get response
    
    Request body:
    {
        "message": "User's message",
        "context": {  // Optional
            "page": "dashboard",
            "challenge_id": 123
        }
    }
    """
    data = request.get_json()
    
    if not data or 'message' not in data:
        return jsonify({'error': 'Message is required'}), 400
    
    message = data['message']
    context = data.get('context', {})
    
    try:
        # Get OpenAI service
        openai_service = get_openai_service()
        
        # Prepare user context
        user_context = {
            'role': current_user.role,
            'user_id': current_user.id
        }
        
        # Add challenges info if available
        challenges = Challenge.query.filter_by(user_id=current_user.id).all()
        user_context['challenges'] = [c.to_dict() for c in challenges]
        
        # Get response from GPT-5
        response = openai_service.get_trading_advice(message, user_context)
        
        if not response['success']:
            return jsonify({'error': response.get('error', 'Failed to get response')}), 500
        
        return jsonify({
            'message': response['message'],
            'usage': response.get('usage', {})
        }), 200
        
    except Exception as e:
        logger.error(f"Chat error: {str(e)}")
        return jsonify({'error': 'Failed to process message'}), 500


@chat_bp.route('/program-recommendation', methods=['POST'])
@token_required
def get_program_recommendation(current_user):
    """
    Get program recommendation based on user profile
    
    Request body:
    {
        "experience": "beginner|intermediate|advanced",
        "preferred_capital": 10000,
        "risk_tolerance": "low|moderate|high",
        "trading_style": "day trading|swing trading|scalping"
    }
    """
    data = request.get_json(silent=True) or {}
    
    try:
        openai_service = get_openai_service()
        
        user_profile = {
            'experience': data.get('experience', 'beginner'),
            'preferred_capital': data.get('preferred_capital', 10000),
            'risk_tolerance': data.get('risk_tolerance', 'moderate'),
            'trading_style': data.get('trading_style', 'day trading')
        }
        
        response = openai_service.get_program_recommendation(user_profile)
        
        if not response['success']:
            return jsonify({'error': response.get('error', 'Failed to get recommendation')}), 500
        
        return jsonify({
            'recommendation': response['message'],
            'usage': response.get('usage', {})
        }), 200
        
    except Exception as e:
        logger.error(f"Program recommendation error: {str(e)}")
        return jsonify({'error': 'Failed to get recommendation'}), 500


@chat_bp.route('/performance-analysis', methods=['POST'])
@token_required
def analyze_performance(current_user):
    """
    Analyze trading performance
    
    Request body:
    {
        "challenge_id": 123  // Optional, if not provided will analyze all user's trades
    }
    """
    data = request.get_json(silent=True) or {}
    requested_challenge = data.get('challenge_id')

    def not_found():
        # Do not distinguish a foreign challenge from a nonexistent one.
        return jsonify({'error': 'Resource not found'}), 404

    if requested_challenge is not None:
        if (
            isinstance(requested_challenge, bool)
            or not isinstance(requested_challenge, int)
            or requested_challenge <= 0
        ):
            return not_found()
        requested_challenge_ids = [requested_challenge]
    else:
        requested_challenge_ids = None
    
    try:
        from src.models import Trade

        # Establish owner -> challenge -> program -> tenant before reading
        # trades. Client-provided user, email, and tenant data are ignored.
        challenges = OpenAIService.get_authorized_challenges(
            current_user, requested_challenge_ids
        )
        if not challenges:
            return not_found()
        challenge_ids = [challenge.id for challenge in challenges]

        # The service repeats the authorization lookup immediately before the
        # provider call, preventing a route-bypass from reaching OpenAI.
        trades = Trade.query.filter(Trade.challenge_id.in_(challenge_ids)).all()
        
        if not trades:
            return not_found()
        
        # Calculate performance metrics
        total_trades = len(trades)
        winning_trades = [t for t in trades if t.profit > 0]
        losing_trades = [t for t in trades if t.profit < 0]
        
        win_rate = (len(winning_trades) / total_trades * 100) if total_trades > 0 else 0
        avg_win = sum(t.profit for t in winning_trades) / len(winning_trades) if winning_trades else 0
        avg_loss = sum(t.profit for t in losing_trades) / len(losing_trades) if losing_trades else 0
        
        total_profit = sum(t.profit for t in trades)
        total_loss = abs(sum(t.profit for t in losing_trades))
        profit_factor = (total_profit / total_loss) if total_loss > 0 else 0
        
        # Calculate max drawdown (simplified)
        balance = 0
        peak = 0
        max_dd = 0
        for trade in sorted(trades, key=lambda t: t.created_at):
            balance += trade.profit
            if balance > peak:
                peak = balance
            dd = ((peak - balance) / peak * 100) if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        
        performance_data = {
            'total_trades': total_trades,
            'win_rate': round(win_rate, 2),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'profit_factor': round(profit_factor, 2),
            'max_drawdown': round(max_dd, 2)
        }
        
        # Get AI analysis
        openai_service = get_openai_service()
        response = openai_service.analyze_trading_performance(
            performance_data,
            current_user=current_user,
            challenge_ids=challenge_ids
        )
        
        if not response['success']:
            if response.get('not_found'):
                return not_found()
            return jsonify({'error': response.get('error', 'Failed to analyze performance')}), 500
        
        return jsonify({
            'performance': performance_data,
            'analysis': response['message'],
            'usage': response.get('usage', {})
        }), 200
        
    except Exception as e:
        logger.error(f"Performance analysis error: {str(e)}")
        return jsonify({'error': 'Failed to analyze performance'}), 500


@chat_bp.route('/faq', methods=['POST'])
def answer_faq():
    """
    Get AI-generated answer for FAQ question
    No authentication required for public FAQ
    
    Request body:
    {
        "question": "User's question",
        "context": "Optional context"
    }
    """
    data = request.get_json()
    
    if not data or 'question' not in data:
        return jsonify({'error': 'Question is required'}), 400
    
    question = data['question']
    context = data.get('context')
    
    try:
        openai_service = get_openai_service()
        response = openai_service.generate_faq_answer(question, context)
        
        if not response['success']:
            return jsonify({'error': response.get('error', 'Failed to generate answer')}), 500
        
        return jsonify({
            'answer': response['message'],
            'usage': response.get('usage', {})
        }), 200
        
    except Exception as e:
        logger.error(f"FAQ answer error: {str(e)}")
        return jsonify({'error': 'Failed to generate answer'}), 500
