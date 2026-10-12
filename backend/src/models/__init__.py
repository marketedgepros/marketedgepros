"""
Models package
"""
from src.models.user import User, EmailVerificationToken, PasswordResetToken
from src.models.verification_attempt import VerificationAttempt
from src.models.tenant import Tenant
from src.models.trading_program import TradingProgram, ProgramAddOn, Challenge
from src.models.lead import Lead, LeadActivity, LeadNote
from src.models.agent import Agent
from src.models.referral import Referral
from src.models.commission import Commission
from src.models.withdrawal import Withdrawal
from src.models.trade import Trade
from src.models.payment import Payment
from src.models.payment_approval import PaymentApprovalRequest
from src.models.wallet import Wallet, Transaction
from src.models.notification import Notification, NotificationPreference, EmailQueue
from src.models.support_article import SupportArticle
from src.models.affiliate_lifecycle import (
    AffiliateCommissionAward,
    AffiliateIdentityEvidence,
    AffiliateOrderAttribution,
    AffiliatePayoutCommand,
)

__all__ = [
    'User',
    'EmailVerificationToken',
    'PasswordResetToken',
    'VerificationAttempt',
    'Tenant',
    'TradingProgram',
    'ProgramAddOn',
    'Challenge',
    'Agent',
    'Referral',
    'Commission',
    'Withdrawal',
    'Trade',
    'Payment',
    'PaymentApprovalRequest',
    'Lead',
    'LeadActivity',
    'LeadNote',
    'Wallet',
    'Transaction',
    'Notification',
    'NotificationPreference',
    'EmailQueue',
    'SupportArticle',
    'AccountScaling',
    'ScalingTier',
    'AffiliateIdentityEvidence',
    'AffiliateOrderAttribution',
    'AffiliateCommissionAward',
    'AffiliatePayoutCommand',
]

# Alias for backward compatibility
Program = TradingProgram

from src.models.token_blacklist import TokenBlacklist
from src.models.payout_request import PayoutRequest
from src.models.account_scaling import AccountScaling, ScalingTier
