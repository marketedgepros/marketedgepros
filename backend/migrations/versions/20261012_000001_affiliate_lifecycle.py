"""Create isolated, synthetic affiliate-lifecycle persistence.

Revision ID: 20261012_000001
Revises: 20261011_000008

The migration is deliberately storage-only.  It does not configure a provider, wallet,
KYC authority, public endpoint, scheduler, seed row, or payout adapter.  PostgreSQL
triggers are the authority for direct-SQL immutability, frozen source binding, and the
one-way award/payout state machines.  Every online collision is proved before the first
DDL; downgrade proves empty, exclusively-owned objects before any non-CASCADE DROP.
"""
from __future__ import annotations

import re

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261012_000001"
down_revision = "20261011_000008"
branch_labels = None
depends_on = None

IDENTITY_TABLE = "affiliate_identity_evidence"
ATTRIBUTION_TABLE = "affiliate_order_attributions"
AWARD_TABLE = "affiliate_commission_awards"
COMMAND_TABLE = "affiliate_payout_commands"
TABLES = (IDENTITY_TABLE, ATTRIBUTION_TABLE, AWARD_TABLE, COMMAND_TABLE)

IMMUTABLE_FUNCTION = "marketedgepros_affiliate_lifecycle_immutable"
SOURCE_CONTEXT_FUNCTION = "marketedgepros_affiliate_source_context_validate"
IDENTITY_VALIDATE_FUNCTION = "marketedgepros_affiliate_identity_evidence_validate"
ATTRIBUTION_VALIDATE_FUNCTION = "marketedgepros_affiliate_order_attribution_validate"
AWARD_VALIDATE_FUNCTION = "marketedgepros_affiliate_commission_award_validate"
AWARD_TRANSITION_FUNCTION = "marketedgepros_affiliate_commission_award_transition"
COMMAND_VALIDATE_FUNCTION = "marketedgepros_affiliate_payout_command_validate"
COMMAND_TRANSITION_FUNCTION = "marketedgepros_affiliate_payout_command_transition"
PAYOUT_CONSISTENCY_FUNCTION = "marketedgepros_affiliate_payout_consistency_validate"
FUNCTION_NAMES = (
    IMMUTABLE_FUNCTION,
    SOURCE_CONTEXT_FUNCTION,
    IDENTITY_VALIDATE_FUNCTION,
    ATTRIBUTION_VALIDATE_FUNCTION,
    AWARD_VALIDATE_FUNCTION,
    AWARD_TRANSITION_FUNCTION,
    COMMAND_VALIDATE_FUNCTION,
    COMMAND_TRANSITION_FUNCTION,
    PAYOUT_CONSISTENCY_FUNCTION,
)

