# Original Stage 4 — legacy balance reconciliation boundary

This package prepares read-only legacy wallet diagnostics and disables known unsafe legacy write paths in the draft branch. It does not import opening balances, issue a payment/refund/withdrawal, approve accounting records, or complete Stage 4. There is no new table, balance backfill, provider adapter, public reconciliation API or production rollout.

## What the diagnostics can prove

`src.services.balance_reconciliation.reconcile_snapshot` is a pure bounded read-only function. It compares supplied user identifiers, wallets and transaction projections with exact two-decimal integer arithmetic. It rejects floats/booleans/NaN, rounding and oversized snapshots; even a caller's low Decimal precision cannot alter the cents.

| Check | Meaning |
|---|---|
| Owner/row integrity | Missing/duplicate owner IDs, duplicate row identities, orphan transaction or unknown balance bucket are identified or rejected. |
| Per-entry arithmetic | Observed before/after differences must match recorded positive deposit/commission/bonus, withdrawal or adjustment magnitude. The observed sign of an adjustment is not inferred from its positive amount. |
| Chain continuity | Each observed before value must follow the previous after value. Stored bucket balance must match the observed closing value. |
| Stable ordering | Naive legacy timestamps and row IDs provide deterministic ordering. Equal timestamps are marked ambiguous; an ID tie-break is not proof of commit order. |
| Provenance gaps | Missing/reused `(reference_type, reference_id)` values are flagged across balance buckets and transaction kinds within one wallet. This is a conservative diagnostic, not a cross-wallet authenticity/duplication verdict. A reference existing in a legacy row is not proof its referenced provider/commission/withdrawal was authentic or final. |

An arithmetically continuous chain still has `verified_balance=false`, `source_provenance=unverified_legacy` and `currency=null`. A first `balance_before` is only an observed legacy opening value, not an approved opening balance. No USD currency, zero balance or payout right is inferred. The receipt ledger from the previous package books **unapplied receipt clearing**, not customer-wallet ownership; therefore it is not silently copied into these balances.

The final review also required lexical Decimal validation before normalization, a reference-reuse regression across kinds/buckets, and direct HTTP unauthenticated/non-admin/cookie-CSRF rejection tests. No provider settlement or balance approval is inferred from those tests.

`aggregate_summary` emits only aggregate counts/reasons. It omits row-level IDs, monetary values and identity details. Test fixtures are fictional engineering cases; actual data conclusions come only from the separately identified real backup, not from those fixtures.

## Read-only consistent database snapshot

`balance_snapshot_service.reconcile_readonly_connection` requires an explicit caller-owned PostgreSQL `REPEATABLE READ` or `SERIALIZABLE` **READ ONLY** transaction before it projects the entire user/wallet/transaction snapshot. It uses SQL Core, not ORM or `get_or_create_wallet`, and does not flush, commit or update anything. The transaction owns its consistency point; concurrent writers cannot create a mixed-time wallet/history snapshot.

All three sources have a maximum 10,000-row budget and `LIMIT budget+1`. Exceeding any budget refuses the report instead of truncating data and claiming completeness. A 5-second local statement timeout bounds each read. Missing schema/columns are errors, not an empty confirmed balance. Larger production reconciliation will require a separately designed consistent checkpoint/chunk protocol; this package does not pretend to support it.

The caller retains transaction ownership. A future operational caller must also apply authenticated authorization, constrained DB credentials and result redaction; the helper is not an authenticated service endpoint by itself.

## Legacy wallet compatibility boundary

The historical `get_or_create_wallet` name now means **read an existing exact owner-linked record only**. Missing wallets return `WALLET_NOT_FOUND` rather than creating and committing a zero row during a GET. Existing data is marked `unverified_legacy`.

The wallet service's add/deduct/transfer/adjust entry points and wallet model add/deduct methods refuse with `WALLET_LEDGER_NOT_CONFIGURED` before lookup or mutation. The old two-commit transfer cannot execute. Wallet admin adjust and wallet-route approval/rejection/completion handlers likewise refuse after authentication/authorization/CSRF, before body parsing, status writes or notifications. They are intentionally not replaced with a guessed payout protocol.

History/list query integers, page size and offset are bounded; malformed or duplicate query values refuse instead of falling back silently. Own-user reads remain owner-linked. Admin lists use explicit canonical-root or complete tenant/hierarchy scope, and ambiguous direct-user/agent withdrawal ownership is excluded. A page length is not mislabeled a full total: history returns `returned_count` and unknown `total`.

This is a containment change, not DB-wide immutability for the old wallet tables. Direct SQL, other legacy user balance/agent commission/payout paths and privileged administrator access are not certified by it. Future balance/payout activation must unify these separate sources rather than assume they are identical because they have similar names. The branch must not be deployed alone to replace a live checkout/payout system.

## Actual backup verification

The previously obtained private backup was restored into a temporary PostgreSQL namespace with no external network and inspected using a repeatable-read read-only transaction. All 47 restored table row counts and aggregate content digests were compared before/after the audit; they were unchanged. The backup file's SHA-256 remained unchanged and the temporary process was stopped/cleaned.

The backup contains 24 users, **zero wallets and zero wallet transactions**. It also contains zero payments and withdrawals; there are 13 legacy challenges, but no receipt-to-paid entitlement proof is inferred from that fact. No wallet value or current live state is confirmed by this historical backup. Missing wallet data means **unknown/uninitialized**, not an approved zero-balance opening.

Only sanitized counts and unchanged-content flags are deliverable. The backup, raw records, passwords, bank details or full digests of individual personal rows are not included in the PR or evidence bundle.

## Gates and remaining Stage 4 work

Isolated security/HTTP and real Alembic-constructed PostgreSQL tests must prove no GET writes, no wallet mutation/notifications on refused paths, correct owner/tenant limits, exact decimals, chain mismatch detection, missing-wallet semantics, row-budget refusal and repeatable-read consistency under a concurrent writer. The final commit must pass full CI and the PR stays draft.

A real provider sandbox and final receipt authentication, approved opening balances/currency, source-deduplicated wallet movements/reservations/refunds/withdrawals, entitlement outbox and affiliate rates/qualifications remain Stage 4 dependencies. No monetary import or commercial policy is authorized by the diagnostic report or test success. Original Stage 5–7 numbering stays unchanged.
