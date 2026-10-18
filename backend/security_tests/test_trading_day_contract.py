"""Security contract tests for pure local-calendar Stage 5 day windows.

Fixtures below are calendar examples only; they are not trading, provider, or market
rules.  The contract accepts a caller-supplied UTC timestamp and performs no I/O.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date, datetime, timedelta, timezone
import inspect
from zoneinfo import ZoneInfo

import pytest

from src.services.trading_day_contract import TradingDayWindow, trading_day_window


UTC = timezone.utc


def test_interface_requires_all_arguments_and_returns_a_frozen_utc_dataclass():
    parameters = tuple(inspect.signature(trading_day_window).parameters.values())
    assert [parameter.name for parameter in parameters] == [
        "observed_at",
        "timezone_name",
        "reset_hour",
        "reset_minute",
        "reset_fold",
    ]
    assert all(parameter.default is inspect.Parameter.empty for parameter in parameters)
    with pytest.raises(TypeError):
        trading_day_window(datetime(2026, 1, 1, tzinfo=UTC), "UTC", 0, 0)  # type: ignore[call-arg]

    window = trading_day_window(datetime(2026, 1, 1, 0, 0, tzinfo=UTC), "UTC", 0, 0, 0)
    assert isinstance(window, TradingDayWindow)
    assert window == TradingDayWindow(
        trading_date=date(2026, 1, 1),
        start_utc=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
        end_utc=datetime(2026, 1, 2, 0, 0, tzinfo=UTC),
    )
    assert window.start_utc.tzinfo is UTC
    assert window.end_utc.tzinfo is UTC
    with pytest.raises(FrozenInstanceError):
        window.trading_date = date(2026, 1, 2)  # type: ignore[misc]


def test_utc_reset_before_exact_and_after_choose_the_correct_window():
    before = trading_day_window(
        datetime(2026, 2, 1, 5, 59, 59, tzinfo=UTC), "UTC", 6, 0, 0
    )
    exact = trading_day_window(
        datetime(2026, 2, 1, 6, 0, 0, tzinfo=UTC), "UTC", 6, 0, 0
    )
    after = trading_day_window(
        datetime(2026, 2, 1, 6, 0, 1, tzinfo=UTC), "UTC", 6, 0, 0
    )

    assert (before.trading_date, before.start_utc, before.end_utc) == (
        date(2026, 1, 31),
        datetime(2026, 1, 31, 6, tzinfo=UTC),
        datetime(2026, 2, 1, 6, tzinfo=UTC),
    )
    assert (exact.trading_date, exact.start_utc, exact.end_utc) == (
        date(2026, 2, 1),
        datetime(2026, 2, 1, 6, tzinfo=UTC),
        datetime(2026, 2, 2, 6, tzinfo=UTC),
    )
    assert after == exact


def test_prague_spring_and_fall_resets_create_23_and_25_hour_windows():
    spring = trading_day_window(
        datetime(2026, 3, 29, 12, tzinfo=UTC), "Europe/Prague", 0, 0, 0
    )
    fall = trading_day_window(
        datetime(2026, 10, 25, 12, tzinfo=UTC), "Europe/Prague", 0, 0, 0
    )

    assert spring.trading_date == date(2026, 3, 29)
    assert spring.start_utc == datetime(2026, 3, 28, 23, tzinfo=UTC)
    assert spring.end_utc == datetime(2026, 3, 29, 22, tzinfo=UTC)
    assert spring.end_utc - spring.start_utc == timedelta(hours=23)
    assert fall.trading_date == date(2026, 10, 25)
    assert fall.start_utc == datetime(2026, 10, 24, 22, tzinfo=UTC)
    assert fall.end_utc == datetime(2026, 10, 25, 23, tzinfo=UTC)
    assert fall.end_utc - fall.start_utc == timedelta(hours=25)


def test_new_york_17_reset_assigns_a_date_that_is_not_a_utc_midnight_day():
    before = trading_day_window(
        datetime(2026, 1, 2, 21, 59, 59, tzinfo=UTC), "America/New_York", 17, 0, 0
    )
    exact = trading_day_window(
        datetime(2026, 1, 2, 22, 0, tzinfo=UTC), "America/New_York", 17, 0, 0
    )

    assert before.trading_date == date(2026, 1, 1)
    assert before.start_utc == datetime(2026, 1, 1, 22, tzinfo=UTC)
    assert before.end_utc == datetime(2026, 1, 2, 22, tzinfo=UTC)
    assert exact.trading_date == date(2026, 1, 2)
    assert exact.start_utc == datetime(2026, 1, 2, 22, tzinfo=UTC)
    assert exact.end_utc == datetime(2026, 1, 3, 22, tzinfo=UTC)


def test_fall_back_repeated_reset_uses_the_explicit_fold():
    observed = datetime(2026, 11, 1, 7, 0, tzinfo=UTC)
    first = trading_day_window(observed, "America/New_York", 1, 30, 0)
    second = trading_day_window(observed, "America/New_York", 1, 30, 1)

    assert first.trading_date == second.trading_date == date(2026, 11, 1)
    assert first.start_utc == datetime(2026, 11, 1, 5, 30, tzinfo=UTC)
    assert second.start_utc == datetime(2026, 11, 1, 6, 30, tzinfo=UTC)
    assert first.end_utc == second.end_utc == datetime(2026, 11, 2, 6, 30, tzinfo=UTC)
    assert first.end_utc - first.start_utc == timedelta(hours=25)
    assert second.end_utc - second.start_utc == timedelta(hours=24)


def test_fold_one_is_accepted_when_a_normal_reset_round_trips_with_fold_zero():
    window = trading_day_window(
        datetime(2026, 1, 2, 12, tzinfo=UTC), "America/New_York", 17, 0, 1
    )

    assert window == TradingDayWindow(
        trading_date=date(2026, 1, 1),
        start_utc=datetime(2026, 1, 1, 22, tzinfo=UTC),
        end_utc=datetime(2026, 1, 2, 22, tzinfo=UTC),
    )


def test_nonexistent_spring_reset_is_refused_not_silently_shifted():
    with pytest.raises(ValueError, match="does not exist"):
        trading_day_window(
            datetime(2026, 3, 8, 7, 0, tzinfo=UTC), "America/New_York", 2, 30, 0
        )


def test_observation_must_be_exact_unambiguous_semantic_utc():
    class DatetimeSubclass(datetime):
        pass

    invalid = (
        datetime(2026, 1, 1),
        datetime(2026, 1, 1, tzinfo=timezone(timedelta(0), name="not-utc")),
        datetime(2026, 1, 1, tzinfo=ZoneInfo("Europe/London")),
        datetime(2026, 1, 1, tzinfo=UTC, fold=1),
        DatetimeSubclass(2026, 1, 1, tzinfo=UTC),
    )
    for observed_at in invalid:
        with pytest.raises((TypeError, ValueError)):
            trading_day_window(observed_at, "UTC", 0, 0, 0)

    # A standard ZoneInfo UTC observation is accepted, but result tzinfo is the
    # canonical datetime.timezone.utc required by the public result contract.
    window = trading_day_window(datetime(2026, 1, 1, tzinfo=ZoneInfo("UTC")), "UTC", 0, 0, 0)
    assert window.start_utc.tzinfo is UTC


def test_time_zone_and_reset_validation_rejects_subclasses_bools_and_bad_values():
    class StringSubclass(str):
        pass

    class IntSubclass(int):
        pass

    observed = datetime(2026, 1, 1, tzinfo=UTC)
    for timezone_name in (True, StringSubclass("UTC"), "x" * 65, "Not/A_Zone"):
        with pytest.raises((TypeError, ValueError)):
            trading_day_window(observed, timezone_name, 0, 0, 0)
    for values in (
        (True, 0, 0),
        (IntSubclass(0), 0, 0),
        (-1, 0, 0),
        (24, 0, 0),
        (0, -1, 0),
        (0, 60, 0),
        (0, 0, True),
        (0, 0, IntSubclass(0)),
        (0, 0, -1),
        (0, 0, 2),
    ):
        with pytest.raises((TypeError, ValueError)):
            trading_day_window(observed, "UTC", *values)


def test_poisoned_arguments_are_rejected_by_exact_type_before_operations():
    class Poison:
        def __getattribute__(self, name):
            raise AssertionError(f"poisoned argument accessed: {name}")

    observed = datetime(2026, 1, 1, tzinfo=UTC)
    poisoned = Poison()
    for arguments in (
        (poisoned, "UTC", 0, 0, 0),
        (observed, poisoned, 0, 0, 0),
        (observed, "UTC", poisoned, 0, 0),
        (observed, "UTC", 0, poisoned, 0),
        (observed, "UTC", 0, 0, poisoned),
    ):
        with pytest.raises(TypeError):
            trading_day_window(*arguments)


def test_supported_date_range_is_explicit_and_does_not_guess_historical_windows():
    with pytest.raises(ValueError, match="1900..2100"):
        trading_day_window(datetime(1899, 12, 31, tzinfo=UTC), "UTC", 0, 0, 0)
    with pytest.raises(ValueError, match="1900..2100"):
        trading_day_window(datetime(2101, 1, 1, tzinfo=UTC), "UTC", 0, 0, 0)


@pytest.mark.parametrize('observed', [
    datetime(2011, 12, 30, 3, tzinfo=UTC),
    datetime(2011, 12, 30, 12, tzinfo=UTC),
    datetime(2011, 12, 31, 2, 59, 59, tzinfo=UTC),
])
def test_whole_skipped_apia_date_uses_next_existing_reset_without_polling(observed):
    window = trading_day_window(observed, 'Pacific/Apia', 17, 0, 0)
    assert window.trading_date == date(2011, 12, 29)
    assert window.start_utc == datetime(2011, 12, 30, 3, tzinfo=UTC)
    assert window.end_utc == datetime(2011, 12, 31, 3, tzinfo=UTC)
    assert window.start_utc <= observed < window.end_utc


def test_next_day_normal_dst_gap_is_not_skipped_as_an_entire_date():
    with pytest.raises(ValueError, match='does not exist'):
        trading_day_window(datetime(2026, 3, 7, 12, tzinfo=UTC),
                           'America/New_York', 2, 30, 0)
