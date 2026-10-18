"""Real PostgreSQL checks for the additive Stage 3 core schema shape."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import io
import json
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
import pytest


BACKEND = Path(__file__).resolve().parents[1]
PREVIOUS = "20261011_000004"
REVISION = "20261011_000005"
CORE_FIELDS: dict[str, tuple[str, ...]] = {
    "tenants": (
        "accent_color", "contact_email", "contact_phone", "custom_css",
        "custom_domain", "favicon_url", "logo_url", "primary_color",
        "secondary_color", "settings", "status", "subdomain", "tier",
    ),
    "trading_programs": (
        "minimum_payout_amount", "payout_mode", "profit_split_percentage",
        "rules", "type",
    ),
    "challenges": (
        "account_number", "addons", "approval_status", "approved_at",
        "approved_by", "created_by", "current_phase", "daily_drawdown_history",
        "end_date", "max_drawdown", "passed_at", "payment_type",
        "rejection_reason", "start_date", "total_phases",
    ),
    "payments": (
        "admin_notes", "approval_status", "approved_at", "approved_by",
        "payment_type", "rejection_reason",
    ),
    "program_addons": ("benefits", "price_type"),
}
ALL_FIELDS = tuple((table_name, field) for table_name, fields in CORE_FIELDS.items() for field in fields)

# Canonical model types only for the new fields; historical columns intentionally
# retain their wider or otherwise incompatible legacy types.
EXPECTED_TYPES = {
    ("tenants", "accent_color"): "varchar(7)",
    ("tenants", "contact_email"): "varchar(255)",
    ("tenants", "contact_phone"): "varchar(20)",
    ("tenants", "custom_css"): "text",
    ("tenants", "custom_domain"): "varchar(255)",
    ("tenants", "favicon_url"): "varchar(500)",
    ("tenants", "logo_url"): "varchar(500)",
    ("tenants", "primary_color"): "varchar(7)",
    ("tenants", "secondary_color"): "varchar(7)",
    ("tenants", "settings"): "jsonb",
    ("tenants", "status"): "varchar(20)",
    ("tenants", "subdomain"): "varchar(100)",
    ("tenants", "tier"): "varchar(20)",
    ("trading_programs", "minimum_payout_amount"): "numeric(10, 2)",
    ("trading_programs", "payout_mode"): "varchar(50)",
    ("trading_programs", "profit_split_percentage"): "numeric(5, 2)",
    ("trading_programs", "rules"): "jsonb",
    ("trading_programs", "type"): "varchar(50)",
    ("challenges", "account_number"): "varchar(50)",
    ("challenges", "addons"): "jsonb",
    ("challenges", "approval_status"): "varchar(20)",
    ("challenges", "approved_at"): "timestamp without time zone",
    ("challenges", "approved_by"): "integer",
    ("challenges", "created_by"): "integer",
    ("challenges", "current_phase"): "integer",
    ("challenges", "daily_drawdown_history"): "jsonb",
    ("challenges", "end_date"): "timestamp without time zone",
    ("challenges", "max_drawdown"): "numeric(12, 2)",
    ("challenges", "passed_at"): "timestamp without time zone",
    ("challenges", "payment_type"): "varchar(20)",
    ("challenges", "rejection_reason"): "text",
    ("challenges", "start_date"): "timestamp without time zone",
    ("challenges", "total_phases"): "integer",
    ("payments", "admin_notes"): "text",
    ("payments", "approval_status"): "varchar(20)",
    ("payments", "approved_at"): "timestamp without time zone",
    ("payments", "approved_by"): "integer",
    ("payments", "payment_type"): "varchar(20)",
    ("payments", "rejection_reason"): "text",
    ("program_addons", "benefits"): "jsonb",
    ("program_addons", "price_type"): "varchar(20)",
}


@contextmanager
def core_shape_database(resources):
    """Build one clean historical graph in a runner-owned PostgreSQL database."""
    database = "marketedgepros_test_" + uuid4().hex
    url = make_url(resources["pg_url"]).set(database=database)
    admin = create_engine(
        make_url(resources["pg_url"]).set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    engine = None
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database}"'))
        engine = create_engine(url)
        config = Config(str(BACKEND / "migrations/alembic.ini"))
        config.set_main_option("script_location", str(BACKEND / "migrations"))
        config.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%"))
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, PREVIOUS)
            yield connection, config
        config.attributes.pop("connection", None)
    finally:
        if engine is not None:
            engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database}"'))
        admin.dispose()


def insert_legacy_sentinels(connection) -> None:
    """Insert only legacy-required values, including intentionally unknown enums."""
    connection.execute(text("""
        INSERT INTO tenants (id, name, slug, domain, is_active)
        VALUES (991001, 'Core Shape Sentinel', 'core-shape-sentinel',
                'legacy-shape.example.invalid', false)
    """))
    connection.execute(text("""
        INSERT INTO users (id, email, password_hash, first_name, last_name,
                           is_active, is_verified, role, tenant_id, token_version)
        VALUES (991001, 'core-shape-sentinel@example.invalid', 'not-a-login-credential',
                'Core', 'Sentinel', false, false, 'trader', 991001, 13)
    """))
    connection.execute(text("""
        INSERT INTO trading_programs (
            id, tenant_id, name, description, program_type, account_size, price,
            profit_target, max_daily_loss, max_total_loss, profit_split, is_active
        ) VALUES (
            991001, 991001, 'Legacy Program', 'No type mapping is approved',
            'legacy-unknown-program-type', 100000.00, 499.99, 10.00, 5.00, 10.00,
            80, false
        )
    """))
    connection.execute(text("""
        INSERT INTO program_addons (id, program_id, name, description, price, addon_type, is_active)
        VALUES (991001, 991001, 'Legacy Add-on', 'No price-type mapping is approved',
                25.00, 'legacy-unknown-addon-type', false)
    """))
    connection.execute(text("""
        INSERT INTO challenges (
            id, user_id, program_id, status, phase, initial_balance, current_balance,
            total_profit, total_loss, payment_id, payment_status
        ) VALUES (
            991001, 991001, 991001, 'legacy-challenge-x', 3,
            100000.00, 99900.00, 123.45, 100.00, 'legacy-payment-id',
            'legacy-payment-x'
        )
    """))
    connection.execute(text("""
        INSERT INTO payments (
            id, user_id, amount, currency, payment_method, transaction_id, status,
            purpose, reference_id, provider_response
        ) VALUES (
            991001, 991001, 499.99, 'USD', 'legacy-unknown-payment-method',
            'core-shape-transaction', 'legacy-payment-x',
            'challenge_purchase', 991001, '{"legacy": true}'
        )
    """))
    connection.commit()


def _normalised_type(type_) -> str:
    rendered = str(type_.compile(dialect=postgresql.dialect())).lower()
    return " ".join(rendered.replace("character varying", "varchar").split())


def _snapshot_with_columns(connection, columns_by_table: dict[str, tuple[str, ...]]) -> str:
    """Hash only the pre-existing row shape, so added NULL fields cannot mask drift."""
    snapshot: dict[str, list[str]] = {}
    for table_name, columns in columns_by_table.items():
        selected = ", ".join(f'"{column}"' for column in columns)
        statement = text(
            f'SELECT row_to_json(snapshot_row)::text '
            f'FROM (SELECT {selected} FROM "{table_name}" ORDER BY id) AS snapshot_row'
        )
        snapshot[table_name] = list(connection.execute(statement).scalars())
    payload = json.dumps(snapshot, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _legacy_column_snapshot(connection) -> tuple[dict[str, tuple[str, ...]], str]:
    inspector = inspect(connection)
    columns_by_table = {
        table_name: tuple(column["name"] for column in inspector.get_columns(table_name))
        for table_name in CORE_FIELDS
    }
    return columns_by_table, _snapshot_with_columns(connection, columns_by_table)


def _assert_all_fields_present_and_unknown(connection) -> None:
    inspector = inspect(connection)
    for table_name, fields in CORE_FIELDS.items():
        columns = {column["name"]: column for column in inspector.get_columns(table_name)}
        assert set(fields).issubset(columns), table_name
        values = connection.execute(text(
            f'SELECT {", ".join(f"\"{field}\"" for field in fields)} '
            f'FROM "{table_name}" WHERE id = 991001'
        )).one()
        assert tuple(values) == (None,) * len(fields), f"{table_name} inferred non-NULL data"
        for field in fields:
            assert columns[field]["nullable"] is True
            assert columns[field]["default"] is None
            assert _normalised_type(columns[field]["type"]) == EXPECTED_TYPES[(table_name, field)]


def _assert_shape_constraints(connection) -> None:
    inspector = inspect(connection)
    unique = {item["name"]: item["column_names"] for item in inspector.get_unique_constraints("tenants")}
    assert unique["uq_tenants_custom_domain"] == ["custom_domain"]
    assert "uq_tenants_subdomain" not in unique
    indexes = {item["name"]: item for item in inspector.get_indexes("tenants")}
    assert indexes["ix_tenants_subdomain"]["column_names"] == ["subdomain"]
    assert indexes["ix_tenants_subdomain"]["unique"] is True
    challenge_fks = {item["name"]: item for item in inspector.get_foreign_keys("challenges")}
    payment_fks = {item["name"]: item for item in inspector.get_foreign_keys("payments")}
    assert challenge_fks["fk_challenges_approved_by_users"]["constrained_columns"] == ["approved_by"]
    assert challenge_fks["fk_challenges_approved_by_users"]["referred_table"] == "users"
    assert challenge_fks["fk_challenges_created_by_users"]["constrained_columns"] == ["created_by"]
    assert challenge_fks["fk_challenges_created_by_users"]["referred_table"] == "users"
    assert payment_fks["fk_payments_approved_by_users"]["constrained_columns"] == ["approved_by"]
    assert payment_fks["fk_payments_approved_by_users"]["referred_table"] == "users"


def test_core_shape_adds_all_41_fields_without_inference_and_reverses_exactly(staging_resources):
    with core_shape_database(staging_resources) as (connection, config):
        insert_legacy_sentinels(connection)
        legacy_columns, original_hash = _legacy_column_snapshot(connection)

        command.upgrade(config, REVISION)
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == REVISION
        _assert_all_fields_present_and_unknown(connection)
        _assert_shape_constraints(connection)
        assert connection.execute(text("""
            SELECT program_type FROM trading_programs WHERE id = 991001
        """)).scalar_one() == "legacy-unknown-program-type"
        assert connection.execute(text("""
            SELECT status, payment_status FROM challenges WHERE id = 991001
        """)).one() == ("legacy-challenge-x", "legacy-payment-x")
        assert connection.execute(text("""
            SELECT payment_method, status FROM payments WHERE id = 991001
        """)).one() == ("legacy-unknown-payment-method", "legacy-payment-x")
        assert _snapshot_with_columns(connection, legacy_columns) == original_hash

        command.downgrade(config, PREVIOUS)
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == PREVIOUS
        inspector = inspect(connection)
        for table_name, fields in CORE_FIELDS.items():
            actual = {column["name"] for column in inspector.get_columns(table_name)}
            assert not actual.intersection(fields)
        assert _snapshot_with_columns(connection, legacy_columns) == original_hash

        # A subsequent upgrade remains additive and preserves the unknown state.
        command.upgrade(config, REVISION)
        _assert_all_fields_present_and_unknown(connection)


def test_core_shape_collision_in_last_field_prevents_every_earlier_add(staging_resources):
    with core_shape_database(staging_resources) as (connection, config):
        # price_type is the final frozen field.  A complete preflight must not
        # leave columns in the four earlier tables when this collision is found.
        connection.execute(text("ALTER TABLE program_addons ADD COLUMN price_type varchar(20)"))
        connection.commit()
        with pytest.raises(RuntimeError, match="Core schema reconciliation required"):
            command.upgrade(config, REVISION)
        connection.rollback()

        inspector = inspect(connection)
        for table_name, fields in CORE_FIELDS.items():
            actual = {column["name"] for column in inspector.get_columns(table_name)}
            expected_absent = set(fields) - {"price_type"} if table_name == "program_addons" else set(fields)
            assert not actual.intersection(expected_absent), table_name
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == PREVIOUS


@pytest.mark.parametrize(
    ("table_name", "field", "sql_value"),
    (
        ("tenants", "status", "''"),
        ("tenants", "settings", "'{}'::jsonb"),
        ("trading_programs", "minimum_payout_amount", "0"),
        ("challenges", "addons", "'[]'::jsonb"),
        ("payments", "admin_notes", "''"),
        ("program_addons", "benefits", "'{}'::jsonb"),
    ),
)
def test_core_shape_online_downgrade_refuses_any_non_null_before_drop(
    staging_resources, table_name, field, sql_value
):
    with core_shape_database(staging_resources) as (connection, config):
        insert_legacy_sentinels(connection)
        command.upgrade(config, REVISION)
        connection.execute(text(
            f'UPDATE "{table_name}" SET "{field}" = {sql_value} WHERE id = 991001'
        ))
        connection.commit()

        with pytest.raises(RuntimeError, match="Core schema downgrade refused"):
            command.downgrade(config, PREVIOUS)
        connection.rollback()
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == REVISION
        inspector = inspect(connection)
        for expected_table, fields in CORE_FIELDS.items():
            actual = {column["name"] for column in inspector.get_columns(expected_table)}
            assert set(fields).issubset(actual), expected_table
        assert connection.execute(text(
            f'SELECT "{field}" IS NOT NULL FROM "{table_name}" WHERE id = 991001'
        )).scalar_one() is True


def test_core_shape_offline_downgrade_refuses_to_emit_data_blind_drop(staging_resources, monkeypatch):
    buffer = io.StringIO()
    config = Config(str(BACKEND / "migrations/alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", staging_resources["pg_url"].replace("%", "%%"))
    config.output_buffer = buffer
    monkeypatch.setenv("TEST_DATABASE_URL", staging_resources["pg_url"])

    with pytest.raises(RuntimeError, match="offline downgrade is unsupported"):
        command.downgrade(config, f"{REVISION}:{PREVIOUS}", sql=True)
    assert "DROP COLUMN" not in buffer.getvalue()


@contextmanager
def record_schema_ddl(connection):
    from sqlalchemy import event
    statements=[]
    def capture(conn,cursor,statement,parameters,context,executemany):
        if statement.lstrip().upper().startswith(('CREATE ','ALTER ','DROP ')):
            statements.append(statement)
    event.listen(connection,'before_cursor_execute',capture)
    try:yield statements
    finally:event.remove(connection,'before_cursor_execute',capture)


@pytest.mark.parametrize('collision_ddl',[
    'CREATE INDEX ix_tenants_subdomain ON tenants (slug)',
    'ALTER TABLE tenants ADD CONSTRAINT uq_tenants_custom_domain UNIQUE (slug)',
    'ALTER TABLE challenges ADD CONSTRAINT fk_challenges_approved_by_users FOREIGN KEY (user_id) REFERENCES users(id)',
    'ALTER TABLE challenges ADD CONSTRAINT fk_challenges_created_by_users FOREIGN KEY (user_id) REFERENCES users(id)',
    'ALTER TABLE payments ADD CONSTRAINT fk_payments_approved_by_users FOREIGN KEY (user_id) REFERENCES users(id)',
    'CREATE SEQUENCE ix_tenants_subdomain',
])
def test_named_object_upgrade_collisions_refuse_before_any_ddl(staging_resources,collision_ddl):
    with core_shape_database(staging_resources) as (connection,config):
        connection.execute(text(collision_ddl));connection.commit()
        with record_schema_ddl(connection) as emitted:
            with pytest.raises(RuntimeError,match='Named schema object collision before DDL'):
                command.upgrade(config,REVISION)
        assert emitted==[]
        connection.rollback()
        for table,fields in CORE_FIELDS.items():
            assert not set(fields).intersection(c['name'] for c in inspect(connection).get_columns(table))
        assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one()==PREVIOUS


@pytest.mark.parametrize('alterations',[
    ['DROP INDEX ix_tenants_subdomain'],
    ['ALTER TABLE tenants DROP CONSTRAINT uq_tenants_custom_domain'],
    ['ALTER TABLE challenges DROP CONSTRAINT fk_challenges_approved_by_users'],
    ['ALTER TABLE challenges DROP CONSTRAINT fk_challenges_created_by_users'],
    ['ALTER TABLE payments DROP CONSTRAINT fk_payments_approved_by_users'],
    ['DROP INDEX ix_tenants_subdomain','CREATE INDEX ix_tenants_subdomain ON tenants (subdomain)'],
    ['ALTER TABLE tenants DROP CONSTRAINT uq_tenants_custom_domain','ALTER TABLE tenants ADD CONSTRAINT uq_tenants_custom_domain UNIQUE (contact_email)'],
    ['ALTER TABLE challenges DROP CONSTRAINT fk_challenges_approved_by_users','ALTER TABLE challenges ADD CONSTRAINT fk_challenges_approved_by_users FOREIGN KEY (created_by) REFERENCES users(id)'],
    ['CREATE INDEX external_status_index ON tenants(status)'],
    ['CREATE INDEX external_domain_expression ON tenants((lower(custom_domain)))'],
    ["ALTER TABLE tenants ADD CONSTRAINT external_status_check CHECK (status <> 'unknown')"],
    ['CREATE TABLE external_reference (domain varchar(255) REFERENCES tenants(custom_domain))'],
])
def test_missing_replaced_or_dependent_objects_refuse_before_any_drop(staging_resources,alterations):
    with core_shape_database(staging_resources) as (connection,config):
        command.upgrade(config,REVISION)
        for statement in alterations:connection.execute(text(statement))
        connection.commit()
        with record_schema_ddl(connection) as emitted:
            with pytest.raises(RuntimeError,match='Named schema object ownership/definition mismatch before DDL'):
                command.downgrade(config,PREVIOUS)
        assert emitted==[]
        connection.rollback()
        for table,fields in CORE_FIELDS.items():
            assert set(fields).issubset(c['name'] for c in inspect(connection).get_columns(table))
        assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one()==REVISION