# All bodies are frozen source.  Runtime validation uses literal SHA-256 digests copied
# into affiliate_lifecycle_storage.py and never imports this Alembic module.
FUNCTION_BODIES: dict[str, str] = {
    IMMUTABLE_FUNCTION: """BEGIN
    RAISE EXCEPTION 'affiliate lifecycle evidence is immutable';
END;""",
    SOURCE_CONTEXT_FUNCTION: """DECLARE
    v_attribution public.affiliate_order_attributions%ROWTYPE;
    v_order public.purchase_orders%ROWTYPE;
BEGIN
    SELECT attribution.* INTO v_attribution
    FROM public.affiliate_order_attributions AS attribution
    WHERE attribution.id = p_attribution_id
    FOR KEY SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'affiliate attribution is missing';
    END IF;

    -- Fixed ASCII policy fields have exactly the Python canonical bytes.
    IF v_attribution.policy_hash IS DISTINCT FROM pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(('{\"basis\":' || (v_attribution.policy_json->'basis')::text || ',\"currency\":' || (v_attribution.policy_json->'currency')::text || ',\"hold_seconds\":' || (v_attribution.policy_json->'hold_seconds')::text || ',\"minimum_payout_minor\":' || (v_attribution.policy_json->'minimum_payout_minor')::text || ',\"mode\":' || (v_attribution.policy_json->'mode')::text || ',\"rate_basis_points\":' || (v_attribution.policy_json->'rate_basis_points')::text || ',\"rounding\":' || (v_attribution.policy_json->'rounding')::text || ',\"version\":' || (v_attribution.policy_json->'version')::text || '}'), 'UTF8')), 'hex') THEN
        RAISE EXCEPTION 'affiliate policy fingerprint differs from canonical policy';
    END IF;

    -- This is the shared serialization lock with the isolated receipt writer.  It
    -- deliberately precedes the mutable legacy-user locks below.
    SELECT purchase_order.* INTO v_order
    FROM public.purchase_orders AS purchase_order
    WHERE purchase_order.id = v_attribution.order_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'affiliate attribution order is missing';
    END IF;
    PERFORM 1 FROM public.tenants AS tenant WHERE tenant.id = v_order.tenant_id FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'affiliate attribution tenant is missing';
    END IF;
    PERFORM 1 FROM public.trading_programs AS program WHERE program.id = v_order.program_id FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'affiliate attribution program is missing';
    END IF;

    PERFORM 1
    FROM public.affiliate_identity_evidence AS evidence
    WHERE evidence.id IN (v_attribution.buyer_evidence_id, v_attribution.affiliate_evidence_id)
    ORDER BY evidence.id
    FOR KEY SHARE;
    IF NOT FOUND OR (SELECT count(*) FROM public.affiliate_identity_evidence AS evidence
                     WHERE evidence.id IN (v_attribution.buyer_evidence_id, v_attribution.affiliate_evidence_id)) <> 2 THEN
        RAISE EXCEPTION 'affiliate attribution identity evidence is missing';
    END IF;

    -- Lock both legacy users in stable order, so a tenant/active mutation cannot race
    -- an award or payout transition after it has passed this validation.
    PERFORM 1
    FROM public.users AS account
    WHERE account.id IN (v_attribution.affiliate_user_id, v_order.user_id)
    ORDER BY account.id
    FOR SHARE;
    IF (SELECT count(*) FROM public.users AS account
        WHERE account.id IN (v_attribution.affiliate_user_id, v_order.user_id)) <> 2 THEN
        RAISE EXCEPTION 'affiliate attribution user is missing';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.affiliate_identity_evidence AS buyer_evidence
        JOIN public.affiliate_identity_evidence AS affiliate_evidence
          ON affiliate_evidence.id = v_attribution.affiliate_evidence_id
        JOIN public.users AS buyer ON buyer.id = buyer_evidence.user_id
        JOIN public.users AS affiliate ON affiliate.id = affiliate_evidence.user_id
        JOIN public.tenants AS tenant ON tenant.id = v_order.tenant_id
        JOIN public.trading_programs AS program ON program.id = v_order.program_id
        WHERE buyer_evidence.id = v_attribution.buyer_evidence_id
          AND buyer_evidence.source = 'synthetic'
          AND affiliate_evidence.source = 'synthetic'
          AND buyer_evidence.user_id = v_order.user_id
          AND affiliate_evidence.user_id = v_attribution.affiliate_user_id
          AND buyer_evidence.tenant_id = v_order.tenant_id
          AND affiliate_evidence.tenant_id = v_order.tenant_id
          AND buyer.tenant_id = v_order.tenant_id
          AND affiliate.tenant_id = v_order.tenant_id
          AND program.tenant_id = v_order.tenant_id
          AND tenant.status = 'active'
          AND buyer.is_active IS TRUE AND affiliate.is_active IS TRUE
          AND buyer.id > 0 AND affiliate.id > 0
          AND buyer.id <> affiliate.id
          AND buyer_evidence.subject_hash <> affiliate_evidence.subject_hash
          AND buyer_evidence.created_at <= v_attribution.created_at
          AND affiliate_evidence.created_at <= v_attribution.created_at
          AND (v_order.created_at AT TIME ZONE 'UTC') <= v_attribution.created_at
    ) THEN
        RAISE EXCEPTION 'affiliate attribution legacy tenant, active user, identity, or order context changed';
    END IF;
END;""",
    IDENTITY_VALIDATE_FUNCTION: """DECLARE
    v_user public.users%ROWTYPE;
BEGIN
    SELECT account.* INTO v_user
    FROM public.users AS account
    WHERE account.id = NEW.user_id
    FOR UPDATE;
    IF NOT FOUND OR NEW.user_id <= 0 OR v_user.is_active IS NOT TRUE
       OR v_user.tenant_id IS DISTINCT FROM NEW.tenant_id
       OR NOT EXISTS (SELECT 1 FROM public.tenants AS tenant WHERE tenant.id = NEW.tenant_id) THEN
        RAISE EXCEPTION 'affiliate identity evidence requires an active user in its tenant';
    END IF;
    RETURN NEW;
END;""",
    ATTRIBUTION_VALIDATE_FUNCTION: """DECLARE
    v_order public.purchase_orders%ROWTYPE;
    v_buyer public.affiliate_identity_evidence%ROWTYPE;
    v_affiliate public.affiliate_identity_evidence%ROWTYPE;
    v_buyer_user public.users%ROWTYPE;
    v_affiliate_user public.users%ROWTYPE;
    v_tenant_status varchar(20);
BEGIN
    SELECT purchase_order.* INTO v_order
    FROM public.purchase_orders AS purchase_order
    WHERE purchase_order.id = NEW.order_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'affiliate attribution order is missing';
    END IF;
    SELECT tenant.status INTO v_tenant_status FROM public.tenants AS tenant
    WHERE tenant.id = v_order.tenant_id FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'affiliate attribution tenant is missing';
    END IF;
    PERFORM 1 FROM public.trading_programs AS program
    WHERE program.id = v_order.program_id FOR SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'affiliate attribution program is missing';
    END IF;

    SELECT evidence.* INTO v_buyer
    FROM public.affiliate_identity_evidence AS evidence
    WHERE evidence.id = NEW.buyer_evidence_id
    FOR KEY SHARE;
    SELECT evidence.* INTO v_affiliate
    FROM public.affiliate_identity_evidence AS evidence
    WHERE evidence.id = NEW.affiliate_evidence_id
    FOR KEY SHARE;
    IF v_buyer.id IS NULL OR v_affiliate.id IS NULL THEN
        RAISE EXCEPTION 'affiliate attribution identity evidence is missing';
    END IF;

    -- Lock the two mutable legacy accounts in one deterministic order.
    PERFORM 1 FROM public.users AS account
    WHERE account.id IN (v_buyer.user_id, v_affiliate.user_id)
    ORDER BY account.id FOR SHARE;
    SELECT account.* INTO v_buyer_user FROM public.users AS account WHERE account.id = v_buyer.user_id;
    SELECT account.* INTO v_affiliate_user FROM public.users AS account WHERE account.id = v_affiliate.user_id;
    IF v_buyer_user.id IS NULL OR v_affiliate_user.id IS NULL THEN
        RAISE EXCEPTION 'affiliate attribution user is missing';
    END IF;

    IF NEW.affiliate_user_id <= 0
       OR v_buyer.user_id <= 0 OR v_affiliate.user_id <= 0
       OR NEW.affiliate_user_id <> v_affiliate.user_id
       OR v_order.user_id <> v_buyer.user_id
       OR v_buyer.user_id = v_affiliate.user_id
       OR v_buyer.subject_hash = v_affiliate.subject_hash
       OR v_buyer.source <> 'synthetic' OR v_affiliate.source <> 'synthetic'
       OR v_buyer.tenant_id IS DISTINCT FROM v_order.tenant_id
       OR v_affiliate.tenant_id IS DISTINCT FROM v_order.tenant_id
       OR v_buyer_user.tenant_id IS DISTINCT FROM v_order.tenant_id
       OR v_affiliate_user.tenant_id IS DISTINCT FROM v_order.tenant_id
       OR v_buyer_user.is_active IS NOT TRUE OR v_affiliate_user.is_active IS NOT TRUE
       OR v_tenant_status IS DISTINCT FROM 'active'
       OR v_buyer.created_at > NEW.created_at OR v_affiliate.created_at > NEW.created_at
       OR (v_order.created_at AT TIME ZONE 'UTC') > NEW.created_at
       OR NOT EXISTS (SELECT 1 FROM public.tenants AS tenant WHERE tenant.id = v_order.tenant_id)
       OR NOT EXISTS (SELECT 1 FROM public.trading_programs AS program
                      WHERE program.id = v_order.program_id AND program.tenant_id = v_order.tenant_id) THEN
        RAISE EXCEPTION 'affiliate attribution tenant, active user, identity, or timestamp mismatch';
    END IF;

    -- Fixed ASCII policy fields have exactly the Python canonical bytes.
    IF NEW.policy_hash IS DISTINCT FROM pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(('{\"basis\":' || (NEW.policy_json->'basis')::text || ',\"currency\":' || (NEW.policy_json->'currency')::text || ',\"hold_seconds\":' || (NEW.policy_json->'hold_seconds')::text || ',\"minimum_payout_minor\":' || (NEW.policy_json->'minimum_payout_minor')::text || ',\"mode\":' || (NEW.policy_json->'mode')::text || ',\"rate_basis_points\":' || (NEW.policy_json->'rate_basis_points')::text || ',\"rounding\":' || (NEW.policy_json->'rounding')::text || ',\"version\":' || (NEW.policy_json->'version')::text || '}'), 'UTF8')), 'hex') THEN
        RAISE EXCEPTION 'affiliate policy fingerprint differs from canonical policy';
    END IF;

    IF EXISTS (SELECT 1 FROM public.settlement_journals AS journal WHERE journal.order_id = NEW.order_id)
       OR EXISTS (SELECT 1 FROM public.payment_event_receipts AS receipt WHERE receipt.order_id = NEW.order_id) THEN
        RAISE EXCEPTION 'affiliate attribution cannot be created after a settlement receipt';
    END IF;
    RETURN NEW;
END;""",
    AWARD_VALIDATE_FUNCTION: """DECLARE
    v_attribution public.affiliate_order_attributions%ROWTYPE;
    v_journal public.settlement_journals%ROWTYPE;
    v_receipt public.payment_event_receipts%ROWTYPE;
    v_policy_rate bigint;
    v_policy_hold bigint;
    v_expected bigint;
    v_release timestamptz;
    v_entry_count integer;
    v_order_amount bigint;
BEGIN
    IF NEW.state <> 'held' OR NEW.review_open IS DISTINCT FROM FALSE
       OR NEW.reversal_event_key IS NOT NULL OR NEW.updated_at IS DISTINCT FROM NEW.created_at THEN
        RAISE EXCEPTION 'affiliate awards must be inserted held, unreviewed, and unreversed';
    END IF;
    PERFORM public.marketedgepros_affiliate_source_context_validate(NEW.attribution_id);
    SELECT attribution.* INTO v_attribution FROM public.affiliate_order_attributions AS attribution
    WHERE attribution.id = NEW.attribution_id FOR KEY SHARE;
    SELECT journal.* INTO v_journal FROM public.settlement_journals AS journal
    WHERE journal.id = NEW.journal_id FOR KEY SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'affiliate award settlement journal is missing';
    END IF;
    SELECT receipt.* INTO v_receipt FROM public.payment_event_receipts AS receipt
    WHERE receipt.id = v_journal.receipt_id FOR KEY SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'affiliate award settlement receipt is missing';
    END IF;

    SELECT purchase_order.amount_minor INTO v_order_amount
    FROM public.purchase_orders AS purchase_order WHERE purchase_order.id = v_attribution.order_id;
    IF v_journal.order_id IS DISTINCT FROM v_attribution.order_id
       OR v_receipt.order_id IS DISTINCT FROM v_attribution.order_id
       OR v_journal.receipt_id IS DISTINCT FROM v_receipt.id
       OR v_journal.amount_minor IS DISTINCT FROM v_receipt.amount_minor
       OR v_journal.amount_minor IS DISTINCT FROM v_order_amount
       OR v_journal.currency <> 'USD' OR v_receipt.currency <> 'USD'
       OR v_receipt.source <> 'synthetic' OR v_receipt.merchant_context <> 'isolated-tests'
       OR NEW.created_at < v_attribution.created_at
       OR (v_receipt.created_at AT TIME ZONE 'UTC') < v_attribution.created_at
       OR NEW.created_at < (v_receipt.created_at AT TIME ZONE 'UTC')
       OR NEW.created_at < (v_journal.created_at AT TIME ZONE 'UTC') THEN
        RAISE EXCEPTION 'affiliate award journal, receipt, source, or timestamp mismatch';
    END IF;

    SELECT count(*)::integer INTO v_entry_count
    FROM public.settlement_entries AS entry WHERE entry.journal_id = v_journal.id;
    IF v_entry_count <> 2
       OR NOT EXISTS (SELECT 1 FROM public.settlement_entries AS entry WHERE entry.journal_id=v_journal.id
                      AND entry.line_number=1 AND entry.account_code='provider_clearing'
                      AND entry.side='debit' AND entry.amount_minor=v_journal.amount_minor)
       OR NOT EXISTS (SELECT 1 FROM public.settlement_entries AS entry WHERE entry.journal_id=v_journal.id
                      AND entry.line_number=2 AND entry.account_code='unapplied_order_receipts'
                      AND entry.side='credit' AND entry.amount_minor=v_journal.amount_minor) THEN
        RAISE EXCEPTION 'affiliate award requires canonical balanced settlement entries';
    END IF;

    v_policy_rate := (v_attribution.policy_json->>'rate_basis_points')::bigint;
    v_policy_hold := (v_attribution.policy_json->>'hold_seconds')::bigint;
    v_expected := (v_journal.amount_minor * v_policy_rate) / 10000;
    v_release := (v_receipt.created_at AT TIME ZONE 'UTC') + make_interval(secs => v_policy_hold::double precision);
    IF v_expected <= 0 OR NEW.amount_minor IS DISTINCT FROM v_expected
       OR NEW.release_at IS DISTINCT FROM v_release THEN
        RAISE EXCEPTION 'affiliate award amount or release time does not match explicit policy';
    END IF;
    RETURN NEW;
END;""",
    AWARD_TRANSITION_FUNCTION: """DECLARE
    v_command_state varchar(16);
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'affiliate awards cannot be deleted';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id OR NEW.attribution_id IS DISTINCT FROM OLD.attribution_id
       OR NEW.journal_id IS DISTINCT FROM OLD.journal_id OR NEW.amount_minor IS DISTINCT FROM OLD.amount_minor
       OR NEW.release_at IS DISTINCT FROM OLD.release_at OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'affiliate award identity, money, release, and creation fields are immutable';
    END IF;
    IF NEW.updated_at < OLD.updated_at OR NEW.updated_at < NEW.created_at THEN
        RAISE EXCEPTION 'affiliate award timestamps cannot move backwards';
    END IF;
    PERFORM public.marketedgepros_affiliate_source_context_validate(OLD.attribution_id);

    IF NEW.state = OLD.state THEN
        IF NEW.reversal_event_key IS DISTINCT FROM OLD.reversal_event_key THEN
            RAISE EXCEPTION 'affiliate award reversal evidence is immutable';
        END IF;
        IF OLD.state NOT IN ('held', 'available') AND NEW.review_open IS DISTINCT FROM OLD.review_open THEN
            RAISE EXCEPTION 'affiliate award review may change only while held or available';
        END IF;
        RETURN NEW;
    END IF;

    IF OLD.state IN ('paid', 'reversed') THEN
        RAISE EXCEPTION 'affiliate award terminal state cannot transition';
    ELSIF OLD.state = 'held' AND NEW.state = 'available' THEN
        IF OLD.review_open OR NEW.review_open OR NEW.updated_at < OLD.release_at
           OR NEW.reversal_event_key IS NOT NULL THEN
            RAISE EXCEPTION 'affiliate award release requires maturity and no review';
        END IF;
    ELSIF OLD.state IN ('held', 'available') AND NEW.state = 'reversed' THEN
        IF NEW.review_open IS DISTINCT FROM OLD.review_open
           OR NEW.reversal_event_key IS NULL OR NEW.reversal_event_key !~ '^[A-Za-z0-9_.:-]{1,128}$' THEN
            RAISE EXCEPTION 'affiliate award reversal requires immutable bounded event evidence';
        END IF;
    ELSIF OLD.state = 'available' AND NEW.state = 'reserved' THEN
        IF OLD.review_open OR NEW.review_open OR NEW.reversal_event_key IS NOT NULL THEN
            RAISE EXCEPTION 'affiliate award reservation requires available unreviewed award';
        END IF;
        SELECT command.state INTO v_command_state FROM public.affiliate_payout_commands AS command
        WHERE command.award_id = OLD.id FOR KEY SHARE;
        IF NOT FOUND OR v_command_state <> 'planned' THEN
            RAISE EXCEPTION 'affiliate award reservation requires its planned payout command';
        END IF;
    ELSIF OLD.state = 'reserved' AND NEW.state = 'paid' THEN
        IF NEW.review_open IS DISTINCT FROM OLD.review_open OR NEW.reversal_event_key IS NOT NULL THEN
            RAISE EXCEPTION 'affiliate award payment cannot rewrite review or reversal evidence';
        END IF;
        SELECT command.state INTO v_command_state FROM public.affiliate_payout_commands AS command
        WHERE command.award_id = OLD.id FOR KEY SHARE;
        IF NOT FOUND OR v_command_state <> 'confirmed' THEN
            RAISE EXCEPTION 'affiliate award payment requires its confirmed payout command';
        END IF;
    ELSE
        RAISE EXCEPTION 'affiliate award state transition is invalid';
    END IF;
    RETURN NEW;
END;""",
    COMMAND_VALIDATE_FUNCTION: """DECLARE
    v_award public.affiliate_commission_awards%ROWTYPE;
    v_attribution public.affiliate_order_attributions%ROWTYPE;
    v_approver public.users%ROWTYPE;
    v_minimum bigint;
    v_tenant_id integer;
BEGIN
    IF NEW.state <> 'planned' OR NEW.attempt_token IS NOT NULL OR NEW.transfer_key IS NOT NULL
       OR NEW.updated_at IS DISTINCT FROM NEW.created_at THEN
        RAISE EXCEPTION 'affiliate payout commands must be inserted planned without token or transfer key';
    END IF;
    SELECT award.* INTO v_award FROM public.affiliate_commission_awards AS award
    WHERE award.id = NEW.award_id FOR UPDATE;
    IF NOT FOUND OR v_award.state <> 'available' OR v_award.review_open IS TRUE
       OR NEW.created_at < v_award.updated_at THEN
        RAISE EXCEPTION 'affiliate payout command requires an available unreviewed award';
    END IF;
    PERFORM public.marketedgepros_affiliate_source_context_validate(v_award.attribution_id);
    SELECT attribution.* INTO v_attribution FROM public.affiliate_order_attributions AS attribution
    WHERE attribution.id = v_award.attribution_id FOR KEY SHARE;
    SELECT purchase_order.tenant_id INTO v_tenant_id FROM public.purchase_orders AS purchase_order
    WHERE purchase_order.id = v_attribution.order_id;
    SELECT account.* INTO v_approver FROM public.users AS account
    WHERE account.id = NEW.approved_by FOR SHARE;
    IF NOT FOUND OR NEW.approved_by <= 0 OR v_approver.is_active IS NOT TRUE
       OR v_approver.is_verified IS NOT TRUE OR v_approver.role <> 'supermaster'
       OR v_approver.parent_id IS NOT NULL OR v_approver.can_create_same_role IS NOT TRUE
       OR v_approver.tenant_id IS DISTINCT FROM v_tenant_id
       OR v_approver.tree_path IS NULL OR btrim(v_approver.tree_path) = '' OR length(v_approver.tree_path) > 500 THEN
        RAISE EXCEPTION 'affiliate payout command requires an active verified supermaster approver';
    END IF;
    v_minimum := (v_attribution.policy_json->>'minimum_payout_minor')::bigint;
    IF v_award.amount_minor < v_minimum THEN
        RAISE EXCEPTION 'affiliate payout command award is below explicit policy minimum';
    END IF;
    RETURN NEW;
END;""",
    COMMAND_TRANSITION_FUNCTION: """DECLARE
    v_award public.affiliate_commission_awards%ROWTYPE;
    v_approver public.users%ROWTYPE;
    v_tenant_id integer;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'affiliate payout commands cannot be deleted';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id OR NEW.award_id IS DISTINCT FROM OLD.award_id
       OR NEW.approved_by IS DISTINCT FROM OLD.approved_by OR NEW.network_id IS DISTINCT FROM OLD.network_id
       OR NEW.asset_id IS DISTINCT FROM OLD.asset_id OR NEW.recipient_hash IS DISTINCT FROM OLD.recipient_hash
       OR NEW.amount_atomic IS DISTINCT FROM OLD.amount_atomic OR NEW.quote_hash IS DISTINCT FROM OLD.quote_hash
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'affiliate payout command identity, money, recipient, quote, and creation fields are immutable';
    END IF;
    IF NEW.updated_at < OLD.updated_at OR NEW.updated_at < NEW.created_at THEN
        RAISE EXCEPTION 'affiliate payout command timestamps cannot move backwards';
    END IF;
    SELECT award.* INTO v_award FROM public.affiliate_commission_awards AS award
    WHERE award.id = OLD.award_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'affiliate payout command award is missing';
    END IF;
    PERFORM public.marketedgepros_affiliate_source_context_validate(v_award.attribution_id);
    SELECT purchase_order.tenant_id INTO v_tenant_id
    FROM public.purchase_orders AS purchase_order
    JOIN public.affiliate_order_attributions AS attribution ON attribution.order_id = purchase_order.id
    WHERE attribution.id = v_award.attribution_id;
    SELECT account.* INTO v_approver FROM public.users AS account
    WHERE account.id = OLD.approved_by FOR SHARE;
    IF NOT FOUND OR v_approver.is_active IS NOT TRUE OR v_approver.is_verified IS NOT TRUE
       OR v_approver.role <> 'supermaster' OR v_approver.parent_id IS NOT NULL
       OR v_approver.can_create_same_role IS NOT TRUE OR v_approver.tenant_id IS DISTINCT FROM v_tenant_id
       OR v_approver.tree_path IS NULL OR btrim(v_approver.tree_path) = '' OR length(v_approver.tree_path) > 500 THEN
        RAISE EXCEPTION 'affiliate payout command approver context changed';
    END IF;

    IF NEW.state = OLD.state THEN
        IF NEW.attempt_token IS DISTINCT FROM OLD.attempt_token OR NEW.transfer_key IS DISTINCT FROM OLD.transfer_key THEN
            RAISE EXCEPTION 'affiliate payout command replay cannot rewrite attempt or transfer identity';
        END IF;
        RETURN NEW;
    END IF;
    IF OLD.state = 'planned' THEN
        IF NEW.state <> 'dispatched' OR NEW.attempt_token IS NULL OR NEW.transfer_key IS NOT NULL
           OR v_award.state <> 'reserved' THEN
            RAISE EXCEPTION 'affiliate payout command only claims planned once against reserved award';
        END IF;
    ELSIF OLD.state = 'dispatched' THEN
        IF NEW.state NOT IN ('uncertain', 'confirmed') OR NEW.attempt_token IS DISTINCT FROM OLD.attempt_token
           OR (NEW.state = 'uncertain' AND NEW.transfer_key IS NOT NULL)
           OR (NEW.state = 'confirmed' AND (NEW.transfer_key IS NULL OR NEW.transfer_key !~ '^[A-Za-z0-9_.:-]{1,128}$'))
           OR v_award.state <> 'reserved' THEN
            RAISE EXCEPTION 'affiliate payout dispatched transition is invalid';
        END IF;
    ELSIF OLD.state = 'uncertain' THEN
        IF NEW.state <> 'confirmed' OR NEW.attempt_token IS DISTINCT FROM OLD.attempt_token
           OR NEW.transfer_key IS NULL OR NEW.transfer_key !~ '^[A-Za-z0-9_.:-]{1,128}$'
           OR v_award.state <> 'reserved' THEN
            RAISE EXCEPTION 'affiliate payout uncertain transition is invalid';
        END IF;
    ELSE
        RAISE EXCEPTION 'affiliate payout confirmed state is terminal';
    END IF;
    RETURN NEW;
END;""",
    PAYOUT_CONSISTENCY_FUNCTION: """DECLARE
    v_award_id varchar(36);
    v_award_state varchar(16);
    v_count integer;
    v_command_state varchar(16);
BEGIN
    IF TG_TABLE_NAME = 'affiliate_commission_awards' THEN
        v_award_id := NEW.id;
    ELSIF TG_TABLE_NAME = 'affiliate_payout_commands' THEN
        v_award_id := NEW.award_id;
    ELSE
        RAISE EXCEPTION 'unexpected affiliate payout consistency trigger table: %', TG_TABLE_NAME;
    END IF;
    SELECT award.state INTO v_award_state FROM public.affiliate_commission_awards AS award
    WHERE award.id = v_award_id FOR KEY SHARE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'affiliate payout consistency award is missing';
    END IF;
    SELECT count(*)::integer, max(command.state) INTO v_count, v_command_state
    FROM public.affiliate_payout_commands AS command WHERE command.award_id = v_award_id;

    IF v_award_state = 'reserved' THEN
        IF v_count <> 1 OR v_command_state NOT IN ('planned', 'dispatched', 'uncertain') THEN
            RAISE EXCEPTION 'reserved affiliate award requires exactly one active payout command';
        END IF;
    ELSIF v_award_state = 'paid' THEN
        IF v_count <> 1 OR v_command_state <> 'confirmed' THEN
            RAISE EXCEPTION 'paid affiliate award requires exactly one confirmed payout command';
        END IF;
    ELSIF v_count <> 0 THEN
        RAISE EXCEPTION 'affiliate payout command requires a reserved or paid award';
    END IF;
    RETURN NEW;
END;""",
}

