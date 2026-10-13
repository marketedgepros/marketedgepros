"""Destructive Alembic rehearsal on a database separate from model-DDL tests."""
from __future__ import annotations

import json
import os
import uuid
import ast
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
import pytest


BACKEND = Path(__file__).resolve().parents[1]
MERGE_REVISION = "20261011_000001"
HEAD = "20261013_000002"
EXPECTED_MODEL_TABLE_COUNT = 64
MAIN_OLD_HEAD = "20251110_191500"
TOKEN_OLD_HEAD = "token_blacklist_001"
CORE_SHAPE_COLUMNS = {
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


def _rehearsal_url(primary_url: str, database: str) -> str:
    return str(make_url(primary_url).set(database=database))


def _alembic_config(url: str) -> Config:
    config = Config(str(BACKEND / "migrations" / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    # Alembic's Config wraps ConfigParser, where a percent in the socket URL
    # must be escaped on assignment and is restored on retrieval by env.py.
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def _version_rows(engine) -> set[str]:
    with engine.connect() as connection:
        return set(connection.execute(text("SELECT version_num FROM alembic_version")).scalars())


def _assert_clean_schema(engine) -> None:
    tables = set(inspect(engine).get_table_names())
    assert not (tables - {"alembic_version"}), tables


def _assert_head_invariants(engine, *, expected_users: int = 0, expected_tenants: int = 0) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {
        "tenants", "users", "email_verification_tokens", "password_reset_tokens",
        "challenges", "payments", "trades", "token_blacklist", "account_scaling",
        "scaling_tiers", "purchase_orders", "payment_event_receipts",
        "settlement_journals", "settlement_entries",
        "trading_rule_snapshots", "trading_provision_commands", "trading_event_inbox",
        "affiliate_identity_evidence", "affiliate_order_attributions",
        "affiliate_commission_awards", "affiliate_payout_commands",
        "checkout_intents", "nowpayments_payment_bindings", "nowpayments_observations",
        "nowpayments_verified_receipts", "nowpayments_settlement_journals",
        "nowpayments_settlement_entries", "order_entitlement_grants",
    }.issubset(tables)
    user_columns = {column["name"]: column for column in inspector.get_columns("users")}
    assert user_columns["token_version"]["nullable"] is False
    assert user_columns["token_version"]["default"] in {"0", "'0'::integer"}
    assert user_columns['can_create_same_role']['nullable'] is False
    assert user_columns['can_create_same_role']['default'] in {'false', "'false'::boolean"}
    for name in ('available_balance', 'total_withdrawn', 'payout_count'):
        assert user_columns[name]['nullable'] is True
        assert user_columns[name]['default'] is None
    for table_name, fields in CORE_SHAPE_COLUMNS.items():
        columns = {column['name']: column for column in inspector.get_columns(table_name)}
        for name in fields:
            assert columns[name]['nullable'] is True
            assert columns[name]['default'] is None
    token_columns = {column["name"] for column in inspector.get_columns("token_blacklist")}
    assert {"jti", "token_type", "user_id", "revoked_at", "expires_at"}.issubset(token_columns)
    token_fks = inspector.get_foreign_keys("token_blacklist")
    assert any(fk["referred_table"] == "users" and fk["constrained_columns"] == ["user_id"] for fk in token_fks)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM users")).scalar_one() == expected_users
        assert connection.execute(text("SELECT count(*) FROM tenants")).scalar_one() == expected_tenants
        assert connection.execute(text("SELECT count(*) FROM trading_programs")).scalar_one() == 0


def _insert_main_branch_sentinel(connection) -> None:
    """Create one disabled synthetic row before the cross-branch merge only."""
    connection.execute(text("""
        INSERT INTO tenants (id, name, slug, is_active)
        VALUES (900001, 'Migration Rehearsal Sentinel', 'migration-rehearsal-sentinel', false)
    """))
    connection.execute(text("""
        INSERT INTO users (
            id, email, password_hash, first_name, last_name,
            is_active, is_verified, role, tenant_id
        ) VALUES (
            900001, 'migration-rehearsal-sentinel@example.invalid', 'not-a-login-credential',
            'Migration', 'Sentinel', false, false, 'user', 900001
        )
    """))
    connection.commit()


def _assert_and_remove_main_branch_sentinel(connection) -> None:
    """Verify the merge retained the synthetic row, then remove it before reuse."""
    assert connection.execute(text("""
        SELECT token_version FROM users
        WHERE email = 'migration-rehearsal-sentinel@example.invalid'
    """)).scalar_one() == 0
    values = connection.execute(text('SELECT can_create_same_role, available_balance, total_withdrawn, payout_count FROM users WHERE id = 900001')).one()
    assert tuple(values) == (False, None, None, None)
    tenant_values = connection.execute(text(
        'SELECT accent_color, contact_email, contact_phone, custom_css, custom_domain, '
        'favicon_url, logo_url, primary_color, secondary_color, settings, status, subdomain, tier '
        'FROM tenants WHERE id = 900001'
    )).one()
    assert tuple(tenant_values) == (None,) * len(CORE_SHAPE_COLUMNS['tenants'])
    connection.execute(text("""
        DELETE FROM users WHERE email = 'migration-rehearsal-sentinel@example.invalid'
    """))
    connection.execute(text("""
        DELETE FROM tenants WHERE slug = 'migration-rehearsal-sentinel'
    """))
    connection.commit()


def _normalized_type(type_) -> str:
    """Compare PostgreSQL type spellings without treating aliases as drift."""
    rendered = str(type_.compile(dialect=postgresql.dialect())).lower()
    return " ".join(rendered.replace("character varying", "varchar").split())


def _model_parity_summary(engine) -> dict[str, list[str]]:
    """Describe, rather than hide, the reachable-head/model metadata delta."""
    from src.database import db
    from src.schema_inventory import load_complete_model_inventory

    load_complete_model_inventory()

    inspector = inspect(engine)
    actual_tables = set(inspector.get_table_names())
    model_tables = db.metadata.tables
    assert len(model_tables) == EXPECTED_MODEL_TABLE_COUNT
    # Some production models are imported only by individual blueprints. A
    # focused host must not present loaded metadata as the complete inventory.
    declared_tables = set()
    for source_file in sorted((BACKEND / 'src' / 'models').glob('*.py')):
        syntax = ast.parse(source_file.read_text())
        for node in ast.walk(syntax):
            if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == '__tablename__'
                for target in node.targets
            ) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                declared_tables.add(node.value.value)
    missing_tables = sorted(set(model_tables) - actual_tables)
    missing_columns: list[str] = []
    missing_required_columns: list[str] = []
    type_mismatches: list[str] = []
    nullability_mismatches: list[str] = []
    server_default_mismatches: list[str] = []
    for table_name, model_table in sorted(model_tables.items()):
        if table_name not in actual_tables:
            continue
        actual_columns = {column["name"]: column for column in inspector.get_columns(table_name)}
        for model_column in model_table.columns:
            actual_column = actual_columns.get(model_column.name)
            qualified_name = f"{table_name}.{model_column.name}"
            if actual_column is None:
                missing_columns.append(qualified_name)
                if not model_column.nullable:
                    missing_required_columns.append(qualified_name)
                continue
            if _normalized_type(model_column.type) != _normalized_type(actual_column["type"]):
                type_mismatches.append(qualified_name)
            if model_column.nullable != actual_column['nullable']:
                nullability_mismatches.append(qualified_name)
            if model_column.server_default is not None:
                expected_default = str(model_column.server_default.arg).replace(" ", "")
                actual_default = (actual_column["default"] or "").replace(" ", "")
                if expected_default not in actual_default:
                    server_default_mismatches.append(qualified_name)
    return {
        "missing_tables": missing_tables,
        "unloaded_declared_tables": sorted(declared_tables - set(model_tables)),
        "missing_declared_tables": sorted(declared_tables - actual_tables),
        "missing_columns": sorted(missing_columns),
        "missing_required_columns": sorted(missing_required_columns),
        "type_mismatches": sorted(type_mismatches),
        "nullability_mismatches": sorted(nullability_mismatches),
        "server_default_mismatches": sorted(server_default_mismatches),
    }


def test_alembic_online_rehearsal_on_separate_ephemeral_database(staging_resources, record_property):
    """Exercise old heads, merge, downgrade, and re-upgrade without model DDL."""
    database = f"marketedgepros_test_{uuid.uuid4().hex}"
    assert database != staging_resources["db_name"]
    rehearsal_url = _rehearsal_url(staging_resources["pg_url"], database)
    admin_engine = create_engine(_rehearsal_url(staging_resources["pg_url"], "postgres"), isolation_level="AUTOCOMMIT")
    engine = None
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database}"'))
        engine = create_engine(rehearsal_url)
        config = _alembic_config(rehearsal_url)
        # ``env.py`` uses this exact caller-owned connection in testing mode;
        # it cannot fall back to application or host configuration.
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, MAIN_OLD_HEAD)
            assert _version_rows(engine) == {MAIN_OLD_HEAD}
            _insert_main_branch_sentinel(connection)
            command.upgrade(config, "head")
            assert _version_rows(engine) == {HEAD}
            _assert_head_invariants(engine, expected_users=1, expected_tenants=1)
            _assert_and_remove_main_branch_sentinel(connection)
            _assert_head_invariants(engine)

            command.downgrade(config, "base")
            _assert_clean_schema(engine)
            command.upgrade(config, "head")
            assert _version_rows(engine) == {HEAD}
            _assert_head_invariants(engine)

            command.downgrade(config, "base")
            command.upgrade(config, TOKEN_OLD_HEAD)
            assert _version_rows(engine) == {TOKEN_OLD_HEAD}
            # Model the nullable historical token root without stamping or a
            # production connection; the final additive revision must repair it.
            connection.execute(text("ALTER TABLE users ALTER COLUMN token_version DROP NOT NULL"))
            _insert_main_branch_sentinel(connection)
            connection.execute(text("UPDATE users SET token_version = NULL WHERE id = 900001"))
            connection.execute(text("""
                INSERT INTO users (id, email, password_hash, first_name, last_name,
                    is_active, is_verified, role, tenant_id, token_version)
                VALUES (900002, 'migration-version-sentinel@example.invalid', 'not-a-login-credential',
                    'Version', 'Sentinel', false, false, 'user', 900001, 7)
            """))
            connection.commit()
            assert connection.execute(text("SELECT token_version FROM users WHERE id = 900001")).scalar_one() is None
            connection.commit()
            command.upgrade(config, "head")
            assert _version_rows(engine) == {HEAD}
            _assert_head_invariants(engine, expected_users=2, expected_tenants=1)
            assert connection.execute(text("SELECT token_version FROM users WHERE id = 900002")).scalar_one() == 7
            connection.execute(text("DELETE FROM users WHERE id = 900002"))
            connection.commit()
            _assert_and_remove_main_branch_sentinel(connection)
            _assert_head_invariants(engine)
            parity = _model_parity_summary(engine)
            assert parity['missing_tables'] == []
            assert parity['missing_columns'] == []
            # Type and nullability deltas remain compatibility debt and are
            # intentionally reported rather than concealed by this revision.
            record_property("migration_model_parity", json.dumps(parity, sort_keys=True))
        config.attributes.pop("connection", None)
    finally:
        if engine is not None:
            engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database}"'))
        admin_engine.dispose()


