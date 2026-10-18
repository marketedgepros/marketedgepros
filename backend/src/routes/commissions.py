"""
Commission routes
API endpoints for commission management
"""
from flask import Blueprint, request, jsonify, g
from src.utils.decorators import token_required, admin_required
from src.services.commission_service import CommissionService
from src.services.affiliate_financial_boundary import affiliate_mutation_unavailable_response
from src.models import Commission, Agent, User
from src.database import db

commissions_bp = Blueprint('commissions', __name__, url_prefix='/api/v1/commissions')


@commissions_bp.route('/', methods=['GET'])
@token_required
def get_commissions():
    """Get commissions for current user (if agent) or all (if admin)"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    status = request.args.get('status', None)
    
    # Check if user is an agent
    agent = Agent.query.filter_by(user_id=g.current_user.id).first()
    
    if agent:
        # Agent can only see their own commissions
        pagination = CommissionService.get_agent_commissions(
            agent_id=agent.id,
            status=status,
            page=page,
            per_page=per_page
        )
    elif g.current_user.role in ['supermaster', 'master', 'admin']:
        # Admin can see all commissions
        query = Commission.query
        
        if status:
            query = query.filter_by(status=status)
        
        # Filter by agent_id if provided
        agent_id = request.args.get('agent_id', type=int)
        if agent_id:
            query = query.filter_by(agent_id=agent_id)
        
        pagination = query.order_by(Commission.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
    else:
        return jsonify({'error': 'Unauthorized'}), 403
    
    # Get detailed commission data
    commissions_data = []
    for commission in pagination.items:
        commission_dict = commission.to_dict()
        
        # Add agent info
        agent_obj = Agent.query.get(commission.agent_id)
        if agent_obj:
            agent_user = User.query.get(agent_obj.user_id)
            commission_dict['agent'] = {
                'id': agent_obj.id,
                'agent_code': agent_obj.agent_code,
                'name': f"{agent_user.first_name} {agent_user.last_name}" if agent_user else 'Unknown',
                'email': agent_user.email if agent_user else None
            }
        
        # Add challenge info
        if commission.challenge:
            commission_dict['challenge'] = {
                'id': commission.challenge.id,
                'program_id': commission.challenge.program_id,
                'status': commission.challenge.status
            }
        
        # Add referral info
        if commission.referral:
            referred_user = User.query.get(commission.referral.referred_user_id)
            commission_dict['referral'] = {
                'id': commission.referral.id,
                'referred_user': {
                    'id': referred_user.id if referred_user else None,
                    'name': f"{referred_user.first_name} {referred_user.last_name}" if referred_user else 'Unknown',
                    'email': referred_user.email if referred_user else None
                }
            }
        
        commissions_data.append(commission_dict)
    
    return jsonify({
        'commissions': commissions_data,
        'pagination': {
            'page': pagination.page,
            'per_page': pagination.per_page,
            'total': pagination.total,
            'pages': pagination.pages,
            'has_next': pagination.has_next,
            'has_prev': pagination.has_prev
        }
    }), 200


@commissions_bp.route('/stats', methods=['GET'])
@token_required
def get_commission_stats():
    """Get commission statistics for current user (if agent) or specified agent (if admin)"""
    # Check if user is an agent
    agent = Agent.query.filter_by(user_id=g.current_user.id).first()
    
    if agent:
        # Agent can only see their own stats
        stats = CommissionService.get_agent_commission_stats(agent.id)
    elif g.current_user.role in ['supermaster', 'master', 'admin']:
        # Admin can see any agent's stats
        agent_id = request.args.get('agent_id', type=int)
        if not agent_id:
            return jsonify({'error': 'agent_id is required for admin'}), 400
        
        stats = CommissionService.get_agent_commission_stats(agent_id)
    else:
        return jsonify({'error': 'Unauthorized'}), 403
    
    if not stats:
        return jsonify({'error': 'Agent not found'}), 404
    
    return jsonify(stats), 200


@commissions_bp.route('/<int:commission_id>', methods=['GET'])
@token_required
def get_commission(commission_id):
    """Get a specific commission"""
    commission = Commission.query.get_or_404(commission_id)
    
    # Check permissions
    agent = Agent.query.filter_by(user_id=g.current_user.id).first()
    
    if agent:
        # Agent can only see their own commissions
        if commission.agent_id != agent.id:
            return jsonify({'error': 'Unauthorized'}), 403
    elif g.current_user.role not in ['supermaster', 'master', 'admin']:
        return jsonify({'error': 'Unauthorized'}), 403
    
    commission_dict = commission.to_dict()
    
    # Add related data
    agent_obj = Agent.query.get(commission.agent_id)
    if agent_obj:
        agent_user = User.query.get(agent_obj.user_id)
        commission_dict['agent'] = {
            'id': agent_obj.id,
            'agent_code': agent_obj.agent_code,
            'name': f"{agent_user.first_name} {agent_user.last_name}" if agent_user else 'Unknown',
            'email': agent_user.email if agent_user else None
        }
    
    if commission.challenge:
        commission_dict['challenge'] = commission.challenge.to_dict()
    
    if commission.referral:
        referred_user = User.query.get(commission.referral.referred_user_id)
        commission_dict['referral'] = {
            'id': commission.referral.id,
            'referred_user': {
                'id': referred_user.id if referred_user else None,
                'name': f"{referred_user.first_name} {referred_user.last_name}" if referred_user else 'Unknown',
                'email': referred_user.email if referred_user else None
            }
        }
    
    return jsonify(commission_dict), 200


@commissions_bp.route('/<int:commission_id>/approve', methods=['POST'])
@token_required
@admin_required
def approve_commission(commission_id):
    """Legacy affiliate commission approval is unavailable after admin auth."""
    return affiliate_mutation_unavailable_response()


@commissions_bp.route('/<int:commission_id>/pay', methods=['POST'])
@token_required
@admin_required
def mark_commission_paid(commission_id):
    """Legacy affiliate commission payment is unavailable after admin auth."""
    return affiliate_mutation_unavailable_response()


@commissions_bp.route('/summary', methods=['GET'])
@admin_required
def get_commissions_summary():
    """Get overall commission summary (Admin only)"""
    from sqlalchemy import func
    from decimal import Decimal
    
    # Get total commissions by status
    pending = db.session.query(
        func.count(Commission.id).label('count'),
        func.sum(Commission.commission_amount).label('amount')
    ).filter(Commission.status == 'pending').first()
    
    approved = db.session.query(
        func.count(Commission.id).label('count'),
        func.sum(Commission.commission_amount).label('amount')
    ).filter(Commission.status == 'approved').first()
    
    paid = db.session.query(
        func.count(Commission.id).label('count'),
        func.sum(Commission.commission_amount).label('amount')
    ).filter(Commission.status == 'paid').first()
    
    # Get total sales
    total_sales = db.session.query(
        func.sum(Commission.sale_amount)
    ).scalar() or Decimal('0')
    
    # Get active agents count
    active_agents = Agent.query.filter_by(is_active=True).count()
    
    # Get agents with pending balance
    agents_with_balance = Agent.query.filter(
        Agent.pending_balance > 0
    ).count()
    
    return jsonify({
        'pending': {
            'count': pending.count or 0,
            'amount': float(pending.amount or 0)
        },
        'approved': {
            'count': approved.count or 0,
            'amount': float(approved.amount or 0)
        },
        'paid': {
            'count': paid.count or 0,
            'amount': float(paid.amount or 0)
        },
        'total_sales': float(total_sales),
        'active_agents': active_agents,
        'agents_with_balance': agents_with_balance
    }), 200
