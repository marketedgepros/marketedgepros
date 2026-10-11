"""Authenticated server-price quote API; financial settlement is not exposed."""
import json
from flask import Blueprint, jsonify, request
from src.database import db
from src.services.order_service import OrderService, OrderError
from src.utils.decorators import token_required

orders_bp = Blueprint('orders', __name__)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate field')
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError('Nonfinite number')


@orders_bp.route('/', methods=['POST'])
@token_required
def create_order(current_user):
    if request.content_length is not None and request.content_length > 4096:
        return jsonify({'error': 'Order request exceeds the size limit', 'code': 'ORDER_INVALID'}), 413
    raw = request.stream.read(4097)
    if len(raw) > 4096:
        return jsonify({'error': 'Order request exceeds the size limit', 'code': 'ORDER_INVALID'}), 413
    try:
        if not request.is_json:
            raise ValueError('JSON required')
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError):
        return jsonify({'error': 'A valid unambiguous JSON object is required', 'code': 'ORDER_INVALID'}), 400
    try:
        order, created = OrderService.create_quote(current_user, data, request.headers.get('Idempotency-Key'))
        db.session.commit()
        return jsonify({'order': order.to_dict(), 'replayed': not created}), 201 if created else 200
    except OrderError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc), 'code': exc.code}), exc.status
    except Exception:
        db.session.rollback()
        return jsonify({'error': 'Order service is unavailable', 'code': 'ORDER_UNAVAILABLE'}), 503


@orders_bp.route('/<order_id>', methods=['GET'])
@token_required
def get_order(current_user, order_id):
    try:
        order = OrderService.get_quote(current_user, order_id)
        return jsonify({'order': order.to_dict()}), 200
    except OrderError as exc:
        return jsonify({'error': str(exc), 'code': exc.code}), exc.status
    except Exception:
        return jsonify({'error': 'Order service is unavailable', 'code': 'ORDER_UNAVAILABLE'}), 503
