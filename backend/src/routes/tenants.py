"""
Tenant management routes
"""
from flask import Blueprint, request, jsonify, g, current_app
from src.database import db
from src.models.tenant import Tenant
from src.utils.decorators import token_required, role_required
from src.middleware.tenant_middleware import get_current_tenant, get_current_tenant_id
import logging

logger = logging.getLogger(__name__)

tenants_bp = Blueprint('tenants', __name__)


@tenants_bp.before_request
def launch_brand_management_gate():
    if not current_app.config.get('EXPANDED_HIERARCHY_ENABLED', False) and request.endpoint != 'tenants.get_current_tenant_info':
        return jsonify({'error': 'White label management is disabled in single-brand launch mode', 'code': 'WHITE_LABEL_DISABLED'}), 409


@tenants_bp.route('/current', methods=['GET'])
def get_current_tenant_info():
    """Get current tenant information (public endpoint)"""
    if not current_app.config.get('EXPANDED_HIERARCHY_ENABLED', False):
        from src.middleware.tenant_middleware import get_tenant_from_request
        tenant = get_tenant_from_request()
        if tenant is None:
            return jsonify({'error': 'Single-brand ownership is not configured', 'code': 'BRAND_NOT_CONFIGURED'}), 503
    else:
        tenant = get_current_tenant()
    
    if not tenant:
        return jsonify({'error': 'Tenant not found'}), 404
    
    return jsonify({
        'tenant': tenant.to_dict()
    }), 200


