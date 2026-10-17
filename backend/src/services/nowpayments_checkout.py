"""Fail-closed NOWPayments custom-checkout draft.

The module deliberately keeps provider transport, immutable provider evidence, and
recorded-purchase grants separate from legacy payments and the synthetic ledger.
It never mutates PurchaseOrder, a wallet, MT5, a Challenge, commissions, refunds,
or payouts.  Network transport is reachable only after the explicit pilot policy,
owner allowlist, and storage readiness gates pass.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
import re
from typing import Any, Mapping
from urllib.parse import quote, urlparse
from uuid import uuid4

import requests
import rfc8785
from flask import current_app
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from src.database import db
from src.middleware.tenant_middleware import get_tenant_from_request
from src.models.nowpayments_checkout import (
    CheckoutIntent,
    NowPaymentsObservation,
    NowPaymentsPaymentBinding,
    NowPaymentsSettlementEntry,
    NowPaymentsSettlementJournal,
    NowPaymentsVerifiedReceipt,
    OrderEntitlementGrant,
)
from src.models.purchase_order import PurchaseOrder
from src.nowpayments_credentials import is_valid_nowpayments_api_key
from src.services.order_service import OrderError, OrderService
from src.constants.roles import Roles
from src.utils.hierarchy_scoping import complete_hierarchy_scope, platform_root_scope, without_hierarchy_scope


API_BASE = "https://api.nowpayments.io/v1"
STORAGE_REVISION = "20261013_000002"
MAX_BODY_BYTES = 64 * 1024
MAX_JSON_DEPTH = 16
MAX_PROVIDER_RESPONSE_BYTES = 64 * 1024
_IDENTIFIER = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z", re.ASCII)
_COMMAND_KEY = re.compile(r"[A-Za-z0-9_-]{16,128}\Z", re.ASCII)
_POLICY_VERSION = re.compile(r"[A-Za-z0-9_.:-]{1,64}\Z", re.ASCII)
_CURRENCY = re.compile(r"[a-z0-9]{2,32}\Z", re.ASCII)
_NETWORK = re.compile(r"[A-Za-z0-9_.:-]{1,32}\Z", re.ASCII)
_HASH = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z", re.ASCII)
_PROVIDER_ID = re.compile(r"[1-9][0-9]{0,127}\Z", re.ASCII)
_DECIMAL_TEXT = re.compile(r"-?(?:0|[1-9][0-9]{0,35})(?:\.[0-9]{1,30})?\Z", re.ASCII)
_ALLOWED_STATUSES = frozenset({
    "waiting", "confirming", "confirmed", "sending", "partially_paid",
    "finished", "failed", "expired", "refunded",
})
_ROLE_ALIASES = {"user": "trader", "trader": "trader"}
# NOWPayments describes USDT/TRC20 as ``usdttrc20``.  Some payment objects
# spell the same documented chain as TRX or TRON-TRC20.  The persisted policy
# name remains TRC20; no address, wallet, or unsupported chain is inferred.
_NETWORK_ALIASES = {"TRC20": frozenset({"TRC20", "TRON-TRC20", "TRX"})}


def _instant_bound_quote(order: PurchaseOrder) -> bool:
    """Identify only an immutable Instant Funding quote snapshot.

    This deliberately never consults the mutable program catalog: an old quote
    remains historical evidence even after a catalog row changes.  A malformed
    snapshot is handled by the existing order-integrity gate before callers use
    this predicate.
    """
    try:
        snapshot = json.loads(order.snapshot_json)
        terms = snapshot.get("terms") if isinstance(snapshot, dict) else None
        return isinstance(terms, dict) and terms.get("type") == "instant_funding"
    except (TypeError, ValueError):
        return False


class CheckoutError(ValueError):
    def __init__(self, message: str, code: str = "CHECKOUT_INVALID", status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


class ProviderUnavailable(CheckoutError):
    def __init__(self):
        super().__init__("Payment creation is uncertain; do not retry it", "CHECKOUT_CREATION_UNCERTAIN", 503)


class JsonNumber:
    """A JSON numeric lexeme kept as Decimal until a signing-only conversion.

    Provider money is always extracted through :func:`money_decimal`; no float
    participates in money comparison or persistence.  The signing conversion is
    separate because NOWPayments' documented Node sample calls JSON.parse then
    JSON.stringify, which uses ECMAScript Number rendering.
    """

    __slots__ = ("lexeme", "decimal")

    def __init__(self, lexeme: str):
        self.lexeme = lexeme
        try:
            self.decimal = Decimal(lexeme)
        except InvalidOperation as exc:
            raise ValueError("invalid JSON number") from exc
        if not self.decimal.is_finite():
            raise ValueError("non-finite JSON number")


def _reject_constant(_value: str):
    raise ValueError("non-finite JSON value")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _check_json(value: Any, depth: int = 1) -> None:
    if depth > MAX_JSON_DEPTH:
        raise ValueError("JSON depth exceeds limit")
    if value is None or isinstance(value, (str, bool, JsonNumber)):
        if isinstance(value, str) and any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise ValueError("unpaired surrogate")
        return
    if isinstance(value, list):
        for item in value:
            _check_json(item, depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str) or any(0xD800 <= ord(character) <= 0xDFFF for character in key):
                raise ValueError("invalid JSON object key")
            _check_json(item, depth + 1)
        return
    raise ValueError("unsupported JSON value")


def parse_bounded_json(payload: bytes, *, require_object: bool = True) -> dict[str, Any] | Any:
    """Decode one strict UTF-8 JSON document without losing decimal lexemes."""
    if not isinstance(payload, bytes) or not payload or len(payload) > MAX_BODY_BYTES:
        raise ValueError("payload size is invalid")
    value = json.loads(
        payload.decode("utf-8"), object_pairs_hook=_unique_object,
        parse_int=JsonNumber, parse_float=JsonNumber, parse_constant=_reject_constant,
    )
    _check_json(value)
    if require_object and not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def _utf16_sort_key(value: str) -> bytes:
    """JavaScript ``Object.keys(...).sort()`` order (UTF-16 code units)."""
    return value.encode("utf-16-be", "surrogatepass")


def _array_index_key(value: str) -> int | None:
    if not value or not value.isascii() or not value.isdigit():
        return None
    if len(value) > 1 and value[0] == "0":
        return None
    parsed = int(value)
    return parsed if 0 <= parsed < 2**32 - 1 else None


def _js_number_text(number: JsonNumber) -> str:
    """Render a separately validated JSON number as ECMAScript JSON.stringify.

    This renderer is intentionally confined to HMAC serialization.  It accepts
    only finite IEEE-754 values and is followed by a Decimal round-trip equality
    check in ``money_decimal`` before a signed numeric may affect payment logic.
    CPython and modern V8 both use shortest-round-trip decimal formatting; the
    fixed/exponent threshold and exponent spelling below are ECMAScript's.
    """
    try:
        # RFC 8785 section 3.2.2.3 implements the ECMA-262 Number rendering
        # used by JSON.stringify, including 1.0 -> 1, -0 -> 0, and e-7 rather
        # than Python's e-07.  This is signing-only; money remains Decimal.
        return rfc8785.dumps(float(number.lexeme)).decode("ascii")
    except (OverflowError, ValueError, rfc8785.CanonicalizationError) as exc:
        raise ValueError("number is not an ECMAScript finite number") from exc


def _json_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _canonical_node_value(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _json_string(value)
    if isinstance(value, JsonNumber):
        return _js_number_text(value)
    if isinstance(value, list):
        # The provider's documented Node sortObject turns every array into an
        # ordinary object with numeric keys before JSON.stringify.
        value = {str(index): item for index, item in enumerate(value)}
    if isinstance(value, dict):
        sorted_keys = sorted(value, key=_utf16_sort_key)
        numeric = sorted((key for key in sorted_keys if _array_index_key(key) is not None), key=lambda key: _array_index_key(key))
        other = [key for key in sorted_keys if _array_index_key(key) is None]
        return "{" + ",".join(_json_string(key) + ":" + _canonical_node_value(value[key]) for key in numeric + other) + "}"
    raise ValueError("unsupported canonical JSON value")


def canonical_ipn_bytes(value: Mapping[str, Any]) -> bytes:
    if not isinstance(value, dict):
        raise ValueError("IPN object required")
    _check_json(value)
    return _canonical_node_value(value).encode("utf-8")


def verify_ipn_signature(payload: bytes, signature: str | None, secret: str | None) -> tuple[dict[str, Any], str]:
    """Verify HMAC-SHA-512 after strict parsing; never expose the secret."""
    if not isinstance(secret, str) or not secret or not isinstance(signature, str) or not re.fullmatch(r"[0-9a-fA-F]{128}", signature):
        raise CheckoutError("Invalid payment notification", "IPN_INVALID", 401)
    try:
        parsed = parse_bounded_json(payload)
        canonical = canonical_ipn_bytes(parsed)
    except (UnicodeError, ValueError, RecursionError):
        raise CheckoutError("Invalid payment notification", "IPN_INVALID", 401) from None
    expected = hmac.new(secret.encode("utf-8"), canonical, hashlib.sha512).hexdigest()
    if not hmac.compare_digest(expected, signature.lower()):
        raise CheckoutError("Invalid payment notification", "IPN_INVALID", 401)
    # Replay identity is the signed canonical object, not a whitespace/key-order
    # formatting accident in the HTTP body.
    return parsed, hashlib.sha256(canonical).hexdigest()


def _decimal_text(value: Decimal) -> str:
    rendered = format(value, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered or "0"


def money_decimal(value: Any, *, positive: bool = False, allow_zero: bool = True) -> Decimal:
    """Extract a bounded exact amount without coercing a money value through float."""
    original_number = value if isinstance(value, JsonNumber) else None
    if isinstance(value, bool) or value is None:
        raise ValueError("money is absent or non-numeric")
    if isinstance(value, JsonNumber):
        if not _DECIMAL_TEXT.fullmatch(value.lexeme):
            raise ValueError("money number text is outside the exact decimal domain")
        amount = value.decimal
        # A raw JSON number may have changed when Node parsed it into a double
        # for the documented HMAC.  Such a payload is ambiguous and cannot be
        # used for money even if its signature is otherwise valid.
        if amount != Decimal(_js_number_text(original_number)):
            raise ValueError("money numeric lexeme is ambiguous under Node signing")
    elif isinstance(value, str):
        if value.strip() != value or not _DECIMAL_TEXT.fullmatch(value):
            raise ValueError("money text is invalid")
        amount = Decimal(value)
    else:
        raise ValueError("money must be a JSON number or decimal string")
    if not amount.is_finite() or abs(amount) > Decimal("1e60") or (positive and amount <= 0) or (not allow_zero and amount == 0):
        raise ValueError("money amount is outside bounds")
    return amount


def canonical_provider_id(value: Any) -> str:
    """Accept only NOWPayments' documented positive numeric payment identity."""
    if isinstance(value, JsonNumber):
        if not _PROVIDER_ID.fullmatch(value.lexeme):
            raise ValueError("provider identifier is invalid")
        if value.decimal != Decimal(_js_number_text(value)):
            raise ValueError("provider identifier is ambiguous")
        result = value.lexeme
    elif isinstance(value, int) and not isinstance(value, bool) and _PROVIDER_ID.fullmatch(str(value)):
        # Test doubles may already have decoded a documented JSON number. Real
        # transport uses JsonNumber so no provider string identifier is accepted.
        result = str(value)
    else:
        raise ValueError("provider identifier is invalid")
    return result


