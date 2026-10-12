"""Isolated PostgreSQL proof for legacy trading-program NULL preservation.

Run this module only through ``backend/scripts/run_staging_integration.py``.
Each case owns a fresh runner-created database and uses Alembic revisions only.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url


BACKEND = Path(__file__).resolve().parents[1]
PARENT = "20261012_000001"
REVISION = "20261013_000001"
TABLE = "trading_programs"
RISK_COLUMNS = ("profit_target", "max_daily_loss", "max_total_loss")
LEGACY_PROGRAM_IDS = tuple(range(44001, 44009))


@contextmanager
def program_null_database(resources):
    """Create a fresh predecessor-head database owned by the staging runner."""
    database = "marketedgepros_test_" + uuid4().hex
    url = make_url(resources["pg_url"]).set(database=database)
    admin = create_engine(
        make_url(resources["pg_url"]).set(database="postgres"),
        isolation_level="AUTOCOMMIT",
    )
    engine = None
    config = None
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database}"'))
        engine = create_engine(url)
        config = Config(str(BACKEND / "migrations/alembic.ini"))
        config.set_main_option("script_location", str(BACKEND / "migrations"))
        config.set_main_option(
            "sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%")
        )
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, PARENT)
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == PARENT
            yield connection, config
    finally:
        if config is not None:
            config.attributes.pop("connection", None)
        if engine is not None:
            engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database}"'))
        admin.dispose()


@contextmanager
def record_schema_ddl(connection):
    """Capture only migration schema statements, excluding fixture DML."""
    statements: list[str] = []

    def capture(conn, cursor, statement, parameters, execution_context, executemany):
        if statement.lstrip().upper().startswith(("CREATE ", "ALTER ", "DROP ")):
            statements.append(statement)

    event.listen(connection, "before_cursor_execute", capture)
    try:
        yield statements
    finally:
        event.remove(connection, "before_cursor_execute", capture)


def _normalised_type(type_) -> str:
    rendered = str(type_.compile(dialect=postgresql.dialect())).lower()
    return " ".join(rendered.replace("character varying", "varchar").split())


def _program_shape(connection) -> dict[str, tuple[str, bool, str | None]]:
    return {
        column["name"]: (_normalised_type(column["type"]), column["nullable"], column["default"])
        for column in inspect(connection).get_columns(TABLE, schema="public")
    }


def _changed_columns(before, after):
    return {
        name: (before[name], after[name])
        for name in before
        if before[name] != after[name]
    }


def _upgrade(connection, config) -> None:
    command.upgrade(config, REVISION)
    # The test supplies Alembic's connection, so persist the completed upgrade
    # before a later intentional refusal rolls back its own preflight work.
    connection.commit()
    assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == REVISION


def _legacy_rows(connection):
    return connection.execute(text("""
        SELECT id, tenant_id, name, program_type, type,
               account_size::text, price::text,
               profit_target::text, max_daily_loss::text, max_total_loss::text,
               profit_split, is_active, rules::text
        FROM public.trading_programs
        ORDER BY id
    """)).all()


def _insert_legacy_null_programs(connection) -> None:
    """Model eight transferred old44 rows whose three risk fields are NULL."""
    for column in RISK_COLUMNS:
        connection.execute(text(
            f"ALTER TABLE public.{TABLE} ALTER COLUMN {column} DROP NOT NULL"
        ))
    connection.execute(text("""
        INSERT INTO public.tenants (id, name, slug, is_active)
        VALUES (44001, 'Legacy Transfer Tenant', 'legacy-transfer-tenant', false)
    """))
    for number, program_id in enumerate(LEGACY_PROGRAM_IDS, start=1):
        connection.execute(text("""
            INSERT INTO public.trading_programs (
                id, tenant_id, name, program_type, type, account_size, price,
                rules, is_active, profit_target, max_daily_loss, max_total_loss,
                profit_split
            ) VALUES (
                :id, 44001, :name, 'legacy_transfer', 'legacy_transfer',
                :account_size, :price, CAST(:rules AS jsonb), false,
                NULL, NULL, NULL, 80
            )
        """), {
            "id": program_id,
            "name": f"Legacy Transfer Program {number}",
            "account_size": f"{number * 10000}.00",
            "price": f"{number * 10}.99",
            "rules": '{"source":"old44","transfer":"synthetic"}',
        })
    connection.commit()


def _null_count(connection) -> int:
    return connection.execute(text("""
        SELECT count(*)
        FROM public.trading_programs
        WHERE profit_target IS NULL
          AND max_daily_loss IS NULL
          AND max_total_loss IS NULL
    """)).scalar_one()


def _program_count(connection) -> int:
    return connection.execute(text("SELECT count(*) FROM public.trading_programs")).scalar_one()


def test_program_null_preservation_upgrade_changes_only_three_columns(staging_resources, record_property):
    """The additive upgrade changes only the three intended nullable constraints."""
    source = (BACKEND / "migrations/versions/20261013_000001_preserve_program_nulls.py").read_text(
        encoding="utf-8"
    ).lower()
    assert 'revision = "20261013_000001"' in source
    assert 'down_revision = "20261012_000001"' in source
    assert "update" not in source
    assert "default" not in source
    assert "server_default" not in source

    with program_null_database(staging_resources) as (connection, config):
        before = _program_shape(connection)
        with record_schema_ddl(connection) as emitted:
            _upgrade(connection, config)
        after = _program_shape(connection)

        expected = {
            name: (("numeric(10, 2)", False, None), ("numeric(10, 2)", True, None))
            for name in RISK_COLUMNS
        }
        assert _changed_columns(before, after) == expected
        assert len(emitted) == len(RISK_COLUMNS)
        assert all(statement.lstrip().upper().startswith("ALTER TABLE") for statement in emitted)
        assert {name for name in RISK_COLUMNS if any(
            f"alter column {name}" in statement.lower() and "drop not null" in statement.lower()
            for statement in emitted
        )} == set(RISK_COLUMNS)
        record_property("upgrade_schema_delta", "only profit_target,max_daily_loss,max_total_loss: NOT NULL -> NULL")


def test_program_null_preservation_keeps_eight_legacy_rows_and_guards_downgrade(
    staging_resources, record_property
):
    """NULL rows remain NULL; downgrade requires explicit, known replacement values."""
    with program_null_database(staging_resources) as (connection, config):
        _insert_legacy_null_programs(connection)
        rows_before_upgrade = _legacy_rows(connection)
        assert len(rows_before_upgrade) == 8
        assert _program_count(connection) == len(LEGACY_PROGRAM_IDS) == 8
        assert _null_count(connection) == 8
        assert all(row[7:10] == (None, None, None) for row in rows_before_upgrade)

        _upgrade(connection, config)
        rows_after_upgrade = _legacy_rows(connection)
        assert rows_after_upgrade == rows_before_upgrade
        assert _program_count(connection) == len(LEGACY_PROGRAM_IDS) == 8
        assert _null_count(connection) == 8
        assert all(row[7:10] == (None, None, None) for row in rows_after_upgrade)
        assert connection.execute(text("""
            SELECT count(*) FROM public.trading_programs
            WHERE profit_target = 0 OR max_daily_loss = 0 OR max_total_loss = 0
        """)).scalar_one() == 0

        with record_schema_ddl(connection) as emitted:
            with pytest.raises(RuntimeError, match="refuses while trading_programs retains NULL"):
                command.downgrade(config, PARENT)
        assert emitted == []
        connection.rollback()
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == REVISION
        assert _program_count(connection) == len(LEGACY_PROGRAM_IDS) == 8
        assert _legacy_rows(connection) == rows_before_upgrade

        expected_values = {
            program_id: (f"{10 + offset}.25", f"{4 + offset}.50", f"{8 + offset}.75")
            for offset, program_id in enumerate(LEGACY_PROGRAM_IDS)
        }
        for program_id, values in expected_values.items():
            connection.execute(text("""
                UPDATE public.trading_programs
                SET profit_target = CAST(:profit_target AS numeric(10, 2)),
                    max_daily_loss = CAST(:max_daily_loss AS numeric(10, 2)),
                    max_total_loss = CAST(:max_total_loss AS numeric(10, 2))
                WHERE id = :id
            """), {
                "id": program_id,
                "profit_target": values[0],
                "max_daily_loss": values[1],
                "max_total_loss": values[2],
            })
        connection.commit()
        assert connection.execute(text("""
            SELECT id, profit_target::text, max_daily_loss::text, max_total_loss::text
            FROM public.trading_programs ORDER BY id
        """)).all() == [
            (program_id, *expected_values[program_id]) for program_id in LEGACY_PROGRAM_IDS
        ]

        before_downgrade = _program_shape(connection)
        command.downgrade(config, PARENT)
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == PARENT
        after_downgrade = _program_shape(connection)
        expected_delta = {
            name: (("numeric(10, 2)", True, None), ("numeric(10, 2)", False, None))
            for name in RISK_COLUMNS
        }
        assert _changed_columns(before_downgrade, after_downgrade) == expected_delta
        assert connection.execute(text("""
            SELECT id, profit_target::text, max_daily_loss::text, max_total_loss::text
            FROM public.trading_programs ORDER BY id
        """)).all() == [
            (program_id, *expected_values[program_id]) for program_id in LEGACY_PROGRAM_IDS
        ]
        record_property("legacy_null_rows_preserved", "8; all three fields remained NULL, never 0")
        record_property("downgrade_guard", "refused with NULLs; succeeded after explicit synthetic values")
