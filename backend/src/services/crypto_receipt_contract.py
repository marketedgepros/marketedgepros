"""Offline crypto receipt rehearsal contract, not a wallet/provider integration.

Caller-supplied observations are untrusted. A matching result never authorizes
payment, wallet credit, trading entitlement or signing a transaction. No network,
DB, provider, secrets or price feed is accessed. No asset/network is enabled here.
"""
from dataclasses import dataclass
import hashlib
import json
import re


class CryptoContractError(ValueError):
    pass


_UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z')
_HASH = re.compile(r'[0-9a-f]{64}\Z')
_ID = re.compile(r'[A-Za-z0-9_:.-]{1,128}\Z')
_AMOUNT = re.compile(r'(?:0|[1-9][0-9]{0,35})(?:\.[0-9]{1,30})?\Z')
_LIMIT = 10 ** 36 - 1


def _identifier(value):
    if type(value) is not str or not _ID.fullmatch(value):
        raise CryptoContractError('A bounded explicit identity is required')
    return value


def _opaque(value, *, optional=False):
    if optional and value is None:
        return value
    if type(value) is not str or not 1 <= len(value) <= 256 or any(ord(c) < 33 or ord(c) > 126 for c in value):
        raise CryptoContractError('A bounded exact ASCII recipient or memo is required')
    return value


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise CryptoContractError('A bounded exact integer is required')
    return value


def atomic_units(amount, decimals):
    """Exact base units from a canonical decimal string, no float or rounding."""
    decimals = _integer(decimals, 0, 30)
    if type(amount) is not str or len(amount) > 67 or not _AMOUNT.fullmatch(amount):
        raise CryptoContractError('A canonical positive decimal amount string is required')
    whole, dot, fraction = amount.partition('.')
    if dot and len(fraction) > decimals:
        raise CryptoContractError('Amount precision exceeds the explicit asset precision')
    units = int(whole) * 10 ** decimals + (int(fraction.ljust(decimals, '0')) if dot else 0)
    if not 1 <= units <= _LIMIT:
        raise CryptoContractError('Amount is zero or exceeds the base-unit budget')
    return units


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()


@dataclass(frozen=True)
class CryptoBinding:
    """In-memory immutable rehearsal proposal; not persisted/authenticated evidence."""
    mode: str
    order_id: str
    order_snapshot_hash: str
    user_id: int
    tenant_id: int
    order_amount_minor: int
    order_currency: str
    quote_id: str
    merchant_context: str
    asset_id: str
    network_id: str
    decimals: int
    recipient: str
    memo: str | None
    expected_atomic: int
    created_at: int
    expires_at: int
    required_confirmations: int
    binding_hash: str


_ORDER = frozenset({'id', 'snapshot_hash', 'user_id', 'tenant_id', 'amount_minor', 'currency'})
_QUOTE = frozenset({'mode', 'quote_id', 'merchant_context', 'asset_id', 'network_id', 'decimals',
                    'recipient', 'memo', 'amount', 'created_at', 'expires_at', 'required_confirmations'})
_TRANSFER = frozenset({'mode', 'merchant_context', 'asset_id', 'network_id', 'decimals', 'recipient', 'memo',
                       'amount_atomic', 'transaction_id', 'transfer_index', 'confirmations', 'finalized',
                       'canonical', 'block_id'})


def _shape(value, required):
    # Check cardinality BEFORE iterating/hashing attacker-supplied keys. Plain
    # string keys/scalars prevent custom equality operators from bypassing modes.
    return (type(value) is dict and len(value) == len(required)
            and all(type(key) is str for key in value) and set(value) == required)


def build_rehearsal_binding(order, quote, *, now):
    """Require an explicit asset quote; never derive USDT/token units from USD.

    This validates only the supplied projections. Future adapters must verify the
    real frozen order, provider quote, asset registry, chain and merchant source.
    """
    now = _integer(now, 1, 9999999999)
    if not _shape(order, _ORDER) or not _shape(quote, _QUOTE):
        raise CryptoContractError('Exact order and quote projections are required')
    if type(order['id']) is not str or not _UUID.fullmatch(order['id']):
        raise CryptoContractError('A canonical order identifier is required')
    if type(order['snapshot_hash']) is not str or not _HASH.fullmatch(order['snapshot_hash']):
        raise CryptoContractError('An order snapshot hash is required')
    if type(order['currency']) is not str or order['currency'] != 'USD':
        raise CryptoContractError('Only the existing USD order protocol is represented')
    if type(quote['mode']) is not str or quote['mode'] != 'rehearsal':
        raise CryptoContractError('No live wallet or provider is configured')
    created = _integer(quote['created_at'], 1, 9999999999)
    expiry = _integer(quote['expires_at'], 1, 9999999999)
    if not created <= now < expiry or not 1 <= expiry - created <= 86400:
        raise CryptoContractError('The rehearsal quote is expired, future-dated or unbounded')
    core = dict(mode='rehearsal', order_id=order['id'], order_snapshot_hash=order['snapshot_hash'],
                user_id=_integer(order['user_id'], 1, 2147483647),
                tenant_id=_integer(order['tenant_id'], 1, 2147483647),
                order_amount_minor=_integer(order['amount_minor'], 1, 9999999999), order_currency='USD',
                quote_id=_identifier(quote['quote_id']), merchant_context=_identifier(quote['merchant_context']),
                asset_id=_identifier(quote['asset_id']), network_id=_identifier(quote['network_id']),
                decimals=_integer(quote['decimals'], 0, 30), recipient=_opaque(quote['recipient']),
                memo=_opaque(quote['memo'], optional=True),
                expected_atomic=atomic_units(quote['amount'], quote['decimals']),
                created_at=created, expires_at=expiry,
                required_confirmations=_integer(quote['required_confirmations'], 1, 100000))
    return CryptoBinding(**core, binding_hash=_digest(core))