FOREIGN_KEYS = {
    IDENTITY_TABLE: {
        "fk_affiliate_identity_evidence_user": ("user_id", "users"),
        "fk_affiliate_identity_evidence_tenant": ("tenant_id", "tenants"),
    },
    ATTRIBUTION_TABLE: {
        "fk_affiliate_order_attributions_order": ("order_id", "purchase_orders"),
        "fk_affiliate_order_attributions_affiliate_user": ("affiliate_user_id", "users"),
        "fk_affiliate_order_attributions_buyer_evidence": ("buyer_evidence_id", IDENTITY_TABLE),
        "fk_affiliate_order_attributions_affiliate_evidence": ("affiliate_evidence_id", IDENTITY_TABLE),
    },
    AWARD_TABLE: {
        "fk_affiliate_commission_awards_attribution": ("attribution_id", ATTRIBUTION_TABLE),
        "fk_affiliate_commission_awards_journal": ("journal_id", "settlement_journals"),
    },
    COMMAND_TABLE: {
        "fk_affiliate_payout_commands_award": ("award_id", AWARD_TABLE),
        "fk_affiliate_payout_commands_approved_by": ("approved_by", "users"),
    },
}

UNIQUE_CONSTRAINTS = {
    IDENTITY_TABLE: {
        "uq_affiliate_identity_evidence_source_event": ["source", "event_key"],
        "uq_affiliate_identity_evidence_tenant_user": ["tenant_id", "user_id"],
    },
    ATTRIBUTION_TABLE: {"uq_affiliate_order_attributions_order": ["order_id"]},
    AWARD_TABLE: {
        "uq_affiliate_commission_awards_attribution": ["attribution_id"],
        "uq_affiliate_commission_awards_journal": ["journal_id"],
    },
    COMMAND_TABLE: {
        "uq_affiliate_payout_commands_award": ["award_id"],
        "uq_affiliate_payout_commands_transfer": ["network_id", "transfer_key"],
    },
}

