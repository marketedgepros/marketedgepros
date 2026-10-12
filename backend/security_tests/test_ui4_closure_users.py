"""Focused service contracts for the UI-4 users closure implementation.

This file exercises the owned service directly because the shared admin.py wiring is
supplied as integration.patch and is intentionally not applied by this work unit.
"""
from datetime import datetime, timedelta
from decimal import Decimal
import json

import pytest
from flask import Flask
from sqlalchemy import event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from werkzeug.datastructures import MultiDict

from src.database import db
from src.models.payment import Payment
from src.models.tenant import Tenant
from src.models.token_blacklist import TokenBlacklist
from src.models.trading_program import Challenge, TradingProgram
from src.models.user import PasswordResetToken, User
from src.services.admin_closure_users import (
    AdminClosureUsersNotFound,
    AdminClosureUsersQueryInvalid,
    AdminClosureUsersScopeRequired,
    AdminClosureUsersService,
)
from src.utils.hierarchy_scoping import init_hierarchy_scoping


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_element, _compiler, **_kwargs):
    return "JSON"


@pytest.fixture
def ui4_closure_users_app():
    app = Flask("ui4-closure-users-security")
    app.config.update(
        TESTING=True,
        SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY="ui4-closure-users-synthetic-key",
        PLATFORM_ROOT_USER_ID=1,
        EXPANDED_HIERARCHY_ENABLED=True,
    )
    db.init_app(app)
    init_hierarchy_scoping(db, User)
    tables = [
        Tenant.__table__, User.__table__, TokenBlacklist.__table__, PasswordResetToken.__table__,
        TradingProgram.__table__, Challenge.__table__, Payment.__table__,
    ]
    moment = datetime(2026, 10, 12, 12, 0, 0)
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=tables)
        db.session.add_all([
            Tenant(id=1, name="Synthetic tenant one", subdomain="closure-users-one", status="active"),
            Tenant(id=2, name="Synthetic tenant two", subdomain="closure-users-two", status="active"),
            User(id=1, email="root@example.invalid", password_hash="x", first_name="Root", last_name="One",
                 role="supermaster", tenant_id=1, parent_id=None, tree_path="1", level=0,
                 can_create_same_role=True, is_active=True, is_verified=True, created_at=moment - timedelta(days=3)),
            User(id=2, email="master@example.invalid", password_hash="x", first_name="Master", last_name="Two",
                 role="master", tenant_id=1, parent_id=1, tree_path="1/2", level=1,
                 is_active=True, is_verified=True, created_at=moment - timedelta(days=2)),
            User(id=3, email="trader@example.invalid", password_hash="x", first_name="Trader", last_name="Three",
                 role="trader", tenant_id=1, parent_id=2, tree_path="1/2/3", level=2,
                 is_active=True, is_verified=True, phone="555", country_code="+1", created_at=moment - timedelta(days=1)),
            User(id=4, email="foreign@example.invalid", password_hash="x", first_name="Foreign", last_name="Four",
                 role="trader", tenant_id=2, parent_id=None, tree_path="4", level=0,
                 is_active=True, is_verified=True, created_at=moment),
            User(id=5, email="tenantless@example.invalid", password_hash="x", first_name="No", last_name="Tenant",
                 role="master", tenant_id=None, parent_id=1, tree_path="1/5", level=1,
                 is_active=True, is_verified=True, created_at=moment),
        ])
        db.session.add(TradingProgram(id=1, tenant_id=1, name="Synthetic program", type="one_phase",
                                      account_size=Decimal("1000.00"), price=Decimal("99.00"), is_active=True))
        db.session.flush()
        db.session.add_all([
            Challenge(id=1, user_id=3, program_id=1, status="active", initial_balance=Decimal("1000.00"),
                      current_balance=Decimal("999.50"), total_profit=Decimal("-0.50"), created_at=moment),
            Payment(id=1, user_id=3, amount=Decimal("0.00"), currency="EUR", payment_method="synthetic",
                    payment_type="credit_card", purpose="challenge_purchase", status="completed",
                    transaction_id="private-transaction", provider_response="provider-private", created_at=moment),
        ])
        db.session.commit()
    try:
        yield app
    finally:
        with app.app_context():
            db.session.remove()
            db.metadata.drop_all(bind=db.engine, tables=list(reversed(tables)))
            db.engine.dispose()


