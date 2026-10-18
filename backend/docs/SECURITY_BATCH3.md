# Batch 3: authentication/session lifecycle and isolated PostgreSQL/Redis validation

No production deployment, real-user security operation, database migration, or real email was performed. Changes extend the existing draft security PR.

## Session contract

- Login validates the password with an authoritative User row lock. Tokens or a second-factor challenge are signed before that transaction commits, preventing reset/login version races.
- New access/refresh JWT pairs share a random `sid` family. Both carry version and unique `jti`; real JWT validation requires user_id/type/exp/iat. Legacy access remains version-bound; legacy refresh without family/id/version requires a fresh login.
- Refresh locks User, verifies active/verified/version/family revocation, persists the old refresh jti to the existing unique blacklist table, and returns new access + refresh + CSRF. Reuse is denied; concurrent PostgreSQL refresh test permits one successful consume.
- Logout blacklists the family sid; all refresh rotations in that login stop working. An independent device/login is not revoked. Profile password change, admin reset and successful recovery bump token_version atomically and invalidate unused password-reset credentials.
- Authentication resolves a current database principal in both decorator families. Redis failure falls back to DB; DB revocation failure returns 503, never an authenticated response or misleading successful logout.
- Password/email lifecycle uses User-first locks then guarded token consumption; expiry and used status are checked in SQL. A successful token consumption invalidates siblings. Two-minute issuance cooldown only reuses a still-valid token. Email changes invalidate unused verification/reset tokens and sessions; old links cannot verify the new address.
- Existing verification-attempt records are not rewritten, but new attempts store `******`, never the code entered. The six-character placeholder fits PostgreSQL's existing varchar(6).

## Two-factor login

`POST /auth/login` with a correct password for a 2FA-enabled account returns `requires_2fa`, `user_id`, `challenge_token` only. This is a signed five-minute `preauth` token, not an authenticated session.

`POST /auth/login/2fa` requires `{challenge_token, token, user_id?}`. Active/verified/version checks, strict claims, TOTP and consume-once challenge jti gate precede issuing a session pair. Supplying a user_id + TOTP without prior password proof is denied. Frontend holds the challenge transiently in Zustand memory, clears it on completion/failure/cancel/expiry, and never trusts a cached localStorage user as proof of server authentication.

## CSRF contract

Cookie-first precedence is retained. Unsafe operations using an access cookie require `X-CSRF-Token` matching the HttpOnly CSRF cookie and an HMAC bound to the session's access token. The same value contains a separate refresh-bound signature for cookie refresh after access expiry. Login, completed 2FA and refresh return the value in JSON and set the HttpOnly Secure SameSite=Lax cookie. Pure explicit Bearer clients without auth cookies do not require browser CSRF.

The current frontend keeps legacy JSON/localStorage JWT compatibility; this is not an XSS-proof cookie-only migration. Axios adds CSRF only for same-origin unsafe requests and updates all three tokens after refresh. UI/browser E2E is not certified by Node helpers.

## Reproduction

Focused tests: install `requirements-security.lock` into an isolated virtual environment, then run `backend/scripts/run_security_tests.py` as described in SECURITY_FOUNDATION.md.

Opt-in real PG18/Redis checks:

```sh
.venv/bin/python backend/scripts/run_staging_integration.py
```

Requires PostgreSQL 18 under `/usr/lib/postgresql/18/bin`, redis-server, sudo -n, unshare and runtime user ubuntu. The runner uses current venv, clears all inherited environment before imports, enters a new OS network namespace, drops to ubuntu, and starts newly initialized disposable services only over private Unix sockets. It stops them in finally. It never uses the private restored audit cluster or production URLs. Not a cloud staging deployment.

Six tests exercise actual production-model DDL, PostgreSQL aggregates, RedisCache warm/hit/status/header/key isolation/TTL, and two-session reset/refresh consumption. They pass. **Runner still exits 3** because offline Alembic `upgrade heads --sql` fails in `003a_add_supermaster_user.py` on `conn.execute(...).fetchone()` (offline execute returns None). Graph has two disconnected heads `20251110_191500` and `token_blacklist_001`. No online migration is attempted, so this is not a claim that online migrations succeed or fail. Migration repair is a separate tracked release gate.

## Remaining release blockers / limitations

- Frontend full Vite build still stops on missing `./pages/affiliate/TradersManagement` imported by App.jsx. A broken quote in VerifyEmail.jsx was repaired, but no missing route was replaced with a fake screen or silent redirect. package.json/pnpm-lock compatibility requires a separate reproducible build fix.
- Outstanding URL/code columns remain plaintext. Hash-at-rest migration, session-family table/cleanup constraints, strict single-use TOTP across different password-proven challenges and full revocation retention remain separate work.
- Existing NULL-tenant identity ownership, mixed hierarchy delimiters, legacy payment/payout/MT5 and load/scalability work remain open.
- No claim that every legacy route now conforms to all auth contracts; these tests cover the changed paths and explicit resource boundaries.
