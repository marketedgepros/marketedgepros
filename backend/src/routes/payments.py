"""Bounded legacy payment routes.

Historical checkout is intentionally unavailable until a canonical order
settlement adapter owns price snapshots, provider bindings, and fulfillment.
These legacy endpoints must remain fail-closed in every application mode.
"""
from flask import Blueprint, current_app, request, jsonify
import stripe

from src.models.payment import Payment
from src.utils.decorators import token_required

payments_bp = Blueprint('payments', __name__)

_MAX_PAGE = 1000
_MAX_PER_PAGE = 100


def _settlement_not_configured():
    """Return the deliberate Stage4a legacy-checkout boundary response."""
    return jsonify({
        'error': 'Order settlement is not configured',
        'code': 'ORDER_SETTLEMENT_NOT_CONFIGURED',
        'reason': 'SETTLEMENT_NOT_CONFIGURED',
    }), 503


def _bounded_pagination_value(name, *, default, maximum):
    """Parse one positive integer query argument without silent coercion."""
    raw_value = request.args.get(name)
    if raw_value is None:
        return default, None
    if len(raw_value) > 4 or not raw_value.isascii() or not raw_value.isdecimal():
        return None, (jsonify({
            'error': f'{name} must be an integer between 1 and {maximum}',
            'code': 'PAGINATION_INVALID',
        }), 400)
    value = int(raw_value)
    if not 1 <= value <= maximum:
        return None, (jsonify({
            'error': f'{name} must be an integer between 1 and {maximum}',
            'code': 'PAGINATION_INVALID',
        }), 400)
    return value, None


@payments_bp.route('/', methods=['GET'])
@token_required
def get_payments(current_user):
    """Return only the caller's historical payment rows with bounded paging."""
    page, error_response = _bounded_pagination_value(
        'page', default=1, maximum=_MAX_PAGE
    )
    if error_response:
        return error_response
    per_page, error_response = _bounded_pagination_value(
        'per_page', default=10, maximum=_MAX_PER_PAGE
    )
    if error_response:
        return error_response
    try:
        payments_query = Payment.query.filter_by(
            user_id=current_user.id
        ).order_by(Payment.created_at.desc())
        pagination = payments_query.paginate(page=page, per_page=per_page, error_out=False)
        return jsonify({
            'payments': [payment.to_dict() for payment in pagination.items],
            'total': pagination.total,
            'current_page': page,
            'per_page': per_page,
            'pages': pagination.pages
        }), 200
    except Exception:
        return jsonify({'error': 'Failed to retrieve payments'}), 500


@payments_bp.route('/', methods=['POST'])
@token_required
def create_payment(current_user):
    """Block mutable client-priced legacy payment creation."""
    return _settlement_not_configured()



@payments_bp.route('/create-payment-intent', methods=['POST'])
@token_required
def create_payment_intent(current_user):
    """Block mutable-program legacy Stripe intent creation."""
    return _settlement_not_configured()


@payments_bp.route('/confirm-payment', methods=['POST'])
@token_required
def confirm_payment(current_user):
    """Block legacy client-driven payment confirmation and fulfillment."""
    return _settlement_not_configured()


@payments_bp.route('/webhook', methods=['POST'])
def stripe_webhook():
    """Authenticate a Stripe event, then deliberately decline settlement.

    ``construct_event`` verifies the event locally and does not call the
    Stripe API.  The legacy webhook handler is never invoked.
    """
    payload = request.stream.read(65537)
    if len(payload) > 65536:
        return jsonify({'error': 'Invalid webhook signature'}), 400
    sig_header = request.headers.get('Stripe-Signature')
    webhook_secret = current_app.config.get('STRIPE_WEBHOOK_SECRET')
    if not isinstance(sig_header, str) or not sig_header:
        return jsonify({'error': 'Invalid webhook signature'}), 400
    if not isinstance(webhook_secret, str) or not webhook_secret:
        return jsonify({'error': 'Invalid webhook signature'}), 400
    try:
        stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except Exception:
        # Malformed payloads and all signature failures remain indistinguishable
        # and no raw payload or secret is logged.
        return jsonify({'error': 'Invalid webhook signature'}), 400
    return _settlement_not_configured()


@payments_bp.route('/refund/<int:challenge_id>', methods=['POST'])
@token_required
def refund_payment(current_user, challenge_id):
    """Block the historical direct-provider refund path."""
    return _settlement_not_configured()


@payments_bp.route('/status/<payment_intent_id>', methods=['GET'])
@token_required
def get_payment_status(current_user, payment_intent_id):
    """Block unbound provider-status reads after authenticating the caller."""
    return _settlement_not_configured()
