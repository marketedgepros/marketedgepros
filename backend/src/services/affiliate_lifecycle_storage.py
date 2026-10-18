"""Frozen PostgreSQL storage gate for the isolated affiliate lifecycle rehearsal.

The module deliberately contains no model or Alembic imports.  Its literals were copied
from revisions 20261011_000007 and 20261012_000001 after the latter's final migration
rehearsal.  A request is allowed to touch lifecycle SQL only when the exact migration
head, transaction settings, parent ledger, functions, triggers, and relation metadata
still equal this frozen contract.
"""
from __future__ import annotations

import hashlib
import re
from types import MappingProxyType

from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql


HEAD_REVISION = "20261012_000001"
DEFERRED_CONSTRAINT_NAMES = (
    "affiliate_commission_awards_payout_consistency",
    "affiliate_payout_commands_award_consistency",
)


def _freeze(value):
    """Keep copied catalog expectations immutable after module import."""
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze(item) for item in value)
    return value


# Literal, migration-independent affiliate schema snapshot.
IDENTITY_TABLE = 'affiliate_identity_evidence'
ATTRIBUTION_TABLE = 'affiliate_order_attributions'
AWARD_TABLE = 'affiliate_commission_awards'
COMMAND_TABLE = 'affiliate_payout_commands'
AFFILIATE_TABLES = ('affiliate_identity_evidence',
 'affiliate_order_attributions',
 'affiliate_commission_awards',
 'affiliate_payout_commands')
AFFILIATE_FUNCTIONS = ('marketedgepros_affiliate_lifecycle_immutable',
 'marketedgepros_affiliate_source_context_validate',
 'marketedgepros_affiliate_identity_evidence_validate',
 'marketedgepros_affiliate_order_attribution_validate',
 'marketedgepros_affiliate_commission_award_validate',
 'marketedgepros_affiliate_commission_award_transition',
 'marketedgepros_affiliate_payout_command_validate',
 'marketedgepros_affiliate_payout_command_transition',
 'marketedgepros_affiliate_payout_consistency_validate')
AFFILIATE_COLUMNS = _freeze({'affiliate_commission_awards': {'amount_minor': ('bigint', False),
                                 'attribution_id': ('varchar(36)', False),
                                 'created_at': ('timestamp with time zone', False),
                                 'id': ('varchar(36)', False),
                                 'journal_id': ('varchar(36)', False),
                                 'release_at': ('timestamp with time zone', False),
                                 'reversal_event_key': ('varchar(128)', True),
                                 'review_open': ('boolean', False),
                                 'state': ('varchar(16)', False),
                                 'updated_at': ('timestamp with time zone', False)},
 'affiliate_identity_evidence': {'created_at': ('timestamp with time zone', False),
                                 'event_key': ('varchar(128)', False),
                                 'id': ('varchar(36)', False),
                                 'source': ('varchar(16)', False),
                                 'subject_hash': ('varchar(64)', False),
                                 'tenant_id': ('integer', False),
                                 'user_id': ('integer', False)},
 'affiliate_order_attributions': {'affiliate_evidence_id': ('varchar(36)', False),
                                  'affiliate_user_id': ('integer', False),
                                  'buyer_evidence_id': ('varchar(36)', False),
                                  'created_at': ('timestamp with time zone', False),
                                  'id': ('varchar(36)', False),
                                  'order_id': ('varchar(36)', False),
                                  'policy_hash': ('varchar(64)', False),
                                  'policy_json': ('jsonb', False)},
 'affiliate_payout_commands': {'amount_atomic': ('numeric(78, 0)', False),
                               'approved_by': ('integer', False),
                               'asset_id': ('varchar(64)', False),
                               'attempt_token': ('varchar(36)', True),
                               'award_id': ('varchar(36)', False),
                               'created_at': ('timestamp with time zone', False),
                               'id': ('varchar(36)', False),
                               'network_id': ('varchar(64)', False),
                               'quote_hash': ('varchar(64)', False),
                               'recipient_hash': ('varchar(64)', False),
                               'state': ('varchar(16)', False),
                               'transfer_key': ('varchar(128)', True),
                               'updated_at': ('timestamp with time zone', False)}})
AFFILIATE_FOREIGN_KEYS = _freeze({'affiliate_commission_awards': {'fk_affiliate_commission_awards_attribution': ('attribution_id',
                                                                                'affiliate_order_attributions'),
                                 'fk_affiliate_commission_awards_journal': ('journal_id', 'settlement_journals')},
 'affiliate_identity_evidence': {'fk_affiliate_identity_evidence_tenant': ('tenant_id', 'tenants'),
                                 'fk_affiliate_identity_evidence_user': ('user_id', 'users')},
 'affiliate_order_attributions': {'fk_affiliate_order_attributions_affiliate_evidence': ('affiliate_evidence_id',
                                                                                         'affiliate_identity_evidence'),
                                  'fk_affiliate_order_attributions_affiliate_user': ('affiliate_user_id', 'users'),
                                  'fk_affiliate_order_attributions_buyer_evidence': ('buyer_evidence_id',
                                                                                     'affiliate_identity_evidence'),
                                  'fk_affiliate_order_attributions_order': ('order_id', 'purchase_orders')},
 'affiliate_payout_commands': {'fk_affiliate_payout_commands_approved_by': ('approved_by', 'users'),
                               'fk_affiliate_payout_commands_award': ('award_id', 'affiliate_commission_awards')}})
