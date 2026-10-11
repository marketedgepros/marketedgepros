"""
Wallet model for managing user balances
"""
from datetime import datetime
from src.database import db, TimestampMixin


class Wallet(db.Model, TimestampMixin):
    """User wallet for managing balances"""
    
    __tablename__ = 'wallets'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, unique=True)
    
    # Balance types
    main_balance = db.Column(db.Numeric(12, 2), default=0.0, nullable=False)  # Main trading balance
    commission_balance = db.Column(db.Numeric(12, 2), default=0.0, nullable=False)  # Agent commissions
    bonus_balance = db.Column(db.Numeric(12, 2), default=0.0, nullable=False)  # Bonus/promo balance
    
    # Total available for withdrawal
    @property
    def total_balance(self):
        return float(self.main_balance) + float(self.commission_balance)
    
    # Metadata
    last_transaction_at = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    notes = db.Column(db.Text)
    
    # Relationships
    user = db.relationship('User', backref=db.backref('wallet', uselist=False))
    
    # Indexes
    __table_args__ = (
        db.Index('ix_wallet_user_id', 'user_id'),
    )
    
    def add_funds(self, amount, balance_type='main', description=None, reference_type=None, reference_id=None, created_by=None):
        """Legacy mutation is disabled until a reconciled source-bound ledger exists."""
        from src.services.wallet_service import WalletLedgerNotConfigured
        raise WalletLedgerNotConfigured()
    
    def deduct_funds(self, amount, balance_type='main', description=None, reference_type=None, reference_id=None, created_by=None):
        """Legacy mutation is disabled until a reconciled source-bound ledger exists."""
        from src.services.wallet_service import WalletLedgerNotConfigured
        raise WalletLedgerNotConfigured()
    
    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'main_balance': float(self.main_balance),
            'commission_balance': float(self.commission_balance),
            'bonus_balance': float(self.bonus_balance),
            'total_balance': self.total_balance,
            'is_active': self.is_active,
            'last_transaction_at': self.last_transaction_at.isoformat() if self.last_transaction_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class Transaction(db.Model, TimestampMixin):
    """Transaction history for wallet operations"""
    
    __tablename__ = 'transactions'
    
    id = db.Column(db.Integer, primary_key=True)
    wallet_id = db.Column(db.Integer, db.ForeignKey('wallets.id'), nullable=False)
    
    # Transaction details
    type = db.Column(db.String(50), nullable=False)  # deposit, withdrawal, commission, bonus, adjustment
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    balance_type = db.Column(db.String(20), default='main', nullable=False)  # main, commission, bonus
    
    # Balance before/after
    balance_before = db.Column(db.Numeric(12, 2), nullable=False)
    balance_after = db.Column(db.Numeric(12, 2), nullable=False)
    
    # Reference
    reference_type = db.Column(db.String(50))  # withdrawal, commission, challenge, etc.
    reference_id = db.Column(db.Integer)
    
    # Metadata
    description = db.Column(db.String(255))
    notes = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    # Relationships
    wallet = db.relationship('Wallet', backref='transactions')
    creator = db.relationship('User', foreign_keys=[created_by])
    
    # Indexes
    __table_args__ = (
        db.Index('ix_transaction_wallet_id', 'wallet_id'),
        db.Index('ix_transaction_type', 'type'),
        db.Index('ix_transaction_created_at', 'created_at'),
    )
    
    def to_dict(self):
        """Convert to dictionary"""
        return {
            'id': self.id,
            'wallet_id': self.wallet_id,
            'type': self.type,
            'amount': float(self.amount),
            'balance_type': self.balance_type,
            'balance_before': float(self.balance_before),
            'balance_after': float(self.balance_after),
            'reference_type': self.reference_type,
            'reference_id': self.reference_id,
            'description': self.description,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

