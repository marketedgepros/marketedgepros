"""Contract tests for the pure, non-authorizing legacy balance diagnostic.

These tests use only compact caller-supplied rows.  They neither create a wallet nor
claim that legacy arithmetic or a reference authenticates a provider event.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal, localcontext

import pytest

from src.services.balance_reconciliation import (
    ReconciliationInputError,
    aggregate_summary,
    exact_minor,
    reconcile_snapshot,
)


AT_1 = datetime(2026, 1, 1, 12, 0, 0)
AT_2 = datetime(2026, 1, 1, 12, 1, 0)


def _users(*identifiers):
    return [{"id": identifier} for identifier in identifiers]


def _wallet(identifier=10, user_id=1, main="15.00", commission="0.00", bonus="0.00"):
    return {
        "id": identifier,
        "user_id": user_id,
        "main_balance": main,
        "commission_balance": commission,
        "bonus_balance": bonus,
    }


def _transaction(
    identifier=100,
    wallet_id=10,
    kind="deposit",
    amount="5.00",
    bucket="main",
    before="10.00",
    after="15.00",
    reference_type="legacy_import",
    reference_id=900,
    created_at=AT_1,
):
    return {
        "id": identifier,
        "wallet_id": wallet_id,
        "type": kind,
        "amount": amount,
        "balance_type": bucket,
        "balance_before": before,
        "balance_after": after,
        "reference_type": reference_type,
        "reference_id": reference_id,
        "created_at": created_at,
    }


def _report(users=None, wallets=None, transactions=None, **kwargs):
    return reconcile_snapshot(
        _users(1) if users is None else users,
        [_wallet()] if wallets is None else wallets,
        [_transaction()] if transactions is None else transactions,
        **kwargs,
    )


def _codes(report):
    return [item["code"] for item in report["issues"]]


def test_exact_minor_accepts_only_exact_numeric_12_2_values_and_rejects_lossy_forms():
    assert [exact_minor(value) for value in (0, -12, "12.34", Decimal("-0.01"))] == [0, -1200, 1234, -1]
    # Decimal's ambient context must not round a valid Numeric(12,2) input.
    with localcontext() as context:
        context.prec = 2
        assert exact_minor(Decimal("12345678.91")) == 1234567891
    forbidden = (
        True,
        1.0,
        float("nan"),
        float("inf"),
        Decimal("NaN"),
        Decimal("Infinity"),
        "1.001",
        "1e2",
        "10000000000.00",
    )
    for value in forbidden:
        with pytest.raises(ReconciliationInputError):
            exact_minor(value)


def test_row_budget_is_strictly_bounded_and_never_truncates_a_claimed_snapshot():
    for invalid in (0, 10001, True, 1.0):
        with pytest.raises(ReconciliationInputError):
            _report(max_rows=invalid)
    with pytest.raises(ReconciliationInputError, match="row limit"):
        _report(users=_users(1, 2), max_rows=1)
    with pytest.raises(ReconciliationInputError, match="row limit"):
        _report(wallets=[_wallet(10), _wallet(11)], max_rows=1)
    with pytest.raises(ReconciliationInputError, match="row limit"):
        _report(transactions=[_transaction(100), _transaction(101)], max_rows=1)


def test_continuous_referenced_chain_is_unverified_and_has_no_inferred_currency():
    report = _report()
    main = report["wallets"][0]["buckets"]["main"]
    assert report["status"] == "unverified"
    assert report["verified_balance_count"] == 0
    assert report["issues"] == []
    assert main == {
        "stored_minor": 1500,
        "transaction_count": 1,
        "opening_observed_minor": 1000,
        "closing_observed_minor": 1500,
        "arithmetic_continuity": "consistent",
        "verified_balance": False,
        "source_provenance": "unverified_legacy",
        "currency": None,
        "issues": [],
    }
    assert report["wallets"][0]["verified_balance"] is False
    assert all("USD" not in repr(value) for value in (report, main))


def test_missing_wallet_is_unknown_not_an_invented_verified_zero_balance():
    report = _report(users=_users(1, 2), wallets=[], transactions=[])
    assert report["status"] == "unverified"
    assert report["verified_balance_count"] == 0
    assert report["counts"] == {
        "users": 2,
        "wallets": 0,
        "transactions": 0,
        "users_without_wallet": 2,
        "issues": 0,
    }
    assert report["wallets"] == []
    assert "Missing wallet is unknown, not verified zero" in report["limitations"]


def test_chain_delta_and_stored_closing_disagreements_are_observed_not_repaired():
    cases = (
        (
            [_transaction(), _transaction(101, before="14.00", after="16.00", amount="2.00", reference_id=901, created_at=AT_2)],
            [_wallet()],
            "TRANSACTION_CHAIN_GAP",
        ),
        ([_transaction(after="14.00")], [_wallet(main="14.00")], "TRANSACTION_DELTA_MISMATCH"),
        ([_transaction()], [_wallet(main="16.00")], "STORED_BALANCE_CHAIN_MISMATCH"),
    )
    for transactions, wallets, expected in cases:
        report = _report(wallets=wallets, transactions=transactions)
        assert expected in _codes(report)
        assert report["status"] == "blocked"
        assert report["verified_balance_count"] == 0


def test_invalid_money_source_bucket_and_orphan_rows_block_without_imputing_values():
    cases = (
        ([_transaction(amount="1.001")], "TRANSACTION_MONEY_INVALID"),
        ([_transaction(reference_type=None, reference_id=None)], "TRANSACTION_SOURCE_REFERENCE_MISSING"),
        ([_transaction(bucket="invented_bucket")], "TRANSACTION_BUCKET_UNKNOWN"),
        ([_transaction(bucket=[])], "TRANSACTION_BUCKET_UNKNOWN"),
        ([_transaction(wallet_id=999)], "TRANSACTION_WALLET_MISSING"),
    )
    for transactions, expected in cases:
        report = _report(transactions=transactions)
        assert expected in _codes(report)
        assert report["status"] == "blocked"
        assert report["verified_balance_count"] == 0


def test_duplicate_wallet_owner_and_duplicate_row_identifiers_are_refused_or_reported():
    report = _report(wallets=[_wallet(10), _wallet(11)])
    assert _codes(report).count("DUPLICATE_WALLET_OWNER") == 2
    malformed_owner = _report(wallets=[_wallet(user_id=[])])
    assert "WALLET_OWNER_MISSING" in _codes(malformed_owner)
    for users, wallets, transactions in (
        (_users(1, 1), [], []),
        (_users(1), [_wallet(10), _wallet(10)], []),
        (_users(1), [_wallet()], [_transaction(100), _transaction(100)]),
    ):
        with pytest.raises(ReconciliationInputError, match="duplicate identifiers"):
            _report(users=users, wallets=wallets, transactions=transactions)


def test_timestamp_ambiguity_and_aware_or_invalid_timestamps_are_blocked_not_ordered_by_guesswork():
    ambiguous = _report(transactions=[
        _transaction(100, reference_id=900),
        _transaction(101, before="15.00", after="16.00", amount="1.00", reference_id=901),
    ])
    assert "TRANSACTION_ORDER_AMBIGUOUS" in _codes(ambiguous)
    for created_at in (datetime(2026, 1, 1, tzinfo=timezone.utc), "not-a-timestamp"):
        report = _report(transactions=[_transaction(created_at=created_at)])
        assert "TRANSACTION_TIME_INVALID" in _codes(report)
        assert report["wallets"][0]["buckets"]["main"]["closing_observed_minor"] is None


def test_adjustments_accept_either_observed_sign_only_when_absolute_delta_matches():
    for before, after, expected_opening, expected_closing in (
        ("10.00", "15.00", 1000, 1500),
        ("15.00", "10.00", 1500, 1000),
    ):
        report = _report(
            wallets=[_wallet(main=after)],
            transactions=[_transaction(kind="adjustment", before=before, after=after)],
        )
        main = report["wallets"][0]["buckets"]["main"]
        assert "TRANSACTION_DELTA_MISMATCH" not in _codes(report)
        assert (main["opening_observed_minor"], main["closing_observed_minor"]) == (expected_opening, expected_closing)
        assert main["verified_balance"] is False
    invalid = _report(
        wallets=[_wallet(main="13.00")],
        transactions=[_transaction(kind="adjustment", before="10.00", after="13.00", amount="5.00")],
    )
    assert "TRANSACTION_DELTA_MISMATCH" in _codes(invalid)


def test_reconciliation_does_not_mutate_callers_snapshot_rows():
    users = _users(1)
    wallets = [_wallet()]
    transactions = [_transaction()]
    supplied = {"users": users, "wallets": wallets, "transactions": transactions}
    before = deepcopy(supplied)
    _report(**supplied)
    assert supplied == before


def test_aggregate_summary_redacts_wallet_user_and_balance_fields_but_retains_unverified_counts():
    report = _report()
    summary = aggregate_summary(report)
    rendered = repr(summary)
    assert summary["verified_balance_count"] == 0
    assert summary["counts"] == report["counts"]
    assert "wallets" not in summary
    assert "wallet_id" not in rendered and "user_id" not in rendered
    assert "stored_minor" not in rendered and "opening_observed_minor" not in rendered
    assert "1500" not in rendered and "1000" not in rendered


def test_balance_reconciliation_reused_source_across_buckets_and_kinds_is_flagged():
    report = _report(
        wallets=[_wallet(main="5.00", commission="5.00")],
        transactions=[
            _transaction(100, bucket="main", kind="deposit", before="0.00", after="5.00"),
            _transaction(101, bucket="commission", kind="commission", before="0.00", after="5.00", created_at=AT_2),
        ],
    )
    assert report['status'] == 'blocked'
    assert report['verified_balance_count'] == 0
    assert 'TRANSACTION_SOURCE_REFERENCE_REUSED' in _codes(report)


def test_balance_reconciliation_decimal_exponent_is_not_silently_normalized():
    with pytest.raises(ReconciliationInputError):
        exact_minor(Decimal('1E+2'))
    assert exact_minor(Decimal('100.00')) == 10000
