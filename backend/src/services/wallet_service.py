"""Read-only compatibility boundary for the legacy wallet tables.

The legacy wallet/transaction schema has no reconciled, atomic ledger protocol.
It may be inspected as unverified historical data, but it must not be mutated by
this service until such a protocol is configured and reviewed.
"""
from decimal import Decimal

from src.database import db
from src.models.user import User
from src.models.wallet import Transaction, Wallet


class WalletLedgerNotConfigured(ValueError):
    """Raised before any legacy wallet mutation is looked up or attempted."""

    code = 'WALLET_LEDGER_NOT_CONFIGURED'
    status = 503

    def __init__(self):
        super().__init__('Wallet ledger is not configured')


class WalletNotFound(ValueError):
    """The requested user has no existing legacy wallet record."""

    code = 'WALLET_NOT_FOUND'
    status = 404

    def __init__(self):
        super().__init__('Wallet not found')


class WalletService:
    """Read-only access to explicitly existing legacy wallet records."""

    _BALANCE_TYPES = frozenset({'main', 'commission', 'bonus'})
    _MAX_HISTORY_LIMIT = 100
    _MAX_HISTORY_OFFSET = 10_000

    @staticmethod
    def _require_existing_user_id(user_id):
        # Reject ambiguous coercions before SQL.  A missing/invalid legacy wallet
        # must never be inferred to mean a verified zero balance.
        if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
            raise WalletNotFound()

    @classmethod
    def _validate_balance_type(cls, balance_type, *, allow_total=False):
        accepted = cls._BALANCE_TYPES | ({'total'} if allow_total else set())
        if not isinstance(balance_type, str) or balance_type not in accepted:
            raise ValueError('Invalid balance type')

    @staticmethod
    def _as_decimal(value):
        """Preserve database numeric values without using legacy float arithmetic."""
        return value if isinstance(value, Decimal) else Decimal(str(value))

    @staticmethod
    def _mutation_refused():
        # This is intentionally the first operation in every public mutator.
        # In particular it performs no lookup, flush, commit, provider call, or
        # validation that could accidentally touch legacy financial state.
        raise WalletLedgerNotConfigured()

    @classmethod
    def get_or_create_wallet(cls, user_id):
        """Compatibility name: return an exact existing owned wallet only.

        The method intentionally does not create a record despite its historical
        name.  Joining the owner prevents an orphan legacy row from being treated
        as a user wallet.
        """
        cls._require_existing_user_id(user_id)
        # A compatibility read must not flush an unrelated caller's pending
        # legacy state merely as a side effect of looking at a wallet.
        with db.session.no_autoflush:
            wallet = (
                db.session.query(Wallet)
                .join(User, Wallet.user_id == User.id)
                .filter(Wallet.user_id == user_id, User.id == user_id)
                .one_or_none()
            )
        if wallet is None:
            raise WalletNotFound()
        return wallet

    @classmethod
    def get_balance(cls, user_id, balance_type='main'):
        """Return a raw ``Decimal`` legacy value; it is not a payment assertion."""
        cls._validate_balance_type(balance_type, allow_total=True)
        wallet = cls.get_or_create_wallet(user_id)
        if balance_type == 'main':
            return cls._as_decimal(wallet.main_balance)
        if balance_type == 'commission':
            return cls._as_decimal(wallet.commission_balance)
        if balance_type == 'bonus':
            return cls._as_decimal(wallet.bonus_balance)
        # ``total`` is only a display aggregate of the two historical columns;
        # it is deliberately not an availability or withdrawal-rights decision.
        return cls._as_decimal(wallet.main_balance) + cls._as_decimal(wallet.commission_balance)

    @classmethod
    def add_funds(cls, user_id, amount, balance_type='main', description=None,
                  reference_type=None, reference_id=None, created_by=None):
        cls._mutation_refused()

    @classmethod
    def deduct_funds(cls, user_id, amount, balance_type='main', description=None,
                     reference_type=None, reference_id=None, created_by=None):
        cls._mutation_refused()

    @classmethod
    def transfer_funds(cls, from_user_id, to_user_id, amount, balance_type='main',
                       description=None, reference_type=None, reference_id=None):
        cls._mutation_refused()

    @classmethod
    def get_transaction_history(cls, user_id, limit=50, offset=0, balance_type=None):
        """Read bounded historical entries without creating a wallet or a zero."""
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= cls._MAX_HISTORY_LIMIT:
            raise ValueError('Invalid history limit')
        if not isinstance(offset, int) or isinstance(offset, bool) or not 0 <= offset <= cls._MAX_HISTORY_OFFSET:
            raise ValueError('Invalid history offset')
        if balance_type is not None:
            cls._validate_balance_type(balance_type)

        with db.session.no_autoflush:
            wallet = cls.get_or_create_wallet(user_id)
            query = Transaction.query.filter(Transaction.wallet_id == wallet.id)
            if balance_type is not None:
                query = query.filter(Transaction.balance_type == balance_type)
            return (
                query.order_by(Transaction.created_at.desc(), Transaction.id.desc())
                .limit(limit)
                .offset(offset)
                .all()
            )

    @classmethod
    def adjust_balance(cls, user_id, amount, balance_type='main', description=None, created_by=None):
        cls._mutation_refused()
