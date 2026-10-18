"""Synthetic affiliate lifecycle mappings; no payout provider or wallet authority.

The migration owns immutable evidence, direct-SQL source binding, and transition rules.
These mappings deliberately expose storage shape only; lifecycle service operations use
bounded raw SQL and the PostgreSQL trigger state machines.
"""
from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.dialects.postgresql import JSONB

from src.database import db


_POLICY_CHECK = "jsonb_typeof(policy_json) = 'object' AND policy_json ?& ARRAY['version','rate_basis_points','basis','currency','hold_seconds','minimum_payout_minor','rounding','mode'] AND (policy_json - 'version' - 'rate_basis_points' - 'basis' - 'currency' - 'hold_seconds' - 'minimum_payout_minor' - 'rounding' - 'mode') = '{}'::jsonb AND jsonb_typeof(policy_json->'version') = 'string' AND length(policy_json->>'version') BETWEEN 1 AND 64 AND (policy_json->>'version') ~ '^[A-Za-z0-9_.:-]+$' AND jsonb_typeof(policy_json->'rate_basis_points') = 'number' AND (policy_json->>'rate_basis_points') ~ '^[0-9]+$' AND (policy_json->>'rate_basis_points')::bigint BETWEEN 1 AND 10000 AND policy_json->'basis' = '\"paid_order_total\"'::jsonb AND policy_json->'currency' = '\"USD\"'::jsonb AND jsonb_typeof(policy_json->'hold_seconds') = 'number' AND (policy_json->>'hold_seconds') ~ '^[0-9]+$' AND (policy_json->>'hold_seconds')::bigint BETWEEN 0 AND 31536000 AND jsonb_typeof(policy_json->'minimum_payout_minor') = 'number' AND (policy_json->>'minimum_payout_minor') ~ '^[0-9]+$' AND (policy_json->>'minimum_payout_minor')::bigint BETWEEN 1 AND 9999999999 AND policy_json->'rounding' = '\"floor\"'::jsonb AND policy_json->'mode' = '\"synthetic\"'::jsonb"


class AffiliateIdentityEvidence(db.Model):
    __tablename__ = "affiliate_identity_evidence"

    id = db.Column(db.String(36), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id", name="fk_affiliate_identity_evidence_user"), nullable=False)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id", name="fk_affiliate_identity_evidence_tenant"), nullable=False)
    subject_hash = db.Column(db.String(64), nullable=False)
    source = db.Column(db.String(16), nullable=False)
    event_key = db.Column(db.String(128), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False)

    __table_args__ = (
        db.UniqueConstraint("source", "event_key", name="uq_affiliate_identity_evidence_source_event"),
        db.UniqueConstraint("tenant_id", "user_id", name="uq_affiliate_identity_evidence_tenant_user"),
        db.CheckConstraint("id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'", name='ck_affiliate_identity_evidence_id').ddl_if(dialect='postgresql'),
        db.CheckConstraint('user_id > 0 AND tenant_id > 0', name='ck_affiliate_identity_evidence_user').ddl_if(dialect='postgresql'),
        db.CheckConstraint("subject_hash ~ '^[0-9a-f]{64}$'", name='ck_affiliate_identity_evidence_subject_hash').ddl_if(dialect='postgresql'),
        db.CheckConstraint("source = 'synthetic'", name='ck_affiliate_identity_evidence_source').ddl_if(dialect='postgresql'),
        db.CheckConstraint("event_key ~ '^[A-Za-z0-9_.:-]{1,128}$'", name='ck_affiliate_identity_evidence_event_key').ddl_if(dialect='postgresql'),
    )


