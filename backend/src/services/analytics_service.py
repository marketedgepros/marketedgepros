"""
Analytics Service
Provides advanced analytics and reporting functionality
"""
from datetime import datetime, timedelta
from sqlalchemy import and_, case, func, select, or_, false
from sqlalchemy.orm import aliased
from src.database import db
from src.models.user import User
from src.models.trading_program import Challenge, TradingProgram
from src.models.payment import Payment
from src.models.commission import Commission
from src.models.referral import Referral
from src.models.agent import Agent
import logging

logger = logging.getLogger(__name__)


class AnalyticsService:
    """Service for analytics and reporting"""

    @staticmethod
    def _owner_clause(entity, tenant_id, current_user=None):
        # Explicit tenant-wide service calls are internal only. HTTP routes must
        # pass their authenticated actor; aggregate hooks are not authorization.
        clause = entity.tenant_id == tenant_id
        if current_user is None:
            return clause
        if current_user.tenant_id != tenant_id:
            return false()
        if current_user.role == 'supermaster' and current_user.parent_id is None:
            return clause
        path = current_user.tree_path
        if not isinstance(path, str) or not path:
            return and_(clause, entity.id == current_user.id)
        escaped = path.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        return and_(clause, or_(entity.id == current_user.id,
                    entity.tree_path.like(escaped + '/%', escape='\\')))

    @staticmethod
    def _require_tenant_id(tenant_id):
        """Return a valid actor tenant or fail before any aggregate can run."""
        if isinstance(tenant_id, bool):
            raise ValueError('tenant_id is required for analytics')
        try:
            normalized_tenant_id = int(tenant_id)
        except (TypeError, ValueError):
            raise ValueError('tenant_id is required for analytics') from None
        if normalized_tenant_id < 1:
            raise ValueError('tenant_id is required for analytics')
        return normalized_tenant_id
    
    @staticmethod
    def get_revenue_over_time(days=30, tenant_id=None, current_user=None):
        """
        Get revenue data over time
        
        Args:
            days: Number of days to look back
            
        Returns:
            List of daily revenue data
        """
        tenant_id = AnalyticsService._require_tenant_id(tenant_id)
        try:
            start_date = datetime.utcnow() - timedelta(days=days)
            
            # Payments have no tenant column: scope through the paying user.
            daily_revenue = db.session.query(
                func.date(Payment.created_at).label('date'),
                func.sum(Payment.amount).label('revenue'),
                func.count(Payment.id).label('transactions')
            ).select_from(Payment).join(
                User, Payment.user_id == User.id
            ).filter(
                and_(
                    AnalyticsService._owner_clause(User, tenant_id, current_user),
                    Payment.status == 'completed',
                    Payment.created_at >= start_date
                )
            ).group_by(
                func.date(Payment.created_at)
            ).order_by(
                func.date(Payment.created_at)
            ).all()
            
            return [{
                'date': str(row.date),
                'revenue': float(row.revenue),
                'transactions': row.transactions
            } for row in daily_revenue]
            
        except Exception as e:
            logger.error(f'Error getting revenue over time: {str(e)}')
            raise RuntimeError('Analytics query failed') from e
    
    @staticmethod
    def get_user_growth(days=30, tenant_id=None, current_user=None):
        """
        Get user registration growth over time
        
        Args:
            days: Number of days to look back
            
        Returns:
            List of daily user registration data
        """
        tenant_id = AnalyticsService._require_tenant_id(tenant_id)
        try:
            start_date = datetime.utcnow() - timedelta(days=days)
            
            # Query daily registrations.
            daily_users = db.session.query(
                func.date(User.created_at).label('date'),
                func.count(User.id).label('registrations'),
                func.sum(case((User.is_active == True, 1), else_=0)).label('active')
            ).filter(
                AnalyticsService._owner_clause(User, tenant_id, current_user),
                User.created_at >= start_date
            ).group_by(
                func.date(User.created_at)
            ).order_by(
                func.date(User.created_at)
            ).all()
            
            # Calculate cumulative total
            cumulative = 0
            result = []
            for row in daily_users:
                cumulative += row.registrations
                result.append({
                    'date': str(row.date),
                    'registrations': row.registrations,
                    'active': row.active,
                    'cumulative': cumulative
                })
            
            return result
            
        except Exception as e:
            logger.error(f'Error getting user growth: {str(e)}')
            raise RuntimeError('Analytics query failed') from e
    
    @staticmethod
    def get_challenge_statistics(days=30, tenant_id=None, current_user=None):
        """
        Get challenge statistics over time
        
        Args:
            days: Number of days to look back
            
        Returns:
            Challenge statistics data
        """
        tenant_id = AnalyticsService._require_tenant_id(tenant_id)
        try:
            start_date = datetime.utcnow() - timedelta(days=days)
            
            # A challenge is tenant-safe only when both its owner and program
            # belong to the authenticated actor's tenant.
            status_distribution = db.session.query(
                Challenge.status,
                func.count(Challenge.id).label('count')
            ).select_from(Challenge).join(
                User, Challenge.user_id == User.id
            ).join(
                TradingProgram, Challenge.program_id == TradingProgram.id
            ).filter(
                AnalyticsService._owner_clause(User, tenant_id, current_user),
                TradingProgram.tenant_id == tenant_id,
                Challenge.created_at >= start_date
            ).group_by(
                Challenge.status
            ).all()
            
            # Query daily challenge creation
            daily_challenges = db.session.query(
                func.date(Challenge.created_at).label('date'),
                func.count(Challenge.id).label('created'),
                func.sum(case((Challenge.status == 'completed', 1), else_=0)).label('completed'),
                func.sum(case((Challenge.status == 'funded', 1), else_=0)).label('funded')
            ).select_from(Challenge).join(
                User, Challenge.user_id == User.id
            ).join(
                TradingProgram, Challenge.program_id == TradingProgram.id
            ).filter(
                AnalyticsService._owner_clause(User, tenant_id, current_user),
                TradingProgram.tenant_id == tenant_id,
                Challenge.created_at >= start_date
            ).group_by(
                func.date(Challenge.created_at)
            ).order_by(
                func.date(Challenge.created_at)
            ).all()
            
            return {
                'status_distribution': [{
                    'status': row.status,
                    'count': row.count
                } for row in status_distribution],
                'daily_data': [{
                    'date': str(row.date),
                    'created': row.created,
                    'completed': row.completed,
                    'funded': row.funded
                } for row in daily_challenges]
            }
            
        except Exception as e:
            logger.error(f'Error getting challenge statistics: {str(e)}')
            raise RuntimeError('Analytics query failed') from e
    
    @staticmethod
    def get_kyc_statistics(tenant_id=None, current_user=None):
        """
        Get KYC verification statistics
        
        Returns:
            KYC statistics data
        """
        tenant_id = AnalyticsService._require_tenant_id(tenant_id)
        try:
            # Query KYC status distribution
            kyc_distribution = db.session.query(
                User.kyc_status,
                func.count(User.id).label('count')
            ).filter(
                AnalyticsService._owner_clause(User, tenant_id, current_user)
            ).group_by(
                User.kyc_status
            ).all()
            
            # Query recent KYC submissions (last 30 days)
            thirty_days_ago = datetime.utcnow() - timedelta(days=30)
            recent_kyc = db.session.query(
                func.date(User.kyc_submitted_at).label('date'),
                func.count(User.id).label('submissions')
            ).filter(
                and_(
                    AnalyticsService._owner_clause(User, tenant_id, current_user),
                    User.kyc_submitted_at.isnot(None),
                    User.kyc_submitted_at >= thirty_days_ago
                )
            ).group_by(
                func.date(User.kyc_submitted_at)
            ).order_by(
                func.date(User.kyc_submitted_at)
            ).all()
            
            return {
                'distribution': [{
                    'status': row.kyc_status or 'not_submitted',
                    'count': row.count
                } for row in kyc_distribution],
                'recent_submissions': [{
                    'date': str(row.date),
                    'submissions': row.submissions
                } for row in recent_kyc]
            }
            
        except Exception as e:
            logger.error(f'Error getting KYC statistics: {str(e)}')
            raise RuntimeError('Analytics query failed') from e
    
    @staticmethod
    def get_referral_statistics(tenant_id=None, current_user=None):
        """
        Get referral and MLM statistics
        
        Returns:
            Referral statistics data
        """
        tenant_id = AnalyticsService._require_tenant_id(tenant_id)
        try:
            # Referral/commission records have no tenant column. Anchor agents
            # through their owning user and include only same-tenant referred
            # users and challenge/program combinations.
            agent_owner = aliased(User)
            referred_user = aliased(User)
            challenge_owner = aliased(User)
            commission_referral = aliased(Referral)
            commission_referred_user = aliased(User)
            referral_count = (
                select(func.count(Referral.id))
                .select_from(Referral)
                .join(referred_user, Referral.referred_user_id == referred_user.id)
                .where(
                    Referral.agent_id == Agent.id,
                    referred_user.tenant_id == tenant_id,
                )
                .correlate(Agent)
                .scalar_subquery()
            )
            commission_total = (
                select(func.coalesce(func.sum(Commission.commission_amount), 0))
                .select_from(Commission)
                .join(commission_referral, Commission.referral_id == commission_referral.id)
                .join(commission_referred_user, commission_referral.referred_user_id == commission_referred_user.id)
                .join(Challenge, Commission.challenge_id == Challenge.id)
                .join(challenge_owner, Challenge.user_id == challenge_owner.id)
                .join(TradingProgram, Challenge.program_id == TradingProgram.id)
                .where(
                    Commission.agent_id == Agent.id,
                    commission_referral.agent_id == Agent.id,
                    commission_referred_user.tenant_id == tenant_id,
                    challenge_owner.tenant_id == tenant_id,
                    TradingProgram.tenant_id == tenant_id,
                )
                .correlate(Agent)
                .scalar_subquery()
            )

            # Scalar subqueries retain a single database query and avoid both
            # the former N+1 user lookup and referral/commission row inflation.
            top_agents = db.session.query(
                Agent.id.label('agent_id'),
                agent_owner.first_name,
                agent_owner.last_name,
                agent_owner.email,
                referral_count.label('referral_count'),
                commission_total.label('total_commission'),
            ).join(
                agent_owner, Agent.user_id == agent_owner.id
            ).filter(
                AnalyticsService._owner_clause(agent_owner, tenant_id, current_user)
            ).order_by(
                referral_count.desc(), Agent.id
            ).limit(10).all()
            
            top_agents_data = [{
                'agent_id': row.agent_id,
                'name': f"{row.first_name} {row.last_name}",
                'email': row.email,
                'referrals': row.referral_count,
                'total_commission': float(row.total_commission or 0),
            } for row in top_agents]
            
            scoped_referrals = db.session.query(Referral).join(
                Agent, Referral.agent_id == Agent.id
            ).join(
                agent_owner, Agent.user_id == agent_owner.id
            ).join(
                referred_user, Referral.referred_user_id == referred_user.id
            ).filter(
                AnalyticsService._owner_clause(agent_owner, tenant_id, current_user),
                referred_user.tenant_id == tenant_id,
            )
            total_referrals = scoped_referrals.count()
            active_referrals = scoped_referrals.filter(Referral.status == 'active').count()
            conversion_rate = (active_referrals / total_referrals * 100) if total_referrals > 0 else 0
            
            return {
                'top_agents': top_agents_data,
                'total_referrals': total_referrals,
                'active_referrals': active_referrals,
                'conversion_rate': round(conversion_rate, 2)
            }
            
        except Exception as e:
            logger.error(f'Error getting referral statistics: {str(e)}')
            raise RuntimeError('Analytics query failed') from e

    
    @staticmethod
    def get_payment_statistics(days=30, tenant_id=None, current_user=None):
        """
        Get payment method and status statistics
        
        Args:
            days: Number of days to look back
            
        Returns:
            Payment statistics data
        """
        tenant_id = AnalyticsService._require_tenant_id(tenant_id)
        try:
            start_date = datetime.utcnow() - timedelta(days=days)
            
            # Payments are tenant-derived through their paying user.
            method_distribution = db.session.query(
                Payment.payment_method,
                func.count(Payment.id).label('count'),
                func.sum(Payment.amount).label('total_amount')
            ).select_from(Payment).join(
                User, Payment.user_id == User.id
            ).filter(
                and_(
                    AnalyticsService._owner_clause(User, tenant_id, current_user),
                    Payment.created_at >= start_date,
                    Payment.status == 'completed'
                )
            ).group_by(
                Payment.payment_method
            ).all()
            
            # Payment status distribution
            status_distribution = db.session.query(
                Payment.status,
                func.count(Payment.id).label('count')
            ).select_from(Payment).join(
                User, Payment.user_id == User.id
            ).filter(
                AnalyticsService._owner_clause(User, tenant_id, current_user),
                Payment.created_at >= start_date
            ).group_by(
                Payment.status
            ).all()
            
            return {
                'method_distribution': [{
                    'method': row.payment_method or 'unknown',
                    'count': row.count,
                    'total_amount': float(row.total_amount)
                } for row in method_distribution],
                'status_distribution': [{
                    'status': row.status,
                    'count': row.count
                } for row in status_distribution]
            }
            
        except Exception as e:
            logger.error(f'Error getting payment statistics: {str(e)}')
            raise RuntimeError('Analytics query failed') from e
    
    @staticmethod
    def get_comprehensive_analytics(days=30, tenant_id=None, current_user=None):
        """
        Get comprehensive analytics data for dashboard
        
        Args:
            days: Number of days to look back
            
        Returns:
            Comprehensive analytics data
        """
        tenant_id = AnalyticsService._require_tenant_id(tenant_id)
        try:
            return {
                'revenue_over_time': AnalyticsService.get_revenue_over_time(days, tenant_id, current_user),
                'user_growth': AnalyticsService.get_user_growth(days, tenant_id, current_user),
                'challenge_statistics': AnalyticsService.get_challenge_statistics(days, tenant_id, current_user),
                'kyc_statistics': AnalyticsService.get_kyc_statistics(tenant_id, current_user),
                'referral_statistics': AnalyticsService.get_referral_statistics(tenant_id, current_user),
                'payment_statistics': AnalyticsService.get_payment_statistics(days, tenant_id, current_user)
            }
        except Exception as e:
            logger.error(f'Error getting comprehensive analytics: {str(e)}')
            raise RuntimeError('Analytics query failed') from e