def _actor(identity):
    return db.session.get(User, identity)


def _args(values=None):
    return MultiDict(values or {})


def test_ui4_closure_users_scopes_exact_detail_fields_and_decimal_records(ui4_closure_users_app):
    with ui4_closure_users_app.app_context():
        master = _actor(2)
        arguments = AdminClosureUsersService.parse_list_query(_args({"page": "1", "per_page": "20"}))
        listed = AdminClosureUsersService.list_users(master, arguments)
        assert listed["owner_context"] == {"user_id": 2, "tenant_id": 1}
        assert [row["id"] for row in listed["users"]] == [3, 2]
        assert listed["filters"] == {"role": None, "status": None, "search": None}
        assert all(set(row) == {
            "id", "first_name", "last_name", "email", "role", "is_active", "kyc_status", "created_at", "last_login_at",
        } for row in listed["users"])
        with pytest.raises(AdminClosureUsersNotFound):
            AdminClosureUsersService.get_user(master, 4)
        details = AdminClosureUsersService.full_details(master, 3)
        assert set(details) == {
            "owner_context", "record_verification", "settlement_enabled", "user", "downline", "challenges", "payments",
        }
        assert details["record_verification"] == "unverified_legacy"
        assert details["settlement_enabled"] is False
        assert details["challenges"]["items"][0]["initial_balance"] == "1000.00"
        assert details["challenges"]["items"][0]["total_profit"] == "-0.50"
        assert details["payments"]["items"][0]["amount"] == "0.00"
        assert details["payments"]["items"][0]["currency"] == "EUR"
        rendered = json.dumps(details, sort_keys=True)
        assert "password_hash" not in rendered and "private-transaction" not in rendered and "provider-private" not in rendered
        hierarchy = AdminClosureUsersService.hierarchy(master)
        assert hierarchy["owner_context"] == {"user_id": 2, "tenant_id": 1}
        assert hierarchy["total_users"] == 2
        assert hierarchy["users"][0]["id"] == 2
        assert hierarchy["users"][0]["children"][0]["id"] == 3


def test_ui4_closure_users_query_scope_and_write_allowlist_contracts(ui4_closure_users_app):
    with ui4_closure_users_app.app_context():
        master = _actor(2)
        for arguments in ({"page": "01"}, {"per_page": "51"}, {"status": "all"}, {"search": ""}, {"unknown": "1"}):
            with pytest.raises(AdminClosureUsersQueryInvalid):
                AdminClosureUsersService.parse_list_query(_args(arguments))
        tenantless = _actor(5)
        statements = []
        def observe(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)
        event.listen(db.engine, "before_cursor_execute", observe)
        try:
            with pytest.raises(AdminClosureUsersScopeRequired):
                AdminClosureUsersService.list_users(tenantless, AdminClosureUsersService.parse_list_query(_args()))
        finally:
            event.remove(db.engine, "before_cursor_execute", observe)
        assert statements == []
        updated = AdminClosureUsersService.update_user(master, 3, {
            "first_name": "Updated", "last_name": "Three", "phone": None, "country_code": None,
            "role": "trader", "is_active": True,
        })
        assert updated == {
            "owner_context": {"user_id": 2, "tenant_id": 1}, "action": "updated", "message": "User updated successfully.",
            "user": {"id": 3, "role": "trader", "is_active": True},
        }
        with pytest.raises(ValueError):
            AdminClosureUsersService.update_user(master, 3, {
                "first_name": "Updated", "last_name": "Three", "phone": None, "country_code": None,
                "role": "trader", "is_active": True, "email": "attempt@example.invalid",
            })
        password_result = AdminClosureUsersService.reset_password(master, 3, {"new_password": "NextStrong42!"})
        assert password_result["action"] == "password_reset"
        assert password_result["user"] == {"id": 3, "role": "trader", "is_active": True}
        assert _actor(3).token_version == 1
        deactivated = AdminClosureUsersService.deactivate_user(master, 3)
        assert deactivated["action"] == "deactivated" and deactivated["user"]["is_active"] is False
        assert _actor(3).is_active is False
