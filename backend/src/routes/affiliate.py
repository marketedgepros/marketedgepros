"""
Affiliate Program Routes
Handles affiliate registration, tracking, commissions, and payouts
"""
from flask import Blueprint, request, jsonify, current_app
from datetime import datetime, timedelta
from sqlalchemy import func
import secrets
import string

from src.database import db
from src.models.affiliate import (
    AffiliateLink, AffiliateReferral, AffiliateCommission,
    AffiliatePayout, AffiliateSettings
)
from src.models.user import User
from src.utils.decorators import token_required, admin_required
from src.services.affiliate_financial_boundary import affiliate_mutation_unavailable_response
from src.utils.hierarchy_scoping import platform_root_scope

affiliate_bp = Blueprint('affiliate', __name__)


def generate_affiliate_code(length=8):
    """Generate a code with bounded work; the DB unique constraint is final."""
    for _ in range(5):
        code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(length))
        if not AffiliateLink.query.filter_by(code=code).first():
            return code
    raise RuntimeError('Affiliate code allocation unavailable')


# ============================================================================
# PUBLIC ROUTES
# ============================================================================

@affiliate_bp.route('/info', methods=['GET'])
def get_affiliate_info():
    """Get affiliate program information"""
    try:
        settings = AffiliateSettings.query.first()
        
        if not settings or not settings.is_active:
            return jsonify({'error': 'Affiliate program is not active'}), 404
        
        return jsonify({
            'program': {
                'is_active': settings.is_active,
                'commission_rate': float(settings.default_commission_rate),
                'min_payout': float(settings.min_payout_amount),
                'cookie_duration_days': settings.cookie_duration_days,
                'terms': settings.terms_and_conditions,
                'payouts_enabled': False,
                'settlement_verification': 'not_configured'
            },
            'benefits': [
                f'{float(settings.default_commission_rate)}% configured rate; commission eligibility requires verified settlement',
                f'${float(settings.min_payout_amount)} minimum payout',
                f'{settings.cookie_duration_days}-day cookie duration',
                'Real-time tracking dashboard',
                'Payouts unavailable until settlement and identity verification are configured',
                'Dedicated affiliate support'
            ]
        }), 200
        
    except Exception as e:
        current_app.logger.error(f'Get affiliate info error: {str(e)}')
        return jsonify({'error': 'Failed to get affiliate info'}), 500


