# Security foundation — first implementation batch

## Scope

This is a scoped containment and test-isolation PR, not a complete auth/KYC redesign or a production deployment.

- Public register/resend/password-reset request responses no longer disclose verification/reset codes. Delivery remains out of band through the existing email service.
- Generic local upload GET is fail-closed and serves only canonical profile/avatar/logo image paths. KYC and unknown/private files are not served by this endpoint, including to an alleged admin without document authorization metadata.
- Testing resources are validated before SQLAlchemy/Redis/cache initialization. Tests cannot select the production factory and change config after initialization.
- Tests use memory SQLite and cache by default. PostgreSQL, when explicitly requested, must be a numeric loopback address (127.0.0.1 or ::1), use `TEST_DATABASE_URL` and have a per-run name `marketedgepros_test_<suffix>` distinct from `DATABASE_URL`. Connection URL overrides and SQLAlchemy binds are denied.
- `FLASK_TESTING=true` must be selected before importing the factory. It disables production gevent monkey-patching and loading the local `.env` file.

## Reproduce the focused suite

From the repository root, with Python 3.12 and util-linux/unshare on Linux (if unprivileged namespaces are denied by the host, an administrator can run the same runner under sudo; do not remove isolation to bypass that failure):

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r backend/requirements-security.lock
.venv/bin/python backend/scripts/run_security_tests.py -q
.venv/bin/python backend/scripts/run_security_tests.py -q -n 4
```

The runner creates a clean subprocess environment without inherited provider credentials, never collects the legacy tests, starts an OS user/network namespace before collection that is inherited by all xdist workers and subprocesses, and uses only explicitly enabled pytest plugins. The test fixtures additionally deny Python TCP. A collection-time fresh subprocess verifies the namespace in each worker. No external interfaces or routes are present. The runner fails closed if Linux util-linux/unshare or namespace permissions are unavailable; it never falls back to monkeypatch-only isolation. This is focused runtime HTTP/resource validation, not a load test or full business E2E suite.

**Do not run bare `pytest` against the repository on a production host.** The legacy suite still contains scripts with network side effects, duplicate session fixtures and assumptions about public codes. Removing the unsafe factory call in the legacy conftest does not certify that suite.

## Deployment prerequisites

1. Verify the target file hashes and runtime entrypoint. Do not overwrite the server's unrelated changes with a Git checkout.
2. Rehearse on a staging copy. Test existing profile/logo URLs: only `profiles/profile_<id>.<image>`, `profiles/<id>/avatar.<image>` and `tenants/<id>/logo.<image>` are public now. Other legacy paths return 404 intentionally.
3. Inspect reverse-proxy/object-store routes: this Flask patch cannot protect a separate Nginx alias or public Spaces bucket. Confirm no independent public KYC serving route exists.
4. Verify real email delivery without depending on public verification/reset response codes. Existing fixtures/consumers relying on these leaked fields must be fixed; never restore disclosure for compatibility.
5. Keep a known rollback artifact and run post-release HTTP smoke checks. Batch 2 now adds a dedicated owner/reviewer authorization endpoint; see SECURITY_BATCH2.md for its storage/hierarchy prerequisites. Do not reopen the generic route to make old links work.
6. Deploy containment separately from test-foundation/runtime changes if a smaller risk surface is needed. No DB migration is required by this batch.

## Deferred work (not claimed fixed)

Hashed/single-use reset tokens, distributed rate limits and races, session family revocation, CSRF/2FA redesign, tenant/RLS policy, CRM/AI ownership, ledger/payment replay safety, MT5/risk contracts, full provider sandbox/E2E/load coverage, and private KYC storage with ownership/audit/retention controls.

A schema+data pg_dump restore was verified separately in a private local PostgreSQL 18 instance (roles/ACL intentionally not restored). That is not a complete VM/assets/provider disaster-recovery exercise. No production database or service was modified in this implementation batch.
