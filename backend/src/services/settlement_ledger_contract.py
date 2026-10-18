"""Frozen runtime checks for the isolated Stage4 ledger revision; no migration imports."""

EXPECTED_TRIGGERS = {('payment_event_receipts', 'payment_event_receipts_immutable'): (27,
                                                                  False,
                                                                  False,
                                                                  'marketedgepros_settlement_ledger_immutable'),
 ('payment_event_receipts', 'payment_event_receipts_validate_complete'): (5,
                                                                          True,
                                                                          True,
                                                                          'marketedgepros_settlement_ledger_validate'),
 ('purchase_orders', 'purchase_orders_immutable'): (27,
                                                    False,
                                                    False,
                                                    'marketedgepros_purchase_orders_immutable'),
 ('settlement_entries', 'settlement_entries_immutable'): (27,
                                                          False,
                                                          False,
                                                          'marketedgepros_settlement_ledger_immutable'),
 ('settlement_entries', 'settlement_entries_validate_complete'): (5,
                                                                  True,
                                                                  True,
                                                                  'marketedgepros_settlement_ledger_validate'),
 ('settlement_journals', 'settlement_journals_immutable'): (27,
                                                            False,
                                                            False,
                                                            'marketedgepros_settlement_ledger_immutable'),
 ('settlement_journals', 'settlement_journals_validate_complete'): (5,
                                                                    True,
                                                                    True,
                                                                    'marketedgepros_settlement_ledger_validate')}

EXPECTED_FUNCTION_HASHES = {'marketedgepros_purchase_orders_immutable': 'aa7efd1b795b2882dba130a6351070727ffd2d7cae1f8f7767d45612199296d6',
 'marketedgepros_settlement_ledger_immutable': '98a83e98f424586e4edf3740432e0096674ca2ff7dae950732c3cad0aec0af5e',
 'marketedgepros_settlement_ledger_validate': '45a43bc2d539b8fd98524fb35beef15f6a795a12b641a70c23128780366399c6'}

DEFERRED_CONSTRAINT_NAMES = ('payment_event_receipts_validate_complete', 'settlement_entries_validate_complete', 'settlement_journals_validate_complete')

# Statement-level deletion must not bypass row immutability.
for _table in ('payment_event_receipts', 'settlement_journals', 'settlement_entries'):
    EXPECTED_TRIGGERS[(_table, _table + '_no_truncate')] = (34, False, False, 'marketedgepros_settlement_ledger_immutable')