class AffiliateOrderAttribution(db.Model):
    __tablename__ = "affiliate_order_attributions"

    id = db.Column(db.String(36), primary_key=True)
    order_id = db.Column(db.String(36), db.ForeignKey("purchase_orders.id", name="fk_affiliate_order_attributions_order"), nullable=False)
    affiliate_user_id = db.Column(db.Integer, db.ForeignKey("users.id", name="fk_affiliate_order_attributions_affiliate_user"), nullable=False)
    buyer_evidence_id = db.Column(db.String(36), db.ForeignKey("affiliate_identity_evidence.id", name="fk_affiliate_order_attributions_buyer_evidence"), nullable=False)
    affiliate_evidence_id = db.Column(db.String(36), db.ForeignKey("affiliate_identity_evidence.id", name="fk_affiliate_order_attributions_affiliate_evidence"), nullable=False)
    policy_hash = db.Column(db.String(64), nullable=False)
    policy_json = db.Column(db.JSON().with_variant(JSONB(), 'postgresql'), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False)

    __table_args__ = (
        db.UniqueConstraint("order_id", name="uq_affiliate_order_attributions_order"),
        db.CheckConstraint("id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'", name='ck_affiliate_order_attributions_id').ddl_if(dialect='postgresql'),
        db.CheckConstraint("order_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' AND buyer_evidence_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' AND affiliate_evidence_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' AND affiliate_user_id > 0", name='ck_affiliate_order_attributions_references').ddl_if(dialect='postgresql'),
        db.CheckConstraint("policy_hash ~ '^[0-9a-f]{64}$'", name='ck_affiliate_order_attributions_policy_hash').ddl_if(dialect='postgresql'),
        db.CheckConstraint('jsonb_typeof(policy_json) = \'object\' AND policy_json ?& ARRAY[\'version\',\'rate_basis_points\',\'basis\',\'currency\',\'hold_seconds\',\'minimum_payout_minor\',\'rounding\',\'mode\'] AND (policy_json - \'version\' - \'rate_basis_points\' - \'basis\' - \'currency\' - \'hold_seconds\' - \'minimum_payout_minor\' - \'rounding\' - \'mode\') = \'{}\'::jsonb AND jsonb_typeof(policy_json->\'version\') = \'string\' AND length(policy_json->>\'version\') BETWEEN 1 AND 64 AND (policy_json->>\'version\') ~ \'^[A-Za-z0-9_.:-]+$\' AND jsonb_typeof(policy_json->\'rate_basis_points\') = \'number\' AND (policy_json->>\'rate_basis_points\') ~ \'^[0-9]+$\' AND (policy_json->>\'rate_basis_points\')::bigint BETWEEN 1 AND 10000 AND policy_json->\'basis\' = \'"paid_order_total"\'::jsonb AND policy_json->\'currency\' = \'"USD"\'::jsonb AND jsonb_typeof(policy_json->\'hold_seconds\') = \'number\' AND (policy_json->>\'hold_seconds\') ~ \'^[0-9]+$\' AND (policy_json->>\'hold_seconds\')::bigint BETWEEN 0 AND 31536000 AND jsonb_typeof(policy_json->\'minimum_payout_minor\') = \'number\' AND (policy_json->>\'minimum_payout_minor\') ~ \'^[0-9]+$\' AND (policy_json->>\'minimum_payout_minor\')::bigint BETWEEN 1 AND 9999999999 AND policy_json->\'rounding\' = \'"floor"\'::jsonb AND policy_json->\'mode\' = \'"synthetic"\'::jsonb', name='ck_affiliate_order_attributions_policy').ddl_if(dialect='postgresql'),
    )


class AffiliateCommissionAward(db.Model):
    __tablename__ = "affiliate_commission_awards"

    id = db.Column(db.String(36), primary_key=True)
    attribution_id = db.Column(db.String(36), db.ForeignKey("affiliate_order_attributions.id", name="fk_affiliate_commission_awards_attribution"), nullable=False)
    journal_id = db.Column(db.String(36), db.ForeignKey("settlement_journals.id", name="fk_affiliate_commission_awards_journal"), nullable=False)
    amount_minor = db.Column(db.BigInteger, nullable=False)
    state = db.Column(db.String(16), nullable=False)
    review_open = db.Column(db.Boolean, nullable=False)
    release_at = db.Column(db.DateTime(timezone=True), nullable=False)
    reversal_event_key = db.Column(db.String(128), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False)

    __table_args__ = (
        db.UniqueConstraint("attribution_id", name="uq_affiliate_commission_awards_attribution"),
        db.UniqueConstraint("journal_id", name="uq_affiliate_commission_awards_journal"),
        db.CheckConstraint("id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'", name='ck_affiliate_commission_awards_id').ddl_if(dialect='postgresql'),
        db.CheckConstraint("attribution_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' AND journal_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'", name='ck_affiliate_commission_awards_references').ddl_if(dialect='postgresql'),
        db.CheckConstraint('amount_minor >= 1 AND amount_minor <= 9999999999', name='ck_affiliate_commission_awards_amount').ddl_if(dialect='postgresql'),
        db.CheckConstraint("state IN ('held', 'available', 'reserved', 'paid', 'reversed')", name='ck_affiliate_commission_awards_state').ddl_if(dialect='postgresql'),
        db.CheckConstraint('updated_at >= created_at', name='ck_affiliate_commission_awards_times').ddl_if(dialect='postgresql'),
        db.CheckConstraint("(state = 'reversed' AND reversal_event_key IS NOT NULL AND reversal_event_key ~ '^[A-Za-z0-9_.:-]{1,128}$') OR (state <> 'reversed' AND reversal_event_key IS NULL)", name='ck_affiliate_commission_awards_reversal').ddl_if(dialect='postgresql'),
    )


