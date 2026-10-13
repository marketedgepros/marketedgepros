"""Static PostgreSQL storage contract for revision ``20261013_000002``.

This module deliberately imports neither Alembic nor application metadata/models.  It
is shared by the migration and the runtime checkout service solely to prove the
predefined, disabled-by-default storage shape with bounded, read-only catalog queries.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

REVISION = "20261013_000002"
SCHEMA = "public"

INTENT_TABLE = "checkout_intents"
BINDING_TABLE = "nowpayments_payment_bindings"
OBSERVATION_TABLE = "nowpayments_observations"
RECEIPT_TABLE = "nowpayments_verified_receipts"
JOURNAL_TABLE = "nowpayments_settlement_journals"
ENTRY_TABLE = "nowpayments_settlement_entries"
GRANT_TABLE = "order_entitlement_grants"
TABLES = (
    INTENT_TABLE,
    BINDING_TABLE,
    OBSERVATION_TABLE,
    RECEIPT_TABLE,
    JOURNAL_TABLE,
    ENTRY_TABLE,
    GRANT_TABLE,
)

IMMUTABLE_FUNCTION = "marketedgepros_nowpayments_immutable"
TRANSITION_FUNCTION = "marketedgepros_checkout_intent_transition"
VALIDATE_FUNCTION = "marketedgepros_nowpayments_checkout_validate"
FUNCTIONS = (IMMUTABLE_FUNCTION, TRANSITION_FUNCTION, VALIDATE_FUNCTION)

IMMUTABLE_TRIGGERS = {
    BINDING_TABLE: "nowpayments_payment_bindings_immutable",
    OBSERVATION_TABLE: "nowpayments_observations_immutable",
    RECEIPT_TABLE: "nowpayments_verified_receipts_immutable",
    JOURNAL_TABLE: "nowpayments_settlement_journals_immutable",
    ENTRY_TABLE: "nowpayments_settlement_entries_immutable",
    GRANT_TABLE: "order_entitlement_grants_immutable",
}
VALIDATE_TRIGGERS = {table: f"{table}_validate_complete" for table in TABLES}
NO_TRUNCATE_TRIGGERS = {table: f"{table}_no_truncate" for table in TABLES}

# ``pg_class`` contains every index created to back the named PK/UNIQUE
# constraints, so upgrade collision checking must reserve all of these names.
OWNED_RELATIONS = frozenset({
    *TABLES,
    "checkout_intents_pkey", "uq_checkout_intents_order_provider",
    "uq_checkout_intents_order_command", "uq_checkout_intents_external_reference",
    "ix_checkout_intents_owner",
    "nowpayments_payment_bindings_pkey", "uq_nowpayments_bindings_intent",
    "uq_nowpayments_bindings_order", "uq_nowpayments_binding_provider_payment",
    "ix_nowpayments_bindings_payment",
    "nowpayments_observations_pkey", "uq_nowpayments_observations_replay",
    "ix_nowpayments_observations_binding_created",
    "nowpayments_verified_receipts_pkey", "uq_nowpayments_receipts_order",
    "uq_nowpayments_receipts_binding", "uq_nowpayments_receipts_observation",
    "nowpayments_settlement_journals_pkey", "uq_nowpayments_journals_receipt",
    "uq_nowpayments_journals_order",
    "nowpayments_settlement_entries_pkey", "uq_nowpayments_entries_line",
    "order_entitlement_grants_pkey", "uq_order_entitlement_grants_order",
    "uq_order_entitlement_grants_receipt", "uq_order_entitlement_grants_observation",
})

EXPECTED_COLUMNS: dict[str, dict[str, tuple[str, bool]]] = {
    INTENT_TABLE: {
        "id": ("varchar(36)", False), "order_id": ("varchar(36)", False),
        "user_id": ("integer", False), "tenant_id": ("integer", False),
        "provider": ("varchar(32)", False), "merchant_context": ("varchar(64)", False),
        "command_key": ("varchar(128)", False), "external_reference": ("varchar(96)", False),
        "request_digest": ("varchar(64)", False), "pay_currency": ("varchar(32)", False),
        "network": ("varchar(32)", False), "decimals": ("integer", False),
        "outcome_currency": ("varchar(32)", False), "policy_version": ("varchar(64)", False),
        "state": ("varchar(24)", False), "created_at": ("timestamp with time zone", False),
        "updated_at": ("timestamp with time zone", False),
        "dispatch_reserved_at": ("timestamp with time zone", True),
        "last_refresh_at": ("timestamp with time zone", True),
    },
    BINDING_TABLE: {
        "id": ("varchar(36)", False), "intent_id": ("varchar(36)", False),
        "order_id": ("varchar(36)", False), "provider": ("varchar(32)", False),
        "merchant_context": ("varchar(64)", False), "provider_payment_id": ("varchar(128)", False),
        "parent_payment_id": ("varchar(128)", True), "response_digest": ("varchar(64)", False),
        "price_amount": ("varchar(80)", False), "price_currency": ("varchar(3)", False),
        "pay_amount": ("varchar(80)", False), "pay_currency": ("varchar(32)", False),
        "network": ("varchar(32)", False), "decimals": ("integer", False),
        "pay_address": ("varchar(256)", False), "memo": ("varchar(128)", True),
        "expires_at": ("timestamp with time zone", True), "initial_status": ("varchar(24)", False),
        "fee_paid_by_user": ("boolean", False), "created_at": ("timestamp with time zone", False),
    },
    OBSERVATION_TABLE: {
        "id": ("varchar(36)", False), "binding_id": ("varchar(36)", False),
        "order_id": ("varchar(36)", False), "provider_payment_id": ("varchar(128)", False),
        "payload_digest": ("varchar(64)", False), "source": ("varchar(16)", False),
        "status": ("varchar(24)", False), "review_required": ("boolean", False),
        "pay_amount": ("varchar(80)", True), "actually_paid": ("varchar(80)", True),
        "outcome_amount": ("varchar(80)", True), "outcome_currency": ("varchar(32)", True),
        "created_at": ("timestamp with time zone", False),
    },
    RECEIPT_TABLE: {
        "id": ("varchar(36)", False), "order_id": ("varchar(36)", False),
        "binding_id": ("varchar(36)", False), "observation_id": ("varchar(36)", False),
        "amount_minor": ("bigint", False), "currency": ("varchar(3)", False),
        "source": ("varchar(32)", False), "created_at": ("timestamp with time zone", False),
    },
    JOURNAL_TABLE: {
        "id": ("varchar(36)", False), "receipt_id": ("varchar(36)", False),
        "order_id": ("varchar(36)", False), "amount_minor": ("bigint", False),
        "currency": ("varchar(3)", False), "created_at": ("timestamp with time zone", False),
    },
    ENTRY_TABLE: {
        "id": ("varchar(36)", False), "journal_id": ("varchar(36)", False),
        "line_number": ("integer", False), "account_code": ("varchar(64)", False),
        "side": ("varchar(6)", False), "amount_minor": ("bigint", False),
    },
    GRANT_TABLE: {
        "id": ("varchar(36)", False), "order_id": ("varchar(36)", False),
        "receipt_id": ("varchar(36)", False), "observation_id": ("varchar(36)", False),
        "source": ("varchar(32)", False), "policy_version": ("varchar(64)", False),
        "created_at": ("timestamp with time zone", False),
    },
}

FOREIGN_KEYS: dict[str, dict[str, tuple[str, str]]] = {
    INTENT_TABLE: {
        "fk_checkout_intents_order": ("order_id", "purchase_orders"),
        "fk_checkout_intents_user": ("user_id", "users"),
        "fk_checkout_intents_tenant": ("tenant_id", "tenants"),
    },
    BINDING_TABLE: {
        "fk_nowpayments_bindings_intent": ("intent_id", INTENT_TABLE),
        "fk_nowpayments_bindings_order": ("order_id", "purchase_orders"),
    },
    OBSERVATION_TABLE: {
        "fk_nowpayments_observations_binding": ("binding_id", BINDING_TABLE),
        "fk_nowpayments_observations_order": ("order_id", "purchase_orders"),
    },
    RECEIPT_TABLE: {
        "fk_nowpayments_receipts_order": ("order_id", "purchase_orders"),
        "fk_nowpayments_receipts_binding": ("binding_id", BINDING_TABLE),
        "fk_nowpayments_receipts_observation": ("observation_id", OBSERVATION_TABLE),
    },
    JOURNAL_TABLE: {
        "fk_nowpayments_journals_receipt": ("receipt_id", RECEIPT_TABLE),
        "fk_nowpayments_journals_order": ("order_id", "purchase_orders"),
    },
    ENTRY_TABLE: {"fk_nowpayments_entries_journal": ("journal_id", JOURNAL_TABLE)},
    GRANT_TABLE: {
        "fk_order_entitlement_grants_order": ("order_id", "purchase_orders"),
        "fk_order_entitlement_grants_receipt": ("receipt_id", RECEIPT_TABLE),
        "fk_order_entitlement_grants_observation": ("observation_id", OBSERVATION_TABLE),
    },
}

CHECKS: dict[str, dict[str, str]] = {
    INTENT_TABLE: {
        "ck_checkout_intents_provider": "provider = 'nowpayments'",
        "ck_checkout_intents_owner": "user_id > 0 AND tenant_id > 0",
        "ck_checkout_intents_digest": "length(request_digest) = 64",
        "ck_checkout_intents_currency_network": "pay_currency = 'usdttrc20' AND network = 'TRC20' AND decimals = 6 AND outcome_currency ~ '^[a-z0-9]{2,32}$'",
        "ck_checkout_intents_state": "state IN ('prepared','creating','awaiting_payment','creation_uncertain','processing','manual_review','paid','expired','failed')",
    },
    BINDING_TABLE: {
        "ck_nowpayments_bindings_provider": "provider = 'nowpayments'",
        "ck_nowpayments_bindings_price_currency": "price_currency = 'USD'",
        "ck_nowpayments_bindings_currency_network": "pay_currency = 'usdttrc20' AND network = 'TRC20' AND decimals = 6",
        "ck_nowpayments_bindings_status": "initial_status IN ('waiting','confirming','confirmed','sending','partially_paid','finished','failed','expired','refunded')",
        "ck_nowpayments_bindings_fee": "fee_paid_by_user IS FALSE",
        "ck_nowpayments_bindings_digest": "length(response_digest) = 64",
    },
    OBSERVATION_TABLE: {
        "ck_nowpayments_observations_source": "source IN ('ipn','refresh')",
        "ck_nowpayments_observations_digest": "length(payload_digest) = 64",
    },
    RECEIPT_TABLE: {
        "ck_nowpayments_receipts_amount": "amount_minor > 0 AND amount_minor <= 9999999999",
        "ck_nowpayments_receipts_source": "currency = 'USD' AND source = 'nowpayments'",
    },
    JOURNAL_TABLE: {
        "ck_nowpayments_journals_amount": "amount_minor > 0 AND amount_minor <= 9999999999",
        "ck_nowpayments_journals_currency": "currency = 'USD'",
    },
    ENTRY_TABLE: {
        "ck_nowpayments_entries_line": "line_number IN (1,2)",
        "ck_nowpayments_entries_amount": "amount_minor > 0 AND amount_minor <= 9999999999",
        "ck_nowpayments_entries_account": "(line_number = 1 AND side = 'debit' AND account_code = 'provider_clearing') OR (line_number = 2 AND side = 'credit' AND account_code = 'unapplied_order_receipts')",
    },
    GRANT_TABLE: {"ck_order_entitlement_grants_source": "source = 'nowpayments'"},
}

UNIQUE_CONSTRAINTS: dict[str, dict[str, list[str]]] = {
    INTENT_TABLE: {
        "uq_checkout_intents_order_provider": ["order_id", "provider"],
        "uq_checkout_intents_order_command": ["order_id", "command_key"],
        "uq_checkout_intents_external_reference": ["external_reference"],
    },
    BINDING_TABLE: {
        "uq_nowpayments_bindings_intent": ["intent_id"],
        "uq_nowpayments_bindings_order": ["order_id"],
        "uq_nowpayments_binding_provider_payment": ["provider", "merchant_context", "provider_payment_id"],
    },
    OBSERVATION_TABLE: {"uq_nowpayments_observations_replay": ["binding_id", "payload_digest"]},
    RECEIPT_TABLE: {
        "uq_nowpayments_receipts_order": ["order_id"], "uq_nowpayments_receipts_binding": ["binding_id"],
        "uq_nowpayments_receipts_observation": ["observation_id"],
    },
    JOURNAL_TABLE: {"uq_nowpayments_journals_receipt": ["receipt_id"], "uq_nowpayments_journals_order": ["order_id"]},
    ENTRY_TABLE: {"uq_nowpayments_entries_line": ["journal_id", "line_number"]},
    GRANT_TABLE: {
        "uq_order_entitlement_grants_order": ["order_id"], "uq_order_entitlement_grants_receipt": ["receipt_id"],
        "uq_order_entitlement_grants_observation": ["observation_id"],
    },
}

EXPECTED_INDEXES: dict[str, set[tuple[str, bool, bool, str]]] = {
    INTENT_TABLE: {
        ("checkout_intents_pkey", True, True, "id"),
        ("uq_checkout_intents_order_provider", True, False, "order_id,provider"),
        ("uq_checkout_intents_order_command", True, False, "order_id,command_key"),
        ("uq_checkout_intents_external_reference", True, False, "external_reference"),
        ("ix_checkout_intents_owner", False, False, "user_id,tenant_id,created_at"),
    },
    BINDING_TABLE: {
        ("nowpayments_payment_bindings_pkey", True, True, "id"),
        ("uq_nowpayments_bindings_intent", True, False, "intent_id"),
        ("uq_nowpayments_bindings_order", True, False, "order_id"),
        ("uq_nowpayments_binding_provider_payment", True, False, "provider,merchant_context,provider_payment_id"),
        ("ix_nowpayments_bindings_payment", False, False, "provider_payment_id"),
    },
    OBSERVATION_TABLE: {
        ("nowpayments_observations_pkey", True, True, "id"),
        ("uq_nowpayments_observations_replay", True, False, "binding_id,payload_digest"),
        ("ix_nowpayments_observations_binding_created", False, False, "binding_id,created_at"),
    },
    RECEIPT_TABLE: {
        ("nowpayments_verified_receipts_pkey", True, True, "id"),
        ("uq_nowpayments_receipts_order", True, False, "order_id"),
        ("uq_nowpayments_receipts_binding", True, False, "binding_id"),
        ("uq_nowpayments_receipts_observation", True, False, "observation_id"),
    },
    JOURNAL_TABLE: {
        ("nowpayments_settlement_journals_pkey", True, True, "id"),
        ("uq_nowpayments_journals_receipt", True, False, "receipt_id"),
        ("uq_nowpayments_journals_order", True, False, "order_id"),
    },
    ENTRY_TABLE: {
        ("nowpayments_settlement_entries_pkey", True, True, "id"),
        ("uq_nowpayments_entries_line", True, False, "journal_id,line_number"),
    },
    GRANT_TABLE: {
        ("order_entitlement_grants_pkey", True, True, "id"),
        ("uq_order_entitlement_grants_order", True, False, "order_id"),
        ("uq_order_entitlement_grants_receipt", True, False, "receipt_id"),
        ("uq_order_entitlement_grants_observation", True, False, "observation_id"),
    },
}

IMMUTABLE_FUNCTION_BODY = """BEGIN
    RAISE EXCEPTION 'NOWPayments checkout evidence is immutable';
