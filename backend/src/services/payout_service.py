"""Fail-closed legacy payout service; no ledger/payment authority is configured.

Signatures are retained for compatibility. Each method refuses before accessing
caller objects, SQL, notifications or any external provider. Historical rows are
not modified. Source-bound synthetic rehearsal lives in separate protocols and
cannot enable this legacy API.
"""
from decimal import Decimal
from typing import Dict, List

from src.models.payout_request import PayoutRequest
from src.models.trading_program import TradingProgram
from src.models.user import User
from src.services.wallet_service import WalletLedgerNotConfigured


class PayoutService:
    """No legacy field may be treated as available funds or payment evidence."""

    @staticmethod
    def can_request_payout(user: User, program: TradingProgram) -> Dict:
        raise WalletLedgerNotConfigured()

    @staticmethod
    def request_payout(user: User, program: TradingProgram, amount: Decimal,
                       payment_method: str, payment_details: Dict = None) -> PayoutRequest:
        raise WalletLedgerNotConfigured()

    @staticmethod
    def approve_payout(payout_id: int, approver_id: int, notes: str = None) -> PayoutRequest:
        raise WalletLedgerNotConfigured()

    @staticmethod
    def reject_payout(payout_id: int, approver_id: int, reason: str) -> PayoutRequest:
        raise WalletLedgerNotConfigured()

    @staticmethod
    def mark_as_paid(payout_id: int, notes: str = None) -> PayoutRequest:
        raise WalletLedgerNotConfigured()

    @staticmethod
    def get_user_payouts(user_id: int, status: str = None) -> List[PayoutRequest]:
        raise WalletLedgerNotConfigured()

    @staticmethod
    def get_pending_payouts() -> List[PayoutRequest]:
        raise WalletLedgerNotConfigured()

    @staticmethod
    def get_payout_statistics(user_id: int = None) -> Dict:
        raise WalletLedgerNotConfigured()