POLICY_CHECK = "jsonb_typeof(policy_json) = 'object' AND policy_json ?& ARRAY['version','rate_basis_points','basis','currency','hold_seconds','minimum_payout_minor','rounding','mode'] AND (policy_json - 'version' - 'rate_basis_points' - 'basis' - 'currency' - 'hold_seconds' - 'minimum_payout_minor' - 'rounding' - 'mode') = '{}'::jsonb AND jsonb_typeof(policy_json->'version') = 'string' AND length(policy_json->>'version') BETWEEN 1 AND 64 AND (policy_json->>'version') ~ '^[A-Za-z0-9_.:-]+$' AND jsonb_typeof(policy_json->'rate_basis_points') = 'number' AND (policy_json->>'rate_basis_points') ~ '^[0-9]+$' AND (policy_json->>'rate_basis_points')::bigint BETWEEN 1 AND 10000 AND policy_json->'basis' = '\"paid_order_total\"'::jsonb AND policy_json->'currency' = '\"USD\"'::jsonb AND jsonb_typeof(policy_json->'hold_seconds') = 'number' AND (policy_json->>'hold_seconds') ~ '^[0-9]+$' AND (policy_json->>'hold_seconds')::bigint BETWEEN 0 AND 31536000 AND jsonb_typeof(policy_json->'minimum_payout_minor') = 'number' AND (policy_json->>'minimum_payout_minor') ~ '^[0-9]+$' AND (policy_json->>'minimum_payout_minor')::bigint BETWEEN 1 AND 9999999999 AND policy_json->'rounding' = '\"floor\"'::jsonb AND policy_json->'mode' = '\"synthetic\"'::jsonb"