END;"""

TRANSITION_FUNCTION_BODY = """BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'checkout intents cannot be deleted';
    END IF;
    IF NEW.id IS DISTINCT FROM OLD.id OR NEW.order_id IS DISTINCT FROM OLD.order_id
       OR NEW.user_id IS DISTINCT FROM OLD.user_id OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
       OR NEW.provider IS DISTINCT FROM OLD.provider OR NEW.merchant_context IS DISTINCT FROM OLD.merchant_context
       OR NEW.command_key IS DISTINCT FROM OLD.command_key OR NEW.external_reference IS DISTINCT FROM OLD.external_reference
       OR NEW.request_digest IS DISTINCT FROM OLD.request_digest OR NEW.pay_currency IS DISTINCT FROM OLD.pay_currency
       OR NEW.network IS DISTINCT FROM OLD.network OR NEW.decimals IS DISTINCT FROM OLD.decimals
       OR NEW.outcome_currency IS DISTINCT FROM OLD.outcome_currency
       OR NEW.policy_version IS DISTINCT FROM OLD.policy_version OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'checkout intent identity and approved policy are immutable';
    END IF;
    IF NEW.updated_at IS NULL OR NEW.updated_at < OLD.updated_at OR NEW.updated_at < NEW.created_at
       OR (OLD.last_refresh_at IS NOT NULL AND (NEW.last_refresh_at IS NULL OR NEW.last_refresh_at < OLD.last_refresh_at))
       OR (OLD.dispatch_reserved_at IS NOT NULL AND (NEW.dispatch_reserved_at IS NULL OR NEW.dispatch_reserved_at < OLD.dispatch_reserved_at)) THEN
        RAISE EXCEPTION 'checkout intent timestamps cannot move backwards or reset';
    END IF;
    IF NEW.state = OLD.state THEN
        RETURN NEW;
    ELSIF OLD.state = 'prepared' AND NEW.state IN ('creating','creation_uncertain','manual_review') THEN
        RETURN NEW;
    ELSIF OLD.state = 'creating' AND NEW.state IN ('awaiting_payment','processing','paid','creation_uncertain','manual_review','expired','failed') THEN
        RETURN NEW;
    ELSIF OLD.state = 'creation_uncertain' AND NEW.state IN ('awaiting_payment','processing','paid','manual_review','expired','failed') THEN
        RETURN NEW;
    ELSIF OLD.state = 'awaiting_payment' AND NEW.state IN ('processing','paid','manual_review','expired','failed') THEN
        RETURN NEW;
    ELSIF OLD.state = 'processing' AND NEW.state IN ('paid','manual_review','expired','failed') THEN
        RETURN NEW;
    ELSIF OLD.state = 'paid' AND NEW.state = 'manual_review' THEN
        IF NOT EXISTS (
            SELECT 1 FROM public.nowpayments_verified_receipts AS receipt
            WHERE receipt.order_id = NEW.order_id
        ) OR NOT EXISTS (
            SELECT 1 FROM public.order_entitlement_grants AS entitlement
            WHERE entitlement.order_id = NEW.order_id
        ) THEN
            RAISE EXCEPTION 'paid checkout intent may enter manual review only with its preserved grant';
        END IF;
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'checkout intent state transition is invalid';
END;"""

# Values are cast only after strict ASCII decimal syntax and fixed bounds are proven.
# The validator deliberately reads one receipt-derived chain; unrelated review-required
# observations may contain NULL amounts and cannot poison a later verified receipt.
VALIDATE_FUNCTION_BODY = """DECLARE
    v_receipt_id varchar(36);
    v_receipt public.nowpayments_verified_receipts%ROWTYPE;
    v_binding public.nowpayments_payment_bindings%ROWTYPE;
    v_intent public.checkout_intents%ROWTYPE;
    v_observation public.nowpayments_observations%ROWTYPE;
    v_journal public.nowpayments_settlement_journals%ROWTYPE;
    v_grant public.order_entitlement_grants%ROWTYPE;
    v_order_user integer;
    v_order_tenant integer;
    v_order_amount bigint;
    v_order_currency varchar(3);
    v_entry_count integer;
    v_grant_count integer;
    v_debit_total bigint;
    v_credit_total bigint;
    v_payment numeric;
    v_paid numeric;
    v_outcome numeric;
