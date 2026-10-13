"""Authenticated immutable quotes plus a separately gated NOWPayments checkout draft."""
import json
from types import SimpleNamespace

from flask import Blueprint, current_app, jsonify, request

from src.database import db
from src.services.nowpayments_checkout import (
    CheckoutError,
    CheckoutPolicy,
    NowPaymentsCheckoutService,
    ProviderUnavailable,
    parse_bounded_json,
    verify_ipn_signature,
)
from src.services.order_service import OrderError, OrderService
from src.utils.decorators import token_required

orders_bp = Blueprint("orders", __name__)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate field")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("Nonfinite number")


def _checkout_error(error: CheckoutError):
    db.session.rollback()
    return jsonify({"error": str(error), "code": error.code}), error.status


def _checkout_body(*, limit: int = 2048):
    if request.content_length is not None and request.content_length > limit:
        raise CheckoutError("Checkout request exceeds the size limit", "CHECKOUT_INVALID", 413)
    raw = request.stream.read(limit + 1)
    if len(raw) > limit or not request.is_json:
        raise CheckoutError("A bounded JSON request is required", "CHECKOUT_INVALID", 400)
    try:
        return parse_bounded_json(raw)
    except (UnicodeError, ValueError, RecursionError):
        raise CheckoutError("A valid unambiguous JSON object is required", "CHECKOUT_INVALID", 400) from None


@orders_bp.route("/", methods=["POST"])
@token_required
def create_order(current_user):
    if request.content_length is not None and request.content_length > 4096:
        return jsonify({"error": "Order request exceeds the size limit", "code": "ORDER_INVALID"}), 413
    raw = request.stream.read(4097)
    if len(raw) > 4096:
        return jsonify({"error": "Order request exceeds the size limit", "code": "ORDER_INVALID"}), 413
    try:
        if not request.is_json:
            raise ValueError("JSON required")
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError):
        return jsonify({"error": "A valid unambiguous JSON object is required", "code": "ORDER_INVALID"}), 400
    try:
        order, created = OrderService.create_quote(current_user, data, request.headers.get("Idempotency-Key"))
        db.session.commit()
        return jsonify({"order": order.to_dict(), "replayed": not created}), 201 if created else 200
    except OrderError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc), "code": exc.code}), exc.status
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Order service is unavailable", "code": "ORDER_UNAVAILABLE"}), 503


@orders_bp.route("/payment-capabilities", methods=["GET"])
@token_required
def payment_capabilities(current_user):
    """Local policy/owner capability only: no provider transport or write."""
    try:
        return jsonify(NowPaymentsCheckoutService.capabilities(current_user)), 200
    except CheckoutError as exc:
        return _checkout_error(exc)
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Payment capabilities are unavailable", "code": "CHECKOUT_UNAVAILABLE"}), 503


@orders_bp.route("/payment-records", methods=["GET"])
@token_required
def payment_records(current_user):
    """Current-root tenant read projection; it intentionally has no action route."""
    try:
        return jsonify(NowPaymentsCheckoutService.admin_records(current_user, request.args)), 200
    except CheckoutError as exc:
        return _checkout_error(exc)
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Payment records are unavailable", "code": "PAYMENT_RECORDS_UNAVAILABLE"}), 503


@orders_bp.route("/purchases", methods=["GET"])
@token_required
def purchases(current_user):
    """Private, local-only historical checkout records for the current principal."""
    try:
        return jsonify(NowPaymentsCheckoutService.purchase_records(current_user, request.args)), 200
    except CheckoutError as exc:
        return _checkout_error(exc)
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Purchase records are unavailable", "code": "PURCHASE_RECORDS_UNAVAILABLE"}), 503


@orders_bp.route("/<order_id>/payments/nowpayments", methods=["POST"])
@token_required
def create_nowpayments_checkout(current_user, order_id):
    """Persist command before bounded provider I/O; never retry an uncertain POST."""
    try:
        actor_reference = SimpleNamespace(id=getattr(current_user, "id", None))
        body = _checkout_body()
        intent, created = NowPaymentsCheckoutService.prepare_create(current_user, order_id, body, request.headers.get("Idempotency-Key"))
        # The command is durable before a provider request.  This boundary is
        # deliberately outside a row lock and outside provider transport.
        db.session.commit()
        if not created:
            projection = NowPaymentsCheckoutService.projection(actor_reference, order_id)
            projection["replayed"] = True
            return jsonify(projection), 200
        reservation = NowPaymentsCheckoutService.reserve_create_dispatch(current_user, intent.id)
        db.session.commit()
        # The reservation transaction owns every policy/actor/order lookup and
        # row lock. Remove it before any provider POST, including in test spies.
        db.session.remove()
        if reservation is None:
            projection = NowPaymentsCheckoutService.projection(actor_reference, order_id)
            projection["replayed"] = True
            return jsonify(projection), 200
        try:
            posted = NowPaymentsCheckoutService.dispatch_create(reservation)
            db.session.commit()
            projection = NowPaymentsCheckoutService.projection(actor_reference, order_id)
            projection["replayed"] = not posted
            return jsonify(projection), 201 if posted else 200
        except ProviderUnavailable:
            # dispatch_create persisted only the conservative uncertain state.
            db.session.commit()
            projection = NowPaymentsCheckoutService.projection(actor_reference, order_id)
            return jsonify(projection), 503
    except CheckoutError as exc:
        return _checkout_error(exc)
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Payment creation is unavailable", "code": "CHECKOUT_UNAVAILABLE"}), 503


