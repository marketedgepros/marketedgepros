"""Pure, provider-neutral regressions for offline crypto receipt rehearsals.

These tests deliberately use synthetic identities only.  They prove comparison
contracts, not a live-wallet, provider, ledger, conversion, or settlement flow.
"""
import ast
from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict, replace
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import socket
import sys

import pytest

from src.services import crypto_receipt_contract as contract
from src.services.crypto_receipt_contract import (
    CryptoBinding,
    CryptoContractError,
    assess_rehearsal_transfer,
    atomic_units,
    build_rehearsal_binding,
)


NOW = 1_800_000_000
ORDER_ID = "123e4567-e89b-12d3-a456-426614174000"
SNAPSHOT_HASH = "a" * 64
AUTHORITY_FLAGS = (
    "authenticated",
    "paid",
    "credit_authorized",
    "entitlement_authorized",
    "persisted",
)


def make_order(**changes):
    order = {
        "id": ORDER_ID,
        "snapshot_hash": SNAPSHOT_HASH,
        "user_id": 101,
        "tenant_id": 202,
        "amount_minor": 12_345,
        "currency": "USD",
    }
    order.update(changes)
    return order


def make_quote(**changes):
    quote = {
        "mode": "rehearsal",
        "quote_id": "TEST_QUOTE_001",
        "merchant_context": "TEST_MERCHANT",
        "asset_id": "TEST_ASSET",
        "network_id": "TEST_NETWORK",
        "decimals": 3,
        "recipient": "TEST_RECIPIENT",
        "memo": "TEST_MEMO",
        "amount": "7.125",
        "created_at": NOW - 100,
        "expires_at": NOW + 3_600,
        "required_confirmations": 3,
    }
    quote.update(changes)
    return quote


def make_binding(**quote_changes):
    return build_rehearsal_binding(make_order(), make_quote(**quote_changes), now=NOW)


def make_transfer(binding, **changes):
    transfer = {
        "mode": "rehearsal",
        "merchant_context": binding.merchant_context,
        "asset_id": binding.asset_id,
        "network_id": binding.network_id,
        "decimals": binding.decimals,
        "recipient": binding.recipient,
        "memo": binding.memo,
        "amount_atomic": binding.expected_atomic,
        "transaction_id": "TEST_TX_001",
        "transfer_index": 0,
        "confirmations": binding.required_confirmations,
        "finalized": True,
        "canonical": True,
        "block_id": "TEST_BLOCK_001",
    }
    transfer.update(changes)
    return transfer


def assert_never_authorizes(result):
    assert {field: result[field] for field in AUTHORITY_FLAGS} == {
        "authenticated": False,
        "paid": False,
        "credit_authorized": False,
        "entitlement_authorized": False,
        "persisted": False,
    }


def independent_digest(value):
    """Reproduce the public SHA-256 encoding without calling module internals."""
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def test_build_binding_projects_only_the_required_explicit_rehearsal_inputs():
    order = make_order()
    quote = make_quote()
    binding = build_rehearsal_binding(order, quote, now=NOW)

    assert asdict(binding) == {
        "mode": "rehearsal",
        "order_id": ORDER_ID,
        "order_snapshot_hash": SNAPSHOT_HASH,
        "user_id": 101,
        "tenant_id": 202,
        "order_amount_minor": 12_345,
        "order_currency": "USD",
        "quote_id": "TEST_QUOTE_001",
        "merchant_context": "TEST_MERCHANT",
        "asset_id": "TEST_ASSET",
        "network_id": "TEST_NETWORK",
        "decimals": 3,
        "recipient": "TEST_RECIPIENT",
        "memo": "TEST_MEMO",
        "expected_atomic": 7_125,
        "created_at": NOW - 100,
        "expires_at": NOW + 3_600,
        "required_confirmations": 3,
        "binding_hash": binding.binding_hash,
    }
    assert len(binding.binding_hash) == 64
    assert build_rehearsal_binding(make_order(), make_quote(), now=NOW) == binding