def _canonical_optional_id(value: Any) -> str | None:
    return None if value is None else canonical_provider_id(value)


def _required_string(data: Mapping[str, Any], field: str, maximum: int, *, pattern=None) -> str:
    value = data.get(field)
    if not isinstance(value, str) or not value or len(value) > maximum or value.strip() != value:
        raise ValueError(f"{field} is invalid")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{field} contains control characters")
    if pattern is not None and not pattern.fullmatch(value):
        raise ValueError(f"{field} is invalid")
    return value


def _optional_string(data: Mapping[str, Any], field: str, maximum: int) -> str | None:
    value = data.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value or len(value) > maximum or value.strip() != value:
        raise ValueError(f"{field} is invalid")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{field} contains control characters")
    return value


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 64:
        raise ValueError("expiry is invalid")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("expiry timezone is required")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    # SQLite fixtures (and historic rows before the UTC column migration) can
    # return a naive datetime. It was written by server UTC code, never by a
    # caller, so emit an explicit UTC DTO timestamp rather than a naive value.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _normal_role(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return _ROLE_ALIASES.get(value, value)


def _positive_ids(value: Any) -> tuple[int, ...] | None:
    if not isinstance(value, (tuple, list)) or not value:
        return None
    result = []
    for item in value:
        if not isinstance(item, int) or isinstance(item, bool) or not 0 < item <= 2147483647:
            return None
        result.append(item)
    return tuple(result) if len(set(result)) == len(result) else None


@dataclass(frozen=True)
class CurrencyPolicy:
    code: str
    label: str
    network: str
    decimals: int


@dataclass(frozen=True)
class CheckoutPolicy:
    scope: str
    version: str
    merchant_context: str
    callback_url: str
    outcome_currency: str
    fixed_rate: bool
    fee_paid_by_user: bool
    principal_ids: tuple[int, ...]
    tenant_ids: tuple[int, ...]
    roles: tuple[str, ...]
    currencies: tuple[CurrencyPolicy, ...]
    refresh_min_seconds: int

    @classmethod
    def from_config(cls) -> "CheckoutPolicy":
        config = current_app.config
        if config.get("NOWPAYMENTS_PILOT_ENABLED") is not True:
            raise CheckoutError("Payment checkout is unavailable", "PILOT_DISABLED", 503)
        scope = config.get("NOWPAYMENTS_CHECKOUT_SCOPE", "pilot")
        if not isinstance(scope, str) or scope not in {"pilot", "customers"}:
            raise CheckoutError("Payment checkout scope is not configured", "POLICY_NOT_CONFIGURED", 503)
        version = config.get("NOWPAYMENTS_APPROVED_POLICY_VERSION")
        merchant = config.get("NOWPAYMENTS_MERCHANT_CONTEXT")
        origin = config.get("NOWPAYMENTS_CALLBACK_ORIGIN")
        path = config.get("NOWPAYMENTS_CALLBACK_PATH")
        if not isinstance(version, str) or not _POLICY_VERSION.fullmatch(version):
            raise CheckoutError("Payment policy is not configured", "POLICY_NOT_CONFIGURED", 503)
        if not isinstance(merchant, str) or not _IDENTIFIER.fullmatch(merchant):
            raise CheckoutError("Payment merchant context is not configured", "POLICY_NOT_CONFIGURED", 503)
        parsed_origin = urlparse(origin) if isinstance(origin, str) else None
        if (parsed_origin is None or parsed_origin.scheme != "https" or not parsed_origin.hostname
                or parsed_origin.path not in ("", "/") or parsed_origin.params or parsed_origin.query or parsed_origin.fragment
                or parsed_origin.username or parsed_origin.password or not isinstance(path, str)
                or not re.fullmatch(r"/[A-Za-z0-9/_-]{1,160}", path)):
            raise CheckoutError("Payment callback is not configured", "POLICY_NOT_CONFIGURED", 503)
        if config.get("NOWPAYMENTS_API_BASE") != API_BASE:
            raise CheckoutError("Payment transport is not pinned", "POLICY_NOT_CONFIGURED", 503)
        if config.get("NOWPAYMENTS_STORAGE_REVISION") != STORAGE_REVISION:
            raise CheckoutError("Payment storage revision is not configured", "POLICY_NOT_CONFIGURED", 503)
        if config.get("NOWPAYMENTS_FIXED_RATE") is not False or config.get("NOWPAYMENTS_FEE_PAID_BY_USER") is not False:
            raise CheckoutError("Payment fee policy is not explicitly approved", "POLICY_NOT_CONFIGURED", 503)
        api_key = config.get("NOWPAYMENTS_API_KEY")
        ipn_secret = config.get("NOWPAYMENTS_IPN_SECRET")
        if not (is_valid_nowpayments_api_key(api_key) and isinstance(ipn_secret, str) and len(ipn_secret) >= 32):
            raise CheckoutError("Payment credentials are not configured", "POLICY_NOT_CONFIGURED", 503)
        principals = _positive_ids(config.get("NOWPAYMENTS_PILOT_PRINCIPAL_IDS")) if scope == "pilot" else ()
        tenants = _positive_ids(config.get("NOWPAYMENTS_PILOT_TENANT_IDS"))
        roles = config.get("NOWPAYMENTS_PILOT_ROLES")
        if (scope == "pilot" and not principals) or not tenants or not isinstance(roles, (tuple, list)) or not roles:
            raise CheckoutError("Payment pilot allowlist is not configured", "POLICY_NOT_CONFIGURED", 503)
        normalized_roles = tuple(_normal_role(role) for role in roles)
        if any(role not in {Roles.TRADER, Roles.AFFILIATE} for role in normalized_roles) or len(set(normalized_roles)) != len(normalized_roles):
            raise CheckoutError("Payment pilot role allowlist is invalid", "POLICY_NOT_CONFIGURED", 503)
        raw_currencies = config.get("NOWPAYMENTS_ALLOWED_CURRENCIES")
        currencies: list[CurrencyPolicy] = []
        if not isinstance(raw_currencies, (tuple, list)) or not raw_currencies:
            raise CheckoutError("Payment asset policy is not configured", "POLICY_NOT_CONFIGURED", 503)
        for raw in raw_currencies:
            if not isinstance(raw, Mapping) or set(raw) != {"code", "label", "network", "decimals"}:
                raise CheckoutError("Payment asset policy is invalid", "POLICY_NOT_CONFIGURED", 503)
            code = raw["code"]
            label = raw["label"]
            network = raw["network"]
            decimals = raw["decimals"]
            if (not isinstance(code, str) or code != "usdttrc20" or not isinstance(label, str) or not 1 <= len(label) <= 80
                    or not isinstance(network, str) or not _NETWORK.fullmatch(network) or not isinstance(decimals, int)
                    or isinstance(decimals, bool) or decimals != 6
                    or network.upper() != "TRC20"):
                raise CheckoutError("Payment asset policy is invalid", "POLICY_NOT_CONFIGURED", 503)
            currencies.append(CurrencyPolicy(code, label, network, decimals))
        if len(currencies) != 1 or len({currency.code for currency in currencies}) != len(currencies):
            raise CheckoutError("Payment asset policy is invalid", "POLICY_NOT_CONFIGURED", 503)
        outcome = config.get("NOWPAYMENTS_OUTCOME_CURRENCY")
        if not isinstance(outcome, str) or not _CURRENCY.fullmatch(outcome):
            raise CheckoutError("Payment outcome currency is not configured", "POLICY_NOT_CONFIGURED", 503)
        refresh = config.get("NOWPAYMENTS_REFRESH_MIN_SECONDS", 30)
        if not isinstance(refresh, int) or isinstance(refresh, bool) or not 1 <= refresh <= 3600:
            raise CheckoutError("Payment refresh budget is invalid", "POLICY_NOT_CONFIGURED", 503)
        return cls(scope, version, merchant, origin.rstrip("/") + path, outcome, False, False, principals, tenants, normalized_roles, tuple(currencies), refresh)

    def currency(self, code: Any) -> CurrencyPolicy:
        if not isinstance(code, str):
            raise CheckoutError("A configured pay_currency is required", "CHECKOUT_INVALID", 400)
        for currency in self.currencies:
            if hmac.compare_digest(currency.code, code.lower()):
                return currency
        raise CheckoutError("The requested currency is unavailable", "CURRENCY_UNAVAILABLE", 409)

    def eligible(self, user, tenant) -> bool:
        return (
            (self.scope == "customers" or getattr(user, "id", None) in self.principal_ids)
            and getattr(user, "tenant_id", None) in self.tenant_ids
            and getattr(tenant, "id", None) == getattr(user, "tenant_id", None)
            and bool(getattr(user, "is_active", False))
            and _normal_role(getattr(user, "role", None)) in self.roles
        )


