"""Synthetic-only HTTP/SQLite contracts for the UI-4 account profile routes."""
import base64
import io
import json

import pytest
from flask import Flask
from sqlalchemy import event

from src.config import TestingConfig
from src.database import db
from src.models.token_blacklist import TokenBlacklist
from src.models.user import EmailVerificationToken, PasswordResetToken, User
from src.routes.profile import profile_bp
from src.services.session_service import SessionService

# Complete, tiny PNG: exercises content validation without a real storage provider.
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC"
)


@pytest.fixture
def profile_app():
    app = Flask(__name__)
    app.config.from_object(TestingConfig)
    app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    db.init_app(app)
    app.register_blueprint(profile_bp, url_prefix="/api/v1/profile")
    tables = [
        User.__table__, TokenBlacklist.__table__, PasswordResetToken.__table__,
        EmailVerificationToken.__table__,
    ]
    with app.app_context():
        db.metadata.create_all(db.engine, tables=tables)
        user = User(
            id=1,
            email="profile.synthetic@example.invalid",
            first_name="Before",
            last_name="Profile",
            password_hash="unused",
            is_active=True,
            is_verified=True,
            tenant_id=None,
            tree_path="1",
        )
        user.set_password("InitialStrong42!")
        db.session.add(user)
        db.session.commit()
        app.profile_access, app.profile_refresh = SessionService.issue(user)
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


def _headers(app):
    return {"Authorization": "Bearer " + app.profile_access}


def _user(app):
    with app.app_context():
        return db.session.get(User, 1)


def _avatar(data, name="avatar.png"):
    return {"avatar": (io.BytesIO(data), name)}


def test_profile_http_happy_path_preserves_full_user_shape_and_records_parity(profile_app, record_property):
    """These are real Flask/SQLite payloads for the UI profileViewService map."""
    client = profile_app.test_client()
    response = client.get("/api/v1/profile", headers=_headers(profile_app))
    assert response.status_code == 200
    record_property("profile_get_response", json.dumps(response.get_json()))
    get_user = response.get_json()["user"]
    assert set(get_user) == {
        "id", "email", "first_name", "last_name", "phone", "country_code",
        "is_active", "is_verified", "two_factor_enabled", "kyc_status", "role",
        "tenant_id", "avatar_url", "created_at", "last_login_at", "email_verified_at",
        "kyc_submitted_at", "kyc_verified_at",
    }
    assert "password_hash" not in get_user and "two_factor_secret" not in get_user

    response = client.put(
        "/api/v1/profile", headers=_headers(profile_app),
        json={"first_name": "After", "last_name": "Contract", "phone": "+15551234567"},
    )
    assert response.status_code == 200
    record_property("profile_put_response", json.dumps(response.get_json()))
    payload = response.get_json()
    assert set(payload) == {"message", "user"}
    assert payload["message"] == "Profile updated successfully"
    assert set(payload["user"]) == set(get_user)
    assert payload["user"]["first_name"] == "After"


def test_profile_later_invalid_field_and_privilege_fields_cannot_dirty_or_write(profile_app):
    client = profile_app.test_client()
    statements = []
    with profile_app.app_context():
        engine = db.engine
    def observe_sql(*args):
        statements.append(args[2])
    event.listen(engine, "before_cursor_execute", observe_sql)
    try:
        invalid_later = client.put(
            "/api/v1/profile", headers=_headers(profile_app),
            json={"first_name": "Valid", "last_name": True},
        )
        role_attempt = client.put(
            "/api/v1/profile", headers=_headers(profile_app),
            json={"first_name": "Valid", "role": "supermaster", "tenant_id": 999},
        )
    finally:
        event.remove(engine, "before_cursor_execute", observe_sql)

    assert invalid_later.status_code == 400
    assert role_attempt.status_code == 400
    assert _user(profile_app).first_name == "Before"
    assert _user(profile_app).last_name == "Profile"
    assert _user(profile_app).role == "guest"
    assert _user(profile_app).tenant_id is None
    assert not any(statement.lstrip().upper().startswith(("UPDATE", "INSERT", "DELETE")) for statement in statements)


@pytest.mark.parametrize(
    "body,content_type,status",
    [
        (b"[]", "application/json", 400),
        (b"null", "application/json", 400),
        (b'{"first_name":"Good","first_name":"Other"}', "application/json", 400),
        (b'{"first_name":"Good","last_name":false}', "application/json", 400),
        (b"not-json", "text/plain", 415),
        (b'{"first_name":"' + (b"x" * 4096) + b'"}', "application/json", 413),
    ],
)
def test_profile_requires_bounded_plain_json_mapping(profile_app, body, content_type, status):
    response = profile_app.test_client().put(
        "/api/v1/profile", headers=_headers(profile_app), data=body, content_type=content_type,
    )
    assert response.status_code == status
    assert _user(profile_app).first_name == "Before"


