"""
Affiliate Program Routes
Handles affiliate registration, tracking, commissions, and payouts
"""
from decimal import Decimal, InvalidOperation
import re

from flask import Blueprint, request, jsonify, current_app
from datetime import datetime, timedelta
from sqlalchemy import case, desc, func
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
from src.services.affiliate_records_read import (
    AffiliateRecordsArgumentError,
    AffiliateRecordsReadService,
)
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
    """Return bounded, tenant-scoped legacy affiliate records without authority."""
    tenant_id = current_user.tenant_id
    # Never infer a tenant from a legacy link, referral, or program record.
    if isinstance(tenant_id, bool) or not isinstance(tenant_id, int) or tenant_id < 1:
        return jsonify({
            'error': 'User must belong to a tenant',
            'code': 'TENANT_CONTEXT_REQUIRED',
        }), 403

    owner_context = {'user_id': current_user.id, 'tenant_id': tenant_id}

    def decimal_string(value):
        """Serialize finite stored Numeric values without float coercion or zero-fill."""
        if value is None or isinstance(value, bool):
            return None
        try:
            result = value if isinstance(value, Decimal) else Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None
        return format(result, 'f') if result.is_finite() else None

    def nonnegative_count(value):
        """Expose only recorded non-negative integer counters; unknown stays null."""
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        return value

    def public_link_url(code):
        """Keep received codes inside the sole approved public HTTPS URL shape."""
        if not isinstance(code, str) or not re.fullmatch(r'[A-Z0-9]{1,50}', code):
            return None
        return f'https://marketedgepros.com/?ref={code}'

    try:
        with db.session.no_autoflush:
            # Keep the dashboard's fixed bounded query plan while applying the
            # same local PostgreSQL timeout as the two record-list projections.
            AffiliateRecordsReadService._set_postgresql_statement_timeout()
            link_totals = (
                db.session.query(
                    func.count(AffiliateLink.id).label('total'),
                    func.sum(AffiliateLink.clicks).label('clicks'),
                    func.count(AffiliateLink.clicks).label('clicks_count'),
                    func.sum(case((AffiliateLink.clicks < 0, 1), else_=0)).label('negative_clicks'),
                    func.sum(AffiliateLink.conversions).label('conversions'),
                    func.count(AffiliateLink.conversions).label('conversions_count'),
                    func.sum(case((AffiliateLink.conversions < 0, 1), else_=0)).label('negative_conversions'),
                    func.sum(AffiliateLink.total_revenue).label('revenue'),
                    func.count(AffiliateLink.total_revenue).label('revenue_count'),
                )
                .filter(AffiliateLink.user_id == current_user.id)
                .one()
            )
            # COUNT(id) is the authoritative pagination total and must never be
            # replaced with a guessed zero for a malformed storage response.
            total_links = nonnegative_count(link_totals.total)
            if total_links is None:
                raise RuntimeError('affiliate link count was not a non-negative integer')
            # Preserve the existing endpoint's registration signal without
            # loading all links into application memory.
            if total_links == 0:
                return jsonify({'error': 'Not registered as affiliate'}), 404

            commission_totals = (
                AffiliateRecordsReadService._coherent_commissions_query(current_user)
                .with_entities(
                    func.sum(AffiliateCommission.amount).label('total'),
                    func.sum(case(
                        (AffiliateCommission.status == 'pending', AffiliateCommission.amount),
                        else_=None,
                    )).label('pending'),
                    func.sum(case(
                        (AffiliateCommission.status == 'approved', AffiliateCommission.amount),
                        else_=None,
                    )).label('approved'),
                    func.sum(case(
                        (AffiliateCommission.status == 'paid', AffiliateCommission.amount),
                        else_=None,
                    )).label('paid'),
                )
                .one()
            )
            links = (
                AffiliateLink.query.execution_options(autoflush=False)
                .filter(AffiliateLink.user_id == current_user.id)
                .order_by(desc(AffiliateLink.created_at), desc(AffiliateLink.id))
                .limit(50)
                .all()
            )
            recent_referrals = (
                AffiliateRecordsReadService._coherent_referrals_query(current_user)
                .execution_options(autoflush=False)
                .order_by(desc(AffiliateReferral.click_date), desc(AffiliateReferral.id))
                .limit(10)
                .all()
            )

        # A sum is displayable only if each owned link supplied that field. This
        # prevents a partial legacy aggregate from looking complete. Negative
        # counters are likewise unavailable, not normalized to zero.
        total_clicks = (
            nonnegative_count(link_totals.clicks)
            if link_totals.clicks_count == total_links and link_totals.negative_clicks == 0
            else None
        )
        total_conversions = (
            nonnegative_count(link_totals.conversions)
            if (
                link_totals.conversions_count == total_links
                and link_totals.negative_conversions == 0
            )
            else None
        )
        total_revenue = (
            decimal_string(link_totals.revenue)
            if link_totals.revenue_count == total_links
            else None
        )
        conversion_rate = None
        if total_clicks is not None and total_conversions is not None and total_clicks > 0:
            conversion_rate = decimal_string(
                (Decimal(total_conversions) * Decimal('100')) / Decimal(total_clicks)
            )

        # A concurrent delete after the aggregate remains a closed 404 rather
        # than a widened or stale ownership response.
        if not links:
            return jsonify({'error': 'Not registered as affiliate'}), 404

        return jsonify({
            'owner_context': owner_context,
            'stats': {
                'total_clicks': total_clicks,
                'total_conversions': total_conversions,
                'total_revenue': total_revenue,
                'total_commission': decimal_string(commission_totals.total),
                'conversion_rate': conversion_rate,
                'pending_commission': decimal_string(commission_totals.pending),
                'approved_commission': decimal_string(commission_totals.approved),
                'paid_commission': decimal_string(commission_totals.paid),
                'currency': None,
                'available_for_payout': None,
                'payouts_enabled': False,
                'commission_verification': 'unverified_legacy',
            },
            'link_pagination': {
                'total': total_links,
                'limit': 50,
                'truncated': total_links > 50,
            },
            'links': [{
                'id': link.id,
                'name': link.name,
                'url': public_link_url(link.code),
                'clicks': nonnegative_count(link.clicks),
                'conversions': nonnegative_count(link.conversions),
            } for link in links],
            'recent_referrals': [{
                'id': referral.id,
                'status': referral.status,
                'click_date': referral.click_date.isoformat() if referral.click_date else None,
                'commission_amount': decimal_string(referral.commission_amount),
                'currency': None,
            } for referral in recent_referrals],
        }), 200

    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        current_app.logger.error('Affiliate dashboard read failed')
        return jsonify({
            'error': 'Dashboard is temporarily unavailable',
            'code': 'AFFILIATE_DASHBOARD_UNAVAILABLE',
        }), 503


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
    """Return a bounded, coherent legacy referral page without PII."""
    try:
        arguments = AffiliateRecordsReadService.parse_referral_arguments(request.args)
    except AffiliateRecordsArgumentError:
        return jsonify({
            'error': 'Invalid affiliate records query',
            'code': 'AFFILIATE_RECORDS_QUERY_INVALID',
        }), 400

    # This gate intentionally follows query validation but precedes every
    # affiliate resource query. Tenant identity is never inferred from a row.
    if not AffiliateRecordsReadService.has_positive_tenant(current_user):
        return jsonify({
            'error': 'User must belong to a tenant',
            'code': 'TENANT_CONTEXT_REQUIRED',
        }), 403

    try:
        return jsonify(AffiliateRecordsReadService.get_referrals(current_user, arguments)), 200
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        current_app.logger.error('Affiliate referrals read failed')
        return jsonify({
            'error': 'Affiliate records are temporarily unavailable',
            'code': 'AFFILIATE_RECORDS_UNAVAILABLE',
        }), 503


@affiliate_bp.route('/commissions', methods=['GET'])
@token_required
def get_commissions(current_user):
    """Return a bounded, coherent legacy commission page without payout authority."""
    try:
        arguments = AffiliateRecordsReadService.parse_commission_arguments(request.args)
    except AffiliateRecordsArgumentError:
        return jsonify({
            'error': 'Invalid affiliate records query',
            'code': 'AFFILIATE_RECORDS_QUERY_INVALID',
        }), 400

    # Keep the same closed tenant boundary as referrals; authentication itself
    # remains handled by token_required before this request reaches the handler.
    if not AffiliateRecordsReadService.has_positive_tenant(current_user):
        return jsonify({
            'error': 'User must belong to a tenant',
            'code': 'TENANT_CONTEXT_REQUIRED',
        }), 403

    try:
        return jsonify(AffiliateRecordsReadService.get_commissions(current_user, arguments)), 200
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        current_app.logger.error('Affiliate commissions read failed')
        return jsonify({
            'error': 'Affiliate records are temporarily unavailable',
            'code': 'AFFILIATE_RECORDS_UNAVAILABLE',
        }), 503


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
