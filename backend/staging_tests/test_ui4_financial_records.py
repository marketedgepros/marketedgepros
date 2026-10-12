"""UI-4 financial records against a separately migrated runner-owned PostgreSQL database."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta
from decimal import Decimal
import json
import uuid

import pytest
from alembic import command
from alembic.config import Config
from flask import Flask
import redis
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url


BACKEND = __import__("pathlib").Path(__file__).resolve().parents[1]


def _database_url(primary_url: str, database: str) -> str:
    return str(make_url(primary_url).set(database=database))


def _alembic_config(url: str) -> Config:
    config = Config(str(BACKEND / "migrations" / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


@contextmanager
def _migrated_database(staging_resources):
    """Upgrade a distinct synthetic database to the real migration head, then drop it."""
    database = f"marketedgepros_test_{uuid.uuid4().hex}"
    url = _database_url(staging_resources["pg_url"], database)
    admin = create_engine(_database_url(staging_resources["pg_url"], "postgres"), isolation_level="AUTOCOMMIT")
    engine = None
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database}"'))
        engine = create_engine(url)
        config = _alembic_config(url)
        with engine.connect() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
        config.attributes.pop("connection", None)
        yield url
    finally:
        if engine is not None:
            engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database}"'))
        admin.dispose()


@pytest.fixture
def ui4_financial_staging_app(staging_resources, monkeypatch):
    """A module-local real Flask host bound only to a real isolated migrated schema."""
    import src.database as database_module
    from src.database import db
    from src.routes.traders import traders_bp
    from src.routes.wallet import wallet_bp
    from src.models.user import User
    from src.utils.hierarchy_scoping import init_hierarchy_scoping

    with _migrated_database(staging_resources) as database_url:
        app = Flask("ui4-financial-migrated-staging")
        app.config.update(
            TESTING=True,
            EXPANDED_HIERARCHY_ENABLED=True,
            PLATFORM_ROOT_USER_ID=1,
            JWT_SECRET_KEY="staging-runner-public-synthetic-jwt",
            JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=10),
            JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=1),
            SQLALCHEMY_DATABASE_URI=database_url,
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            WTF_CSRF_ENABLED=False,
        )
        db.init_app(app)
        app.register_blueprint(traders_bp, url_prefix="/api/v1/traders")
        app.register_blueprint(wallet_bp, url_prefix="/api/v1/wallet")
        redis_client = redis.Redis(
            unix_socket_path=str(staging_resources["redis_socket"]), decode_responses=True,
            socket_timeout=2, socket_connect_timeout=2,
        )
        assert redis_client.ping() is True
        monkeypatch.setattr(database_module, "redis_client", redis_client)
        try:
            with app.app_context():
                init_hierarchy_scoping(db, User)
                _seed(app)
            yield app
        finally:
            with app.app_context():
                db.session.rollback()
                db.session.remove()
                db.engine.dispose()
            assert database_module.redis_client is redis_client
            redis_client.close()


def _user(identity, *, tenant_id, role, parent_id, tree_path, root=False):
    from src.models.user import User
    return User(
        id=identity, email=f"ui4-financial-pg-{identity}@example.invalid",
        password_hash="synthetic-not-a-credential", first_name="Synthetic", last_name=f"Postgres{identity}",
        tenant_id=tenant_id, role=role, parent_id=parent_id, tree_path=tree_path,
        level=0 if parent_id is None else 1, is_active=True, is_verified=True, can_create_same_role=root,
    )


def _seed(app):
    from src.database import db
    from src.models.agent import Agent
    from src.models.trading_program import Challenge
    from src.models.user import User
    from src.models.wallet import Transaction, Wallet
    from src.models.withdrawal import Withdrawal

    now = datetime(2026, 10, 12, 12, 0, 0)
    # Frozen migration DDL retains non-null fields not represented by the
    # current models.  Seed the synthetic compatibility rows through the real
    # migrated schema rather than changing production metadata or migrations.
    db.session.execute(text("""
        INSERT INTO tenants (id, name, slug, is_active)
        VALUES (1, 'Synthetic stage tenant', 'ui4-financial-pg-a', true),
               (2, 'Synthetic stage foreign', 'ui4-financial-pg-b', true)
    """))
    db.session.add_all([
        _user(1, tenant_id=1, role="supermaster", parent_id=None, tree_path="1", root=True),
        _user(2, tenant_id=1, role="master", parent_id=1, tree_path="1/2"),
        _user(3, tenant_id=1, role="trader", parent_id=2, tree_path="1/2/3"),
        _user(4, tenant_id=2, role="trader", parent_id=None, tree_path="4"),
    ])
    db.session.flush()
    # ``program_type`` is the unmapped, historical NOT NULL field from revision
    # 001; the remaining historical NOT NULL financial columns are explicit too.
    # ``type`` and ``rules`` are the later mapped compatibility columns used by
    # the live read join.  This is deliberately raw SQL against Alembic head.
    db.session.execute(text("""
        INSERT INTO trading_programs
            (id, tenant_id, name, program_type, type, account_size, price,
             profit_target, max_daily_loss, max_total_loss, profit_split,
             is_active, rules)
        VALUES
            (10, 1, 'Stage one', 'one_phase', 'one_phase', 10000.00, 1.00,
             10.00, 5.00, 10.00, 80.00, true, '{}'::jsonb),
            (11, 2, 'Stage two', 'one_phase', 'one_phase', 10000.00, 1.00,
             10.00, 5.00, 10.00, 80.00, true, '{}'::jsonb)
    """))
    db.session.add_all([
        Challenge(id=100, user_id=3, program_id=10, status="active",
                  initial_balance=Decimal("10000.00"), current_balance=Decimal("10000.00")),
        Challenge(id=101, user_id=3, program_id=11, status="active",
                  initial_balance=Decimal("10000.00"), current_balance=Decimal("10000.00")),
        Wallet(id=30, user_id=3, main_balance=Decimal("12.34"), commission_balance=Decimal("5.66"),
               bonus_balance=Decimal("1.00"), is_active=True, last_transaction_at=now, created_at=now),
        Agent(id=31, agent_code="UI4PG31", user_id=3),
        Agent(id=41, agent_code="UI4PG41", user_id=4),
    ])
    db.session.flush()
    db.session.add_all([
        Transaction(id=200, wallet_id=30, type="deposit", balance_type="main", amount=Decimal("12.34"),
                    balance_before=Decimal("0.00"), balance_after=Decimal("12.34"), created_at=now,
                    description="private transaction description", notes="private transaction notes"),
        Transaction(id=201, wallet_id=30, type="commission", balance_type="commission", amount=Decimal("5.66"),
                    balance_before=Decimal("0.00"), balance_after=Decimal("5.66"), created_at=now,
                    description="private commission description", notes="private commission notes"),
        Withdrawal(id=300, user_id=3, challenge_id=100, amount=Decimal("10.00"), fee=Decimal("1.00"),
                   net_amount=Decimal("9.00"), payment_method="bank_transfer", status="pending", created_at=now,
                   payment_details={"account": "private payment details"},
                   account_details={"account": "private account details"}, transaction_id="private transaction id",
                   notes="private withdrawal notes"),
        Withdrawal(id=301, agent_id=31, challenge_id=100, amount=Decimal("11.00"), fee=Decimal("0.00"),
                   net_amount=Decimal("11.00"), payment_method="paypal", status="completed", created_at=now,
                   completed_at=now, payment_details={"email": "private payment email"},
                   account_details={"email": "private account email"}, transaction_id="private agent transaction",
                   notes="private agent notes"),
        # Both owners disagree, so the row cannot be attributed to either one.
        Withdrawal(id=302, user_id=3, agent_id=41, amount=Decimal("12.00"), fee=Decimal("0.00"),
                   net_amount=Decimal("12.00"), payment_method="bank_transfer", status="pending", created_at=now,
                   notes="private ambiguous notes"),
        # A challenge on another tenant's program must not supply tenant scope.
        Withdrawal(id=303, user_id=3, challenge_id=101, amount=Decimal("13.00"), fee=Decimal("0.00"),
                   net_amount=Decimal("13.00"), payment_method="bank_transfer", status="pending", created_at=now,
                   notes="private foreign challenge notes"),
        Withdrawal(id=304, user_id=4, amount=Decimal("14.00"), fee=Decimal("0.00"),
                   net_amount=Decimal("14.00"), payment_method="bank_transfer", status="pending", created_at=now,
                   notes="private foreign owner notes"),
    ])
    db.session.commit()
    app.ui4_financial_tokens = {
        identity: db.session.get(User, identity).generate_access_token() for identity in (1, 2, 3, 4)
    }


def _headers(app, actor):
    return {"Authorization": "Bearer " + app.ui4_financial_tokens[actor]}


def _raw_financial_rows():
    """Capture actual persisted compatibility values without ORM serialization."""
    from src.database import db

    return {
        table: [dict(row) for row in db.session.execute(text(f"SELECT * FROM {table} ORDER BY id")).mappings()]
        for table in ("users", "trading_programs", "challenges", "agents", "wallets", "transactions", "withdrawals")
    }


def _assert_flags(payload, *, user_id):
    assert payload["owner_context"] == {"user_id": user_id, "tenant_id": 1}
    assert payload["balance_verification"] == "unverified_legacy"
    assert payload["payouts_enabled"] is False
    assert payload["available_for_payout"] is None
    assert payload["currency"] is None


def _assert_no_financial_resource_sql(statements):
    resource_names = ("wallets", "transactions", "withdrawals", "agents", "challenges", "trading_programs")
    statement_text = "\n".join(statements).lower()
    assert not any(name in statement_text for name in resource_names)


def test_ui4_financial_migrated_postgresql_routes_are_scoped_projected_and_timed(
    ui4_financial_staging_app, record_property,
):
    """Alembic-head PostgreSQL proves safe exact UI4 reads without changing raw rows."""
    from src.database import db

    statements = []
    with ui4_financial_staging_app.app_context():
        engine = db.engine
        assert engine.dialect.name == "postgresql"
        before_rows = _raw_financial_rows()
        assert {table: len(rows) for table, rows in before_rows.items()} == {
            "users": 4, "trading_programs": 2, "challenges": 2, "agents": 2,
            "wallets": 1, "transactions": 2, "withdrawals": 5,
        }
        assert {row["program_type"] for row in before_rows["trading_programs"]} == {"one_phase"}

    def observed(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements.append(statement.lower())

    event.listen(engine, "before_cursor_execute", observed)
    try:
        client = ui4_financial_staging_app.test_client()
        balance = client.get("/api/v1/wallet/balance", headers=_headers(ui4_financial_staging_app, 3))
        transactions = client.get("/api/v1/wallet/transactions?balance_type=main", headers=_headers(ui4_financial_staging_app, 3))
        mine = client.get("/api/v1/traders/withdrawals", headers=_headers(ui4_financial_staging_app, 3))
        admin = client.get("/api/v1/wallet/admin/withdrawals", headers=_headers(ui4_financial_staging_app, 2))
        post_start = len(statements)
        refused_post = client.post(
            "/api/v1/traders/withdrawals", data="{", content_type="application/json",
            headers=_headers(ui4_financial_staging_app, 3),
        )
        post_statements = statements[post_start:]
        invalid_start = len(statements)
        invalid = client.get(
            "/api/v1/wallet/transactions?page=01", headers=_headers(ui4_financial_staging_app, 3),
        )
        invalid_statements = statements[invalid_start:]
    finally:
        event.remove(engine, "before_cursor_execute", observed)

    assert balance.status_code == transactions.status_code == mine.status_code == admin.status_code == 200
    balance_payload = balance.get_json()
    _assert_flags(balance_payload, user_id=3)
    assert balance_payload == {
        "owner_context": {"user_id": 3, "tenant_id": 1},
        "balance_verification": "unverified_legacy", "payouts_enabled": False,
        "available_for_payout": None, "currency": None,
        "wallet": {
            "id": 30, "user_id": 3, "main_balance": "12.34", "commission_balance": "5.66",
            "bonus_balance": "1.00", "is_active": True, "last_transaction_at": "2026-10-12T12:00:00",
            "created_at": "2026-10-12T12:00:00",
        },
    }
    record_property("ui4_wallet_balance_payload", json.dumps(balance_payload, sort_keys=True))

    transaction_payload = transactions.get_json()
    _assert_flags(transaction_payload, user_id=3)
    assert transaction_payload["wallet_id"] == 30
    assert transaction_payload["pagination"] == {"page": 1, "per_page": 20, "total": 1, "pages": 1}
    assert transaction_payload["filters"] == {"balance_type": "main"}
    assert transaction_payload["transactions"] == [{
        "id": 200, "wallet_id": 30, "type": "deposit", "balance_type": "main", "amount": "12.34",
        "balance_before": "0.00", "balance_after": "12.34", "created_at": "2026-10-12T12:00:00",
    }]
    record_property("ui4_wallet_transactions_payload", json.dumps(transaction_payload, sort_keys=True))

    mine_payload = mine.get_json()
    _assert_flags(mine_payload, user_id=3)
    assert [row["id"] for row in mine_payload["withdrawals"]] == [301, 300]
    assert mine_payload["pagination"] == {"page": 1, "per_page": 20, "total": 2, "pages": 1}
    assert mine_payload["filters"] == {"status": None}
    assert all(row["user_id"] == 3 for row in mine_payload["withdrawals"])
    assert {302, 303, 304}.isdisjoint(row["id"] for row in mine_payload["withdrawals"])
    assert all(set(row) == {
        "id", "user_id", "amount", "fee", "net_amount", "payment_method", "status", "created_at",
        "approved_at", "processed_at", "completed_at",
    } for row in mine_payload["withdrawals"])
    record_property("ui4_withdrawals_payload", json.dumps(mine_payload, sort_keys=True))

    admin_payload = admin.get_json()
    _assert_flags(admin_payload, user_id=2)
    assert [row["id"] for row in admin_payload["withdrawals"]] == [301, 300]
    assert all(row["user_id"] == 3 for row in admin_payload["withdrawals"])
    assert admin_payload["pagination"] == {"page": 1, "per_page": 20, "total": 2, "pages": 1}
    assert admin_payload["filters"] == {"status": None}
    record_property("ui4_admin_withdrawals_payload", json.dumps(admin_payload, sort_keys=True))

    assert refused_post.status_code == 503
    assert refused_post.get_json() == {
        "error": "Wallet ledger is not configured", "code": "WALLET_LEDGER_NOT_CONFIGURED",
    }
    assert invalid.status_code == 400
    assert invalid.get_json() == {"error": "Invalid wallet request"}
    _assert_no_financial_resource_sql(post_statements)
    _assert_no_financial_resource_sql(invalid_statements)
    assert not any(statement.lstrip().startswith(("insert", "update", "delete")) for statement in statements)
    assert sum("set local statement_timeout = 1500" in statement for statement in statements) == 4
    encoded_payloads = json.dumps({
        "balance": balance_payload, "transactions": transaction_payload,
        "withdrawals": mine_payload, "admin": admin_payload,
    }, sort_keys=True)
    for private_value in (
        "private transaction description", "private transaction notes", "private payment details",
        "private account details", "private transaction id", "private withdrawal notes",
        "private payment email", "private account email", "private agent transaction", "private agent notes",
    ):
        assert private_value not in encoded_payloads

    with ui4_financial_staging_app.app_context():
        db.session.expire_all()
        after_rows = _raw_financial_rows()
    assert after_rows == before_rows