def test_password_contract_is_exact_bounded_and_revokes_reset_tokens_atomically(profile_app):
    with profile_app.app_context():
        reset = PasswordResetToken(1)
        db.session.add(reset)
        db.session.commit()
    client = profile_app.test_client()

    too_long = client.put(
        "/api/v1/profile/password", headers=_headers(profile_app),
        json={"current_password": "InitialStrong42!", "new_password": "A1!a" + ("z" * 1021)},
    )
    assert too_long.status_code == 400
    unknown = client.put(
        "/api/v1/profile/password", headers=_headers(profile_app),
        json={"current_password": "InitialStrong42!", "new_password": "NextStrong43!", "role": "supermaster"},
    )
    assert unknown.status_code == 400
    wrong = client.put(
        "/api/v1/profile/password", headers=_headers(profile_app),
        json={"current_password": "wrong", "new_password": "NextStrong43!"},
    )
    assert wrong.status_code == 401

    changed = client.put(
        "/api/v1/profile/password", headers=_headers(profile_app),
        json={"current_password": "InitialStrong42!", "new_password": "NextStrong43!"},
    )
    assert changed.status_code == 200
    assert changed.get_json() == {"message": "Password changed successfully"}
    with profile_app.app_context():
        user = db.session.get(User, 1)
        assert user.check_password("NextStrong43!")
        assert user.token_version == 1
        assert PasswordResetToken.query.filter_by(user_id=1).one().used is True
    # The old versioned access and refresh tokens cannot survive the response.
    assert profile_app.test_client().get("/api/v1/profile", headers=_headers(profile_app)).status_code == 401
    with profile_app.app_context():
        with pytest.raises(ValueError):
            SessionService.authenticate(profile_app.profile_refresh, "refresh")


def test_password_reset_revoke_failure_rolls_back_hash_and_token_version(profile_app):
    with profile_app.app_context():
        reset = PasswordResetToken(1)
        db.session.add(reset)
        db.session.commit()
        engine = db.engine

    def fail_reset_update(_connection, _cursor, statement, _parameters, _context, _executemany):
        if "UPDATE password_reset_tokens" in statement:
            raise RuntimeError("synthetic reset write failure")

    event.listen(engine, "before_cursor_execute", fail_reset_update)
    try:
        response = profile_app.test_client().put(
            "/api/v1/profile/password", headers=_headers(profile_app),
            json={"current_password": "InitialStrong42!", "new_password": "NextStrong43!"},
        )
    finally:
        event.remove(engine, "before_cursor_execute", fail_reset_update)
    assert response.status_code == 500
    assert response.get_json() == {"error": "Failed to change password"}
    with profile_app.app_context():
        user = db.session.get(User, 1)
        assert user.check_password("InitialStrong42!")
        assert user.token_version == 0
        assert PasswordResetToken.query.filter_by(user_id=1).one().used is False


def test_avatar_requires_real_image_content_and_strict_storage_success(profile_app, monkeypatch):
    client = profile_app.test_client()
    called = []
    monkeypatch.setattr(
        "src.routes.profile.storage_service.upload_profile_image",
        lambda *_args: called.append(True) or {"success": True, "url": "https://storage.invalid/profiles/1/avatar.png", "key": "profiles/1/avatar.png"},
    )
    fake = client.post(
        "/api/v1/profile/avatar", headers=_headers(profile_app),
        data=_avatar(b"not an image"), content_type="multipart/form-data",
    )
    assert fake.status_code == 400 and not called

    monkeypatch.setattr(
        "src.routes.profile.storage_service.upload_profile_image",
        lambda *_args: {"success": "yes", "url": "https://storage.invalid/secret?token=leak"},
    )
    failure = client.post(
        "/api/v1/profile/avatar", headers=_headers(profile_app),
        data=_avatar(PNG_1X1), content_type="multipart/form-data",
    )
    assert failure.status_code == 503
    assert "secret" not in failure.get_data(as_text=True)
    assert _user(profile_app).avatar_url is None


def test_avatar_upload_and_delete_are_truthful_with_mocked_storage(profile_app, monkeypatch):
    client = profile_app.test_client()
    url = "/uploads/profiles/1/avatar.png"
    monkeypatch.setattr(
        "src.routes.profile.storage_service.upload_profile_image",
        lambda *_args: {"success": True, "url": url, "key": "profiles/1/avatar.png"},
    )
    uploaded = client.post(
        "/api/v1/profile/avatar", headers=_headers(profile_app),
        data=_avatar(PNG_1X1), content_type="multipart/form-data",
    )
    assert uploaded.status_code == 200
    assert uploaded.get_json()["avatar_url"] == url

    monkeypatch.setattr("src.routes.profile.storage_service.delete_file", lambda _key: False)
    failed_delete = client.delete("/api/v1/profile/avatar", headers=_headers(profile_app))
    assert failed_delete.status_code == 503
    assert failed_delete.get_json() == {"error": "Avatar deletion failed"}
    assert _user(profile_app).avatar_url == url

    keys = []
    monkeypatch.setattr("src.routes.profile.storage_service.delete_file", lambda key: keys.append(key) or True)
    deleted = client.delete("/api/v1/profile/avatar", headers=_headers(profile_app))
    assert deleted.status_code == 200
    assert keys == ["profiles/1/avatar.png"]
    assert _user(profile_app).avatar_url is None
    noop = client.delete("/api/v1/profile/avatar", headers=_headers(profile_app))
    assert noop.status_code == 200
    assert noop.get_json()["message"] == "No avatar to delete"