def test_isolated_target_validator_rejects_non_synthetic_database_without_connecting(staging_resources):
    """The fail-closed URL/resource validator must reject an audit/production-like name."""
    from migrations.target_safety import IsolatedMigrationTargetError, validate_isolated_postgresql_target

    validate_isolated_postgresql_target(staging_resources["pg_url"])
    non_synthetic_url = str(make_url(staging_resources["pg_url"]).set(database="marketedgepros_production"))
    with pytest.raises(IsolatedMigrationTargetError, match="not a synthetic UUID database"):
        validate_isolated_postgresql_target(non_synthetic_url)


@pytest.mark.parametrize('case',['tcp_host','password','wrong_socket','extra_query','wrong_user','missing_metadata','external_interface','tcp_listener'])
def test_migration_target_guard_rejects_resource_overrides(staging_resources,case):
    from migrations.target_safety import IsolatedMigrationTargetError, validate_isolated_postgresql_target
    url=make_url(staging_resources['pg_url'])
    environment=dict(os.environ)
    overrides={}
    if case=='tcp_host':url=url.set(host='127.0.0.1')
    elif case=='password':url=url.set(password='synthetic-not-used')
    elif case=='wrong_socket':url=url.update_query_dict({'host':'/var/run/postgresql'})
    elif case=='extra_query':url=url.update_query_dict({'options':'-c search_path=public'})
    elif case=='wrong_user':url=url.set(username='unrelated-test-user')
    elif case=='missing_metadata':environment.pop('STAGING_RUN_ROOT')
    elif case=='external_interface':overrides['interface_names']=['lo','eth0']
    elif case=='tcp_listener':overrides['tcp_listener_present']=True
    with pytest.raises(IsolatedMigrationTargetError):
        validate_isolated_postgresql_target(url.render_as_string(hide_password=False),environment=environment,**overrides)
