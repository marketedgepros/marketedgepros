# Stage 5 — MT5 containment before verified provisioning

## Position in the original seven-stage plan

Stage 4 is **open** pending verified wallet/provider receipts, settlement, entitlements and the remaining payout/commission/refund workflows. Starting this independent portion of Stage 5 does not close Stage 4. This package is **the first part of Stage 5**, not completion of trading or a new stage in the roadmap.

## Why this boundary is needed

The previous `/api/mt5/accounts/create` generated a random login and placeholder password, used request-supplied balances and marked the account active without calling a provider. Disablement, balance adjustments and manual synchronization changed local state or timestamps while claiming remote success. Challenge routes could insert user-supplied simulated trades, evaluate mutable legacy balances, mark funding locally and delete trading history. None establishes paid entitlement or provider-confirmed account state.

The old SDK contained default endpoint/credentials, plaintext transport and layered retries including POST mutations. WebSocket handlers used an unauthenticated default stream and ticket-only matching. Legacy webhook code guessed a signing format using `str(dict)` and referenced unavailable model/task imports. Legacy monitoring marked violations and logged `account_disabled` before a provider acknowledged disablement. Some of these integration modules were not registered by the factory; this package does not claim they were all running in production.

## Current contract

All legacy MT5 provider calls are inert and raise `MT5ProviderNotConfigured` (`MT5_PROVIDER_NOT_CONFIGURED`, 503) before reading credentials, opening transports or inspecting caller data. No environment variable or flag can reactivate this undocumented adapter. The async challenge interface is retained but refuses provisioning, synchronization, parameter inference and credential delivery before a database lookup. Existing exception class names remain available to callers.

WebSocket start, connect, event handlers and progress updates refuse before parsing or side effects; stop is an inert local cleanup. No reconnection loop remains in this adapter. The unregistered webhook blueprint still returns 503 if separately mounted: callbacks neither parse bodies nor query accounts nor enqueue tasks. Its signature helper always returns false rather than pretending to validate an undocumented provider protocol.

Existing Celery monitoring task names are retained but return `success: false`, `provider_confirmed: false` and an unavailable code before queries, status changes or notifications. They do not assert a breach, provider suspension or synchronized state. A Celery invocation may complete at the framework level with an unavailable result; this is not successful monitoring. No beat schedule or worker configuration is installed or changed here.

The HTTP package preserves authentication, role checks and cookie CSRF before refusing provisioning/balance/suspension/sync, challenge evaluation/funding, simulated trade ingestion and destructive legacy history deletion. These are deliberate unavailable responses, not a fake sandbox. Ordinary read paths are local legacy snapshots, scoped by actual owner/brand and consistent challenge/program bindings, bounded and explicitly not provider-verified. They must not be treated as entitlements, risk rulings or fresh provider data. Credential delivery is not available from a mutable `paid` flag.

## What this does not change

No database schema or existing rows, roles, program rules, balances or credentials are migrated. The legacy MT5 password column and inactive backup/history may still contain previously committed or improperly encrypted material. This package removes defaults from active adapters, not Git history or external credentials; assess rotation and data classification separately before deployment. The legacy model's calculation and mutation helpers are not a new risk engine and are not certified by this boundary. Direct database administrator access is outside HTTP containment.

The independent service review identified `PaymentService.confirm_payment` continuing to activate and commit an account after provisioning failed. That legacy confirmation entry point now returns `confirmed: false` and `ORDER_SETTLEMENT_NOT_CONFIGURED` before secret/provider/DB access. This closes this specific activation path; it does not certify or enable the other legacy payment/refund helpers. Their public HTTP settlement boundaries remain unchanged. A legacy standalone MT5 improvement script still expects the removed network/retry adapter; it is not a supported live-provider acceptance test and must not be used to reactivate that adapter.

No provider is contacted and no trading account is created, disabled, funded or traded. No receipt is accepted and no ledger, payout or wallet mutation is enabled. No connector, production worker, service or firewall is changed. SDK readiness cannot be inferred from a matching URL or a test flag.

## Remaining work inside Stage 5

| Work package | Required evidence before enabling |
|---|---|
| Versioned Challenge/rule contract | Approved program rules with explicit amount/percentage units; immutable version and phase bindings; static/trailing drawdown definition, balance/equity basis, timezone, reset hour and threshold comparisons. No copying a competitor name as a substitute for rules. |
| Local deterministic risk rehearsal | Exact fixed-point/rational calculations; missing/stale/out-of-order evidence yields unknown; boundary/equality, trading-day/DST, simultaneous profit/loss, fees and reset scenarios. Pure calculations cannot grant entitlement or disable accounts. |
| Provisioning and event state machine | Verified Stage-4 settlement → immutable entitlement → durable provisioning command; one account per challenge/phase/provider identity, reconciliation of uncertain outcomes, inbox deduplication, transaction/outbox and bounded work. No blind retries after account creation. |
| Provider test integration and acceptance | Authenticated encrypted connection, documented signing/event IDs and broker/group mapping; isolated provider account; risk decisions bound to verified ordered events; provider acknowledgement before reporting suspension. End-to-end evidence including duplicate/concurrent events and recovery. |

Until these are implemented, Stage 5 cannot satisfy its original acceptance condition: verified payment → one provider account → verified trading event → risk calculation → phase transition or acknowledged breach handling in a provider test environment.

## Validation and rollout

Use the existing `backend/scripts/run_security_tests.py` runner from the locked security environment; run focused boundary cases plus complete serial/parallel regression and PostgreSQL/Redis/migration rehearsal. Tests use synthetic users, accounts, balances and messages with network isolation. No live account or merchant key is needed for containment tests.

The changes belong to the existing draft PR. Do not deploy this broad containment package blindly over a live provider integration or claim these changes are already running on DigitalOcean. Validate active routes, callers, worker schedules and existing real trading obligations, then use a separately reviewed release artifact and recovery plan. No automatic merge or production rollout is part of this package.