def test_quote_allows_optional_memo_but_requires_a_positive_confirmation_threshold():
    binding = make_binding(memo=None)
    result = assess_rehearsal_transfer(binding, make_transfer(binding, memo=None), now=NOW)

    assert result["status"] == "matching_unverified_observation"
    assert_never_authorizes(result)
    with pytest.raises(CryptoContractError):
        build_rehearsal_binding(make_order(), make_quote(required_confirmations=0), now=NOW)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(unexpected="projection-smuggling"),
        lambda value: value.pop("snapshot_hash"),
        lambda value: value.update(currency="EUR"),
        lambda value: value.update(id="not-a-canonical-uuid"),
    ],
    ids=["extra-field", "missing-snapshot", "non-usd-order", "bad-order-id"],
)
def test_build_rejects_nonexact_order_projection(mutate):
    order = make_order()
    mutate(order)
    with pytest.raises(CryptoContractError):
        build_rehearsal_binding(order, make_quote(), now=NOW)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.pop("decimals"),
        lambda value: value.update(mode="live"),
        lambda value: value.update(usd_per_asset="1.00"),
        lambda value: value.update(asset_symbol="USDT"),
    ],
    ids=["no-decimal-default", "not-rehearsal", "no-usd-rate-inference", "no-symbol-substitute"],
)
def test_build_requires_an_exact_explicit_asset_quote(mutate):
    quote = make_quote()
    mutate(quote)
    with pytest.raises(CryptoContractError):
        build_rehearsal_binding(make_order(), quote, now=NOW)


@pytest.mark.parametrize(
    ("amount", "decimals", "expected"),
    [
        ("1", 0, 1),
        ("0.000001", 6, 1),
        ("7.125", 3, 7_125),
        ("9" * 36, 0, 10**36 - 1),
    ],
)
def test_atomic_units_accepts_only_exact_canonical_decimal_strings(amount, decimals, expected):
    assert atomic_units(amount, decimals) == expected


@pytest.mark.parametrize(
    ("amount", "decimals"),
    [
        (0, 0),
        (1.0, 0),
        (True, 0),
        ("0", 0),
        ("01", 0),
        ("1.", 0),
        ("1e2", 0),
        ("+1", 0),
        ("-1", 0),
        (" 1", 0),
        ("1.234", 2),
        ("9" * 37, 0),
    ],
    ids=[
        "integer-not-string", "float", "bool", "zero", "leading-zero", "empty-fraction",
        "scientific", "plus-sign", "minus-sign", "whitespace", "rounding-required", "over-36-units",
    ],
)
def test_atomic_units_refuses_ambiguous_or_out_of_budget_values(amount, decimals):
    with pytest.raises(CryptoContractError):
        atomic_units(amount, decimals)


@pytest.mark.parametrize("decimals", [False, 1.0, -1, 31], ids=["bool", "float", "negative", "over-30"])
def test_atomic_units_requires_explicit_bounded_integer_precision(decimals):
    with pytest.raises(CryptoContractError):
        atomic_units("1", decimals)


@pytest.mark.parametrize(
    ("quote_changes", "call_now"),
    [
        ({"created_at": NOW + 1}, NOW),
        ({"created_at": NOW - 10, "expires_at": NOW - 10}, NOW),
        ({"created_at": NOW - 10, "expires_at": NOW + 86_391}, NOW),
    ],
    ids=["future-created", "zero-lifetime", "longer-than-one-day"],
)
def test_build_enforces_current_bounded_quote_lifetime(quote_changes, call_now):
    with pytest.raises(CryptoContractError):
        build_rehearsal_binding(make_order(), make_quote(**quote_changes), now=call_now)


def test_binding_is_frozen_and_input_projections_are_not_mutated():
    order = make_order()
    quote = make_quote()
    original_order, original_quote = deepcopy(order), deepcopy(quote)

    binding = build_rehearsal_binding(order, quote, now=NOW)

    assert order == original_order
    assert quote == original_quote
    with pytest.raises(FrozenInstanceError):
        binding.asset_id = "TEST_ASSET_REWRITTEN"


def test_corrupted_binding_hash_is_refused_before_any_observation_can_match():
    binding = make_binding()
    corrupted = replace(binding, binding_hash="0" * 64)

    with pytest.raises(CryptoContractError):
        assess_rehearsal_transfer(corrupted, make_transfer(binding), now=NOW)


def test_directly_constructed_invalid_binding_is_not_made_trusted_by_a_recomputed_hash():
    binding = make_binding()
    unsafe_fields = asdict(binding)
    unsafe_fields["order_currency"] = "EUR"
    unsafe_fields.pop("binding_hash")
    unsafe = CryptoBinding(**unsafe_fields, binding_hash=independent_digest(unsafe_fields))

    with pytest.raises(CryptoContractError):
        assess_rehearsal_transfer(unsafe, make_transfer(binding), now=NOW)


