"""PostgreSQL contract tests for immutable purchase-quote snapshot migration only."""
from __future__ import annotations

from contextlib import contextmanager
import io
from pathlib import Path
import re
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError


BACKEND = Path(__file__).resolve().parents[1]
PREVIOUS = "20261011_000005"
REVISION = "20261011_000006"
TABLE = "purchase_orders"
FUNCTION = "marketedgepros_purchase_orders_immutable"
TRIGGER = "purchase_orders_immutable"

EXPECTED_TYPES = {
    "id": "varchar(36)",
    "user_id": "integer",
    "tenant_id": "integer",
    "program_id": "integer",
    "idempotency_key": "varchar(128)",
    "request_hash": "varchar(64)",
    "snapshot_hash": "varchar(64)",
    "snapshot_json": "text",
    "amount_minor": "bigint",
    "currency": "varchar(3)",
    "state": "varchar(20)",
    "created_at": "timestamp without time zone",
}

EXPECTED_CHECKS = {
    "ck_purchase_orders_amount": "amount_minor > 0 AND amount_minor <= 9999999999",
    "ck_purchase_orders_currency": "currency = 'USD'",
    "ck_purchase_orders_state": "state = 'quoted'",
    "ck_purchase_orders_hash_length": "length(request_hash) = 64 AND length(snapshot_hash) = 64",
}


@contextmanager
def purchase_order_database(resources):
    """Create a fresh pre-000006 graph in a runner-owned PostgreSQL database."""
    database = "marketedgepros_test_" + uuid4().hex
    url = make_url(resources["pg_url"]).set(database=database)
    admin = create_engine(make_url(resources["pg_url"]).set(database="postgres"), isolation_level="AUTOCOMMIT")
    engine = None
    config = None
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
    finally:
        if config is not None:
            config.attributes.pop("connection", None)
        if engine is not None:
            engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database}"'))
        admin.dispose()


def upgrade_orders(connection, config) -> None:
    command.upgrade(config, REVISION)
    assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == REVISION


def _normalised_type(type_) -> str:
    rendered = str(type_.compile(dialect=postgresql.dialect())).lower()
    return " ".join(rendered.replace("character varying", "varchar").split())


def _normalised_check(expression: str) -> str:
    normalised = "".join(str(expression).lower().split())
    normalised = re.sub(r"'([0-9]+)'::bigint", r"\1", normalised)
    return (
        normalised
        .replace("::character varying", "")
        .replace("::text", "")
        .replace('"', "")
        .replace("(", "")
        .replace(")", "")
    )


@contextmanager
def record_schema_ddl(connection):
    """Capture migration DDL, excluding setup statements executed before the context."""
    statements: list[str] = []

    def capture(conn, cursor, statement, parameters, execution_context, executemany):
        if statement.lstrip().upper().startswith(("CREATE ", "ALTER ", "DROP ")):
            statements.append(statement)

    event.listen(connection, "before_cursor_execute", capture)
    try:
        yield statements
    finally:
        event.remove(connection, "before_cursor_execute", capture)


def insert_quote_parents(connection, *, users=(991001, 991002)) -> None:
    """Insert only disabled synthetic parents required by the frozen quote FKs."""
    connection.execute(text("""
        INSERT INTO tenants (id, name, slug, domain, is_active)
        VALUES (991001, 'Order Schema Tenant', 'order-schema-tenant',
                'order-schema.example.invalid', false)
    """))
    for user_id in users:
        connection.execute(text("""
            INSERT INTO users (
                id, email, password_hash, first_name, last_name,
                is_active, is_verified, role, tenant_id, token_version
            ) VALUES (
                :id, :email, 'not-a-login-credential', 'Order', 'Schema',
                false, false, 'trader', 991001, 0
            )
        """), {"id": user_id, "email": f"order-schema-{user_id}@example.invalid"})
    connection.execute(text("""
        INSERT INTO trading_programs (
            id, tenant_id, name, description, program_type, account_size, price,
            profit_target, max_daily_loss, max_total_loss, profit_split, is_active
        ) VALUES (
            991001, 991001, 'Order Schema Program', 'Synthetic quote target only',
            'synthetic', 100000.00, 499.99, 10.00, 5.00, 10.00, 80, false
        )
    """))
    connection.commit()


