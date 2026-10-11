# Stage 5 — durable synthetic rule, provisioning-command and event protocol

## Scope and integration boundary

This package adds three PostgreSQL tables, a frozen storage-readiness contract and one internal service for **isolated synthetic rehearsal only**. It is part of the original Stage 5, after the pure risk calculator, not a new roadmap stage. Stage 4 still requires a verified wallet/provider receipt and immutable entitlement. There is no public route, provider adapter, worker/queue consumer, scheduling, live account, actual entitlement or phase/violation action here. Existing live/trading/payment mutators remain contained.

`TRADING_PROTOCOL_REHEARSAL_ENABLED` is hardcoded false in configuration defaults (not an environment fallback). Every method additionally requires testing mode, the staging runner, OS network isolation, an owned PostgreSQL socket and exactly matching engine/factory resource configuration **before SQL**. Pending ORM mutations are refused before a savepoint could autoflush unrelated data. These are internal test operations, not an authenticated administration API.

## Durable records

| Record | Purpose and uniqueness |
|---|---|
| `trading_rule_snapshots` | Frozen canonical JSON, content rules_digest, program, phase and rules_version; tenant-context hash is the primary key so different brands are not merged; unique tenant/program/phase/version |
| `trading_provision_commands` | Durable **synthetic** command state and original attempt token; unique tenant/challenge/phase, including requests for different providers; unique provider/account acknowledgement |
| `trading_event_inbox` | Append-only normalized RiskObservation payload, event key, sequence and hash; unique provider/account/event and provider/account/sequence, not just the most recent ID |

Rule hash/version replay is only accepted with identical canonical content. A rule version cannot silently acquire a different threshold. A different rule version does not create another provisioning command for the same challenge phase. The program, challenge, owner and snapshot must share explicit tenant ownership; they are checked again when acting on the command. No tenant, opening balance, approval or initial rule values are backfilled into existing customer data.

`store_rules` validates a complete `TradingRules`, then stores its canonical JSON. This changes durability, **not approval**: fixtures can be commercially nonsensical and are still synthetic, never an approved customer policy. Installed timezone data is still not pinned inside the risk hash. Snapshot integrity checks re-hash content/context and verify program/phase/version. Future commercial rollout needs a reviewed approval/versioning protocol and historical obligations.

## No retry of an ambiguous provider attempt

```text
planned -> dispatched -> acknowledged
                    \-> uncertain -> acknowledged
```

- Planning is atomic and returns an existing identical command on replay, without calling MT5 or creating an `mt5_accounts` row.
- Claiming a `planned` command creates one UUID attempt token and records `dispatched` in the caller's transaction. A second claim is refused, even with another provider or after a timeout.
- `mark_uncertain` preserves that attempt token. There is deliberately no uncertain→planned reset, automatic resend, reassignment, lease expiry or reconnect/polling loop.
- `acknowledge` must carry the original attempt token. Replay with the same account is idempotent; a different account or wrong token conflicts. Account identity cannot be claimed by another command for the same provider.
- Times are explicit UTC, cannot move backwards for a command, and a new command cannot predate its rule snapshot.

The status names describe rehearsal rows, **not evidence that a provider accepted an operation**. No external acknowledgement/signature protocol is supplied. A failed dispatcher process would leave the recorded attempt to reconciliation; a persisted dispatch claim must commit before any future adapter may call a provider. A future adapter must also use the original provider idempotency token and verified reconciliation lookup: these DB constraints alone cannot guarantee exactly-once external effects.

The command record is a minimal durable command/outbox foundation, not a complete outbox delivery service. There is no SKIP LOCKED batch dispatcher, long-running task, delivery retry or automatic lease stealing. Error recovery intentionally favors uncertain/refusal over generating a duplicate account. Provider-reported not-found, definitive failure, cancellation/rejection and retry policy need an explicit provider contract before adding new transitions.

## Inbox deduplication is not verified state processing

`record_observation` accepts an exact typed `RiskObservation` only after acknowledgement and matching command tenant/challenge/provider/account and frozen rule digest/currency/scale. It stores normalized UTC microseconds, exact integer currency units and explicit fee/swap semantics. Future observation timestamps are refused. Payload carries `source=synthetic` and `local_only=true`; all response authorization/provider flags remain false.

Identical old events replay to the same inbox record even after other events arrive. Reuse of an event ID with changed content/sequence, or reuse of a sequence with a different event, is a conflict. SQL unique constraints are the final arbiter under parallel requests; no unbounded in-memory history scan is needed. No arbitrarily large raw JSON/webhook body is accepted by this method.

**The inbox may store out-of-order observations; it does not apply them.** Adjacent-sequence/freshness/day-opening logic belongs to the existing pure risk evaluator; this package does not trust raw inbox data, generate reset states, reconstruct peaks or update durable risk state. Missing provider identity scope, signing, tenant mapping, stream epoch/reset/reconciliation and origin evidence must be completed before claiming authenticated ordered state processing. Provider/account IDs currently must be globally namespaced within the selected provider identity; an authenticated integration will need explicit provider environment/server/account namespace mapping.

## Transaction and database boundaries

Caller owns outer commit/rollback. Internal savepoints are error boundaries, never an implicit commit. `created=true` means a row was created in the caller's still-open transaction; it does not prove committed delivery or provider effect. Rule replay, command planning/claiming/transition and inbox insertion use indexed identities and fixed work per method. Lock and statement timeouts bound failures. No full-history replay loop is introduced; this is not a production throughput/load guarantee.

Migration `20261011_000008` follows immutable ledger revision `000007` without altering historical revision bodies. Runtime requires the correct revision, origin trigger execution and canonical frozen storage metadata/functions; it does not import migration code during a request. Immutability and transition guards live in PostgreSQL in addition to service checks. Direct update/delete/truncate of frozen evidence is refused. An administrative database superuser can alter/drop safeguards; no claim is made against that actor.

Upgrade must refuse collisions before DDL. Downgrade must validate owned metadata, lock tables and refuse nonempty records or foreign dependencies before any drop; offline downgrade cannot inspect data and is refused. This is rehearsal DDL, not authorization to deploy to an existing production DB. Release planning still requires backup, restore rehearsal, live-schema comparison and rollback plan.

## Testing and remaining Stage 5 work

Tests must use real Alembic-built PostgreSQL on a disposable database inside the validated runner, not `create_all` as evidence of migration correctness. Required tests include identical and conflicting races, one-command policy across providers, one claim, uncertain outcome, token/account conflicts, nonadjacent inbox replay, outer rollback, direct SQL immutability/transition checks, storage drift and refusal before SQL outside isolation. Serial/parallel security regression and existing frontend/migration CI must remain green.

Still needed for Stage 5 closure: approved/versioned commercial program rules with timezone reproducibility; verified payment entitlement; authenticated provider namespace/events; durable ordered risk/reset state with coherent replay/reconciliation; operational outbox dispatch; actual provider-test single-account provisioning and a complete verified risk/phase-change workflow. This package does not close those dependencies or Stage 5 as a whole. Keep the PR in draft; do not deploy over live obligations without an approved rollout.
