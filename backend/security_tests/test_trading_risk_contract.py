"""Pure, synthetic regressions for the Stage 5b local risk rule contract.

These fixtures are deliberately fictitious and do not represent MarketEdgePros,
provider, programme, entitlement, or trading policy.
"""
from dataclasses import MISSING, FrozenInstanceError, fields, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
import ast
import hashlib
import inspect
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.services import trading_risk_contract as contract
from src.services.trading_risk_contract import (
    MAX_UNITS,
    RiskLimit,
    TradingRules,
    exact_int,
    fraction_dict,
    utc_datetime,
)


UTC = timezone.utc
FIXTURE_AT = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


class PoisonInt(int):
    """An int-shaped value must not cross exact-type validation."""


class PoisonStr(str):
    """A str-shaped value must not cross exact-type validation."""


def make_rules(**changes):
    """A complete synthetic fixture; every rules field is explicit."""
    values = {
        "schema_version": 1,
        "rules_version": "TEST_RULESET_2026_10",
        "program_id": 701,
        "phase": 3,
        "currency": "TST",
        "currency_scale": 2,
        "initial_units": 10_001,
        "profit_target": RiskLimit("units", 1_000),
        "daily_loss": RiskLimit("units", 1_000),
        "total_loss": RiskLimit("units", 2_000),
        "target_basis": "balance",
        "daily_basis": "balance",
        "daily_reference_basis": "balance",
        "total_basis": "balance",
        "total_drawdown_mode": "static",
        "loss_at_threshold_is_breach": True,
        "target_at_threshold_is_met": True,
        "timezone_name": "UTC",
        "reset_hour": 0,
        "reset_minute": 0,
        "reset_fold": 0,
        "maximum_age_seconds": 60,
    }
    values.update(changes)
    return TradingRules(**values)


def independent_digest(canonical):
    """Independent public encoding oracle, deliberately not contract internals."""
    raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def test_rules_have_no_defaults_and_digest_is_canonical_and_deterministic():
    rules = make_rules()

    assert all(field.default is MISSING and field.default_factory is MISSING for field in fields(TradingRules))
    assert inspect.signature(TradingRules)  # Construction is intentionally field-complete.
    canonical = rules.canonical_dict()
    assert set(canonical) == {field.name for field in fields(TradingRules)}
    assert canonical["daily_loss"] == {"unit": "units", "value": 1_000}
    assert rules.digest == independent_digest(canonical)
    assert make_rules().digest == rules.digest
    assert len(rules.digest) == 64


def test_digest_changes_for_each_permitted_policy_field_including_phase_and_day_controls():
    rules = make_rules()
    changes = {
        "rules_version": "TEST_RULESET_2026_11",
        "program_id": 702,
        "phase": 4,
        "currency": "TSU",
        "currency_scale": 3,
        "initial_units": 10_002,
        "profit_target": RiskLimit("bps", 1),
        "daily_loss": RiskLimit("bps", 2),
        "total_loss": RiskLimit("units", 2_001),
        "target_basis": "equity",
        "daily_basis": "equity",
        "daily_reference_basis": "equity",
        "total_basis": "equity",
        "total_drawdown_mode": "trailing_observed",
        "loss_at_threshold_is_breach": False,
        "target_at_threshold_is_met": False,
        "timezone_name": "Etc/UTC",
        "reset_hour": 1,
        "reset_minute": 1,
        "reset_fold": 1,
        "maximum_age_seconds": 5,
    }

    assert rules.canonical_dict()["schema_version"] == 1
    for name, value in changes.items():
        changed = replace(rules, **{name: value})
        assert changed.digest != rules.digest, name
        assert changed.digest == independent_digest(changed.canonical_dict()), name


@pytest.mark.parametrize(
    ("unit", "value"),
    [
        ("percent", 1),
        ("units", 0),
        ("bps", 10_001),
        ("units", MAX_UNITS + 1),
        ("units", True),
        ("units", 1.0),
        ("units", "1"),
        ("units", PoisonInt(1)),
        (PoisonStr("units"), 1),
        ("bps", None),
    ],
    ids=["unsupported-unit", "zero", "bps-over-cap", "units-over-cap", "bool", "float", "text", "int-subclass", "str-subclass", "null"],
)
def test_risk_limit_requires_explicit_bounded_exact_types(unit, value):
    with pytest.raises(ValueError):
        RiskLimit(unit, value)


