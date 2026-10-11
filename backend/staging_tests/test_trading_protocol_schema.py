"""Real PostgreSQL contract tests for frozen Stage5c protocol migration 000008."""
from __future__ import annotations

import io
import json
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from test_purchase_order_schema import (
    insert_quote_parents,
    purchase_order_database,
    record_schema_ddl,
    upgrade_orders,
)


BACKEND = Path(__file__).resolve().parents[1]
PREVIOUS = "20261011_000007"
REVISION = "20261011_000008"
SNAPSHOT = "trading_rule_snapshots"
COMMAND = "trading_provision_commands"
INBOX = "trading_event_inbox"
TABLES = {SNAPSHOT, COMMAND, INBOX}
AT = "2026-10-11 12:00:00+00"
SNAPSHOT_ID = "a" * 64
DIGEST = "b" * 64
COMMAND_ID = "00000000-0000-0000-0000-000000008001"
TOKEN = "00000000-0000-0000-0000-000000008002"


def upgrade_protocol(connection, config) -> None:
    command.upgrade(config, REVISION)
    assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == REVISION


def prepare_protocol(connection, config) -> None:
    """Supply only disabled synthetic FK parents, then reach 000008."""
    insert_quote_parents(connection, users=(991001, 991002))
    connection.execute(text("""
        INSERT INTO challenges (id, user_id, program_id) VALUES (991001, 991001, 991001)
    """))
    connection.execute(text("""
        INSERT INTO challenges (id, user_id, program_id) VALUES (991002, 991002, 991001)
    """))
    connection.commit()
    upgrade_orders(connection, config)
    upgrade_protocol(connection, config)
    connection.commit()


def insert_snapshot(connection, *, snapshot_id: str = SNAPSHOT_ID, rules_version: str = "stage5c-r1") -> None:
    rules = {
        "schema_version": 1, "rules_version": rules_version, "program_id": 991001, "phase": 1,
        "currency": "USD", "currency_scale": 2, "initial_units": 10000000,
        "profit_target": {"unit": "bps", "value": 1000}, "daily_loss": {"unit": "bps", "value": 500},
        "total_loss": {"unit": "bps", "value": 1000}, "target_basis": "balance",
        "daily_basis": "equity", "daily_reference_basis": "balance", "total_basis": "balance",
        "total_drawdown_mode": "static", "loss_at_threshold_is_breach": True,
        "target_at_threshold_is_met": True, "timezone_name": "UTC", "reset_hour": 0,
        "reset_minute": 0, "reset_fold": 0, "maximum_age_seconds": 60,
    }
    connection.execute(text("""
        INSERT INTO trading_rule_snapshots (
            id, tenant_id, program_id, phase, rules_version, rules_digest,
            canonical_rules, source, created_at
        ) VALUES (
            :id, 991001, 991001, 1, :rules_version, :digest,
            CAST(:canonical AS jsonb),
            'synthetic', :at
        )
    """), {"id": snapshot_id, "rules_version": rules_version, "digest": DIGEST,
            "canonical": json.dumps(rules, separators=(",", ":"), sort_keys=True), "at": AT})


def insert_planned_command(connection, *, command_id: str = COMMAND_ID, challenge_id: int = 991001,
                           provider: str = "synthetic-provider", snapshot_id: str = SNAPSHOT_ID) -> None:
    connection.execute(text("""
        INSERT INTO trading_provision_commands (
            id, tenant_id, challenge_id, phase, provider_id, rule_snapshot_id, source,
            status, attempt_token, account_id, created_at, updated_at
        ) VALUES (
            :id, 991001, :challenge_id, 1, :provider, :snapshot_id, 'synthetic',
            'planned', NULL, NULL, :at, :at
        )
    """), {"id": command_id, "challenge_id": challenge_id, "provider": provider,
          "snapshot_id": snapshot_id, "at": AT})


def acknowledge(connection, *, command_id: str = COMMAND_ID, account: str = "account-001") -> None:
    connection.execute(text("""
        UPDATE trading_provision_commands
        SET status='dispatched', attempt_token=:token, updated_at=:at
        WHERE id=:id
    """), {"id": command_id, "token": TOKEN, "at": "2026-10-11 12:00:01+00"})
    connection.execute(text("""
        UPDATE trading_provision_commands
        SET status='acknowledged', account_id=:account, updated_at=:at
        WHERE id=:id
    """), {"id": command_id, "account": account, "at": "2026-10-11 12:00:02+00"})