BEGIN
    -- Attempt rows are durable before any receipt exists, so owner and approved
    -- binding identity must be proven independently of a completed chain.
    IF TG_TABLE_NAME = 'checkout_intents' THEN
        SELECT purchase_order.user_id, purchase_order.tenant_id, purchase_order.amount_minor, purchase_order.currency
          INTO v_order_user, v_order_tenant, v_order_amount, v_order_currency
          FROM public.purchase_orders AS purchase_order WHERE purchase_order.id = NEW.order_id;
        IF NOT FOUND OR NEW.user_id <> v_order_user OR NEW.tenant_id <> v_order_tenant THEN
            RAISE EXCEPTION 'NOWPayments intent must match quoted order owner';
        END IF;
    ELSIF TG_TABLE_NAME = 'nowpayments_payment_bindings' THEN
        SELECT intent.* INTO v_intent FROM public.checkout_intents AS intent WHERE intent.id = NEW.intent_id;
        IF NOT FOUND THEN RAISE EXCEPTION 'NOWPayments binding intent is missing'; END IF;
        SELECT purchase_order.user_id, purchase_order.tenant_id, purchase_order.amount_minor, purchase_order.currency
          INTO v_order_user, v_order_tenant, v_order_amount, v_order_currency
          FROM public.purchase_orders AS purchase_order WHERE purchase_order.id = v_intent.order_id;
        IF NOT FOUND OR v_intent.user_id <> v_order_user OR v_intent.tenant_id <> v_order_tenant THEN
            RAISE EXCEPTION 'NOWPayments intent must match quoted order owner';
        END IF;
        IF NEW.order_id <> v_intent.order_id OR NEW.provider <> v_intent.provider
           OR NEW.merchant_context <> v_intent.merchant_context OR NEW.pay_currency <> v_intent.pay_currency
           OR NEW.network <> v_intent.network OR NEW.decimals <> v_intent.decimals
           OR NEW.fee_paid_by_user IS DISTINCT FROM FALSE OR NEW.price_currency <> 'USD' THEN
            RAISE EXCEPTION 'NOWPayments binding must match approved intent and merchant-fee policy';
        END IF;
        IF NEW.price_amount !~ '^[0-9]{1,36}(\\.[0-9]{1,30})?$'
           OR NEW.pay_amount !~ '^[0-9]{1,36}(\\.[0-9]{1,30})?$' THEN
            RAISE EXCEPTION 'NOWPayments binding amounts require bounded plain decimal syntax';
        END IF;
        v_payment := NEW.pay_amount::numeric;
        IF NEW.price_amount::numeric <> (v_order_amount::numeric / 100)
           OR v_payment <= 0 OR scale(v_payment) > NEW.decimals THEN
            RAISE EXCEPTION 'NOWPayments binding price or exact deposit quantum is invalid';
        END IF;
    ELSIF TG_TABLE_NAME = 'nowpayments_observations' THEN
        SELECT binding.* INTO v_binding FROM public.nowpayments_payment_bindings AS binding WHERE binding.id = NEW.binding_id;
        IF NOT FOUND OR NEW.order_id <> v_binding.order_id OR NEW.provider_payment_id <> v_binding.provider_payment_id THEN
            RAISE EXCEPTION 'NOWPayments observation must match its binding order and provider payment';
        END IF;
    END IF;

    IF TG_TABLE_NAME = 'nowpayments_verified_receipts' THEN
        v_receipt_id := NEW.id;
    ELSIF TG_TABLE_NAME = 'nowpayments_settlement_journals' THEN
        v_receipt_id := NEW.receipt_id;
    ELSIF TG_TABLE_NAME = 'nowpayments_settlement_entries' THEN
        SELECT journal.receipt_id INTO v_receipt_id
        FROM public.nowpayments_settlement_journals AS journal WHERE journal.id = NEW.journal_id;
    ELSIF TG_TABLE_NAME = 'order_entitlement_grants' THEN
        v_receipt_id := NEW.receipt_id;
    ELSIF TG_TABLE_NAME = 'nowpayments_observations' THEN
        SELECT receipt.id INTO v_receipt_id FROM public.nowpayments_verified_receipts AS receipt
        WHERE receipt.observation_id = NEW.id;
        IF NOT FOUND THEN RETURN NEW; END IF;
    ELSIF TG_TABLE_NAME = 'nowpayments_payment_bindings' THEN
        SELECT receipt.id INTO v_receipt_id FROM public.nowpayments_verified_receipts AS receipt
        WHERE receipt.binding_id = NEW.id;
        IF NOT FOUND THEN RETURN NEW; END IF;
    ELSIF TG_TABLE_NAME = 'checkout_intents' THEN
        SELECT receipt.id INTO v_receipt_id
        FROM public.nowpayments_verified_receipts AS receipt
        JOIN public.nowpayments_payment_bindings AS binding ON binding.id = receipt.binding_id
        WHERE binding.intent_id = NEW.id;
        IF NOT FOUND THEN RETURN NEW; END IF;
    ELSE
        RAISE EXCEPTION 'unexpected NOWPayments checkout trigger table: %', TG_TABLE_NAME;
    END IF;

    SELECT receipt.* INTO v_receipt FROM public.nowpayments_verified_receipts AS receipt
    WHERE receipt.id = v_receipt_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'NOWPayments receipt is missing'; END IF;
    SELECT binding.* INTO v_binding FROM public.nowpayments_payment_bindings AS binding
    WHERE binding.id = v_receipt.binding_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'NOWPayments receipt binding is missing'; END IF;
    SELECT intent.* INTO v_intent FROM public.checkout_intents AS intent
    WHERE intent.id = v_binding.intent_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'NOWPayments binding intent is missing'; END IF;
    SELECT observation.* INTO v_observation FROM public.nowpayments_observations AS observation
    WHERE observation.id = v_receipt.observation_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'NOWPayments receipt observation is missing'; END IF;
    SELECT purchase_order.user_id, purchase_order.tenant_id, purchase_order.amount_minor, purchase_order.currency
      INTO v_order_user, v_order_tenant, v_order_amount, v_order_currency
      FROM public.purchase_orders AS purchase_order WHERE purchase_order.id = v_receipt.order_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'NOWPayments receipt purchase order is missing'; END IF;

    IF v_intent.order_id <> v_receipt.order_id OR v_intent.user_id <> v_order_user
       OR v_intent.tenant_id <> v_order_tenant THEN
        RAISE EXCEPTION 'NOWPayments intent must match quoted order owner';
    END IF;
    IF v_binding.order_id <> v_intent.order_id OR v_binding.provider <> v_intent.provider
       OR v_binding.merchant_context <> v_intent.merchant_context
       OR v_binding.pay_currency <> v_intent.pay_currency OR v_binding.network <> v_intent.network
       OR v_binding.decimals <> v_intent.decimals OR v_binding.fee_paid_by_user IS DISTINCT FROM FALSE
       OR v_binding.price_currency <> 'USD' THEN
        RAISE EXCEPTION 'NOWPayments binding must match approved intent and merchant-fee policy';
    END IF;
    IF v_binding.price_amount !~ '^[0-9]{1,36}(\\.[0-9]{1,30})?$'
       OR v_binding.pay_amount !~ '^[0-9]{1,36}(\\.[0-9]{1,30})?$' THEN
        RAISE EXCEPTION 'NOWPayments binding amounts require bounded plain decimal syntax';
    END IF;
    v_payment := v_binding.pay_amount::numeric;
    IF v_binding.price_amount::numeric <> (v_order_amount::numeric / 100)
       OR v_payment <= 0 OR scale(v_payment) > v_binding.decimals THEN
        RAISE EXCEPTION 'NOWPayments binding price or exact deposit quantum is invalid';
    END IF;

    IF v_receipt.order_id <> v_binding.order_id OR v_observation.binding_id <> v_binding.id
       OR v_observation.order_id <> v_receipt.order_id
       OR v_observation.provider_payment_id <> v_binding.provider_payment_id
       OR v_observation.source <> 'ipn' OR v_observation.status <> 'finished'
       OR v_observation.review_required IS DISTINCT FROM FALSE THEN
        RAISE EXCEPTION 'NOWPayments receipt must use one trusted finished IPN observation';
    END IF;
    IF v_observation.pay_amount IS NULL OR v_observation.actually_paid IS NULL
       OR v_observation.outcome_amount IS NULL OR v_observation.outcome_currency IS NULL
       OR v_observation.pay_amount !~ '^[0-9]{1,36}(\\.[0-9]{1,30})?$'
       OR v_observation.actually_paid !~ '^[0-9]{1,36}(\\.[0-9]{1,30})?$'
       OR v_observation.outcome_amount !~ '^[0-9]{1,36}(\\.[0-9]{1,30})?$' THEN
        RAISE EXCEPTION 'NOWPayments verified observation requires bounded plain decimal amounts';
    END IF;
    v_paid := v_observation.actually_paid::numeric;
    v_outcome := v_observation.outcome_amount::numeric;
    IF v_observation.pay_amount::numeric <> v_payment OR v_paid <> v_payment
       OR scale(v_paid) > v_binding.decimals OR v_outcome <= 0
       OR v_observation.outcome_currency <> v_intent.outcome_currency THEN
        RAISE EXCEPTION 'NOWPayments observation is not the exact approved USDT deposit';
    END IF;
    IF v_receipt.amount_minor <> v_order_amount OR v_receipt.currency <> v_order_currency
       OR v_order_currency <> 'USD' OR v_receipt.source <> 'nowpayments' THEN
        RAISE EXCEPTION 'NOWPayments receipt must equal immutable USD purchase order';
    END IF;

    SELECT journal.* INTO v_journal FROM public.nowpayments_settlement_journals AS journal
    WHERE journal.receipt_id = v_receipt.id;
    IF NOT FOUND OR v_journal.order_id <> v_receipt.order_id
       OR v_journal.amount_minor <> v_receipt.amount_minor OR v_journal.currency <> v_receipt.currency THEN
        RAISE EXCEPTION 'NOWPayments receipt requires one matching settlement journal';
    END IF;
    SELECT count(*)::integer INTO v_grant_count FROM public.order_entitlement_grants AS entitlement
    WHERE entitlement.receipt_id = v_receipt.id;
    IF v_grant_count <> 1 THEN RAISE EXCEPTION 'NOWPayments receipt requires exactly one entitlement grant'; END IF;
    SELECT entitlement.* INTO v_grant FROM public.order_entitlement_grants AS entitlement
    WHERE entitlement.receipt_id = v_receipt.id;
    IF v_grant.order_id <> v_receipt.order_id OR v_grant.observation_id <> v_receipt.observation_id
       OR v_grant.source <> 'nowpayments' OR v_grant.policy_version <> v_intent.policy_version THEN
        RAISE EXCEPTION 'NOWPayments entitlement grant must match receipt, observation, and policy';
    END IF;
    SELECT count(*)::integer,
           COALESCE(sum(CASE WHEN entry.side = 'debit' THEN entry.amount_minor ELSE 0 END), 0),
           COALESCE(sum(CASE WHEN entry.side = 'credit' THEN entry.amount_minor ELSE 0 END), 0)
      INTO v_entry_count, v_debit_total, v_credit_total
      FROM public.nowpayments_settlement_entries AS entry WHERE entry.journal_id = v_journal.id;
    IF v_entry_count <> 2 OR v_debit_total <> v_journal.amount_minor
       OR v_credit_total <> v_journal.amount_minor THEN
        RAISE EXCEPTION 'NOWPayments journal requires exactly two balanced entries';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM public.nowpayments_settlement_entries AS entry
                   WHERE entry.journal_id = v_journal.id AND entry.line_number = 1
                     AND entry.account_code = 'provider_clearing' AND entry.side = 'debit'
                     AND entry.amount_minor = v_journal.amount_minor)
       OR NOT EXISTS (SELECT 1 FROM public.nowpayments_settlement_entries AS entry
                      WHERE entry.journal_id = v_journal.id AND entry.line_number = 2
                        AND entry.account_code = 'unapplied_order_receipts' AND entry.side = 'credit'
                        AND entry.amount_minor = v_journal.amount_minor) THEN
        RAISE EXCEPTION 'NOWPayments journal entries must use canonical clearing accounts';
    END IF;
    RETURN NEW;