def quote_values(*, identifier: str, user_id: int = 991001, idempotency_key: str = "quote-key",
                 amount_minor: int = 49999, currency: str = "USD", state: str = "quoted",
                 request_hash: str | None = None, snapshot_hash: str | None = None) -> dict[str, object]:
    return {
        "id": identifier,
        "user_id": user_id,
        "tenant_id": 991001,
        "program_id": 991001,
        "idempotency_key": idempotency_key,
        "request_hash": request_hash or "a" * 64,
        "snapshot_hash": snapshot_hash or "b" * 64,
        "snapshot_json": '{"synthetic": true, "kind": "quote"}',
        "amount_minor": amount_minor,
        "currency": currency,
        "state": state,
    }


def insert_quote(connection, **kwargs) -> None:
    connection.execute(text("""
        INSERT INTO purchase_orders (
            id, user_id, tenant_id, program_id, idempotency_key, request_hash,
            snapshot_hash, snapshot_json, amount_minor, currency, state, created_at
        ) VALUES (
            :id, :user_id, :tenant_id, :program_id, :idempotency_key, :request_hash,
            :snapshot_hash, :snapshot_json, :amount_minor, :currency, :state, CURRENT_TIMESTAMP
        )
    """), quote_values(**kwargs))


def test_purchase_order_migration_is_frozen_quote_only_schema(staging_resources):
    """The migration adds one table and exact canonical database objects, not payment state."""
    source = (BACKEND / "migrations/versions/20261011_000006_purchase_orders.py").read_text(encoding="utf-8")
    assert "src.models" not in source
    assert "create_all" not in source
    assert "IF NOT EXISTS" not in source

    with purchase_order_database(staging_resources) as (connection, config):
        before = set(inspect(connection).get_table_names(schema="public"))
        upgrade_orders(connection, config)
        inspector = inspect(connection)
        assert set(inspector.get_table_names(schema="public")) - before == {TABLE}

        columns = {column["name"]: column for column in inspector.get_columns(TABLE, schema="public")}
        assert set(columns) == set(EXPECTED_TYPES)
        for name, expected_type in EXPECTED_TYPES.items():
            assert _normalised_type(columns[name]["type"]) == expected_type
            assert columns[name]["nullable"] is False
            assert columns[name]["default"] is None

        primary_key = inspector.get_pk_constraint(TABLE, schema="public")
        assert primary_key["constrained_columns"] == ["id"]
        assert primary_key["name"] == "purchase_orders_pkey"
        foreign_keys = {foreign_key["name"]: foreign_key for foreign_key in inspector.get_foreign_keys(TABLE, schema="public")}
        assert set(foreign_keys) == {
            "fk_purchase_orders_user_id_users",
            "fk_purchase_orders_tenant_id_tenants",
            "fk_purchase_orders_program_id_trading_programs",
        }
        assert foreign_keys["fk_purchase_orders_user_id_users"]["constrained_columns"] == ["user_id"]
        assert foreign_keys["fk_purchase_orders_user_id_users"]["referred_table"] == "users"
        assert foreign_keys["fk_purchase_orders_tenant_id_tenants"]["constrained_columns"] == ["tenant_id"]
        assert foreign_keys["fk_purchase_orders_tenant_id_tenants"]["referred_table"] == "tenants"
        assert foreign_keys["fk_purchase_orders_program_id_trading_programs"]["constrained_columns"] == ["program_id"]
        assert foreign_keys["fk_purchase_orders_program_id_trading_programs"]["referred_table"] == "trading_programs"
        for foreign_key in foreign_keys.values():
            assert foreign_key["referred_columns"] == ["id"]
            assert foreign_key["referred_schema"] in (None, "public")
            assert not foreign_key.get("options")

        uniques = {item["name"]: item["column_names"] for item in inspector.get_unique_constraints(TABLE, schema="public")}
        assert uniques == {"uq_purchase_orders_user_key": ["user_id", "idempotency_key"]}
        checks = {item["name"]: item["sqltext"] for item in inspector.get_check_constraints(TABLE, schema="public")}
        assert set(checks) == set(EXPECTED_CHECKS)
        for name, expression in EXPECTED_CHECKS.items():
            assert _normalised_check(checks[name]) == _normalised_check(expression)

        indexes = {
            item["name"]: (item["column_names"], item["unique"])
            for item in inspector.get_indexes(TABLE, schema="public")
            if not item.get("duplicates_constraint")
        }
        assert indexes == {
            "ix_purchase_orders_user_created": (["user_id", "created_at"], False),
            "ix_purchase_orders_tenant": (["tenant_id"], False),
        }
        function = connection.execute(text("""
            SELECT procedure.prorettype::regtype::text, language.lanname, procedure.prosrc
            FROM pg_proc AS procedure
            JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace
            JOIN pg_language AS language ON language.oid = procedure.prolang
            WHERE namespace.nspname = 'public'
              AND procedure.proname = :function_name
        """), {"function_name": FUNCTION}).one()
        assert function[0:2] == ("trigger", "plpgsql")
        assert "RAISE EXCEPTION 'purchase_orders are immutable'" in function[2]
        trigger = connection.execute(text("""
            SELECT trigger.tgtype, trigger.tgenabled, trigger.tgqual IS NULL, procedure.proname
            FROM pg_trigger AS trigger
            JOIN pg_class AS relation ON relation.oid = trigger.tgrelid
            JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
            JOIN pg_proc AS procedure ON procedure.oid = trigger.tgfoid
            WHERE namespace.nspname = 'public'
              AND relation.relname = 'purchase_orders'
              AND trigger.tgname = 'purchase_orders_immutable'
              AND NOT trigger.tgisinternal
        """)).one()
        assert tuple(trigger) == (27, "O", True, FUNCTION)


