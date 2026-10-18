"""Full active-model inventory and revision-000003 schema completion tests.

These tests only run through ``scripts/run_staging_integration.py``.  They use
runner-created PostgreSQL databases over its private Unix socket and never invoke an
application factory or provider service.
"""
from __future__ import annotations

import ast
from contextlib import contextmanager
import io
from pathlib import Path
import uuid

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url


BACKEND = Path(__file__).resolve().parents[1]
REVISION = "20261011_000003"
PREVIOUS_REVISION = "20261011_000002"

# This literal is intentionally independent of the migration's OWNED_TABLES.  It
# turns an omitted source declaration, model module, or migration table into a test
# failure instead of allowing both sides to drift together.
EXPECTED_DECLARED_TABLES = frozenset({
    "account_scaling", "affiliate_commissions", "affiliate_links", "affiliate_payouts",
    "affiliate_referrals", "affiliate_settings", "agents", "blog_posts", "challenges",
    "commissions", "course_enrollments", "email_queue", "email_verification_tokens",
    "faqs", "lead_activities", "lead_notes", "leads", "monitoring_alerts",
    "monitoring_events", "mt5_accounts", "mt5_positions", "mt5_trades",
    "notification_preferences", "notifications", "password_reset_tokens",
    "payment_approval_requests", "payment_methods", "payments", "payout_requests",
    "program_addons", "referrals", "roles", "scaling_tiers", "support_articles",
    "support_tickets", "tenants", "ticket_messages", "token_blacklist", "trades",
    "trading_programs", "transactions", "users", "verification_attempts",
    "violation_logs", "wallets", "withdrawals",
})

# These are model declarations whose table already exists at 000002.  ``programs``
# is intentionally absent: it is a legacy table created by 005 and only a FK target
# for affiliate_referrals, not an active model declaration.
PREEXISTING_MODEL_TABLES = frozenset({
    "account_scaling", "challenges", "email_verification_tokens", "password_reset_tokens",
    "payments", "program_addons", "scaling_tiers", "tenants", "token_blacklist",
    "trades", "trading_programs", "users",
})
EXPECTED_NEW_TABLES = EXPECTED_DECLARED_TABLES - PREEXISTING_MODEL_TABLES
assert len(EXPECTED_DECLARED_TABLES) == 46
assert len(EXPECTED_NEW_TABLES) == 34
CURRENT_DECLARED_TABLES = EXPECTED_DECLARED_TABLES | {
    'purchase_orders', 'payment_event_receipts', 'settlement_journals', 'settlement_entries',
    'trading_rule_snapshots', 'trading_provision_commands', 'trading_event_inbox',
    'affiliate_identity_evidence', 'affiliate_order_attributions',
    'affiliate_commission_awards', 'affiliate_payout_commands',
    'checkout_intents', 'nowpayments_payment_bindings', 'nowpayments_observations',
    'nowpayments_verified_receipts', 'nowpayments_settlement_journals',
    'nowpayments_settlement_entries', 'order_entitlement_grants',
}


def _alembic_config(url: str) -> Config:
    config = Config(str(BACKEND / "migrations" / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    # ConfigParser treats percent-encoded Unix socket paths specially.
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def _database_url(primary_url: str, database: str) -> str:
    return str(make_url(primary_url).set(database=database))


@contextmanager
def _isolated_database(staging_resources):
    """Create one synthetic UUID database inside the runner-owned cluster."""
    database = f"marketedgepros_test_{uuid.uuid4().hex}"
    url = _database_url(staging_resources["pg_url"], database)
    admin_engine = create_engine(_database_url(staging_resources["pg_url"], "postgres"), isolation_level="AUTOCOMMIT")
    engine = None
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database}"'))
        engine = create_engine(url)
        yield engine, _alembic_config(url)
    finally:
        if engine is not None:
            engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database}"'))
        admin_engine.dispose()


def _run_upgrade(config: Config, engine, revision: str) -> None:
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, revision)
    config.attributes.pop("connection", None)


def _run_downgrade(config: Config, engine, revision: str) -> None:
    with engine.connect() as connection:
        config.attributes["connection"] = connection
        command.downgrade(config, revision)
    config.attributes.pop("connection", None)


def _migration_owned_tables() -> tuple[str, ...]:
    source = BACKEND / "migrations" / "versions" / "20261011_000003_add_missing_model_tables.py"
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "OWNED_TABLES" for target in node.targets
        ):
            tables = ast.literal_eval(node.value)
            assert isinstance(tables, tuple)
            return tuple(tables)
    raise AssertionError("000003 must define OWNED_TABLES as a static tuple")


