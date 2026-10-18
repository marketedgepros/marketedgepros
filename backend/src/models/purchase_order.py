"""Immutable purchase quote; not a payment, wallet deposit or trading entitlement."""
from datetime import datetime
from decimal import Decimal
from sqlalchemy import event
from src.database import db


class PurchaseOrder(db.Model):
    __tablename__ = 'purchase_orders'
    id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    tenant_id = db.Column(db.Integer, db.ForeignKey('tenants.id'), nullable=False)
    program_id = db.Column(db.Integer, db.ForeignKey('trading_programs.id'), nullable=False)
    idempotency_key = db.Column(db.String(128), nullable=False)
    request_hash = db.Column(db.String(64), nullable=False)
    snapshot_hash = db.Column(db.String(64), nullable=False)
    snapshot_json = db.Column(db.Text, nullable=False)
    amount_minor = db.Column(db.BigInteger, nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    state = db.Column(db.String(20), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (
        db.UniqueConstraint('user_id', 'idempotency_key', name='uq_purchase_orders_user_key'),
        db.CheckConstraint('amount_minor > 0 AND amount_minor <= 9999999999', name='ck_purchase_orders_amount'),
        db.CheckConstraint("currency = 'USD'", name='ck_purchase_orders_currency'),
        db.CheckConstraint("state = 'quoted'", name='ck_purchase_orders_state'),
        db.CheckConstraint('length(request_hash) = 64 AND length(snapshot_hash) = 64', name='ck_purchase_orders_hash_length'),
        db.Index('ix_purchase_orders_user_created', 'user_id', 'created_at'),
        db.Index('ix_purchase_orders_tenant', 'tenant_id'),
    )

    def to_dict(self):
        import json
        return {'id': self.id, 'program_id': self.program_id,
                'user_id': self.user_id, 'tenant_id': self.tenant_id,
                'amount_minor': self.amount_minor, 'amount': format(Decimal(self.amount_minor) / 100, '.2f'),
                'currency': self.currency, 'state': self.state, 'paid': False,
                'snapshot': json.loads(self.snapshot_json), 'snapshot_hash': self.snapshot_hash,
                'created_at': self.created_at.isoformat() if self.created_at else None}


@event.listens_for(PurchaseOrder, 'before_update')
@event.listens_for(PurchaseOrder, 'before_delete')
def _immutable_order(mapper, connection, target):
    raise ValueError('Purchase order snapshots are immutable; use a separate verified event')
