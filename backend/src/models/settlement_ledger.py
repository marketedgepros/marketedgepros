"""Append-only receipt journal; not customer wallet balances or entitlement."""
from datetime import datetime
from sqlalchemy import event
from src.database import db


class PaymentEventReceipt(db.Model):
    __tablename__ = 'payment_event_receipts'
    id = db.Column(db.String(36), primary_key=True)
    source = db.Column(db.String(64), nullable=False)
    merchant_context = db.Column(db.String(128), nullable=False)
    event_key = db.Column(db.String(128), nullable=False)
    order_id = db.Column(db.String(36), db.ForeignKey('purchase_orders.id', name='fk_receipt_order'), nullable=False)
    amount_minor = db.Column(db.BigInteger, nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    payload_hash = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (
        db.UniqueConstraint('source', 'merchant_context', 'event_key', name='uq_payment_event_identity'),
        db.CheckConstraint('amount_minor > 0 AND amount_minor <= 9999999999', name='ck_receipt_amount'),
        db.CheckConstraint("currency = 'USD'", name='ck_receipt_currency'),
        db.CheckConstraint('length(payload_hash) = 64', name='ck_receipt_hash'),
        db.Index('ix_receipt_order', 'order_id'),
    )


class SettlementJournal(db.Model):
    __tablename__ = 'settlement_journals'
    id = db.Column(db.String(36), primary_key=True)
    receipt_id = db.Column(db.String(36), db.ForeignKey('payment_event_receipts.id', name='fk_journal_receipt'), nullable=False)
    order_id = db.Column(db.String(36), db.ForeignKey('purchase_orders.id', name='fk_journal_order'), nullable=False)
    amount_minor = db.Column(db.BigInteger, nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    __table_args__ = (
        db.UniqueConstraint('receipt_id', name='uq_journal_receipt'),
        db.UniqueConstraint('order_id', name='uq_journal_order'),
        db.CheckConstraint('amount_minor > 0 AND amount_minor <= 9999999999', name='ck_journal_amount'),
        db.CheckConstraint("currency = 'USD'", name='ck_journal_currency'),
    )


class SettlementEntry(db.Model):
    __tablename__ = 'settlement_entries'
    id = db.Column(db.String(36), primary_key=True)
    journal_id = db.Column(db.String(36), db.ForeignKey('settlement_journals.id', name='fk_entry_journal'), nullable=False)
    line_number = db.Column(db.Integer, nullable=False)
    account_code = db.Column(db.String(64), nullable=False)
    side = db.Column(db.String(6), nullable=False)
    amount_minor = db.Column(db.BigInteger, nullable=False)
    __table_args__ = (
        db.UniqueConstraint('journal_id', 'line_number', name='uq_journal_line'),
        db.CheckConstraint('line_number IN (1, 2)', name='ck_entry_line'),
        db.CheckConstraint('amount_minor > 0 AND amount_minor <= 9999999999', name='ck_entry_amount'),
        db.CheckConstraint("(line_number = 1 AND side = 'debit' AND account_code = 'provider_clearing') OR "
                           "(line_number = 2 AND side = 'credit' AND account_code = 'unapplied_order_receipts')", name='ck_entry_account'),
        db.Index('ix_entry_journal', 'journal_id'),
    )


def _immutable_ledger(mapper, connection, target):
    raise ValueError('Settlement evidence is immutable; corrections require a separate source event')


for _model in (PaymentEventReceipt, SettlementJournal, SettlementEntry):
    event.listen(_model, 'before_update', _immutable_ledger)
    event.listen(_model, 'before_delete', _immutable_ledger)
