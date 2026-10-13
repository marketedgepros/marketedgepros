"""Unified UI-4 route wiring on a disposable database built from real Alembic heads.

Only the isolated staging runner may execute this file. No provider, file bytes,
production resource, external message or money operation is used.
"""
from datetime import datetime
from decimal import Decimal
import json

from sqlalchemy import select, text
from test_order_quote_concurrency import quote_database


def test_ui4_closure_six_domains_real_factory_http_and_persisted_user_actions(staging_resources, monkeypatch):
    from src.database import db
    from src.models.lead import Lead
    from src.models.trading_program import Challenge
    from src.models.user import User

    with quote_database(staging_resources, monkeypatch, revision="heads") as app:
        app.config["EXPANDED_HIERARCHY_ENABLED"] = True
        with app.app_context():
            assert db.session.execute(text("SELECT version_num FROM alembic_version")).scalars().all() == ["20261013_000002"]
            subject = db.session.get(User, 2)
            subject.kyc_status = "pending"
            subject.kyc_submitted_at = datetime(2026, 10, 12, 12, 0, 0)
            subject.kyc_id_status = "pending"
            subject.kyc_id_uploaded_at = datetime(2026, 10, 12, 11, 0, 0)
            subject.kyc_id_url = "local-kyc:kyc/2/id_proof_20261012_110000.pdf"
            db.session.add(Lead(id=100, first_name="Scoped", last_name="Lead", email="closure-head@example.invalid", assigned_to=1, status="new", source="website", score=1, budget=Decimal("10.50")))
            db.session.add(Challenge(id=100, user_id=2, program_id=10, status="pending", payment_status="pending", initial_balance=Decimal("10000.00"), current_balance=Decimal("10000.00")))
            db.session.commit()
            tokens = {i: db.session.get(User, i).generate_access_token() for i in (1, 2)}
            original_version = db.session.get(User, 2).token_version or 0
        headers = {"Authorization": "Bearer " + tokens[1]}
        client = app.test_client()
        requests = {
            "users": "/api/v1/admin/users?page=1&per_page=20",
            "crm": "/api/v1/crm/leads?page=1&per_page=20",
            "programs": "/api/v1/admin/programs",
            "challenges": "/api/v1/challenges/admin/all?page=1&per_page=20&include_mt5=false",
            "kyc": "/api/v1/kyc/admin/submissions?page=1&per_page=20&status=pending",
            "settings": "/api/v1/admin/settings",
        }
        payloads = {}
        for domain, url in requests.items():
            response = client.get(url, headers=headers)
            assert response.status_code == 200, (domain, response.status_code, response.get_json())
            payloads[domain] = response.get_json()
            assert payloads[domain]["owner_context"]["user_id"] == 1
            assert payloads[domain]["owner_context"]["tenant_id"] == 1
            assert set(payloads[domain]["owner_context"]) <= {"user_id", "tenant_id", "role"}
            if "role" in payloads[domain]["owner_context"]:
                assert payloads[domain]["owner_context"]["role"] == "supermaster"
            assert client.get(url).status_code == 401
            assert client.get(url, headers={"Authorization": "Bearer " + tokens[2]}).status_code == 403
        assert payloads["crm"]["leads"][0]["budget"] == "10.50"
        assert payloads["challenges"]["challenges"][0]["provider_authenticated"] is False
        assert payloads["kyc"]["review_scope"] == "recorded_document_only"
        # Authenticate and dispatch all three previously affected lock paths through
        # the production factory's actual decorators and route/service integration.
        actions = [
            ("put", "/api/v1/admin/users/2", {"first_name": "Persisted", "last_name": "User", "phone": None, "country_code": None, "role": "trader", "is_active": True}, "updated"),
            ("post", "/api/v1/admin/users/2/reset-password", {"new_password": "SyntheticStrong42!"}, "password_reset"),
            ("delete", "/api/v1/admin/users/2", None, "deactivated"),
        ]
        for method, url, body, expected in actions:
            response = getattr(client, method)(url, headers=headers, **({"json": body} if body is not None else {}))
            assert response.status_code == 200, (expected, response.status_code, response.get_json())
            data = response.get_json()
            assert data["action"] == expected and data["owner_context"] == {"user_id": 1, "tenant_id": 1}
        with app.app_context():
            db.session.expire_all()
            subject = db.session.get(User, 2)
            assert subject.first_name == "Persisted" and subject.is_active is False
            assert subject.token_version == original_version + 1
            assert subject.check_password("SyntheticStrong42!") is True
            assert db.session.scalar(select(Challenge.payment_status).where(Challenge.id == 100)) == "pending"
        # Only synthetic, minimal read payloads are captured: no password, token,
        # personal document bytes, production records or storage credentials.
        print("UI4_CLOSURE_HTTP_JSON=" + json.dumps(payloads, sort_keys=True))
