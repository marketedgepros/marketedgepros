"""PostgreSQL staging contract for the UI-4 admin challenge closure boundary.

Run only through backend/scripts/run_staging_integration.py. The runner inventories
real migrations before provisioning its isolated Unix-socket PostgreSQL instance.
"""
from datetime import datetime, timedelta
from decimal import Decimal

from flask import Flask
from sqlalchemy import event, update
from werkzeug.datastructures import MultiDict


def test_ui4_closure_challenges_postgresql_scope_snapshot_timeout_and_exact_decimals(staging_resources):
    from src.database import db
    from src.models.mt5_models import MT5Account
    from src.models.tenant import Tenant
    from src.models.token_blacklist import TokenBlacklist
    from src.models.trading_program import Challenge, TradingProgram
    from src.models.user import User
    from src.services.admin_closure_challenges import AdminClosureChallengesService
    from src.utils.hierarchy_scoping import init_hierarchy_scoping

    app = Flask("ui4-closure-challenges-postgresql")
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI=staging_resources["pg_url"],
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY="ui4-closure-challenges-staging-synthetic-key",
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=10),
        PLATFORM_ROOT_USER_ID=1,
        EXPANDED_HIERARCHY_ENABLED=True,
    )
    db.init_app(app)
    init_hierarchy_scoping(db, User)
    tables = [
        Tenant.__table__, User.__table__, TokenBlacklist.__table__, TradingProgram.__table__,
        Challenge.__table__, MT5Account.__table__,
    ]
    instant = datetime(2026, 10, 12, 12, 0, 0)
    with app.app_context():
        assert db.engine.dialect.name == "postgresql"
        db.metadata.create_all(bind=db.engine, tables=[MT5Account.__table__])
        db.session.add_all([
            Tenant(id=1, name="PG closure tenant", subdomain="ui4-closure-challenges-pg", status="active"),
            User(
                id=1, email="pg-closure-root@example.invalid", password_hash="x",
                first_name="Root", last_name="One", role="supermaster", tenant_id=1,
                parent_id=None, tree_path="1", level=0, can_create_same_role=True,
                is_active=True, is_verified=True,
            ),
            User(
                id=2, email="pg-closure-owner@example.invalid", password_hash="x",
                first_name="Owner", last_name="Two", role="trader", tenant_id=1,
                parent_id=1, tree_path="1/2", level=1, is_active=True, is_verified=True,
            ),
            TradingProgram(
                id=10, tenant_id=1, name="PG recorded program", type="one_phase",
                account_size=Decimal("10000.00"), price=Decimal("99.00"), is_active=True,
            ),
            Challenge(
                id=100, user_id=2, program_id=10, status="active", payment_status="paid",
                initial_balance=Decimal("0.00"), current_balance=None, max_drawdown=Decimal("12.34"),
                current_phase=0, total_phases=2, created_at=instant,
            ),
        ])
        db.session.flush()
        db.session.add(MT5Account(
            id=1000, user_id=2, challenge_id=100, mt5_login="PG-RECORDED-1000",
            mt5_password_encrypted="synthetic", balance=Decimal("0.00"), equity=None,
            status="active", created_at=instant, updated_at=instant,
        ))
        db.session.flush()
        # ORM defaults otherwise overwrite constructor None: seed genuine SQL NULL.
        db.session.execute(update(Challenge).where(Challenge.id == 100).values(current_balance=None))
        db.session.execute(update(MT5Account).where(MT5Account.id == 1000).values(equity=None))
        db.session.commit()
        root = db.session.get(User, 1)
        statements = []

        def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)

        event.listen(db.engine, "before_cursor_execute", observe)
        try:
            list_args = AdminClosureChallengesService.parse_list_query(MultiDict([
                ("page", "1"), ("per_page", "20"), ("status", "active"), ("include_mt5", "true"),
            ]))
            listing = AdminClosureChallengesService.list(root, list_args)
            detail_args = AdminClosureChallengesService.parse_detail_query(MultiDict([("include_mt5", "false")]))
            detail = AdminClosureChallengesService.detail(root, 100, detail_args)
        finally:
            event.remove(db.engine, "before_cursor_execute", observe)

        assert listing["owner_context"] == {"user_id": 1, "tenant_id": 1}
        assert listing["filters"] == {"status": "active", "include_mt5": True}
        assert listing["pagination"] == {"page": 1, "per_page": 20, "total": 1, "pages": 1}
        row = listing["challenges"][0]
        assert row["id"] == 100 and row["initial_balance"] == "0.00" and row["current_balance"] is None
        assert row["mt5_account"]["balance"] == "0.00" and row["mt5_account"]["equity"] is None
        assert detail["challenge"]["mt5_account_binding"] == "not_requested"
        assert detail["challenge"]["mt5_account"] is None
        assert sum("SET LOCAL statement_timeout = 1500" in statement for statement in statements) == 2
    with app.app_context():
        db.session.remove()
        db.metadata.drop_all(bind=db.engine, tables=[MT5Account.__table__])
        db.engine.dispose()