CHECKS = {
    IDENTITY_TABLE: {
        "ck_affiliate_identity_evidence_id": "id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
        "ck_affiliate_identity_evidence_user": "user_id > 0 AND tenant_id > 0",
        "ck_affiliate_identity_evidence_subject_hash": "subject_hash ~ '^[0-9a-f]{64}$'",
        "ck_affiliate_identity_evidence_source": "source = 'synthetic'",
        "ck_affiliate_identity_evidence_event_key": "event_key ~ '^[A-Za-z0-9_.:-]{1,128}$'",
    },
    ATTRIBUTION_TABLE: {
        "ck_affiliate_order_attributions_id": "id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
        "ck_affiliate_order_attributions_references": "order_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' AND buyer_evidence_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' AND affiliate_evidence_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' AND affiliate_user_id > 0",
        "ck_affiliate_order_attributions_policy_hash": "policy_hash ~ '^[0-9a-f]{64}$'",
        "ck_affiliate_order_attributions_policy": POLICY_CHECK,
    },
    AWARD_TABLE: {
        "ck_affiliate_commission_awards_id": "id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
        "ck_affiliate_commission_awards_references": "attribution_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' AND journal_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
        "ck_affiliate_commission_awards_amount": "amount_minor >= 1 AND amount_minor <= 9999999999",
        "ck_affiliate_commission_awards_state": "state IN ('held', 'available', 'reserved', 'paid', 'reversed')",
        "ck_affiliate_commission_awards_times": "updated_at >= created_at",
        "ck_affiliate_commission_awards_reversal": "(state = 'reversed' AND reversal_event_key IS NOT NULL AND reversal_event_key ~ '^[A-Za-z0-9_.:-]{1,128}$') OR (state <> 'reversed' AND reversal_event_key IS NULL)",
    },
    COMMAND_TABLE: {
        "ck_affiliate_payout_commands_id": "id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
        "ck_affiliate_payout_commands_award": "award_id ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' AND approved_by > 0",
        "ck_affiliate_payout_commands_identifiers": "network_id ~ '^[A-Za-z0-9_.:-]{1,64}$' AND asset_id ~ '^[A-Za-z0-9_.:-]{1,64}$'",
        "ck_affiliate_payout_commands_hashes": "recipient_hash ~ '^[0-9a-f]{64}$' AND quote_hash ~ '^[0-9a-f]{64}$'",
        "ck_affiliate_payout_commands_amount": "amount_atomic > 0",
        "ck_affiliate_payout_commands_state": "state IN ('planned', 'dispatched', 'uncertain', 'confirmed')",
        "ck_affiliate_payout_commands_shape": "(state = 'planned' AND attempt_token IS NULL AND transfer_key IS NULL) OR (state IN ('dispatched', 'uncertain') AND attempt_token IS NOT NULL AND attempt_token ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' AND transfer_key IS NULL) OR (state = 'confirmed' AND attempt_token IS NOT NULL AND transfer_key IS NOT NULL AND attempt_token ~ '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' AND transfer_key ~ '^[A-Za-z0-9_.:-]{1,128}$')",
        "ck_affiliate_payout_commands_times": "updated_at >= created_at",
    },
}

EXPECTED_COLUMNS = {
    IDENTITY_TABLE: {
        "id": ("varchar(36)", False), "user_id": ("integer", False), "tenant_id": ("integer", False),
        "subject_hash": ("varchar(64)", False), "source": ("varchar(16)", False),
        "event_key": ("varchar(128)", False), "created_at": ("timestamp with time zone", False),
    },
    ATTRIBUTION_TABLE: {
        "id": ("varchar(36)", False), "order_id": ("varchar(36)", False),
        "affiliate_user_id": ("integer", False), "buyer_evidence_id": ("varchar(36)", False),
        "affiliate_evidence_id": ("varchar(36)", False), "policy_hash": ("varchar(64)", False),
        "policy_json": ("jsonb", False), "created_at": ("timestamp with time zone", False),
    },
    AWARD_TABLE: {
        "id": ("varchar(36)", False), "attribution_id": ("varchar(36)", False),
        "journal_id": ("varchar(36)", False), "amount_minor": ("bigint", False),
        "state": ("varchar(16)", False), "review_open": ("boolean", False),
        "release_at": ("timestamp with time zone", False), "reversal_event_key": ("varchar(128)", True),
        "created_at": ("timestamp with time zone", False), "updated_at": ("timestamp with time zone", False),
    },
    COMMAND_TABLE: {
        "id": ("varchar(36)", False), "award_id": ("varchar(36)", False), "approved_by": ("integer", False),
        "network_id": ("varchar(64)", False), "asset_id": ("varchar(64)", False),
        "recipient_hash": ("varchar(64)", False), "amount_atomic": ("numeric(78, 0)", False),
        "quote_hash": ("varchar(64)", False), "attempt_token": ("varchar(36)", True),
        "transfer_key": ("varchar(128)", True), "state": ("varchar(16)", False),
        "created_at": ("timestamp with time zone", False), "updated_at": ("timestamp with time zone", False),
    },
}

EXPECTED_INDEXES = {
    IDENTITY_TABLE: {
        ("affiliate_identity_evidence_pkey", True, True, "id"),
        ("uq_affiliate_identity_evidence_source_event", True, False, "source,event_key"),
        ("uq_affiliate_identity_evidence_tenant_user", True, False, "tenant_id,user_id"),
    },
    ATTRIBUTION_TABLE: {
        ("affiliate_order_attributions_pkey", True, True, "id"),
        ("uq_affiliate_order_attributions_order", True, False, "order_id"),
    },
    AWARD_TABLE: {
        ("affiliate_commission_awards_pkey", True, True, "id"),
        ("uq_affiliate_commission_awards_attribution", True, False, "attribution_id"),
        ("uq_affiliate_commission_awards_journal", True, False, "journal_id"),
    },
    COMMAND_TABLE: {
        ("affiliate_payout_commands_pkey", True, True, "id"),
        ("uq_affiliate_payout_commands_award", True, False, "award_id"),
        ("uq_affiliate_payout_commands_transfer", True, False, "network_id,transfer_key"),
    },
}

# name -> (tgtype, function, is_constraint, deferrable, initially_deferred)
TRIGGERS = {
    IDENTITY_TABLE: {
        "affiliate_identity_evidence_immutable": (27, IMMUTABLE_FUNCTION, False, False, False),
        "affiliate_identity_evidence_validate_insert": (7, IDENTITY_VALIDATE_FUNCTION, False, False, False),
        "affiliate_identity_evidence_no_truncate": (34, IMMUTABLE_FUNCTION, False, False, False),
    },
    ATTRIBUTION_TABLE: {
        "affiliate_order_attributions_immutable": (27, IMMUTABLE_FUNCTION, False, False, False),
        "affiliate_order_attributions_validate_insert": (7, ATTRIBUTION_VALIDATE_FUNCTION, False, False, False),
        "affiliate_order_attributions_no_truncate": (34, IMMUTABLE_FUNCTION, False, False, False),
    },
    AWARD_TABLE: {
        "affiliate_commission_awards_transition": (27, AWARD_TRANSITION_FUNCTION, False, False, False),
        "affiliate_commission_awards_validate_insert": (7, AWARD_VALIDATE_FUNCTION, False, False, False),
        "affiliate_commission_awards_payout_consistency": (21, PAYOUT_CONSISTENCY_FUNCTION, True, True, True),
        "affiliate_commission_awards_no_truncate": (34, IMMUTABLE_FUNCTION, False, False, False),
    },
    COMMAND_TABLE: {
        "affiliate_payout_commands_transition": (27, COMMAND_TRANSITION_FUNCTION, False, False, False),
        "affiliate_payout_commands_validate_insert": (7, COMMAND_VALIDATE_FUNCTION, False, False, False),
        "affiliate_payout_commands_award_consistency": (21, PAYOUT_CONSISTENCY_FUNCTION, True, True, True),
        "affiliate_payout_commands_no_truncate": (34, IMMUTABLE_FUNCTION, False, False, False),
    },
}

OWNED_RELATIONS = frozenset({
    IDENTITY_TABLE, "affiliate_identity_evidence_pkey", "uq_affiliate_identity_evidence_source_event",
    "uq_affiliate_identity_evidence_tenant_user", ATTRIBUTION_TABLE,
    "affiliate_order_attributions_pkey", "uq_affiliate_order_attributions_order",
    AWARD_TABLE, "affiliate_commission_awards_pkey", "uq_affiliate_commission_awards_attribution",
    "uq_affiliate_commission_awards_journal", COMMAND_TABLE, "affiliate_payout_commands_pkey",
    "uq_affiliate_payout_commands_award", "uq_affiliate_payout_commands_transfer",
})

