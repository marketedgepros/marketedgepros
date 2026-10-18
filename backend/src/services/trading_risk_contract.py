"""Pure draft rule contract; not approved rules, trading evidence or entitlement."""
from dataclasses import dataclass, fields
from datetime import datetime, timedelta, timezone
from fractions import Fraction
import hashlib
import json
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_UNITS = 10 ** 15


def exact_int(value, minimum, maximum, label):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('Invalid ' + label)
    return value


def exact_text(value, pattern, maximum, label):
    if type(value) is not str or not 1 <= len(value) <= maximum or re.fullmatch(pattern, value) is None:
        raise ValueError('Invalid ' + label)
    return value


def utc_datetime(value):
    if type(value) is not datetime or value.tzinfo is None or value.fold != 0:
        raise ValueError('UTC datetime required')
    if value.tzinfo is not timezone.utc and not (type(value.tzinfo) is ZoneInfo and value.tzinfo.key == 'UTC'):
        raise ValueError('Explicit UTC timezone required')
    offset = value.utcoffset()
    if offset != timedelta(0) or not 1900 <= value.year <= 2100:
        raise ValueError('UTC datetime required')
    return value


@dataclass(frozen=True)
class RiskLimit:
    """units = exact currency minor units; bps = basis points of named reference."""
    unit: str
    value: int

    def __post_init__(self):
        if type(self.unit) is not str or self.unit not in {'units', 'bps'}:
            raise ValueError('Limit unit must be explicit units or bps')
        exact_int(self.value, 1, 10000 if self.unit == 'bps' else MAX_UNITS, 'limit')

    def amount(self, reference_units):
        self.__post_init__()
        exact_int(reference_units, 0, MAX_UNITS, 'limit reference')
        return Fraction(self.value) if self.unit == 'units' else Fraction(reference_units * self.value, 10000)


@dataclass(frozen=True)
class TradingRules:
    """Every policy field is explicit. Immutable in-process, not a DB approval."""
    schema_version: int
    rules_version: str
    program_id: int
    phase: int
    currency: str
    currency_scale: int
    initial_units: int
    profit_target: RiskLimit
    daily_loss: RiskLimit
    total_loss: RiskLimit
    target_basis: str
    daily_basis: str
    daily_reference_basis: str
    total_basis: str
    total_drawdown_mode: str
    loss_at_threshold_is_breach: bool
    target_at_threshold_is_met: bool
    timezone_name: str
    reset_hour: int
    reset_minute: int
    reset_fold: int
    maximum_age_seconds: int

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != 1:
            raise ValueError('Unsupported rules schema')
        exact_text(self.rules_version, r'[A-Za-z0-9][A-Za-z0-9_.-]*', 64, 'rules version')
        exact_int(self.program_id, 1, 2 ** 31 - 1, 'program')
        exact_int(self.phase, 1, 20, 'phase')
        exact_text(self.currency, r'[A-Z][A-Z0-9]*', 12, 'currency')
        exact_int(self.currency_scale, 0, 8, 'currency scale')
        exact_int(self.initial_units, 1, MAX_UNITS, 'initial amount')
        for limit in (self.profit_target, self.daily_loss, self.total_loss):
            if type(limit) is not RiskLimit:
                raise ValueError('Explicit RiskLimit required')
            limit.__post_init__()
        for basis in (self.target_basis, self.daily_basis, self.daily_reference_basis, self.total_basis):
            if type(basis) is not str or basis not in {'balance', 'equity'}:
                raise ValueError('Explicit balance/equity basis required')
        if type(self.total_drawdown_mode) is not str or self.total_drawdown_mode not in {'static', 'trailing_observed'}:
            raise ValueError('Explicit supported drawdown mode required')
        if type(self.loss_at_threshold_is_breach) is not bool or type(self.target_at_threshold_is_met) is not bool:
            raise ValueError('Explicit equality policies required')
        exact_text(self.timezone_name, r'[A-Za-z0-9_+./-]+', 64, 'timezone')
        try:
            ZoneInfo(self.timezone_name)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError('Invalid IANA timezone') from error
        exact_int(self.reset_hour, 0, 23, 'reset hour')
        exact_int(self.reset_minute, 0, 59, 'reset minute')
        exact_int(self.reset_fold, 0, 1, 'reset fold')
        exact_int(self.maximum_age_seconds, 1, 86400, 'maximum evidence age')

    def canonical_dict(self):
        self.__post_init__()
        result = {}
        for field in fields(self):
            value = getattr(self, field.name)
            result[field.name] = {'unit': value.unit, 'value': value.value} if type(value) is RiskLimit else value
        return result

    @property
    def digest(self):
        raw = json.dumps(self.canonical_dict(), sort_keys=True, separators=(',', ':'), allow_nan=False)
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def fraction_dict(value):
    """Exact JSON projection; no float, Decimal context or implicit rounding."""
    if value is None:
        return None
    if type(value) is not Fraction:
        raise ValueError('Exact Fraction required')
    return {'numerator': str(value.numerator), 'denominator': str(value.denominator)}