class AffiliatePayoutCommand(db.Model):
    __tablename__ = "affiliate_payout_commands"

    id = db.Column(db.String(36), primary_key=True)
    award_id = db.Column(db.String(36), db.ForeignKey("affiliate_commission_awards.id", name="fk_affiliate_payout_commands_award"), nullable=False)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id", name="fk_affiliate_payout_commands_approved_by"), nullable=False)
    network_id = db.Column(db.String(64), nullable=False)
    asset_id = db.Column(db.String(64), nullable=False)
    recipient_hash = db.Column(db.String(64), nullable=False)
    amount_atomic = db.Column(db.Numeric(78, 0), nullable=False)
    quote_hash = db.Column(db.String(64), nullable=False)
    attempt_token = db.Column(db.String(36), nullable=True)
    transfer_key = db.Column(db.String(128), nullable=True)
    state = db.Column(db.String(16), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False)

    __table_args__ = (
        db.UniqueConstraint("award_id", name="uq_affiliate_payout_commands_award"),
        db.UniqueConstraint("network_id", "transfer_key", name="uq_affiliate_payout_commands_transfer"),
        db.CheckConstraint("id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'", name='ck_affiliate_payout_commands_id').ddl_if(dialect='postgresql'),
        db.CheckConstraint("award_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' AND approved_by > 0", name='ck_affiliate_payout_commands_award').ddl_if(dialect='postgresql'),
        db.CheckConstraint("network_id ~ '^[A-Za-z0-9_.:-]{1,64}$' AND asset_id ~ '^[A-Za-z0-9_.:-]{1,64}$'", name='ck_affiliate_payout_commands_identifiers').ddl_if(dialect='postgresql'),
        db.CheckConstraint("recipient_hash ~ '^[0-9a-f]{64}$' AND quote_hash ~ '^[0-9a-f]{64}$'", name='ck_affiliate_payout_commands_hashes').ddl_if(dialect='postgresql'),
        db.CheckConstraint('amount_atomic > 0', name='ck_affiliate_payout_commands_amount').ddl_if(dialect='postgresql'),
        db.CheckConstraint("state IN ('planned', 'dispatched', 'uncertain', 'confirmed')", name='ck_affiliate_payout_commands_state').ddl_if(dialect='postgresql'),
        db.CheckConstraint("(state = 'planned' AND attempt_token IS NULL AND transfer_key IS NULL) OR (state IN ('dispatched', 'uncertain') AND attempt_token IS NOT NULL AND attempt_token ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' AND transfer_key IS NULL) OR (state = 'confirmed' AND attempt_token IS NOT NULL AND transfer_key IS NOT NULL AND attempt_token ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' AND transfer_key ~ '^[A-Za-z0-9_.:-]{1,128}$')", name='ck_affiliate_payout_commands_shape').ddl_if(dialect='postgresql'),
        db.CheckConstraint('updated_at >= created_at', name='ck_affiliate_payout_commands_times').ddl_if(dialect='postgresql'),
    )


def _immutable_affiliate_evidence(mapper, connection, target):
    raise ValueError("Affiliate identity and attribution evidence are immutable")


for _model in (AffiliateIdentityEvidence, AffiliateOrderAttribution):
    event.listen(_model, "before_update", _immutable_affiliate_evidence)
    event.listen(_model, "before_delete", _immutable_affiliate_evidence)