PARENT_COLUMNS = {
    "tenants": {"id": ("integer", False), "status": ("varchar(20)", True)},
    "users": {
        "id": ("integer", False), "tenant_id": ("integer", None), "is_active": ("boolean", False),
        "is_verified": ("boolean", False), "role": ("varchar(20)", False),
        "parent_id": ("integer", True), "can_create_same_role": ("boolean", False),
        "tree_path": ("varchar(500)", True),
    },
    "trading_programs": {"id": ("integer", False), "tenant_id": ("integer", None)},
    "purchase_orders": {
        "id": ("varchar(36)", False), "user_id": ("integer", False), "tenant_id": ("integer", False),
        "program_id": ("integer", False), "amount_minor": ("bigint", False), "currency": ("varchar(3)", False),
        "created_at": ("timestamp without time zone", False),
    },
    "payment_event_receipts": {
        "id": ("varchar(36)", False), "source": ("varchar(64)", False),
        "merchant_context": ("varchar(128)", False), "order_id": ("varchar(36)", False),
        "amount_minor": ("bigint", False), "currency": ("varchar(3)", False),
        "created_at": ("timestamp without time zone", False),
    },
    "settlement_journals": {
        "id": ("varchar(36)", False), "receipt_id": ("varchar(36)", False),
        "order_id": ("varchar(36)", False), "amount_minor": ("bigint", False),
        "currency": ("varchar(3)", False), "created_at": ("timestamp without time zone", False),
    },
    "settlement_entries": {
        "id": ("varchar(36)", False), "journal_id": ("varchar(36)", False),
        "line_number": ("integer", False), "account_code": ("varchar(64)", False),
        "side": ("varchar(6)", False), "amount_minor": ("bigint", False),
    },
}


def _normalised_type(type_) -> str:
    rendered = str(type_.compile(dialect=postgresql.dialect())).lower()
    return " ".join(rendered.replace("character varying", "varchar").split())


def _normalised_check(expression: str) -> str:
    # PostgreSQL deparses BETWEEN into its equivalent pair of comparisons.
    value = re.sub(r"([^\s]+)\s+BETWEEN\s+(\d+)\s+AND\s+(\d+)",
                   r"\1 >= \2 AND \1 <= \3", str(expression), flags=re.IGNORECASE)
    value = "".join(value.lower().split())
    value = re.sub(r"'([0-9]+)'::bigint", r"\1", value)
    value = re.sub(r"'([0-9]+)'::numeric", r"\1", value)
    value = re.sub(r"(?<=\d)::numeric", "", value)
    value = value.replace("::text[]", "").replace("::character varying", "").replace("::charactervarying", "").replace("::text", "")
    value = re.sub(r"=any\(array\[([^]]*)\]\)", r"in(\1)", value)
    return value.replace('"', '').replace("(", "").replace(")", "")


def _public_relation_names(bind) -> set[str]:
    return set(bind.execute(sa.text("""
        SELECT relation.relname FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public'
    """)).scalars())


def _function_rows(bind, name: str):
    return bind.execute(sa.text("""
        SELECT procedure.oid, pg_get_function_identity_arguments(procedure.oid) AS signature,
               procedure.prorettype::regtype::text AS return_type, procedure.prokind,
               language.lanname AS language, procedure.prosrc, procedure.provolatile,
               procedure.proisstrict, procedure.prosecdef, procedure.proleakproof,
               procedure.proparallel, procedure.proconfig, procedure.proacl
        FROM pg_proc AS procedure
        JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
        JOIN pg_language AS language ON language.oid = procedure.prolang
        WHERE namespace.nspname = 'public' AND procedure.proname = :name
        ORDER BY procedure.oid
    """), {"name": name}).mappings().all()


def _parent_shape_errors(bind) -> list[str]:
    inspector = sa.inspect(bind)
    errors: list[str] = []
    for table, expected in PARENT_COLUMNS.items():
        relation = bind.execute(sa.text("""
            SELECT relation.relkind FROM pg_class AS relation
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            WHERE namespace.nspname='public' AND relation.relname=:table
        """), {"table": table}).scalar()
        if relation not in ("r", "p"):
            errors.append(table)
            continue
        columns = {row["name"]: row for row in inspector.get_columns(table, schema="public")}
        for name, (type_name, nullable) in expected.items():
            actual = columns.get(name)
            if (actual is None or _normalised_type(actual["type"]) != type_name
                    or (nullable is not None and actual["nullable"] is not nullable)):
                errors.append(f"{table}.{name}")
        primary = inspector.get_pk_constraint(table, schema="public")
        if primary.get("constrained_columns") != ["id"]:
            errors.append(f"{table}.id")
    return errors


def _preflight_upgrade() -> None:
    if context.is_offline_mode():
        return
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT current_schema()='public' AND current_schemas(false)=ARRAY['public']::name[]")).scalar_one() is not True:
        raise RuntimeError('Affiliate lifecycle schema collision before DDL: unsafe search path')
    collisions = sorted(OWNED_RELATIONS & _public_relation_names(bind))
    functions = {name: _function_rows(bind, name) for name in FUNCTION_NAMES}
    parents = _parent_shape_errors(bind)
    if collisions or any(functions.values()) or parents:
        detail: list[str] = []
        if collisions:
            detail.append("public relations: " + ", ".join(collisions))
        for name, rows in functions.items():
            if rows:
                detail.append("public functions: " + ", ".join(f"public.{name}({row['signature']})" for row in rows))
        if parents:
            detail.append("invalid FK/source targets: " + ", ".join(parents))
        raise RuntimeError("Affiliate lifecycle schema collision before DDL: " + "; ".join(detail))


def _table_oid_or_error(bind, table: str) -> int:
    row = bind.execute(sa.text("""
        SELECT relation.oid, relation.relkind FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname='public' AND relation.relname=:table
    """), {"table": table}).mappings().first()
    if row is None or row["relkind"] != "r":
        raise RuntimeError("Affiliate lifecycle downgrade refuses partial ownership: " + table)
    return int(row["oid"])


def _owned_index_rows(bind, table_oid: int):
    return bind.execute(sa.text("""
        SELECT index_relation.relname AS name, index_meta.indisunique AS is_unique,
               index_meta.indisprimary AS is_primary, index_meta.indisvalid AS is_valid,
               index_meta.indisready AS is_ready, index_meta.indislive AS is_live,
               index_namespace.nspname = 'public' AS public_schema,
               access_method.amname = 'btree' AS btree_access_method,
               index_relation.reltablespace = 0 AS default_tablespace,
               index_meta.indpred IS NULL AS no_predicate,
               index_meta.indexprs IS NULL AS no_expressions,
               index_meta.indnkeyatts = index_meta.indnatts AS no_included_columns,
               COALESCE(bool_and(COALESCE(operator_class.opcdefault
                   AND operator_class.opcmethod = index_relation.relam, false)), false)
                   AS default_operator_classes,
               COALESCE(bool_and(COALESCE(key_part.collation_oid = attribute.attcollation, false)), false)
                   AS matching_collations,
               COALESCE(bool_and(COALESCE(key_part.sort_options = 0, false)), false)
                   AS all_sort_options_zero,
               array_to_string(array_agg(attribute.attname ORDER BY key_part.ordinality), ',') AS columns
        FROM pg_index AS index_meta
        JOIN pg_class AS index_relation ON index_relation.oid=index_meta.indexrelid
        JOIN pg_namespace AS index_namespace ON index_namespace.oid=index_relation.relnamespace
        JOIN pg_am AS access_method ON access_method.oid=index_relation.relam
        LEFT JOIN LATERAL unnest(index_meta.indkey, index_meta.indclass, index_meta.indcollation, index_meta.indoption)
          WITH ORDINALITY AS key_part(attnum, opclass_oid, collation_oid, sort_options, ordinality) ON true
        LEFT JOIN pg_attribute AS attribute ON attribute.attrelid=index_meta.indrelid AND attribute.attnum=key_part.attnum
        LEFT JOIN pg_opclass AS operator_class ON operator_class.oid=key_part.opclass_oid
        WHERE index_meta.indrelid=:oid
        GROUP BY index_relation.relname, index_namespace.nspname, access_method.amname,
                 index_relation.relnamespace, index_relation.relam, index_relation.reltablespace,
                 index_meta.indisunique, index_meta.indisprimary, index_meta.indisvalid,
                 index_meta.indisready, index_meta.indislive, index_meta.indpred, index_meta.indexprs,
                 index_meta.indnkeyatts, index_meta.indnatts
    """), {"oid": table_oid}).mappings().all()