def test_purchase_order_insert_constraints_and_per_user_idempotency(staging_resources):
    """Quotes can be recorded, but invalid snapshots and duplicate user keys are rejected by PostgreSQL."""
    with purchase_order_database(staging_resources) as (connection, config):
        insert_quote_parents(connection)
        upgrade_orders(connection, config)

        insert_quote(connection, identifier="00000000-0000-0000-0000-000000000001", idempotency_key="shared-key")
        insert_quote(
            connection, identifier="00000000-0000-0000-0000-000000000002",
            user_id=991002, idempotency_key="shared-key", amount_minor=9999999999,
        )
        connection.commit()
        assert connection.execute(text("SELECT count(*) FROM purchase_orders")).scalar_one() == 2

        with pytest.raises(IntegrityError, match="uq_purchase_orders_user_key"):
            insert_quote(
                connection, identifier="00000000-0000-0000-0000-000000000003",
                idempotency_key="shared-key",
            )
        connection.rollback()

        invalid_cases = (
            ("00000000-0000-0000-0000-000000000004", {"amount_minor": 0}, "ck_purchase_orders_amount"),
            ("00000000-0000-0000-0000-000000000005", {"amount_minor": 10000000000}, "ck_purchase_orders_amount"),
            ("00000000-0000-0000-0000-000000000006", {"currency": "EUR"}, "ck_purchase_orders_currency"),
            ("00000000-0000-0000-0000-000000000007", {"state": "pending"}, "ck_purchase_orders_state"),
            ("00000000-0000-0000-0000-000000000008", {"request_hash": "a" * 63}, "ck_purchase_orders_hash_length"),
            ("00000000-0000-0000-0000-000000000009", {"snapshot_hash": "b" * 63}, "ck_purchase_orders_hash_length"),
        )
        for identifier, overrides, expected_constraint in invalid_cases:
            with pytest.raises(IntegrityError, match=expected_constraint):
                insert_quote(connection, identifier=identifier, idempotency_key="invalid-" + identifier[-1], **overrides)
            connection.rollback()
        assert connection.execute(text("SELECT count(*) FROM purchase_orders")).scalar_one() == 2


