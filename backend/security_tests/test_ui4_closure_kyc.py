"""Focused security contracts for the UI-4 KYC administration closure."""
from datetime import datetime, timedelta
import io
import json

import pytest
from flask import Flask

from src.database import db
from src.models.user import User
from src.routes.kyc import kyc_bp
from src.services.auth_service import AuthService
from src.services.storage_service import storage_service
from src.utils.hierarchy_scoping import init_hierarchy_scoping


@pytest.fixture
def ui4_closure_kyc_app(tmp_path, monkeypatch):
    from src.config import TestingConfig

    app = Flask("ui4-closure-kyc-security")
    app.config.from_object(TestingConfig)
    app.config.update(
        TESTING=True,
        JWT_SECRET_KEY="ui4-closure-kyc-synthetic-key",
        JWT_ACCESS_TOKEN_EXPIRES=timedelta(minutes=10),
        JWT_REFRESH_TOKEN_EXPIRES=timedelta(days=1),
        PLATFORM_ROOT_USER_ID=1,
        EXPANDED_HIERARCHY_ENABLED=True,
        UPLOAD_FOLDER=str(tmp_path / "public"),
        KYC_PRIVATE_UPLOAD_FOLDER=str(tmp_path / "private"),
        KYC_ALLOW_PRIVATE_LOCAL_STORAGE=True,
    )
    db.init_app(app)
    app.register_blueprint(kyc_bp, url_prefix="/api/v1/kyc")
    init_hierarchy_scoping(db, User)
    monkeypatch.setattr(AuthService, "is_token_blacklisted", lambda _token: False)
    monkeypatch.setattr(storage_service, "client", None)

    instant = datetime(2026, 10, 12, 12, 0, 0)
    with app.app_context():
        User.__table__.create(db.engine)
        from src.models.token_blacklist import TokenBlacklist
        TokenBlacklist.__table__.create(db.engine)
        db.session.add_all([
            User(id=1, email="root@example.invalid", password_hash="x", first_name="Root", last_name="One",
                 role="supermaster", tenant_id=10, parent_id=None, tree_path="1", level=0,
                 can_create_same_role=True, is_active=True, is_verified=True),
            User(id=2, email="master@example.invalid", password_hash="x", first_name="Master", last_name="Two",
                 role="master", tenant_id=10, parent_id=1, tree_path="1/2", level=1,
                 is_active=True, is_verified=True),
            User(id=3, email="reviewee@example.invalid", password_hash="x", first_name="Review", last_name="Subject",
                 role="trader", tenant_id=10, parent_id=2, tree_path="1/2/3", level=2,
                 is_active=True, is_verified=True, kyc_status="pending", kyc_submitted_at=instant + timedelta(minutes=2)),
            User(id=4, email="foreign@example.invalid", password_hash="x", first_name="Foreign", last_name="Subject",
                 role="master", tenant_id=20, parent_id=None, tree_path="4", level=0,
                 is_active=True, is_verified=True, kyc_status="pending", kyc_submitted_at=instant + timedelta(minutes=3)),
            User(id=5, email="child-super@example.invalid", password_hash="x", first_name="Child", last_name="Super",
                 role="supermaster", tenant_id=10, parent_id=1, tree_path="1/5", level=1,
                 can_create_same_role=False, is_active=True, is_verified=True),
            User(id=6, email="tenantless@example.invalid", password_hash="x", first_name="No", last_name="Tenant",
                 role="master", tenant_id=None, parent_id=1, tree_path="1/6", level=1,
                 is_active=True, is_verified=True),
        ])
        db.session.commit()
        app.tokens = {identity: db.session.get(User, identity).generate_access_token() for identity in range(1, 7)}
        db.session.remove()
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def _headers(app, identity):
    return {"Authorization": "Bearer " + app.tokens[identity]}


def _upload(app, identity=3, document_type="id_proof", content=b"%PDF-1.7\nsynthetic-kyc"):
    return app.test_client().post(
        f"/api/v1/kyc/documents/{document_type}/upload",
        headers=_headers(app, identity),
        data={"file": (io.BytesIO(content), "proof.pdf")},
        content_type="multipart/form-data",
    )


def _prepare_pending_document(app, identity=3):
    assert _upload(app, identity).status_code == 200
    with app.app_context():
        user = db.session.get(User, identity)
        user.kyc_status = "pending"
        user.kyc_submitted_at = datetime(2026, 10, 12, 12, 4, 0)
        db.session.commit()


def test_ui4_closure_kyc_list_is_bounded_scoped_and_minimal(ui4_closure_kyc_app, record_property):
    app = ui4_closure_kyc_app
    _prepare_pending_document(app)
    client = app.test_client()

    root = client.get("/api/v1/kyc/admin/submissions?status=pending&page=1&per_page=20", headers=_headers(app, 1))
    assert root.status_code == 200
    payload = root.get_json()
    assert payload["owner_context"] == {"user_id": 1, "tenant_id": 10}
    assert payload["review_scope"] == "recorded_document_only"
    assert payload["filters"] == {"status": "pending"}
    assert payload["pagination"] == {"page": 1, "per_page": 20, "total": 1, "pages": 1}
    assert payload["submissions"] == [{
        "user_id": 3,
        "kyc_status": "pending",
        "submitted_at": "2026-10-12T12:04:00",
        "documents": {
            "id_proof": "pending", "address_proof": "not_uploaded",
            "selfie": "not_uploaded", "bank_statement": "not_uploaded",
        },
    }]
    serialized = json.dumps(payload, sort_keys=True)
    assert all(value not in serialized for value in ("@example.invalid", "local-kyc:", "phone", "country"))
    record_property("admin_closure_kyc_list", serialized)

    master = client.get("/api/v1/kyc/admin/submissions", headers=_headers(app, 2))
    assert master.status_code == 200
    assert [row["user_id"] for row in master.get_json()["submissions"]] == [3]
    child_super = client.get("/api/v1/kyc/admin/submissions", headers=_headers(app, 5))
    tenantless = client.get("/api/v1/kyc/admin/submissions", headers=_headers(app, 6))
    assert child_super.status_code == 200
    assert child_super.get_json()["submissions"] == []
    assert tenantless.status_code == 403
    assert tenantless.get_json()["code"] == "ADMIN_KYC_SCOPE_REQUIRED"


