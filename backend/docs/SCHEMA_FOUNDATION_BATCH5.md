# Full active-model inventory and additive schema foundation — Batch 5

This patch remains in the existing draft PR. No production DDL, deployment, account promotion, tenant assignment, data backfill or financial transaction was performed.

## Model inventory

`src/schema_inventory.py` discovers every active model source file with AST, loads all 26 model modules, checks mapper configuration, and verifies all 46 literal table declarations are represented in SQLAlchemy metadata. Errors are not skipped. Full imports require the scrubbed isolated staging runner and its validated synthetic PostgreSQL target before application model imports. AST-only discovery does not connect to a database.

The legacy `programs` table is an external FK target of `affiliate_referrals` and is created by historical revision005. It is not a dummy table or an active ORM declaration; all new FK targets exist in the real migration-replay database.

## New revisions

### `20261011_000003`

Creates the 34 previously absent model tables using a static source-reviewed Alembic snapshot: 476 columns,56 foreign keys,53 indexes and7 unique constraints. There are no runtime model imports, `create_all`, stamps, seed rows, automatic table adoption or changes to existing columns. Create order is FK-topological and drop order reverses it.

**Upgrade:** collision with any owned table causes refusal before the first DDL operation. Out-of-band existing schemas need a separately reviewed compatibility/baseline plan, not `IF NOT EXISTS`, silent skipping or fake stamping.

**Online downgrade:** refuses before any drop if any owned table is absent or any contains data. **Offline downgrade:** explicitly unsupported and refused; an SQL generator cannot certify ownership or emptiness. Never execute partial output from failed SQL generation. Offline upgrade SQL is generated successfully, but applying it to an existing target still needs catalog preflight and transactional execution.

### `20261011_000004`

Adds `users.can_create_same_role BOOLEAN NOT NULL DEFAULT FALSE` and three nullable physical fields: `available_balance NUMERIC(12,2)`, `total_withdrawn NUMERIC(12,2)` and `payout_count INTEGER`.

Existing user records retain role, tenant, parent and token version. **No same-role permission is granted** and no root principal is selected. Existing financial fields remain **NULL = unknown**, not reconstructed zero. No financial server default, ledger inference or update/backfill is added; existing Python-model defaults are unchanged.

Online collision preflight refuses before adding any column. Downgrade refuses if the flag is true or any financial field is non-NULL, including numeric zero. The offline004 reversal emits the equivalent data guard, but predecessor003 refuses offline destructive reversal entirely.

## Verification

Run only in an isolated Python environment with `requirements-security.lock`:

```sh
.venv/bin/python backend/scripts/run_security_tests.py -q
.venv/bin/python backend/scripts/run_security_tests.py -q -n 4
.venv/bin/python backend/scripts/run_staging_integration.py --junitxml=staging-junit.xml
```

Evidence: **153 backend security/policy tests** pass sequentially and with4 workers; **32 isolated PostgreSQL18/Redis/schema tests** pass, with offline upgrade SQL passing. Six user-field tests prove identity preservation, unknown financial NULL preservation, exact values retained on refused downgrade, collision refusal and clean re-upgrade. Eleven pure role regressions preserve the current explicit same-role capability rules; they do not resolve the wider Platform Root policy.

All 46 declared tables exist at fresh final head `20261011_000004`. The 34 new tables are checked against all loaded metadata for columns, types, nullability, PKs, defaults, FK actions, indexes, unique constraints and check constraints.

## Explicit remaining gates

**All tables present does not mean full application parity.** Full model comparison still records41 missing columns (8 required),25 nullability differences and9 type differences in legacy tables. Some differences preserve wider legacy Numeric precision. No blind casts, precision shrinkage, default retrofit, approval backfill or tenant assignment was attempted. Zero reported server-default mismatch concerns explicit ORM server defaults only, not equality between Python defaults and legacy SQL defaults.

Existing production schemas may already contain many new tables or columns. These revisions intentionally refuse such collisions and are not a one-click live-schema migration. A read-only reconciliation and data-preserving forward plan must precede live application.

Platform Root has inconsistent current predicates (capability flag versus parentlessness), hierarchy writers use different delimiters, and non-root missing-path scoping needs a fail-closed policy. Brand routing is not an authorization boundary. Decisions about root identity, brand ownership, entitlements, payment/approval states and legacy program mapping require explicit policy; never infer them from historical bootstrap identities or arbitrary defaults.

Before financial use, audit all consumers that turn `NULL` into `0`; this migration certifies neither balances nor payout history. Browser E2E, KYC, broker/risk mathematics, payment ledger and measured load remain separate acceptance gates.
