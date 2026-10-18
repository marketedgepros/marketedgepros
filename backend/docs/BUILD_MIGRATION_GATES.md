# Build and migration gates — Batch 4

This work stays in the existing draft PR. No production deploy, ownership backfill, real-user provisioning, or production migration has been performed.

## Reproducible frontend

Use Node 22 and the package-manager version declared in `frontend/package.json` (pnpm 11.25.0). From `frontend`:

```sh
pnpm install --frozen-lockfile
pnpm test
pnpm build
```

The lock importer now contains all dependencies already declared by the application; declared dependency specifiers were not arbitrarily upgraded. pnpm's script allowlist enables esbuild only. Dedicated clean copies without `.env`, local node_modules or previous dist pass installation, six Node tests and production build.

Three broken affiliate management lazy imports now point to the existing canonical `pages/agent` components, while `/affiliate/*` routes and allowed-role guards remain unchanged. Malformed legacy layout wrappers re-export the existing canonical affiliate/trader layouts. No placeholder screen or new product permissions were introduced.

## What build success does not certify

- Node route inventory tests are static source-contract checks, not browser E2E or backend authorization proofs.
- The existing duplicate `/affiliate` public/protected routing remains a separate product-contract decision.
- `/grid.svg` is referenced by four pages but is absent. This is a missing decorative runtime asset, not a bundling blocker.
- Production dependency audit still reports high/moderate advisories. A frozen lock is a reproducibility guarantee, not proof that dependencies have no known vulnerabilities; security upgrades require controlled compatibility tests.
- KYC end-to-end, payouts, broker workflows, loading/error states and load/scalability remain separately tracked.

## CI boundaries

The workflow contains only focused backend tests, frontend frozen install/tests/build, and isolated PostgreSQL18/Redis migration rehearsal. Artifacts are retained for review, not published or deployed. No production secrets are supplied. A passing workflow must not be interpreted as production-schema parity or product acceptance.

## Migration evidence

The precise migration graph, online/offline rehearsal results and remaining schema drift are recorded in the Batch 4 implementation report and JUnit properties. Migration commands are run only in a disposable namespace with private sockets and newly created synthetic databases. No `create_all` or fake Alembic stamp is allowed as a substitute for migration replay. Forward-only fixes for already-applied history must be separately represented in new revisions.

The final graph head is `20261011_000002`: an explicit two-parent merge is followed by an additive token-version invariant fix. Historical bootstrap revisions retain their IDs but no longer create known login credentials or sample business rows; their downgrades do not delete such rows. Existing already-applied history is not rerun. Legacy nullable-token rehearsal places an actual NULL and a separate version 7 in synthetic rows, then verifies only the NULL becomes 0.

The isolated suite passes **16 tests**, including the six real PostgreSQL/Redis protocol tests, complete migration replay/downgrade/re-upgrade, and target-guard negative cases. This proves graph reachability, not full application-schema parity. Loaded metadata lacks 16 tables, nine required columns and nine matching types; static inventory of all model source declarations reveals 18 additional unloaded missing tables, so **at least 34 declared tables are absent from the fresh migration-only schema**. JUnit retains both scopes separately. This is not a claim that those tables are missing from the production server, which was not modified or queried in this batch.

## Reachable affiliate screens

The newly reachable canonical affiliate pages now use only authenticated current-account `/affiliate/referrals`, `/affiliate/commissions` and `/affiliate/dashboard` routes, with actor identity chosen by the server. They no longer provide client-selected user/agent IDs, nested affiliate layouts, mock trader rows, hard-coded reports, or synthetic performance metrics. Malformed responses fail explicitly, missing scalar values remain unavailable, and valid empty lists are empty states. The frontend suite now passes eight tests, including synthetic Axios adapter URL/response contracts. Period rankings, broker P&L and report export remain explicitly unavailable rather than simulated. Browser E2E and broader tenant invariants are still release gates.
