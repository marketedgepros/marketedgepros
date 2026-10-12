"""
Commission Service
Handles automatic commission calculation and tracking
"""
from src.database import db
from src.models import Commission, Agent
from decimal import Decimal
import logging
from src.services.affiliate_financial_boundary import refuse_unverified_affiliate_mutation

logger = logging.getLogger(__name__)


class CommissionService:
    """Service for managing commissions"""
    
    @staticmethod
    def calculate_and_create_commission(challenge_id, sale_amount):
        """Refuse legacy commission creation before any lookup or side effect.

        A verified affiliate settlement, identity, and ledger integration must
        replace this mutator before commissions can be created again. Reporting
        methods below remain deliberately read-only.
        """
        refuse_unverified_affiliate_mutation()
    
    @staticmethod
    def approve_commission(commission_id, approved_by_id):
        """Refuse legacy commission approval before any lookup or side effect."""
        refuse_unverified_affiliate_mutation()
    
    @staticmethod
    def mark_commission_paid(commission_id, payment_method, transaction_id):
        """Refuse legacy commission payment before any lookup or side effect."""
        refuse_unverified_affiliate_mutation()
    
    @staticmethod
    def get_agent_commissions(agent_id, status=None, page=1, per_page=20):
        """
        Get commissions for an agent
        
        Args:
            agent_id: ID of the agent
            status: Filter by status (optional)
            page: Page number
            per_page: Items per page
            
        Returns:
            Paginated commissions
        """
        query = Commission.query.filter_by(agent_id=agent_id)
        
        if status:
            query = query.filter_by(status=status)
        
        pagination = query.order_by(Commission.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        return pagination
    
    @staticmethod
    def get_agent_commission_stats(agent_id):
        """
        Get commission statistics for an agent
        
        Args:
            agent_id: ID of the agent
            
        Returns:
            Dictionary with statistics
        """
        try:
            agent = Agent.query.get(agent_id)
            if not agent:
                return None
            
            # Get commission counts by status
            pending_count = Commission.query.filter_by(
                agent_id=agent_id,
                status='pending'
            ).count()
            
            approved_count = Commission.query.filter_by(
                agent_id=agent_id,
                status='approved'
            ).count()
            
            paid_count = Commission.query.filter_by(
                agent_id=agent_id,
                status='paid'
            ).count()
            
            # Get total amounts
            pending_amount = db.session.query(
                db.func.sum(Commission.commission_amount)
            ).filter(
                Commission.agent_id == agent_id,
                Commission.status == 'pending'
            ).scalar() or Decimal('0')
            
            approved_amount = db.session.query(
                db.func.sum(Commission.commission_amount)
            ).filter(
                Commission.agent_id == agent_id,
                Commission.status == 'approved'
            ).scalar() or Decimal('0')
            
            paid_amount = db.session.query(
                db.func.sum(Commission.commission_amount)
            ).filter(
                Commission.agent_id == agent_id,
                Commission.status == 'paid'
            ).scalar() or Decimal('0')
            
            return {
                'agent_id': agent_id,
                'commission_rate': float(agent.commission_rate),
                'pending_balance': float(agent.pending_balance),
                'total_earned': float(agent.total_earned),
                'total_withdrawn': float(agent.total_withdrawn),
                'total_sales': float(agent.total_sales),
                'pending': {
                    'count': pending_count,
                    'amount': float(pending_amount)
                },
                'approved': {
                    'count': approved_count,
                    'amount': float(approved_amount)
                },
                'paid': {
                    'count': paid_count,
                    'amount': float(paid_amount)
                },
                'total_commissions': pending_count + approved_count + paid_count,
                'total_commission_amount': float(pending_amount + approved_amount + paid_amount)
            }
            
        except Exception as e:
            logger.error(f"Error getting commission stats: {str(e)}")
            return None