def payload(*, account: str = "account-001", event: str = "event-001", sequence: int = 1) -> str:
    return json.dumps({
        "schema_version": 1, "source": "synthetic", "local_only": True,
        "observation": {
            "tenant_id": 991001, "challenge_id": 991001, "provider_id": "synthetic-provider",
            "account_id": account, "rules_digest": DIGEST, "event_id": event, "sequence": sequence,
            "observed_at": "2026-10-11T12:00:00.000000+00:00", "currency": "USD",
            "currency_scale": 2, "balance_units": 10000000, "equity_units": 10000000,
            "equity_includes_fees_and_swaps": True,
        },
    }, separators=(",", ":"), sort_keys=True)


def test_protocol_upgrade_is_exact_three_tables_and_preserves_legacy_schema(staging_resources):
    with purchase_order_database(staging_resources) as (connection, config):
        insert_quote_parents(connection)
        upgrade_orders(connection, config)
        command.upgrade(config, PREVIOUS)
        connection.commit()
        before_tables = set(inspect(connection).get_table_names(schema="public"))
        legacy_columns = [(column["name"], str(column["type"]), column["nullable"])
                          for column in inspect(connection).get_columns("purchase_orders", schema="public")]
        upgrade_protocol(connection, config)
        inspector = inspect(connection)
        assert set(inspector.get_table_names(schema="public")) - before_tables == TABLES
        assert [(column["name"], str(column["type"]), column["nullable"])
                for column in inspector.get_columns("purchase_orders", schema="public")] == legacy_columns
        assert {row["name"] for row in inspector.get_check_constraints(SNAPSHOT)} == {
            "ck_trading_rule_snapshot_id", "ck_trading_rule_snapshot_phase",
            "ck_trading_rule_snapshot_rules_version", "ck_trading_rule_snapshot_digest",
            "ck_trading_rule_snapshot_canonical", "ck_trading_rule_snapshot_source",
        }
        assert {row["name"] for row in inspector.get_unique_constraints(COMMAND)} == {
            "uq_trading_provision_command_context", "uq_trading_provision_provider_account",
        }
        assert {row["name"] for row in inspector.get_unique_constraints(INBOX)} == {
            "uq_trading_event_inbox_event", "uq_trading_event_inbox_sequence",
        }
        assert all(column["default"] is None for table in TABLES for column in inspector.get_columns(table))
        assert connection.execute(text("SELECT count(*) FROM trading_rule_snapshots")).scalar_one() == 0