def _function_ownership_error(bind, name: str, body: str) -> tuple[int | None, str | None]:
    rows = _function_rows(bind, name)
    if len(rows) != 1:
        return None, "public." + name
    row = rows[0]
    expected_signature = "p_attribution_id character varying" if name == SOURCE_CONTEXT_FUNCTION else ""
    expected_return = "void" if name == SOURCE_CONTEXT_FUNCTION else "trigger"
    if (row["signature"] != expected_signature or row["return_type"] != expected_return or row["prokind"] != "f"
            or row["language"] != "plpgsql" or row["prosrc"].strip() != body.strip()
            or row["provolatile"] != "v" or row["proisstrict"] or row["prosecdef"]
            or row["proleakproof"] or row["proparallel"] != "u" or row["proconfig"] is not None
            or row["proacl"] is not None):
        return int(row["oid"]), "public." + name
    return int(row["oid"]), None


def _ownership_errors(bind, oids: dict[str, int]) -> list[str]:
    inspector = sa.inspect(bind)
    errors: list[str] = []
    function_oids: dict[str, int | None] = {}
    for name, body in FUNCTION_BODIES.items():
        function_oids[name], error = _function_ownership_error(bind, name, body)
        if error:
            errors.append(error)
    trigger_oids: dict[str, set[int]] = {name: set() for name in FUNCTION_NAMES}
    owned_oid_csv = ", ".join(str(oid) for oid in oids.values())
    for table, oid in oids.items():
        columns = {row["name"]: row for row in inspector.get_columns(table, schema="public")}
        if set(columns) != set(EXPECTED_COLUMNS[table]):
            errors.append(table + ".columns")
        for name, (type_name, nullable) in EXPECTED_COLUMNS[table].items():
            item = columns.get(name)
            if item is not None and (_normalised_type(item["type"]) != type_name
                    or item["nullable"] is not nullable or item["default"] is not None):
                errors.append(f"{table}.{name}")
        primary = inspector.get_pk_constraint(table, schema="public")
        if primary.get("name") != table + "_pkey" or primary.get("constrained_columns") != ["id"]:
            errors.append(table + ".primary_key")
        fks = {row["name"]: row for row in inspector.get_foreign_keys(table, schema="public")}
        if set(fks) != set(FOREIGN_KEYS[table]):
            errors.append(table + ".foreign_keys")
        for name, (column, parent) in FOREIGN_KEYS[table].items():
            item = fks.get(name)
            if item is not None and (item.get("constrained_columns") != [column] or item.get("referred_table") != parent
                    or item.get("referred_columns") != ["id"] or item.get("referred_schema") not in (None, "public")
                    or item.get("options")):
                errors.append(f"{table}.{name}")
        uniques = {row["name"]: row for row in inspector.get_unique_constraints(table, schema="public")}
        if set(uniques) != set(UNIQUE_CONSTRAINTS[table]):
            errors.append(table + ".unique_constraints")
        for name, expected in UNIQUE_CONSTRAINTS[table].items():
            if name in uniques and uniques[name].get("column_names") != expected:
                errors.append(f"{table}.{name}")
        checks = {row["name"]: row for row in inspector.get_check_constraints(table, schema="public")}
        if set(checks) != set(CHECKS[table]):
            errors.append(table + ".check_constraints")
        for name, expected in CHECKS[table].items():
            if name in checks and _normalised_check(checks[name].get("sqltext", "")) != _normalised_check(expected):
                errors.append(f"{table}.{name}")
        index_rows = _owned_index_rows(bind, oid)
        if any(not row["is_valid"] or not row["is_ready"] or not row["is_live"]
               or not row["public_schema"] or not row["btree_access_method"]
               or not row["default_operator_classes"] or not row["matching_collations"]
               or not row["all_sort_options_zero"] or not row["default_tablespace"]
               or not row["no_included_columns"] or not row["no_predicate"]
               or not row["no_expressions"] for row in index_rows):
            errors.append(table + ".unowned_index_definition")
        expected_indexes = {
            (*item, True, True, True, True, True, True, True, True, True, True, True, True)
            for item in EXPECTED_INDEXES[table]
        }
        actual_indexes = {
            (row["name"], row["is_unique"], row["is_primary"], row["columns"],
             row["is_valid"], row["is_ready"], row["is_live"], row["public_schema"],
             row["btree_access_method"], row["default_operator_classes"], row["matching_collations"],
             row["all_sort_options_zero"], row["default_tablespace"], row["no_included_columns"],
             row["no_predicate"], row["no_expressions"])
            for row in index_rows
        }
        if actual_indexes != expected_indexes:
            errors.append(table + ".indexes")
        rows = bind.execute(sa.text("""
            SELECT trigger.oid, trigger.tgname, trigger.tgtype, trigger.tgenabled, trigger.tgfoid,
                   trigger.tgqual IS NULL AS no_when, trigger.tgnargs, trigger.tgconstraint,
                   trigger.tgdeferrable, trigger.tginitdeferred
            FROM pg_trigger AS trigger WHERE trigger.tgrelid=:oid AND NOT trigger.tgisinternal
        """), {"oid": oid}).mappings().all()
        trigger_map = {row["tgname"]: row for row in rows}
        if set(trigger_map) != set(TRIGGERS[table]):
            errors.append(table + ".triggers")
        else:
            for name, (tgtype, function_name, is_constraint, deferrable, initially_deferred) in TRIGGERS[table].items():
                item = trigger_map[name]
                function_oid = function_oids[function_name]
                if (item["tgtype"] != tgtype or item["tgenabled"] != "O" or not item["no_when"]
                        or item["tgnargs"] != 0 or function_oid is None or int(item["tgfoid"]) != function_oid
                        or (int(item["tgconstraint"]) != 0) is not is_constraint
                        or bool(item["tgdeferrable"]) is not deferrable
                        or bool(item["tginitdeferred"]) is not initially_deferred):
                    errors.append(f"{table}.{name}")
                else:
                    trigger_oids[function_name].add(int(item["oid"]))
        external = bind.execute(sa.text(f"""
            SELECT conname FROM pg_constraint WHERE contype='f' AND confrelid=:oid
              AND conrelid NOT IN ({owned_oid_csv})
        """), {"oid": oid}).scalars().all()
        if external:
            errors.append(table + ".external_foreign_keys")
        views = bind.execute(sa.text("""
            SELECT DISTINCT dependent_relation.relname
            FROM pg_depend AS dependency
            JOIN pg_rewrite AS rewrite_rule ON rewrite_rule.oid=dependency.objid AND dependency.classid='pg_rewrite'::regclass
            JOIN pg_class AS dependent_relation ON dependent_relation.oid=rewrite_rule.ev_class
            WHERE dependency.refobjid=:oid AND dependent_relation.oid<>:oid
        """), {"oid": oid}).scalars().all()
        if views:
            errors.append(table + ".view_dependents")
    for name, function_oid in function_oids.items():
        if function_oid is None:
            continue
        dependent = bind.execute(sa.text("""
            SELECT trigger.oid FROM pg_depend AS dependency
            JOIN pg_trigger AS trigger ON trigger.oid=dependency.objid AND dependency.classid='pg_trigger'::regclass
            WHERE dependency.refobjid=:oid
        """), {"oid": function_oid}).scalars().all()
        # The context helper is called, rather than trigger-owned, and therefore
        # legitimately has no pg_trigger dependent rows.
        if set(map(int, dependent)) != trigger_oids[name]:
            errors.append("public." + name + ".dependents")
    return sorted(set(errors))


def _preflight_downgrade() -> None:
    if context.is_offline_mode():
        raise RuntimeError("20261012_000001 offline downgrade is unsupported; an online data and ownership preflight is required")
    bind = op.get_bind()
    oids = {table: _table_oid_or_error(bind, table) for table in TABLES}
    bind.execute(sa.text("SET LOCAL lock_timeout = '3s'"))
    bind.execute(sa.text("SET LOCAL statement_timeout = '5s'"))
    bind.execute(sa.text("""
        LOCK TABLE public.affiliate_identity_evidence, public.affiliate_order_attributions,
                   public.affiliate_commission_awards, public.affiliate_payout_commands
        IN ACCESS EXCLUSIVE MODE
    """))
    nonempty = [table for table in TABLES if bind.execute(sa.text(
        f"SELECT EXISTS (SELECT 1 FROM public.{table} LIMIT 1)"
    )).scalar_one()]
    if nonempty:
        raise RuntimeError("Affiliate lifecycle downgrade refuses to delete synthetic lifecycle evidence: " + ", ".join(nonempty))
    errors = _ownership_errors(bind, oids)
    if errors:
        raise RuntimeError("Affiliate lifecycle downgrade refuses changed ownership metadata before DDL: " + ", ".join(errors))


