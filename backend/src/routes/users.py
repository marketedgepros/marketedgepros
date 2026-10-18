"""
User routes for profile and account management
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, request, jsonify, g, current_app
from sqlalchemy import case, desc, func
from sqlalchemy.orm import joinedload

from src.database import db
from src.models.user import User
from src.models.trading_program import Challenge, TradingProgram
from src.utils.decorators import token_required

users_bp = Blueprint('users', __name__)


@users_bp.route('/dashboard', methods=['GET'])
@token_required
def get_user_dashboard():
    """Return a bounded view of the caller's locally recorded legacy rows."""
    user = g.current_user
    tenant_id = user.tenant_id
    # Do not infer a brand from a challenge or its program.  Refuse before any
    # dashboard-resource SQL when the authenticated principal lacks a tenant.
    if isinstance(tenant_id, bool) or not isinstance(tenant_id, int) or tenant_id < 1:
        return jsonify({
            'error': 'User must belong to a tenant',
            'code': 'TENANT_CONTEXT_REQUIRED',
        }), 403

    owner_context = {'user_id': user.id, 'tenant_id': tenant_id}
    try:
        def decimal_string(value):
            """Preserve finite legacy Numeric values without float conversion."""
            if value is None or isinstance(value, bool):
                return None
            try:
                decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
            except (InvalidOperation, TypeError, ValueError):
                return None
            return format(decimal_value, 'f') if decimal_value.is_finite() else None

        # ``Challenge`` has no tenant_id.  Both read queries explicitly join its
        # program and constrain the program tenant as well as the authenticated
        # owner, rather than trusting a challenge row's implied tenancy.
        with db.session.no_autoflush:
            status_totals = (
                db.session.query(
                    func.count(Challenge.id).label('total'),
                    func.sum(case((Challenge.status == 'pending', 1), else_=0)).label('pending'),
                    func.sum(case((Challenge.status == 'active', 1), else_=0)).label('active'),
                    func.sum(case((Challenge.status == 'passed', 1), else_=0)).label('passed'),
                    func.sum(case((Challenge.status == 'failed', 1), else_=0)).label('failed'),
                    func.sum(case((Challenge.status == 'funded', 1), else_=0)).label('funded'),
                )
                .select_from(Challenge)
                .join(TradingProgram, Challenge.program_id == TradingProgram.id)
                .filter(
                    Challenge.user_id == user.id,
                    TradingProgram.tenant_id == tenant_id,
                )
                .one()
            )
            status_counts = {
                name: int(getattr(status_totals, name) or 0)
                for name in ('total', 'pending', 'active', 'passed', 'failed', 'funded')
            }
            recorded_outcomes = status_counts['passed'] + status_counts['failed']
            success_rate = (
                round((status_counts['passed'] / recorded_outcomes) * 100, 2)
                if recorded_outcomes else None
            )
            recent_challenges = (
                Challenge.query.execution_options(autoflush=False)
                .join(TradingProgram, Challenge.program_id == TradingProgram.id)
                .options(joinedload(Challenge.program))
                .filter(
                    Challenge.user_id == user.id,
                    TradingProgram.tenant_id == tenant_id,
                )
                .order_by(desc(Challenge.created_at), desc(Challenge.id))
                .limit(5)
                .all()
            )

        recent_rows = []
        for challenge in recent_challenges:
            initial_balance = decimal_string(challenge.initial_balance)
            current_balance = decimal_string(challenge.current_balance)
            profit = None
            if initial_balance is not None and current_balance is not None:
                # This is arithmetic over recorded legacy balances only, never
                # a provider-verified trading result.
                profit = decimal_string(Decimal(current_balance) - Decimal(initial_balance))
            recent_rows.append({
                'id': challenge.id,
                'user_id': user.id,
                'program_name': challenge.program.name if challenge.program else None,
                'status': challenge.status,
                'status_data_status': 'recorded_not_verified',
                'phase': challenge.current_phase,
                'total_phases': challenge.total_phases,
                'initial_balance': initial_balance,
                'current_balance': current_balance,
                'balance_data_quality': 'legacy_unverified',
                'profit': profit,
                'profit_data_status': (
                    'recorded_not_verified'
                    if profit is not None else 'unavailable_missing_recorded_balance'
                ),
                # Challenge records have no source currency column.
                'currency': None,
                # There is no approved dashboard target/provenance contract.
                'progress': None,
                'progress_data_status': 'unavailable_no_approved_rule_source',
                'created_at': challenge.created_at.isoformat() if challenge.created_at else None,
            })

        return jsonify({
            'owner_context': owner_context,
            'user': {
                'id': user.id,
                'tenant_id': tenant_id,
                'first_name': user.first_name,
                'role': user.role,
            },
            'statistics': {
                'status_counts': status_counts,
                'status_counts_data_status': 'recorded_legacy_statuses',
                'success_rate': success_rate,
                'success_rate_data_status': (
                    'recorded_legacy_statuses'
                    if success_rate is not None else 'unavailable_no_recorded_outcomes'
                ),
                # Payment and trading rows have no verified provenance contract.
                'total_profit': None,
                'total_profit_data_status': 'unavailable_no_verified_provenance',
                'total_spent': None,
                'total_spent_data_status': 'unavailable_no_verified_provenance',
                'data_quality': 'legacy_unverified',
            },
            'recent_challenges': recent_rows,
            'data_quality': {
                'challenge_statuses': 'legacy_unverified',
                'trading_balances': 'legacy_unverified',
                'financial_totals': 'unavailable_no_verified_provenance',
                'provider_verification': 'not_available',
            },
        }), 200

    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        current_app.logger.error('User dashboard read failed')
        return jsonify({
            'error': 'Dashboard is temporarily unavailable',
            'code': 'USER_DASHBOARD_UNAVAILABLE',
        }), 503


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
