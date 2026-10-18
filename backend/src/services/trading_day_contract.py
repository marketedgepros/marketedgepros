"""Pure, local-calendar trading-day boundary calculation for Stage 5.

This module has no provider, payment, database, authorization, I/O, or wall-clock
integration.  It maps one caller-supplied UTC observation to the local reset-to-reset
window that contains it.  It does not count trading days or encode market policy.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


# A deliberate operational range prevents callers from relying on accidental,
# jurisdiction-specific historical time-zone data.  The adjacent boundary must also
# remain in this range, so edge observations whose active window crosses it are refused.
_MIN_SUPPORTED_YEAR = 1900
_MAX_SUPPORTED_YEAR = 2100


@dataclass(frozen=True, slots=True)
class TradingDayWindow:
    """The local reset-to-reset window containing a UTC observation.

    ``start_utc`` and ``end_utc`` are aware datetimes with ``datetime.timezone.utc``
    as their tzinfo.  ``trading_date`` is the calendar date on which this window's
    local reset occurred; it is not a counted or provider-authorized trading day.
    """

    trading_date: date
    start_utc: datetime
    end_utc: datetime


def _require_utc_observation(observed_at: object) -> datetime:
    """Accept only an exact UTC ``datetime`` with an unambiguous fold."""
    if type(observed_at) is not datetime:
        raise TypeError("observed_at must be an exact datetime")
    if observed_at.tzinfo is None:
        raise ValueError("observed_at must be aware UTC")
    if observed_at.fold != 0:
        raise ValueError("observed_at must have fold=0")

    # Offset zero alone is not enough: a seasonal/local zone can happen to have a
    # zero offset at this instant.  Accept the standard UTC singleton and the explicit
    # ZoneInfo('UTC') form, but no arbitrary zero-offset tzinfo implementation.
    tzinfo = observed_at.tzinfo
    if tzinfo is not timezone.utc and not (
        type(tzinfo) is ZoneInfo and tzinfo.key == "UTC"
    ):
        raise ValueError("observed_at must use UTC tzinfo")
    if observed_at.utcoffset() != timedelta(0):
        raise ValueError("observed_at must have UTC offset zero")
    return observed_at


def _require_timezone_name(timezone_name: object) -> ZoneInfo:
    if type(timezone_name) is not str:
        raise TypeError("timezone_name must be an exact str")
    if not timezone_name or len(timezone_name) > 64:
        raise ValueError("timezone_name must be a non-empty IANA name of at most 64 characters")
    try:
        return ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as error:
        raise ValueError("timezone_name must name a valid IANA time zone") from error


def _require_reset_value(value: object, name: str, maximum: int) -> int:
    if type(value) is not int:
        raise TypeError(f"{name} must be an exact int")
    if value < 0 or value > maximum:
        raise ValueError(f"{name} is outside its permitted range")
    return value


def _require_supported_date(local_day: date) -> None:
    if local_day.year < _MIN_SUPPORTED_YEAR or local_day.year > _MAX_SUPPORTED_YEAR:
        raise ValueError("local calendar date is outside the supported 1900..2100 range")


def _reset_boundary_utc(
    local_day: date,
    local_timezone: ZoneInfo,
    reset_hour: int,
    reset_minute: int,
    reset_fold: int,
) -> datetime:
    """Return one valid local reset boundary as a ``timezone.utc`` datetime.

    UTC round-tripping is the validation step.  A nonexistent spring-forward wall
    time returns a different local clock reading and is refused instead of shifted.
    For an unambiguous wall time, ``reset_fold=1`` round-trips with fold 0; that is
    accepted because both folds denote the same instant.  For an ambiguous wall
    time, the caller-selected fold determines which UTC instant is returned.
    """
    _require_supported_date(local_day)
    local_boundary = datetime(
        local_day.year,
        local_day.month,
        local_day.day,
        reset_hour,
        reset_minute,
        tzinfo=local_timezone,
        fold=reset_fold,
    )
    boundary_utc = local_boundary.astimezone(timezone.utc)
    round_tripped = boundary_utc.astimezone(local_timezone)
    if (
        round_tripped.year,
        round_tripped.month,
        round_tripped.day,
        round_tripped.hour,
        round_tripped.minute,
        round_tripped.second,
        round_tripped.microsecond,
    ) != (
        local_day.year,
        local_day.month,
        local_day.day,
        reset_hour,
        reset_minute,
        0,
        0,
    ):
        raise ValueError("local reset time does not exist on this calendar date")
    return boundary_utc


def _whole_date_was_skipped(local_day: date, local_timezone: ZoneInfo) -> bool:
    """Prove a full 24-hour midnight date-line jump, not an ordinary DST gap."""
    midnight = datetime(local_day.year, local_day.month, local_day.day)
    first = midnight.replace(tzinfo=local_timezone, fold=0)
    second = midnight.replace(tzinfo=local_timezone, fold=1)
    first_back = first.astimezone(timezone.utc).astimezone(local_timezone).replace(tzinfo=None)
    second_back = second.astimezone(timezone.utc).astimezone(local_timezone).replace(tzinfo=None)
    return (
        second.utcoffset() - first.utcoffset() == timedelta(days=1)
        and first_back == midnight + timedelta(days=1)
        and second_back == midnight - timedelta(days=1)
    )


def _adjacent_reset_utc(local_day, direction, local_timezone, hour, minute, fold):
    """Inspect at most two adjacent labels; skip only a proven nonexistent date."""
    adjacent = local_day + timedelta(days=direction)
    try:
        return _reset_boundary_utc(adjacent, local_timezone, hour, minute, fold)
    except ValueError:
        if not _whole_date_was_skipped(adjacent, local_timezone):
            raise
        return _reset_boundary_utc(local_day + timedelta(days=2 * direction),
                                   local_timezone, hour, minute, fold)


def trading_day_window(
    observed_at: datetime,
    timezone_name: str,
    reset_hour: int,
    reset_minute: int,
    reset_fold: int,
) -> TradingDayWindow:
    """Return the local reset-to-reset window containing ``observed_at``.

    All five parameters are required.  ``observed_at`` must be an exact, aware UTC
    datetime (``timezone.utc`` or ``ZoneInfo('UTC')``), with offset zero and fold 0.
    ``timezone_name`` is an exact, non-empty IANA string at most 64 characters.
    Reset components are exact integers: hour 0..23, minute 0..59, and fold 0 or 1.

    Only local-calendar calculations occur.  An exact reset instant begins the new
    window.  A nonexistent reset in a boundary needed by the window raises
    ``ValueError``; it is never silently moved. A proven full skipped date is not
    a trading-day label; at most two adjacent date labels are inspected to find
    the neighboring existing reset. The calculation never polls the system clock.
    """
    utc_observation = _require_utc_observation(observed_at)
    local_timezone = _require_timezone_name(timezone_name)
    hour = _require_reset_value(reset_hour, "reset_hour", 23)
    minute = _require_reset_value(reset_minute, "reset_minute", 59)
    fold = _require_reset_value(reset_fold, "reset_fold", 1)

    local_observation = utc_observation.astimezone(local_timezone)
    current_day = local_observation.date()
    _require_supported_date(current_day)

    current_start = _reset_boundary_utc(
        current_day, local_timezone, hour, minute, fold
    )

    if utc_observation >= current_start:
        next_start = _adjacent_reset_utc(current_day, 1, local_timezone, hour, minute, fold)
        return TradingDayWindow(
            trading_date=current_day,
            start_utc=current_start,
            end_utc=next_start,
        )

    previous_start = _adjacent_reset_utc(current_day, -1, local_timezone, hour, minute, fold)
    return TradingDayWindow(
        trading_date=previous_start.astimezone(local_timezone).date(),
        start_utc=previous_start,
        end_utc=current_start,
    )


__all__ = ("TradingDayWindow", "trading_day_window")
