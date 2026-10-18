# Stage 4 — immutable order quote foundation

This is the **first work package inside original Stage 4**, not the completion of the payments/ledger/affiliate stage. No production configuration, customer, balance, provider, charge, refund or entitlement has been changed. The pull request remains a draft and must not be blindly deployed over the legacy installation.

## Quote protocol

`POST /api/v1/orders/` requires the actual authenticated principal, cookie CSRF when applicable, and an `Idempotency-Key` of 16–128 ASCII alphanumeric/underscore/hyphen characters. The only body fields are `program_id` and optional `addon_ids`. At most 20 distinct positive add-on IDs and 4096 bytes of strict UTF-8 JSON are accepted. Duplicate fields, NaN, malformed JSON and client money/identity/status overrides are refused. Browser CORS explicitly allows `Idempotency-Key`.

Quotes are disabled by default. `ORDER_QUOTES_ENABLED=true` and an explicit `ORDER_QUOTE_CURRENCY=USD` are required. USD cents is the only implemented quote denomination; this is not a merchant currency decision, multi-currency support, tax/discount calculation or payment integration. Test fixtures explicitly opt in with synthetic USD prices. Production requires review of pricing, settlement and release configuration before opt-in.

The service refreshes the stored principal and resolves the same configured-root active brand as the launch middleware. The selected program must belong to that brand and be active. Every requested add-on must exist, be active and belong to the exact program; unknown, foreign, inactive or duplicate IDs are rejected rather than silently ignored. The owner is not supplied in a body; even root cannot retrieve another user's quote through the quote read API.

Price uses `Decimal` only. Fixed lines use the stored fixed price; percentage lines use the base program price and quantize to USD cents with `ROUND_HALF_UP` per line. This provisional explicit quote arithmetic matches the existing additive catalog contract and is frozen in each snapshot. Any future change to rounding, currency, discounts, tax or commercial terms must be explicit and versioned. No provider is called.

The immutable snapshot includes the actual catalog description/type/rules, payout and risk terms, selected add-on pricing/benefits, total, owner and brand. Unknown values stay unknown; no missing business status or rule is backfilled. Price changes after quotation cannot silently change a replay. A new purchase uses a new key; there is no claim that a quote has an approved expiry or is a binding paid entitlement.

The first request persists `state=quoted`, positive integer `amount_minor`, explicit USD, a canonical SHA-256 snapshot, a normalized request digest and a UUID. The unique `(user_id,idempotency_key)` constraint is the final concurrent authority. Equivalent replays return 200/the original quote; the first creation returns 201; the same key with different selection returns 409. A nested savepoint contains the losing insert without committing the caller's outer transaction. PostgreSQL uses shared catalog locks plus local 3-second lock and 5-second statement budgets. There is no retry loop, external network call, payment row, wallet deposit, commission or MT5 provisioning inside quote creation.

`GET /api/v1/orders/<id>` returns only the owner and current trusted brand's quote. It checks stored snapshot integrity, returns a money string and integer cents, and explicitly reports `paid=false`. Unavailable quote configuration/storage returns a refusal rather than a success placeholder.

## Frozen schema and immutability

The additive revision `20261011_000006` follows `20261011_000005`; old revisions are not repurposed for the new table. It creates `purchase_orders`, indexes and named check/unique/FK constraints. Database triggers protect snapshots from UPDATE/DELETE, including direct SQL and bulk ORM; the model also rejects instance updates/deletes. Future settlement belongs in separate verified-event/ledger tables, not mutation of this price evidence. The runtime additionally checks the exact revision and canonical enabled trigger/function (including absence of a conditional WHEN clause) before accepting or returning a quote; an enablement flag alone is insufficient. Snapshot integrity compares amount/owner/brand/program columns to the hashed contents. SQLite quote storage is allowed only in testing.

