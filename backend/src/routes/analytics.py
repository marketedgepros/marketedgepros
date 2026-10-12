"""Analytics routes for advanced dashboard data."""
from datetime import datetime

from flask import Blueprint, jsonify, request

from src.services.analytics_service import AnalyticsService
from src.services.admin_insights_read import (
    AdminInsightsQueryInvalid,
    AdminInsightsScopeRequired,
    AdminInsightsReadService,
)
from src.utils.analytics_cache import (
    analytics_cached,
    bounded_days_filter,
    no_query_filters,
)
from src.utils.decorators import admin_required, tenant_required, token_required
import logging

logger = logging.getLogger(__name__)

analytics_bp = Blueprint('analytics', __name__)


@analytics_bp.route('/revenue-over-time', methods=['GET'])
@token_required
@admin_required
@tenant_required
@analytics_cached(filters=bounded_days_filter)
def get_revenue_over_time(current_user):
    """Get revenue data over time"""
    try:
        days = bounded_days_filter()['days']
        data = AnalyticsService.get_revenue_over_time(days, tenant_id=current_user.tenant_id, current_user=current_user)
        
        return jsonify({
            'data': data,
            'period': f'Last {days} days'
        }), 200
        
    except Exception as e:
        logger.error(f'Error in revenue-over-time endpoint: {str(e)}')
        return jsonify({'error': 'Failed to fetch revenue data'}), 500


@analytics_bp.route('/user-growth', methods=['GET'])
@token_required
@admin_required
@tenant_required
@analytics_cached(filters=bounded_days_filter)
def get_user_growth(current_user):
    """Get user registration growth over time"""
    try:
        days = bounded_days_filter()['days']
        data = AnalyticsService.get_user_growth(days, tenant_id=current_user.tenant_id, current_user=current_user)
        
        return jsonify({
            'data': data,
            'period': f'Last {days} days'
        }), 200
        
    except Exception as e:
        logger.error(f'Error in user-growth endpoint: {str(e)}')
        return jsonify({'error': 'Failed to fetch user growth data'}), 500


@analytics_bp.route('/challenge-statistics', methods=['GET'])
@token_required
@admin_required
@tenant_required
@analytics_cached(filters=bounded_days_filter)
def get_challenge_statistics(current_user):
    """Get challenge statistics"""
    try:
        days = bounded_days_filter()['days']
        data = AnalyticsService.get_challenge_statistics(days, tenant_id=current_user.tenant_id, current_user=current_user)
        
        return jsonify({
            'data': data,
            'period': f'Last {days} days'
        }), 200
        
    except Exception as e:
        logger.error(f'Error in challenge-statistics endpoint: {str(e)}')
        return jsonify({'error': 'Failed to fetch challenge statistics'}), 500


@analytics_bp.route('/kyc-statistics', methods=['GET'])
@token_required
@admin_required
@tenant_required
@analytics_cached(filters=no_query_filters)
def get_kyc_statistics(current_user):
    """Get KYC verification statistics"""
    try:
        data = AnalyticsService.get_kyc_statistics(tenant_id=current_user.tenant_id, current_user=current_user)
        
        return jsonify({
            'data': data
        }), 200
        
    except Exception as e:
        logger.error(f'Error in kyc-statistics endpoint: {str(e)}')
        return jsonify({'error': 'Failed to fetch KYC statistics'}), 500


@analytics_bp.route('/referral-statistics', methods=['GET'])
@token_required
@admin_required
@tenant_required
@analytics_cached(filters=no_query_filters)
def get_referral_statistics(current_user):
    """Get referral and MLM statistics"""
    try:
        data = AnalyticsService.get_referral_statistics(tenant_id=current_user.tenant_id, current_user=current_user)
        
        return jsonify({
            'data': data
        }), 200
        
    except Exception as e:
        logger.error(f'Error in referral-statistics endpoint: {str(e)}')
        return jsonify({'error': 'Failed to fetch referral statistics'}), 500


@analytics_bp.route('/payment-statistics', methods=['GET'])
@token_required
@admin_required
@tenant_required
@analytics_cached(filters=bounded_days_filter)
def get_payment_statistics(current_user):
    """Get payment method and status statistics"""
    try:
        days = bounded_days_filter()['days']
        data = AnalyticsService.get_payment_statistics(days, tenant_id=current_user.tenant_id, current_user=current_user)
        
        return jsonify({
            'data': data,
            'period': f'Last {days} days'
        }), 200
        
    except Exception as e:
        logger.error(f'Error in payment-statistics endpoint: {str(e)}')
        return jsonify({'error': 'Failed to fetch payment statistics'}), 500


@analytics_bp.route('/comprehensive', methods=['GET'])
@token_required
@admin_required
@tenant_required
def get_comprehensive_analytics(current_user):
    """Return the bounded, uncached UI-4 insight analytics projection."""
    try:
        # Validate query syntax before constructing any resource CTEs.  This one
        # route deliberately bypasses the shared analytics cache.
        days = AdminInsightsReadService.parse_comprehensive_query(request.args)
        return jsonify(AdminInsightsReadService.comprehensive(current_user, days)), 200
    except AdminInsightsQueryInvalid:
        return jsonify({'error': 'Invalid admin insights query', 'code': 'INVALID_ADMIN_INSIGHTS_QUERY'}), 400
    except AdminInsightsScopeRequired:
        return jsonify({'error': 'Admin insights scope is required', 'code': 'ADMIN_INSIGHTS_SCOPE_REQUIRED'}), 403
    except Exception:
        from src.database import db
        db.session.rollback()
        return jsonify({'error': 'Admin insights are temporarily unavailable',
                        'code': 'ADMIN_INSIGHTS_READ_FAILED'}), 503