def test_risk_limit_uses_fraction_without_rounding_at_an_awkward_basis_point_boundary():
    bps = RiskLimit("bps", 1)
    amount = bps.amount(10_001)

    assert type(amount) is Fraction
    assert amount == Fraction(10_001, 10_000)
    assert RiskLimit("units", MAX_UNITS).amount(MAX_UNITS) == Fraction(MAX_UNITS)
    for invalid_reference in (True, 1.0, "10001", PoisonInt(10_001), None, MAX_UNITS + 1):
        with pytest.raises(ValueError):
            bps.amount(invalid_reference)


@pytest.mark.parametrize(
    ("changes", "label"),
    [
        ({"schema_version": 2}, "unknown-schema"),
        ({"total_drawdown_mode": "trailing"}, "unsupported-drawdown-mode"),
        ({"target_basis": "mark_price"}, "unsupported-target-basis"),
        ({"daily_basis": ""}, "empty-daily-basis"),
        ({"loss_at_threshold_is_breach": 1}, "truthy-int-is-not-bool"),
        ({"currency": PoisonStr("TST")}, "currency-subclass"),
        ({"currency_scale": False}, "scale-bool"),
        ({"maximum_age_seconds": 0}, "no-freshness-default"),
        ({"timezone_name": "Not/A_Zone"}, "unknown-iana-zone"),
    ],
)
def test_rules_reject_unknown_modes_and_nonexact_required_policy_values(changes, label):
    with pytest.raises(ValueError):
        make_rules(**changes)


def test_nested_risk_limit_is_revalidated_after_intentional_frozen_bypass():
    """Frozen dataclasses are not a trust boundary against object.__setattr__."""
    rules = make_rules(daily_loss=RiskLimit("bps", 1))
    object.__setattr__(rules.daily_loss, "value", 10_001)

    # Parent construction must recursively validate the nested immutable contract.
    with pytest.raises(ValueError):
        rules.__post_init__()


def test_fraction_projection_accepts_fraction_only_and_never_imports_decimal_or_float_math():
    assert fraction_dict(Fraction(-10_001, 10_000)) == {"numerator": "-10001", "denominator": "10000"}
    for ambiguous in (1.5, Decimal("1.5")):
        with pytest.raises((TypeError, ValueError)):
            fraction_dict(ambiguous)


def test_utc_datetime_refuses_naive_non_utc_and_out_of_supported_range_values():
    for value in (
        datetime(2026, 10, 11, 12, 0),
        datetime(2026, 10, 11, 12, 0, tzinfo=timezone(timedelta(0), "TEST_ZERO")),
        datetime(2026, 1, 1, 12, 0, tzinfo=ZoneInfo("Europe/London")),
        datetime(2026, 10, 11, 12, 0, tzinfo=timezone(timedelta(hours=1))),
        datetime(1899, 12, 31, 23, 59, tzinfo=UTC),
        datetime(2101, 1, 1, tzinfo=UTC),
    ):
        with pytest.raises(ValueError):
            utc_datetime(value)
    assert utc_datetime(FIXTURE_AT) is FIXTURE_AT


def test_exact_integer_guard_refuses_bool_float_text_and_subclasses_at_the_boundary():
    for value in (True, 1.0, "1", PoisonInt(1), None, -1, 2):
        with pytest.raises(ValueError):
            exact_int(value, 0, 1, "TEST")
    assert exact_int(1, 0, 1, "TEST") == 1


def test_contract_source_stays_pure_local_fraction_math_without_routes_databases_or_providers():
    source = Path(contract.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])
    assert imported_roots <= {"dataclasses", "datetime", "fractions", "hashlib", "json", "re", "zoneinfo"}
    forbidden_names = {"Decimal", "float", "requests", "sqlalchemy", "db", "Flask", "socket"}
    assert not any(isinstance(node, ast.Name) and node.id in forbidden_names for node in ast.walk(tree))