def test_matching_observation_is_explicitly_unverified_and_never_authorizes():
    binding = make_binding()
    result = assess_rehearsal_transfer(binding, make_transfer(binding), now=NOW)

    assert result["status"] == "matching_unverified_observation"
    assert result["mismatched_fields"] == []
    assert result["binding_hash"] == binding.binding_hash
    assert_never_authorizes(result)


@pytest.mark.parametrize(
    ("transfer_changes", "call_now", "expected_status"),
    [
        ({"amount_atomic": 7_124}, NOW, "underpaid_observation"),
        ({"amount_atomic": 7_126}, NOW, "overpaid_observation"),
        ({"canonical": False}, NOW, "noncanonical_observation"),
        ({"finalized": False}, NOW, "awaiting_finality"),
        ({"confirmations": 2}, NOW, "awaiting_finality"),
        ({}, NOW + 3_600, "quote_expired"),
        ({}, NOW - 101, "not_yet_valid"),
        ({"merchant_context": "FOREIGN_MERCHANT"}, NOW, "identity_mismatch"),
    ],
    ids=["underpaid", "overpaid", "noncanonical", "not-finalized", "under-confirmed", "expired", "before-created", "merchant-mismatch"],
)
def test_nonmatching_or_nonfinal_observations_are_all_no_fill(transfer_changes, call_now, expected_status):
    binding = make_binding()
    result = assess_rehearsal_transfer(binding, make_transfer(binding, **transfer_changes), now=call_now)

    assert result["status"] == expected_status
    assert_never_authorizes(result)


@pytest.mark.parametrize(
    ("field", "foreign_value"),
    [
        ("asset_id", "TEST_ASSET_FOREIGN_CONTRACT"),
        ("network_id", "TEST_NETWORK_FOREIGN"),
        ("recipient", "FOREIGN_RECIPIENT"),
        ("memo", "FOREIGN_MEMO"),
        ("decimals", 2),
        ("merchant_context", "FOREIGN_MERCHANT"),
    ],
    ids=["foreign-token-contract", "foreign-network", "recipient", "memo", "precision", "merchant"],
)
def test_token_and_recipient_identity_fields_are_exact_not_symbol_or_network_guesses(field, foreign_value):
    binding = make_binding()
    result = assess_rehearsal_transfer(binding, make_transfer(binding, **{field: foreign_value}), now=NOW)

    assert result["status"] == "identity_mismatch"
    assert result["mismatched_fields"] == [field]
    assert_never_authorizes(result)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda value: value.update(fee_atomic=1),
        lambda value: value.pop("block_id"),
        lambda value: value.update(mode="provider"),
    ],
    ids=["no-fee-field", "missing-block-id", "not-rehearsal"],
)
def test_transfer_schema_is_exact_and_provider_neutral(mutate):
    binding = make_binding()
    transfer = make_transfer(binding)
    mutate(transfer)
    with pytest.raises(CryptoContractError):
        assess_rehearsal_transfer(binding, transfer, now=NOW)


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("amount_atomic", True),
        ("amount_atomic", 7_125.0),
        ("transfer_index", True),
        ("confirmations", True),
        ("decimals", True),
        ("finalized", 1),
        ("canonical", "false"),
    ],
    ids=["atomic-bool", "atomic-float", "index-bool", "confirmation-bool", "decimal-bool", "finality-int", "canonical-string"],
)
def test_transfer_uses_exact_integer_and_boolean_observation_types(field, invalid_value):
    binding = make_binding()
    with pytest.raises(CryptoContractError):
        assess_rehearsal_transfer(binding, make_transfer(binding, **{field: invalid_value}), now=NOW)


@pytest.mark.parametrize("invalid_now", [True, 0, 10_000_000_000], ids=["bool", "below-range", "above-range"])
def test_assessment_now_is_a_bounded_plain_integer(invalid_now):
    binding = make_binding()
    with pytest.raises(CryptoContractError):
        assess_rehearsal_transfer(binding, make_transfer(binding), now=invalid_now)


def test_event_identity_distinguishes_transfers_with_same_network_and_transaction():
    binding = make_binding()
    first = assess_rehearsal_transfer(binding, make_transfer(binding, transfer_index=0), now=NOW)
    second = assess_rehearsal_transfer(binding, make_transfer(binding, transfer_index=1), now=NOW)

    assert first["event_identity_hash"] != second["event_identity_hash"]
    assert first["observation_hash"] != second["observation_hash"]
    assert_never_authorizes(first)
    assert_never_authorizes(second)


