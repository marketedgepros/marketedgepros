# Single-brand MVP identity and rollout gates — Batch 6

## Approved operating scope

The launch product is a **single-brand prop platform**, with one platform owner, ordinary trading users, and a single-tier affiliate program. Multi-brand/white-label management and expanded master/supermaster hierarchies are **future features**, not MVP release requirements. Their records and code are retained, not deleted.

Canonical launch roles are `supermaster` for the designated owner, `trader` for users, and `affiliate` for partners. Existing `agent` is accepted as an affiliate alias; existing `guest` remains a limited ordinary-user role. Future manager roles cannot authenticate in launch mode.

## Server-controlled authority

- `PLATFORM_ROOT_USER_ID` must identify a reviewed, existing database principal. There is no first-supermaster fallback and no email-based privilege grant.
- Owner eligibility additionally requires explicit `parent_id IS NULL`, a complete hierarchy identity/path, existing `can_create_same_role=true`, active status, and verified status.
- Missing/malformed owner configuration fails closed. This change does not promote accounts or set flags.
- `EXPANDED_HIERARCHY_ENABLED` is **false** in production/development configuration. Older integration fixtures explicitly enable the future mode to keep their regression coverage; separate tests exercise the launch mode.
- Ordinary launch sessions require a known tenant matching the configured owner's tenant. Tenant IDs are retained as internal ownership boundaries, not a white-label product.
- Launch public brand information derives from that owner association, not a Host/header/first-tenant fallback. Unknown ownership yields an explicit unavailable response.

## Active and inactive surfaces

- Owner and ordinary-user authentication use the same principal guard for login, authenticated requests, and refresh.
- The launch owner can create ordinary users; creation is owned and canonical, without granting capability flags from request data.
- Expanded hierarchy endpoints and white-label management return explicit disabled responses in launch mode. Public current-brand information remains available once ownership is configured.
- New affiliate activation is intentionally blocked until approved bonus terms and the affiliate workflow are implemented. The historical hard-coded commission percentage must not become a new MVP commercial promise.
- Existing active affiliates can be attributed by registration, within the owner brand. An eligible referrer must be an active affiliate/legacy-agent principal in launch mode, not a future master. Registration creates a pending referral and increments a count; it does **not** credit a bonus.

## Atomicity and hierarchy defense

1. Admin account, canonical path, optional referral code/profile are committed once after validation. Path failures roll back the account.
2. Registration selects the configured owner and known brand before provision, then commits User, path, referral/counter, and verification record once. Notification is after commit only.
3. Request ORM scope snapshots scalar fields; invalid non-root scope denies data. User predicates use actor ID or a literal escaped slash-bounded subtree plus tenant equality. Aliases and ORM bulk update/delete are covered.
4. Listener registration is idempotent. Already cached identity-map objects, raw SQL, and instance flushes still need explicit route/service authorization.
5. New paths refuse unknown/noncanonical parent paths and excessive length. Ancestor traversal detects repeated IDs and caps depth at 128. Referral-code retry caps at 32 attempts; DB uniqueness is still the race gate.
6. Future hierarchy views have bounded response size/depth, offset <=10,000, iterative tree assembly and batched counts. These are not production-load guarantees, and future concurrent reparenting is not solved by this batch.

## Required before production rollout

- Verify the actual live owner and primary brand association, then configure its stable ID. Do not guess or silently repair production ownership.
- Reconcile required MVP schema/data in a restored copy. Preserve future/test records and monetary facts; do not manufacture balances, paid states, approval states or bonuses.
- Check role transitions/session invalidation, tenant membership, private KYC, transaction rollback and restored-copy migrations for the specific release.
- Do not enable future hierarchy or multi-brand features to make launch tests pass.
- Do not merge/deploy this draft before the data and configuration gates are satisfied. The live site is not updated by this PR.

## Verification

Use the isolated `backend/scripts/run_security_tests.py` runner and Unix-socket-only `backend/scripts/run_staging_integration.py`, not production environment variables or legacy root fixtures. CI remains testing/build/rehearsal only; this change adds no deploy workflow.

The private implementation report and JUnit artifacts record the actual final counts for this batch. Affiliate link UI, bonus eligibility/rate, commission ledger, payouts, browser E2E and real load tests are separate acceptance work, not claimed complete here.
