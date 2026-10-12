"""
Payment Approval Service
Handles cash and free payment approval workflow
"""
from datetime import datetime
import logging
from src.database import db
from src.models import PaymentApprovalRequest, Challenge, Payment, User
from src.services.email_service import EmailService
from src.services.affiliate_financial_boundary import refuse_unverified_affiliate_mutation


class PaymentApprovalSettlementNotConfigured(RuntimeError):
    """Legacy approval operations have no verified settlement command."""


class PaymentApprovalService:
    """Service for managing payment approvals"""
    
    @staticmethod
    def can_use_cash_payment(user):
        """
        Check if user can create cash payments
        Only Super Admin (supermaster) and Master can use cash payment
        """
        return user.role in ['supermaster', 'master']
    
    @staticmethod
    def can_create_free_account(user):
        """
        Check if user can create free accounts
        Only Super Admin (supermaster) can create completely free accounts
        """
        return user.role == 'supermaster'
    
    @staticmethod
    def create_approval_request(challenge_id, payment_id, requested_by_id, requested_for_id, 
                               amount, payment_type):
        """Refuse legacy cash/free settlement before any validation or effect.

        This approval workflow cannot establish affiliate settlement authority.
        It remains unavailable until a verified settlement/identity/ledger path
        is introduced. Read-only queries and rejection handling are unchanged.
        """
        refuse_unverified_affiliate_mutation()
    
    @staticmethod
    def approve_request(approval_request_id, admin_id, admin_notes=None):
        """Refuse legacy approval before any lookup, activation, or payment write.

        In particular, challenge activation and payment completion must never be
        performed when the related commission/settlement cannot be verified.
        """
        refuse_unverified_affiliate_mutation()
    
    @staticmethod
    def reject_request(approval_request_id, admin_id, rejection_reason, admin_notes=None):
        """Refuse legacy rejection before any lookup, write, or notification.

        The historical path changes a challenge/payment and sends email without a
        verified settlement command.  It must therefore remain unavailable even
        when this service is invoked outside its HTTP route.
        """
        raise PaymentApprovalSettlementNotConfigured(
            'Order settlement is not configured'
        )

    @staticmethod
    def reject_unavailable_response():
        """HTTP boundary after JWT/role/CSRF decorators and before body parsing."""
        from flask import jsonify
        return jsonify({
            'error': 'Order settlement is not configured',
            'code': 'ORDER_SETTLEMENT_NOT_CONFIGURED',
        }), 503
    
    @staticmethod
    def get_pending_requests():
        """Get all pending approval requests"""
        return PaymentApprovalRequest.query.filter_by(status='pending').order_by(
            PaymentApprovalRequest.created_at.desc()
        ).all()
    
    @staticmethod
    def get_request_by_id(request_id):
        """Get approval request by ID"""
        return PaymentApprovalRequest.query.get(request_id)
    
    @staticmethod
    def get_requests_by_requester(requester_id):
        """Get all approval requests created by a specific user"""
        return PaymentApprovalRequest.query.filter_by(
            requested_by=requester_id
        ).order_by(PaymentApprovalRequest.created_at.desc()).all()
    
    @staticmethod
    def _notify_super_admins(approval_request):
        """Send notification to all Super Admins about new approval request"""
        try:
            # Get all Super Admins
            super_admins = User.query.filter_by(role='supermaster', is_active=True).all()
            
            requester = User.query.get(approval_request.requested_by)
            trader = User.query.get(approval_request.requested_for)
            
            for admin in super_admins:
                EmailService.send_payment_approval_notification(
                    admin_email=admin.email,
                    admin_name=admin.first_name,
                    requester_name=f"{requester.first_name} {requester.last_name}",
                    trader_name=f"{trader.first_name} {trader.last_name}",
                    amount=float(approval_request.amount),
                    payment_type=approval_request.payment_type,
                    request_id=approval_request.id
                )
        except Exception as e:
            # Log error but don't fail the request creation
            logging.error(f"Error sending notification to Super Admins: {str(e)}", exc_info=True)
    
    @staticmethod
    def _notify_approval(approval_request, approved=True):
        """Send notification about approval/rejection decision"""
        try:
            requester = User.query.get(approval_request.requested_by)
            trader = User.query.get(approval_request.requested_for)
            
            if approved:
                # Notify requester (Master/Admin)
                EmailService.send_payment_approved_notification(
                    email=requester.email,
                    name=requester.first_name,
                    trader_name=f"{trader.first_name} {trader.last_name}",
                    amount=float(approval_request.amount),
                    payment_type=approval_request.payment_type
                )
                
                # Notify trader
                EmailService.send_challenge_activated_notification(
                    email=trader.email,
                    name=trader.first_name,
                    challenge_id=approval_request.challenge_id
                )
            else:
                # Notify requester about rejection
                EmailService.send_payment_rejected_notification(
                    email=requester.email,
                    name=requester.first_name,
                    trader_name=f"{trader.first_name} {trader.last_name}",
                    amount=float(approval_request.amount),
                    payment_type=approval_request.payment_type,
                    reason=approval_request.rejection_reason
                )
        except Exception as e:
            # Log error but don't fail the approval/rejection
            logging.error(f"Error sending approval/rejection notification: {str(e)}", exc_info=True)