@dataclass(frozen=True)
class CreateDispatchReservation:
    """Server-frozen command data safe to carry across the provider I/O boundary."""

    intent_id: str
    order_id: str
    payload: dict[str, str | bool]


@dataclass(frozen=True)
class RefreshReservation:
    """A committed, rate-budgeted provider identity; it is never request input."""

    order_id: str
    provider_payment_id: str


def _provider_payload(data: Mapping[str, Any]) -> tuple[str, str, Decimal, str, Decimal, str, str, str | None, datetime | None, str | None, Any]:
    """Read the strict shared provider fields without trusting a client value."""
    payment_id = canonical_provider_id(data.get("payment_id"))
    order_reference = _required_string(data, "order_id", 96, pattern=_IDENTIFIER)
    price = money_decimal(data.get("price_amount"), positive=True)
    price_currency = _required_string(data, "price_currency", 3).upper()
    pay_amount = money_decimal(data.get("pay_amount"), positive=True)
    pay_currency = _required_string(data, "pay_currency", 32).lower()
    pay_address = _required_string(data, "pay_address", 256)
    memo = _optional_string(data, "payin_extra_id", 128)
    expiration = _parse_timestamp(data.get("expiration_estimate_date", data.get("valid_until")))
    parent = _canonical_optional_id(data.get("parent_payment_id"))
    status_value = data.get("payment_status")
    if not isinstance(status_value, str) or status_value not in _ALLOWED_STATUSES:
        raise ValueError("payment status is invalid")
    return payment_id, order_reference, price, price_currency, pay_amount, pay_currency, pay_address, memo, expiration, parent, status_value


def _network_matches(network: Any, approved_network: str) -> bool:
    """Accept only the finite documented spelling set for the approved chain."""
    if network is None:
        # NOWPayments payment responses commonly omit this optional field. The
        # immutable usdttrc20 code remains the authoritative coin/network bind.
        return True
    aliases = _NETWORK_ALIASES.get(approved_network.upper(), frozenset())
    return isinstance(network, str) and network.upper() in aliases


def _is_currency_quantized(amount: Decimal, decimals: int) -> bool:
    """No money float: the stored/provider Decimal must be an exact asset quantum."""
    if not isinstance(decimals, int) or not 0 <= decimals <= 6:
        return False
    return -amount.as_tuple().exponent <= decimals


def _trc20_address(value: str) -> bool:
    """Validate a standard TRON base58-check address without deriving a wallet."""
    if not isinstance(value, str) or len(value) != 34 or not value.startswith("T"):
        return False
    alphabet = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    encoded_number = 0
    for character in value:
        index = alphabet.find(character)
        if index < 0:
            return False
        encoded_number = encoded_number * 58 + index
    encoded = encoded_number.to_bytes(25, "big")
    payload, checksum = encoded[:-4], encoded[-4:]
    return payload[:1] == b"\x41" and hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4] == checksum


def _approved_address(address: str, network: str) -> bool:
    return network.upper() == "TRC20" and _trc20_address(address)


