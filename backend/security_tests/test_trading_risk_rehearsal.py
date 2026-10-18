"""Pure, provider-neutral regressions for Stage 5b local risk rehearsal.

All IDs, values and rules here are synthetic test fixtures.  They prove local,
fail-closed arithmetic and sequencing only; they do not authorize trading,
providers, persistence, phase changes, account actions, or real business rules.
"""
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from fractions import Fraction
import ast
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from src.services import trading_risk_rehearsal as rehearsal
from src.services.trading_day_contract import trading_day_window
from src.services.trading_risk_contract import MAX_UNITS, RiskLimit, TradingRules
from src.services.trading_risk_rehearsal import RiskObservation, RiskState, evaluate_risk


UTC = timezone.utc
OBSERVED_AT = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
LOCAL_ONLY_FLAGS = (
    "provider_verified",
    "authorized",
    "persisted",
    "phase_transition_authorized",
    "account_disable_authorized",
)


class PoisonInt(int):
    """An int-shaped object must never be accepted as a minor-unit value."""


def make_rules(**changes):
    values = {
        "schema_version": 1,
        "rules_version": "TEST_RISK_REHEARSAL_1",
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


def make_state(rules, **changes):
    last_observed_at = changes.pop("last_observed_at", OBSERVED_AT - timedelta(seconds=1))
    window = trading_day_window(
        last_observed_at,
        rules.timezone_name,
        rules.reset_hour,
        rules.reset_minute,
        rules.reset_fold,
    )
    values = {
        "tenant_id": 101,
        "challenge_id": 202,
        "provider_id": "TEST_PROVIDER",
        "account_id": "TEST_ACCOUNT",
        "rules_digest": rules.digest,
        "sequence": 7,
        "last_event_id": "TEST_EVENT_7",
        "last_observed_at": last_observed_at,
        "day_start_utc": window.start_utc,
        "day_end_utc": window.end_utc,
        "opening_balance_units": rules.initial_units,
        "opening_equity_units": rules.initial_units,
        "peak_units": rules.initial_units,
        "daily_breach_latched": False,
        "total_breach_latched": False,
    }
    values.update(changes)
    return RiskState(**values)


def make_observation(rules, **changes):
    values = {
        "tenant_id": 101,
        "challenge_id": 202,
        "provider_id": "TEST_PROVIDER",
        "account_id": "TEST_ACCOUNT",
        "rules_digest": rules.digest,
        "event_id": "TEST_EVENT_8",
        "sequence": 8,
        "observed_at": OBSERVED_AT,
        "currency": rules.currency,
        "currency_scale": rules.currency_scale,
        "balance_units": rules.initial_units,
        "equity_units": rules.initial_units,
        "equity_includes_fees_and_swaps": True,
    }
    values.update(changes)
    return RiskObservation(**values)


def assert_local_only(result):
    assert {name: result[name] for name in LOCAL_ONLY_FLAGS} == {
        "provider_verified": False,
        "authorized": False,
        "persisted": False,
        "phase_transition_authorized": False,
        "account_disable_authorized": False,
    }


def assert_unknown_preserves(state, result, next_state, reason):
    assert result["status"] == "unknown"
    assert result["reasons"] == [reason]
    assert result["diagnostics"] == {}
    assert next_state is state
    assert_local_only(result)


def test_valid_matched_synthetic_event_is_local_only_and_updates_explicit_state():
    rules = make_rules()
    state = make_state(rules)
    observation = make_observation(rules)

    result, next_state = evaluate_risk(rules, state, observation, as_of=observation.observed_at)

    assert result["status"] == "local_within_limits"
    assert result["reasons"] == []
    assert result["diagnostics"]["event_id"] == "TEST_EVENT_8"
    assert result["diagnostics"]["rules_digest"] == rules.digest
    assert next_state is not state
    assert next_state.sequence == 8
    assert next_state.last_event_id == "TEST_EVENT_8"
    assert next_state.last_observed_at == OBSERVED_AT
    assert next_state.day_start_utc == state.day_start_utc
    assert next_state.day_end_utc == state.day_end_utc
    assert_local_only(result)


@pytest.mark.parametrize(
    ("state_factory", "observation_factory", "reason"),
    [
        (lambda rules: None, lambda rules: make_observation(rules), "missing_state_or_observation"),
        (lambda rules: make_state(rules), lambda rules: None, "missing_state_or_observation"),
        (lambda rules: None, lambda rules: None, "missing_state_or_observation"),
    ],
    ids=["missing-state", "missing-observation", "both-missing"],
)
def test_absent_evidence_is_unknown_not_default_pass_or_breach(state_factory, observation_factory, reason):
    rules = make_rules()
    state = state_factory(rules)
    observation = observation_factory(rules)
    result, next_state = evaluate_risk(rules, state, observation, as_of=OBSERVED_AT)
    assert_unknown_preserves(state, result, next_state, reason)


@pytest.mark.parametrize(
    ("loss_is_breach", "balance", "expected"),
    [
        (True, 9_000, "local_breach"),
        (False, 9_000, "local_within_limits"),
        (True, 9_001, "local_within_limits"),
        (False, 8_999, "local_breach"),
    ],
    ids=["inclusive-at-floor", "strict-at-floor", "inclusive-above-floor", "strict-below-floor"],
)
def test_daily_loss_threshold_comparison_is_explicit(loss_is_breach, balance, expected):
    rules = make_rules(
        daily_loss=RiskLimit("units", 1_000),
        total_loss=RiskLimit("units", 10_000),
        profit_target=RiskLimit("units", 100_000),
        loss_at_threshold_is_breach=loss_is_breach,
    )
    state = make_state(rules, opening_balance_units=10_000)
    observation = make_observation(rules, balance_units=balance, equity_units=balance)

    result, _ = evaluate_risk(rules, state, observation, as_of=OBSERVED_AT)
    assert result["status"] == expected
    assert result["diagnostics"]["daily_floor"] == {"numerator": "9000", "denominator": "1"}
    assert result["diagnostics"]["daily_breach_at_event"] is (expected == "local_breach")
    assert_local_only(result)


@pytest.mark.parametrize(
    ("target_is_met", "expected"),
    [(True, "local_target_met"), (False, "local_within_limits")],
    ids=["inclusive-profit-target", "strict-profit-target"],
)
def test_profit_target_equality_comparison_is_explicit(target_is_met, expected):
    rules = make_rules(
        profit_target=RiskLimit("units", 1_000),
        daily_loss=RiskLimit("units", 10_000),
        total_loss=RiskLimit("units", 10_000),
        target_at_threshold_is_met=target_is_met,
    )
    state = make_state(rules)
    observation = make_observation(rules, balance_units=11_001, equity_units=11_001)

    result, _ = evaluate_risk(rules, state, observation, as_of=OBSERVED_AT)
    assert result["status"] == expected
    assert result["diagnostics"]["target_profit"] == {"numerator": "1000", "denominator": "1"}
    assert result["diagnostics"]["target_amount"] == {"numerator": "1000", "denominator": "1"}
    assert result["diagnostics"]["target_met"] is target_is_met


def test_risk_breach_precedes_target_when_balance_profit_and_negative_equity_both_signal():
    rules = make_rules(
        target_basis="balance",
        daily_basis="equity",
        daily_reference_basis="equity",
        total_basis="equity",
        profit_target=RiskLimit("units", 1_000),
        daily_loss=RiskLimit("units", 1_000),
        total_loss=RiskLimit("units", 1_000),
    )
    state = make_state(rules)
    observation = make_observation(rules, balance_units=11_001, equity_units=-1)

    result, _ = evaluate_risk(rules, state, observation, as_of=OBSERVED_AT)
    assert result["status"] == "local_breach"
    assert result["diagnostics"]["target_met"] is True
    assert result["diagnostics"]["daily_breach_at_event"] is True
    assert result["diagnostics"]["total_breach_at_event"] is True
    assert_local_only(result)


def test_static_and_trailing_use_initial_based_fractional_loss_with_explicit_observed_peak():
    common = {
        "profit_target": RiskLimit("units", 100_000),
        "daily_loss": RiskLimit("units", 10_000),
        "total_loss": RiskLimit("bps", 1),
    }
    static_rules = make_rules(total_drawdown_mode="static", **common)
    trailing_rules = make_rules(total_drawdown_mode="trailing_observed", **common)
    static_state = make_state(static_rules, peak_units=20_002)
    trailing_state = make_state(trailing_rules, peak_units=20_002)
    static_observation = make_observation(static_rules, balance_units=15_000, equity_units=15_000)
    trailing_observation = make_observation(trailing_rules, balance_units=15_000, equity_units=15_000)

    static_result, _ = evaluate_risk(static_rules, static_state, static_observation, as_of=OBSERVED_AT)
    trailing_result, _ = evaluate_risk(trailing_rules, trailing_state, trailing_observation, as_of=OBSERVED_AT)

    initial_loss = Fraction(10_001, 10_000)
    assert static_result["status"] == "local_within_limits"
    assert trailing_result["status"] == "local_breach"
    assert static_result["diagnostics"]["total_floor"] == {
        "numerator": str((Fraction(10_001) - initial_loss).numerator),
        "denominator": str((Fraction(10_001) - initial_loss).denominator),
    }
    assert trailing_result["diagnostics"]["total_floor"] == {
        "numerator": str((Fraction(20_002) - initial_loss).numerator),
        "denominator": str((Fraction(20_002) - initial_loss).denominator),
    }
    assert trailing_result["diagnostics"]["peak_units"] == 20_002


def test_cost_semantics_must_be_explicit_and_no_fee_or_swap_is_added_twice():
    rules = make_rules(daily_basis="equity", daily_reference_basis="equity")
    state = make_state(rules)
    included = make_observation(rules, balance_units=10_500, equity_units=9_500)
    missing = replace(included, equity_includes_fees_and_swaps=False)

    included_result, _ = evaluate_risk(rules, state, included, as_of=OBSERVED_AT)
    missing_result, missing_state = evaluate_risk(rules, state, missing, as_of=OBSERVED_AT)
    assert included_result["status"] == "local_within_limits"
    assert included_result["diagnostics"]["daily_floor"] == {"numerator": "9001", "denominator": "1"}
    assert_unknown_preserves(state, missing_result, missing_state, "equity_cost_semantics_missing")


def test_daily_breach_latch_is_cumulative_local_state_and_never_recovers_implicitly():
    rules = make_rules(profit_target=RiskLimit("units", 100_000))
    state = make_state(rules, daily_breach_latched=True)
    observation = make_observation(rules, balance_units=20_000, equity_units=20_000)

    result, next_state = evaluate_risk(rules, state, observation, as_of=OBSERVED_AT)
    assert result["status"] == "local_breach"
    assert result["diagnostics"]["daily_breach_at_event"] is False
    assert result["diagnostics"]["daily_breach_latched"] is True
    assert next_state.daily_breach_latched is True
    assert next_state.total_breach_latched is False


@pytest.mark.parametrize(
    ("observation_changes", "as_of", "reason"),
    [
        ({"event_id": "TEST_EVENT_7"}, OBSERVED_AT, "duplicate_or_sequence_gap"),
        ({"sequence": 9}, OBSERVED_AT, "duplicate_or_sequence_gap"),
        ({"observed_at": OBSERVED_AT - timedelta(seconds=2)}, OBSERVED_AT, "out_of_order_timestamp"),
        ({}, OBSERVED_AT - timedelta(microseconds=1), "future_or_stale_observation"),
        ({}, OBSERVED_AT + timedelta(seconds=61), "future_or_stale_observation"),
    ],
    ids=["next-sequence-same-event-id", "sequence-gap", "backward-time", "future-one-microsecond", "stale"],
)
def test_duplicate_gap_backwards_future_and_stale_evidence_are_unknown_unchanged(observation_changes, as_of, reason):
    rules = make_rules()
    state = make_state(rules)
    observation = make_observation(rules, **observation_changes)
    result, next_state = evaluate_risk(rules, state, observation, as_of=as_of)
    assert_unknown_preserves(state, result, next_state, reason)


def test_freshness_boundary_is_exact_to_the_microsecond_and_equal_timestamp_new_sequence_is_allowed():
    rules = make_rules(maximum_age_seconds=5)
    state = make_state(rules, last_observed_at=OBSERVED_AT)
    observation = make_observation(rules, event_id="TEST_EVENT_8_DIFFERENT")

    exact_result, exact_next = evaluate_risk(rules, state, observation, as_of=OBSERVED_AT + timedelta(seconds=5))
    over_result, over_next = evaluate_risk(rules, state, observation, as_of=OBSERVED_AT + timedelta(seconds=5, microseconds=1))
    assert exact_result["status"] == "local_within_limits"
    assert exact_next.sequence == 8
    assert_unknown_preserves(state, over_result, over_next, "future_or_stale_observation")


def test_new_calendar_day_is_unknown_until_a_new_explicit_opening_reference_is_supplied():
    rules = make_rules()
    state = make_state(rules)
    next_day = datetime(2026, 10, 12, 0, 0, tzinfo=UTC)
    observation = make_observation(rules, observed_at=next_day)

    result, next_state = evaluate_risk(rules, state, observation, as_of=next_day)
    assert_unknown_preserves(state, result, next_state, "day_opening_reference_required")


@pytest.mark.parametrize(
    ("rules_changes", "observation_changes", "reason"),
    [
        ({"phase": 4}, {}, "rules_version_mismatch"),
        ({"program_id": 702}, {}, "rules_version_mismatch"),
        ({}, {"currency_scale": 3}, "currency_or_scale_mismatch"),
        ({}, {"tenant_id": 999}, "identity_mismatch"),
    ],
    ids=["phase-digest", "program-digest", "same-currency-scale-mismatch", "matched-looking-ids-not-trusted"],
)
def test_rules_bindings_identity_and_currency_scale_mismatch_fail_closed(rules_changes, observation_changes, reason):
    original_rules = make_rules()
    state = make_state(original_rules)
    observation = make_observation(original_rules, **observation_changes)
    evaluated_rules = replace(original_rules, **rules_changes)

    result, next_state = evaluate_risk(evaluated_rules, state, observation, as_of=OBSERVED_AT)
    assert_unknown_preserves(state, result, next_state, reason)


def test_frozen_assignment_fails_and_deliberate_corruption_is_revalidated_before_math():
    rules = make_rules()
    state = make_state(rules)
    observation = make_observation(rules)
    with pytest.raises(FrozenInstanceError):
        state.opening_balance_units = 1
    with pytest.raises(FrozenInstanceError):
        observation.balance_units = 1

    object.__setattr__(state, "opening_balance_units", True)
    with pytest.raises(ValueError):
        evaluate_risk(rules, state, observation, as_of=OBSERVED_AT)

    state = make_state(rules)
    observation = make_observation(rules)
    object.__setattr__(observation, "balance_units", PoisonInt(10_001))
    with pytest.raises(ValueError):
        evaluate_risk(rules, state, observation, as_of=OBSERVED_AT)


def test_terminal_sequence_is_a_valid_state_but_has_no_representable_next_observation():
    rules = make_rules()
    penultimate = 2**63 - 2
    terminal = make_state(rules, sequence=penultimate, last_event_id="TEST_EVENT_PENULTIMATE")
    last_observation = make_observation(
        rules, sequence=2**63 - 1, event_id="TEST_EVENT_TERMINAL"
    )

    result, next_state = evaluate_risk(rules, terminal, last_observation, as_of=OBSERVED_AT)
    assert result["status"] == "local_within_limits"
    assert next_state.sequence == 2**63 - 1
    assert_local_only(result)
    with pytest.raises(ValueError):
        make_observation(rules, sequence=2**63, event_id="TEST_EVENT_UNREPRESENTABLE")


def test_peak_below_explicit_opening_total_basis_is_unknown_and_preserves_state():
    rules = make_rules(total_basis="equity")
    state = make_state(
        rules,
        opening_equity_units=rules.initial_units + 1,
        peak_units=rules.initial_units,
    )
    observation = make_observation(rules, balance_units=rules.initial_units, equity_units=rules.initial_units)

    result, next_state = evaluate_risk(rules, state, observation, as_of=OBSERVED_AT)
    assert_unknown_preserves(state, result, next_state, "invalid_peak_reference")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("observed_at", datetime(2026, 10, 11, 12, 0)),
        ("observed_at", datetime(2026, 10, 11, 12, 0, tzinfo=timezone(timedelta(0), "TEST_ZERO"))),
        ("observed_at", datetime(2026, 1, 1, 12, 0, tzinfo=ZoneInfo("Europe/London"))),
        ("observed_at", datetime(1899, 12, 31, tzinfo=UTC)),
        ("balance_units", MAX_UNITS + 1),
        ("equity_units", None),
        ("sequence", True),
    ],
    ids=["naive-time", "arbitrary-zero-offset", "seasonal-zero-offset", "out-of-year", "balance-over-cap", "equity-null", "sequence-bool"],
)
def test_observation_requires_complete_exact_utc_and_bounded_values(field, value):
    rules = make_rules()
    with pytest.raises(ValueError):
        make_observation(rules, **{field: value})


