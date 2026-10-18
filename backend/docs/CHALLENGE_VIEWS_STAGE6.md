# Stage 6 — canonical challenge views

This package continues original Stage 6: customer journey and administration screens. It does not add a roadmap stage, enable a provider or close Stages 4–5. The owner-reported MT5 and wallet connections remain recorded in `INTEGRATION_REGISTER_HE.md`; live integration verification is separate.

## Scoped outcomes

A bounded owner-only challenge list is exposed under `/api/v1/challenges/my-challenges`, using existing legacy projections rather than calculation-heavy `Challenge.to_dict()`. Every row must match both the authenticated user ID and the program's tenant. Pagination and filters have explicit input limits, with no provider requests, account creation, payment or credentials.

Customer list and detail screens use the canonical list and `/challenges/<id>/progress` contracts. A missing value remains unavailable; a recorded zero is retained. Stored status, payment flags, balances and account metadata are labeled unverified legacy records. An old local status must not become proof of payment, live funding, rule approval or authenticated MT5 data. A missing API response must not turn into a misleading empty success state.

The administration challenge screen uses the existing scoped `/challenges/admin/all` endpoint. Server pagination totals are distinguished from counts or searches on the displayed page. Ambiguous account bindings are displayed as such; the UI does not choose one account or request credentials. This package adds no trading-state mutation controls.

All screens reuse existing styling and router-owned layouts. Requests are cancelable, manual refresh is bounded, and late responses may not overwrite newer route/filter/page context. There is no continuous polling or invented account-connection button, rule percentage, win rate or trading-day calculation.

## Validation and limitations

New HTTP tests use real authentication and synthetic records in an isolated database. Node contract tests exercise frontend service logic without customer/provider requests. Existing security, PostgreSQL/Redis and frontend build gates are retained. These are not browser E2E tests against the MT5 or wallet providers.

The old program/trader challenge endpoints and other callers are not rewritten by this focused package. No schema migration, historical row modification, deployment or provider-side action is performed. The full Stage 6 acceptance journey and operational load/failure work of Stage 7 remain pending their original dependencies.