def test_protocol_direct_sql_state_machine_scope_unique_and_immutability(staging_resources):
    with purchase_order_database(staging_resources) as (connection, config):
        prepare_protocol(connection, config)
        insert_snapshot(connection)
        insert_planned_command(connection)
        with pytest.raises(IntegrityError, match="uq_trading_provision_command_context"):
            insert_planned_command(connection, command_id="00000000-0000-0000-0000-000000008003", provider="different-provider")
        connection.rollback()
        assert connection.execute(text("SELECT count(*) FROM trading_rule_snapshots")).scalar_one() == 0
        insert_snapshot(connection)
        insert_planned_command(connection)
        with pytest.raises(DBAPIError, match="only transitions planned to dispatched"):
            connection.execute(text("""UPDATE trading_provision_commands SET status='uncertain',
                attempt_token=:token, updated_at=:at WHERE id=:id"""),
                {"id": COMMAND_ID, "token": TOKEN, "at": "2026-10-11 12:00:01+00"})
        connection.rollback()
        insert_snapshot(connection)
        insert_planned_command(connection)
        connection.execute(text("""UPDATE trading_provision_commands SET status='dispatched',
            attempt_token=:token, updated_at=:at WHERE id=:id"""),
            {"id": COMMAND_ID, "token": TOKEN, "at": "2026-10-11 12:00:01+00"})
        connection.execute(text("""UPDATE trading_provision_commands SET status='uncertain',
            updated_at=:at WHERE id=:id"""), {"id": COMMAND_ID, "at": "2026-10-11 12:00:02+00"})
        connection.execute(text("""UPDATE trading_provision_commands SET status='acknowledged',
            account_id='account-001', updated_at=:at WHERE id=:id"""),
            {"id": COMMAND_ID, "at": "2026-10-11 12:00:03+00"})
        # Exact direct-SQL acknowledgement replay is permitted; a changed account is not.
        connection.execute(text("""UPDATE trading_provision_commands SET status='acknowledged',
            account_id='account-001', updated_at=:at WHERE id=:id"""),
            {"id": COMMAND_ID, "at": "2026-10-11 12:00:04+00"})
        with pytest.raises(DBAPIError, match="acknowledged state is terminal"):
            connection.execute(text("""UPDATE trading_provision_commands SET account_id='account-002',
                updated_at=:at WHERE id=:id"""), {"id": COMMAND_ID, "at": "2026-10-11 12:00:05+00"})
        connection.rollback()
        insert_snapshot(connection)
        insert_planned_command(connection)
        connection.commit()
        for table in (SNAPSHOT,):
            with pytest.raises(DBAPIError, match="trading protocol rows are immutable"):
                connection.execute(text(f"UPDATE {table} SET id=id"))
            connection.rollback()
        # Command deletion and all three truncates are database-authoritative refusals.
        with pytest.raises(DBAPIError, match="cannot be deleted"):
            connection.execute(text("DELETE FROM trading_provision_commands"))
        connection.rollback()
        for table in (SNAPSHOT, COMMAND, INBOX):
            with pytest.raises(DBAPIError, match="trading protocol rows are immutable"):
                connection.execute(text(f"TRUNCATE {table} CASCADE"))
            connection.rollback()
        assert connection.execute(text('SELECT count(*) FROM trading_rule_snapshots')).scalar_one() == 1
        assert connection.execute(text('SELECT count(*) FROM trading_provision_commands')).scalar_one() == 1


def test_protocol_inbox_requires_acknowledged_matching_canonical_observation(staging_resources):
    with purchase_order_database(staging_resources) as (connection, config):
        prepare_protocol(connection, config)
        insert_snapshot(connection)
        insert_planned_command(connection)
        acknowledge(connection)
        body = payload()
        connection.execute(text("""
            INSERT INTO trading_event_inbox (
                id, command_id, provider_id, account_id, event_id, sequence, payload_hash, payload, received_at
            ) VALUES (:id, :command, 'synthetic-provider', 'account-001', 'event-001', 1, :hash,
                      CAST(:payload AS jsonb), :at)
        """), {"id": "00000000-0000-0000-0000-000000008004", "command": COMMAND_ID,
              "hash": "c" * 64, "payload": body, "at": "2026-10-11 12:00:04+00"})
        connection.commit()
        with pytest.raises(DBAPIError, match="trading protocol rows are immutable"):
            connection.execute(text("DELETE FROM trading_event_inbox"))
        connection.rollback()
        assert connection.execute(text("SELECT count(*) FROM trading_event_inbox")).scalar_one() == 1


def test_protocol_collision_and_guarded_downgrade(staging_resources):
    with purchase_order_database(staging_resources) as (connection, config):
        insert_quote_parents(connection)
        upgrade_orders(connection, config)
        command.upgrade(config, PREVIOUS)
        connection.execute(text("CREATE TABLE trading_rule_snapshots (id integer PRIMARY KEY)"))
        connection.commit()
        with record_schema_ddl(connection) as emitted:
            with pytest.raises(RuntimeError, match="Trading protocol schema collision before DDL"):
                upgrade_protocol(connection, config)
        assert emitted == []
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == PREVIOUS

    with purchase_order_database(staging_resources) as (connection, config):
        prepare_protocol(connection, config)
        command.downgrade(config, PREVIOUS)
        assert not TABLES.intersection(inspect(connection).get_table_names(schema="public"))
        upgrade_protocol(connection, config)
        insert_snapshot(connection)
        connection.commit()
        with record_schema_ddl(connection) as emitted:
            with pytest.raises(RuntimeError, match="refuses to delete synthetic protocol evidence"):
                command.downgrade(config, PREVIOUS)
        assert emitted == []
        assert TABLES.issubset(inspect(connection).get_table_names(schema="public"))


