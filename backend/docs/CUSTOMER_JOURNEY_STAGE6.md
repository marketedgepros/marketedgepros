# Stage 6 — customer journey, first integration package

## Position in the seven-stage roadmap

This is the original Stage 6 (customer journey and administration screens), not an additional roadmap stage. The owner reports that MT5 and the receiving cryptocurrency wallet connections exist. See `INTEGRATION_REGISTER_HE.md` for the source and technical-verification status. That statement is recorded without inventing provider, network, addresses, credentials, signing or a successful transaction.

Stages 4–5 retain their original provider-verification and end-to-end acceptance dependencies. Work on customer screens can proceed in parallel without declaring live payment/trading integration ready.

## Current scoped outcomes

Checkout uses the existing server purchase-order quote contract, preserves an idempotency key for an unchanged selection after an ambiguous request, and presents `quoted`/`paid=false` as an unpaid quote. It must not send a client-defined amount to legacy payment endpoints, prescribe an unverified USDT network, or promise instant activation. No payment adapter is enabled by this package.

KYC screens consume existing document metadata, use authenticated private download requests, and display verification only from explicit server status rather than document-count inference. Storage addresses must not become public browser links. Only synthetic files are used in tests.

The user dashboard reads scoped aggregate counts and at most five recent challenges, avoids loading the entire challenge history, and preserves unknown financial information as unknown rather than zero. Recorded historical balances and statuses are not authenticated MT5 evidence. A hard-coded 8% progress target is not an approved rule and must not appear as a real target. Page layouts are owned by the router; these pages must not add a second sidebar.

The existing component styling is reused. This is a contract-correction package, not a site redesign, new managed-hosting project or replacement for the external DigitalOcean deployment.

## Acceptance boundaries

Focused Node tests exercise actual frontend service logic with synthetic API responses. Backend HTTP tests exercise the actual authenticated handler and disposable data. A clean frontend build and existing security/staging CI must pass. These checks are not equivalent to a live-provider browser E2E journey.

Completion of this package does not close Stage 6: payment-to-account flow, coherent challenge screens, payout eligibility, administration, support/notification delivery and the full registration-to-KYC/payout journey still require their own verified integration. No production document submission, account change, wallet transfer, payout, deployment or migration is authorized by a test success alone.
