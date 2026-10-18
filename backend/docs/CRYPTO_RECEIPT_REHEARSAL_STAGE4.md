# Original Stage 4 — provider-neutral crypto receipt rehearsal

The user intends to receive USDT and additional currencies through their wallet. The wallet service identity, API and supported networks have not yet been supplied; an authenticated connection is planned later. This package prepares a **pure offline comparison contract**, not a wallet integration, blockchain verifier, provider webhook, payment receipt inbox or settlement rollout.

No Stripe/NOWPayments service is selected. No connector is enabled, credential requested/read, wallet imported, API contacted, transaction signed, payment/refund/payout sent or contract deployed. There are no new routes, tables or migrations and no change to the previous synthetic USD receipt ledger.

## Explicit order-to-asset quote proposal

`build_rehearsal_binding(order, quote, now=...)` produces a frozen in-memory proposal with a canonical content hash. It requires explicit order identifier/hash/owner/tenant/USD minor amount and an explicit quote identity, merchant context, asset identity, network identity, asset precision, receiving address, optional memo, crypto amount and bounded quote window/finality threshold.

It does **not** derive a token amount from the order's USD cents. In particular USDT is not automatically treated as USD at parity. A later adapter must obtain and freeze an authoritative conversion/price quote from the chosen service, including expiry and applicable fee policy. The current proposal only compares caller-supplied data, which can be fictional or wrong; neither its hash nor frozen dataclass proves provider/merchant authenticity or a valid economic rate.

Asset/network strings are required identities, not a configured allowlist. Test fixtures may name fictional assets/networks with arbitrary explicitly declared precision. No USDT contract address, network, decimals, recipient address or confirmation count is chosen for production. A real adapter must resolve and verify a versioned asset registry and correct chain/token contract or native asset; symbols alone cannot identify a token.

Recipient and memo are exact bounded ASCII values. This protects the comparison from omissions/mismatches but does **not** validate a real address checksum or chain-specific normalization. Such rules depend on the wallet service and selected network. The amount parser uses canonical positive decimal strings and explicit precision 0–30, returning exact integer base units without float, coercion, scientific notation or rounding. Amounts are capped at 36-digit base units. All scalar inputs are bounded; booleans cannot stand in for numeric claims.

Quote lifetime up to one day and finality count bounds are engineering input limits, not an approved customer promise or production confirmation policy. Values are supplied explicitly; no defaults activate any asset/network. The quote window is evaluated with caller-supplied integer epoch seconds and has not been checked against a provider clock. At expiry, classification is blocked rather than silently extending a rate.

## One observation at a time, never payment authorization

`assess_rehearsal_transfer(binding, transfer, now=...)` compares an exact normalized transfer against the proposal. It reconstructs and validates binding contents before comparison so a directly constructed/replaced dataclass cannot bypass field validation or silently change a price/address.

Mismatched merchant/asset/network/precision/address/memo, a future/expired proposal, noncanonical-chain observations, underpayment, overpayment and incomplete finality receive explicit distinct classifications. Only exact amount and identity with claimed sufficient confirmations/finality/canonicality produce `matching_unverified_observation`.

**Every result, including an exact match, has:** `authenticated=false`, `paid=false`, `credit_authorized=false`, `entitlement_authorized=false`, `persisted=false`. These are not optional. A caller's `finalized`/`canonical` booleans and confirmation count are untrusted observations; no RPC/node/provider checked them. Under/overpayment is merely classified: no credit, aggregation, refund, tolerance or fee decision is performed.

The proposed event key hashes merchant context + network + transaction ID + transfer index. It distinguishes separate token-transfer logs/outputs in one transaction while staying stable when confirmation count or observed block changes. A separate observation digest captures those changes. Opaque transaction IDs must be canonicalized and authenticated by the real chain adapter later; this offline hash does not validate transaction identity across differing case/encoding.

No observation collection, database unique constraint, durable inbox, event lock, reorg reversal or deduplication is implemented here. Identical observations compute identical proposed keys but are not recorded as processed. Multi-part payments, multiple network outputs, gas/native fees, conversion, confirmations-after-expiry and reversal policies remain explicit future work.

The prior `SettlementLedgerService` accepts only isolated synthetic USD receipts and is **not called** by this module. Passing a crypto observation to it cannot create a live-provider receipt. Real durable settlement will require a separate versioned binding/event protocol and validated source before granting any order entitlement.

## Tests and later secure connection

Run through the locked, network-isolated security runner:

```sh
python backend/scripts/run_security_tests.py -q -k crypto_receipt_contract
python backend/scripts/run_security_tests.py -q
python backend/scripts/run_security_tests.py -q -n 2
```

Engineering tests use fictional assets, networks and recipient strings. They prove exact-unit parsing, immutable proposal reconstruction, strict scalar/shape validation, identity mismatch, finality/expiry classifications, stable transfer identity and unconditional non-authorization. They are not sandbox delivery or live on-chain proof. Full branch CI must stay green for security, frontend build and real PostgreSQL/Alembic rehearsal.

The secure connection needs the precise wallet service name/API docs, receiver account context, receive-only permissions and secret storage, authenticated webhook or read API, asset/network registry and explicit supported currencies, price/expiry/fees and confirmation rules. Private keys/seed phrases are not needed for a receive-only integration and must not be imported to the app. No broad write/withdraw permissions should be introduced just to observe incoming transactions. The actual API capabilities/credentials will be reviewed once that service is identified.

Original Stage 4 remains in progress. Quote/ledger foundation, read-only balance diagnostics and this offline crypto contract are prerequisites; they do not close payment authenticity, wallet balances, refunds/withdrawals, entitlement outbox or affiliate policy. Stages 5–7 numbering remains unchanged.