@orders_bp.route("/<order_id>/payment", methods=["GET"])
@token_required
def get_order_payment(current_user, order_id):
    """Owner-scoped local projection. It never calls a provider or writes state."""
    try:
        return jsonify(NowPaymentsCheckoutService.projection(current_user, order_id)), 200
    except CheckoutError as exc:
        return _checkout_error(exc)
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Payment status is unavailable", "code": "CHECKOUT_UNAVAILABLE"}), 503


@orders_bp.route("/<order_id>/payment/refresh", methods=["POST"])
@token_required
def refresh_order_payment(current_user, order_id):
    """A manual, budgeted GET for the server-bound provider ID only."""
    try:
        actor_reference = SimpleNamespace(id=getattr(current_user, "id", None))
        raw = request.get_data(cache=False)
        if raw:
            if len(raw) > 2048 or not request.is_json:
                raise CheckoutError("Payment refresh accepts only an empty JSON object", "CHECKOUT_INVALID", 400)
            try:
                if parse_bounded_json(raw) != {}:
                    raise ValueError("nonempty refresh body")
            except (UnicodeError, ValueError, RecursionError):
                raise CheckoutError("Payment refresh accepts only an empty JSON object", "CHECKOUT_INVALID", 400) from None
        reservation = NowPaymentsCheckoutService.refresh(current_user, order_id)
        # Commit the local rate-budget claim before provider I/O; no lock spans GET.
        db.session.commit()
        db.session.remove()
        try:
            NowPaymentsCheckoutService.refresh_after_commit(reservation)
            db.session.commit()
        except ProviderUnavailable:
            db.session.rollback()
            raise
        return jsonify(NowPaymentsCheckoutService.projection(actor_reference, order_id)), 200
    except CheckoutError as exc:
        return _checkout_error(exc)
    except Exception:
        db.session.rollback()
        return jsonify({"error": "Payment refresh is unavailable", "code": "CHECKOUT_UNAVAILABLE"}), 503


@orders_bp.route("/webhooks/nowpayments", methods=["POST"])
def nowpayments_webhook():
    """Signed IPN only; 2xx is emitted after durable observation/replay commit."""
    try:
        # Creation uses the current pilot gate. An authenticated notification
        # for an existing command uses its immutable stored policy instead, so
        # closing creation cannot discard a late receipt. Unknown references
        # cannot create commands/bindings/grants, and no default key is used.
        NowPaymentsCheckoutService._storage_ready()
        payload = request.stream.read(64 * 1024 + 1)
        if len(payload) > 64 * 1024:
            raise CheckoutError("Payment notification is too large", "IPN_INVALID", 401)
        data, digest = verify_ipn_signature(
            payload, request.headers.get("x-nowpayments-sig"), current_app.config.get("NOWPAYMENTS_IPN_SECRET"),
        )
        observation, created = NowPaymentsCheckoutService.record_provider_observation(data, digest, source="ipn", signed=True)
        db.session.commit()
        return jsonify({"schema_version": 1, "replayed": not created}), 200
    except CheckoutError as exc:
        return _checkout_error(exc)
    except Exception:
        db.session.rollback()
        # No raw payload, signature, provider body, or configured secret reaches logs/response.
        return jsonify({"error": "Payment notification is temporarily unavailable", "code": "IPN_UNAVAILABLE"}), 503


@orders_bp.route("/<order_id>", methods=["GET"])
@token_required
def get_order(current_user, order_id):
    try:
        order = OrderService.get_quote(current_user, order_id)
        return jsonify({"order": order.to_dict()}), 200
    except OrderError as exc:
        return jsonify({"error": str(exc), "code": exc.code}), exc.status
    except Exception:
        return jsonify({"error": "Order service is unavailable", "code": "ORDER_UNAVAILABLE"}), 503