AFFILIATE_UNIQUES = _freeze({'affiliate_commission_awards': {'uq_affiliate_commission_awards_attribution': ['attribution_id'],
                                 'uq_affiliate_commission_awards_journal': ['journal_id']},
 'affiliate_identity_evidence': {'uq_affiliate_identity_evidence_source_event': ['source', 'event_key'],
                                 'uq_affiliate_identity_evidence_tenant_user': ['tenant_id', 'user_id']},
 'affiliate_order_attributions': {'uq_affiliate_order_attributions_order': ['order_id']},
 'affiliate_payout_commands': {'uq_affiliate_payout_commands_award': ['award_id'],
                               'uq_affiliate_payout_commands_transfer': ['network_id', 'transfer_key']}})
AFFILIATE_CHECKS = _freeze({'affiliate_commission_awards': {'ck_affiliate_commission_awards_amount': 'amount_minor >= 1 AND amount_minor <= '
                                                                          '9999999999',
                                 'ck_affiliate_commission_awards_id': 'id ~ '
                                                                      "'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
                                 'ck_affiliate_commission_awards_references': 'attribution_id ~ '
                                                                              "'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' "
                                                                              'AND journal_id ~ '
                                                                              "'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
                                 'ck_affiliate_commission_awards_reversal': "(state = 'reversed' AND "
                                                                            'reversal_event_key IS NOT NULL AND '
                                                                            'reversal_event_key ~ '
                                                                            "'^[A-Za-z0-9_.:-]{1,128}$') OR (state <> "
                                                                            "'reversed' AND reversal_event_key IS "
                                                                            'NULL)',
                                 'ck_affiliate_commission_awards_state': "state IN ('held', 'available', 'reserved', "
                                                                         "'paid', 'reversed')",
                                 'ck_affiliate_commission_awards_times': 'updated_at >= created_at'},
 'affiliate_identity_evidence': {'ck_affiliate_identity_evidence_event_key': "event_key ~ '^[A-Za-z0-9_.:-]{1,128}$'",
                                 'ck_affiliate_identity_evidence_id': 'id ~ '
                                                                      "'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
                                 'ck_affiliate_identity_evidence_source': "source = 'synthetic'",
                                 'ck_affiliate_identity_evidence_subject_hash': "subject_hash ~ '^[0-9a-f]{64}$'",
                                 'ck_affiliate_identity_evidence_user': 'user_id > 0 AND tenant_id > 0'},
 'affiliate_order_attributions': {'ck_affiliate_order_attributions_id': 'id ~ '
                                                                        "'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
                                  'ck_affiliate_order_attributions_policy': "jsonb_typeof(policy_json) = 'object' AND "
                                                                            'policy_json ?& '
                                                                            "ARRAY['version','rate_basis_points','basis','currency','hold_seconds','minimum_payout_minor','rounding','mode'] "
                                                                            "AND (policy_json - 'version' - "
                                                                            "'rate_basis_points' - 'basis' - "
                                                                            "'currency' - 'hold_seconds' - "
                                                                            "'minimum_payout_minor' - 'rounding' - "
                                                                            "'mode') = '{}'::jsonb AND "
                                                                            "jsonb_typeof(policy_json->'version') = "
                                                                            "'string' AND "
                                                                            "length(policy_json->>'version') BETWEEN "
                                                                            "1 AND 64 AND (policy_json->>'version') ~ "
                                                                            "'^[A-Za-z0-9_.:-]+$' AND "
                                                                            "jsonb_typeof(policy_json->'rate_basis_points') "
                                                                            "= 'number' AND "
                                                                            "(policy_json->>'rate_basis_points') ~ "
                                                                            "'^[0-9]+$' AND "
                                                                            "(policy_json->>'rate_basis_points')::bigint "
                                                                            'BETWEEN 1 AND 10000 AND '
                                                                            "policy_json->'basis' = "
                                                                            '\'"paid_order_total"\'::jsonb AND '
                                                                            "policy_json->'currency' = "
                                                                            '\'"USD"\'::jsonb AND '
                                                                            "jsonb_typeof(policy_json->'hold_seconds') "
                                                                            "= 'number' AND "
                                                                            "(policy_json->>'hold_seconds') ~ "
                                                                            "'^[0-9]+$' AND "
                                                                            "(policy_json->>'hold_seconds')::bigint "
                                                                            'BETWEEN 0 AND 31536000 AND '
                                                                            "jsonb_typeof(policy_json->'minimum_payout_minor') "
                                                                            "= 'number' AND "
                                                                            "(policy_json->>'minimum_payout_minor') ~ "
                                                                            "'^[0-9]+$' AND "
                                                                            "(policy_json->>'minimum_payout_minor')::bigint "
                                                                            'BETWEEN 1 AND 9999999999 AND '
                                                                            "policy_json->'rounding' = "
                                                                            '\'"floor"\'::jsonb AND '
                                                                            "policy_json->'mode' = "
                                                                            '\'"synthetic"\'::jsonb',
                                  'ck_affiliate_order_attributions_policy_hash': "policy_hash ~ '^[0-9a-f]{64}$'",
                                  'ck_affiliate_order_attributions_references': 'order_id ~ '
                                                                                "'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' "
                                                                                'AND buyer_evidence_id ~ '
                                                                                "'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' "
                                                                                'AND affiliate_evidence_id ~ '
                                                                                "'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' "
                                                                                'AND affiliate_user_id > 0'},
 'affiliate_payout_commands': {'ck_affiliate_payout_commands_amount': 'amount_atomic > 0',
                               'ck_affiliate_payout_commands_award': 'award_id ~ '
                                                                     "'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' "
                                                                     'AND approved_by > 0',
                               'ck_affiliate_payout_commands_hashes': "recipient_hash ~ '^[0-9a-f]{64}$' AND "
                                                                      "quote_hash ~ '^[0-9a-f]{64}$'",
                               'ck_affiliate_payout_commands_id': 'id ~ '
                                                                  "'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'",
                               'ck_affiliate_payout_commands_identifiers': "network_id ~ '^[A-Za-z0-9_.:-]{1,64}$' "
                                                                           "AND asset_id ~ '^[A-Za-z0-9_.:-]{1,64}$'",
                               'ck_affiliate_payout_commands_shape': "(state = 'planned' AND attempt_token IS NULL "
                                                                     'AND transfer_key IS NULL) OR (state IN '
                                                                     "('dispatched', 'uncertain') AND attempt_token "
                                                                     'IS NOT NULL AND attempt_token ~ '
                                                                     "'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' "
                                                                     'AND transfer_key IS NULL) OR (state = '
                                                                     "'confirmed' AND attempt_token IS NOT NULL AND "
                                                                     'transfer_key IS NOT NULL AND attempt_token ~ '
                                                                     "'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$' "
                                                                     "AND transfer_key ~ '^[A-Za-z0-9_.:-]{1,128}$')",
                               'ck_affiliate_payout_commands_state': "state IN ('planned', 'dispatched', 'uncertain', "
                                                                     "'confirmed')",
                               'ck_affiliate_payout_commands_times': 'updated_at >= created_at'}})