END;"""


class CheckoutSchemaValidationError(RuntimeError):
    """Bounded, read-only failure emitted when checkout storage has drifted."""


def _normalised_type(type_: Any) -> str:
    rendered = str(type_.compile(dialect=postgresql.dialect())).lower()
    return " ".join(rendered.replace("character varying", "varchar").split())


def _normalised_check(expression: str) -> str:
    value = "".join(str(expression).lower().split()).replace('"', "")
    # PostgreSQL rewrites finite IN predicates as = ANY (ARRAY[...]) and adds
    # implementation casts to literals/arrays.  These rewrites are equivalent
    # only for our static simple-column predicates, then parentheses are inert.
    value = re.sub(r"::(charactervarying|character varying|varchar|text|integer|bigint|numeric|boolean)(?:\[\])?", "", value)
    value = re.sub(r"'([0-9]+)'", r"\1", value)
    value = value.replace("=any(array[", "in(").replace("])" , ")")
    value = value.replace("(", "").replace(")", "")
    return value.replace("=anyarray[", "in").replace("]", "")


def _function_rows(bind: Any, function_name: str) -> list[Mapping[str, Any]]:
    return bind.execute(sa.text("""
        SELECT procedure.oid, pg_get_function_identity_arguments(procedure.oid) AS signature,
               procedure.prorettype::regtype::text AS return_type, procedure.prokind,
               language.lanname AS language, procedure.prosrc, procedure.provolatile,
               procedure.proisstrict, procedure.prosecdef, procedure.proleakproof,
               procedure.proparallel, procedure.proconfig, procedure.proacl
        FROM pg_proc AS procedure
        JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
        JOIN pg_language AS language ON language.oid = procedure.prolang
        WHERE namespace.nspname = :schema AND procedure.proname = :function_name
        ORDER BY procedure.oid
    """), {"schema": SCHEMA, "function_name": function_name}).mappings().all()


def _index_rows(bind: Any, table_oid: int) -> list[Mapping[str, Any]]:
    return bind.execute(sa.text("""
        SELECT index_relation.relname AS name, index_meta.indisunique AS is_unique,
               index_meta.indisprimary AS is_primary, index_meta.indpred IS NULL AS no_predicate,
               index_meta.indexprs IS NULL AS no_expressions,
               array_to_string(array_agg(attribute.attname ORDER BY key_part.ordinality), ',') AS columns,
               array_to_string(index_meta.indoption, ',') AS options
        FROM pg_index AS index_meta
        JOIN pg_class AS index_relation ON index_relation.oid = index_meta.indexrelid
        LEFT JOIN LATERAL unnest(index_meta.indkey) WITH ORDINALITY
          AS key_part(attnum, ordinality) ON true
        LEFT JOIN pg_attribute AS attribute ON attribute.attrelid = index_meta.indrelid
          AND attribute.attnum = key_part.attnum
        WHERE index_meta.indrelid = :table_oid
        GROUP BY index_relation.relname, index_meta.indisunique, index_meta.indisprimary,
                 index_meta.indpred, index_meta.indexprs, index_meta.indoption
        ORDER BY index_relation.relname
    """), {"table_oid": table_oid}).mappings().all()


def _append(errors: list[str], detail: str) -> None:
    if len(errors) < 24:
        errors.append(detail)


def _relation_oid(bind: Any, table: str, errors: list[str]) -> int | None:
    row = bind.execute(sa.text("""
        SELECT relation.oid, relation.relkind FROM pg_class AS relation
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = :schema AND relation.relname = :table
    """), {"schema": SCHEMA, "table": table}).mappings().first()
    if row is None or row["relkind"] != "r":
        _append(errors, table + ".relation")
        return None
    return int(row["oid"])


def validate_checkout_schema(bind: Any) -> bool:
    """Return ``True`` only for the exact 000002 checkout storage contract.

    The function issues catalog ``SELECT`` statements only.  It never acquires locks,
    modifies sessions, imports models, or uses the Alembic context.  Any catalog error
    or drift raises a bounded :class:`CheckoutSchemaValidationError` fail-closed.
    """
    errors: list[str] = []
    try:
        version_relation = bind.execute(sa.text("SELECT to_regclass('public.alembic_version') IS NOT NULL")).scalar_one()
        if version_relation is not True:
            _append(errors, "alembic_version")
        else:
            versions = bind.execute(sa.text("SELECT version_num FROM public.alembic_version ORDER BY version_num")).scalars().all()
            if versions != [REVISION]:
                _append(errors, "alembic_version.head")

        table_oids = {table: _relation_oid(bind, table, errors) for table in TABLES}
        inspector = sa.inspect(bind)
        function_oids: dict[str, int | None] = {}
        expected_bodies = {
            IMMUTABLE_FUNCTION: IMMUTABLE_FUNCTION_BODY,
            TRANSITION_FUNCTION: TRANSITION_FUNCTION_BODY,
            VALIDATE_FUNCTION: VALIDATE_FUNCTION_BODY,
        }
        for name, body in expected_bodies.items():
            rows = _function_rows(bind, name)
            if len(rows) != 1:
                _append(errors, "function." + name)
                function_oids[name] = None
                continue
            row = rows[0]
            function_oids[name] = int(row["oid"])
            if (row["signature"] != "" or row["return_type"] != "trigger" or row["prokind"] != "f"
                    or row["language"] != "plpgsql" or str(row["prosrc"]).strip() != body.strip()
                    or row["provolatile"] != "v" or bool(row["proisstrict"])
                    or bool(row["prosecdef"]) or bool(row["proleakproof"])
                    or row["proparallel"] != "u" or row["proconfig"] is not None or row["proacl"] is not None):
                _append(errors, "function." + name)

        trigger_oids: dict[str, set[int]] = {name: set() for name in FUNCTIONS}
        for table, table_oid in table_oids.items():
            if table_oid is None:
                continue
            columns = {item["name"]: item for item in inspector.get_columns(table, schema=SCHEMA)}
            if set(columns) != set(EXPECTED_COLUMNS[table]):
                _append(errors, table + ".columns")
            for name, (expected_type, nullable) in EXPECTED_COLUMNS[table].items():
                actual = columns.get(name)
                if actual is None or _normalised_type(actual["type"]) != expected_type or actual["nullable"] is not nullable or actual["default"] is not None:
                    _append(errors, table + "." + name)

            primary = inspector.get_pk_constraint(table, schema=SCHEMA)
            if primary.get("name") != table + "_pkey" or primary.get("constrained_columns") != ["id"]:
                _append(errors, table + ".primary_key")
            foreign_keys = {item["name"]: item for item in inspector.get_foreign_keys(table, schema=SCHEMA)}
            if set(foreign_keys) != set(FOREIGN_KEYS[table]):
                _append(errors, table + ".foreign_keys")
            for name, (column, parent) in FOREIGN_KEYS[table].items():
                actual = foreign_keys.get(name)
                if (actual is None or actual.get("constrained_columns") != [column]
                        or actual.get("referred_table") != parent or actual.get("referred_columns") != ["id"]
                        or actual.get("referred_schema") not in (None, SCHEMA) or actual.get("options")):
                    _append(errors, table + "." + name)
            unique = {item["name"]: item for item in inspector.get_unique_constraints(table, schema=SCHEMA)}
            if set(unique) != set(UNIQUE_CONSTRAINTS[table]):
                _append(errors, table + ".unique_constraints")
            for name, expected_columns in UNIQUE_CONSTRAINTS[table].items():
                if unique.get(name, {}).get("column_names") != expected_columns:
                    _append(errors, table + "." + name)
            checks = {item["name"]: item for item in inspector.get_check_constraints(table, schema=SCHEMA)}
            if set(checks) != set(CHECKS[table]):
                _append(errors, table + ".check_constraints")
            for name, expression in CHECKS[table].items():
                if _normalised_check(str(checks.get(name, {}).get("sqltext", ""))) != _normalised_check(expression):
                    _append(errors, table + "." + name)

            indexes = _index_rows(bind, table_oid)
            if any(not item["no_predicate"] or not item["no_expressions"] or item["options"] not in ("0", "0,0", "0,0,0") for item in indexes):
                _append(errors, table + ".index_definition")
            actual_indexes = {(item["name"], bool(item["is_unique"]), bool(item["is_primary"]), item["columns"]) for item in indexes}
            if actual_indexes != EXPECTED_INDEXES[table]:
                _append(errors, table + ".indexes")

            trigger_rows = bind.execute(sa.text("""
                SELECT trigger.oid, trigger.tgname, trigger.tgtype, trigger.tgenabled,
                       trigger.tgfoid, trigger.tgconstraint, trigger.tgdeferrable,
                       trigger.tginitdeferred, trigger.tgnargs,
                       trigger.tgqual IS NULL AS no_when
                FROM pg_trigger AS trigger
                WHERE trigger.tgrelid = :table_oid AND NOT trigger.tgisinternal
                ORDER BY trigger.tgname
            """), {"table_oid": table_oid}).mappings().all()
            if table == INTENT_TABLE:
                expected_triggers = {
                    "checkout_intents_transition": (27, TRANSITION_FUNCTION, False),
                    NO_TRUNCATE_TRIGGERS[table]: (34, IMMUTABLE_FUNCTION, False),
                    VALIDATE_TRIGGERS[table]: (21, VALIDATE_FUNCTION, True),
                }
            else:
                expected_triggers = {
                    IMMUTABLE_TRIGGERS[table]: (27, IMMUTABLE_FUNCTION, False),
                    NO_TRUNCATE_TRIGGERS[table]: (34, IMMUTABLE_FUNCTION, False),
                    VALIDATE_TRIGGERS[table]: (21, VALIDATE_FUNCTION, True),
                }
            trigger_map = {item["tgname"]: item for item in trigger_rows}
            if set(trigger_map) != set(expected_triggers):
                _append(errors, table + ".triggers")
                continue
            for name, (kind, function_name, constrained) in expected_triggers.items():
                actual = trigger_map[name]
                function_oid = function_oids.get(function_name)
                if (actual["tgtype"] != kind or actual["tgenabled"] != "O" or not actual["no_when"]
                        or actual["tgnargs"] != 0 or function_oid is None or int(actual["tgfoid"]) != function_oid
                        or (int(actual["tgconstraint"]) != 0) is not constrained
                        or bool(actual["tgdeferrable"]) is not constrained
                        or bool(actual["tginitdeferred"]) is not constrained):
                    _append(errors, table + "." + name)
                else:
                    trigger_oids[function_name].add(int(actual["oid"]))

        for function_name, function_oid in function_oids.items():
            if function_oid is None:
                continue
            dependent_ids = bind.execute(sa.text("""
                SELECT trigger.oid FROM pg_depend AS dependency
                JOIN pg_trigger AS trigger ON trigger.oid = dependency.objid
                  AND dependency.classid = 'pg_trigger'::regclass
                WHERE dependency.refobjid = :function_oid
            """), {"function_oid": function_oid}).scalars().all()
            if set(map(int, dependent_ids)) != trigger_oids[function_name]:
                _append(errors, "function." + function_name + ".dependents")
    except Exception as exc:  # catalog connection/permission failures remain fail closed
        raise CheckoutSchemaValidationError("NOWPayments checkout schema validation unavailable") from exc

    if errors:
        raise CheckoutSchemaValidationError("NOWPayments checkout schema drift: " + ", ".join(errors[:24]))
    return True
