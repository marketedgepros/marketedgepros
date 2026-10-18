# Stage 3 — single-brand MVP identity/data acceptance

## Technical acceptance versus production release

Stage 3's MVP **development and isolated-data acceptance** consists of one stable configured owner, an active single brand, ordinary users/affiliates, safe account workflows, reachable schema shape and a preserved-data restore rehearsal. This does not assert that the live installation has been migrated or that payment/trading/customer-journey/load acceptance is complete.

All changes remain in the draft security-foundation PR. No production account flag, password, role, tenant assignment, service configuration, SQL version stamp or deployment is changed by the tests. Production rollout requires a reviewed fresh backup, exact preimages and separate authorization for identity/access changes.

## Canonical clean-install schema

The new head `20261011_000005` adds 41 frozen core fields that were absent from the historical migration graph. Every new field is nullable with **no server default or backfill**; historical unknown approval/payment/type/phase/payout/rules values remain unknown. The migration does not import mutable application models. Upgrade collision-checks the entire set before DDL. Downgrade refuses any non-NULL value (including empty strings/JSON) before any removal, and refuses blind offline destructive SQL.

All 46 active model declarations are loaded in the isolated inventory. No model table or column is absent at clean head. That is **shape availability**, not exact parity: historical precision, timestamp/nullability and default differences remain recorded. Existing wider monetary types are not narrowed and no economic value is inferred.

Named-object preflight checks the PostgreSQL relation namespace and every owned constraint before upgrade. Downgrade validates exact expected definitions and refuses missing/replaced objects or foreign CHECK/FK/index dependencies, including expression indexes, before any removal. Eighteen real PostgreSQL refusal tests capture executed SQL and prove no CREATE/ALTER/DROP occurred before the error. Subdomain uses the single model-canonical unique index, without a duplicate unique-constraint backing index.

## Legacy restored installation is a different deployment track

The audited backup has out-of-band schema changes already present despite an older Alembic marker. Its core columns already exist; only the reviewed monitoring table trio is absent from active-model shape. Running the new clean-install chain against it would correctly hit collision guards.

`run_restored_acceptance.py` restores the explicitly hash-checked private backup into a newly created PostgreSQL 18 UUID database in a private Unix-socket-only network namespace. It selectively rehearses the frozen missing monitoring DDL, verifies model shape, and **leaves the original Alembic marker unchanged**. It does not stamp the clean head or silently adopt existing tables. This labelled legacy-compatibility track is not a canonical full migration replay.

Production release must choose a reviewed compatibility/baseline procedure for that actual snapshot, not `upgrade head`, `create_all`, seed or `stamp head` as a shortcut. The isolated rehearsal supplies evidence and a recovery plan, not a production write-capable CLI.

## Pure ownership plan and preserved data

`launch_reconciliation_service.py` plans from explicit owner/brand IDs and existing facts. Owner eligibility must already exist: active/verified supermaster, no parent, exact root path/level and existing same-role capability. The designated brand must already be active. No first-row or email-based privilege selection is allowed.

Candidate ordinary/affiliate rows must have a bounded, cycle-free chain to the owner. Their stored slash or legacy-dot path must exactly prove that chain; level must agree. Existing other-brand rows are excluded, not transferred. A challenge referencing another/unknown program brand blocks the candidate plan. Missing token-version facts refuse planning.

The only proposed row changes are `tenant_id`, canonical `tree_path`, and `token_version + 1` to invalidate sessions with the old identity scope. Role, parent, level, activity, verification, capability, password, KYC, money, payment and challenge status are preserved.

Application validates the isolated runner target, locks and checks **all** preimages before any update, and runs in the caller's single transaction. Actual restored-copy checks prove trial rollback, idempotence, unchanged row counts, exact hashes of all non-user tables and exact user hashes excluding only those three permitted identity fields.

## Shared runtime authority and handler compatibility

Single-brand context, ordinary session checks and public current-brand information share the configured owner/active-brand lookup. Headers, Host, query parameters and first-active fallbacks do not select a brand. Missing/unavailable scope filters to no rows; conflicting caller tenant data is refused before mutation.

The configured root also requires that active brand and matching tenant. An inactive or unmapped brand cannot leave globally scoped admin access active. Health remains reachable; no implicit break-glass or new privileged account is created.

`token_required` supports explicit `current_user`, explicit legacy `user`, and handlers using `g.current_user` without adding a positional argument. URL arguments are retained. Signature inspection occurs once at registration, not by catching/retrying handler failures. Real HTTP tests demonstrate that a failing handler runs once, not twice.

Both modern and legacy expanded-hierarchy surfaces are disabled in MVP mode. White-label and future role records are retained. Affiliate activation/bonus rules remain Stage 4 work; accepting an affiliate principal is not a claim that bonuses or withdrawals are enabled.

## Repeatable verification

```bash
# Synthetic, secret-clean SQLite authentication/authorization regression suite
.venv/bin/python backend/scripts/run_security_tests.py -q
.venv/bin/python backend/scripts/run_security_tests.py -q -n 2

# Ephemeral Unix-socket PostgreSQL/Redis and clean migration rehearsal
.venv/bin/python backend/scripts/run_staging_integration.py

# PRIVATE local backup only — never upload the backup or supply production URL
.venv/bin/python backend/scripts/run_restored_acceptance.py \
  --backup /private/path/reviewed.dump \
  --backup-sha256 <reviewed-64-character-digest> \
  --owner-id <reviewed-existing-owner-id> \
  --brand-id <reviewed-existing-brand-id> \
  --report /private/path/restored-acceptance.json
```

The restore requires a private caller-owned regular file with no symlink path, an isolated virtual environment, and caller-owned runner resources. Environment cleaning occurs before application imports. There is no TCP listener or route to external providers; PostgreSQL runs unprivileged. The ephemeral cluster is removed in `finally`. Private logs/backup/row values are not CI artifacts.

Final counts, commit and CI are recorded in the private Stage 3 closure report. CI covers security regressions, locked frontend build and synthetic migration rehearsal. Private restored-data acceptance is intentionally local, not a public GitHub artifact.

## Acceptance boundaries for the next stages

| Area | What is established here | What is not established here |
|---|---|---|
| Identity | Owner/User/Affiliate and foreign/future principal rejection; owned profile/admin action matrix; real JWT/CSRF/version regressions | Every financial/trading route's resource-specific business authorization |
| Data | Reviewed single-brand proposal, copy-only application, unchanged economic facts, rollback/idempotence | Applying identity/access changes to production |
| Schema | Model columns reachable from clean migrations and available on reviewed restored copy | Automatic adoption/stamping of legacy out-of-band history; business-state backfills |
| Affiliate | Principal and referral ownership boundaries | Rate, qualifying event, attribution window, ledger or payout policy |
| Release | Reproducible isolated evidence | Browser E2E, supplier integration, load targets, production pilot |

Stages 4–7 remain the original payment/ledger/affiliate, trading/risk, customer journey, and operations/load/pilot sequence. Future expanded hierarchy/white-label development is excluded from the launch critical path.
