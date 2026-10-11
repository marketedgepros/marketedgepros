"""
User routes for profile and account management
"""
from flask import Blueprint, request, jsonify, g, current_app
from src.database import db
from src.models.user import User
from src.models.trading_program import Challenge
from src.models.payment import Payment
from src.utils.decorators import token_required
from datetime import datetime
from sqlalchemy import func, desc

users_bp = Blueprint('users', __name__)


@users_bp.route('/dashboard', methods=['GET'])
@token_required
def get_user_dashboard():
    """Get user dashboard statistics - works for all user types"""
    try:
        user = g.current_user
        
        # Get challenges count
        total_challenges = Challenge.query.filter_by(user_id=user.id).count()
        active_challenges = Challenge.query.filter_by(user_id=user.id, status='active').count()
        passed_challenges = Challenge.query.filter_by(user_id=user.id, status='passed').count()
        failed_challenges = Challenge.query.filter_by(user_id=user.id, status='failed').count()
        funded_challenges = Challenge.query.filter_by(user_id=user.id, status='funded').count()
        
        # Get total profit from all challenges
        challenges = Challenge.query.filter_by(user_id=user.id).all()
        total_profit = 0
        for challenge in challenges:
            if challenge.current_balance and challenge.initial_balance:
                profit = float(challenge.current_balance) - float(challenge.initial_balance)
                if profit > 0:
                    total_profit += profit
        
        # Get payments
        total_spent = db.session.query(func.sum(Payment.amount)).filter(
            Payment.user_id == user.id,
            Payment.status == 'completed',
            Payment.purpose == 'challenge_purchase'
        ).scalar() or 0
        
        # Get recent challenges
        recent_challenges = Challenge.query.filter_by(
            user_id=user.id
        ).order_by(desc(Challenge.created_at)).limit(5).all()
        
        # Calculate success rate
        completed_challenges = passed_challenges + failed_challenges
        success_rate = (passed_challenges / completed_challenges * 100) if completed_challenges > 0 else 0
        
        return jsonify({
            'user': {
                'id': user.id,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'role': user.role,
                'kyc_status': user.kyc_status,
                'is_verified': user.is_verified
            },
            'statistics': {
                'total_challenges': total_challenges,
                'active_challenges': active_challenges,
                'passed_challenges': passed_challenges,
                'failed_challenges': failed_challenges,
                'funded_challenges': funded_challenges,
                'success_rate': round(success_rate, 2),
                'total_profit': round(total_profit, 2),
                'total_spent': float(total_spent)
            },
            'recent_challenges': [{
                'id': challenge.id,
                'program_name': challenge.program.name if challenge.program else 'Unknown',
                'status': challenge.status,
                'phase': challenge.phase,
                'current_balance': float(challenge.current_balance) if challenge.current_balance else 0,
                'initial_balance': float(challenge.initial_balance) if challenge.initial_balance else 0,
                'profit': float(challenge.current_balance or 0) - float(challenge.initial_balance or 0),
                'created_at': challenge.created_at.isoformat() if challenge.created_at else None
            } for challenge in recent_challenges]
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@users_bp.route('/profile', methods=['GET'])
@token_required
def get_profile():
    """Get user profile"""
    try:
        user = g.current_user
        return jsonify(user.to_dict()), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@users_bp.route('/profile', methods=['PUT'])
@token_required
def update_profile():
    """Update user profile"""
    try:
        user = g.current_user
        data = request.get_json()
        
        # Update allowed fields
        if 'first_name' in data:
            user.first_name = data['first_name']
        if 'last_name' in data:
            user.last_name = data['last_name']
        if 'phone' in data:
            user.phone = data['phone']
        if 'country_code' in data:
            user.country_code = data['country_code']
        if 'date_of_birth' in data:
            user.date_of_birth = datetime.fromisoformat(data['date_of_birth'])
        
        db.session.commit()
        
        return jsonify({
            'message': 'Profile updated successfully',
            'user': user.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@users_bp.route('/hierarchy', methods=['GET'])
@token_required
def get_users_hierarchy():
    """Get users in hierarchical tree structure based on parent_id"""
    if not current_app.config.get('EXPANDED_HIERARCHY_ENABLED', False):
        return jsonify({'error': 'Expanded hierarchy is disabled in launch mode', 'code': 'EXPANDED_HIERARCHY_DISABLED'}), 409
    try:
        # Get all users
        users = User.query.all()
        
        # Build user dict for quick lookup
        user_dict = {user.id: {
            'id': user.id,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'role': user.role,
            'parent_id': user.parent_id,
            'is_verified': user.is_verified,
            'kyc_status': user.kyc_status,
            'created_at': user.created_at.isoformat() if user.created_at else None,
            'children': []
        } for user in users}
        
        # Build tree structure
        root_users = []
        for user_id, user_data in user_dict.items():
            parent_id = user_data['parent_id']
            if parent_id and parent_id in user_dict:
                # Add to parent's children
                user_dict[parent_id]['children'].append(user_data)
            else:
                # Root user (no parent)
                root_users.append(user_data)
        
        # Sort by role hierarchy (supermaster > master > agent > trader)
        role_order = {'supermaster': 0, 'master': 1, 'agent': 2, 'trader': 3}
        
        def sort_users(users_list):
            return sorted(users_list, key=lambda u: (
                role_order.get(u['role'], 999),
                u['email']
            ))
        
        # Recursively sort all levels
        def sort_tree(node):
            if node.get('children'):
                node['children'] = sort_users(node['children'])
                for child in node['children']:
                    sort_tree(child)
        
        root_users = sort_users(root_users)
        for user in root_users:
            sort_tree(user)
        
        return jsonify({
            'users': root_users,
            'total_count': len(users)
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
