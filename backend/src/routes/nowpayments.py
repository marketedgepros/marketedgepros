"""Bounded legacy NOWPayments endpoints.

No legacy crypto checkout operation can call a provider or settle an order
until the canonical order settlement adapter exists.  The callback endpoint
only performs local signature verification before returning that same gate.
"""
import hashlib
import hmac
import json

from flask import Blueprint, current_app, jsonify, request

from src.utils.decorators import token_required

nowpayments_bp = Blueprint('nowpayments', __name__)

_MAX_IPN_PAYLOAD_BYTES = 64 * 1024
_MAX_IPN_JSON_DEPTH = 16


def _settlement_not_configured():
    """Return the deliberate Stage4a legacy-checkout boundary response."""
    return jsonify({
        'error': 'Order settlement is not configured',
        'code': 'ORDER_SETTLEMENT_NOT_CONFIGURED',
        'reason': 'SETTLEMENT_NOT_CONFIGURED',
    }), 503


@nowpayments_bp.route('/api/crypto/create-payment', methods=['POST'])
@token_required
def create_crypto_payment(current_user):
    """Authenticate then block mutable client-priced crypto payment creation."""
    return _settlement_not_configured()


@nowpayments_bp.route('/api/crypto/payment-status/<payment_id>', methods=['GET'])
@token_required
def get_payment_status(current_user, payment_id):
    """Authenticate then block unbound provider-status reads."""
    return _settlement_not_configured()


@nowpayments_bp.route('/api/crypto/webhook', methods=['POST'])
def payment_webhook():
    """Verify an IPN locally, then deliberately decline legacy settlement."""
    payload = request.stream.read(_MAX_IPN_PAYLOAD_BYTES + 1)
    if not verify_webhook_signature(
        payload, request.headers.get('x-nowpayments-sig')
    ):
        return jsonify({'error': 'Invalid signature'}), 401
    return _settlement_not_configured()


@nowpayments_bp.route('/api/crypto/currencies', methods=['GET'])
def get_available_currencies():
    """Block legacy provider currency discovery rather than inventing a list."""
    return _settlement_not_configured()


def _reject_nonstandard_json_constant(_value):
    """Reject NaN and infinity, which strict JSON and provider signing do not use."""
    raise ValueError('Non-finite JSON value')


def _reject_duplicate_json_keys(pairs):
    """Build a JSON object while refusing ambiguous duplicate keys."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def _supported_ipn_json(value, depth=1):
    """Allow only deterministically serializable, bounded callback JSON."""
    if depth > _MAX_IPN_JSON_DEPTH:
        return False
    if value is None or isinstance(value, (str, bool)):
        return True
    # Python and JavaScript differ when rendering some finite numeric values
    # (for example 1.0).  Accept only JSON integer literals in this legacy
    # verifier until adapter-backed provider interoperability is exercised.
    if isinstance(value, int) and not isinstance(value, bool):
        return True
    if isinstance(value, list):
        return all(_supported_ipn_json(item, depth + 1) for item in value)
    if isinstance(value, dict):
        return all(
            isinstance(key, str) and _supported_ipn_json(item, depth + 1)
            for key, item in value.items()
        )
    return False


def verify_webhook_signature(payload, signature):
    """Verify NOWPayments' sorted-JSON HMAC-SHA-512 IPN signature locally.

    The official NOWPayments IPN instructions require sorted callback JSON and
    HMAC-SHA-512 with the IPN secret compared to ``x-nowpayments-sig``.  This
    function intentionally accepts no environment fallback: application
    configuration is the only secret source for this draft boundary.
    """
    try:
        ipn_secret = current_app.config.get('NOWPAYMENTS_IPN_SECRET')
        if not isinstance(ipn_secret, str) or not ipn_secret:
            return False
        if not isinstance(signature, str) or not signature:
            return False
        if not isinstance(payload, bytes) or not payload or len(payload) > _MAX_IPN_PAYLOAD_BYTES:
            return False
        decoded_payload = payload.decode('utf-8')
        data = json.loads(
            decoded_payload,
            object_pairs_hook=_reject_duplicate_json_keys,
            parse_constant=_reject_nonstandard_json_constant,
        )
        if not isinstance(data, dict) or not _supported_ipn_json(data):
            return False
        canonical_payload = json.dumps(
            data,
            sort_keys=True,
            separators=(',', ':'),
            ensure_ascii=False,
            allow_nan=False,
        )
        expected_signature = hmac.new(
            ipn_secret.encode('utf-8'),
            canonical_payload.encode('utf-8'),
            hashlib.sha512,
        ).hexdigest()
        return hmac.compare_digest(expected_signature, signature)
    except (TypeError, UnicodeError, ValueError, RecursionError):
        return False