def assess_rehearsal_transfer(binding, transfer, *, now):
    """Compare one untrusted normalized transfer; no persistence/dedup/settlement.

    Event identity includes network + transaction + transfer index, since one
    transaction can carry multiple token transfers. Canonical hashes are proposed
    keys only: a unique database inbox is still required for real deduplication.
    """
    now = _integer(now, 1, 9999999999)
    if type(binding) is not CryptoBinding or type(binding.mode) is not str or binding.mode != 'rehearsal':
        raise CryptoContractError('A rehearsal binding is required')
    if type(binding.binding_hash) is not str or not _HASH.fullmatch(binding.binding_hash):
        raise CryptoContractError('A canonical binding fingerprint is required')
    # A frozen dataclass is not an authenticity authority. Reconstruct through
    # the validator so direct construction/replacement cannot bypass field rules.
    units = _integer(binding.expected_atomic, 1, _LIMIT)
    scale = _integer(binding.decimals, 0, 30)
    amount = str(units // 10 ** scale)
    if scale:
        amount += '.' + str(units % 10 ** scale).zfill(scale)
    validated = build_rehearsal_binding(
        {'id': binding.order_id, 'snapshot_hash': binding.order_snapshot_hash, 'user_id': binding.user_id,
         'tenant_id': binding.tenant_id, 'amount_minor': binding.order_amount_minor, 'currency': binding.order_currency},
        {'mode': binding.mode, 'quote_id': binding.quote_id, 'merchant_context': binding.merchant_context,
         'asset_id': binding.asset_id, 'network_id': binding.network_id, 'decimals': scale,
         'recipient': binding.recipient, 'memo': binding.memo, 'amount': amount,
         'created_at': binding.created_at, 'expires_at': binding.expires_at,
         'required_confirmations': binding.required_confirmations}, now=binding.created_at)
    if validated != binding:
        raise CryptoContractError('Binding is not a canonical rehearsal contract')
    if not _shape(transfer, _TRANSFER) or type(transfer['mode']) is not str or transfer['mode'] != 'rehearsal':
        raise CryptoContractError('An exact rehearsal transfer is required')
    for field in ['merchant_context', 'asset_id', 'network_id', 'transaction_id', 'block_id']:
        _identifier(transfer[field])
    _opaque(transfer['recipient'])
    _opaque(transfer['memo'], optional=True)
    amount_atomic = _integer(transfer['amount_atomic'], 1, _LIMIT)
    _integer(transfer['decimals'], 0, 30)
    _integer(transfer['transfer_index'], 0, 1000000)
    _integer(transfer['confirmations'], 0, 1000000)
    if type(transfer['finalized']) is not bool or type(transfer['canonical']) is not bool:
        raise CryptoContractError('Explicit chain-observation booleans are required')
    mismatches = [field for field in ['merchant_context', 'asset_id', 'network_id', 'decimals', 'recipient', 'memo']
                  if transfer[field] != getattr(binding, field)]
    if mismatches:
        status = 'identity_mismatch'
    elif now < binding.created_at:
        status = 'not_yet_valid'
    elif now >= binding.expires_at:
        status = 'quote_expired'
    elif not transfer['canonical']:
        status = 'noncanonical_observation'
    elif amount_atomic < binding.expected_atomic:
        status = 'underpaid_observation'
    elif amount_atomic > binding.expected_atomic:
        status = 'overpaid_observation'
    elif not transfer['finalized'] or transfer['confirmations'] < binding.required_confirmations:
        status = 'awaiting_finality'
    else:
        status = 'matching_unverified_observation'
    identity = {field: transfer[field] for field in ['merchant_context', 'network_id', 'transaction_id', 'transfer_index']}
    return {'schema_version': 1, 'mode': 'rehearsal', 'status': status, 'mismatched_fields': mismatches,
            'binding_hash': binding.binding_hash, 'event_identity_hash': _digest(identity),
            'observation_hash': _digest(transfer), 'authenticated': False, 'paid': False,
            'credit_authorized': False, 'entitlement_authorized': False, 'persisted': False}