def test_postgresql_trigger_blocks_direct_and_bulk_quote_mutation(staging_resources):
    """Raw SQL cannot bypass mapper events: both UPDATE and DELETE fail before any row changes."""
    with purchase_order_database(staging_resources) as (connection, config):
        insert_quote_parents(connection, users=(991001,))
        upgrade_orders(connection, config)
        insert_quote(connection, identifier="00000000-0000-0000-0000-000000000010", idempotency_key="bulk-one")
        insert_quote(connection, identifier="00000000-0000-0000-0000-000000000011", idempotency_key="bulk-two")
        connection.commit()

        with pytest.raises(DBAPIError, match="purchase_orders are immutable"):
            connection.execute(text("""
                UPDATE purchase_orders
                SET snapshot_json = '{"synthetic": false}'
                WHERE user_id = 991001
            """))
        connection.rollback()
        with pytest.raises(DBAPIError, match="purchase_orders are immutable"):
            connection.execute(text("DELETE FROM purchase_orders WHERE user_id = 991001"))
        connection.rollback()

        rows = connection.execute(text("""
            SELECT id, snapshot_json, state FROM purchase_orders ORDER BY id
        """)).all()
        assert rows == [
            ("00000000-0000-0000-0000-000000000010", '{"synthetic": true, "kind": "quote"}', "quoted"),
            ("00000000-0000-0000-0000-000000000011", '{"synthetic": true, "kind": "quote"}', "quoted"),
        ]


def test_purchase_order_upgrade_and_empty_downgrade_preserve_legacy_parent_data(staging_resources):
    """The migration neither infers nor changes legacy user/tenant/program values in either direction."""
    with purchase_order_database(staging_resources) as (connection, config):
        insert_quote_parents(connection, users=(991001,))
        original = connection.execute(text("""
            SELECT tenant.name, account.email, program.name, program.price
            FROM tenants AS tenant
            JOIN users AS account ON account.tenant_id = tenant.id
            JOIN trading_programs AS program ON program.tenant_id = tenant.id
            WHERE tenant.id = 991001 AND account.id = 991001 AND program.id = 991001
        """)).one()
        upgrade_orders(connection, config)
        assert connection.execute(text("""
            SELECT tenant.name, account.email, program.name, program.price
            FROM tenants AS tenant
            JOIN users AS account ON account.tenant_id = tenant.id
            JOIN trading_programs AS program ON program.tenant_id = tenant.id
            WHERE tenant.id = 991001 AND account.id = 991001 AND program.id = 991001
        """)).one() == original

        command.downgrade(config, PREVIOUS)
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == PREVIOUS
        assert TABLE not in set(inspect(connection).get_table_names(schema="public"))
        assert connection.execute(text("""
            SELECT tenant.name, account.email, program.name, program.price
            FROM tenants AS tenant
            JOIN users AS account ON account.tenant_id = tenant.id
            JOIN trading_programs AS program ON program.tenant_id = tenant.id
            WHERE tenant.id = 991001 AND account.id = 991001 AND program.id = 991001
        """)).one() == original


def test_purchase_order_upgrade_refuses_foreign_relation_or_function_collision_before_ddl(staging_resources):
    """Indexes and overloaded function names are globally checked before the table is created."""
    collisions = (
        "CREATE TABLE ix_purchase_orders_tenant (id integer PRIMARY KEY)",
        """CREATE FUNCTION public.marketedgepros_purchase_orders_immutable(ignored integer)
           RETURNS integer LANGUAGE sql AS 'SELECT ignored'""",
    )
    for collision in collisions:
        with purchase_order_database(staging_resources) as (connection, config):
            connection.execute(text(collision))
            connection.commit()
            with record_schema_ddl(connection) as emitted:
                with pytest.raises(RuntimeError, match="schema collision before DDL"):
                    upgrade_orders(connection, config)
            assert emitted == []
            assert TABLE not in set(inspect(connection).get_table_names(schema="public"))
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == PREVIOUS


