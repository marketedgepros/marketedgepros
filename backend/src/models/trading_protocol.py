"""Synthetic, local-only Stage5c protocol persistence models.

The PostgreSQL migration is authoritative for direct-SQL immutability, tenant/program
bindings, and command transitions.  Mapper listeners only provide an early guard for
accidental ORM mutation of immutable evidence rows.
"""
from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.dialects.postgresql import JSONB

from src.database import db


class TradingRuleSnapshot(db.Model):
    __tablename__ = "trading_rule_snapshots"

    id = db.Column(db.String(64), primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id", name="fk_trading_rule_snapshots_tenant"), nullable=False)
    program_id = db.Column(db.Integer, db.ForeignKey("trading_programs.id", name="fk_trading_rule_snapshots_program"), nullable=False)
    phase = db.Column(db.Integer, nullable=False)
    rules_version = db.Column(db.String(64), nullable=False)
    rules_digest = db.Column(db.String(64), nullable=False)
    canonical_rules = db.Column(JSONB, nullable=False)
    source = db.Column(db.String(16), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False)

    __table_args__ = (
        db.UniqueConstraint("tenant_id", "program_id", "phase", "rules_version", name="uq_trading_rule_snapshot_context"),
        db.CheckConstraint("id ~ '^[0-9a-f]{64}$'", name="ck_trading_rule_snapshot_id"),
        db.CheckConstraint("phase >= 1 AND phase <= 9", name="ck_trading_rule_snapshot_phase"),
        db.CheckConstraint("rules_version ~ '^[A-Za-z0-9._:-]{1,64}$'", name="ck_trading_rule_snapshot_rules_version"),
        db.CheckConstraint("rules_digest ~ '^[0-9a-f]{64}$'", name="ck_trading_rule_snapshot_digest"),
        db.CheckConstraint("jsonb_typeof(canonical_rules) = 'object' AND canonical_rules ?& ARRAY['schema_version','rules_version','program_id','phase','currency','currency_scale','initial_units','profit_target','daily_loss','total_loss','target_basis','daily_basis','daily_reference_basis','total_basis','total_drawdown_mode','loss_at_threshold_is_breach','target_at_threshold_is_met','timezone_name','reset_hour','reset_minute','reset_fold','maximum_age_seconds'] AND (canonical_rules - 'schema_version' - 'rules_version' - 'program_id' - 'phase' - 'currency' - 'currency_scale' - 'initial_units' - 'profit_target' - 'daily_loss' - 'total_loss' - 'target_basis' - 'daily_basis' - 'daily_reference_basis' - 'total_basis' - 'total_drawdown_mode' - 'loss_at_threshold_is_breach' - 'target_at_threshold_is_met' - 'timezone_name' - 'reset_hour' - 'reset_minute' - 'reset_fold' - 'maximum_age_seconds') = '{}'::jsonb", name="ck_trading_rule_snapshot_canonical"),
        db.CheckConstraint("source = 'synthetic'", name="ck_trading_rule_snapshot_source"),
    )


class TradingProvisionCommand(db.Model):
    __tablename__ = "trading_provision_commands"

    id = db.Column(db.String(36), primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id", name="fk_trading_provision_commands_tenant"), nullable=False)
    challenge_id = db.Column(db.Integer, db.ForeignKey("challenges.id", name="fk_trading_provision_commands_challenge"), nullable=False)
    phase = db.Column(db.Integer, nullable=False)
    provider_id = db.Column(db.String(64), nullable=False)
    rule_snapshot_id = db.Column(db.String(64), db.ForeignKey("trading_rule_snapshots.id", name="fk_trading_provision_commands_snapshot"), nullable=False)
    source = db.Column(db.String(16), nullable=False)
    status = db.Column(db.String(16), nullable=False)
    attempt_token = db.Column(db.String(36), nullable=True)
    account_id = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False)

    __table_args__ = (
        db.UniqueConstraint("tenant_id", "challenge_id", "phase", name="uq_trading_provision_command_context"),
        db.UniqueConstraint("provider_id", "account_id", name="uq_trading_provision_provider_account"),
        db.CheckConstraint("id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'", name="ck_trading_provision_command_id"),
        db.CheckConstraint("phase >= 1 AND phase <= 9", name="ck_trading_provision_command_phase"),
        db.CheckConstraint("provider_id ~ '^[A-Za-z0-9_.:-]{1,64}$'", name="ck_trading_provision_command_provider"),
        db.CheckConstraint("source = 'synthetic'", name="ck_trading_provision_command_source"),
        db.CheckConstraint("status IN ('planned', 'dispatched', 'uncertain', 'acknowledged')", name="ck_trading_provision_command_status"),
        db.CheckConstraint("(status = 'planned' AND attempt_token IS NULL AND account_id IS NULL) OR (status IN ('dispatched', 'uncertain') AND attempt_token IS NOT NULL AND account_id IS NULL) OR (status = 'acknowledged' AND attempt_token IS NOT NULL AND account_id IS NOT NULL)", name="ck_trading_provision_command_shape"),
        db.CheckConstraint("attempt_token IS NULL OR attempt_token ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'", name="ck_trading_provision_command_token"),
        db.CheckConstraint("account_id IS NULL OR account_id ~ '^[A-Za-z0-9_.:-]{1,64}$'", name="ck_trading_provision_command_account"),
        db.CheckConstraint("updated_at >= created_at", name="ck_trading_provision_command_times"),
    )


class TradingEventInbox(db.Model):
    __tablename__ = "trading_event_inbox"

    id = db.Column(db.String(36), primary_key=True)
    command_id = db.Column(db.String(36), db.ForeignKey("trading_provision_commands.id", name="fk_trading_event_inbox_command"), nullable=False)
    provider_id = db.Column(db.String(64), nullable=False)
    account_id = db.Column(db.String(64), nullable=False)
    event_id = db.Column(db.String(128), nullable=False)
    sequence = db.Column(db.BigInteger, nullable=False)
    payload_hash = db.Column(db.String(64), nullable=False)
    payload = db.Column(JSONB, nullable=False)
    received_at = db.Column(db.DateTime(timezone=True), nullable=False)

    __table_args__ = (
        db.UniqueConstraint("provider_id", "account_id", "event_id", name="uq_trading_event_inbox_event"),
        db.UniqueConstraint("provider_id", "account_id", "sequence", name="uq_trading_event_inbox_sequence"),
        db.CheckConstraint("id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'", name="ck_trading_event_inbox_id"),
        db.CheckConstraint("provider_id ~ '^[A-Za-z0-9_.:-]{1,64}$' AND account_id ~ '^[A-Za-z0-9_.:-]{1,64}$' AND event_id ~ '^[A-Za-z0-9_.:-]{1,128}$'", name="ck_trading_event_inbox_identity"),
        db.CheckConstraint("sequence > 0", name="ck_trading_event_inbox_sequence"),
        db.CheckConstraint("payload_hash ~ '^[0-9a-f]{64}$'", name="ck_trading_event_inbox_hash"),
        db.CheckConstraint("jsonb_typeof(payload) = 'object' AND payload ?& ARRAY['schema_version','source','local_only','observation'] AND (payload - 'schema_version' - 'source' - 'local_only' - 'observation') = '{}'::jsonb AND payload->'schema_version' = '1'::jsonb AND payload->'source' = '\"synthetic\"'::jsonb AND payload->'local_only' = 'true'::jsonb AND jsonb_typeof(payload->'observation') = 'object' AND payload->'observation' ?& ARRAY['tenant_id','challenge_id','provider_id','account_id','rules_digest','event_id','sequence','observed_at','currency','currency_scale','balance_units','equity_units','equity_includes_fees_and_swaps'] AND ((payload->'observation') - 'tenant_id' - 'challenge_id' - 'provider_id' - 'account_id' - 'rules_digest' - 'event_id' - 'sequence' - 'observed_at' - 'currency' - 'currency_scale' - 'balance_units' - 'equity_units' - 'equity_includes_fees_and_swaps') = '{}'::jsonb", name="ck_trading_event_inbox_payload"),
    )


def _immutable_protocol_evidence(mapper, connection, target):
    raise ValueError("Trading protocol evidence is immutable; create a new synthetic event instead")


for _model in (TradingRuleSnapshot, TradingEventInbox):
    event.listen(_model, "before_update", _immutable_protocol_evidence)
    event.listen(_model, "before_delete", _immutable_protocol_evidence)
