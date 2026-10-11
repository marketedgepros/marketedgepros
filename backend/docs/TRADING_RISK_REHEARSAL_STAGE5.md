# Stage 5 — draft rule versions and deterministic local risk rehearsal

## Scope in the original roadmap

This is the next package **inside Stage 5**, after MT5 containment. Stage 4 still requires wallet/provider receipts and immutable settlement/entitlements. It does not finish Stage 5, create a provider account, authenticate trading evidence, count trading days, move a phase or authorize suspension. No routes, model tables, migrations, connectors, worker schedules or production changes are added.

The fixtures in tests are synthetic calculation examples, **not approved MarketEdgePros or FXIFY program terms**. Do not activate these rules silently for existing customers. No losses, profit targets, timezone, reset hour, minimum days, leverage or broker group are chosen by default.

## Contract and exact arithmetic

`TradingRules` and nested `RiskLimit` are frozen in-process dataclasses. Every rule field is required: schema/version, program/phase, currency/scale, initial units, three limits, comparison and reference bases, drawdown mode, threshold equality policy, day reset and maximum observation age. Canonical sorted JSON includes all fields and yields a SHA-256 digest. A digest identifies content; it is **not approval, a signature, a DB uniqueness constraint, a persisted version or evidence of historical program terms**. Schema 1 is the only supported schema.

Amounts are exact signed integer currency minor units, bounded to magnitude `10^15`. A limit explicitly specifies `units` or `bps` (basis points). No floats, implicit amount/percentage conversion or Decimal-context rounding are used in the risk formulas. Fractions are serialized as exact numerator/denominator strings, including fractional minor-unit thresholds. Rounding policy for eventual display or provider orders is not invented here.

For example, `RiskLimit('bps', 1)` at a reference of `10001` minor units is exactly `10001/10000` minor units. It must not be rounded to `1` before checking a boundary. Currency/scale are explicit and observations must match them; there is no FX conversion or assumption that a stablecoin equals fiat.

### Supported narrow formulas

Let `I` be initial units; `D` be the explicitly selected daily opening balance/equity; `P` the observed peak for the chosen total basis; and `X` the current amount for the appropriate comparison basis. Define `L(r)` as the specified units, or `r × bps / 10000`.

| Metric | Exact definition |
|---|---|
| Profit target amount | `profit_target(I)`; compare selected current balance/equity minus `I` |
| Daily loss floor | `D - daily_loss(D)`; current comparison may explicitly use balance or equity independently of the opening reference |
| Static total floor | `I - total_loss(I)` |
| Observed trailing total floor | `max(previous_peak, current_total_basis) - total_loss(I)`; the percentage distance, if any, is relative to initial units, **not the current peak** |
| Loss threshold | Explicitly `< floor` or `<= floor` |
| Target threshold | Explicitly `> target` or `>= target` |

Trailing mode is named `trailing_observed`: it uses caller-provided ordered observations and a caller-provided peak, not proof of a continuous/intraday or end-of-day high-water mark. There is **no trailing floor cap**. Continuous sampling, EOD ratchets, caps at initial balance and other drawdown variants are deliberately unsupported, not inferred from legacy names. Limit `bps` values are explicitly bounded to `1..10000`; positive absolute-unit limits remain bounded by the money range. No rule is assumed to be a valid commercial policy merely because its data types pass.

The supplied equity must explicitly already include fees and swaps. Otherwise the result is unknown. Fees are not independently added/subtracted: this is a normalized-snapshot contract and does not perform fee accounting or trade execution arithmetic.

## Evidence prerequisites and local state

`evaluate_risk(rules, state, observation, as_of=...)` handles exactly **one** observation and explicit prior state; it returns diagnostics plus a new frozen state. Inputs use explicit tenant/challenge/provider/account identity, rule digest, sequence, event ID, UTC timestamp, day window, opening balance/equity, observed peak and local breach latches. Neither identifiers nor flags prove provenance. There is no HTTP JSON-to-object trust boundary or provider signature verification in this package.

Invalid typed inputs are rejected. Missing state/observation, mismatched identity/currency/scale/digest, stale or future data, sequence gaps/duplicate last ID, backward timestamps, an invalid day reset, mismatched day opening window or an incoherent peak produce `unknown` and preserve the original state. A peak must not be lower than the initial amount or the corresponding day-opening amount. Equal timestamps with distinct sequential events are allowed; sub-second freshness uses exact `timedelta` comparisons.

An accepted event advances the local sequence/last ID and observed peak. Local daily/total breach latches remain set even if the following observation recovers. A known local breach takes priority over a simultaneous local target signal. This does not mean the provider was suspended or the challenge passed.

Day rollover requires a new, explicitly validated opening-reference state. This calculator **does not generate or trust a reset state**, clear breach latches automatically, infer opening balances from the current observation, or reconstruct missing events from a truncated history. Trusted reset/state persistence, previous-day carryover and replay protection belong to the future event/state protocol. Only the last event ID and adjacent sequence are checked: complete inbox deduplication, history integrity and tamper-proof peak/latch reconstruction are not implemented.

Statuses are `unknown`, `local_breach`, `local_target_met` or `local_within_limits`. All results always set `provider_verified`, `authorized`, `persisted`, `phase_transition_authorized` and `account_disable_authorized` to false. Unauthenticated local results must not be relabeled as pass/funded/suspended.

## Explicit trading-day window

`trading_day_window(observed_at, timezone_name, reset_hour, reset_minute, reset_fold)` requires all five arguments. Observations use explicit `datetime.timezone.utc` or `ZoneInfo('UTC')`, exact datetime type and fold 0; a local/seasonal timezone merely at zero offset is refused. Operational local calendar dates are bounded to 1900..2100. An IANA timezone and reset hour/minute/fold are explicit.

The returned frozen `TradingDayWindow` contains a local reset date and canonical UTC start/end. Exact reset belongs to the next day window. Local calendar days are not fixed 86400-second durations: DST can produce 23/25-hour windows. Ambiguous reset uses the explicit `reset_fold` choice. A nonexistent reset in a required boundary is refused, never silently shifted. The calculation examines the current reset and at most two adjacent labels in the needed direction. It skips one label only when an exact 24-hour midnight date-line jump proves that the entire calendar date did not exist; an ordinary DST reset gap is still refused. No unbounded search, wall-clock read, polling or replay of a growing event list occurs. `ZoneInfo` resolves timezone definitions from installed system data, so this is not a claim of zero OS filesystem access; timezone database reproducibility must be pinned for eventual production acceptance.

These are calendar windows, not the number of eligible trading days. Weekend/session eligibility, minimum profitable days, time limits and holiday calendars are not computed.

## Validation and deployment boundary

Use the locked security environment and `backend/scripts/run_security_tests.py`, focused tests plus complete serial/parallel regression; existing PostgreSQL/Redis/migration rehearsal must still pass. Tests exercise exact threshold equality, fractions, static/trailing formulas, distinct bases, latches, matching identities/versions, freshness/order/missing prerequisites, timezone/DST and poisoned types. They do not validate any real customer balance or provider contract.

Remaining Stage 5 work: approved and durably stored/versioned program rules, verified ordered events and stable reset/state protocol, immutable Stage-4 entitlement → durable provisioning command → single account, idempotent inbox/outbox and uncertain-outcome reconciliation, then authenticated provider-test end-to-end acceptance. All legacy trading/provisioning mutators remain unavailable. Keep the PR in draft and do not deploy over live trading obligations without a reviewed release and rollback plan.