def test_protocol_offline_downgrade_emits_no_drop_sql(staging_resources, monkeypatch):
    buffer = io.StringIO()
    config = Config(str(BACKEND / "migrations/alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", staging_resources["pg_url"].replace("%", "%%"))
    config.output_buffer = buffer
    monkeypatch.setenv("TEST_DATABASE_URL", staging_resources["pg_url"])
    with pytest.raises(RuntimeError, match="offline downgrade is unsupported"):
        command.downgrade(config, f"{REVISION}:{PREVIOUS}", sql=True)
    assert "DROP" not in buffer.getvalue().upper()


@pytest.mark.parametrize('new_tenant', [991002, None])
def test_protocol_direct_sql_command_refuses_changed_program_tenant(staging_resources, new_tenant):
    with purchase_order_database(staging_resources) as (connection, config):
        prepare_protocol(connection, config)
        insert_snapshot(connection)
        connection.commit()
        if new_tenant is not None:
            connection.execute(text('''INSERT INTO tenants (id,name,slug,domain,is_active)
                VALUES (:id,'Other Synthetic Tenant','other-synthetic-tenant',
                        'other-synthetic.example.invalid',false)'''), {'id': new_tenant})
        connection.execute(text('UPDATE trading_programs SET tenant_id=:tenant WHERE id=991001'), {'tenant': new_tenant})
        connection.commit()
        with pytest.raises(DBAPIError, match='mismatch'):
            insert_planned_command(connection)
        connection.rollback()
        assert connection.execute(text('SELECT count(*) FROM trading_provision_commands')).scalar_one() == 0
        assert connection.execute(text('SELECT count(*) FROM trading_rule_snapshots')).scalar_one() == 1


def test_protocol_direct_sql_cannot_insert_an_acknowledged_command(staging_resources):
    with purchase_order_database(staging_resources) as (connection, config):
        prepare_protocol(connection, config)
        insert_snapshot(connection)
        connection.commit()
        with pytest.raises(DBAPIError, match='inserted planned'):
            connection.execute(text('''INSERT INTO trading_provision_commands
                (id,tenant_id,challenge_id,phase,provider_id,rule_snapshot_id,source,status,attempt_token,account_id,created_at,updated_at)
                VALUES (:id,991001,991001,1,'synthetic-provider',:snapshot,'synthetic','acknowledged',:token,'account-001',:at,:at)'''),
                {'id': COMMAND_ID, 'snapshot': SNAPSHOT_ID, 'token': TOKEN, 'at': AT})
        connection.rollback()
        assert connection.execute(text('SELECT count(*) FROM trading_provision_commands')).scalar_one() == 0


@pytest.mark.parametrize('change', ['missing-key', 'null-key', 'string-local-only'])
def test_protocol_direct_sql_inbox_canonical_json_refuses_missing_or_wrong_types(staging_resources, change):
    with purchase_order_database(staging_resources) as (connection, config):
        prepare_protocol(connection, config)
        insert_snapshot(connection)
        insert_planned_command(connection)
        acknowledge(connection)
        connection.commit()
        body = json.loads(payload())
        if change == 'missing-key':
            del body['observation']['rules_digest']
        elif change == 'null-key':
            body['observation']['rules_digest'] = None
        else:
            body['local_only'] = 'true'
        with pytest.raises(DBAPIError):
            connection.execute(text('''INSERT INTO trading_event_inbox
                (id,command_id,provider_id,account_id,event_id,sequence,payload_hash,payload,received_at)
                VALUES (:id,:command,'synthetic-provider','account-001','event-001',1,:hash,CAST(:payload AS jsonb),:at)'''),
                {'id': '00000000-0000-0000-0000-000000008004', 'command': COMMAND_ID,
                 'hash': 'c'*64, 'payload': json.dumps(body), 'at': AT})
        connection.rollback()
        assert connection.execute(text('SELECT count(*) FROM trading_event_inbox')).scalar_one() == 0
