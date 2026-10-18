"""Durable NOWPayments checkout evidence, separate from legacy and synthetic settlement.

These rows record a bounded payment attempt and a verified recorded-purchase grant.
They never create a wallet credit, trading account, challenge, refund, payout, or
any other fulfilment side effect.
"""
from datetime import datetime

from sqlalchemy import event

from src.database import db


class CheckoutIntent(db.Model):
    __tablename__ = "checkout_intents"

    id = db.Column(db.String(36), primary_key=True)
    order_id = db.Column(db.String(36), db.ForeignKey("purchase_orders.id", name="fk_checkout_intents_order"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", name="fk_checkout_intents_user"), nullable=False)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id", name="fk_checkout_intents_tenant"), nullable=False)
    provider = db.Column(db.String(32), nullable=False)
    merchant_context = db.Column(db.String(64), nullable=False)
    command_key = db.Column(db.String(128), nullable=False)
    external_reference = db.Column(db.String(96), nullable=False)
    request_digest = db.Column(db.String(64), nullable=False)
    pay_currency = db.Column(db.String(32), nullable=False)
    network = db.Column(db.String(32), nullable=False)
    decimals = db.Column(db.Integer, nullable=False)
    outcome_currency = db.Column(db.String(32), nullable=False)
    policy_version = db.Column(db.String(64), nullable=False)
    state = db.Column(db.String(24), nullable=False, default="prepared")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)
    dispatch_reserved_at = db.Column(db.DateTime(timezone=True), nullable=True)
    last_refresh_at = db.Column(db.DateTime(timezone=True), nullable=True)

    __table_args__ = (
        db.UniqueConstraint("order_id", "provider", name="uq_checkout_intents_order_provider"),
        db.UniqueConstraint("order_id", "command_key", name="uq_checkout_intents_order_command"),
        db.UniqueConstraint("external_reference", name="uq_checkout_intents_external_reference"),
        db.CheckConstraint("provider = 'nowpayments'", name="ck_checkout_intents_provider"),
        db.CheckConstraint("user_id > 0 AND tenant_id > 0", name="ck_checkout_intents_owner"),
        db.CheckConstraint("length(request_digest) = 64", name="ck_checkout_intents_digest"),
        db.CheckConstraint("pay_currency = 'usdttrc20' AND network = 'TRC20' AND decimals = 6", name="ck_checkout_intents_currency_network"),
        db.CheckConstraint("state IN ('prepared','creating','awaiting_payment','creation_uncertain','processing','manual_review','paid','expired','failed')", name="ck_checkout_intents_state"),
        db.Index("ix_checkout_intents_owner", "user_id", "tenant_id", "created_at"),
    )


