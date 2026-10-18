"""Focused contracts for the shared evaluation-family policy and legacy archive reads."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.models.trading_program import Challenge, TradingProgram
from src.services.program_catalog_service import CatalogValidationError, program_terms
from src.services.program_evaluation_policy import build_evaluation_policy
from src.services import program_evaluation_policy


def _assigned_program(*, program_type="two_phase", rules=None, **changes):
    policy = build_evaluation_policy(program_type)
    values = {
        "id": 3698,
        "name": "Synthetic assigned program",
        "type": program_type,
        "description": "Synthetic only",
        "payout_mode": "on_demand",
        "account_size": Decimal("10000.00"),
        "profit_target": Decimal(policy["phase_targets"][0]) if policy["phase_targets"] else Decimal("0.00"),
        "max_daily_loss": Decimal("5.00"),
        "max_total_loss": Decimal("10.00"),
        "price": Decimal("99.00"),
        "profit_split": Decimal("90.00"),
        "profit_split_percentage": Decimal("90.00"),
        "minimum_payout_amount": Decimal("50.00"),
        "rules": {"evaluation_policy": policy, "drawdown_type": "static", "unknown_legacy_rule": {"retained": [1, 2.5, None]}},
    }
    if rules is not None:
        values["rules"] = rules
    values.update(changes)
    return SimpleNamespace(**values)


def test_explicit_complete_assignment_uses_exact_canonical_policy_and_keeps_unknown_rules():
    program = _assigned_program()
    terms = program_terms(program)
    expected = build_evaluation_policy("two_phase")
    assert terms["rules"]["evaluation_policy"] == expected
    assert terms["rules"]["unknown_legacy_rule"] == {"retained": [1, 2.5, None]}
    assert expected["phases"] == 2
    assert expected["max_daily_loss"] == "5.00"
    assert expected["max_total_loss"] == "10.00"
    assert expected["drawdown_type"] == "static"
    assert expected["profit_split"] == "90.00" and expected["operator_share"] == "10.00"


@pytest.mark.parametrize("change", ["mismatch", "unknown_version", "missing_field", "float", "unsupported_type"])
def test_assigned_rows_fail_closed_for_nonexact_policy_or_scalars(change):
    program = _assigned_program()
    if change == "mismatch":
        program.rules["evaluation_policy"]["phase_targets"] = ["10.00", "5.00"]
    elif change == "unknown_version":
        program.rules["evaluation_policy"]["version"] = "mep-evaluation-families-v999"
    elif change == "missing_field":
        del program.rules["evaluation_policy"]["drawdown_type"]
    elif change == "float":
        program.profit_target = 8.0
    else:
        program.type = "unsupported_family"
    with pytest.raises(CatalogValidationError):
        program_terms(program)


@pytest.mark.parametrize("drawdown_type", [None, "static ", "trailing"])
def test_assigned_rows_fail_closed_when_raw_drawdown_type_is_not_static(drawdown_type):
    program = _assigned_program()
    if drawdown_type is None:
        del program.rules["drawdown_type"]
    else:
        program.rules["drawdown_type"] = drawdown_type
    with pytest.raises(CatalogValidationError):
        program_terms(program)


def test_canonical_source_rejects_unrecognized_version(tmp_path, monkeypatch):
    source = program_evaluation_policy._POLICY_PATH.read_text(encoding="utf-8")
    wrong_version = source.replace('"version": "mep-evaluation-families-v1"', '"version": "mep-evaluation-families-v999"')
    assert wrong_version != source
    path = tmp_path / "wrong-version.json"
    path.write_text(wrong_version, encoding="utf-8")
    monkeypatch.setattr(program_evaluation_policy, "_POLICY_PATH", path)
    with pytest.raises(program_evaluation_policy.EvaluationPolicyError):
        build_evaluation_policy("one_phase")


def test_private_history_is_never_serialized_and_matching_archive_stabilizes_legacy_calculations():
    archived = {
        "profit_target": "5.00",
        "max_daily_loss": "2.00",
        "max_total_loss": "3.00",
        "profit_split": "80.00",
        "profit_split_percentage": "80.00",
        "rules": {"calculation_method": "fxify", "unknown_old_rule": 1.5},
        "name": "Original two phase offer",
        "type": "two_phase",
        "description": "Historical evaluation terms, not the new stage plan",
    }
    program = TradingProgram(
        id=3698,
        name="Current replacement terms",
        description="New plan with different phase targets and split",
        type="two_phase",
        account_size=Decimal("1000.00"),
        price=Decimal("99.00"),
        profit_target=Decimal("8.00"),
        max_daily_loss=Decimal("5.00"),
        max_total_loss=Decimal("10.00"),
        profit_split=Decimal("90.00"),
        profit_split_percentage=Decimal("90.00"),
        rules={
            "evaluation_policy": build_evaluation_policy("two_phase"),
            "drawdown_type": "static",
            "unknown_current_rule": {"kept": True},
            "_mep_legacy_challenge_terms": {"42": archived},
        },
    )
    challenge = Challenge(
        id=42,
        program=program,
        initial_balance=Decimal("1000.00"),
        current_balance=Decimal("1000.00"),
        total_profit=Decimal("50.00"),
        total_loss=Decimal("31.00"),
        daily_drawdown_history={},
    )

    public_terms = program_terms(program)
    assert "_mep_legacy_challenge_terms" not in public_terms["rules"]
    assert public_terms["rules"]["unknown_current_rule"] == {"kept": True}
    assert "_mep_legacy_challenge_terms" not in program.to_dict()["rules"]
    assert challenge.historical_program_term("profit_split") == "80.00"
    assert challenge.historical_program_read_fields()["profit_split"] == 80.0
    assert challenge.historical_program_read_fields()["max_total_loss"] == 3.0
    assert challenge.historical_program_read_fields()["name"] == archived["name"]
    assert challenge.historical_program_read_fields()["description"] == archived["description"]
    assert challenge.calculate_progress() == Decimal("100")
    assert challenge.get_calculation_method() == "fxify"
    assert challenge.is_max_loss_exceeded() is True
    daily = challenge.update_daily_drawdown(Decimal("1000.00"), current_equity=Decimal("1000.00"))
    assert daily["daily_limit"] == 20.0 and daily["threshold"] == 980.0


def test_matching_malformed_archive_never_falls_back_to_current_catalog_terms():
    policy = build_evaluation_policy("one_phase")
    program = TradingProgram(
        id=3690,
        name="Edited current program",
        type="one_phase",
        account_size=Decimal("1000.00"),
        price=Decimal("99.00"),
        profit_target=Decimal("10.00"),
        max_daily_loss=Decimal("5.00"),
        max_total_loss=Decimal("10.00"),
        profit_split=Decimal("90.00"),
        profit_split_percentage=Decimal("90.00"),
        rules={
            "evaluation_policy": policy,
            "drawdown_type": "static",
            "_mep_legacy_challenge_terms": {
                # Floats are not canonical archived scalar strings; the matching
                # entry must fail closed instead of using current 10%/10% terms.
                "42": {
                    "profit_target": 5.0,
                    "max_daily_loss": "2.00",
                    "max_total_loss": "3.00",
                    "profit_split": "80.00",
                    "profit_split_percentage": "80.00",
                    "rules": {},
                },
            },
        },
    )
    challenge = Challenge(
        id=42,
        program=program,
        initial_balance=Decimal("1000.00"),
        total_profit=Decimal("100.00"),
        total_loss=Decimal("110.00"),
    )
    with pytest.raises(CatalogValidationError):
        program_terms(program)
    assert challenge.calculate_progress() == 0
    assert challenge.is_max_loss_exceeded() is False
    assert challenge.get_calculation_method() == "ftmo"


@pytest.mark.parametrize("malformed_map", [None, []])
def test_malformed_entire_private_history_map_blocks_current_term_fallback(malformed_map):
    program = TradingProgram(
        id=3691,
        name="Edited current program",
        type="one_phase",
        account_size=Decimal("1000.00"),
        price=Decimal("99.00"),
        profit_target=Decimal("10.00"),
        max_daily_loss=Decimal("5.00"),
        max_total_loss=Decimal("10.00"),
        profit_split=Decimal("90.00"),
        profit_split_percentage=Decimal("90.00"),
        rules={"evaluation_policy": build_evaluation_policy("one_phase"), "drawdown_type": "static", "_mep_legacy_challenge_terms": malformed_map},
    )
    challenge = Challenge(id=42, program=program, initial_balance=Decimal("1000.00"), total_profit=Decimal("100.00"))
    with pytest.raises(CatalogValidationError):
        program_terms(program)
    assert challenge.historical_program_term("profit_target") is None
    assert challenge.historical_program_read_fields() == {
        "profit_target": None,
        "max_daily_loss": None,
        "max_total_loss": None,
        "profit_split": None,
        "profit_split_percentage": None,
        "rules": None,
        "name": None,
        "type": None,
        "description": None,
    }
    assert challenge.calculate_progress() == 0