def test_ui4_closure_kyc_invalid_query_and_detail_scope_fail_closed(ui4_closure_kyc_app):
    app = ui4_closure_kyc_app
    _prepare_pending_document(app)
    client = app.test_client()
    for suffix in ("?page=01", "?per_page=0", "?status=all", "?page=1&page=2", "?unknown=1"):
        response = client.get("/api/v1/kyc/admin/submissions" + suffix, headers=_headers(app, 1))
        assert response.status_code == 400
        assert response.get_json()["code"] == "INVALID_ADMIN_KYC_QUERY"

    foreign = client.get("/api/v1/kyc/admin/submissions/4", headers=_headers(app, 2))
    missing = client.get("/api/v1/kyc/admin/submissions/999", headers=_headers(app, 1))
    trader = client.get("/api/v1/kyc/admin/submissions/3", headers=_headers(app, 3))
    assert foreign.status_code == missing.status_code == 404
    assert all(response.get_json()["code"] == "ADMIN_KYC_SUBMISSION_NOT_FOUND" for response in (foreign, missing))
    assert trader.status_code == 403


def test_ui4_closure_kyc_detail_download_and_typed_document_review_are_canonical(ui4_closure_kyc_app, record_property):
    app = ui4_closure_kyc_app
    _prepare_pending_document(app)
    client = app.test_client()

    detail_response = client.get("/api/v1/kyc/admin/submissions/3", headers=_headers(app, 2))
    assert detail_response.status_code == 200
    detail = detail_response.get_json()
    document = next(value for value in detail["documents"] if value["type"] == "id_proof")
    assert detail["user"] == {"id": 3, "display_name": "Review Subject"}
    assert document["download_url"] == "/api/v1/kyc/documents/3/id_proof/download"
    assert document["notes"] is None
    assert "email" not in json.dumps(detail)

    downloaded = client.get(document["download_url"], headers=_headers(app, 2))
    assert downloaded.status_code == 200
    assert downloaded.data.startswith(b"%PDF-")
    assert "private, no-store" in downloaded.headers["Cache-Control"]
    downloaded.close()

    before = client.put(
        "/api/v1/kyc/admin/submissions/3/documents/id_proof",
        headers=_headers(app, 2),
        json={
            "status": "approved", "notes": "", "acknowledgement": "REVIEW 4 id_proof",
            "expected_uploaded_at": document["uploaded_at"],
        },
    )
    assert before.status_code == 400
    with app.app_context():
        assert db.session.get(User, 3).kyc_id_status == "pending"

    saved = client.put(
        "/api/v1/kyc/admin/submissions/3/documents/id_proof",
        headers=_headers(app, 2),
        json={
            "status": "approved", "notes": "reviewed", "acknowledgement": "REVIEW 3 id_proof",
            "expected_uploaded_at": document["uploaded_at"],
        },
    )
    assert saved.status_code == 200
    result = saved.get_json()
    assert result == {
        "owner_context": {"user_id": 2, "tenant_id": 10},
        "review_scope": "recorded_document_only",
        "user": {"id": 3},
        "document": {
            "type": "id_proof", "status": "approved", "notes": "reviewed",
            "uploaded_at": document["uploaded_at"], "download_url": document["download_url"],
        },
        "review_recorded": True,
    }
    with app.app_context():
        reviewed = db.session.get(User, 3)
        assert reviewed.kyc_id_status == "approved"
        assert reviewed.kyc_id_notes == "reviewed"
        assert reviewed.kyc_status == "pending", "document review must not invent identity or product eligibility"
    record_property("admin_closure_kyc_review", json.dumps(result, sort_keys=True))


def test_ui4_closure_kyc_stale_cross_tenant_and_csrf_writes_do_not_change_document(ui4_closure_kyc_app):
    app = ui4_closure_kyc_app
    _prepare_pending_document(app)
    client = app.test_client()
    detail = client.get("/api/v1/kyc/admin/submissions/3", headers=_headers(app, 2)).get_json()
    document = next(value for value in detail["documents"] if value["type"] == "id_proof")
    review = {
        "status": "rejected", "notes": "Unreadable", "acknowledgement": "REVIEW 3 id_proof",
        "expected_uploaded_at": document["uploaded_at"],
    }

    foreign = client.put("/api/v1/kyc/admin/submissions/3/documents/id_proof", headers=_headers(app, 4), json=review)
    stale = client.put("/api/v1/kyc/admin/submissions/3/documents/id_proof", headers=_headers(app, 2), json={
        **review, "expected_uploaded_at": "2026-10-12T00:00:00",
    })
    assert foreign.status_code == 404
    assert stale.status_code == 409
    assert stale.get_json()["code"] == "KYC_DOCUMENT_REVIEW_STALE"

    cookie_client = app.test_client()
    cookie_client.set_cookie("access_token", app.tokens[2])
    csrf = cookie_client.put("/api/v1/kyc/admin/submissions/3/documents/id_proof", json=review)
    assert csrf.status_code == 403
    assert csrf.get_json()["code"] == "CSRF_INVALID"
    with app.app_context():
        user = db.session.get(User, 3)
        assert user.kyc_id_status == "pending"
        assert user.kyc_id_notes is None