@pytest.mark.parametrize("alterations", (
    ("DROP TRIGGER purchase_orders_immutable ON purchase_orders",),
    ("""CREATE OR REPLACE FUNCTION public.marketedgepros_purchase_orders_immutable()
        RETURNS trigger LANGUAGE plpgsql AS $function$
        BEGIN RAISE EXCEPTION 'changed ownership'; END;
        $function$""",),
    ("DROP INDEX ix_purchase_orders_tenant",),
    ("ALTER TABLE purchase_orders DROP CONSTRAINT fk_purchase_orders_user_id_users",),
    ("ALTER TABLE purchase_orders DROP CONSTRAINT ck_purchase_orders_state",),
    (
        "DROP TRIGGER purchase_orders_immutable ON purchase_orders",
        """CREATE TRIGGER purchase_orders_immutable
           BEFORE UPDATE OR DELETE ON public.purchase_orders
           FOR EACH ROW WHEN (false)
           EXECUTE FUNCTION public.marketedgepros_purchase_orders_immutable()""",
    ),
))
def test_purchase_order_downgrade_refuses_missing_or_changed_owned_metadata_before_ddl(staging_resources, alterations):
    """No trigger/function/index/table cleanup begins if another migration changed ownership."""
    with purchase_order_database(staging_resources) as (connection, config):
        upgrade_orders(connection, config)
        for alteration in alterations:
            connection.execute(text(alteration))
        connection.commit()
        with record_schema_ddl(connection) as emitted:
            with pytest.raises(RuntimeError, match="changed ownership metadata before DDL"):
                command.downgrade(config, PREVIOUS)
        assert emitted == []
        assert TABLE in set(inspect(connection).get_table_names(schema="public"))
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == REVISION


def test_purchase_order_populated_downgrade_refuses_before_trigger_or_table_drop(staging_resources):
    """An immutable quote blocks downgrade and remains present after the failed data gate."""
    with purchase_order_database(staging_resources) as (connection, config):
        insert_quote_parents(connection, users=(991001,))
        upgrade_orders(connection, config)
        insert_quote(connection, identifier="00000000-0000-0000-0000-000000000012", idempotency_key="preserve")
        connection.commit()
        with record_schema_ddl(connection) as emitted:
            with pytest.raises(RuntimeError, match="refuses to delete immutable quote snapshots"):
                command.downgrade(config, PREVIOUS)
        assert emitted == []
        assert connection.execute(text("SELECT count(*) FROM purchase_orders")).scalar_one() == 1
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == REVISION


def test_purchase_order_offline_downgrade_emits_no_unverified_drop_sql(staging_resources, monkeypatch):
    """Offline SQL generation cannot inspect quotes or ownership, so it must stop before DROP."""
    buffer = io.StringIO()
    config = Config(str(BACKEND / "migrations/alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", staging_resources["pg_url"].replace("%", "%%"))
    config.output_buffer = buffer
    monkeypatch.setenv("TEST_DATABASE_URL", staging_resources["pg_url"])
    with pytest.raises(RuntimeError, match="offline downgrade is unsupported"):
        command.downgrade(config, f"{REVISION}:{PREVIOUS}", sql=True)
    assert "DROP" not in buffer.getvalue().upper()


@pytest.mark.parametrize('index_ddl', [
    'CREATE INDEX foreign_order_expression ON purchase_orders ((lower(currency)))',
    'CREATE INDEX foreign_order_partial ON purchase_orders (amount_minor) WHERE amount_minor > 100',
])
def test_purchase_order_downgrade_refuses_foreign_filtered_or_expression_indexes_before_ddl(staging_resources, index_ddl):
    with purchase_order_database(staging_resources) as (connection, config):
        upgrade_orders(connection, config)
        connection.execute(text(index_ddl))
        connection.commit()
        with record_schema_ddl(connection) as emitted:
            with pytest.raises(RuntimeError, match='changed ownership metadata before DDL'):
                command.downgrade(config, PREVIOUS)
        assert emitted == []
        assert TABLE in set(inspect(connection).get_table_names(schema='public'))
