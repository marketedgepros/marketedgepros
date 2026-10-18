"""Deterministic local risk calculations; no provider trust, persistence or actions."""
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from fractions import Fraction

from src.services.trading_day_contract import trading_day_window
from src.services.trading_risk_contract import (
    MAX_UNITS, TradingRules, exact_int, exact_text, fraction_dict, utc_datetime,
)


@dataclass(frozen=True)
class RiskState:
    tenant_id: int
    challenge_id: int
    provider_id: str
    account_id: str
    rules_digest: str
    sequence: int
    last_event_id: str
    last_observed_at: datetime
    day_start_utc: datetime
    day_end_utc: datetime
    opening_balance_units: int
    opening_equity_units: int
    peak_units: int
    daily_breach_latched: bool
    total_breach_latched: bool

    def __post_init__(self):
        exact_int(self.tenant_id, 1, 2 ** 31 - 1, 'tenant')
        exact_int(self.challenge_id, 1, 2 ** 31 - 1, 'challenge')
        exact_text(self.provider_id, r'[A-Za-z0-9_.:-]+', 64, 'provider identity')
        exact_text(self.account_id, r'[A-Za-z0-9_.:-]+', 64, 'account identity')
        exact_text(self.rules_digest, r'[a-f0-9]{64}', 64, 'rules digest')
        exact_int(self.sequence, 0, 2 ** 63 - 1, 'sequence')
        exact_text(self.last_event_id, r'[A-Za-z0-9_.:-]+', 128, 'last event')
        for value in (self.last_observed_at, self.day_start_utc, self.day_end_utc):
            utc_datetime(value)
        if not self.day_start_utc <= self.last_observed_at < self.day_end_utc:
            raise ValueError('State observation must lie in its day window')
        exact_int(self.opening_balance_units, 1, MAX_UNITS, 'opening balance')
        exact_int(self.opening_equity_units, 1, MAX_UNITS, 'opening equity')
        exact_int(self.peak_units, 1, MAX_UNITS, 'observed peak')
        if type(self.daily_breach_latched) is not bool or type(self.total_breach_latched) is not bool:
            raise ValueError('Explicit local latch states required')


@dataclass(frozen=True)
class RiskObservation:
    tenant_id: int
    challenge_id: int
    provider_id: str
    account_id: str
    rules_digest: str
    event_id: str
    sequence: int
    observed_at: datetime
    currency: str
    currency_scale: int
    balance_units: int
    equity_units: int
    equity_includes_fees_and_swaps: bool

    def __post_init__(self):
        exact_int(self.tenant_id, 1, 2 ** 31 - 1, 'tenant')
        exact_int(self.challenge_id, 1, 2 ** 31 - 1, 'challenge')
        exact_text(self.provider_id, r'[A-Za-z0-9_.:-]+', 64, 'provider identity')
        exact_text(self.account_id, r'[A-Za-z0-9_.:-]+', 64, 'account identity')
        exact_text(self.rules_digest, r'[a-f0-9]{64}', 64, 'rules digest')
        exact_text(self.event_id, r'[A-Za-z0-9_.:-]+', 128, 'event')
        exact_int(self.sequence, 1, 2 ** 63 - 1, 'sequence')
        utc_datetime(self.observed_at)
        exact_text(self.currency, r'[A-Z][A-Z0-9]*', 12, 'currency')
        exact_int(self.currency_scale, 0, 8, 'currency scale')
        exact_int(self.balance_units, -MAX_UNITS, MAX_UNITS, 'balance')
        exact_int(self.equity_units, -MAX_UNITS, MAX_UNITS, 'equity')
        if type(self.equity_includes_fees_and_swaps) is not bool:
            raise ValueError('Explicit equity cost semantics required')


def _result(status, reasons, **diagnostics):
    return {
        'status': status, 'reasons': reasons, 'diagnostics': diagnostics,
        'provider_verified': False, 'authorized': False, 'persisted': False,
        'phase_transition_authorized': False, 'account_disable_authorized': False,
    }