@affiliate_bp.route('/register', methods=['POST'])
@token_required
def register_affiliate(current_user):
    """Register as an affiliate"""
    try:
        settings = AffiliateSettings.query.first()
        
        if not settings or not settings.is_active:
            return jsonify({'error': 'Affiliate program is not active'}), 400
        
        # Check if user already has an affiliate link
        existing_link = AffiliateLink.query.filter_by(user_id=current_user.id).first()
        if existing_link:
            return jsonify({
                'message': 'You are already registered as an affiliate',
                'link': existing_link.to_dict()
            }), 200
        
        # Create affiliate link
        code = generate_affiliate_code()
        affiliate_link = AffiliateLink(
            user_id=current_user.id,
            code=code,
            name='Default Link',
            commission_rate=settings.default_commission_rate
        )
        
        db.session.add(affiliate_link)
        db.session.commit()
        
        return jsonify({
            'message': 'Successfully registered as affiliate',
            'link': affiliate_link.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Affiliate registration error: {str(e)}')
        return jsonify({'error': 'Failed to register as affiliate'}), 500


# ============================================================================
# AFFILIATE ROUTES (Authenticated Users)
# ============================================================================

@affiliate_bp.route('/dashboard', methods=['GET'])
@token_required
def get_dashboard(current_user):
    """Get affiliate dashboard statistics"""
    try:
        # Get all affiliate links for user
        links = AffiliateLink.query.filter_by(user_id=current_user.id).all()
        
        if not links:
            return jsonify({'error': 'Not registered as affiliate'}), 404
        
        # Calculate totals
        total_clicks = sum(link.clicks for link in links)
        total_conversions = sum(link.conversions for link in links)
        total_revenue = sum(link.total_revenue for link in links)
        total_commission = sum(link.total_commission for link in links)
        
        # Get commission breakdown
        commissions = AffiliateCommission.query.filter_by(affiliate_user_id=current_user.id).all()
        pending_commission = sum(c.amount for c in commissions if c.status == 'pending')
        approved_commission = sum(c.amount for c in commissions if c.status == 'approved')
        paid_commission = sum(c.amount for c in commissions if c.status == 'paid')
        
        # Get recent referrals
        recent_referrals = AffiliateReferral.query.filter_by(
            affiliate_user_id=current_user.id
        ).order_by(AffiliateReferral.click_date.desc()).limit(10).all()
        
        return jsonify({
            'stats': {
                'total_clicks': total_clicks,
                'total_conversions': total_conversions,
                'total_revenue': float(total_revenue),
                'total_commission': float(total_commission),
                'conversion_rate': round((total_conversions / total_clicks * 100) if total_clicks > 0 else 0, 2),
                'pending_commission': float(pending_commission),
                'approved_commission': float(approved_commission),
                'paid_commission': float(paid_commission),
                'available_for_payout': None,
                'payouts_enabled': False,
                'commission_verification': 'unverified_legacy'
            },
            'links': [link.to_dict() for link in links],
            'recent_referrals': [ref.to_dict() for ref in recent_referrals]
        }), 200
        
    except Exception as e:
        current_app.logger.error(f'Get affiliate dashboard error: {str(e)}')
        return jsonify({'error': 'Failed to get dashboard'}), 500


@affiliate_bp.route('/links', methods=['GET'])
@token_required
def get_affiliate_links(current_user):
    """Get all affiliate links for current user"""
    try:
        links = AffiliateLink.query.filter_by(user_id=current_user.id).all()
        return jsonify({'links': [link.to_dict() for link in links]}), 200
        
    except Exception as e:
        current_app.logger.error(f'Get affiliate links error: {str(e)}')
        return jsonify({'error': 'Failed to get links'}), 500


@affiliate_bp.route('/links', methods=['POST'])
@token_required
def create_affiliate_link(current_user):
    """Create new affiliate link"""
    try:
        data = request.get_json()
        name = data.get('name', 'Custom Link')
        
        # Generate unique code
        code = generate_affiliate_code()
        
        # Get default commission rate
        settings = AffiliateSettings.query.first()
        
        affiliate_link = AffiliateLink(
            user_id=current_user.id,
            code=code,
            name=name,
            commission_rate=settings.default_commission_rate if settings else 10.00
        )
        
        db.session.add(affiliate_link)
        db.session.commit()
        
        return jsonify({
            'message': 'Affiliate link created',
            'link': affiliate_link.to_dict()
        }), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Create affiliate link error: {str(e)}')
        return jsonify({'error': 'Failed to create link'}), 500


@affiliate_bp.route('/referrals', methods=['GET'])
@token_required
def get_referrals(current_user):
    """Get all referrals for current user"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        status = request.args.get('status')
        
        query = AffiliateReferral.query.filter_by(affiliate_user_id=current_user.id)
        
        if status:
            query = query.filter_by(status=status)
        
        referrals = query.order_by(AffiliateReferral.click_date.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        return jsonify({
            'referrals': [ref.to_dict() for ref in referrals.items],
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': referrals.total,
                'pages': referrals.pages
            }
        }), 200
        
    except Exception as e:
        current_app.logger.error(f'Get referrals error: {str(e)}')
        return jsonify({'error': 'Failed to get referrals'}), 500


@affiliate_bp.route('/commissions', methods=['GET'])
@token_required
def get_commissions(current_user):
    """Get all commissions for current user"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        status = request.args.get('status')
        
        query = AffiliateCommission.query.filter_by(affiliate_user_id=current_user.id)
        
        if status:
            query = query.filter_by(status=status)
        
        commissions = query.order_by(AffiliateCommission.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        return jsonify({
            'commissions': [comm.to_dict() for comm in commissions.items],
            'payouts_enabled': False,
            'verification': 'unverified_legacy',
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': commissions.total,
                'pages': commissions.pages
            }
        }), 200
        
    except Exception as e:
        current_app.logger.error(f'Get commissions error: {str(e)}')
        return jsonify({'error': 'Failed to get commissions'}), 500


@affiliate_bp.route('/payout', methods=['POST'])
@token_required
def request_payout(current_user):
    """Legacy approved rows are not authority to reserve or request funds."""
    return affiliate_mutation_unavailable_response()


@affiliate_bp.route('/payouts', methods=['GET'])
@token_required
def get_payouts(current_user):
    """Get all payouts for current user"""
    try:
        payouts = AffiliatePayout.query.filter_by(
            affiliate_user_id=current_user.id
        ).order_by(AffiliatePayout.requested_at.desc()).all()
        
        return jsonify({'payouts': [p.to_dict() for p in payouts], 'verification': 'unverified_legacy', 'payouts_enabled': False}), 200
        
    except Exception as e:
        current_app.logger.error(f'Get payouts error: {str(e)}')
        return jsonify({'error': 'Failed to get payouts'}), 500


# ============================================================================
# ADMIN ROUTES
# ============================================================================

@affiliate_bp.route('/admin/affiliates', methods=['GET'])
@admin_required
def get_all_affiliates(current_user):
    """Get all affiliates (admin only)"""
    try:
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        # Get all users with affiliate links
        affiliates = db.session.query(User, AffiliateLink).join(
            AffiliateLink, User.id == AffiliateLink.user_id
        ).paginate(page=page, per_page=per_page, error_out=False)
        
        result = []
        for user, link in affiliates.items:
            result.append({
                'user': {
                    'id': user.id,
                    'email': user.email,
                    'name': f'{user.first_name} {user.last_name}'
                },
                'link': link.to_dict()
            })
        
        return jsonify({
            'affiliates': result,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': affiliates.total,
                'pages': affiliates.pages
            }
        }), 200
        
    except Exception as e:
        current_app.logger.error(f'Get all affiliates error: {str(e)}')
        return jsonify({'error': 'Failed to get affiliates'}), 500


@affiliate_bp.route('/admin/payouts', methods=['GET'])
@admin_required
def get_all_payouts(current_user):
    """Get all payout requests (admin only)"""
    try:
        status = request.args.get('status')
        
        query = AffiliatePayout.query
        
        if status:
            query = query.filter_by(status=status)
        
        payouts = query.order_by(AffiliatePayout.requested_at.desc()).all()
        
        result = []
        for payout in payouts:
            result.append({
                **payout.to_dict(),
                'affiliate': {
                    'id': payout.affiliate_user.id,
                    'email': payout.affiliate_user.email,
                    'name': f'{payout.affiliate_user.first_name} {payout.affiliate_user.last_name}'
                }
            })
        
        return jsonify({'payouts': result}), 200
        
    except Exception as e:
        current_app.logger.error(f'Get all payouts error: {str(e)}')
        return jsonify({'error': 'Failed to get payouts'}), 500


@affiliate_bp.route('/admin/payout/<int:payout_id>/process', methods=['POST'])
@token_required
@admin_required
def process_payout(current_user, payout_id):
    """Client-supplied status/transaction text cannot prove disbursement."""
    return affiliate_mutation_unavailable_response()


@affiliate_bp.route('/admin/settings', methods=['GET', 'PUT'])
@token_required
@admin_required
def manage_settings(current_user):
    """Get or update affiliate settings (admin only)"""
    # This legacy table has no tenant key: only the explicitly configured
    # platform owner may read or edit its global program settings.
    if not platform_root_scope(current_user):
        return jsonify({'error': 'Platform owner access required'}), 403
    try:
        data = None
        if request.method == 'PUT':
            if not request.is_json:
                return jsonify({'error': 'JSON request required'}), 415
            raw = request.stream.read(4097)
            if len(raw) > 4096:
                return jsonify({'error': 'Affiliate settings request too large'}), 413
            import json
            def unique_fields(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError('Duplicate field')
                    result[key] = value
                return result
            def reject_constant(value):
                raise ValueError('Non-finite JSON number')
            try:
                data = json.loads(raw, object_pairs_hook=unique_fields, parse_constant=reject_constant)
            except (ValueError, RecursionError):
                return jsonify({'error': 'Invalid affiliate settings request'}), 400
            if not isinstance(data, dict):
                return jsonify({'error': 'Invalid affiliate settings request'}), 400
            if 'auto_approve_commissions' in data and data['auto_approve_commissions'] is not False:
                return jsonify({'error': 'Automatic commission approval requires verified settlement and identity',
                                'code': 'AFFILIATE_AUTO_APPROVAL_UNAVAILABLE'}), 409

        settings = AffiliateSettings.query.first()
        if not settings:
            return jsonify({'error': 'Affiliate settings not configured'}), 404
        if request.method == 'GET':
            return jsonify({'settings': settings.to_dict(), 'payouts_enabled': False,
                            'settlement_verification': 'not_configured'}), 200
        
        if 'default_commission_rate' in data:
            settings.default_commission_rate = data['default_commission_rate']
        if 'min_payout_amount' in data:
            settings.min_payout_amount = data['min_payout_amount']
        if 'cookie_duration_days' in data:
            settings.cookie_duration_days = data['cookie_duration_days']
        if 'is_active' in data:
            settings.is_active = data['is_active']
        if 'auto_approve_affiliates' in data:
            settings.auto_approve_affiliates = data['auto_approve_affiliates']
        if 'auto_approve_commissions' in data:
            settings.auto_approve_commissions = data['auto_approve_commissions']
        if 'terms_and_conditions' in data:
            settings.terms_and_conditions = data['terms_and_conditions']
        
        settings.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'message': 'Settings updated successfully',
            'settings': settings.to_dict()
        }), 200
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Manage settings error: {str(e)}')
        return jsonify({'error': 'Failed to manage settings'}), 500