class NowPaymentsPaymentBinding(db.Model):
    __tablename__ = "nowpayments_payment_bindings"

    id = db.Column(db.String(36), primary_key=True)
    intent_id = db.Column(db.String(36), db.ForeignKey("checkout_intents.id", name="fk_nowpayments_bindings_intent"), nullable=False)
    order_id = db.Column(db.String(36), db.ForeignKey("purchase_orders.id", name="fk_nowpayments_bindings_order"), nullable=False)
    provider = db.Column(db.String(32), nullable=False)
    merchant_context = db.Column(db.String(64), nullable=False)
    provider_payment_id = db.Column(db.String(128), nullable=False)
    parent_payment_id = db.Column(db.String(128), nullable=True)
    response_digest = db.Column(db.String(64), nullable=False)
    price_amount = db.Column(db.String(80), nullable=False)
    price_currency = db.Column(db.String(3), nullable=False)
    pay_amount = db.Column(db.String(80), nullable=False)
    pay_currency = db.Column(db.String(32), nullable=False)
    network = db.Column(db.String(32), nullable=False)
    decimals = db.Column(db.Integer, nullable=False)
    pay_address = db.Column(db.String(256), nullable=False)
    memo = db.Column(db.String(128), nullable=True)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    initial_status = db.Column(db.String(24), nullable=False)
    fee_paid_by_user = db.Column(db.Boolean, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("intent_id", name="uq_nowpayments_bindings_intent"),
        db.UniqueConstraint("order_id", name="uq_nowpayments_bindings_order"),
        db.UniqueConstraint("provider", "merchant_context", "provider_payment_id", name="uq_nowpayments_binding_provider_payment"),
        db.CheckConstraint("provider = 'nowpayments'", name="ck_nowpayments_bindings_provider"),
        db.CheckConstraint("price_currency = 'USD'", name="ck_nowpayments_bindings_price_currency"),
        db.CheckConstraint("pay_currency = 'usdttrc20' AND network = 'TRC20' AND decimals = 6", name="ck_nowpayments_bindings_currency_network"),
        db.CheckConstraint("initial_status IN ('waiting','confirming','confirmed','sending','partially_paid','finished','failed','expired','refunded')", name="ck_nowpayments_bindings_status"),
        db.CheckConstraint("fee_paid_by_user IS FALSE", name="ck_nowpayments_bindings_fee"),
        db.CheckConstraint("length(response_digest) = 64", name="ck_nowpayments_bindings_digest"),
        db.Index("ix_nowpayments_bindings_payment", "provider_payment_id"),
    )


class NowPaymentsObservation(db.Model):
    __tablename__ = "nowpayments_observations"

    id = db.Column(db.String(36), primary_key=True)
    binding_id = db.Column(db.String(36), db.ForeignKey("nowpayments_payment_bindings.id", name="fk_nowpayments_observations_binding"), nullable=False)
    order_id = db.Column(db.String(36), db.ForeignKey("purchase_orders.id", name="fk_nowpayments_observations_order"), nullable=False)
    provider_payment_id = db.Column(db.String(128), nullable=False)
    payload_digest = db.Column(db.String(64), nullable=False)
    source = db.Column(db.String(16), nullable=False)
    status = db.Column(db.String(24), nullable=False)
    review_required = db.Column(db.Boolean, nullable=False)
    pay_amount = db.Column(db.String(80), nullable=True)
    actually_paid = db.Column(db.String(80), nullable=True)
    outcome_amount = db.Column(db.String(80), nullable=True)
    outcome_currency = db.Column(db.String(32), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("binding_id", "payload_digest", name="uq_nowpayments_observations_replay"),
        db.CheckConstraint("source IN ('ipn','refresh')", name="ck_nowpayments_observations_source"),
        db.CheckConstraint("length(payload_digest) = 64", name="ck_nowpayments_observations_digest"),
        db.Index("ix_nowpayments_observations_binding_created", "binding_id", "created_at"),
    )


class NowPaymentsVerifiedReceipt(db.Model):
    __tablename__ = "nowpayments_verified_receipts"

    id = db.Column(db.String(36), primary_key=True)
    order_id = db.Column(db.String(36), db.ForeignKey("purchase_orders.id", name="fk_nowpayments_receipts_order"), nullable=False)
    binding_id = db.Column(db.String(36), db.ForeignKey("nowpayments_payment_bindings.id", name="fk_nowpayments_receipts_binding"), nullable=False)
    observation_id = db.Column(db.String(36), db.ForeignKey("nowpayments_observations.id", name="fk_nowpayments_receipts_observation"), nullable=False)
    amount_minor = db.Column(db.BigInteger, nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    source = db.Column(db.String(32), nullable=False, default="nowpayments")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("order_id", name="uq_nowpayments_receipts_order"),
        db.UniqueConstraint("binding_id", name="uq_nowpayments_receipts_binding"),
        db.UniqueConstraint("observation_id", name="uq_nowpayments_receipts_observation"),
        db.CheckConstraint("amount_minor > 0 AND amount_minor <= 9999999999", name="ck_nowpayments_receipts_amount"),
        db.CheckConstraint("currency = 'USD' AND source = 'nowpayments'", name="ck_nowpayments_receipts_source"),
    )