def _create_functions_and_triggers() -> None:
    for name, body in FUNCTION_BODIES.items():
        if name == SOURCE_CONTEXT_FUNCTION:
            op.execute(f"CREATE FUNCTION public.{name}(p_attribution_id varchar(36)) RETURNS void LANGUAGE plpgsql AS $function$\n{body}\n$function$")
        else:
            op.execute(f"CREATE FUNCTION public.{name}() RETURNS trigger LANGUAGE plpgsql AS $function$\n{body}\n$function$")
    for table, validator in ((IDENTITY_TABLE, IDENTITY_VALIDATE_FUNCTION), (ATTRIBUTION_TABLE, ATTRIBUTION_VALIDATE_FUNCTION)):
        op.execute(f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.{IMMUTABLE_FUNCTION}()")
        op.execute(f"CREATE TRIGGER {table}_validate_insert BEFORE INSERT ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.{validator}()")
        op.execute(f"CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON public.{table} FOR EACH STATEMENT EXECUTE FUNCTION public.{IMMUTABLE_FUNCTION}()")
    op.execute(f"CREATE TRIGGER affiliate_commission_awards_transition BEFORE UPDATE OR DELETE ON public.{AWARD_TABLE} FOR EACH ROW EXECUTE FUNCTION public.{AWARD_TRANSITION_FUNCTION}()")
    op.execute(f"CREATE TRIGGER affiliate_commission_awards_validate_insert BEFORE INSERT ON public.{AWARD_TABLE} FOR EACH ROW EXECUTE FUNCTION public.{AWARD_VALIDATE_FUNCTION}()")
    op.execute(f"CREATE CONSTRAINT TRIGGER affiliate_commission_awards_payout_consistency AFTER INSERT OR UPDATE ON public.{AWARD_TABLE} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.{PAYOUT_CONSISTENCY_FUNCTION}()")
    op.execute(f"CREATE TRIGGER affiliate_commission_awards_no_truncate BEFORE TRUNCATE ON public.{AWARD_TABLE} FOR EACH STATEMENT EXECUTE FUNCTION public.{IMMUTABLE_FUNCTION}()")
    op.execute(f"CREATE TRIGGER affiliate_payout_commands_transition BEFORE UPDATE OR DELETE ON public.{COMMAND_TABLE} FOR EACH ROW EXECUTE FUNCTION public.{COMMAND_TRANSITION_FUNCTION}()")
    op.execute(f"CREATE TRIGGER affiliate_payout_commands_validate_insert BEFORE INSERT ON public.{COMMAND_TABLE} FOR EACH ROW EXECUTE FUNCTION public.{COMMAND_VALIDATE_FUNCTION}()")
    op.execute(f"CREATE CONSTRAINT TRIGGER affiliate_payout_commands_award_consistency AFTER INSERT OR UPDATE ON public.{COMMAND_TABLE} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION public.{PAYOUT_CONSISTENCY_FUNCTION}()")
    op.execute(f"CREATE TRIGGER affiliate_payout_commands_no_truncate BEFORE TRUNCATE ON public.{COMMAND_TABLE} FOR EACH STATEMENT EXECUTE FUNCTION public.{IMMUTABLE_FUNCTION}()")


def upgrade() -> None:
    _preflight_upgrade()
    op.create_table(
        IDENTITY_TABLE,
        sa.Column("id", sa.String(36), nullable=False), sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.Integer(), nullable=False), sa.Column("subject_hash", sa.String(64), nullable=False),
        sa.Column("source", sa.String(16), nullable=False), sa.Column("event_key", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="affiliate_identity_evidence_pkey"),
        sa.ForeignKeyConstraint(["user_id"], ["public.users.id"], name="fk_affiliate_identity_evidence_user"),
        sa.ForeignKeyConstraint(["tenant_id"], ["public.tenants.id"], name="fk_affiliate_identity_evidence_tenant"),
        *(sa.UniqueConstraint(*columns, name=name) for name, columns in UNIQUE_CONSTRAINTS[IDENTITY_TABLE].items()),
        *(sa.CheckConstraint(expression, name=name) for name, expression in CHECKS[IDENTITY_TABLE].items()),
        schema="public",
    )
    op.create_table(
        ATTRIBUTION_TABLE,
        sa.Column("id", sa.String(36), nullable=False), sa.Column("order_id", sa.String(36), nullable=False),
        sa.Column("affiliate_user_id", sa.Integer(), nullable=False), sa.Column("buyer_evidence_id", sa.String(36), nullable=False),
        sa.Column("affiliate_evidence_id", sa.String(36), nullable=False), sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("policy_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="affiliate_order_attributions_pkey"),
        sa.ForeignKeyConstraint(["order_id"], ["public.purchase_orders.id"], name="fk_affiliate_order_attributions_order"),
        sa.ForeignKeyConstraint(["affiliate_user_id"], ["public.users.id"], name="fk_affiliate_order_attributions_affiliate_user"),
        sa.ForeignKeyConstraint(["buyer_evidence_id"], [f"public.{IDENTITY_TABLE}.id"], name="fk_affiliate_order_attributions_buyer_evidence"),
        sa.ForeignKeyConstraint(["affiliate_evidence_id"], [f"public.{IDENTITY_TABLE}.id"], name="fk_affiliate_order_attributions_affiliate_evidence"),
        *(sa.UniqueConstraint(*columns, name=name) for name, columns in UNIQUE_CONSTRAINTS[ATTRIBUTION_TABLE].items()),
        *(sa.CheckConstraint(expression, name=name) for name, expression in CHECKS[ATTRIBUTION_TABLE].items()),
        schema="public",
    )
    op.create_table(
        AWARD_TABLE,
        sa.Column("id", sa.String(36), nullable=False), sa.Column("attribution_id", sa.String(36), nullable=False),
        sa.Column("journal_id", sa.String(36), nullable=False), sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False), sa.Column("review_open", sa.Boolean(), nullable=False),
        sa.Column("release_at", sa.DateTime(timezone=True), nullable=False), sa.Column("reversal_event_key", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="affiliate_commission_awards_pkey"),
        sa.ForeignKeyConstraint(["attribution_id"], [f"public.{ATTRIBUTION_TABLE}.id"], name="fk_affiliate_commission_awards_attribution"),
        sa.ForeignKeyConstraint(["journal_id"], ["public.settlement_journals.id"], name="fk_affiliate_commission_awards_journal"),
        *(sa.UniqueConstraint(*columns, name=name) for name, columns in UNIQUE_CONSTRAINTS[AWARD_TABLE].items()),
        *(sa.CheckConstraint(expression, name=name) for name, expression in CHECKS[AWARD_TABLE].items()),
        schema="public",
    )
    op.create_table(
        COMMAND_TABLE,
        sa.Column("id", sa.String(36), nullable=False), sa.Column("award_id", sa.String(36), nullable=False),
        sa.Column("approved_by", sa.Integer(), nullable=False), sa.Column("network_id", sa.String(64), nullable=False),
        sa.Column("asset_id", sa.String(64), nullable=False), sa.Column("recipient_hash", sa.String(64), nullable=False),
        sa.Column("amount_atomic", sa.Numeric(78, 0), nullable=False), sa.Column("quote_hash", sa.String(64), nullable=False),
        sa.Column("attempt_token", sa.String(36), nullable=True), sa.Column("transfer_key", sa.String(128), nullable=True),
        sa.Column("state", sa.String(16), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="affiliate_payout_commands_pkey"),
        sa.ForeignKeyConstraint(["award_id"], [f"public.{AWARD_TABLE}.id"], name="fk_affiliate_payout_commands_award"),
        sa.ForeignKeyConstraint(["approved_by"], ["public.users.id"], name="fk_affiliate_payout_commands_approved_by"),
        *(sa.UniqueConstraint(*columns, name=name) for name, columns in UNIQUE_CONSTRAINTS[COMMAND_TABLE].items()),
        *(sa.CheckConstraint(expression, name=name) for name, expression in CHECKS[COMMAND_TABLE].items()),
        schema="public",
    )
    _create_functions_and_triggers()


def downgrade() -> None:
    _preflight_downgrade()
    for table in reversed(TABLES):
        for name in TRIGGERS[table]:
            op.execute(f"DROP TRIGGER {name} ON public.{table}")
    for name in reversed(FUNCTION_NAMES):
        if name == SOURCE_CONTEXT_FUNCTION:
            op.execute(f"DROP FUNCTION public.{name}(varchar)")
        else:
            op.execute(f"DROP FUNCTION public.{name}()")
    for table in reversed(TABLES):
        op.drop_table(table, schema="public")
