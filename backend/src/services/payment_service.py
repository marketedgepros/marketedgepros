from src.services.mt5_challenge_service import mt5_challenge_service
import asyncio
"""
Payment service using Stripe
"""
import stripe
from flask import current_app
from src.database import db
from src.models import Challenge
import logging

logger = logging.getLogger(__name__)


class PaymentService:
    """Payment service for handling Stripe payments"""
    
    @staticmethod
    def _get_stripe_key():
        """Get Stripe secret key"""
        api_key = current_app.config.get('STRIPE_SECRET_KEY')
        if api_key:
            stripe.api_key = api_key
        return api_key
    
    @staticmethod
    def _get_or_create_customer(user):
        """Get or create Stripe customer for user"""
        # Check if user has stripe_customer_id stored
        if hasattr(user, 'stripe_customer_id') and user.stripe_customer_id:
            try:
                # Verify customer exists
                customer = stripe.Customer.retrieve(user.stripe_customer_id)
                return customer.id
            except stripe.error.StripeError:
                # Customer doesn't exist, create new one
                pass
        
        # Create new customer
        try:
            customer = stripe.Customer.create(
                email=user.email,
                name=f"{user.first_name} {user.last_name}",
                metadata={
                    'user_id': user.id
                }
            )
            
            # Store customer ID (if user model supports it)
            if hasattr(user, 'stripe_customer_id'):
                user.stripe_customer_id = customer.id
                db.session.commit()
            
            return customer.id
        except stripe.error.StripeError as e:
            logger.error(f'Failed to create Stripe customer: {str(e)}')
            # Fallback: proceed without customer ID
            return None
    
    @staticmethod
    def create_payment_intent(challenge, user):
        """Create Stripe payment intent for challenge purchase"""
        if not PaymentService._get_stripe_key():
            logger.error('Stripe API key not configured')
            raise ValueError('Payment system not configured')
        
        try:
            # Calculate amount (in cents)
            amount = int(challenge.program.calculate_total_price(challenge.addons) * 100)
            
            # Get or create Stripe customer
            customer_id = PaymentService._get_or_create_customer(user)
            
            # Prepare payment intent parameters
            intent_params = {
                'amount': amount,
                'currency': 'usd',
                'metadata': {
                    'challenge_id': challenge.id,
                    'user_id': user.id,
                    'program_id': challenge.program_id,
                    'program_name': challenge.program.name
                },
                'description': f'MarketEdgePros - {challenge.program.name}',
                'receipt_email': user.email
            }
            
            # Add customer ID if available
            if customer_id:
                intent_params['customer'] = customer_id
            
            # Create payment intent
            intent = stripe.PaymentIntent.create(**intent_params)
            
            # Store payment intent ID
            challenge.payment_id = intent.id
            db.session.commit()
            
            logger.info(f'Payment intent created: {intent.id} for challenge {challenge.id}')
            
            return {
                'client_secret': intent.client_secret,
                'payment_intent_id': intent.id,
                'amount': amount / 100,
                'currency': 'usd'
            }
            
        except stripe.error.StripeError as e:
            logger.error(f'Stripe error: {str(e)}')
            raise ValueError(f'Payment error: {str(e)}')
        except Exception as e:
            logger.error(f'Payment intent creation failed: {str(e)}')
            raise ValueError('Failed to create payment')
    
    @staticmethod
    def confirm_payment(payment_intent_id):
        """Legacy activation unavailable until canonical settlement/provisioning."""
        # Do not activate from a mutable payment_id/status or continue after
        # failed MT5 provisioning. This service is not a verified entitlement
        # adapter, even when a Stripe key exists. Refuse before credentials,
        # provider retrieval, DB lookup, status mutation or commit.
        return {
            'status': 'error', 'confirmed': False,
            'code': 'ORDER_SETTLEMENT_NOT_CONFIGURED',
            'message': 'Verified settlement and MT5 provisioning are not configured',
        }

    @staticmethod
    def refund_payment(challenge, reason=None):
        """Refund payment for a challenge"""
        if not PaymentService._get_stripe_key():
            logger.error('Stripe API key not configured')
            raise ValueError('Payment system not configured')
        
        if not challenge.payment_id:
            raise ValueError('No payment found for this challenge')
        
        try:
            # Create refund
            refund = stripe.Refund.create(
                payment_intent=challenge.payment_id,
                reason=reason or 'requested_by_customer'
            )
            
            # Update challenge
            challenge.payment_status = 'refunded'
            challenge.status = 'cancelled'
            db.session.commit()
            
            logger.info(f'Refund created: {refund.id} for challenge {challenge.id}')
            
            return {
                'refund_id': refund.id,
                'amount': refund.amount / 100,
                'status': refund.status
            }
            
        except stripe.error.StripeError as e:
            logger.error(f'Stripe error: {str(e)}')
            raise ValueError(f'Refund error: {str(e)}')
        except Exception as e:
            logger.error(f'Refund failed: {str(e)}')
            raise ValueError('Failed to process refund')
    
    @staticmethod
    def handle_webhook(payload, sig_header):
        """Handle Stripe webhook events"""
        if not PaymentService._get_stripe_key():
            logger.error('Stripe API key not configured')
            return False
        
        webhook_secret = current_app.config.get('STRIPE_WEBHOOK_SECRET')
        if not webhook_secret:
            logger.error('Stripe webhook secret not configured')
            return False
        
        try:
            # Verify webhook signature
            event = stripe.Webhook.construct_event(
                payload, sig_header, webhook_secret
            )
            
            logger.info(f'Webhook received: {event.type}')
            
            # Handle different event types
            if event.type == 'payment_intent.succeeded':
                payment_intent = event.data.object
                PaymentService.confirm_payment(payment_intent.id)
                
            elif event.type == 'payment_intent.payment_failed':
                payment_intent = event.data.object
                challenge = Challenge.query.filter_by(payment_id=payment_intent.id).first()
                if challenge:
                    challenge.payment_status = 'failed'
                    db.session.commit()
                    logger.warning(f'Payment failed for challenge {challenge.id}')
            
            elif event.type == 'charge.refunded':
                charge = event.data.object
                payment_intent_id = charge.payment_intent
                challenge = Challenge.query.filter_by(payment_id=payment_intent_id).first()
                if challenge:
                    challenge.payment_status = 'refunded'
                    challenge.status = 'cancelled'
                    db.session.commit()
                    logger.info(f'Refund processed for challenge {challenge.id}')
            
            return True
            
        except ValueError as e:
            logger.error(f'Invalid webhook payload: {str(e)}')
            return False
        except stripe.error.SignatureVerificationError as e:
            logger.error(f'Invalid webhook signature: {str(e)}')
            return False
        except Exception as e:
            logger.error(f'Webhook handling failed: {str(e)}')
            return False
    
    @staticmethod
    def get_payment_status(payment_intent_id):
        """Get payment status from Stripe"""
        if not PaymentService._get_stripe_key():
            return None
        
        try:
            intent = stripe.PaymentIntent.retrieve(payment_intent_id)
            return {
                'status': intent.status,
                'amount': intent.amount / 100,
                'currency': intent.currency,
                'created': intent.created
            }
        except Exception as e:
            logger.error(f'Failed to get payment status: {str(e)}')
            return None