def test_partial_or_wrong_typed_state_and_observation_are_rejected_not_defaulted():
    rules = make_rules()
    with pytest.raises(TypeError):
        RiskState(101)  # No implicit state fields or opening values.
    with pytest.raises(TypeError):
        RiskObservation(101)  # No implicit evidence fields.
    with pytest.raises(ValueError):
        evaluate_risk(rules, "not-a-state", make_observation(rules), as_of=OBSERVED_AT)
    with pytest.raises(ValueError):
        evaluate_risk(rules, make_state(rules), "not-an-observation", as_of=OBSERVED_AT)


def test_small_exhaustive_fraction_oracle_has_no_rounding_or_hidden_peak_policy():
    """Independent small-range oracle for static/trailing, threshold equality and units."""
    for mode in ("static", "trailing_observed"):
        for inclusive in (False, True):
            for loss_units in (1, 2, 3):
                rules = make_rules(
                    profit_target=RiskLimit("units", 100_000),
                    daily_loss=RiskLimit("units", 10_000),
                    total_loss=RiskLimit("units", loss_units),
                    total_drawdown_mode=mode,
                    loss_at_threshold_is_breach=inclusive,
                )
                peak = 15_000
                state = make_state(rules, peak_units=peak)
                floor = Fraction(rules.initial_units if mode == "static" else peak) - Fraction(loss_units)
                for balance in range(9_995, 10_006):
                    observation = make_observation(rules, balance_units=balance, equity_units=balance)
                    result, next_state = evaluate_risk(rules, state, observation, as_of=OBSERVED_AT)
                    expected_breach = Fraction(balance) <= floor if inclusive else Fraction(balance) < floor
                    assert result["status"] == ("local_breach" if expected_breach else "local_within_limits")
                    assert result["diagnostics"]["total_floor"] == {
                        "numerator": str(floor.numerator), "denominator": str(floor.denominator)
                    }
                    assert next_state.peak_units == peak
                    assert_local_only(result)


def test_rehearsal_source_is_pure_local_math_without_routes_database_or_provider_clients():
    source = Path(rehearsal.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])
    assert imported_roots <= {"dataclasses", "datetime", "fractions", "src"}
    assert "Decimal" not in source and "float(" not in source
    forbidden_names = {"Flask", "sqlalchemy", "db", "requests", "socket", "create_app"}
    assert not any(isinstance(node, ast.Name) and node.id in forbidden_names for node in ast.walk(tree))
