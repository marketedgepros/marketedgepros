# Original Stage 4 — isolated receipt ledger foundation

This is a second bounded work package inside original Stage 4, not a new stage and not completion of payment processing. No provider adapter is configured by this package. It adds no public settlement endpoint, changes no wallet/customer balance, marks no payment as paid, issues no entitlement and provisions no MT5 account.

## Evidence model

Three append-only tables follow the frozen order snapshot:

| Table | Purpose and authority |
|---|---|
| `payment_event_receipts` | Normalized source identity `(source, merchant_context, event_key)`, frozen order reference, exact integer minor-unit amount, currency and SHA-256 payload digest. Unique source identity prevents duplicate processing. |
| `settlement_journals` | One journal per receipt and per purchase order in this purchase-receipt-only protocol. It records the same order/amount/currency; it is not refund, withdrawal, revenue recognition or user-wallet credit. |
| `settlement_entries` | Exactly two positive lines: debit `provider_clearing` and credit `unapplied_order_receipts`, each equal to the journal amount. The line-number/side/account constraints and unique journal/line key bound the entry set to two. |

USD cents and purchase receipt are the only implemented rehearsal denomination/type. The two clearing accounts are **unapplied receipt evidence**, not a declaration of revenue, spendable funds, payout rights, accounting policy or tax treatment. Later approved business/accounting rules must introduce a separate versioned protocol instead of editing evidence.

## Database is the final authority

Frozen Alembic revision `20261011_000007` follows `20261011_000006`. It creates only the new three tables, named foreign-key/unique/check/index objects, immutable triggers, and a deferred validation function/constraint trigger on INSERT for each table. No data backfill, seeds, role or balance change occurs.

At transaction end, PostgreSQL verifies each receipt has one journal, journal/receipt/order identity and money match, and exactly two canonical balanced lines exist. Missing journal, one-sided entry, wrong amount/currency/order, extra line or incomplete receipt cannot commit. UPDATE/DELETE of existing evidence, including bulk/direct SQL, is rejected before mutation by DB triggers; mapper events add an additional ordinary-ORM refusal. Statement-level BEFORE TRUNCATE triggers also reject whole-table evidence deletion. This does not protect against a privileged database administrator deliberately disabling safeguards; rollout must use a constrained application DB role.

Upgrade checks owned relation/function collisions before DDL. Downgrade first verifies all owned tables exist, then locks all three `ACCESS EXCLUSIVE` within bounded local lock/statement timeouts, checks emptiness and exact metadata ownership, and only then removes owned objects without CASCADE. The lock closes the gap between checking empty data and a concurrent insert. Owned internal FK dependencies are allowed only after their exact definitions are verified; foreign dependencies/index expressions/partial indexes/triggers/functions are refused. Offline downgrade cannot certify ownership/data and emits no destructive SQL.

The 000003 historical table snapshot is unchanged; complete active source inventory is now 50 tables across 28 model modules. Inventory size is structural coverage, not a claim that all application data/flows are certified.

## Synthetic service boundary

`SettlementLedgerService.record_synthetic_receipt(data)` is **not a webhook API** and is not available from any public route. It only accepts `source=synthetic` and `merchant_context=isolated-tests`. `SYNTHETIC_SETTLEMENT_ENABLED` is false in all default configuration classes and cannot be activated by an environment variable.

The service refuses before any SQL unless Flask testing is explicitly true, the flag is explicitly opted in, the isolated runner markers are present and the existing resource validator proves a loopback-only OS network namespace, private runner-owned Unix socket, UUID test database, engine/config identity and safe factory connection settings. A forged marker alone, production-shaped configuration, remote target or custom bind cannot open the service. The provider source values `stripe`, `nowpayments`, refund or live merchant identity are refused; no credentials are read.

Before creating or replaying evidence, the service additionally checks migration head, the canonical enabled immutable/deferred trigger set and pinned function body hashes (including the order's immutable trigger), exact trigger/function execution attributes, duplicate-identity unique constraints and FK definitions. `session_replication_role` must be `origin`; replica sessions that would skip normal triggers are refused. Function hashes are literal runtime constants, not imports of mutable migration code at request time.

The normalized input has exactly seven allowed keys. Event keys, canonical lowercase UUIDs and hashes are bounded/validated; integer prices reject booleans/floats/coercion. Payload digest records identity of supplied synthetic evidence; it is **not proof of a provider signature or receipt of funds**. A real adapter must authenticate and bind source evidence before using a future provider-enabled service.

## Transaction and concurrency protocol

The service locks the immutable order, verifies its snapshot/column integrity and exact price/currency, checks existing source identity and records receipt, journal and two entries within one nested savepoint. It owns no outer commit. Local lock timeout is 3 seconds and statement timeout 5 seconds; no retry loop or external I/O is inside the operation.

Before releasing the savepoint, only the named ledger deferred constraints are forced IMMEDIATE and restored DEFERRED. An internal partial-write error therefore rolls back the entire new ledger set even if the caller catches the error and commits its outer transaction. An outer rollback also removes all newly created ledger evidence.

An identical source-event replay returns the original receipt/journal IDs after rechecking the frozen order and exact recorded lines. Changing order, money or payload digest for the same identity returns a conflict. A distinct source event for an already recorded purchase order is refused. Different locked orders that compete for the same source identity are arbitrated by the unique DB key; the losing savepoint cannot leave an orphan receipt. No duplicate-success heuristic, second charge or second journal is used.

A successful service result means **uncommitted synthetic evidence was staged** until the caller commits. It never means paid or finalized by a provider. Transport/webhook success acknowledgement must wait for the eventual adapter's verified durable commit and cannot be inferred from this internal return value.

## Verification and rollout

Run in the exact locked isolated Python environment:

```sh
python backend/scripts/run_security_tests.py -q
python backend/scripts/run_security_tests.py -q -n 2
python backend/scripts/run_staging_integration.py -q
```

Tests build the actual Alembic graph, not `create_all` as a substitute, seed explicit fictional legacy-required fields, create a real server-priced quote and exercise the actual service in independent PostgreSQL sessions. Coverage includes balanced persistence, replay/conflicting identity/order, malformed input, concurrent winners/refusals, outer rollback, injected flush failures with caller commit, DB deferred invalid-state rejection, DB immutability, metadata collision/ownership and isolation/readiness refusal. Existing quote/payment/CSRF/role security regressions remain gates.

All evidence belongs to a draft branch and must be bound to an exact tested commit. No production upgrade/rollout is authorized by test success. Existing unsafe wallet arithmetic/autocommit/transfer paths are **not migrated or certified** here; baseline balance reconciliation and approved ledger-to-balance/withdrawal/refund rules remain separate Stage 4 work. A missing legacy wallet is not silently inferred to have a verified zero balance.

The next Stage 4 dependencies remain provider sandbox selection and immutable receipt-to-order binding, ledger reconciliation, source-deduplicated atomic balances/refunds/withdrawals, bounded exactly-once entitlement outbox and approved affiliate qualification/rates. Stage 5 proves actual MT5 lifecycle; Stage 6 proves the customer journey; Stage 7 proves performance/operations. No promise of zero bottlenecks follows from this bounded ledger proof.