@pytest.mark.parametrize(
    "transfer_changes",
    [{"confirmations": 4}, {"block_id": "TEST_BLOCK_002"}],
    ids=["confirmation-change", "block-change"],
)
def test_reobserving_same_event_changes_observation_not_event_identity(transfer_changes):
    binding = make_binding()
    original = assess_rehearsal_transfer(binding, make_transfer(binding), now=NOW)
    changed = assess_rehearsal_transfer(binding, make_transfer(binding, **transfer_changes), now=NOW)

    assert changed["event_identity_hash"] == original["event_identity_hash"]
    assert changed["observation_hash"] != original["observation_hash"]
    assert_never_authorizes(changed)


def test_partial_transfers_do_not_aggregate_and_fee_or_refund_fields_are_not_supported():
    binding = make_binding()
    first = assess_rehearsal_transfer(binding, make_transfer(binding, amount_atomic=3_000), now=NOW)
    second = assess_rehearsal_transfer(binding, make_transfer(binding, amount_atomic=4_125, transaction_id="TEST_TX_002"), now=NOW)

    assert first["status"] == second["status"] == "underpaid_observation"
    assert_never_authorizes(first)
    assert_never_authorizes(second)
    with pytest.raises(CryptoContractError):
        assess_rehearsal_transfer(binding, make_transfer(binding, refund_atomic=1), now=NOW)


def test_synthetic_unknown_asset_and_network_are_explicit_but_not_catalog_or_provider_verified():
    binding = make_binding(asset_id="TEST_ASSET_UNREGISTERED", network_id="TEST_NETWORK_UNCONFIGURED")
    result = assess_rehearsal_transfer(binding, make_transfer(binding), now=NOW)

    assert (binding.asset_id, binding.network_id) == ("TEST_ASSET_UNREGISTERED", "TEST_NETWORK_UNCONFIGURED")
    assert result["status"] == "matching_unverified_observation"
    assert_never_authorizes(result)


def test_contract_source_has_only_stdlib_imports_and_no_http_db_sdk_or_route_surface():
    source = inspect.getsource(contract)
    tree = ast.parse(source)
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported_roots.add((node.module or "").split(".", 1)[0])

    assert imported_roots == {"dataclasses", "hashlib", "json", "re"}
    assert not any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "route"
        for node in ast.walk(tree)
    )
    forbidden_names = {"Flask", "Blueprint", "db", "requests", "web3", "boto3", "socket", "os"}
    assert not ({node.id for node in ast.walk(tree) if isinstance(node, ast.Name)} & forbidden_names)


def test_fresh_contract_import_cannot_make_a_socket_connection(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("contract import must not attempt a socket connection")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    module_name = "crypto_receipt_contract_socket_canary"
    module_path = Path(contract.__file__)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    fresh_module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = fresh_module
    try:
        assert spec.loader is not None
        spec.loader.exec_module(fresh_module)
    finally:
        sys.modules.pop(module_name, None)

    assert fresh_module.CryptoBinding.__module__ == module_name


class _MisleadingString(str):
    def __ne__(self, other):
        return False


def test_crypto_contract_rejects_custom_string_equality_for_modes_and_currency():
    with pytest.raises(CryptoContractError):
        build_rehearsal_binding(make_order(currency=_MisleadingString('EUR')), make_quote(), now=NOW)
    with pytest.raises(CryptoContractError):
        build_rehearsal_binding(make_order(), make_quote(mode=_MisleadingString('live')), now=NOW)
    binding = make_binding()
    with pytest.raises(CryptoContractError):
        assess_rehearsal_transfer(binding, make_transfer(binding, mode=_MisleadingString('live')), now=NOW)


def test_crypto_contract_rejects_nonplain_string_keys_even_when_they_match_schema():
    order = make_order()
    order[_MisleadingString('currency')] = order.pop('currency')
    with pytest.raises(CryptoContractError):
        build_rehearsal_binding(order, make_quote(), now=NOW)


def test_crypto_contract_cardinality_is_checked_before_untrusted_keys_are_compared():
    class PoisonKey:
        def __hash__(self):
            return 8675309

        def __eq__(self, other):
            raise AssertionError('unexpected key comparison before schema size refusal')

    oversize = make_order()
    oversize[PoisonKey()] = 'unexpected'
    assert contract._shape(oversize, contract._ORDER) is False
    with pytest.raises(CryptoContractError):
        build_rehearsal_binding(oversize, make_quote(), now=NOW)


def test_crypto_contract_bounds_atomic_amount_before_regex_for_string_subclasses():
    with pytest.raises(CryptoContractError):
        atomic_units(_MisleadingString('1'), 0)