@tenants_bp.route('/', methods=['GET'])
@token_required
@role_required('supermaster')
def list_tenants():
    """List all tenants (supermaster only)"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    status = request.args.get('status')
    
    query = Tenant.query
    
    if status:
        query = query.filter_by(status=status)
    
    pagination = query.order_by(Tenant.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    return jsonify({
        'tenants': [t.to_dict() for t in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    }), 200


@tenants_bp.route('/<int:tenant_id>', methods=['GET'])
@token_required
@role_required('supermaster')
def get_tenant(tenant_id):
    """Get specific tenant (supermaster only)"""
    tenant = Tenant.query.get_or_404(tenant_id)
    
    return jsonify({
        'tenant': tenant.to_dict()
    }), 200


@tenants_bp.route('/', methods=['POST'])
@token_required
@role_required('supermaster')
def create_tenant():
    """Create new tenant (supermaster only)"""
    data = request.get_json()
    
    required_fields = ['name', 'subdomain']
    missing = [f for f in required_fields if f not in data]
    if missing:
        return jsonify({'error': f'Missing fields: {", ".join(missing)}'}), 400
    
    # Check if subdomain already exists
    existing = Tenant.query.filter_by(subdomain=data['subdomain']).first()
    if existing:
        return jsonify({'error': 'Subdomain already exists'}), 400
    
    # Check custom domain if provided
    if data.get('custom_domain'):
        existing = Tenant.query.filter_by(custom_domain=data['custom_domain']).first()
        if existing:
            return jsonify({'error': 'Custom domain already exists'}), 400
    
    try:
        tenant = Tenant(
            name=data['name'],
            subdomain=data['subdomain'],
            custom_domain=data.get('custom_domain'),
            status=data.get('status', 'active'),
            tier=data.get('tier', 'basic'),
            parent_id=data.get('parent_id'),
            logo_url=data.get('logo_url'),
            favicon_url=data.get('favicon_url'),
            primary_color=data.get('primary_color', '#1a1a1a'),
            secondary_color=data.get('secondary_color', '#00ff88'),
            accent_color=data.get('accent_color', '#ff6b35'),
            custom_css=data.get('custom_css'),
            settings=data.get('settings', {}),
            contact_email=data.get('contact_email'),
            contact_phone=data.get('contact_phone')
        )
        
        db.session.add(tenant)
        db.session.commit()
        
        logger.info(f"Tenant created: {tenant.name} (ID: {tenant.id})")
        
        return jsonify({
            'message': 'Tenant created successfully',
            'tenant': tenant.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to create tenant: {str(e)}")
        return jsonify({'error': 'Failed to create tenant'}), 500


@tenants_bp.route('/<int:tenant_id>', methods=['PUT'])
@token_required
@role_required('supermaster')
def update_tenant(tenant_id):
    """Update tenant (supermaster only)"""
    tenant = Tenant.query.get_or_404(tenant_id)
    data = request.get_json()
    
    try:
        # Update fields
        updatable_fields = [
            'name', 'subdomain', 'custom_domain', 'status', 'tier',
            'parent_id', 'logo_url', 'favicon_url', 'primary_color',
            'secondary_color', 'accent_color', 'custom_css', 'settings',
            'contact_email', 'contact_phone'
        ]
        
        # Check subdomain uniqueness if changed
        if 'subdomain' in data and data['subdomain'] != tenant.subdomain:
            existing = Tenant.query.filter_by(subdomain=data['subdomain']).first()
            if existing:
                return jsonify({'error': 'Subdomain already exists'}), 400
        
        # Check custom domain uniqueness if changed
        if 'custom_domain' in data and data['custom_domain'] != tenant.custom_domain:
            existing = Tenant.query.filter_by(custom_domain=data['custom_domain']).first()
            if existing:
                return jsonify({'error': 'Custom domain already exists'}), 400
        
        for field in updatable_fields:
            if field in data:
                setattr(tenant, field, data[field])
        
        db.session.commit()
        
        logger.info(f"Tenant updated: {tenant.name} (ID: {tenant.id})")
        
        return jsonify({
            'message': 'Tenant updated successfully',
            'tenant': tenant.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to update tenant: {str(e)}")
        return jsonify({'error': 'Failed to update tenant'}), 500


@tenants_bp.route('/<int:tenant_id>', methods=['DELETE'])
@token_required
@role_required('supermaster')
def delete_tenant(tenant_id):
    """Delete tenant (supermaster only) - Soft delete by setting status to inactive"""
    tenant = Tenant.query.get_or_404(tenant_id)
    
    try:
        # Soft delete - set status to inactive
        tenant.status = 'inactive'
        db.session.commit()
        
        logger.info(f"Tenant deactivated: {tenant.name} (ID: {tenant.id})")
        
        return jsonify({
            'message': 'Tenant deactivated successfully'
        }), 200
        
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to deactivate tenant: {str(e)}")
        return jsonify({'error': 'Failed to deactivate tenant'}), 500


@tenants_bp.route('/<int:tenant_id>/children', methods=['GET'])
@token_required
@role_required('supermaster')
def get_tenant_children(tenant_id):
    """Get all children of a tenant (supermaster only)"""
    tenant = Tenant.query.get_or_404(tenant_id)
    
    children = tenant.get_all_children(include_self=False)
    
    return jsonify({
        'children': [c.to_dict() for c in children],
        'total': len(children)
    }), 200


@tenants_bp.route('/<int:tenant_id>/hierarchy', methods=['GET'])
@token_required
@role_required('supermaster')
def get_tenant_hierarchy(tenant_id):
    """Get full hierarchy of a tenant (supermaster only)"""
    tenant = Tenant.query.get_or_404(tenant_id)
    
    hierarchy = tenant.get_full_hierarchy()
    
    return jsonify({
        'hierarchy': [t.to_dict() for t in hierarchy]
    }), 200


@tenants_bp.route('/<int:tenant_id>/stats', methods=['GET'])
@token_required
@role_required('supermaster')
def get_tenant_stats(tenant_id):
    """Get tenant statistics (supermaster only)"""
    from src.models.user import User
    from src.models.trading_program import TradingProgram
    from src.models.challenge import Challenge
    
    tenant = Tenant.query.get_or_404(tenant_id)
    
    # Count users
    users_count = User.query.filter_by(tenant_id=tenant_id).count()
    
    # Count programs
    programs_count = TradingProgram.query.filter_by(tenant_id=tenant_id).count()
    
    # Count challenges
    challenges_count = Challenge.query.join(User).filter(User.tenant_id == tenant_id).count()
    
    # Count active challenges
    active_challenges = Challenge.query.join(User).filter(
        User.tenant_id == tenant_id,
        Challenge.status.in_(['active', 'pending'])
    ).count()
    
    return jsonify({
        'tenant_id': tenant_id,
        'stats': {
            'users': users_count,
            'programs': programs_count,
            'challenges': challenges_count,
            'active_challenges': active_challenges
        }
    }), 200
