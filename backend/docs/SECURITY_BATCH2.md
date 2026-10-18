# Security batch 2 — KYC, CRM, AI ownership and analytics

This extends the security foundation draft PR. It is not a production deployment, complete tenant migration, or full frontend KYC release. No schema changes are required for this containment patch.

## Implemented boundaries

| Area | New boundary | Compatibility / limitation |
|---|---|---|
| KYC | Real token decorator signature; persisted mapping from API document names to existing `User.kyc_*` columns. Authenticated owner/reviewer download with tenant and explicit bounded hierarchy predicates. | Existing reviewer roles (`master`/`supermaster`) retained. Root supermaster is limited to its tenant, not all NULL-tenant users. Legacy object references that cannot prove owner/type/path are unavailable. |
| KYC storage | Spaces uploads explicitly private; references persist as object keys rather than expiring signed URLs. Local storage is opt-in, service-owned 0700 root outside public uploads, 0600 files. Every path component opened with directory descriptors and `O_NOFOLLOW`. | Failure at Spaces does not fall back to local storage. Old objects and reverse-proxy exposure require separate verification. A DB failure after object creation may leave an unreferenced private object; retention/cleanup remains a separate task. |
| KYC download | `GET /api/v1/kyc/documents/<user_id>/<document_type>/download`, owner or existing permitted reviewer only. Attachment, no-store, no raw storage URL/filename input. Supports cookie and Bearer authentication. | Download is bounded to 10 MB. PDF/JPG/PNG upload magic/header check is not malware scanning or proof of genuine identity. |
| CRM | Every list/detail/notes/mutation/stats/pipeline query is scoped through assigned user's tenant and actor's self/downline, with escaped path predicates. Assignment/program targets validated before mutation. | Lead has no tenant column; unassigned/unknown-owner leads and NULL-tenant actors fail closed. Requires ownership backfill/tenant migration before a multi-tenant launch. Roles were not redesigned. |
| AI analysis | Signed-in owner + Challenge → TradingProgram → tenant verified before trade access and rechecked at service provider boundary. | Provider mocked in tests; actual OpenAI API contract, model, quotas, performance metric correctness and streaming scalability are not validated by this patch. |
| Analytics | Authentication/admin/tenant before cache lookup. Keys include actor, tenant, role, hierarchy, token_version and canonical bounded filters. Values are immutable bytes/status/header data, not live Responses, and are verified with the actual Redis serializer. HTTP aggregate queries enforce tenant plus explicit actor self/downline; root supermaster retains tenant-wide review scope. Commission totals also validate the referral/agent/referred-user chain. Query errors return 500 instead of cached fake zero-data success. | Cache keys do not implement a new RBAC policy or replace DB tenant joins. Direct service callers must now supply tenant_id. Metrics/complex joins require PostgreSQL staging validation. |

## KYC storage configuration for staging

Local private storage must be chosen deliberately. Create a directory owned by the actual runtime service user, with mode 0700, and configure:

```dotenv
KYC_ALLOW_PRIVATE_LOCAL_STORAGE=true
KYC_PRIVATE_UPLOAD_FOLDER=/var/lib/marketedgepros/private-kyc
```

Do not point it under `UPLOAD_FOLDER`, the frontend build, an Nginx alias, or a public object-store prefix. Do not use symlink components in the configured path. With Spaces configured, verify bucket/object ACL and existing object exposure; the patch does not change historical ACLs. Never print object signing credentials in logs.

The local fallback is false by default outside testing. If neither private Spaces nor explicitly configured local storage is ready, document upload fails rather than storing public files.

## Validation

Run the locked focused suite with the same runner as `SECURITY_FOUNDATION.md`. Real Flask/JWT/SQLite tests cover owner/reviewer access, two tenants, unrelated hierarchy trees, spoofed tenant filters, denied mutations with unchanged DB state, traversal/symlinks, private filesystem mode, mocked Spaces ACL, core and complex actual tenant aggregates, cache hit/miss, actual DB failure/recovery, and collector/worker network namespace inheritance.

Passing regressions are not proof that every historical user or UI flow remains compatible. In the audited snapshot, 11 of 24 users have no tenant; they must not be assigned arbitrarily or given a broad bypass to make tests/site screens work. Classify platform principals versus tenant members and rehearse the intended access matrix first.

## Gates before deployment

1. Confirm current server hashes and preserve unrelated drift; do not overwrite with a blanket checkout.
2. Use a staging copy and validate on PostgreSQL, including all legacy migrations and relevant tenant/role assignments.
3. Test runtime service filesystem permissions and object store ACL without real KYC files.
4. Verify the frontend upload/download contract. The old `KYC.jsx` references an undefined `kycAPI.submit` and does not implement the canonical flow; this backend patch does not certify the UI as ready.
5. Check Nginx/static aliases, historical Spaces URLs and generic upload paths independently of Flask.
6. Have a rollback artifact and post-release smoke tests before any production rollout. No checkout, payment, payout, MT5 or funded-account flow is authorized by success of this suite.

## Scope verification snapshot

104 focused regressions passed sequentially and with 4 workers in a network namespace. Eight analytics tests include actual SQL tenant/referral/commission queries, same-tenant masters in different branches, actual query failure/recovery, and Redis serializer roundtrip. Serializer verification is not a live Redis server/network/TTL test. The existing AI performance metrics still use a simplified drawdown/profit-factor implementation; they must not be presented as certified risk-engine mathematics.
