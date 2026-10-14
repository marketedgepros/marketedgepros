"""Canonical evaluation-family policy and private legacy challenge-term helpers.

The policy document is intentionally shared with the frontend.  This module only
validates/serializes catalog facts; it does not enable trading, settlement, MT5,
or lifecycle transitions.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
from typing import Any, Mapping


_POLICY_PATH = Path(__file__).resolve().parents[3] / "frontend" / "src" / "services" / "programEvaluationProfiles.json"
_PRIVATE_HISTORY_KEY = "_mep_legacy_challenge_terms"
_MAX_JSON_BYTES = 64 * 1024
_MAX_HISTORY_ENTRIES = 128
_MAX_HISTORY_ENTRY_BYTES = 16 * 1024
_ID_TEXT = re.compile(r"[1-9][0-9]{0,9}\Z", re.ASCII)
_DECIMAL_TEXT = re.compile(r"(?:0|[1-9][0-9]{0,7})(?:\.[0-9]{1,2})?\Z", re.ASCII)
_SUPPORTED_VERSION = "mep-evaluation-families-v1"

# This is deliberately a fixed contract, not an inferred family scheme.  A
# changed or partial source document must make assigned catalog rows unavailable
# until reviewed rather than silently changing an offer's terms.
_EXPECTED_PHASE_TARGETS = {
    "one_phase": ("10.00",),
    "two_phase": ("8.00", "5.00"),
    "three_phase": ("5.00", "5.00", "5.00"),
    "instant_funding": (),
}
_COMMON_KEYS = frozenset({
    "max_daily_loss", "max_total_loss", "drawdown_type", "profit_split",
    "operator_share", "daily_loss_amount_base", "daily_threshold_base",
    "breach_comparison", "evaluation_target_basis",
    "evaluation_requires_closed_positions", "phase_reset_basis",
    "phase_profit_carryover", "phase_loss_carryover", "daily_reset_timezone",
    "daily_reset_time", "funded_account_type", "eligible_profit_definition",
    "payout_schedule",
})
_PROFILE_KEYS = frozenset({
    "availability", "phase_targets", "evaluation_target_basis",
    "evaluation_requires_closed_positions", "phase_reset_basis",
    "phase_profit_carryover", "phase_loss_carryover",
})


class EvaluationPolicyError(ValueError):
    """A canonical policy, assignment, or private historical snapshot is unsafe."""


@dataclass(frozen=True)
class LegacyTermsLookup:
    """An archived-term lookup with no implicit fallback on a bad matching entry."""

    found: bool
    valid: bool
    terms: dict[str, Any] | None


def _reject_duplicate_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_number(_value: str):
    # The source document is a string/boolean/null policy contract.  Numeric
    # JSON values invite float drift and are not part of its schema.
    raise ValueError("numeric JSON values are not permitted")


def _json_bytes(value: Any, *, maximum: int = _MAX_JSON_BYTES) -> bytes:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise EvaluationPolicyError("JSON value is invalid") from None
    result = encoded.encode("utf-8")
    if len(result) > maximum:
        raise EvaluationPolicyError("JSON value exceeds its bounded budget")
    return result


def _require_text(value: Any, field: str, *, maximum: int = 128) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise EvaluationPolicyError(f"Policy field is invalid: {field}")
    return value


def _exact_percent(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _DECIMAL_TEXT.fullmatch(value):
        raise EvaluationPolicyError(f"Policy field is invalid: {field}")
    try:
        decimal = Decimal(value)
    except InvalidOperation:
        raise EvaluationPolicyError(f"Policy field is invalid: {field}") from None
    if not decimal.is_finite() or decimal < 0 or decimal > Decimal("100") or decimal != decimal.quantize(Decimal("0.01")):
        raise EvaluationPolicyError(f"Policy field is invalid: {field}")
    return format(decimal.quantize(Decimal("0.01")), ".2f")


def _no_float(value: Any) -> None:
    if isinstance(value, float):
        raise EvaluationPolicyError("Floating-point policy data is not permitted")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise EvaluationPolicyError("Policy object keys must be strings")
            _no_float(item)
    elif isinstance(value, list):
        for item in value:
            _no_float(item)


def _load_document() -> dict[str, Any]:
    try:
        raw = _POLICY_PATH.read_text(encoding="utf-8")
        if len(raw.encode("utf-8")) > _MAX_JSON_BYTES:
            raise ValueError("source budget")
        document = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_object,
            parse_int=_reject_number,
            parse_float=_reject_number,
            parse_constant=_reject_number,
        )
    except (OSError, UnicodeError, ValueError, RecursionError):
        raise EvaluationPolicyError("Canonical evaluation policy is unavailable") from None
    if not isinstance(document, dict) or set(document) != {"version", "common", "profiles"}:
        raise EvaluationPolicyError("Canonical evaluation policy is malformed")
    _no_float(document)
    return document


def _canonical_document() -> tuple[str, dict[str, Any], dict[str, dict[str, Any]]]:
    document = _load_document()
    version = _require_text(document["version"], "version", maximum=64)
    if version != _SUPPORTED_VERSION:
        raise EvaluationPolicyError("Canonical evaluation policy version is unsupported")
    common = document["common"]
    profiles = document["profiles"]
    if not isinstance(common, dict) or set(common) != _COMMON_KEYS:
        raise EvaluationPolicyError("Canonical common policy is malformed")
    if not isinstance(profiles, dict) or set(profiles) != set(_EXPECTED_PHASE_TARGETS):
        raise EvaluationPolicyError("Canonical policy profiles are malformed")

    # Fixed approved common terms. Nullable operational fields remain explicitly
    # null rather than becoming invented delivery/readiness claims.
    expected_common = {
        "max_daily_loss": "5.00",
        "max_total_loss": "10.00",
        "drawdown_type": "static",
        "profit_split": "90.00",
        "operator_share": "10.00",
        "daily_loss_amount_base": "initial_account_size",
        "daily_threshold_base": "day_start_closed_balance",
        "breach_comparison": "equity_less_than_or_equal_to_threshold",
        "evaluation_target_basis": "closed_profit_after_trading_costs",
        "evaluation_requires_closed_positions": True,
        "phase_reset_basis": "initial_account_size",
        "phase_profit_carryover": False,
        "phase_loss_carryover": False,
        "daily_reset_timezone": None,
        "daily_reset_time": None,
        "funded_account_type": None,
        "eligible_profit_definition": None,
        "payout_schedule": None,
    }
    if common != expected_common:
        raise EvaluationPolicyError("Canonical common policy is unsupported")

    normalized_profiles: dict[str, dict[str, Any]] = {}
    for program_type, expected_targets in _EXPECTED_PHASE_TARGETS.items():
        profile = profiles.get(program_type)
        if not isinstance(profile, dict) or set(profile) - _PROFILE_KEYS:
            raise EvaluationPolicyError("Canonical profile is malformed")
        if set(profile) != {"availability", "phase_targets"} | (
            {"evaluation_target_basis", "evaluation_requires_closed_positions", "phase_reset_basis", "phase_profit_carryover", "phase_loss_carryover"}
            if program_type == "instant_funding" else set()
        ):
            raise EvaluationPolicyError("Canonical profile is incomplete")
        expected_availability = "coming_soon" if program_type == "instant_funding" else "evaluation_catalog"
        if profile.get("availability") != expected_availability:
            raise EvaluationPolicyError("Canonical profile availability is unsupported")
        targets = profile.get("phase_targets")
        if (
            not isinstance(targets, list)
            or tuple(targets) != expected_targets
            or tuple(_exact_percent(item, "phase_targets") for item in targets) != expected_targets
        ):
            raise EvaluationPolicyError("Canonical phase targets are unsupported")
        if program_type == "instant_funding":
            for key in ("evaluation_target_basis", "evaluation_requires_closed_positions", "phase_reset_basis", "phase_profit_carryover", "phase_loss_carryover"):
                if profile.get(key) is not None:
                    raise EvaluationPolicyError("Canonical instant profile is unsupported")
        normalized_profiles[program_type] = deepcopy(profile)
    return version, deepcopy(common), normalized_profiles


def build_evaluation_policy(program_type: str) -> dict[str, Any]:
    """Return the complete exact snapshot for one approved program family."""
    if not isinstance(program_type, str):
        raise EvaluationPolicyError("Program type is invalid")
    version, common, profiles = _canonical_document()
    profile = profiles.get(program_type)
    if profile is None:
        raise EvaluationPolicyError("Program type has no canonical evaluation policy")
    result: dict[str, Any] = {"version": version, "program_type": program_type}
    result.update(common)
    result.update(profile)
    result["phases"] = len(profile["phase_targets"])
    _no_float(result)
    return result


def is_coming_soon_program_type(program_type: Any) -> bool:
    """Identify a configured Coming soon family without trusting row metadata."""
    if not isinstance(program_type, str):
        return False
    try:
        return build_evaluation_policy(program_type).get("availability") == "coming_soon"
    except EvaluationPolicyError:
        return False


def _scalar_decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, (bool, float)) or value is None:
        raise EvaluationPolicyError(f"Program scalar is invalid: {field}")
    try:
        decimal = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        raise EvaluationPolicyError(f"Program scalar is invalid: {field}") from None
    if not decimal.is_finite() or decimal != decimal.quantize(Decimal("0.01")):
        raise EvaluationPolicyError(f"Program scalar is invalid: {field}")
    return decimal


def validate_program_evaluation_policy(program: Any, rules: Mapping[str, Any] | None = None) -> dict[str, Any] | None:
    """Validate a versioned assignment if present; unassigned legacy rows pass through.

    No partial policy, percentage-only match, float coercion, or source fallback is
    accepted.  The return value is a deep copy of the expected canonical snapshot.
    """
    raw_rules = getattr(program, "rules", None) if rules is None else rules
    if not isinstance(raw_rules, Mapping):
        raise EvaluationPolicyError("Program rules are invalid")
    if "evaluation_policy" not in raw_rules:
        return None
    snapshot = raw_rules.get("evaluation_policy")
    if not isinstance(snapshot, dict):
        raise EvaluationPolicyError("Evaluation policy assignment is invalid")
    _no_float(snapshot)
    program_type = getattr(program, "type", None)
    expected = build_evaluation_policy(program_type)
    # ``dict ==`` permits True == 1; the canonical JSON bytes prove both exact
    # shape and scalar JSON types after float rejection.
    if _json_bytes(snapshot) != _json_bytes(expected):
        raise EvaluationPolicyError("Evaluation policy assignment does not match the canonical snapshot")
    targets = expected["phase_targets"]
    expected_target = Decimal("0.00") if expected["availability"] == "coming_soon" else Decimal(targets[0])
    if _scalar_decimal(getattr(program, "profit_target", None), "profit_target") != expected_target:
        raise EvaluationPolicyError("Program profit target does not match its evaluation policy")
    if _scalar_decimal(getattr(program, "max_daily_loss", None), "max_daily_loss") != Decimal("5.00"):
        raise EvaluationPolicyError("Program daily loss does not match its evaluation policy")
    if _scalar_decimal(getattr(program, "max_total_loss", None), "max_total_loss") != Decimal("10.00"):
        raise EvaluationPolicyError("Program total loss does not match its evaluation policy")
    if _scalar_decimal(getattr(program, "profit_split", None), "profit_split") != Decimal("90.00"):
        raise EvaluationPolicyError("Program profit split does not match its evaluation policy")
    if _scalar_decimal(getattr(program, "profit_split_percentage", None), "profit_split_percentage") != Decimal("90.00"):
        raise EvaluationPolicyError("Program profit split percentage does not match its evaluation policy")
    if raw_rules.get("drawdown_type") != expected["drawdown_type"]:
        raise EvaluationPolicyError("Program drawdown type does not match its evaluation policy")
    return deepcopy(expected)


def _legacy_decimal(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return _exact_percent(value, field)


def _validated_legacy_terms(value: Any) -> dict[str, Any]:
    """Validate only the immutable archived values historical getters consume.

    The remaining old term vocabulary is copied verbatim once it passes bounded
    JSON validation, so adding this private map never normalizes unrelated legacy
    rules.  All consumed scalar values use catalog-style exact-decimal strings.
    """
    if not isinstance(value, dict):
        raise EvaluationPolicyError("Legacy challenge terms are invalid")
    _json_bytes(value, maximum=_MAX_HISTORY_ENTRY_BYTES)
    required = {"profit_target", "max_daily_loss", "max_total_loss", "profit_split", "profit_split_percentage", "rules"}
    if not required.issubset(value) or not isinstance(value.get("rules"), dict):
        raise EvaluationPolicyError("Legacy challenge terms are incomplete")
    for field in required - {"rules"}:
        _legacy_decimal(value.get(field), field)
    _json_bytes(value["rules"], maximum=_MAX_HISTORY_ENTRY_BYTES)
    return deepcopy(value)


def _validated_history_map(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, dict) or len(value) > _MAX_HISTORY_ENTRIES:
        raise EvaluationPolicyError("Legacy challenge history is invalid")
    _json_bytes(value)
    result: dict[str, dict[str, Any]] = {}
    for challenge_id, terms in value.items():
        if not isinstance(challenge_id, str) or not _ID_TEXT.fullmatch(challenge_id):
            raise EvaluationPolicyError("Legacy challenge history key is invalid")
        result[challenge_id] = _validated_legacy_terms(terms)
    return result


def public_program_rules(rules: Any) -> dict[str, Any]:
    """Return safe public rules, removing only the reserved private history map."""
    if not isinstance(rules, dict):
        raise EvaluationPolicyError("Program rules are invalid")
    copied = deepcopy(rules)
    _json_bytes(copied)
    if _PRIVATE_HISTORY_KEY in copied:
        _validated_history_map(copied[_PRIVATE_HISTORY_KEY])
        del copied[_PRIVATE_HISTORY_KEY]
    return copied


def legacy_challenge_terms(rules: Any, challenge_id: Any) -> LegacyTermsLookup:
    """Fetch a matching archived snapshot without ever falling back after failure."""
    if not isinstance(challenge_id, int) or isinstance(challenge_id, bool) or challenge_id <= 0:
        return LegacyTermsLookup(found=False, valid=False, terms=None)
    if not isinstance(rules, dict) or _PRIVATE_HISTORY_KEY not in rules:
        return LegacyTermsLookup(found=False, valid=False, terms=None)
    raw_history = rules.get(_PRIVATE_HISTORY_KEY)
    key = str(challenge_id)
    # Determine whether this challenge has an entry before validating it.  A
    # malformed matching record must not cause a fallback to newly edited rows.
    found = isinstance(raw_history, dict) and key in raw_history
    try:
        history = _validated_history_map(raw_history)
    except EvaluationPolicyError:
        return LegacyTermsLookup(found=found, valid=False, terms=None)
    if key not in history:
        return LegacyTermsLookup(found=False, valid=True, terms=None)
    return LegacyTermsLookup(found=True, valid=True, terms=history[key])


__all__ = [
    "EvaluationPolicyError",
    "LegacyTermsLookup",
    "build_evaluation_policy",
    "is_coming_soon_program_type",
    "legacy_challenge_terms",
    "public_program_rules",
    "validate_program_evaluation_policy",
]