def evaluate_risk(rules, state, observation, *, as_of):
    """One bounded event, explicit prior state; never derive trust from input IDs.

    Returns (local diagnostic, immutable next state). Unknown preserves the exact
    input state. Opening day values and observed peak are explicit prerequisites,
    not reconstructed from current balance or a truncated trade history.
    """
    if type(rules) is not TradingRules:
        raise ValueError('TradingRules required')
    utc_datetime(as_of)
    if state is None or observation is None:
        return _result('unknown', ['missing_state_or_observation']), state
    if type(state) is not RiskState or type(observation) is not RiskObservation:
        raise ValueError('Typed local state and observation required')
    # Revalidate immutable objects to reject mutated/nonnative values before math.
    rules.__post_init__()
    state.__post_init__()
    observation.__post_init__()
    if state.rules_digest != rules.digest or observation.rules_digest != rules.digest:
        return _result('unknown', ['rules_version_mismatch']), state
    identity = ('tenant_id', 'challenge_id', 'provider_id', 'account_id')
    if any(getattr(state, key) != getattr(observation, key) for key in identity):
        return _result('unknown', ['identity_mismatch']), state
    if observation.currency != rules.currency or observation.currency_scale != rules.currency_scale:
        return _result('unknown', ['currency_or_scale_mismatch']), state
    if not observation.equity_includes_fees_and_swaps:
        return _result('unknown', ['equity_cost_semantics_missing']), state
    if observation.sequence != state.sequence + 1 or observation.event_id == state.last_event_id:
        return _result('unknown', ['duplicate_or_sequence_gap']), state
    if observation.observed_at < state.last_observed_at:
        return _result('unknown', ['out_of_order_timestamp']), state
    age = as_of - observation.observed_at
    if age < timedelta(0) or age > timedelta(seconds=rules.maximum_age_seconds):
        return _result('unknown', ['future_or_stale_observation']), state
    try:
        window = trading_day_window(observation.observed_at, rules.timezone_name,
                                    rules.reset_hour, rules.reset_minute, rules.reset_fold)
    except ValueError:
        return _result('unknown', ['invalid_trading_day_window']), state
    if window.start_utc != state.day_start_utc or window.end_utc != state.day_end_utc:
        return _result('unknown', ['day_opening_reference_required']), state
    opening_total_basis = state.opening_balance_units if rules.total_basis == 'balance' else state.opening_equity_units
    if state.peak_units < max(rules.initial_units, opening_total_basis):
        return _result('unknown', ['invalid_peak_reference']), state

    target_value = observation.balance_units if rules.target_basis == 'balance' else observation.equity_units
    daily_value = observation.balance_units if rules.daily_basis == 'balance' else observation.equity_units
    total_value = observation.balance_units if rules.total_basis == 'balance' else observation.equity_units
    daily_reference = state.opening_balance_units if rules.daily_reference_basis == 'balance' else state.opening_equity_units
    peak = max(state.peak_units, total_value)
    target_amount = rules.profit_target.amount(rules.initial_units)
    daily_amount = rules.daily_loss.amount(daily_reference)
    total_amount = rules.total_loss.amount(rules.initial_units)
    daily_floor = Fraction(daily_reference) - daily_amount
    total_floor = Fraction(rules.initial_units if rules.total_drawdown_mode == 'static' else peak) - total_amount
    daily_breach = daily_value <= daily_floor if rules.loss_at_threshold_is_breach else daily_value < daily_floor
    total_breach = total_value <= total_floor if rules.loss_at_threshold_is_breach else total_value < total_floor
    profit = Fraction(target_value - rules.initial_units)
    target_met = profit >= target_amount if rules.target_at_threshold_is_met else profit > target_amount
    daily_latched = state.daily_breach_latched or daily_breach
    total_latched = state.total_breach_latched or total_breach
    # Violations take precedence even when profit target is reached at this event.
    status = 'local_breach' if daily_latched or total_latched else 'local_target_met' if target_met else 'local_within_limits'
    next_state = replace(state, sequence=observation.sequence, last_event_id=observation.event_id,
                         last_observed_at=observation.observed_at, peak_units=peak,
                         daily_breach_latched=daily_latched, total_breach_latched=total_latched)
    return _result(status, [], rules_digest=rules.digest, event_id=observation.event_id,
                   daily_floor=fraction_dict(daily_floor), total_floor=fraction_dict(total_floor),
                   target_amount=fraction_dict(target_amount), target_profit=fraction_dict(profit),
                   daily_breach_at_event=daily_breach, total_breach_at_event=total_breach,
                   daily_breach_latched=daily_latched, total_breach_latched=total_latched,
                   target_met=target_met, peak_units=peak, trading_date=window.trading_date.isoformat()), next_state
