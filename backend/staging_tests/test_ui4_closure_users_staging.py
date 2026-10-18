"""PostgreSQL staging contract for the UI-4 users closure service.

The staging runner provisions its isolated PostgreSQL schema before this test.  The
shared admin.py endpoint patch is deliberately not applied in this work unit, so the
service contract is exercised directly here; the integrator runs this once after
applying users/integration.patch.
"""
from datetime import datetime
from decimal import Decimal

from werkzeug.datastructures import MultiDict


def test_ui4_closure_users_postgresql_scope_decimal_and_persisted_actions(app, staging_resources):
    from src.database import db
    from src.models.payment import Payment
    from src.models.tenant import Tenant
    from src.models.trading_program import Challenge, TradingProgram
    from src.models.user import User
    from src.services.admin_closure_users import AdminClosureUsersService

    with app.app_context():
        assert db.engine.dialect.name == "postgresql"
        instant = datetime(2026, 10, 12, 13, 0, 0)
        db.session.add_all([
            Tenant(id=1, name="Users closure tenant", subdomain="users-closure-pg", status="active"),
            User(id=1, email="users-root@example.invalid", password_hash="x", first_name="Root", last_name="One",
                 role="supermaster", tenant_id=1, parent_id=None, tree_path="1", level=0,
                 can_create_same_role=True, is_active=True, is_verified=True),
            User(id=2, email="users-master@example.invalid", password_hash="x", first_name="Master", last_name="Two",
                 role="master", tenant_id=1, parent_id=1, tree_path="1/2", level=1,
                 is_active=True, is_verified=True),
            User(id=3, email="users-trader@example.invalid", password_hash="x", first_name="Trader", last_name="Three",
                 role="trader", tenant_id=1, parent_id=2, tree_path="1/2/3", level=2,
                 is_active=True, is_verified=True),
        ])
        db.session.add(TradingProgram(id=1, tenant_id=1, name="Users closure program", type="one_phase",
                                      account_size=Decimal("1000.00"), price=Decimal("99.00"), is_active=True))
        db.session.flush()
        db.session.add_all([
            Challenge(id=1, user_id=3, program_id=1, status="active", initial_balance=Decimal("1000.00"),
                      current_balance=Decimal("1000.00"), total_profit=Decimal("0.00"), created_at=instant),
            Payment(id=1, user_id=3, amount=Decimal("0.00"), currency="EUR", payment_method="synthetic",
                    payment_type="credit_card", purpose="challenge_purchase", status="completed",
                    transaction_id="staging-private-users", provider_response="staging-private", created_at=instant),
        ])
        db.session.commit()
        master = db.session.get(User, 2)
        listing = AdminClosureUsersService.list_users(master, AdminClosureUsersService.parse_list_query(MultiDict()))
        assert listing["owner_context"] == {"user_id": 2, "tenant_id": 1}
        assert [row["id"] for row in listing["users"]] == [3, 2]
        details = AdminClosureUsersService.full_details(master, 3)
        assert details["challenges"]["items"][0]["initial_balance"] == "1000.00"
        assert details["payments"]["items"][0] == {
            "id": 1, "amount": "0.00", "currency": "EUR", "status": "completed",
            "payment_type": "challenge_purchase", "created_at": "2026-10-12T13:00:00Z",
        }
        updated = AdminClosureUsersService.update_user(master, 3, {
            "first_name": "Persisted", "last_name": "Three", "phone": None,
            "country_code": None, "role": "trader", "is_active": True,
        })
        assert updated["action"] == "updated"
        db.session.expire_all()
        assert db.session.get(User, 3).first_name == "Persisted"
        reset = AdminClosureUsersService.reset_password(master, 3, {"new_password": "SyntheticStrong42!"})
        assert reset["action"] == "password_reset"
        db.session.expire_all()
        assert db.session.get(User, 3).token_version == 1
        assert db.session.get(User, 3).check_password("SyntheticStrong42!") is True
        result = AdminClosureUsersService.deactivate_user(master, 3)
        assert result["action"] == "deactivated" and result["user"]["is_active"] is False
        db.session.expire_all()
        assert db.session.get(User, 3).is_active is False
