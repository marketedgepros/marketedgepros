"""Disabled MT5 webhook boundary; never authenticate an invented wire format.

This blueprint is not registered by the application factory. If explicitly
mounted later, all callbacks still refuse before reading payloads, querying DB
or scheduling tasks. A real provider's documented signature/replay contract,
merchant/account binding and durable inbox must be implemented first.
"""
from flask import Blueprint, jsonify

mt5_webhooks_bp = Blueprint('mt5_webhooks', __name__, url_prefix='/webhooks/mt5')


def verify_mt5_signature(data, signature, secret_key):
    # str(dict) is not a defined provider signing format. Never pretend it is.
    return False


def _not_configured():
    return jsonify({'status': 'unavailable', 'error': 'Verified MT5 events are not configured',
                    'code': 'MT5_PROVIDER_NOT_CONFIGURED'}), 503


@mt5_webhooks_bp.route('/trade', methods=['POST'])
def trade_webhook():
    return _not_configured()


@mt5_webhooks_bp.route('/balance', methods=['POST'])
def balance_webhook():
    return _not_configured()


@mt5_webhooks_bp.route('/equity', methods=['POST'])
def equity_webhook():
    return _not_configured()


@mt5_webhooks_bp.route('/status', methods=['GET'])
def webhook_status():
    return _not_configured()