AFFILIATE_INDEXES = _freeze({'affiliate_commission_awards': {('affiliate_commission_awards_pkey', True, True, 'id'),
                                 ('uq_affiliate_commission_awards_attribution', True, False, 'attribution_id'),
                                 ('uq_affiliate_commission_awards_journal', True, False, 'journal_id')},
 'affiliate_identity_evidence': {('affiliate_identity_evidence_pkey', True, True, 'id'),
                                 ('uq_affiliate_identity_evidence_source_event', True, False, 'source,event_key'),
                                 ('uq_affiliate_identity_evidence_tenant_user', True, False, 'tenant_id,user_id')},
 'affiliate_order_attributions': {('affiliate_order_attributions_pkey', True, True, 'id'),
                                  ('uq_affiliate_order_attributions_order', True, False, 'order_id')},
 'affiliate_payout_commands': {('affiliate_payout_commands_pkey', True, True, 'id'),
                               ('uq_affiliate_payout_commands_award', True, False, 'award_id'),
                               ('uq_affiliate_payout_commands_transfer', True, False, 'network_id,transfer_key')}})
AFFILIATE_TRIGGER_SPECS = _freeze({'affiliate_commission_awards': {'affiliate_commission_awards_no_truncate': (34,
                                                                             'marketedgepros_affiliate_lifecycle_immutable',
                                                                             False,
                                                                             False,
                                                                             False),
                                 'affiliate_commission_awards_payout_consistency': (21,
                                                                                    'marketedgepros_affiliate_payout_consistency_validate',
                                                                                    True,
                                                                                    True,
                                                                                    True),
                                 'affiliate_commission_awards_transition': (27,
                                                                            'marketedgepros_affiliate_commission_award_transition',
                                                                            False,
                                                                            False,
                                                                            False),
                                 'affiliate_commission_awards_validate_insert': (7,
                                                                                 'marketedgepros_affiliate_commission_award_validate',
                                                                                 False,
                                                                                 False,
                                                                                 False)},
 'affiliate_identity_evidence': {'affiliate_identity_evidence_immutable': (27,
                                                                           'marketedgepros_affiliate_lifecycle_immutable',
                                                                           False,
                                                                           False,
                                                                           False),
                                 'affiliate_identity_evidence_no_truncate': (34,
                                                                             'marketedgepros_affiliate_lifecycle_immutable',
                                                                             False,
                                                                             False,
                                                                             False),
                                 'affiliate_identity_evidence_validate_insert': (7,
                                                                                 'marketedgepros_affiliate_identity_evidence_validate',
                                                                                 False,
                                                                                 False,
                                                                                 False)},
 'affiliate_order_attributions': {'affiliate_order_attributions_immutable': (27,
                                                                             'marketedgepros_affiliate_lifecycle_immutable',
                                                                             False,
                                                                             False,
                                                                             False),
                                  'affiliate_order_attributions_no_truncate': (34,
                                                                               'marketedgepros_affiliate_lifecycle_immutable',
                                                                               False,
                                                                               False,
                                                                               False),
                                  'affiliate_order_attributions_validate_insert': (7,
                                                                                   'marketedgepros_affiliate_order_attribution_validate',
                                                                                   False,
                                                                                   False,
                                                                                   False)},
 'affiliate_payout_commands': {'affiliate_payout_commands_award_consistency': (21,
                                                                               'marketedgepros_affiliate_payout_consistency_validate',
                                                                               True,
                                                                               True,
                                                                               True),
                               'affiliate_payout_commands_no_truncate': (34,
                                                                         'marketedgepros_affiliate_lifecycle_immutable',
                                                                         False,
                                                                         False,
                                                                         False),
                               'affiliate_payout_commands_transition': (27,
                                                                        'marketedgepros_affiliate_payout_command_transition',
                                                                        False,
                                                                        False,
                                                                        False),
                               'affiliate_payout_commands_validate_insert': (7,
                                                                             'marketedgepros_affiliate_payout_command_validate',
                                                                             False,
                                                                             False,
                                                                             False)}})