class NowPaymentsSettlementJournal(db.Model):
    __tablename__ = "nowpayments_settlement_journals"

    id = db.Column(db.String(36), primary_key=True)
    receipt_id = db.Column(db.String(36), db.ForeignKey("nowpayments_verified_receipts.id", name="fk_nowpayments_journals_receipt"), nullable=False)
    order_id = db.Column(db.String(36), db.ForeignKey("purchase_orders.id", name="fk_nowpayments_journals_order"), nullable=False)
    amount_minor = db.Column(db.BigInteger, nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("receipt_id", name="uq_nowpayments_journals_receipt"),
        db.UniqueConstraint("order_id", name="uq_nowpayments_journals_order"),
        db.CheckConstraint("amount_minor > 0 AND amount_minor <= 9999999999", name="ck_nowpayments_journals_amount"),
        db.CheckConstraint("currency = 'USD'", name="ck_nowpayments_journals_currency"),
    )


class NowPaymentsSettlementEntry(db.Model):
    __tablename__ = "nowpayments_settlement_entries"

    id = db.Column(db.String(36), primary_key=True)
    journal_id = db.Column(db.String(36), db.ForeignKey("nowpayments_settlement_journals.id", name="fk_nowpayments_entries_journal"), nullable=False)
    line_number = db.Column(db.Integer, nullable=False)
    account_code = db.Column(db.String(64), nullable=False)
    side = db.Column(db.String(6), nullable=False)
    amount_minor = db.Column(db.BigInteger, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("journal_id", "line_number", name="uq_nowpayments_entries_line"),
        db.CheckConstraint("line_number IN (1,2)", name="ck_nowpayments_entries_line"),
        db.CheckConstraint("amount_minor > 0 AND amount_minor <= 9999999999", name="ck_nowpayments_entries_amount"),
        db.CheckConstraint("(line_number = 1 AND side = 'debit' AND account_code = 'provider_clearing') OR (line_number = 2 AND side = 'credit' AND account_code = 'unapplied_order_receipts')", name="ck_nowpayments_entries_account"),
    )


class OrderEntitlementGrant(db.Model):
    __tablename__ = "order_entitlement_grants"

    id = db.Column(db.String(36), primary_key=True)
    order_id = db.Column(db.String(36), db.ForeignKey("purchase_orders.id", name="fk_order_entitlement_grants_order"), nullable=False)
    receipt_id = db.Column(db.String(36), db.ForeignKey("nowpayments_verified_receipts.id", name="fk_order_entitlement_grants_receipt"), nullable=False)
    observation_id = db.Column(db.String(36), db.ForeignKey("nowpayments_observations.id", name="fk_order_entitlement_grants_observation"), nullable=False)
    source = db.Column(db.String(32), nullable=False, default="nowpayments")
    policy_version = db.Column(db.String(64), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint("order_id", name="uq_order_entitlement_grants_order"),
        db.UniqueConstraint("receipt_id", name="uq_order_entitlement_grants_receipt"),
        db.UniqueConstraint("observation_id", name="uq_order_entitlement_grants_observation"),
        db.CheckConstraint("source = 'nowpayments'", name="ck_order_entitlement_grants_source"),
    )


_IMMUTABLE = (
    NowPaymentsPaymentBinding,
    NowPaymentsObservation,
    NowPaymentsVerifiedReceipt,
    NowPaymentsSettlementJournal,
    NowPaymentsSettlementEntry,
    OrderEntitlementGrant,
)


def _immutable(mapper, connection, target):
    raise ValueError("Checkout payment evidence is immutable; record a new observation instead")


for _model in _IMMUTABLE:
    event.listen(_model, "before_update", _immutable)
    event.listen(_model, "before_delete", _immutable)


@event.listens_for(CheckoutIntent, "before_delete")
def _intent_no_delete(mapper, connection, target):
    raise ValueError("Checkout intents are durable and cannot be deleted")