def _create_wire_body(payload: Mapping[str, str | bool]) -> bytes:
    """Emit the immutable USD quote as a JSON number, without a money float.

    ``requests.post(json=...)`` would quote our Decimal-safe string (or require a
    float). The only spliced token is the independently validated two-decimal
    server quote; standard json escaping serializes every other scalar.
    """
    expected = {
        "price_amount", "price_currency", "pay_currency", "ipn_callback_url",
        "order_id", "is_fixed_rate", "is_fee_paid_by_user",
    }
    if set(payload) != expected:
        raise ValueError("unexpected payment payload")
    price = payload.get("price_amount")
    if not isinstance(price, str) or not re.fullmatch(r"(?:0|[1-9][0-9]{0,9})\.[0-9]{2}", price):
        raise ValueError("price amount is not an exact USD-cent lexeme")
    remainder = {key: value for key, value in payload.items() if key != "price_amount"}
    encoded_remainder = json.dumps(remainder, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return b'{"price_amount":' + price.encode("ascii") + b"," + encoded_remainder[1:]


class NowPaymentsTransport:
    """Pinned, bounded, no-retry HTTP adapter.  It never logs request/response bodies."""

    @staticmethod
    def _read_response(response) -> bytes:
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(chunk_size=4096):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_PROVIDER_RESPONSE_BYTES:
                raise ProviderUnavailable()
            chunks.append(chunk)
        return b"".join(chunks)

    @classmethod
    def create_payment(cls, payload: Mapping[str, str | bool]) -> tuple[dict[str, Any], bytes]:
        response = None
        try:
            wire_body = _create_wire_body(payload)
            response = requests.post(
                API_BASE + "/payment", data=wire_body,
                headers={"x-api-key": current_app.config["NOWPAYMENTS_API_KEY"], "Content-Type": "application/json"},
                timeout=(3.05, 10), allow_redirects=False, stream=True,
            )
            raw = cls._read_response(response)
            if response.status_code != 201:
                raise ProviderUnavailable()
            return parse_bounded_json(raw), raw
        except ProviderUnavailable:
            raise
        except (requests.RequestException, UnicodeError, ValueError, json.JSONDecodeError):
            raise ProviderUnavailable() from None
        finally:
            if response is not None:
                response.close()

    @classmethod
    def get_payment(cls, payment_id: str) -> tuple[dict[str, Any], bytes]:
        response = None
        try:
            response = requests.get(
                API_BASE + "/payment/" + quote(payment_id, safe=""),
                headers={"x-api-key": current_app.config["NOWPAYMENTS_API_KEY"]},
                timeout=(3.05, 10), allow_redirects=False, stream=True,
            )
            raw = cls._read_response(response)
            if response.status_code != 200:
                raise ProviderUnavailable()
            return parse_bounded_json(raw), raw
        except ProviderUnavailable:
            raise
        except (requests.RequestException, UnicodeError, ValueError, json.JSONDecodeError):
            raise ProviderUnavailable() from None
        finally:
            if response is not None:
                response.close()


class NowPaymentsCheckoutService:
    @staticmethod
    def _query_budget() -> None:
        if db.session.get_bind().dialect.name == "postgresql":
            db.session.execute(text("SET LOCAL lock_timeout = '3s'"))
            db.session.execute(text("SET LOCAL statement_timeout = '5s'"))

    @staticmethod
    def _actor(actor):
        try:
            user, tenant = OrderService._actor(actor)
        except OrderError as exc:
            raise CheckoutError(str(exc), exc.code, exc.status) from None
        if _normal_role(getattr(user, "role", None)) not in Roles.ALL_ROLES:
            raise CheckoutError("Authenticated canonical role is required", "ORDER_FORBIDDEN", 403)
        return user, tenant

    @staticmethod
    def _storage_ready(*, read_only: bool = False) -> None:
        dialect = db.session.get_bind().dialect.name
        if dialect == "sqlite" and current_app.testing:
            return
        if dialect != "postgresql":
            raise CheckoutError("Payment storage is not ready", "CHECKOUT_STORAGE_NOT_READY", 503)
        if not read_only:
            NowPaymentsCheckoutService._query_budget()
        version = db.session.execute(text("SELECT version_num FROM public.alembic_version")).scalars().all()
        if version != [STORAGE_REVISION]:
            raise CheckoutError("Payment storage is not ready", "CHECKOUT_STORAGE_NOT_READY", 503)
        # This migration-owned verifier checks exact columns, constraints,
        # immutable function bodies, and trigger bindings; names alone do not
        # establish payment-storage readiness.
        try:
            from src.services.nowpayments_checkout_schema import validate_checkout_schema
            schema_ready = validate_checkout_schema(db.session.connection())
        except Exception:
            schema_ready = False
        if schema_ready is not True:
            raise CheckoutError("Payment storage is not ready", "CHECKOUT_STORAGE_NOT_READY", 503)

    @staticmethod
    def _owned_order(actor, order_id: str) -> tuple[Any, Any, PurchaseOrder]:
        if not isinstance(order_id, str) or not _UUID.fullmatch(order_id):
            raise CheckoutError("Order not found", "ORDER_NOT_FOUND", 404)
        user, tenant = NowPaymentsCheckoutService._actor(actor)
        with without_hierarchy_scope(db.session):
            order = db.session.execute(select(PurchaseOrder).where(
                PurchaseOrder.id == order_id, PurchaseOrder.user_id == user.id,
                PurchaseOrder.tenant_id == tenant.id,
            ).execution_options(skip_hierarchy_scope=True, populate_existing=True)).scalar_one_or_none()
        if order is None:
            raise CheckoutError("Order not found", "ORDER_NOT_FOUND", 404)
        try:
            OrderService._integrity(order)
        except OrderError:
            raise CheckoutError("Stored order integrity failed", "ORDER_INTEGRITY_FAILED", 503) from None
        return user, tenant, order

    @staticmethod
    def _policy_for_actor(actor) -> tuple[CheckoutPolicy, Any, Any]:
        user, tenant = NowPaymentsCheckoutService._actor(actor)
        policy = CheckoutPolicy.from_config()
        if not policy.eligible(user, tenant):
            raise CheckoutError("Payment checkout is unavailable", "PILOT_INELIGIBLE", 403)
        NowPaymentsCheckoutService._storage_ready()
        return policy, user, tenant

    @staticmethod
    def _last_observation(binding_id: str) -> NowPaymentsObservation | None:
        return db.session.execute(select(NowPaymentsObservation).where(
            NowPaymentsObservation.binding_id == binding_id
        ).order_by(NowPaymentsObservation.created_at.desc(), NowPaymentsObservation.id.desc()).limit(1)).scalar_one_or_none()

    @staticmethod
    def _grant(order_id: str) -> OrderEntitlementGrant | None:
        return db.session.execute(select(OrderEntitlementGrant).where(OrderEntitlementGrant.order_id == order_id)).scalar_one_or_none()

    @staticmethod
    def _reason_from_error(error: CheckoutError) -> str:
        return error.code

    @classmethod
    def capabilities(cls, actor) -> dict[str, Any]:
        user, tenant = cls._actor(actor)
        enabled = False
        reason = None
        currencies: list[dict[str, Any]] = []
        quote_currency = "USD"
        fee_paid_by_user = None
        policy_version = None
        try:
            policy = CheckoutPolicy.from_config()
            if not policy.eligible(user, tenant):
                reason = "PILOT_INELIGIBLE"
            else:
                cls._storage_ready(read_only=True)
                enabled = True
                currencies = [{"code": item.code, "label": item.label, "network": item.network, "decimals": item.decimals} for item in policy.currencies]
                fee_paid_by_user = policy.fee_paid_by_user
                policy_version = policy.version
        except CheckoutError as exc:
            reason = cls._reason_from_error(exc)
        return {
            "schema_version": 1,
            "owner_context": {"user_id": user.id, "tenant_id": tenant.id, "role": _normal_role(user.role)},
            "enabled": enabled,
            "reason": reason,
            "currencies": currencies,
            "quote_currency": quote_currency,
            "fee_paid_by_user": fee_paid_by_user,
            "policy_version": policy_version,
            "live_trading_enabled": False,
        }

    @staticmethod
    def _intent_state(intent: CheckoutIntent | None, observation: NowPaymentsObservation | None, grant: OrderEntitlementGrant | None) -> tuple[str, bool, str | None]:
        if intent is None:
            return "not_started", False, None
        # A later discrepancy must remain visible even if a historically valid
        # recorded grant exists. ``paid`` below remains historical grant truth.
        if intent.state == "manual_review" or (observation is not None and observation.review_required):
            return "manual_review", True, "MANUAL_REVIEW_REQUIRED"
        if grant is not None:
            return "paid", False, None
        mapping = {
            "prepared": ("creation_uncertain", "CREATION_IN_PROGRESS"),
            "creating": ("creation_uncertain", "CREATION_IN_PROGRESS"),
            "awaiting_payment": ("awaiting_payment", None),
            "creation_uncertain": ("creation_uncertain", "CREATION_RECONCILIATION_REQUIRED"),
            "processing": ("processing", None),
            "manual_review": ("manual_review", "MANUAL_REVIEW_REQUIRED"),
            "expired": ("expired", None),
            "failed": ("failed", None),
            "paid": ("manual_review", "GRANT_INTEGRITY_REQUIRED"),
        }
        state, reason = mapping.get(intent.state, ("manual_review", "STATE_INTEGRITY_REQUIRED"))
        return state, state == "manual_review", reason

    @classmethod
    def _display_observation(
        cls,
        latest: NowPaymentsObservation | None,
        grant: OrderEntitlementGrant | None,
    ) -> NowPaymentsObservation | None:
        """Do not let a benign delayed waiting/processing callback hide a receipt."""
        if grant is None or latest is None or latest.review_required or latest.status == "finished":
            return latest
        granted = db.session.get(NowPaymentsObservation, grant.observation_id)
        return granted if granted is not None else latest

    @classmethod
    def projection(cls, actor, order_id: str) -> dict[str, Any]:
        user, tenant, order = cls._owned_order(actor, order_id)
        # Do not name an additive checkout relation until the local schema is
        # known ready. This remains local-only even if the pilot was disabled.
        cls._storage_ready(read_only=True)
        intent = db.session.execute(select(CheckoutIntent).where(CheckoutIntent.order_id == order.id)).scalar_one_or_none()
        binding = None
        latest_observation = None
        if intent is not None:
            binding = db.session.execute(select(NowPaymentsPaymentBinding).where(NowPaymentsPaymentBinding.intent_id == intent.id)).scalar_one_or_none()
            if binding is not None:
                latest_observation = cls._last_observation(binding.id)
        grant = cls._grant(order.id)
        state, review_required, state_reason = cls._intent_state(intent, latest_observation, grant)
        observation = cls._display_observation(latest_observation, grant)
        enabled = False
        policy: CheckoutPolicy | None = None
        policy_reason: str | None = None
        try:
            candidate = CheckoutPolicy.from_config()
            if candidate.eligible(user, tenant):
                cls._storage_ready(read_only=True)
                enabled, policy = True, candidate
            else:
                policy_reason = "PILOT_INELIGIBLE"
        except CheckoutError as exc:
            policy_reason = exc.code
        creation_attempted = intent is not None
        coming_soon = _instant_bound_quote(order)
        can_create = enabled and intent is None and grant is None and not coming_soon
        can_refresh = bool(enabled and binding is not None and intent is not None and (
            intent.last_refresh_at is None or (datetime.now(timezone.utc) - (intent.last_refresh_at if intent.last_refresh_at.tzinfo is not None else intent.last_refresh_at.replace(tzinfo=timezone.utc))).total_seconds() >= policy.refresh_min_seconds
        ))
        payment = None
        if binding is not None:
            currency = next((item for item in (policy.currencies if policy else ()) if item.code == binding.pay_currency), None)
            payment = {
                "provider": "nowpayments",
                "provider_payment_id": binding.provider_payment_id,
                "pay_amount": binding.pay_amount,
                "pay_currency": binding.pay_currency,
                "network": binding.network,
                "label": currency.label if currency else binding.pay_currency,
                "decimals": binding.decimals,
                "pay_address": binding.pay_address,
                "memo": binding.memo,
                "expires_at": _iso(binding.expires_at),
                "actually_paid": observation.actually_paid if observation else None,
                "outcome_amount": observation.outcome_amount if observation else None,
                "outcome_currency": observation.outcome_currency if observation else None,
                "fee_paid_by_user": binding.fee_paid_by_user,
            }
        reason = state_reason or ("PROGRAM_COMING_SOON" if coming_soon and intent is None else (None if (can_create or can_refresh or state not in {"not_started", "unavailable"}) else policy_reason))
        return {
            "schema_version": 1,
            "owner_context": {"user_id": user.id, "tenant_id": tenant.id, "role": _normal_role(user.role)},
            "order_id": order.id,
            "program_id": order.program_id,
            "state": state,
            "paid": grant is not None,
            "review_required": review_required,
            "recorded_purchase": grant is not None,
            "creation_attempted": creation_attempted,
            "can_create": can_create,
            "can_refresh": can_refresh,
            "reason": reason,
            "provider_status": observation.status if observation else (binding.initial_status if binding else None),
            "payment": payment,
            "quote_amount_minor": str(order.amount_minor),
            "quote_currency": "USD",
            "policy_version": intent.policy_version if intent else (policy.version if enabled else None),
            "updated_at": _iso(observation.created_at if observation else (intent.updated_at if intent else None)),
            "replayed": False,
        }

    @classmethod
    def prepare_create(cls, actor, order_id: str, body: Mapping[str, Any], command_key: str) -> tuple[CheckoutIntent, bool]:
        if not isinstance(body, dict) or set(body) != {"pay_currency"}:
            raise CheckoutError("Only pay_currency is accepted", "CHECKOUT_INVALID", 400)
        if not isinstance(command_key, str) or not _COMMAND_KEY.fullmatch(command_key):
            raise CheckoutError("A bounded Idempotency-Key is required", "CHECKOUT_INVALID", 400)
        policy, user, tenant = cls._policy_for_actor(actor)
        currency = policy.currency(body.get("pay_currency"))
        _, _, order = cls._owned_order(actor, order_id)
        cls._query_budget()
        with without_hierarchy_scope(db.session):
            locked = db.session.execute(select(PurchaseOrder).where(PurchaseOrder.id == order.id).with_for_update().execution_options(skip_hierarchy_scope=True, populate_existing=True)).scalar_one()
        existing = db.session.execute(select(CheckoutIntent).where(CheckoutIntent.order_id == locked.id, CheckoutIntent.provider == "nowpayments").with_for_update()).scalar_one_or_none()
        if existing is not None:
            if existing.command_key != command_key or existing.pay_currency != currency.code:
                raise CheckoutError("A checkout command already exists for this order", "CHECKOUT_COMMAND_CONFLICT", 409)
            return existing, False
        if _instant_bound_quote(locked):
            raise CheckoutError("Program is coming soon", "PROGRAM_COMING_SOON", 409)
        request_body = {"order_id": locked.id, "currency": currency.code, "policy_version": policy.version, "merchant_context": policy.merchant_context}
        digest = hashlib.sha256(json.dumps(request_body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
        intent = CheckoutIntent(
            id=str(uuid4()), order_id=locked.id, user_id=user.id, tenant_id=tenant.id,
            provider="nowpayments", merchant_context=policy.merchant_context, command_key=command_key,
            external_reference="np_" + uuid4().hex, request_digest=digest, pay_currency=currency.code,
            network=currency.network, decimals=currency.decimals, policy_version=policy.version,
            outcome_currency=policy.outcome_currency,
            state="prepared", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc),
        )
        try:
            with db.session.begin_nested():
                db.session.add(intent)
                db.session.flush()
        except IntegrityError:
            existing = db.session.execute(select(CheckoutIntent).where(CheckoutIntent.order_id == locked.id, CheckoutIntent.provider == "nowpayments")).scalar_one_or_none()
            if existing is None:
                raise
            if existing.command_key != command_key or existing.pay_currency != currency.code:
                raise CheckoutError("A checkout command already exists for this order", "CHECKOUT_COMMAND_CONFLICT", 409)
            return existing, False
        return intent, True

    @classmethod
    def _create_request(cls, intent: CheckoutIntent, order: PurchaseOrder, policy: CheckoutPolicy) -> dict[str, str | bool]:
        if (not isinstance(order.amount_minor, int) or isinstance(order.amount_minor, bool)
                or not 0 < order.amount_minor <= 9_999_999_999):
            raise CheckoutError("Stored order integrity failed", "ORDER_INTEGRITY_FAILED", 503)
        return {
            "price_amount": format(Decimal(order.amount_minor) / Decimal(100), ".2f"),
            "price_currency": "usd",
            "pay_currency": intent.pay_currency,
            "ipn_callback_url": policy.callback_url,
            "order_id": intent.external_reference,
            "is_fixed_rate": policy.fixed_rate,
            "is_fee_paid_by_user": policy.fee_paid_by_user,
        }

    @classmethod
    def reserve_create_dispatch(cls, actor, intent_id: str) -> CreateDispatchReservation | None:
        """Lock once, mark the one permitted POST, and freeze scalar request data.

        The caller *must commit and remove the session* before ``dispatch_create``.
        A replay observes the same command but cannot reserve a second POST.
        """
        policy, user, tenant = cls._policy_for_actor(actor)
        intent = db.session.execute(select(CheckoutIntent).where(
            CheckoutIntent.id == intent_id
        ).with_for_update()).scalar_one_or_none()
        if intent is None or intent.user_id != user.id or intent.tenant_id != tenant.id:
            raise CheckoutError("Checkout command not found", "CHECKOUT_NOT_FOUND", 404)
        binding = db.session.execute(select(NowPaymentsPaymentBinding.id).where(
            NowPaymentsPaymentBinding.intent_id == intent.id
        )).scalar_one_or_none()
        if binding is not None or intent.state != "prepared" or intent.dispatch_reserved_at is not None:
            return None
        with without_hierarchy_scope(db.session):
            order = db.session.execute(select(PurchaseOrder).where(
                PurchaseOrder.id == intent.order_id
            ).with_for_update().execution_options(skip_hierarchy_scope=True, populate_existing=True)).scalar_one_or_none()
        if order is None:
            raise CheckoutError("Stored order is unavailable", "ORDER_INTEGRITY_FAILED", 503)
        try:
            OrderService._integrity(order)
        except OrderError:
            raise CheckoutError("Stored order integrity failed", "ORDER_INTEGRITY_FAILED", 503) from None
        # A command from before the catalog closure must never reach the
        # provider either.  Existing local projections and signed IPN handling
        # use different read/reconciliation paths and remain available.
        if _instant_bound_quote(order):
            raise CheckoutError("Program is coming soon", "PROGRAM_COMING_SOON", 409)
        payload = cls._create_request(intent, order, policy)
        now = datetime.now(timezone.utc)
        intent.state, intent.dispatch_reserved_at, intent.updated_at = "creating", now, now
        db.session.flush()
        return CreateDispatchReservation(intent.id, order.id, dict(payload))

    @classmethod
    def _mark_creation_uncertain(cls, intent_id: str) -> None:
        """Persist the conservative result in a new post-transport transaction."""
        intent = db.session.execute(select(CheckoutIntent).where(
            CheckoutIntent.id == intent_id
        ).with_for_update()).scalar_one_or_none()
        if intent is not None and intent.state in {"prepared", "creating"}:
            intent.state, intent.updated_at = "creation_uncertain", datetime.now(timezone.utc)
            db.session.flush()

    @classmethod
    def dispatch_create(cls, reservation: CreateDispatchReservation) -> bool:
        """Perform at most one POST, with no database transaction during I/O."""
        if not isinstance(reservation, CreateDispatchReservation):
            raise CheckoutError("Checkout command not found", "CHECKOUT_NOT_FOUND", 404)
        # An early trusted callback can bind the same existing command after the
        # reservation commit. Recheck under a fresh row lock so it suppresses a
        # duplicate create request rather than racing a second POST.
        intent = db.session.execute(select(CheckoutIntent).where(
            CheckoutIntent.id == reservation.intent_id
        ).with_for_update()).scalar_one_or_none()
        existing_binding = None if intent is None else db.session.execute(select(
            NowPaymentsPaymentBinding.id
        ).where(NowPaymentsPaymentBinding.intent_id == intent.id)).scalar_one_or_none()
        should_post = bool(intent is not None and existing_binding is None and intent.state == "creating"
                           and intent.dispatch_reserved_at is not None)
        # This is an explicit transport boundary, not an incidental route commit:
        # release every read/row lock and the scoped session before provider I/O.
        db.session.commit()
        db.session.remove()
        if not should_post:
            return False
        try:
            response, raw = NowPaymentsTransport.create_payment(reservation.payload)
        except ProviderUnavailable:
            cls._mark_creation_uncertain(reservation.intent_id)
            raise
        except (ValueError, CheckoutError):
            cls._mark_creation_uncertain(reservation.intent_id)
            raise ProviderUnavailable() from None
        try:
            cls.record_binding_from_provider(reservation.intent_id, response, raw)
        except (ValueError, CheckoutError):
            cls._mark_creation_uncertain(reservation.intent_id)
            raise ProviderUnavailable() from None
        return True

    @classmethod
    def record_binding_from_provider(
        cls, intent_id: str, data: Mapping[str, Any], raw: bytes, *, allow_terminal: bool = False
    ) -> NowPaymentsPaymentBinding:
        intent = db.session.execute(select(CheckoutIntent).where(CheckoutIntent.id == intent_id).with_for_update()).scalar_one_or_none()
        if intent is None:
            raise CheckoutError("Checkout command not found", "CHECKOUT_NOT_FOUND", 404)
        order = db.session.execute(select(PurchaseOrder).where(PurchaseOrder.id == intent.order_id).with_for_update()).scalar_one()
        payment_id, reference, price, price_currency, pay_amount, pay_currency, address, memo, expiry, parent, status = _provider_payload(data)
        if reference != intent.external_reference or price_currency != "USD" or price != Decimal(order.amount_minor) / Decimal(100):
            raise CheckoutError("Provider response does not match the immutable order", "PROVIDER_IDENTITY_CONFLICT", 409)
        if pay_currency != intent.pay_currency or (status != "waiting" and not allow_terminal):
            raise CheckoutError("Provider response does not match approved asset policy", "PROVIDER_IDENTITY_CONFLICT", 409)
        if not _network_matches(data.get("network"), intent.network):
            raise CheckoutError("Provider response lacks the approved network", "PROVIDER_IDENTITY_CONFLICT", 409)
        if not _approved_address(address, intent.network):
            raise CheckoutError("Provider response has an invalid approved-chain address", "PROVIDER_IDENTITY_CONFLICT", 409)
        if not _is_currency_quantized(pay_amount, intent.decimals):
            raise CheckoutError("Provider response violates approved asset quantum", "PROVIDER_IDENTITY_CONFLICT", 409)
        digest = hashlib.sha256(raw).hexdigest()
        existing = db.session.execute(select(NowPaymentsPaymentBinding).where(NowPaymentsPaymentBinding.intent_id == intent.id)).scalar_one_or_none()
        if existing is not None:
            expected = (payment_id, reference, _decimal_text(price), _decimal_text(pay_amount), pay_currency, address, memo, parent)
            actual = (existing.provider_payment_id, intent.external_reference, existing.price_amount, existing.pay_amount, existing.pay_currency, existing.pay_address, existing.memo, existing.parent_payment_id)
            if actual != expected:
                raise CheckoutError("Provider payment binding conflicts with recorded evidence", "PROVIDER_IDENTITY_CONFLICT", 409)
            return existing
        binding = NowPaymentsPaymentBinding(
            id=str(uuid4()), intent_id=intent.id, order_id=order.id, provider="nowpayments", merchant_context=intent.merchant_context,
            provider_payment_id=payment_id, parent_payment_id=parent, response_digest=digest, price_amount=_decimal_text(price), price_currency="USD",
            pay_amount=_decimal_text(pay_amount), pay_currency=pay_currency, network=intent.network, decimals=intent.decimals,
            pay_address=address, memo=memo, expires_at=expiry, initial_status=status,
            fee_paid_by_user=False, created_at=datetime.now(timezone.utc),
        )
        db.session.add(binding)
        cls._advance_intent(intent, "awaiting_payment")
        intent.updated_at = datetime.now(timezone.utc)
        db.session.flush()
        return binding

    @classmethod
    def _validate_observation(cls, binding: NowPaymentsPaymentBinding, intent: CheckoutIntent, order: PurchaseOrder, data: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        payment_id, reference, price, price_currency, pay_amount, pay_currency, address, memo, expiry, parent, status = _provider_payload(data)
        if payment_id != binding.provider_payment_id or reference != intent.external_reference:
            raise CheckoutError("Provider payment identity is unknown", "PROVIDER_IDENTITY_CONFLICT", 409)
        price_conflict = price_currency != "USD" or price != Decimal(order.amount_minor) / Decimal(100)
        foreign_parent = parent != binding.parent_payment_id
        wrong_asset = pay_currency != binding.pay_currency
        amount_conflict = pay_amount != Decimal(binding.pay_amount)
        immutable_binding_conflict = (
            address != binding.pay_address
            or memo != binding.memo
            or not _network_matches(data.get("network"), binding.network)
            or not _approved_address(address, binding.network)
            or (expiry is not None and expiry != binding.expires_at)
            or not _is_currency_quantized(pay_amount, binding.decimals)
        )
        actually_paid_value = data.get("actually_paid")
        outcome_amount_value = data.get("outcome_amount")
        outcome_currency_value = data.get("outcome_currency")
        review = price_conflict or foreign_parent or wrong_asset or amount_conflict or immutable_binding_conflict or status in {"partially_paid", "refunded"}
        actually_paid = outcome_amount = outcome_currency = None
        try:
            if actually_paid_value is not None:
                actually_paid_decimal = money_decimal(actually_paid_value)
                if not _is_currency_quantized(actually_paid_decimal, binding.decimals):
                    raise ValueError("actually paid violates asset quantum")
                actually_paid = _decimal_text(actually_paid_decimal)
            else:
                actually_paid_decimal = None
            if outcome_amount_value is not None:
                outcome_amount_decimal = money_decimal(outcome_amount_value)
                outcome_amount = _decimal_text(outcome_amount_decimal)
            else:
                outcome_amount_decimal = None
            if outcome_currency_value is not None:
                if not isinstance(outcome_currency_value, str) or not _CURRENCY.fullmatch(outcome_currency_value.lower()):
                    raise ValueError("outcome currency invalid")
                outcome_currency = outcome_currency_value.lower()
        except ValueError:
            actually_paid_decimal = outcome_amount_decimal = None
            review = True
        if (actually_paid_decimal is not None and actually_paid_decimal > 0
                and actually_paid_decimal != Decimal(binding.pay_amount)):
            # Both under- and over-deposits require a human decision. A zero
            # interim amount remains normal for waiting/confirmation statuses.
            review = True
        final_safe = (
            status == "finished" and not review and actually_paid_decimal is not None and outcome_amount_decimal is not None
            and actually_paid_decimal > 0 and actually_paid_decimal == Decimal(binding.pay_amount)
            and outcome_amount_decimal > 0 and outcome_currency == intent.outcome_currency
        )
        if status == "finished" and not final_safe:
            review = True
        return {
            "payment_id": payment_id, "status": status, "pay_amount": _decimal_text(pay_amount),
            "actually_paid": actually_paid, "outcome_amount": outcome_amount, "outcome_currency": outcome_currency,
        }, review

    @classmethod
    def _record_grant(cls, order: PurchaseOrder, binding: NowPaymentsPaymentBinding, observation: NowPaymentsObservation, intent: CheckoutIntent) -> None:
        existing = cls._grant(order.id)
        if existing is not None:
            # A valid signed terminal notification with a distinct canonical
            # digest is retained as observation evidence, never a second grant.
            return
        receipt_id, journal_id = str(uuid4()), str(uuid4())
        receipt = NowPaymentsVerifiedReceipt(id=receipt_id, order_id=order.id, binding_id=binding.id, observation_id=observation.id,
                                             amount_minor=order.amount_minor, currency="USD", source="nowpayments", created_at=datetime.now(timezone.utc))
        journal = NowPaymentsSettlementJournal(id=journal_id, receipt_id=receipt_id, order_id=order.id,
                                                amount_minor=order.amount_minor, currency="USD", created_at=datetime.now(timezone.utc))
        grant = OrderEntitlementGrant(id=str(uuid4()), order_id=order.id, receipt_id=receipt_id, observation_id=observation.id,
                                      source="nowpayments", policy_version=intent.policy_version, created_at=datetime.now(timezone.utc))
        db.session.add(receipt)
        db.session.flush()
        db.session.add(journal)
        db.session.flush()
        db.session.add_all([
            NowPaymentsSettlementEntry(id=str(uuid4()), journal_id=journal_id, line_number=1, account_code="provider_clearing", side="debit", amount_minor=order.amount_minor),
            NowPaymentsSettlementEntry(id=str(uuid4()), journal_id=journal_id, line_number=2, account_code="unapplied_order_receipts", side="credit", amount_minor=order.amount_minor),
            grant,
        ])
        db.session.flush()

    @staticmethod
    def _advance_intent(intent: CheckoutIntent, desired: str | None) -> None:
        """Never let an older provider status erase a more progressed local fact."""
        if desired is None or intent.state == desired:
            return
        if intent.state == "paid":
            if desired == "manual_review":
                intent.state = desired
            return
        if intent.state == "manual_review":
            return
        if desired == "manual_review":
            intent.state = desired
            return
        rank = {"prepared": 0, "creating": 1, "awaiting_payment": 2, "processing": 3,
                "expired": 4, "failed": 4, "paid": 5}
        if rank.get(desired, -1) >= rank.get(intent.state, -1):
            if intent.state in {"expired", "failed"} and desired == "paid":
                intent.state = "manual_review"
            else:
                intent.state = desired

    @classmethod
    def record_provider_observation(cls, data: Mapping[str, Any], raw_digest: str, *, source: str, signed: bool) -> tuple[NowPaymentsObservation | None, bool]:
        if not isinstance(data, Mapping) or not _HASH.fullmatch(raw_digest) or source not in {"ipn", "refresh"}:
            raise CheckoutError("Provider payload is invalid", "IPN_SCHEMA_INVALID", 400)
        try:
            payment_id = canonical_provider_id(data.get("payment_id"))
            reference = _required_string(data, "order_id", 96, pattern=_IDENTIFIER)
        except ValueError:
            raise CheckoutError("Provider payload is invalid", "IPN_SCHEMA_INVALID", 400) from None
        intent = db.session.execute(select(CheckoutIntent).where(CheckoutIntent.external_reference == reference, CheckoutIntent.provider == "nowpayments").with_for_update()).scalar_one_or_none()
        if intent is None:
            raise CheckoutError("Provider payment identity is unknown", "PROVIDER_IDENTITY_CONFLICT", 409)
        binding = db.session.execute(select(NowPaymentsPaymentBinding).where(NowPaymentsPaymentBinding.intent_id == intent.id).with_for_update()).scalar_one_or_none()
        if binding is None:
            # Signed IPN reconciliation is allowed only for the existing command/reference;
            # require a complete binding-shaped payload and never use client input.
            if not signed:
                raise CheckoutError("Payment binding is unavailable", "PROVIDER_IDENTITY_CONFLICT", 409)
            order = db.session.execute(select(PurchaseOrder).where(PurchaseOrder.id == intent.order_id).with_for_update()).scalar_one()
            try:
                binding = cls.record_binding_from_provider(
                    intent.id, data, canonical_ipn_bytes(dict(data)), allow_terminal=True
                )
            except (ValueError, CheckoutError):
                intent.state, intent.updated_at = "manual_review", datetime.now(timezone.utc)
                # No valid binding exists to own an observation. Preserve the
                # trusted command-level stop instead of throwing through the
                # route's rollback. The webhook commits before ACK; later valid
                # evidence cannot silently turn this reviewed command into a grant.
                db.session.flush()
                return None, True
        order = db.session.execute(select(PurchaseOrder).where(PurchaseOrder.id == binding.order_id).with_for_update()).scalar_one()
        existing = db.session.execute(select(NowPaymentsObservation).where(
            NowPaymentsObservation.binding_id == binding.id, NowPaymentsObservation.payload_digest == raw_digest
        )).scalar_one_or_none()
        if existing is not None:
            return existing, False
        try:
            normalized, review = cls._validate_observation(binding, intent, order, data)
        except CheckoutError:
            raise
        except ValueError:
            # The signed/GET payload was tied to the already locked binding by
            # provider ID and external reference above. Preserve that malformed
            # evidence as a sticky review instead of returning an error that the
            # route would roll back, thereby allowing a later notification to
            # auto-grant an under/over or malformed amount.
            reported_status = data.get("payment_status")
            normalized = {
                "payment_id": payment_id,
                "status": reported_status if isinstance(reported_status, str) and reported_status in _ALLOWED_STATUSES else binding.initial_status,
                "pay_amount": None,
                "actually_paid": None,
                "outcome_amount": None,
                "outcome_currency": None,
            }
            review = True
        if normalized["status"] == "finished" and intent.state in {"expired", "failed", "manual_review"} and cls._grant(order.id) is None:
            # A terminal or reviewed command is not automatically resurrected
            # by a late notification, even when the deposit amount is exact.
            # Preserve its signed observation for an explicit manual review.
            review = True
        observation = NowPaymentsObservation(
            id=str(uuid4()), binding_id=binding.id, order_id=order.id, provider_payment_id=payment_id,
            payload_digest=raw_digest, source=source, status=normalized["status"], review_required=review,
            pay_amount=normalized["pay_amount"], actually_paid=normalized["actually_paid"],
            outcome_amount=normalized["outcome_amount"], outcome_currency=normalized["outcome_currency"], created_at=datetime.now(timezone.utc),
        )
        db.session.add(observation)
        db.session.flush()
        prior_review = db.session.execute(select(NowPaymentsObservation.id).where(
            NowPaymentsObservation.binding_id == binding.id, NowPaymentsObservation.review_required.is_(True),
            NowPaymentsObservation.id != observation.id,
        ).limit(1)).scalar_one_or_none() is not None
        desired: str | None
        if signed and normalized["status"] == "finished" and not review and not prior_review:
            cls._record_grant(order, binding, observation, intent)
            desired = "paid"
        elif review:
            desired = "manual_review"
        elif source == "refresh" and normalized["status"] == "finished":
            # A trusted GET may show a terminal provider status for owner
            # reconciliation but cannot grant or make a later signed IPN fail.
            # Show processing while awaiting that valid signed IPN.
            desired = "processing"
        elif normalized["status"] in {"confirming", "confirmed", "sending"}:
            desired = "processing"
        elif normalized["status"] == "expired":
            desired = "expired"
        elif normalized["status"] == "failed":
            desired = "failed"
        else:
            desired = "awaiting_payment"
        before = intent.state
        cls._advance_intent(intent, desired)
        if intent.state != before:
            intent.updated_at = datetime.now(timezone.utc)
        db.session.flush()
        return observation, True

    @staticmethod
    def _admin_page(arguments) -> tuple[int, int, int]:
        if any(name not in {"page", "per_page"} or len(arguments.getlist(name)) != 1 for name in arguments.keys()):
            raise CheckoutError("Invalid payment-record query", "PAYMENT_RECORDS_QUERY_INVALID", 400)
        def canonical(name: str, default: int, maximum: int) -> int:
            values = arguments.getlist(name)
            value = str(default) if not values else values[0]
            if not isinstance(value, str) or not value.isascii() or not value.isdecimal() or len(value) > 5:
                raise CheckoutError("Invalid payment-record query", "PAYMENT_RECORDS_QUERY_INVALID", 400)
            parsed = int(value)
            if not 1 <= parsed <= maximum or str(parsed) != value:
                raise CheckoutError("Invalid payment-record query", "PAYMENT_RECORDS_QUERY_INVALID", 400)
            return parsed
        page, per_page = canonical("page", 1, 10_000), canonical("per_page", 20, 50)
        offset = (page - 1) * per_page
        if offset > 10_000:
            raise CheckoutError("Invalid payment-record query", "PAYMENT_RECORDS_QUERY_INVALID", 400)
        return page, per_page, offset

    @staticmethod
    def _collection_pagination(page: int, per_page: int, total: int) -> dict[str, Any]:
        pages = (total + per_page - 1) // per_page if total else 0
        return {"page": page, "per_page": per_page, "total": total, "pages": pages,
                "has_next": page < pages, "has_prev": page > 1}

    @classmethod
    def _collection_unavailable(cls, owner_context: dict[str, Any], page: int, per_page: int) -> dict[str, Any]:
        return {
            "schema_version": 1, "owner_context": owner_context, "availability": False,
            "source_unavailable": True, "reason": "CHECKOUT_STORAGE_NOT_READY", "records": [],
            "pagination": cls._collection_pagination(page, per_page, 0),
        }

    @staticmethod
    def _grant_chain_is_valid(
        order: PurchaseOrder,
        binding: NowPaymentsPaymentBinding | None,
        grant: OrderEntitlementGrant | None,
    ) -> bool:
        if grant is None:
            return True
        if binding is None or grant.order_id != order.id or grant.observation_id is None:
            return False
        receipt = db.session.execute(select(NowPaymentsVerifiedReceipt).where(
            NowPaymentsVerifiedReceipt.id == grant.receipt_id
        ).execution_options(skip_hierarchy_scope=True)).scalar_one_or_none()
        journal = None if receipt is None else db.session.execute(select(NowPaymentsSettlementJournal).where(
            NowPaymentsSettlementJournal.receipt_id == receipt.id
        ).execution_options(skip_hierarchy_scope=True)).scalar_one_or_none()
        observation = db.session.execute(select(NowPaymentsObservation).where(
            NowPaymentsObservation.id == grant.observation_id
        ).execution_options(skip_hierarchy_scope=True)).scalar_one_or_none()
        entries = [] if journal is None else db.session.execute(select(NowPaymentsSettlementEntry).where(
            NowPaymentsSettlementEntry.journal_id == journal.id
        ).order_by(NowPaymentsSettlementEntry.line_number).execution_options(skip_hierarchy_scope=True)).scalars().all()
        return bool(
            receipt is not None and journal is not None and observation is not None
            and receipt.order_id == order.id and receipt.binding_id == binding.id
            and receipt.observation_id == observation.id and receipt.amount_minor == order.amount_minor
            and receipt.currency == "USD" and receipt.source == "nowpayments"
            and journal.order_id == order.id and journal.amount_minor == order.amount_minor and journal.currency == "USD"
            and observation.binding_id == binding.id and observation.order_id == order.id
            and len(entries) == 2 and [(entry.line_number, entry.account_code, entry.side, entry.amount_minor) for entry in entries] == [
                (1, "provider_clearing", "debit", order.amount_minor),
                (2, "unapplied_order_receipts", "credit", order.amount_minor),
            ]
        )

    @classmethod
    def _record_dto(
        cls,
        order: PurchaseOrder,
        intent: CheckoutIntent,
        binding: NowPaymentsPaymentBinding | None,
        latest: NowPaymentsObservation | None,
        grant: OrderEntitlementGrant | None,
    ) -> dict[str, Any]:
        try:
            OrderService._integrity(order)
        except OrderError:
            raise CheckoutError("Stored payment record integrity failed", "PAYMENT_RECORDS_INTEGRITY_FAILED", 503) from None
        if not cls._grant_chain_is_valid(order, binding, grant):
            raise CheckoutError("Stored payment record integrity failed", "PAYMENT_RECORDS_INTEGRITY_FAILED", 503)
        try:
            snapshot = json.loads(order.snapshot_json)
            terms = snapshot.get("terms") if isinstance(snapshot, dict) else None
            program_name = terms.get("name") if isinstance(terms, dict) and isinstance(terms.get("name"), str) else None
        except (TypeError, ValueError):
            program_name = None
        state, review_required, _reason = cls._intent_state(intent, latest, grant)
        observation = cls._display_observation(latest, grant)
        return {
            "order_id": order.id, "program_id": order.program_id, "program_name": program_name,
            "user_id": order.user_id, "tenant_id": order.tenant_id, "state": state,
            "paid": grant is not None, "review_required": review_required,
            "quote_amount_minor": str(order.amount_minor), "quote_currency": "USD",
            "provider_payment_id": binding.provider_payment_id if binding else None,
            "pay_currency": binding.pay_currency if binding else None,
            "network": binding.network if binding else None,
            "actually_paid": observation.actually_paid if observation else None,
            "outcome_amount": observation.outcome_amount if observation else None,
            "outcome_currency": observation.outcome_currency if observation else None,
            "updated_at": _iso(observation.created_at if observation else intent.updated_at),
            "recorded_purchase": grant is not None,
        }

    @classmethod
    def _local_records(cls, user, tenant, page: int, per_page: int, offset: int, *, owner_only: bool) -> dict[str, Any]:
        owner_context = {"user_id": user.id, "tenant_id": tenant.id, "role": _normal_role(user.role)}
        try:
            cls._storage_ready(read_only=True)
        except CheckoutError:
            return cls._collection_unavailable(owner_context, page, per_page)
        ranked = select(
            NowPaymentsObservation.id.label("observation_id"),
            NowPaymentsObservation.binding_id.label("binding_id"),
            func.row_number().over(
                partition_by=NowPaymentsObservation.binding_id,
                order_by=(NowPaymentsObservation.created_at.desc(), NowPaymentsObservation.id.desc()),
            ).label("position"),
        ).subquery("checkout_ranked_observation")
        latest = select(ranked.c.observation_id, ranked.c.binding_id).where(
            ranked.c.position == 1
        ).subquery("checkout_latest_observation")
        query = select(
            PurchaseOrder, CheckoutIntent, NowPaymentsPaymentBinding, NowPaymentsObservation, OrderEntitlementGrant,
        ).join(CheckoutIntent, CheckoutIntent.order_id == PurchaseOrder.id).outerjoin(
            NowPaymentsPaymentBinding, NowPaymentsPaymentBinding.intent_id == CheckoutIntent.id
        ).outerjoin(latest, latest.c.binding_id == NowPaymentsPaymentBinding.id).outerjoin(
            NowPaymentsObservation, NowPaymentsObservation.id == latest.c.observation_id,
        ).outerjoin(OrderEntitlementGrant, OrderEntitlementGrant.order_id == PurchaseOrder.id).where(
            PurchaseOrder.tenant_id == tenant.id
        ).order_by(PurchaseOrder.created_at.desc(), PurchaseOrder.id.desc()).execution_options(
            skip_hierarchy_scope=True, autoflush=False
        )
        if owner_only:
            query = query.where(PurchaseOrder.user_id == user.id)
        total = db.session.execute(select(func.count()).select_from(query.order_by(None).subquery())).scalar_one()
        rows = db.session.execute(query.limit(per_page).offset(offset)).all()
        records = [cls._record_dto(order, intent, binding, observation, grant)
                   for order, intent, binding, observation, grant in rows]
        return {
            "schema_version": 1, "owner_context": owner_context, "availability": True,
            "source_unavailable": False, "reason": None, "records": records,
            "pagination": cls._collection_pagination(page, per_page, total),
        }

    @classmethod
    def admin_records(cls, actor, arguments) -> dict[str, Any]:
        """Current-brand root finance history, independent of pilot enablement."""
        page, per_page, offset = cls._admin_page(arguments)
        user, tenant = cls._actor(actor)
        if not (Roles.is_admin(user.role) and complete_hierarchy_scope(user) and platform_root_scope(user)):
            raise CheckoutError("Admin payment-record scope is required", "PAYMENT_RECORDS_SCOPE_REQUIRED", 403)
        return cls._local_records(user, tenant, page, per_page, offset, owner_only=False)

    @classmethod
    def purchase_records(cls, actor, arguments) -> dict[str, Any]:
        """Current active trader/affiliate's own historical evidence, no pilot gate."""
        page, per_page, offset = cls._admin_page(arguments)
        user, tenant = cls._actor(actor)
        if _normal_role(user.role) not in {Roles.TRADER, Roles.AFFILIATE}:
            raise CheckoutError("Private purchase-record scope is required", "PURCHASE_RECORDS_SCOPE_REQUIRED", 403)
        return cls._local_records(user, tenant, page, per_page, offset, owner_only=True)

    @classmethod
    def refresh(cls, actor, order_id: str) -> RefreshReservation:
        policy, user, tenant = cls._policy_for_actor(actor)
        _user, _tenant, order = cls._owned_order(actor, order_id)
        intent = db.session.execute(select(CheckoutIntent).where(CheckoutIntent.order_id == order.id).with_for_update()).scalar_one_or_none()
        if intent is None:
            raise CheckoutError("No provider payment is bound to this order", "PAYMENT_NOT_BOUND", 409)
        binding = db.session.execute(select(NowPaymentsPaymentBinding).where(NowPaymentsPaymentBinding.intent_id == intent.id).with_for_update()).scalar_one_or_none()
        if binding is None:
            raise CheckoutError("No provider payment is bound to this order", "PAYMENT_NOT_BOUND", 409)
        now = datetime.now(timezone.utc)
        last_refresh = intent.last_refresh_at
        if last_refresh is not None and last_refresh.tzinfo is None:
            last_refresh = last_refresh.replace(tzinfo=timezone.utc)
        if last_refresh is not None and (now - last_refresh).total_seconds() < policy.refresh_min_seconds:
            raise CheckoutError("Payment refresh budget is exhausted", "REFRESH_RATE_LIMITED", 429)
        intent.last_refresh_at = now
        intent.updated_at = now
        db.session.flush()
        # The caller commits this budget marker before performing provider I/O.
        return RefreshReservation(order.id, binding.provider_payment_id)

    @classmethod
    def refresh_after_commit(cls, reservation: RefreshReservation) -> None:
        if not isinstance(reservation, RefreshReservation):
            raise CheckoutError("No provider payment is bound to this order", "PAYMENT_NOT_BOUND", 409)
        # Provider I/O begins immediately from frozen scalars. The subsequent
        # observation call performs its own fresh locks only after the GET ends.
        response, raw = NowPaymentsTransport.get_payment(reservation.provider_payment_id)
        # A GET with byte-identical canonical content must not consume the unique
        # digest of a later signed IPN: only the latter may record a purchase.
        cls.record_provider_observation(response, hashlib.sha256(b"refresh\x00" + raw).hexdigest(), source="refresh", signed=False)
