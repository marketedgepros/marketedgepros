"""
Admin routes for system management
"""
from flask import Blueprint, request, jsonify, g
from src import cache
import logging
from src.database import db
from src.models.user import User
from src.models.trading_program import Challenge
from src.models.payment import Payment
from src.models.trading_program import TradingProgram as Program
from src.utils.decorators import token_required, admin_required
from src.utils.validators import validate_required_fields, validate_email_format
from src.utils.error_messages import format_error_response
from src.utils.hierarchy_scoping import without_hierarchy_scope
from src.routes.kyc import _document_url, _kyc_users_for_actor
from datetime import datetime, timedelta
from sqlalchemy import func, and_, or_

admin_bp = Blueprint('admin', __name__)


@admin_bp.route("/dashboard/stats", methods=["GET"])
@token_required
@admin_required
def get_dashboard_stats(current_user):
    """Get admin dashboard statistics"""
    try:
        # User statistics
        total_users = User.query.count()
        active_users = User.query.filter_by(is_active=True).count()
        pending_kyc = User.query.filter_by(kyc_status='pending').count()
        
        # Revenue statistics
        total_revenue = db.session.query(func.sum(Payment.amount)).filter(
            Payment.status == 'completed'
        ).scalar() or 0
        
        # Monthly revenue (last 30 days)
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        monthly_revenue = db.session.query(func.sum(Payment.amount)).filter(
            and_(
                Payment.status == 'completed',
                Payment.created_at >= thirty_days_ago
            )
        ).scalar() or 0
        
        # Challenge statistics
        total_challenges = Challenge.query.count()
        active_challenges = Challenge.query.filter_by(status='active').count()
        completed_challenges = Challenge.query.filter_by(status='completed').count()
        failed_challenges = Challenge.query.filter_by(status='failed').count()
        funded_challenges = Challenge.query.filter_by(status='funded').count()
        
        # Recent users (last 5) - automatically filtered by hierarchy!
        recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
        
        # Recent payments (last 5)
        recent_payments = Payment.query.order_by(Payment.created_at.desc()).limit(5).all()
        
        return jsonify({
            'users': {
                'total': total_users,
                'active': active_users,
                'pending_kyc': pending_kyc,
                'suspended': User.query.filter_by(is_active=False).count()
            },
            'revenue': {
                'total': float(total_revenue),
                'monthly': float(monthly_revenue),
                'average_per_user': float(total_revenue / total_users) if total_users > 0 else 0
            },
            'challenges': {
                'total': total_challenges,
                'active': active_challenges,
                'completed': completed_challenges,
                'failed': failed_challenges,
                'funded': funded_challenges
            },
            'recent_users': [{
                'id': user.id,
                'name': f"{user.first_name} {user.last_name}",
                'email': user.email,
                'role': user.role,
                'status': 'active' if user.is_active else 'inactive',
                'created_at': user.created_at.isoformat()
            } for user in recent_users],
            'recent_payments': [{
                'id': payment.id,
                'user_id': payment.user_id,
                'amount': float(payment.amount),
                'type': payment.purpose,
                'status': payment.status,
                'created_at': payment.created_at.isoformat()
            } for payment in recent_payments]
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/users', methods=['GET'])
@token_required
@admin_required
def get_users(current_user):
    """Get all users with filtering and pagination"""
    try:
        # DEBUG: Log hierarchy scope info
        from flask import g
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f'=== GET USERS DEBUG ===')
        logger.info(f'Current user: {g.current_user.email if hasattr(g, "current_user") else "None"}')
        logger.info(f'Role: {getattr(g, "hierarchy_scope_role", "None")}')
        logger.info(f'Parent ID: {getattr(g, "hierarchy_scope_parent_id", "None")}')
        logger.info(f'Tree Path: {getattr(g, "hierarchy_scope_tree_path", "None")}')
        logger.info(f'Scoping enabled: {getattr(g, "hierarchy_scope_enabled", False)}')
        
        # Get query parameters
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        role = request.args.get('role')
        status = request.args.get('status')
        search = request.args.get('search')
        
        # Build query
        query = User.query
        
        # Apply filters
        if role:
            query = query.filter_by(role=role)
        if status:
            if status == 'active':
                query = query.filter_by(is_active=True)
            elif status == 'inactive':
                query = query.filter_by(is_active=False)
        if search:
            query = query.filter(
                or_(
                    User.email.ilike(f'%{search}%'),
                    User.first_name.ilike(f'%{search}%'),
                    User.last_name.ilike(f'%{search}%')
                )
            )
        
        # Get total count with hierarchy filtering applied
        # We need to count manually because paginate() doesn't apply our event-based filters to COUNT queries
        total_count = query.count()
        
        # Calculate pagination values
        total_pages = (total_count + per_page - 1) // per_page  # Ceiling division
        
        # Get the items for current page
        offset = (page - 1) * per_page
        users = query.order_by(User.created_at.desc()).limit(per_page).offset(offset).all()
        
        return jsonify({
            'users': [{
                'id': user.id,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'role': user.role,
                'is_active': user.is_active,
                'kyc_status': user.kyc_status,
                'phone': user.phone,
                'country_code': user.country_code,
                'parent_id': user.parent_id if hasattr(user, 'parent_id') else None,
                'level': user.level if hasattr(user, 'level') else 0,
                'referral_code': user.referral_code if hasattr(user, 'referral_code') else None,
                'created_at': user.created_at.isoformat() if user.created_at else None,
                'last_login_at': user.last_login_at.isoformat() if user.last_login_at else None
            } for user in users],
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total_count,
                'pages': total_pages
            }
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/users/hierarchy', methods=['GET'])
@token_required
@admin_required
def get_users_tree(current_user):
    """Get all users in hierarchical tree structure"""
    try:
        def build_user_tree(user):
            """Recursively build user tree with children"""
            user_data = {
                'id': user.id,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'role': user.role,
                'is_active': user.is_active,
                'is_verified': user.is_verified if hasattr(user, 'is_verified') else False,
                'kyc_status': user.kyc_status,
                'phone': user.phone,
                'country_code': user.country_code,
                'parent_id': user.parent_id,
                'level': user.level if hasattr(user, 'level') else 0,
                'tree_path': user.tree_path if hasattr(user, 'tree_path') else None,
                'referral_code': user.referral_code if hasattr(user, 'referral_code') else None,
                'created_at': user.created_at.isoformat() if user.created_at else None,
                'last_login_at': user.last_login_at.isoformat() if user.last_login_at else None,
                'children': []
            }
            
            # Get direct children
            children = User.query.filter_by(parent_id=user.id).order_by(User.created_at.asc()).all()
            
            # Recursively build children
            for child in children:
                user_data['children'].append(build_user_tree(child))
            
            return user_data
        
        # Get root users (users without parent or with parent_id=None)
        # For supermaster, this will be the current user
        # For others, it will be their top-level accessible users
        root_users = User.query.filter(
            or_(
                User.parent_id == None,
                User.parent_id == g.current_user.id
            )
        ).order_by(User.created_at.asc()).all()
        
        # If no root users found, use current user as root
        if not root_users:
            root_users = [g.current_user]
        
        # Build tree for each root user
        tree = [build_user_tree(user) for user in root_users]
        
        return jsonify({
            'users': tree,
            'total_users': len(tree)
        }), 200
        
    except Exception as e:
        import traceback
        print(f"Error in get_users_tree: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/users/<int:user_id>', methods=['GET'])
@token_required
@admin_required
def get_user(current_user, user_id):
    """Get specific user details"""
    try:
        user = User.query.get_or_404(user_id)
        
        return jsonify({
            'id': user.id,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'role': user.role,
            'is_active': user.is_active,
            'kyc_status': user.kyc_status,
            'phone': user.phone,
            'country_code': user.country_code,
            'created_at': user.created_at.isoformat(),
            'updated_at': user.updated_at.isoformat(),
            'last_login_at': user.last_login_at.isoformat() if user.last_login_at else None,
            'is_verified': user.is_verified,
            'two_factor_enabled': user.two_factor_enabled
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/users', methods=['POST'])
@token_required
@admin_required
def create_user(current_user):
    """Create a new user with comprehensive error handling"""
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['email', 'password', 'first_name', 'last_name', 'role']
        missing_fields = [field for field in required_fields if not data.get(field)]
        
        if missing_fields:
            return jsonify(format_error_response(
                'MISSING_REQUIRED_FIELDS',
                fields=', '.join(missing_fields)
            )), 400
        
        # Validate email format
        valid, result = validate_email_format(data['email'])
        if not valid:
            return jsonify(format_error_response(
                'INVALID_EMAIL_FORMAT',
                email=data['email']
            )), 400
        
        # Check if user already exists (without hierarchy filtering)
        with without_hierarchy_scope(db.session):
            if User.query.filter_by(email=data['email']).first():
                return jsonify(format_error_response(
                    'USER_ALREADY_EXISTS'
                )), 400
        
        # Validate role
        allowed_roles = ['supermaster', 'super_admin', 'master', 'admin', 'agent', 'trader']
        if data['role'] not in allowed_roles:
            return jsonify(format_error_response(
                'INVALID_ROLE',
                roles=', '.join(allowed_roles)
            )), 400
        
        # FIXED: Check role creation permissions using ROLE_HIERARCHY
        from src.constants.roles import can_user_create_role, Roles
        
        # Normalize roles (agent -> affiliate, etc.)
        target_role = Roles.normalize_role(data['role'])
        current_role = Roles.normalize_role(g.current_user.role)
        
        # Check if current user can create target role
        if not can_user_create_role(current_role, target_role, g.current_user.can_create_same_role):
            role_names = {
                'supermaster': 'SuperMaster',
                'master': 'Master',
                'affiliate': 'Affiliate',
                'trader': 'Trader'
            }
            return jsonify(format_error_response(
                'CANNOT_CREATE_ROLE',
                message=f"Your role ({role_names.get(current_role, current_role)}) cannot create {role_names.get(target_role, target_role)}"
            )), 403
        
        # Phone number validation and verification logic
        is_verified = False
        
        # Supermaster, super_admin, and admin can create users without phone
        # Note: agent is NOT included - agents cannot create users directly
        if g.current_user.role in ['supermaster', 'super_admin', 'admin']:
            is_verified = data.get('is_verified', True)  # Default to verified for admin-created users
        else:
            # Only non-admin roles require phone
            if data['role'] in ['admin', 'agent', 'trader']:
                if not data.get('phone'):
                    role_names = {
                        'admin': 'Master',
                        'agent': 'Agent',
                        'trader': 'Trader'
                    }
                    return jsonify(format_error_response(
                        'PHONE_REQUIRED_FOR_ROLE',
                        role=role_names.get(data['role'], data['role'])
                    )), 400
                
                # Force verification
                is_verified = True
        
        # Create user WITHOUT hierarchy scoping to avoid recursion
        with without_hierarchy_scope(db.session):
            user = User(
                email=data['email'],
                first_name=data['first_name'],
                last_name=data['last_name'],
                role=data['role'],
                is_active=data.get('is_active', True),
                phone=data.get('phone'),
                country_code=data.get('country_code'),
                is_verified=is_verified,
                parent_id=g.current_user.id,  # Set parent to current user
                level=g.current_user.level + 1 if hasattr(g.current_user, 'level') else 1
            )
            user.set_password(data['password'])
            
            db.session.add(user)
            db.session.commit()
            
            # Build tree_path after commit
            if g.current_user.tree_path:
                user.tree_path = f"{g.current_user.tree_path}.{user.id}"
            else:
                user.tree_path = str(user.id)
            db.session.commit()
        
        # Generate referral code AFTER commit (to avoid NOT NULL issues)
        if user.role in ['supermaster', 'super_admin', 'admin', 'agent']:
            user.generate_referral_code()
            db.session.commit()
        
        # Create Agent profile for agents
        if user.role == 'agent':
            from src.models.agent import Agent
            agent = Agent(
                user_id=user.id,
                agent_code=user.referral_code,  # Use the same code as referral_code
                commission_rate=10.0,  # Default 10% commission
                is_active=True
            )
            db.session.add(agent)
            db.session.commit()
        
        return jsonify({
            'message': 'User created successfully',
            'user': {
                'id': user.id,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'role': user.role,
                'is_active': user.is_active,
                'referral_code': user.referral_code if hasattr(user, 'referral_code') else None
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        # Log the actual error for debugging
        logging.error(f"Error creating user: {str(e)}", exc_info=True)
        return jsonify(format_error_response(
            'DATABASE_ERROR'
        )), 500


@admin_bp.route('/users/<int:user_id>', methods=['PUT'])
@token_required
@admin_required
def update_user(current_user, user_id):
    """Update user details"""
    try:
        user = User.query.get_or_404(user_id)
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
        if 'role' in data:
            user.role = data['role']
        if 'is_active' in data:
            user.is_active = data['is_active']
        if 'kyc_status' in data:
            user.kyc_status = data['kyc_status']
        
        user.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'message': 'User updated successfully',
            'user': {
                'id': user.id,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'role': user.role,
                'is_active': user.is_active,
                'kyc_status': user.kyc_status
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/users/<int:user_id>', methods=['DELETE'])
@token_required
@admin_required
def delete_user(current_user, user_id):
    """Delete (soft delete) a user"""
    try:
        user = User.query.get_or_404(user_id)
        
        # Prevent self-deletion
        if user.id == g.current_user.id:
            return jsonify({'error': 'Cannot delete yourself'}), 400
        
        # Soft delete
        user.is_active = False
        user.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({'message': 'User deleted successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/users/<int:user_id>/reset-password', methods=['POST'])
@token_required
@admin_required
def admin_reset_password(current_user, user_id):
    """Admin reset user password"""
    try:
        if not current_user.tenant_id:
            return jsonify({'error': 'Tenant membership required'}), 403
        user = _kyc_users_for_actor(current_user).filter(User.id == user_id).with_for_update().populate_existing().first()
        if user is None:
            return jsonify({'error': 'User not found'}), 404
        data = request.get_json(silent=True)
        if not isinstance(data, dict) or 'new_password' not in data:
            return jsonify({'error': 'New password is required'}), 400
        from src.services.auth_token_service import AuthTokenService
        try:
            AuthTokenService._password(data['new_password'])
        except ValueError:
            return jsonify({'error': 'Invalid password'}), 400
        user.set_password(data['new_password'])
        user.token_version = (user.token_version or 0) + 1
        from src.models.user import PasswordResetToken
        db.session.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user.id, PasswordResetToken.used.is_(False)
        ).update({'used': True}, synchronize_session=False)
        user.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({'message': 'Password reset successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'Password reset failed'}), 500


@admin_bp.route('/programs', methods=['GET'])
@token_required
@admin_required
def get_programs(current_user):
    """Get all trading programs"""
    try:
        programs = Program.query.all()
        
        return jsonify({
            'programs': [{
                'id': program.id,
                'name': program.name,
                'description': program.description,
                'account_size': float(program.account_size),
                'profit_target': float(program.profit_target),
                'max_daily_loss': float(program.max_daily_loss),
                'max_total_loss': float(program.max_total_loss),
                'price': float(program.price),
                'is_active': program.is_active,
                'created_at': program.created_at.isoformat()
            } for program in programs]
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/programs', methods=['POST'])
@token_required
@admin_required
def create_program(current_user):
    """Create a new trading program"""
    try:
        data = request.get_json()
        
        # Validate required fields
        required = ['name', 'account_size', 'profit_target', 'max_daily_loss', 'max_total_loss', 'price']
        valid, message = validate_required_fields(data, required)
        if not valid:
            return jsonify({'error': message}), 400
        
        program = Program(
            name=data['name'],
            description=data.get('description', ''),
            account_size=data['account_size'],
            profit_target=data['profit_target'],
            max_daily_loss=data['max_daily_loss'],
            max_total_loss=data['max_total_loss'],
            price=data['price'],
            is_active=data.get('is_active', True)
        )
        
        db.session.add(program)
        db.session.commit()
        
        return jsonify({
            'message': 'Program created successfully',
            'program': {
                'id': program.id,
                'name': program.name,
                'account_size': float(program.account_size)
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/programs/<int:program_id>', methods=['PUT'])
@token_required
@admin_required
def update_program(current_user, program_id):
    """Update a trading program"""
    try:
        program = Program.query.get_or_404(program_id)
        data = request.get_json()
        
        # Update fields
        if 'name' in data:
            program.name = data['name']
        if 'description' in data:
            program.description = data['description']
        if 'account_size' in data:
            program.account_size = data['account_size']
        if 'profit_target' in data:
            program.profit_target = data['profit_target']
        if 'max_daily_loss' in data:
            program.max_daily_loss = data['max_daily_loss']
        if 'max_total_loss' in data:
            program.max_total_loss = data['max_total_loss']
        if 'price' in data:
            program.price = data['price']
        if 'is_active' in data:
            program.is_active = data['is_active']
        
        program.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'message': 'Program updated successfully',
            'program': {
                'id': program.id,
                'name': program.name
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/programs/<int:program_id>', methods=['DELETE'])
@token_required
@admin_required
def delete_program(current_user, program_id):
    """Delete a trading program"""
    try:
        program = Program.query.get_or_404(program_id)
        
        # Check if program has active challenges
        active_challenges = Challenge.query.filter_by(
            program_id=program_id,
            status='active'
        ).count()
        
        if active_challenges > 0:
            return jsonify({'error': 'Cannot delete program with active challenges'}), 400
        
        db.session.delete(program)
        db.session.commit()
        
        return jsonify({'message': 'Program deleted successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/payments', methods=['GET'])
@token_required
@admin_required
def get_payments(current_user):
    """Get all payments with filtering"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        status = request.args.get('status')
        
        query = Payment.query
        
        if status:
            query = query.filter_by(status=status)
        
        pagination = query.order_by(Payment.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        return jsonify({
            'payments': [{
                'id': payment.id,
                'user_id': payment.user_id,
                'amount': float(payment.amount),
                'currency': payment.currency,
                'payment_type': payment.purpose,
                'payment_method': payment.payment_method,
                'status': payment.status,
                'transaction_id': payment.transaction_id,
                'created_at': payment.created_at.isoformat()
            } for payment in pagination.items],
            'pagination': {
                'page': pagination.page,
                'per_page': pagination.per_page,
                'total': pagination.total,
                'pages': pagination.pages
            }
        }), 200
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@admin_bp.route('/kyc/pending', methods=['GET'])
@token_required
@admin_required
def get_pending_kyc(current_user):
    """Get all pending KYC submissions"""
    try:
        if not current_user.tenant_id:
            return jsonify({'error': 'Tenant membership required'}), 403
        users = _kyc_users_for_actor(current_user).filter_by(kyc_status='pending').limit(100).all()
        
        return jsonify({
            'pending_kyc': [{
                'id': user.id,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'kyc_submitted_at': user.kyc_submitted_at.isoformat() if user.kyc_submitted_at else None,
                'kyc_id_url': _document_url(user, 'id_proof'),
                'kyc_address_url': _document_url(user, 'address_proof'),
                'kyc_selfie_url': _document_url(user, 'selfie'),
                'kyc_bank_url': _document_url(user, 'bank_statement')
            } for user in users]
        }), 200
        
    except Exception as e:
        return jsonify({'error': 'KYC operation failed'}), 500


@admin_bp.route('/kyc/<int:user_id>/approve', methods=['POST'])
@token_required
@admin_required
def approve_kyc(current_user, user_id):
    """Approve user KYC"""
    try:
        if not current_user.tenant_id:
            return jsonify({'error': 'Tenant membership required'}), 403
        user = _kyc_users_for_actor(current_user).filter_by(id=user_id).first()
        if user is None:
            return jsonify({'error': 'Submission not found'}), 404
        
        if user.kyc_status != 'pending':
            return jsonify({'error': 'KYC is not pending'}), 400
        
        user.kyc_status = 'approved'
        user.kyc_approved_at = datetime.utcnow()
        user.kyc_approved_by = g.current_user.id
        
        db.session.commit()
        
        return jsonify({'message': 'KYC approved successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'KYC operation failed'}), 500


@admin_bp.route('/kyc/<int:user_id>/reject', methods=['POST'])
@token_required
@admin_required
def reject_kyc(current_user, user_id):
    """Reject user KYC"""
    try:
        if not current_user.tenant_id:
            return jsonify({'error': 'Tenant membership required'}), 403
        user = _kyc_users_for_actor(current_user).filter_by(id=user_id).first()
        if user is None:
            return jsonify({'error': 'Submission not found'}), 404
        data = request.get_json()
        
        if user.kyc_status != 'pending':
            return jsonify({'error': 'KYC is not pending'}), 400
        
        if 'reason' not in data:
            return jsonify({'error': 'Rejection reason is required'}), 400
        
        user.kyc_status = 'rejected'
        user.kyc_rejected_at = datetime.utcnow()
        user.kyc_rejected_by = g.current_user.id
        user.kyc_rejection_reason = data['reason']
        user.kyc_admin_notes = data.get('notes', '')
        
        db.session.commit()
        
        return jsonify({'message': 'KYC rejected successfully'}), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': 'KYC operation failed'}), 500




@admin_bp.route('/users/<int:user_id>/full-details', methods=['GET'])
@token_required
@admin_required
def get_user_full_details(current_user, user_id):
    """Get complete user details including downline, challenges, commissions, and payments"""
    import traceback
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        logger.info(f'Fetching full details for user_id: {user_id}')
        user = User.query.get_or_404(user_id)
        logger.info(f'User found: {user.email}')
        
        # Basic user info
        user_data = {
            'id': user.id,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'role': user.role,
            'is_active': user.is_active,
            'kyc_status': user.kyc_status,
            'phone': user.phone,
            'country_code': user.country_code,
            'created_at': user.created_at.isoformat(),
            'updated_at': user.updated_at.isoformat(),
            'last_login_at': user.last_login_at.isoformat() if user.last_login_at else None,
            'is_verified': user.is_verified,
            'two_factor_enabled': user.two_factor_enabled
        }
        logger.info('User data collected')
        
        # Downline (for Master/Agent roles)
        downline_data = []
        try:
            if user.role in ['supermaster', 'admin', 'agent']:
                logger.info(f'Fetching downline for role: {user.role}')
                children = user.children
                for child in children:
                    downline_data.append({
                        'id': child.id,
                        'name': f"{child.first_name} {child.last_name}",
                        'email': child.email,
                        'role': child.role,
                        'is_active': child.is_active,
                        'created_at': child.created_at.isoformat() if child.created_at else None,
                        'children_count': User.query.filter_by(parent_id=child.id).count()
                    })
                logger.info(f'Downline collected: {len(downline_data)} children')
        except Exception as e:
            logger.error(f'Error fetching downline: {str(e)}')
            logger.error(traceback.format_exc())
        
        # Trading challenges
        challenges_data = []
        try:
            logger.info('Fetching challenges')
            challenges = user.challenges
            for challenge in challenges:
                challenges_data.append({
                    'id': challenge.id,
                    'program_name': challenge.program.name if challenge.program else 'N/A',
                    'account_size': float(challenge.account_size) if challenge.account_size else 0,
                    'status': challenge.status,
                    'current_balance': float(challenge.current_balance) if challenge.current_balance else 0,
                    'profit_loss': float(challenge.profit_loss) if challenge.profit_loss else 0,
                    'created_at': challenge.created_at.isoformat() if challenge.created_at else None
                })
            logger.info(f'Challenges collected: {len(challenges_data)}')
        except Exception as e:
            logger.error(f'Error fetching challenges: {str(e)}')
            logger.error(traceback.format_exc())
        
        # Payments
        payments_data = []
        try:
            logger.info('Fetching payments')
            payments = user.payments
            for payment in payments:
                payments_data.append({
                    'id': payment.id,
                    'amount': float(payment.amount),
                    'currency': payment.currency,
                    'status': payment.status,
                    'payment_type': payment.payment_type,
                    'created_at': payment.created_at.isoformat() if payment.created_at else None
                })
            logger.info(f'Payments collected: {len(payments_data)}')
        except Exception as e:
            logger.error(f'Error fetching payments: {str(e)}')
            logger.error(traceback.format_exc())
        
        # Commissions (if applicable)
        commissions_data = {
            'total_earned': 0,
            'this_month': 0,
            'commission_rate': float(user.commission_rate) if hasattr(user, 'commission_rate') and user.commission_rate else 0
        }
        
        logger.info('Returning full details response')
        return jsonify({
            'user': user_data,
            'downline': {
                'direct_referrals': downline_data,
                'total_count': len(downline_data)
            },
            'challenges': {
                'list': challenges_data,
                'total_count': len(challenges_data),
                'active_count': len([c for c in challenges_data if c['status'] == 'active'])
            },
            'payments': {
                'list': payments_data,
                'total_count': len(payments_data),
                'total_amount': sum([p['amount'] for p in payments_data if p['status'] == 'completed'])
            },
            'commissions': commissions_data
        }), 200
        
    except Exception as e:
        logger.error(f'CRITICAL ERROR in get_user_full_details: {str(e)}')
        logger.error(traceback.format_exc())
        return jsonify({'error': str(e), 'traceback': traceback.format_exc()}), 500