AFFILIATE_FUNCTION_HASHES = _freeze({'marketedgepros_affiliate_commission_award_transition': 'ef0a504af06023269b82a864c6f3aa26e6e2188500344c26cd029db32de24046',
 'marketedgepros_affiliate_commission_award_validate': 'cbed335278c7e36471df8a52c5b42344eec27544eac8036a88590751733ab993',
 'marketedgepros_affiliate_identity_evidence_validate': '2fc313681c6ac5bf9089ca05b3789348f77790772e57d1dac578a2b14300a7dc',
 'marketedgepros_affiliate_lifecycle_immutable': 'fdac30bed009295203d64843a58421364ae425355d1d14181e292ed0df5dcde9',
 'marketedgepros_affiliate_order_attribution_validate': 'c9cf9979cdcda9a24eeb05a36b87d16c916128ee68dfed28fa1fbc2b888a8b67',
 'marketedgepros_affiliate_payout_command_transition': 'c41e480980cc2e8c129ce3833c86f2634e9fc8cc2869069abebb514017e66fd4',
 'marketedgepros_affiliate_payout_command_validate': '416868f44e4c46a2ca5dffc7d33dcbc68b60a0252d0050e0f292f14997bf3309',
 'marketedgepros_affiliate_payout_consistency_validate': '4110d08738de2f78fde3d586f61d8a5aad682d86b4c7db26893507f334ec665d',
 'marketedgepros_affiliate_source_context_validate': '2005f85e98c32715ee492d0b4bd97a1cbcb7f8bd3d4a9e00e616a4836c6d1dbc'})
AFFILIATE_PARENT_COLUMNS = _freeze({'payment_event_receipts': {'amount_minor': ('bigint', False),
                            'created_at': ('timestamp without time zone', False),
                            'currency': ('varchar(3)', False),
                            'id': ('varchar(36)', False),
                            'merchant_context': ('varchar(128)', False),
                            'order_id': ('varchar(36)', False),
                            'source': ('varchar(64)', False)},
 'purchase_orders': {'amount_minor': ('bigint', False),
                     'created_at': ('timestamp without time zone', False),
                     'currency': ('varchar(3)', False),
                     'id': ('varchar(36)', False),
                     'program_id': ('integer', False),
                     'tenant_id': ('integer', False),
                     'user_id': ('integer', False)},
 'settlement_entries': {'account_code': ('varchar(64)', False),
                        'amount_minor': ('bigint', False),
                        'id': ('varchar(36)', False),
                        'journal_id': ('varchar(36)', False),
                        'line_number': ('integer', False),
                        'side': ('varchar(6)', False)},
 'settlement_journals': {'amount_minor': ('bigint', False),
                         'created_at': ('timestamp without time zone', False),
                         'currency': ('varchar(3)', False),
                         'id': ('varchar(36)', False),
                         'order_id': ('varchar(36)', False),
                         'receipt_id': ('varchar(36)', False)},
 'tenants': {'id': ('integer', False), 'status': ('varchar(20)', True)},
 'trading_programs': {'id': ('integer', False), 'tenant_id': ('integer', None)},
 'users': {'can_create_same_role': ('boolean', False),
           'id': ('integer', False),
           'is_active': ('boolean', False),
           'is_verified': ('boolean', False),
           'parent_id': ('integer', True),
           'role': ('varchar(20)', False),
           'tenant_id': ('integer', None),
           'tree_path': ('varchar(500)', True)}})

