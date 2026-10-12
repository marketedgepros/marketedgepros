"""Fail-closed boundary for unverified legacy affiliate financial mutations.

There is deliberately no config flag, user role or client supplied evidence that
can enable this path. A verified settlement/identity/ledger integration must be
implemented and tested separately before any replacement mutator is enabled.
Read-only reporting and public program configuration are not payout authority.
"""


class AffiliateSettlementNotConfigured(RuntimeError):
    """The legacy operation cannot prove commission or payout entitlement."""

    code = 'AFFILIATE_SETTLEMENT_NOT_CONFIGURED'
    status = 503

    def __init__(self):
        super().__init__('Affiliate settlement and identity verification are not configured')


def refuse_unverified_affiliate_mutation():
    """Reject before parsing untrusted bodies, ORM lookup, or external effects."""
    raise AffiliateSettlementNotConfigured()


def affiliate_mutation_unavailable_response():
    """HTTP boundary, called only after existing authentication/authorization."""
    from flask import jsonify
    error = AffiliateSettlementNotConfigured()
    return jsonify({'error': str(error), 'code': error.code}), error.status
