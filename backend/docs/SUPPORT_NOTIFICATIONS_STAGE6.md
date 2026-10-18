# Stage 6 — authenticated support and in-app notification views

This is a bounded implementation batch within stage 6 of the existing seven-stage plan. It is not a production rollout or completion of every customer-journey acceptance condition.

## Scope

- Customer support-ticket creation bound to the authenticated principal; authenticated listing, detail and replies.
- Email address and ticket number are identifiers, never authentication credentials.
- Guest-created legacy tickets remain unowned. No automatic ownership reassignment by email, and no migration of legacy records.
- Internal support notes are excluded from customer details, counts and latest-message summaries.
- Bounded pagination and payload validation, one transaction per mutation, stable errors and no uncontrolled retry loops.
- In-app notification listing, unread counts, read acknowledgement, soft deletion and preference storage use the actual notification models.
- Reading preferences must not create database rows.
- Stored preferences or an in-app row do not establish successful delivery of email, SMS or Slack messages.
- Frontend views use the configured API client, reject malformed responses, distinguish failures from empty results, and invalidate stale responses when the principal changes.
- One shared notification bell per active layout. Refresh is triggered by user interaction or a component mount, not a periodic polling loop.
- Customer support routes require sign-in. Public help articles and the support landing page remain public.

## Non-goals and remaining gates

- No new SMTP/SMS/Slack configuration, bulk dispatch, real-time delivery infrastructure or external sending.
- Existing monitoring notification producers and financial/trading event generation are not integrated by this batch. A readable historical notification does not certify the business event it describes.
- No live MT5 or wallet verification, payment collection, account provisioning, challenge activation or balance update.
- No new ownership assignment for guest tickets, attachment-upload/storage flow, or financial SLA/promise.
- No production migration, service restart, deployment or merge. All changes remain on the draft PR.
- Public support articles/FAQ editorial content, staff-console completeness, browser end-to-end acceptance and stage 7 operational/load gates remain separate work.

## Validation boundaries

Regression suites use synthetic records and isolated test infrastructure, never the production database. Node contract tests and production build checks are supplemented with full-application HTTP wiring checks. Passing these checks proves the tested contracts, not unrestricted throughput or live provider delivery.

## Integration review closure

The actual support detail API accepts `page` and `per_page`; the customer service validates the echoed page, requested ticket number and bounded result length. Customer message visibility requires `is_internal === false`. A keyed component boundary binds support views to the authenticated user/tenant and detail route; canceled or stale mutations cannot merge an old ticket into a new detail view or clear its draft. Notification pages, preference drafts and the shared bell also reset on an identity change.

The single-brand middleware lookup and both authentication decorators suppress autoflush during their read boundary. Support list/detail and notification preference/list GETs are regression-tested in the full MVP factory with unrelated pending ORM work, proving that these reads do not flush it. Payload readers cap allocation before JSON decoding, reject oversized bodies, catch recursion-depth errors and limit pagination-string length before integer parsing.

Local verification uses the locked Python environment, serial and parallel security regression suites, and real PostgreSQL/Redis rehearsal. The frontend is checked with its Node contract tests and a fresh frozen-lockfile production build without `.env` files. Component-level delayed-response scenarios supplement these checks; they are not browser E2E and do not establish real email delivery or live wallet/MT5 operation.