def _migration_created_tables() -> set[str]:
    source = BACKEND / "migrations" / "versions" / "20261011_000003_add_missing_model_tables.py"
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    return {
        ast.literal_eval(call.args[0])
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "create_table"
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
    }


def _normalized_type(type_) -> str:
    rendered = str(type_.compile(dialect=postgresql.dialect())).lower()
    return " ".join(rendered.replace("character varying", "varchar").split())


def _assert_table_matches_model(inspector, model_table) -> None:
    actual_columns = {column["name"]: column for column in inspector.get_columns(model_table.name)}
    assert set(actual_columns) == {column.name for column in model_table.columns}
    assert tuple(inspector.get_pk_constraint(model_table.name)["constrained_columns"]) == tuple(
        column.name for column in model_table.primary_key.columns
    )
    for model_column in model_table.columns:
        actual = actual_columns[model_column.name]
        assert actual["nullable"] is model_column.nullable, f"{model_table.name}.{model_column.name} nullability"
        assert _normalized_type(actual["type"]) == _normalized_type(model_column.type), (
            f"{model_table.name}.{model_column.name} type "
            f"{_normalized_type(actual['type'])} != {_normalized_type(model_column.type)}"
        )
        # PostgreSQL supplies an implicit serial/identity expression for integer
        # PKs.  Apart from that implementation detail, the snapshot may only
        # expose an explicit model server_default (there are none in this scope).
        if not model_column.primary_key:
            if model_column.server_default is None:
                assert actual["default"] is None, f"{model_table.name}.{model_column.name} unexpected server default"
            else:
                expected_default = str(model_column.server_default.arg).replace(" ", "")
                actual_default = (actual["default"] or "").replace(" ", "")
                assert expected_default in actual_default, f"{model_table.name}.{model_column.name} server default"

    expected_fks = {
        (tuple(element.parent.name for element in foreign_key.elements),
         foreign_key.elements[0].target_fullname.rsplit(".", 1)[0],
         tuple(element.target_fullname.rsplit(".", 1)[1] for element in foreign_key.elements),
         foreign_key.elements[0].ondelete)
        for foreign_key in model_table.foreign_key_constraints
    }
    actual_fks = {
        (tuple(foreign_key["constrained_columns"]), foreign_key["referred_table"],
         tuple(foreign_key["referred_columns"]), foreign_key.get("options", {}).get("ondelete"))
        for foreign_key in inspector.get_foreign_keys(model_table.name)
    }
    assert actual_fks == expected_fks, model_table.name

    expected_indexes = {
        (index.name, tuple(column.name for column in index.columns), index.unique)
        for index in model_table.indexes
    }
    actual_indexes = {
        (index["name"], tuple(index["column_names"]), index["unique"])
        for index in inspector.get_indexes(model_table.name)
        # PostgreSQL exposes the implementation index of a UNIQUE constraint in
        # get_indexes() and marks it with this key.  Constraints are compared
        # below; only standalone model indexes belong in this set.
        if not index.get("duplicates_constraint")
    }
    assert actual_indexes == expected_indexes, model_table.name

    expected_unique = {
        tuple(constraint.columns.keys())
        for constraint in model_table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    actual_unique = {tuple(constraint["column_names"]) for constraint in inspector.get_unique_constraints(model_table.name)}
    assert actual_unique == expected_unique, model_table.name

    expected_checks = [
        constraint for constraint in model_table.constraints
        if constraint.__class__.__name__ == "CheckConstraint"
    ]
    assert not expected_checks, f"{model_table.name} requires explicit check-constraint snapshot review"
    assert not inspector.get_check_constraints(model_table.name), f"{model_table.name} unexpected check constraint"


def test_complete_active_model_inventory_imports_every_source_module(staging_resources):
    """No individual blueprint import may hide a declared table from metadata."""
    from src.schema_inventory import load_complete_model_inventory

    inventory = load_complete_model_inventory()
    assert len(inventory.modules) == 31
    assert set(inventory.declared_tables) == CURRENT_DECLARED_TABLES
    assert set(inventory.metadata_tables) == CURRENT_DECLARED_TABLES
    assert dict(inventory.external_foreign_key_targets) == {"affiliate_referrals": ("programs",)}


def test_complete_inventory_refuses_unmarked_process_before_dynamic_import(monkeypatch):
    """The public loader cannot be used as a convenient production metadata import."""
    import src.schema_inventory as schema_inventory

    monkeypatch.delenv("FLASK_TESTING", raising=False)
    monkeypatch.delenv("MARKETEDGEPROS_STAGING_INNER", raising=False)

    def _unexpected_import(_module):
        raise AssertionError("model import must not be attempted before safety validation")

    monkeypatch.setattr(schema_inventory.importlib, "import_module", _unexpected_import)
    with pytest.raises(schema_inventory.SchemaInventoryError, match="isolated staging runner"):
        schema_inventory.load_complete_model_inventory()


def test_000003_is_static_exact_missing_table_snapshot():
    """The migration itself has explicit table DDL for exactly the static gap."""
    source = (BACKEND / "migrations" / "versions" / "20261011_000003_add_missing_model_tables.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    assert _migration_owned_tables() == tuple(sorted(EXPECTED_NEW_TABLES))
    assert _migration_created_tables() == EXPECTED_NEW_TABLES
    assert "src.models" not in source
    assert not any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "create_all"
        for call in ast.walk(tree)
    )
    assert "IF NOT EXISTS" not in source


def test_000003_fresh_schema_matches_every_new_active_model_table(staging_resources):
    """Exercise actual PostgreSQL DDL, including JSONB, FKs, unique constraints, and indexes."""
    from src.schema_inventory import load_complete_model_inventory

    inventory = load_complete_model_inventory()
    with _isolated_database(staging_resources) as (engine, config):
        _run_upgrade(config, engine, REVISION)
        inspector = inspect(engine)
        actual_tables = set(inspector.get_table_names())
        assert EXPECTED_NEW_TABLES.issubset(actual_tables)
        for table_name in sorted(EXPECTED_NEW_TABLES):
            _assert_table_matches_model(inspector, __import__("src.database", fromlist=["db"]).db.metadata.tables[table_name])


def test_000003_upgrade_refuses_any_existing_owned_table_before_ddl(staging_resources):
    """A historical collision cannot cause partial table creation or silent adoption."""
    with _isolated_database(staging_resources) as (engine, config):
        _run_upgrade(config, engine, PREVIOUS_REVISION)
        with engine.begin() as connection:
            connection.execute(text('CREATE TABLE roles (id integer PRIMARY KEY)'))
        with pytest.raises(RuntimeError, match="refuses to adopt existing model tables.*roles"):
            _run_upgrade(config, engine, REVISION)
        tables = set(inspect(engine).get_table_names())
        assert "roles" in tables
        assert not (EXPECTED_NEW_TABLES - {"roles"}) & tables


def test_000003_downgrade_refuses_nonempty_owned_table_before_any_drop(staging_resources):
    """Downgrade never deletes support/financial-domain rows as a side effect."""
    with _isolated_database(staging_resources) as (engine, config):
        _run_upgrade(config, engine, REVISION)
        with engine.begin() as connection:
            # This table has no business transaction semantics and accepts its PK alone.
            connection.execute(text("INSERT INTO affiliate_settings (id) VALUES (1)"))
        with pytest.raises(RuntimeError, match="downgrade refuses to delete rows.*affiliate_settings"):
            _run_downgrade(config, engine, PREVIOUS_REVISION)
        tables = set(inspect(engine).get_table_names())
        assert EXPECTED_NEW_TABLES.issubset(tables)
        with engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM affiliate_settings")).scalar_one() == 1


def test_000003_offline_downgrade_refuses_to_emit_unverified_drop_sql(staging_resources, monkeypatch):
    """Offline mode cannot inspect table ownership/rows, so it must stop before 000003 drops."""
    buffer = io.StringIO()
    config = _alembic_config(staging_resources["pg_url"])
    config.output_buffer = buffer
    monkeypatch.setenv("TEST_DATABASE_URL", staging_resources["pg_url"])
    with pytest.raises(RuntimeError, match="offline downgrade is unsupported"):
        command.downgrade(config, "20261011_000004:20261011_000002", sql=True)
    # Revision 000004 may have emitted its guarded column reversal before 000003
    # rejects the range, but unsafe model-table drops were never emitted.
    assert "DROP TABLE" not in buffer.getvalue()


@pytest.mark.parametrize('case',['missing_runner','missing_target','invalid_target'])
def test_complete_model_import_refuses_before_imports_without_valid_isolation(staging_resources,monkeypatch,case):
    from src import schema_inventory
    attempted=[]
    monkeypatch.setattr(schema_inventory.importlib,'import_module',lambda name: attempted.append(name))
    if case=='missing_runner':
        monkeypatch.delenv('MARKETEDGEPROS_STAGING_INNER')
    elif case=='missing_target':
        monkeypatch.delenv('STAGING_PG_URL')
    else:
        invalid=make_url(staging_resources['pg_url']).set(database='production_unrelated')
        monkeypatch.setenv('STAGING_PG_URL',str(invalid))
    with pytest.raises(schema_inventory.SchemaInventoryError):
        schema_inventory.load_complete_model_inventory()
    assert attempted==[]