Migration rehearsal proves collision refusal before DDL, canonical metadata and constraints, duplicate-key rejection and immutability. Downgrade requires an empty owned table and exact metadata ownership; it never silently deletes purchase evidence. Offline downgrade cannot certify rows/ownership and is refused. The full source inventory now has 47 active model tables; historical revision-000003 coverage remains a separate 46-table inventory so its frozen snapshot does not change.

## Unsafe legacy checkout containment

Historical routes could accept client prices/free/cash statuses, expose unbound provider IDs, acknowledge a truthy non-success Stripe result, invoke MT5 while confirming, or start a pending challenge without a payment check. These mutation/provider paths now return `503 ORDER_SETTLEMENT_NOT_CONFIGURED` after existing authentication/role/CSRF checks and before lookup, mutation or external work. There is no flag or expanded-role escape hatch.

This gate covers legacy payment creation/intent/confirmation/refund/provider-status, crypto creation/status/currency discovery, program purchase, direct challenge creation/start, and legacy cash/free approval creation/approval. Historical payment-list reads stay owner-scoped with page 1–1000 and per-page 1–100.

Provider callbacks perform only local verification: Stripe uses the locked real SDK signature verifier; NOWPayments verifies strict recursively sorted JSON using HMAC-SHA-512 and fails closed without a configured secret. Their read budgets are 64 KiB; malformed/ambiguous/nonfinite inputs are refused. NOWPayments numeric interoperability is deliberately incomplete: floating-point literals are refused until a provider adapter is tested against real sandbox fixtures. Neither webhook ACKs valid payment settlement: a valid signature still receives 503 because no verified-event ledger adapter exists yet. Such a response will cause provider retry behavior and is one reason this incomplete package is **not production-ready**.

Official NOWPayments format references: [IPN setup](https://nowpayments.zendesk.com/hc/en-us/articles/21395546303389-IPN-and-how-to-setup) and [official Node SDK](https://github.com/NowPaymentsIO/nowpayments-sdk-nodejs). No supplier sandbox or merchant account has been accessed.

## Proof and remaining Stage 4 work

Full-factory HTTP tests use synthetic database-backed users and actual JWT/CSRF mechanics. No auth decorator or signature verifier is mocked into granting access. Outbound provider/MT5/email functions are canaries. Private PostgreSQL tests build the real full Alembic graph and exercise identical-key and conflicting-selection races through the actual quote service, verify the winner/replay/refusal and prove outer rollback removes an uncommitted quote. Four negative runtime-readiness cases refuse an old revision, disabled trigger, replaced function or conditional trigger before inserting. Separate migration tests also exercise PostgreSQL triggers and frozen DDL, including foreign expression/partial-index refusal before any cleanup. Fixtures supply explicit synthetic legacy-only fields (slug/program_type/addon_type) rather than altering production defaults or schema.

The remaining original Stage 4 acceptance gates are unchanged: provider choice and sandbox adapter, immutable provider-to-order binding, verified event inbox with receipt deduplication, atomic ledger reconciliation, exactly-once entitlement through a bounded outbox, refund/withdrawal consistency and approved affiliate qualification/commission policy. No fees, refund rights, affiliate rates or cash/free attestation are assumed.

Existing wallet/commission/withdrawal services are not certified by these quote tests. Legacy wallet reads may create rows and arithmetic/transfers need atomic Decimal source-deduplicated ledger work. Administrative funding, simulated trading and manual MT5 endpoints are not certified here; they remain subsequent business/trading gates. No statement about zero bottlenecks or complete financial correctness follows from successful quote creation.

## Validation commands

```sh
python backend/scripts/run_security_tests.py -q
python backend/scripts/run_security_tests.py -q -n 2
python backend/scripts/run_staging_integration.py -q
```

Use the exact locked Python test environment in `backend/requirements-security.txt`. Runners establish OS-level network isolation and remove provider secrets before model/application imports. Evidence must refer to the exact draft commit and successful CI; this document intentionally does not hard-code moving test counts.