# Direct settlement-ledger parent snapshot from revision 20261011_000007.  Do not
# import settlement_ledger_contract at runtime: this is intentionally self-contained.
LEDGER_TABLES = (
    "payment_event_receipts",
    "settlement_journals",
    "settlement_entries",
)
LEDGER_COLUMNS = _freeze({
    "payment_event_receipts": {
        "id": ("varchar(36)", False), "source": ("varchar(64)", False),
        "merchant_context": ("varchar(128)", False), "event_key": ("varchar(128)", False),
        "order_id": ("varchar(36)", False), "amount_minor": ("bigint", False),
        "currency": ("varchar(3)", False), "payload_hash": ("varchar(64)", False),
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
})
LEDGER_FOREIGN_KEYS = _freeze({
    "payment_event_receipts": {"fk_receipt_order": ("order_id", "purchase_orders")},
    "settlement_journals": {
        "fk_journal_receipt": ("receipt_id", "payment_event_receipts"),
        "fk_journal_order": ("order_id", "purchase_orders"),
    },
    "settlement_entries": {"fk_entry_journal": ("journal_id", "settlement_journals")},
})
LEDGER_UNIQUES = _freeze({
    "payment_event_receipts": {"uq_payment_event_identity": ("source", "merchant_context", "event_key")},
    "settlement_journals": {
        "uq_journal_receipt": ("receipt_id",), "uq_journal_order": ("order_id",),
    },
    "settlement_entries": {"uq_journal_line": ("journal_id", "line_number")},
})
LEDGER_CHECKS = _freeze({
    "payment_event_receipts": {
        "ck_receipt_amount": "amount_minor > 0 AND amount_minor <= 9999999999",
        "ck_receipt_currency": "currency = 'USD'", "ck_receipt_hash": "length(payload_hash) = 64",
    },
    "settlement_journals": {
        "ck_journal_amount": "amount_minor > 0 AND amount_minor <= 9999999999",
        "ck_journal_currency": "currency = 'USD'",
    },
    "settlement_entries": {
        "ck_entry_line": "line_number IN (1, 2)",
        "ck_entry_amount": "amount_minor > 0 AND amount_minor <= 9999999999",
        "ck_entry_account": "(line_number = 1 AND side = 'debit' AND account_code = 'provider_clearing') OR (line_number = 2 AND side = 'credit' AND account_code = 'unapplied_order_receipts')",
    },
})
LEDGER_INDEXES = _freeze({
    "payment_event_receipts": frozenset({
        ("payment_event_receipts_pkey", True, True, "id"),
        ("uq_payment_event_identity", True, False, "source,merchant_context,event_key"),
        ("ix_receipt_order", False, False, "order_id"),
    }),
    "settlement_journals": frozenset({
        ("settlement_journals_pkey", True, True, "id"),
        ("uq_journal_receipt", True, False, "receipt_id"),
        ("uq_journal_order", True, False, "order_id"),
    }),
    "settlement_entries": frozenset({
        ("settlement_entries_pkey", True, True, "id"),
        ("uq_journal_line", True, False, "journal_id,line_number"),
        ("ix_entry_journal", False, False, "journal_id"),
    }),
})
LEDGER_FUNCTION_HASHES = _freeze({
    "marketedgepros_purchase_orders_immutable": "aa7efd1b795b2882dba130a6351070727ffd2d7cae1f8f7767d45612199296d6",
    "marketedgepros_settlement_ledger_immutable": "98a83e98f424586e4edf3740432e0096674ca2ff7dae950732c3cad0aec0af5e",
    "marketedgepros_settlement_ledger_validate": "45a43bc2d539b8fd98524fb35beef15f6a795a12b641a70c23128780366399c6",
})
LEDGER_TRIGGER_SPECS = _freeze({
    "payment_event_receipts": {
        "payment_event_receipts_immutable": (27, "marketedgepros_settlement_ledger_immutable", False, False, False),
        "payment_event_receipts_validate_complete": (5, "marketedgepros_settlement_ledger_validate", True, True, True),
        "payment_event_receipts_no_truncate": (34, "marketedgepros_settlement_ledger_immutable", False, False, False),
    },
    "settlement_journals": {
        "settlement_journals_immutable": (27, "marketedgepros_settlement_ledger_immutable", False, False, False),
        "settlement_journals_validate_complete": (5, "marketedgepros_settlement_ledger_validate", True, True, True),
        "settlement_journals_no_truncate": (34, "marketedgepros_settlement_ledger_immutable", False, False, False),
    },
    "settlement_entries": {
        "settlement_entries_immutable": (27, "marketedgepros_settlement_ledger_immutable", False, False, False),
        "settlement_entries_validate_complete": (5, "marketedgepros_settlement_ledger_validate", True, True, True),
        "settlement_entries_no_truncate": (34, "marketedgepros_settlement_ledger_immutable", False, False, False),
    },
})
PARENT_LEDGER_TRIGGER_SPECS = _freeze({
    "purchase_orders": {
        "purchase_orders_immutable": (27, "marketedgepros_purchase_orders_immutable", False, False, False),
    },
})

ALL_TABLES = AFFILIATE_TABLES + LEDGER_TABLES
ALL_COLUMNS = _freeze(dict(AFFILIATE_COLUMNS, **LEDGER_COLUMNS))
ALL_FOREIGN_KEYS = _freeze(dict(AFFILIATE_FOREIGN_KEYS, **LEDGER_FOREIGN_KEYS))
ALL_UNIQUES = _freeze(dict(AFFILIATE_UNIQUES, **LEDGER_UNIQUES))
ALL_CHECKS = _freeze(dict(AFFILIATE_CHECKS, **LEDGER_CHECKS))
ALL_INDEXES = _freeze(dict(AFFILIATE_INDEXES, **LEDGER_INDEXES))
FUNCTION_HASHES = _freeze(dict(AFFILIATE_FUNCTION_HASHES, **LEDGER_FUNCTION_HASHES))

# name -> (identity signature, return type).  Every function must also be a volatile,
# non-strict, invoker-security PL/pgSQL function with default parallel behavior and no ACL.
FUNCTION_SIGNATURES = _freeze({
    **{name: ("", "trigger") for name in AFFILIATE_FUNCTIONS if name != "marketedgepros_affiliate_source_context_validate"},
    "marketedgepros_affiliate_source_context_validate": ("p_attribution_id character varying", "void"),
    "marketedgepros_purchase_orders_immutable": ("", "trigger"),
    "marketedgepros_settlement_ledger_immutable": ("", "trigger"),
    "marketedgepros_settlement_ledger_validate": ("", "trigger"),
})


def _normalised_type(type_) -> str:
    value = str(type_.compile(dialect=postgresql.dialect())).lower()
    return " ".join(value.replace("character varying", "varchar").split())


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


def _index_rows(connection, table_name: str):
    return connection.execute(text("""
        SELECT index_relation.relname AS name, index_meta.indisunique AS is_unique,
               index_meta.indisprimary AS is_primary, index_meta.indisvalid AS is_valid,
               index_meta.indisready AS is_ready, index_meta.indislive AS is_live,
               index_namespace.nspname = 'public' AS public_schema,
               access_method.amname = 'btree' AS btree_access_method,
               index_relation.reltablespace = 0 AS default_tablespace,
               index_meta.indpred IS NULL AS no_predicate, index_meta.indexprs IS NULL AS no_expressions,
               index_meta.indnkeyatts = index_meta.indnatts AS no_included_columns,
               COALESCE(bool_and(COALESCE(operator_class.opcdefault
                   AND operator_class.opcmethod = index_relation.relam, false)), false)
                   AS default_operator_classes,
               COALESCE(bool_and(COALESCE(key_part.collation_oid = attribute.attcollation, false)), false)
                   AS matching_collations,
               COALESCE(bool_and(COALESCE(key_part.sort_options = 0, false)), false)
                   AS all_sort_options_zero,
               array_to_string(array_agg(attribute.attname ORDER BY key_part.ordinality), ',') AS columns
        FROM pg_catalog.pg_index AS index_meta
        JOIN pg_catalog.pg_class AS table_relation ON table_relation.oid = index_meta.indrelid
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = table_relation.relnamespace
        JOIN pg_catalog.pg_class AS index_relation ON index_relation.oid = index_meta.indexrelid
        JOIN pg_catalog.pg_namespace AS index_namespace ON index_namespace.oid = index_relation.relnamespace
        JOIN pg_catalog.pg_am AS access_method ON access_method.oid = index_relation.relam
        LEFT JOIN LATERAL unnest(index_meta.indkey, index_meta.indclass, index_meta.indcollation, index_meta.indoption)
          WITH ORDINALITY AS key_part(attnum, opclass_oid, collation_oid, sort_options, ordinality) ON true
        LEFT JOIN pg_catalog.pg_attribute AS attribute
          ON attribute.attrelid = index_meta.indrelid AND attribute.attnum = key_part.attnum
        LEFT JOIN pg_catalog.pg_opclass AS operator_class ON operator_class.oid = key_part.opclass_oid
        WHERE namespace.nspname = 'public' AND table_relation.relname = :table_name
        GROUP BY index_relation.relname, index_namespace.nspname, access_method.amname,
                 index_relation.relnamespace, index_relation.relam, index_relation.reltablespace,
                 index_meta.indisunique, index_meta.indisprimary,
                 index_meta.indisvalid, index_meta.indisready, index_meta.indislive,
                 index_meta.indpred, index_meta.indexprs, index_meta.indnkeyatts, index_meta.indnatts
    """), {"table_name": table_name}).mappings().all()


def _constraint_rows(connection, table_name: str):
    return connection.execute(text("""
        SELECT con_meta.conname AS name, con_meta.contype AS kind,
               con_meta.condeferrable AS deferrable, con_meta.condeferred AS initially_deferred,
               con_meta.convalidated AS validated, con_meta.confupdtype AS update_action,
               con_meta.confdeltype AS delete_action, con_meta.confmatchtype AS match_type
        FROM pg_catalog.pg_constraint AS con_meta
        JOIN pg_catalog.pg_class AS relation ON relation.oid = con_meta.conrelid
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public' AND relation.relname = :table_name
          AND con_meta.contype IN ('p', 'u', 'f', 'c')
    """), {"table_name": table_name}).mappings().all()


def _relation_rows(connection, names):
    return connection.execute(text("""
        SELECT relation.relname AS name, relation.relkind AS kind, relation.relacl AS acl,
               relation.relrowsecurity AS row_security, relation.relforcerowsecurity AS force_row_security
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public' AND relation.relname = ANY(:names)
    """), {"names": list(names)}).mappings().all()


def _expected_constraint_kinds(table_name: str):
    result = {table_name + "_pkey": "p"}
    result.update({name: "f" for name in ALL_FOREIGN_KEYS[table_name]})
    result.update({name: "u" for name in ALL_UNIQUES[table_name]})
    result.update({name: "c" for name in ALL_CHECKS[table_name]})
    return result


def _validate_parent_shapes(inspector, relation_kinds, errors) -> None:
    for table_name, expected_columns in AFFILIATE_PARENT_COLUMNS.items():
        if relation_kinds.get(table_name) not in ("r", "p"):
            errors.append("parent." + table_name)
            continue
        columns = {item["name"]: item for item in inspector.get_columns(table_name, schema="public")}
        for name, (type_name, nullable) in expected_columns.items():
            item = columns.get(name)
            if (item is None or _normalised_type(item["type"]) != type_name
                    or (nullable is not None and item["nullable"] is not nullable)):
                errors.append("parent." + table_name + "." + name)
        if inspector.get_pk_constraint(table_name, schema="public").get("constrained_columns") != ["id"]:
            errors.append("parent." + table_name + ".primary_key")


def _validate_relations(connection, inspector, relation_rows, errors) -> None:
    relations = {row["name"]: row for row in relation_rows}
    if set(relations) != set(ALL_TABLES) | set(AFFILIATE_PARENT_COLUMNS):
        errors.append("relations")
    _validate_parent_shapes(inspector, {name: row["kind"] for name, row in relations.items()}, errors)
    for table_name in ALL_TABLES:
        relation = relations.get(table_name)
        if (relation is None or relation["kind"] != "r" or relation["acl"] is not None
                or relation["row_security"] or relation["force_row_security"]):
            errors.append(table_name + ".relation")
            continue
        columns = {item["name"]: item for item in inspector.get_columns(table_name, schema="public")}
        if set(columns) != set(ALL_COLUMNS[table_name]):
            errors.append(table_name + ".columns")
        for name, (type_name, nullable) in ALL_COLUMNS[table_name].items():
            item = columns.get(name)
            if (item is None or _normalised_type(item["type"]) != type_name
                    or item["nullable"] is not nullable or item["default"] is not None):
                errors.append(table_name + "." + name)
        primary = inspector.get_pk_constraint(table_name, schema="public")
        if primary.get("name") != table_name + "_pkey" or primary.get("constrained_columns") != ["id"]:
            errors.append(table_name + ".primary_key")
        foreign_keys = {item["name"]: item for item in inspector.get_foreign_keys(table_name, schema="public")}
        if set(foreign_keys) != set(ALL_FOREIGN_KEYS[table_name]):
            errors.append(table_name + ".foreign_keys")
        for name, (column, parent) in ALL_FOREIGN_KEYS[table_name].items():
            item = foreign_keys.get(name)
            if (item is None or item.get("constrained_columns") != [column]
                    or item.get("referred_table") != parent or item.get("referred_columns") != ["id"]
                    or item.get("referred_schema") not in (None, "public") or item.get("options")):
                errors.append(table_name + "." + name)
        unique_constraints = {item["name"]: item for item in inspector.get_unique_constraints(table_name, schema="public")}
        if set(unique_constraints) != set(ALL_UNIQUES[table_name]):
            errors.append(table_name + ".unique_constraints")
        for name, expected in ALL_UNIQUES[table_name].items():
            item = unique_constraints.get(name)
            if item is None or tuple(item.get("column_names") or ()) != tuple(expected):
                errors.append(table_name + "." + name)
        checks = {item["name"]: item for item in inspector.get_check_constraints(table_name, schema="public")}
        if set(checks) != set(ALL_CHECKS[table_name]):
            errors.append(table_name + ".check_constraints")
        for name, expected in ALL_CHECKS[table_name].items():
            item = checks.get(name)
            if item is None or _normalised_check(item.get("sqltext", "")) != _normalised_check(expected):
                errors.append(table_name + "." + name)
        constraints = {item["name"]: item for item in _constraint_rows(connection, table_name)}
        expected_kinds = _expected_constraint_kinds(table_name)
        if set(constraints) != set(expected_kinds):
            errors.append(table_name + ".constraints")
        for name, expected_kind in expected_kinds.items():
            item = constraints.get(name)
            if item is None:
                continue
            if (item["kind"] != expected_kind or item["deferrable"] or item["initially_deferred"]
                    or not item["validated"]):
                errors.append(table_name + "." + name)
                continue
            if expected_kind == "f" and (item["update_action"] != "a" or item["delete_action"] != "a" or item["match_type"] != "s"):
                errors.append(table_name + "." + name)
        indexes = _index_rows(connection, table_name)
        if any(not item["is_valid"] or not item["is_ready"] or not item["is_live"]
               or not item["public_schema"] or not item["btree_access_method"]
               or not item["default_operator_classes"] or not item["matching_collations"]
               or not item["all_sort_options_zero"] or not item["default_tablespace"]
               or not item["no_predicate"] or not item["no_expressions"]
               or not item["no_included_columns"] for item in indexes):
            errors.append(table_name + ".index_definition")
        expected_indexes = {
            (*item, True, True, True, True, True, True, True, True, True, True, True, True)
            for item in ALL_INDEXES[table_name]
        }
        actual_indexes = {
            (item["name"], item["is_unique"], item["is_primary"], item["columns"],
             item["is_valid"], item["is_ready"], item["is_live"], item["public_schema"],
             item["btree_access_method"], item["default_operator_classes"], item["matching_collations"],
             item["all_sort_options_zero"], item["default_tablespace"], item["no_included_columns"],
             item["no_predicate"], item["no_expressions"])
            for item in indexes
        }
        if actual_indexes != expected_indexes:
            errors.append(table_name + ".indexes")


def _expected_trigger_specs():
    expected = {}
    for table_name, triggers in AFFILIATE_TRIGGER_SPECS.items():
        for name, spec in triggers.items():
            expected[(table_name, name)] = spec
    for table_name, triggers in LEDGER_TRIGGER_SPECS.items():
        for name, spec in triggers.items():
            expected[(table_name, name)] = spec
    for table_name, triggers in PARENT_LEDGER_TRIGGER_SPECS.items():
        for name, spec in triggers.items():
            expected[(table_name, name)] = spec
    return expected


def _validate_functions_and_triggers(connection, errors) -> None:
    function_rows = connection.execute(text("""
        SELECT procedure.oid, procedure.proname, procedure.prosrc,
               pg_catalog.pg_get_function_identity_arguments(procedure.oid) AS signature,
               procedure.prorettype::pg_catalog.regtype::text AS return_type, procedure.prokind,
               language.lanname AS language, procedure.provolatile, procedure.proisstrict,
               procedure.prosecdef, procedure.proleakproof, procedure.proparallel,
               procedure.proconfig, procedure.proacl
        FROM pg_catalog.pg_proc AS procedure
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
        JOIN pg_catalog.pg_language AS language ON language.oid = procedure.prolang
        WHERE namespace.nspname = 'public' AND procedure.proname = ANY(:names)
    """), {"names": list(FUNCTION_HASHES)}).mappings().all()
    functions = {row["proname"]: row for row in function_rows}
    if len(function_rows) != len(FUNCTION_HASHES) or set(functions) != set(FUNCTION_HASHES):
        errors.append("functions")
    for name, digest in FUNCTION_HASHES.items():
        row = functions.get(name)
        signature, return_type = FUNCTION_SIGNATURES[name]
        if (row is None or row["signature"] != signature or row["return_type"] != return_type
                or row["prokind"] != "f" or row["language"] != "plpgsql" or row["provolatile"] != "v"
                or row["proisstrict"] or row["prosecdef"] or row["proleakproof"]
                or row["proparallel"] != "u" or row["proconfig"] is not None or row["proacl"] is not None
                or hashlib.sha256(row["prosrc"].strip().encode("utf-8")).hexdigest() != digest):
            errors.append("function." + name)
    expected_triggers = _expected_trigger_specs()
    trigger_rows = connection.execute(text("""
        SELECT relation.relname AS table_name, trigger.oid, trigger.tgname, trigger.tgtype,
               trigger.tgenabled, trigger.tgnargs, trigger.tgqual IS NULL AS no_when,
               trigger.tgfoid, trigger.tgconstraint, trigger.tgdeferrable, trigger.tginitdeferred
        FROM pg_catalog.pg_trigger AS trigger
        JOIN pg_catalog.pg_class AS relation ON relation.oid = trigger.tgrelid
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public' AND relation.relname = ANY(:tables)
          AND NOT trigger.tgisinternal
    """), {"tables": list(ALL_TABLES + tuple(PARENT_LEDGER_TRIGGER_SPECS))}).mappings().all()
    triggers = {(row["table_name"], row["tgname"]): row for row in trigger_rows}
    if len(trigger_rows) != len(expected_triggers) or set(triggers) != set(expected_triggers):
        errors.append("triggers")
    expected_trigger_oids_by_function = {name: set() for name in FUNCTION_HASHES}
    for key, (tgtype, function_name, is_constraint, deferrable, initially_deferred) in expected_triggers.items():
        item, function = triggers.get(key), functions.get(function_name)
        if (item is None or function is None or item["tgtype"] != tgtype or item["tgenabled"] != "O"
                or item["tgnargs"] != 0 or not item["no_when"] or int(item["tgfoid"]) != int(function["oid"])
                or (int(item["tgconstraint"]) != 0) is not is_constraint
                or bool(item["tgdeferrable"]) is not deferrable
                or bool(item["tginitdeferred"]) is not initially_deferred):
            errors.append("trigger." + key[1])
        elif function_name in expected_trigger_oids_by_function:
            expected_trigger_oids_by_function[function_name].add(int(item["oid"]))
    available_oids = [int(row["oid"]) for row in functions.values()]
    if available_oids:
        rows = connection.execute(text("""
            SELECT trigger.tgfoid, trigger.oid
            FROM pg_catalog.pg_trigger AS trigger
            WHERE trigger.tgfoid = ANY(:function_oids) AND NOT trigger.tgisinternal
        """), {"function_oids": available_oids}).mappings().all()
        actual_trigger_oids_by_function = {name: set() for name in FUNCTION_HASHES}
        oid_to_name = {int(row["oid"]): name for name, row in functions.items()}
        for item in rows:
            actual_trigger_oids_by_function[oid_to_name[int(item["tgfoid"])]].add(int(item["oid"]))
        for name, expected_oids in expected_trigger_oids_by_function.items():
            if actual_trigger_oids_by_function[name] != expected_oids:
                errors.append("function." + name + ".trigger_dependents")


def _validate_foreign_key_graph(connection, errors) -> None:
    rows = connection.execute(text("""
        SELECT child_relation.relname AS child_table, con_meta.conname AS name,
               parent_relation.relname AS parent_table
        FROM pg_catalog.pg_constraint AS con_meta
        JOIN pg_catalog.pg_class AS child_relation ON child_relation.oid = con_meta.conrelid
        JOIN pg_catalog.pg_namespace AS child_namespace ON child_namespace.oid = child_relation.relnamespace
        JOIN pg_catalog.pg_class AS parent_relation ON parent_relation.oid = con_meta.confrelid
        JOIN pg_catalog.pg_namespace AS parent_namespace ON parent_namespace.oid = parent_relation.relnamespace
        WHERE con_meta.contype = 'f' AND parent_namespace.nspname = 'public'
          AND con_meta.confrelid IN (
              SELECT relation.oid FROM pg_catalog.pg_class AS relation
              JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
              WHERE namespace.nspname = 'public' AND relation.relname = ANY(:tables)
          )
    """), {"tables": list(ALL_TABLES)}).mappings().all()
    expected = {
        (table_name, name, parent)
        for table_name, foreign_keys in ALL_FOREIGN_KEYS.items()
        for name, (_column, parent) in foreign_keys.items()
        if parent in ALL_TABLES
    }
    actual = {(row["child_table"], row["name"], row["parent_table"]) for row in rows}
    if actual != expected:
        errors.append("foreign_key_graph")


def validate_storage(connection) -> None:
    """Raise RuntimeError if any frozen storage authority or parent ledger has drifted."""
    errors = []
    try:
        inspector = inspect(connection)
        relation_rows = _relation_rows(connection, ALL_TABLES + tuple(AFFILIATE_PARENT_COLUMNS))
        _validate_relations(connection, inspector, relation_rows, errors)
        _validate_foreign_key_graph(connection, errors)
        _validate_functions_and_triggers(connection, errors)
    except RuntimeError:
        raise
    except Exception as error:
        raise RuntimeError("Affiliate lifecycle storage catalog is unavailable") from error
    if errors:
        raise RuntimeError("Affiliate lifecycle storage metadata mismatch: " + ", ".join(sorted(set(errors))))


def require_storage_ready() -> None:
    """Set bounded local waits, reject replication mode, pin head, then validate storage."""
    from src.database import db

    connection = db.session.connection()
    connection.execute(text("SET LOCAL lock_timeout = '3s'"))
    connection.execute(text("SET LOCAL statement_timeout = '5s'"))
    settings = connection.execute(text("""
        SELECT current_setting('lock_timeout') AS lock_timeout,
               current_setting('statement_timeout') AS statement_timeout,
               current_setting('session_replication_role') AS replication_role
    """)).mappings().one()
    if (settings["lock_timeout"] != "3s" or settings["statement_timeout"] != "5s"
            or settings["replication_role"] != "origin"):
        raise RuntimeError("Affiliate lifecycle storage transaction settings are unsafe")
    revisions = connection.execute(text("SELECT version_num FROM public.alembic_version")).scalars().all()
    if revisions != [HEAD_REVISION]:
        raise RuntimeError("Affiliate lifecycle storage revision is not canonical")
    validate_storage(connection)
