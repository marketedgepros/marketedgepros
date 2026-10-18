"""Isolated PostgreSQL tests for the synthetic Stage 5c durable protocol rehearsal.

This suite calls the internal rehearsal service only.  All program, challenge, provider,
account, token and event identities below are deliberately synthetic test fixtures; no
provider, MT5 endpoint, entitlement, worker, route, or retry loop is involved.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from time import monotonic
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from flask import Flask
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


PROTOCOL_HEAD = "20261011_000008"
UTC = timezone.utc
NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
HISTORICAL_AT = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
SYNTHETIC_PROVIDER = "SYNTHETIC_STAGE5C_PROVIDER"
SYNTHETIC_ACCOUNT = "SYNTHETIC_CALLBACK_ACCOUNT_100"


@contextmanager
def protocol_database(resources, monkeypatch):
    """Create one private migrated PostgreSQL database without ``create_all``.

    The migration is applied before the Flask factory and protocol service are imported,
    which makes the service's own readiness check observe the real frozen 000008 DDL.
    """
    from src.app import create_app
    from src.database import db

    database = "marketedgepros_test_" + uuid4().hex
    url = make_url(resources["pg_url"]).set(database=database)
    rendered = url.render_as_string(hide_password=False)
    admin = create_engine(
        make_url(resources["pg_url"]).set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    app = None
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database}"'))
        monkeypatch.setenv("TEST_DATABASE_URL", rendered)
        backend = Path(__file__).resolve().parents[1]
        migration_config = Config(str(backend / "migrations" / "alembic.ini"))
        migration_config.set_main_option("script_location", str(backend / "migrations"))
        migration_config.set_main_option("sqlalchemy.url", rendered.replace("%", "%%"))
        migration_engine = create_engine(url)
        try:
            with migration_engine.connect() as connection:
                migration_config.attributes["connection"] = connection
                command.upgrade(migration_config, PROTOCOL_HEAD)
        finally:
            migration_engine.dispose()

        app = create_app("testing", config_overrides={
            "SQLALCHEMY_DATABASE_URI": rendered,
            "ISOLATED_STAGING_DATABASE": True,
            "TRADING_PROTOCOL_REHEARSAL_ENABLED": True,
            "PLATFORM_ROOT_USER_ID": 1,
            "EXPANDED_HIERARCHY_ENABLED": False,
            "SQLALCHEMY_ENGINE_OPTIONS": {"pool_size": 4, "max_overflow": 0, "pool_timeout": 5},
        })
        with app.app_context():
            _seed_synthetic_protocol_parents()
            db.session.commit()
        yield app
    finally:
        if app is not None:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def protocol_app(staging_resources, monkeypatch):
    with protocol_database(staging_resources, monkeypatch) as app:
        yield app


def _seed_synthetic_protocol_parents():
    """Insert only explicit fake legacy rows required by the real migration graph."""
    from src.database import db

    # These are raw SQL seeds so the asserted legacy migration shape, rather than
    # SQLAlchemy defaults or create_all, supplies the exact historical relations.
    db.session.execute(text("""
        INSERT INTO tenants (id, name, slug, subdomain, status)
        VALUES
          (1, 'Synthetic Stage5c Tenant', 'synthetic-stage5c', 'synthetic-stage5c', 'active'),
          (2, 'Synthetic Other Tenant', 'synthetic-other', 'synthetic-other', 'active')
    """))
    db.session.execute(text("""
        INSERT INTO users
          (id, email, password_hash, first_name, last_name, role, tenant_id,
           parent_id, level, tree_path, is_active, is_verified, can_create_same_role)
        VALUES
          (1, 'synthetic-owner@stage5c.invalid', 'not-a-credential', 'Synthetic', 'Owner',
           'supermaster', 1, NULL, 0, '1', true, true, true),
          (2, 'synthetic-trader@stage5c.invalid', 'not-a-credential', 'Synthetic', 'Trader',
           'trader', 1, 1, 1, '1/2', true, true, false),
          (3, 'synthetic-other@stage5c.invalid', 'not-a-credential', 'Synthetic', 'Other',
           'trader', 2, NULL, 0, '3', true, true, false)
    """))
    db.session.execute(text("""
        INSERT INTO trading_programs
          (id, tenant_id, name, program_type, type, account_size, price, rules,
           is_active, profit_target, max_daily_loss, max_total_loss, profit_split)
        VALUES
          (10, 1, 'Synthetic Stage5c Program', 'one_phase', 'one_phase', 10000, 19.99,
           CAST(:rules AS jsonb), true, 10, 5, 10, 80),
          (11, 2, 'Synthetic Other Program', 'one_phase', 'one_phase', 10000, 19.99,
           CAST(:rules AS jsonb), true, 10, 5, 10, 80)
    """), {"rules": '{"source":"synthetic","local_only":true}'})
    # ``phase`` is the original non-null legacy field.  ``current_phase`` is also
    # supplied deliberately because it is the current model's explicit phase field.
    db.session.execute(text("""
        INSERT INTO challenges
          (id, user_id, program_id, status, phase, current_phase, total_phases,
           payment_status, payment_type, approval_status, initial_balance, current_balance)
        VALUES
          (100, 2, 10, 'pending', 1, 1, 1, 'pending', 'synthetic', 'approved', 10000, 10000),
          (101, 2, 10, 'pending', 1, 1, 1, 'pending', 'synthetic', 'approved', 10000, 10000),
          (102, 2, 10, 'pending', 1, 1, 1, 'pending', 'synthetic', 'approved', 10000, 10000),
          (200, 3, 11, 'pending', 1, 1, 1, 'pending', 'synthetic', 'approved', 10000, 10000)
    """))


def make_rules(**changes):
    """Canonical complete TST rules copied locally, never imported from security tests."""
    from src.services.trading_risk_contract import RiskLimit, TradingRules

    values = {
        "schema_version": 1,
        "rules_version": "TST_STAGE5C_1",
        "program_id": 10,
        "phase": 1,
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


def make_observation(rules, *, command_id="unused", account_id=SYNTHETIC_ACCOUNT,
                     provider_id=SYNTHETIC_PROVIDER, challenge_id=100,
                     event_id="SYNTHETIC_EVENT_1", sequence=1, observed_at=NOW, **changes):
    """Build an exact typed, local-only synthetic observation (no arbitrary JSON)."""
    from src.services.trading_risk_rehearsal import RiskObservation

    values = {
        "tenant_id": 1,
        "challenge_id": challenge_id,
        "provider_id": provider_id,
        "account_id": account_id,
        "rules_digest": rules.digest,
        "event_id": event_id,
        "sequence": sequence,
        "observed_at": observed_at,
        "currency": rules.currency,
        "currency_scale": rules.currency_scale,
        "balance_units": rules.initial_units,
        "equity_units": rules.initial_units,
        "equity_includes_fees_and_swaps": True,
    }
    assert command_id == "unused" or isinstance(command_id, str)  # documents that command identity is API-side.
    values.update(changes)
    return RiskObservation(**values)


def _service():
    from src.services.trading_protocol_service import TradingProtocolRehearsal
    return TradingProtocolRehearsal


def _error_type():
    from src.services.trading_protocol_service import ProtocolError
    return ProtocolError


def _status(error):
    """The service error carries an HTTP status without coupling to its attribute spelling."""
    for attribute in ("status_code", "status", "http_status"):
        value = getattr(error, attribute, None)
        if type(value) is int:
            return value
    raise AssertionError("ProtocolError did not expose an integer HTTP status")


def _assert_refusal(call, *, code=None, status=409):
    with pytest.raises(_error_type()) as raised:
        call()
    error = raised.value
    assert _status(error) == status
    if code is not None:
        assert error.code == code
    return error


def _assert_local_synthetic(result):
    assert result["source"] == "synthetic"
    assert result["provider_verified"] is False
    assert result["authorized"] is False


def _protocol_counts():
    from src.database import db
    return db.session.execute(text("""
        SELECT
          (SELECT count(*) FROM trading_rule_snapshots),
          (SELECT count(*) FROM trading_provision_commands),
          (SELECT count(*) FROM trading_event_inbox)
    """)).one()


def _historical_state():
    """A content digest plus MT5 row count guards against non-protocol side effects."""
    from src.database import db
    return db.session.execute(text("""
        SELECT
          md5(COALESCE((SELECT string_agg(to_jsonb(t)::text, '' ORDER BY t.id) FROM tenants t), '')),
          md5(COALESCE((SELECT string_agg(to_jsonb(p)::text, '' ORDER BY p.id) FROM trading_programs p), '')),
          md5(COALESCE((SELECT string_agg(to_jsonb(c)::text, '' ORDER BY c.id) FROM challenges c), '')),
          (SELECT count(*) FROM mt5_accounts)
    """)).one()


def _store(rules, *, tenant_id=1, at=NOW):
    return _service().store_rules(tenant_id, rules, at=at)


def _plan(snapshot_id, *, challenge_id=100, tenant_id=1, provider_id=SYNTHETIC_PROVIDER, at=NOW):
    return _service().plan_command(tenant_id, challenge_id, provider_id, snapshot_id, at=at)


def _claimed_command(rules=None, *, challenge_id=100, provider_id=SYNTHETIC_PROVIDER):
    """Persist one planned command then atomically place it in dispatched state."""
    from src.database import db

    rules = rules or make_rules()
    snapshot = _store(rules)
    command = _plan(snapshot["id"], challenge_id=challenge_id, provider_id=provider_id)
    claim = _service().claim_command(command["id"], at=NOW)
    db.session.commit()
    return rules, snapshot, command, claim


def _acknowledged_command(rules=None, *, challenge_id=100, provider_id=SYNTHETIC_PROVIDER,
                          account_id=SYNTHETIC_ACCOUNT):
    from src.database import db

    rules, snapshot, command, claim = _claimed_command(
        rules, challenge_id=challenge_id, provider_id=provider_id
    )
    acknowledgement = _service().acknowledge(
        command["id"], claim["attempt_token"], account_id, at=NOW
    )
    db.session.commit()
    return rules, snapshot, command, claim, acknowledgement


def _race_two(app, calls):
    """Exactly two independent sessions, one shared start barrier, and a 20 s ceiling."""
    from src.database import db

    assert len(calls) == 2
    barrier = Barrier(2, timeout=10)

    def worker(call):
        with app.app_context():
            db.session.execute(text("SET statement_timeout = '10s'"))
            barrier.wait()
            try:
                result = call()
                db.session.commit()
                return ("ok", result)
            except _error_type() as error:
                db.session.rollback()
                return ("refused", error.code, _status(error))
            finally:
                db.session.remove()

    started = monotonic()
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker, call) for call in calls]
        results = [future.result(timeout=20) for future in futures]
    elapsed = monotonic() - started
    assert elapsed < 20
    return results


def test_store_rules_is_idempotent_immutable_synthetic_snapshot(protocol_app):
    from src.database import db

    rules = make_rules()
    with protocol_app.app_context():
        first = _store(rules)
        replay = _store(rules)
        assert first["created"] is True
        assert replay["created"] is False
        assert replay["id"] == first["id"]
        assert len(first["id"]) == 64
        _assert_local_synthetic(first)
        _assert_local_synthetic(replay)
        assert _protocol_counts() == (1, 0, 0)
        db.session.commit()


def test_snapshot_races_have_one_replay_for_identical_rules_and_one_conflict_for_changed_version(protocol_app):
    from src.database import db
    from src.services.trading_risk_contract import RiskLimit

    identical = make_rules()
    same_results = _race_two(protocol_app, [
        lambda: _store(identical),
        lambda: _store(identical),
    ])
    assert [row[0] for row in same_results] == ["ok", "ok"]
    assert sorted(row[1]["created"] for row in same_results) == [False, True]
    assert len({row[1]["id"] for row in same_results}) == 1

    changed = make_rules(
        rules_version="TST_STAGE5C_CHANGED_VERSION",
        daily_loss=RiskLimit("units", 999),
    )
    changed_again = make_rules(
        rules_version="TST_STAGE5C_CHANGED_VERSION",
        daily_loss=RiskLimit("units", 998),
    )
    conflict_results = _race_two(protocol_app, [
        lambda: _store(changed),
        lambda: _store(changed_again),
    ])
    assert [row[0] for row in conflict_results].count("ok") == 1
    assert ("refused", "PROTOCOL_CONFLICT", 409) in conflict_results
    with protocol_app.app_context():
        assert _protocol_counts() == (2, 0, 0)
        db.session.rollback()


def test_plan_race_creates_one_durable_command_and_one_replay(protocol_app):
    from src.database import db

    with protocol_app.app_context():
        snapshot = _store(make_rules())
        db.session.commit()
    results = _race_two(protocol_app, [
        lambda: _plan(snapshot["id"]),
        lambda: _plan(snapshot["id"]),
    ])
    assert [row[0] for row in results] == ["ok", "ok"]
    assert sorted(row[1]["created"] for row in results) == [False, True]
    assert len({row[1]["id"] for row in results}) == 1
    command = results[0][1]
    assert command["status"] == "planned"
    assert command["attempt_token"] is None and command["account_id"] is None
    _assert_local_synthetic(command)
    with protocol_app.app_context():
        assert _protocol_counts() == (1, 1, 0)
        db.session.rollback()


@pytest.mark.parametrize("case", ["tenant", "predates-snapshot", "provider-differs"])
def test_plan_refuses_tenant_time_or_provider_context_conflicts_before_extra_command_insert(protocol_app, case):
    from src.database import db

    with protocol_app.app_context():
        snapshot = _store(make_rules())
        if case == "tenant":
            _assert_refusal(
                lambda: _plan(snapshot["id"], tenant_id=2),
                code="PROTOCOL_SCOPE_MISMATCH",
            )
            expected = (1, 0, 0)
        elif case == "predates-snapshot":
            _assert_refusal(
                lambda: _plan(snapshot["id"], at=NOW - timedelta(microseconds=1)),
                code="PROTOCOL_STATE_CONFLICT",
            )
            expected = (1, 0, 0)
        else:
            _plan(snapshot["id"], provider_id=SYNTHETIC_PROVIDER)
            _assert_refusal(
                lambda: _plan(snapshot["id"], provider_id="SYNTHETIC_OTHER_PROVIDER"),
            )
            expected = (1, 1, 0)
        assert _protocol_counts() == expected
        db.session.rollback()


def test_double_claim_has_one_dispatch_winner_and_no_second_attempt_token(protocol_app):
    from src.database import db

    with protocol_app.app_context():
        snapshot = _store(make_rules())
        command = _plan(snapshot["id"])
        db.session.commit()
    results = _race_two(protocol_app, [
        lambda: _service().claim_command(command["id"], at=NOW),
        lambda: _service().claim_command(command["id"], at=NOW),
    ])
    winners = [row[1] for row in results if row[0] == "ok"]
    assert len(winners) == 1
    assert winners[0]["status"] == "dispatched"
    assert isinstance(winners[0]["attempt_token"], str) and winners[0]["attempt_token"]
    assert ("refused", "PROTOCOL_STATE_CONFLICT", 409) in results
    with protocol_app.app_context():
        persisted = db.session.execute(text("""
            SELECT status, attempt_token, account_id FROM trading_provision_commands WHERE id = :id
        """), {"id": command["id"]}).one()
        assert persisted == ("dispatched", winners[0]["attempt_token"], None)
        assert _protocol_counts() == (1, 1, 0)
        db.session.rollback()


def test_uncertain_is_idempotent_but_never_reclaimable_and_wrong_token_refuses(protocol_app):
    with protocol_app.app_context():
        rules, _snapshot, command, claim = _claimed_command()
        uncertain = _service().mark_uncertain(command["id"], claim["attempt_token"], at=NOW)
        replay = _service().mark_uncertain(command["id"], claim["attempt_token"], at=NOW)
        assert uncertain["status"] == replay["status"] == "uncertain"
        assert uncertain["attempt_token"] == replay["attempt_token"] == claim["attempt_token"]
        _assert_local_synthetic(uncertain)
        _assert_refusal(
            lambda: _service().claim_command(command["id"], at=NOW),
            code="PROTOCOL_STATE_CONFLICT",
        )
        _assert_refusal(
            lambda: _service().mark_uncertain(command["id"], "00000000-0000-0000-0000-000000000000", at=NOW),
            code="PROTOCOL_STATE_CONFLICT",
        )
        assert rules.digest


def test_changed_legacy_owner_tenant_after_plan_refuses_claim_without_transition(protocol_app):
    from src.database import db

    with protocol_app.app_context():
        snapshot = _store(make_rules())
        command = _plan(snapshot["id"])
        db.session.commit()
        before = db.session.execute(text("""
            SELECT status, attempt_token, account_id
            FROM trading_provision_commands WHERE id = :id
        """), {"id": command["id"]}).one()
        # Deliberately direct synthetic test tampering: the durable command must
        # revalidate its legacy owner binding before any claim transition.
        db.session.execute(text("UPDATE users SET tenant_id = NULL WHERE id = 2"))
        db.session.commit()
        _assert_refusal(
            lambda: _service().claim_command(command["id"], at=NOW),
            code="PROTOCOL_SCOPE_MISMATCH",
        )
        db.session.rollback()
        after = db.session.execute(text("""
            SELECT status, attempt_token, account_id
            FROM trading_provision_commands WHERE id = :id
        """), {"id": command["id"]}).one()
        assert after == before == ("planned", None, None)


def test_acknowledgement_replay_never_changes_challenge_or_creates_mt5_account(protocol_app):
    from src.database import db

    with protocol_app.app_context():
        before = _historical_state()
        rules, _snapshot, command, claim = _claimed_command()
        first = _service().acknowledge(command["id"], claim["attempt_token"], SYNTHETIC_ACCOUNT, at=NOW)
        replay = _service().acknowledge(command["id"], claim["attempt_token"], SYNTHETIC_ACCOUNT, at=NOW)
        assert first["status"] == replay["status"] == "acknowledged"
        assert first["id"] == replay["id"] == command["id"]
        assert first["account_id"] == replay["account_id"] == SYNTHETIC_ACCOUNT
        _assert_local_synthetic(first)
        _assert_refusal(
            lambda: _service().acknowledge(
                command["id"], claim["attempt_token"], "SYNTHETIC_CALLBACK_OTHER", at=NOW
            ),
            code="PROTOCOL_CONFLICT",
        )
        db.session.commit()
        assert _historical_state() == before
        assert _protocol_counts() == (1, 1, 0)
        assert rules.digest


def test_two_commands_cannot_acknowledge_the_same_synthetic_callback_account(protocol_app):
    from src.database import db

    with protocol_app.app_context():
        rules = make_rules()
        snapshot = _store(rules)
        first = _plan(snapshot["id"], challenge_id=100)
        second = _plan(snapshot["id"], challenge_id=101)
        first_claim = _service().claim_command(first["id"], at=NOW)
        second_claim = _service().claim_command(second["id"], at=NOW)
        db.session.commit()
    results = _race_two(protocol_app, [
        lambda: _service().acknowledge(first["id"], first_claim["attempt_token"], SYNTHETIC_ACCOUNT, at=NOW),
        lambda: _service().acknowledge(second["id"], second_claim["attempt_token"], SYNTHETIC_ACCOUNT, at=NOW),
    ])
    assert [row[0] for row in results].count("ok") == 1
    assert [row[0] for row in results].count("refused") == 1
    assert results[[row[0] for row in results].index("refused")][2] == 409
    with protocol_app.app_context():
        assert db.session.execute(text("""
            SELECT count(*) FROM trading_provision_commands
            WHERE provider_id = :provider AND account_id = :account
        """), {"provider": SYNTHETIC_PROVIDER, "account": SYNTHETIC_ACCOUNT}).scalar_one() == 1
        db.session.rollback()


def test_inbox_event_replay_returns_original_id_and_changed_payload_conflicts(protocol_app):
    from src.database import db

    with protocol_app.app_context():
        rules, _snapshot, command, _claim, acknowledgement = _acknowledged_command()
        observation = make_observation(
            rules, account_id=acknowledgement["account_id"], event_id="SYNTHETIC_OLD_EVENT",
            sequence=9, observed_at=HISTORICAL_AT,
        )
        # The evidence itself is intentionally old; it is received at the current
        # synthetic UTC time, after the command was acknowledged.
        first = _service().record_observation(command["id"], observation, at=NOW)
        replay = _service().record_observation(command["id"], observation, at=NOW)
        assert first["created"] is True and replay["created"] is False
        assert first["id"] == replay["id"]
        _assert_local_synthetic(first)
        db.session.commit()
        changed = replace(observation, balance_units=observation.balance_units + 1)
        _assert_refusal(
            lambda: _service().record_observation(command["id"], changed, at=NOW),
            code="PROTOCOL_CONFLICT",
        )
        db.session.rollback()
        assert _protocol_counts() == (1, 1, 1)


def test_two_different_events_with_same_sequence_have_one_inbox_winner(protocol_app):
    from src.database import db

    with protocol_app.app_context():
        rules, _snapshot, command, _claim, acknowledgement = _acknowledged_command()
    left = make_observation(rules, account_id=acknowledgement["account_id"], event_id="SYNTHETIC_SEQUENCE_LEFT", sequence=7)
    right = make_observation(rules, account_id=acknowledgement["account_id"], event_id="SYNTHETIC_SEQUENCE_RIGHT", sequence=7)
    results = _race_two(protocol_app, [
        lambda: _service().record_observation(command["id"], left, at=NOW),
        lambda: _service().record_observation(command["id"], right, at=NOW),
    ])
    assert [row[0] for row in results].count("ok") == 1
    assert [row[0] for row in results].count("refused") == 1
    assert results[[row[0] for row in results].index("refused")][2] == 409
    with protocol_app.app_context():
        assert _protocol_counts() == (1, 1, 1)
        db.session.rollback()


@pytest.mark.parametrize("field,value", [
    ("tenant_id", 2),
    ("provider_id", "SYNTHETIC_OTHER_PROVIDER"),
    ("account_id", "SYNTHETIC_CALLBACK_OTHER"),
    ("rules_digest", "0" * 64),
], ids=["tenant", "provider", "account", "rules"])
def test_observation_scope_identity_mismatch_refuses_before_inbox_insert(protocol_app, field, value):
    from src.database import db

    with protocol_app.app_context():
        rules, _snapshot, command, _claim, acknowledgement = _acknowledged_command()
        observation = make_observation(rules, account_id=acknowledgement["account_id"])
        observation = replace(observation, **{field: value})
        _assert_refusal(
            lambda: _service().record_observation(command["id"], observation, at=NOW),
            code="PROTOCOL_SCOPE_MISMATCH",
        )
        assert _protocol_counts() == (1, 1, 0)
        db.session.rollback()


def test_inbox_persists_three_out_of_order_sequences_without_processing_them(protocol_app):
    from src.database import db

    with protocol_app.app_context():
        rules, _snapshot, command, _claim, acknowledgement = _acknowledged_command()
        account = acknowledgement["account_id"]
        for sequence in (3, 1, 2):
            event = make_observation(
                rules, account_id=account, event_id=f"SYNTHETIC_OUT_OF_ORDER_{sequence}", sequence=sequence,
                observed_at=NOW - timedelta(seconds=sequence),
            )
            result = _service().record_observation(command["id"], event, at=NOW)
            assert result["created"] is True
        db.session.commit()
        assert db.session.execute(text("""
            SELECT sequence FROM trading_event_inbox WHERE command_id = :id ORDER BY sequence
        """), {"id": command["id"]}).scalars().all() == [1, 2, 3]
        assert _protocol_counts() == (1, 1, 3)


def test_caller_outer_rollback_removes_snapshot_command_and_inbox_together(protocol_app):
    from src.database import db

    with protocol_app.app_context():
        rules = make_rules()
        snapshot = _store(rules)
        command = _plan(snapshot["id"])
        claim = _service().claim_command(command["id"], at=NOW)
        acknowledgement = _service().acknowledge(command["id"], claim["attempt_token"], SYNTHETIC_ACCOUNT, at=NOW)
        event = make_observation(rules, account_id=acknowledgement["account_id"])
        _service().record_observation(command["id"], event, at=NOW)
        assert _protocol_counts() == (1, 1, 1)
        db.session.rollback()
        assert _protocol_counts() == (0, 0, 0)


@pytest.mark.parametrize("write_kind", ["snapshot", "command", "inbox"])
def test_injected_flush_failure_rolls_back_only_the_service_savepoint(protocol_app, monkeypatch, write_kind):
    from src.database import db

    with protocol_app.app_context():
        rules = make_rules()
        if write_kind == "snapshot":
            expected_before = (0, 0, 0)
            expected_after = (0, 0, 0)
            invoke = lambda: _store(rules)
            expected_index = 0
        elif write_kind == "command":
            snapshot = _store(rules)
            db.session.commit()
            expected_before = (1, 0, 0)
            expected_after = expected_before
            invoke = lambda: _plan(snapshot["id"])
            expected_index = 1
        else:
            _rules, _snapshot, command, _claim, acknowledgement = _acknowledged_command(rules)
            expected_before = (1, 1, 0)
            expected_after = expected_before
            invoke = lambda: _service().record_observation(
                command["id"], make_observation(rules, account_id=acknowledgement["account_id"]), at=NOW
            )
            expected_index = 2

        real_execute = db.session.execute
        saw_persisted_write = []

        table_by_kind = {
            "snapshot": "trading_rule_snapshots",
            "command": "trading_provision_commands",
            "inbox": "trading_event_inbox",
        }

        def execute_after_real_write(statement, *args, **kwargs):
            result = real_execute(statement, *args, **kwargs)
            # The service is intentionally raw-SQL rather than ORM-backed.  This
            # injection is therefore the equivalent of raising after a real flush:
            # PostgreSQL has accepted the INSERT inside begin_nested(), and the
            # enclosing savepoint must still remove it when the exception escapes.
            rendered = str(statement).lower()
            if "insert into public." + table_by_kind[write_kind] in rendered:
                counts = db.session.connection().execute(text("""
                    SELECT
                      (SELECT count(*) FROM trading_rule_snapshots),
                      (SELECT count(*) FROM trading_provision_commands),
                      (SELECT count(*) FROM trading_event_inbox)
                """)).one()
                if counts[expected_index] > expected_before[expected_index]:
                    saw_persisted_write.append(counts)
                    raise RuntimeError("synthetic post-write protocol failure")
            return result

        monkeypatch.setattr(db.session, "execute", execute_after_real_write)
        with pytest.raises(RuntimeError, match="synthetic post-write protocol failure"):
            invoke()
        assert saw_persisted_write
        # Commit, rather than rollback, proves begin_nested() cleaned just the failed
        # service unit and did not leave a partial durable protocol record behind.
        db.session.commit()
        assert _protocol_counts() == expected_after


@pytest.mark.parametrize("tamper", ["wrong-head", "altered-function", "conditional-trigger", "replica"])
def test_runtime_storage_gate_refuses_tampered_protocol_authority_before_insert(protocol_app, tamper):
    from src.database import db

    with protocol_app.app_context():
        if tamper == "wrong-head":
            db.session.execute(text("UPDATE alembic_version SET version_num = '20261011_000007'"))
            db.session.commit()
        elif tamper == "altered-function":
            db.session.execute(text("""
                CREATE OR REPLACE FUNCTION public.marketedgepros_trading_protocol_immutable()
                RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN
                    RETURN NEW;
                END;
                $$
            """))
            db.session.commit()
        elif tamper == "conditional-trigger":
            db.session.execute(text("""
                DROP TRIGGER trading_rule_snapshots_validate_insert
                ON public.trading_rule_snapshots
            """))
            db.session.execute(text("""
                CREATE TRIGGER trading_rule_snapshots_validate_insert
                BEFORE INSERT ON public.trading_rule_snapshots
                FOR EACH ROW WHEN (false)
                EXECUTE FUNCTION public.marketedgepros_trading_rule_snapshot_validate()
            """))
            db.session.commit()
        else:
            db.session.execute(text("SET LOCAL session_replication_role = replica"))

        _assert_refusal(
            lambda: _store(make_rules()), code="PROTOCOL_STORAGE_NOT_READY", status=503
        )
        db.session.rollback()
        assert _protocol_counts() == (0, 0, 0)


def test_disabled_rehearsal_refuses_before_any_database_sql(monkeypatch):
    from src.database import db

    application = Flask("protocol-disabled-guard")
    application.config.update(
        TESTING=True,
        FLASK_TESTING=True,
        ISOLATED_STAGING_DATABASE=True,
        TRADING_PROTOCOL_REHEARSAL_ENABLED=False,
    )
    sql_calls = 0

    def no_sql(*args, **kwargs):
        nonlocal sql_calls
        sql_calls += 1
        raise AssertionError("disabled protocol rehearsal attempted database SQL")

    monkeypatch.setattr(db.session, "execute", no_sql)
    with application.app_context():
        _assert_refusal(
            lambda: _store(make_rules()), code="PROTOCOL_NOT_CONFIGURED", status=503
        )
    assert sql_calls == 0
