"""Full API contract for the Stage 6c in-app notification boundary.

Run from ``backend`` with:
    ../.venv/bin/python -m pytest --confcutdir=security_tests -q -k in_app_notification
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from src.database import db
from src.middleware.csrf_middleware import generate_csrf_token
from src.models.notification import EmailQueue, Notification, NotificationPreference
from src.models.tenant import Tenant
from src.models.token_blacklist import TokenBlacklist
from src.models.user import User


NOTIFICATIONS = "/api/v1/notifications/"


# Tenant.settings is existing PostgreSQL JSONB schema.  The focused security
# runner intentionally uses SQLite, so compile that already-existing type as
# JSON only for its ephemeral test database.
@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"

_TABLES = [
    Tenant.__table__,
    User.__table__,
    Notification.__table__,
    NotificationPreference.__table__,
    EmailQueue.__table__,
    TokenBlacklist.__table__,
]


@pytest.fixture
def in_app_notification_app():
    """Full factory, real JWT middleware and only isolated SQLite tables."""
    from src.app import create_app

    app = create_app(
        "testing",
        config_overrides={
            "EXPANDED_HIERARCHY_ENABLED": True,
            "PLATFORM_ROOT_USER_ID": 1,
            "PROPAGATE_EXCEPTIONS": False,
            "RATELIMIT_ENABLED": False,
        },
    )
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=_TABLES)
        db.session.add_all([
            Tenant(id=1, name="Primary", subdomain="primary", status="active"),
            Tenant(id=2, name="Foreign", subdomain="foreign", status="active"),
            Tenant(id=3, name="Inactive", subdomain="inactive", status="inactive"),
        ])
        users = [
            _user(1, "root@example.test", role="supermaster", tenant_id=1,
                  parent_id=None, tree_path="1", can_create_same_role=True),
            _user(2, "owner@example.test", tenant_id=1, parent_id=1, tree_path="1/2"),
            _user(3, "foreign@example.test", tenant_id=2, parent_id=None, tree_path="3"),
            _user(4, "inactive@example.test", tenant_id=1, parent_id=1, tree_path="1/4", active=False),
            _user(5, "master@example.test", role="master", tenant_id=1, parent_id=1, tree_path="1/5"),
            _user(6, "downline@example.test", tenant_id=1, parent_id=5, tree_path="1/5/6"),
            _user(7, "unverified@example.test", tenant_id=1, parent_id=1, tree_path="1/7", verified=False),
            _user(8, "inactive-tenant@example.test", tenant_id=3, parent_id=None, tree_path="8"),
        ]
        db.session.add_all(users)
        db.session.commit()
        app.notification_tokens = {
            user.id: user.generate_access_token() for user in users
        }
        yield app
        db.session.remove()
        db.metadata.drop_all(bind=db.engine, tables=list(reversed(_TABLES)))


def _user(identity, email, *, role="trader", tenant_id, parent_id, tree_path,
          active=True, verified=True, can_create_same_role=False):
    return User(
        id=identity,
        email=email,
        password_hash="not-a-credential",
        first_name="Notification",
        last_name="Contract",
        role=role,
        tenant_id=tenant_id,
        parent_id=parent_id,
        tree_path=tree_path,
        level=0 if parent_id is None else tree_path.count("/"),
        is_active=active,
        is_verified=verified,
        can_create_same_role=can_create_same_role,
    )


def _headers(app, user_id=2):
    return {"Authorization": "Bearer " + app.notification_tokens[user_id]}


def _notification(user_id, *, kind="system", read=False, deleted=False, title="Notice"):
    row = Notification(
        user_id=user_id,
        type=kind,
        title=title,
        message="A notification contract row",
        priority="normal",
        is_read=read,
        is_deleted=deleted,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.session.add(row)
    db.session.commit()
    return row


def test_in_app_notification_list_count_filter_and_stable_pagination(in_app_notification_app):
    app = in_app_notification_app
    with app.app_context():
        oldest = _notification(2, kind="system", title="oldest")
        middle = _notification(2, kind="kyc", read=True, title="middle")
        newest = _notification(2, kind="kyc", title="newest")
        for row, timestamp in ((oldest, 1), (middle, 2), (newest, 3)):
            row.created_at = datetime(2026, 1, timestamp)
        db.session.commit()

    client = app.test_client()
    response = client.get(NOTIFICATIONS + "?page=1&per_page=2", headers=_headers(app))
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["page"] == 1 and payload["per_page"] == 2
    assert payload["total"] == 3
    assert payload["pages"] == 2
    assert [row["title"] for row in payload["notifications"]] == ["newest", "middle"]

    filtered = client.get(
        NOTIFICATIONS + "?type=kyc&is_read=false&priority=normal", headers=_headers(app)
    )
    assert filtered.status_code == 200
    assert [row["title"] for row in filtered.get_json()["notifications"]] == ["newest"]
    assert client.get(NOTIFICATIONS + "unread-count", headers=_headers(app)).get_json() == {
        "count": 2, "owner_context": {"user_id": 2, "tenant_id": 1},
    }


@pytest.mark.parametrize("query,code", [
    ("?page=0", "PAGINATION_INVALID"),
    ("?page=01", "PAGINATION_INVALID"),
    ("?page=1001", "PAGINATION_INVALID"),
    ("?per_page=101", "PAGINATION_INVALID"),
    ("?type=unknown", "QUERY_INVALID"),
    ("?is_read=1", "QUERY_INVALID"),
    ("?page=1&page=2", "QUERY_INVALID"),
    ("?type=kyc&type=system", "QUERY_INVALID"),
    ("?unexpected=value", "QUERY_INVALID"),
])
def test_in_app_notification_list_rejects_ambiguous_or_invalid_primitives(in_app_notification_app, query, code):
    response = in_app_notification_app.test_client().get(NOTIFICATIONS + query, headers=_headers(in_app_notification_app))
    assert response.status_code == 400
    assert response.get_json()["code"] == code


def test_in_app_notification_personal_ownership_inactive_and_tenant_boundaries(in_app_notification_app):
    app = in_app_notification_app
    with app.app_context():
        foreign = _notification(3, title="foreign")
        inactive_owner = _notification(4, title="inactive-owner")
        _notification(2, title="owned")
        foreign_id = foreign.id
        inactive_owner_id = inactive_owner.id

    client = app.test_client()
    assert client.post(f"{NOTIFICATIONS}{foreign_id}/read", headers=_headers(app)).status_code == 404
    assert client.delete(f"{NOTIFICATIONS}{foreign_id}", headers=_headers(app)).status_code == 404
    # A root's personal endpoint remains self-only and cannot enumerate a child.
    root_rows = client.get(NOTIFICATIONS, headers=_headers(app, 1)).get_json()["notifications"]
    assert root_rows == []
    assert client.get(NOTIFICATIONS, headers=_headers(app, 4)).status_code == 401
    assert client.get(NOTIFICATIONS, headers=_headers(app, 7)).status_code == 403
    assert client.get(NOTIFICATIONS, headers=_headers(app, 8)).status_code == 403
    # Never leak whether an inactive owner's record exists.
    assert client.post(f"{NOTIFICATIONS}{inactive_owner_id}/read", headers=_headers(app)).status_code == 404


def test_in_app_notification_read_all_soft_delete_and_unread_exclusion(in_app_notification_app):
    app = in_app_notification_app
    with app.app_context():
        first = _notification(2, title="first")
        second = _notification(2, title="second")
        deleted = _notification(2, deleted=True, title="already-deleted")
        first_id, second_id, deleted_id = first.id, second.id, deleted.id

    client = app.test_client()
    read_all = client.post(NOTIFICATIONS + "read-all", headers=_headers(app))
    assert read_all.status_code == 200
    assert read_all.get_json()["count"] == 2
    assert client.get(NOTIFICATIONS + "unread-count", headers=_headers(app)).get_json() == {
        "count": 0, "owner_context": {"user_id": 2, "tenant_id": 1},
    }

    deleted_response = client.delete(f"{NOTIFICATIONS}{first_id}", headers=_headers(app))
    assert deleted_response.status_code == 200
    assert deleted_response.get_json()["notification"]["is_deleted"] is True
    listed = client.get(NOTIFICATIONS, headers=_headers(app)).get_json()["notifications"]
    assert [row["id"] for row in listed] == [second_id]
    with app.app_context():
        assert db.session.get(Notification, first_id).is_deleted is True
        assert db.session.get(Notification, deleted_id).is_deleted is True


def test_in_app_notification_preferences_read_defaults_without_dml_or_autoflush(in_app_notification_app):
    app = in_app_notification_app
    writes = []

    def observe_write(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)

    with app.app_context():
        # Pending unrelated work is a regression tripwire: the preference GET
        # itself must neither create defaults nor flush this record.
        pending = Notification(user_id=2, type="system", title="pending", message="pending")
        db.session.add(pending)
        event.listen(db.engine, "before_cursor_execute", observe_write)
        try:
            response = app.test_client().get(NOTIFICATIONS + "preferences", headers=_headers(app))
        finally:
            event.remove(db.engine, "before_cursor_execute", observe_write)
            db.session.rollback()

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["id"] is None and payload["persisted"] is False
    assert payload["in_app"] == {key: True for key in ("withdrawal", "commission", "kyc", "system", "payment", "challenge")}
    assert payload["email"]["system"] is False
    assert payload["settings"] == {"email_enabled": True, "email_frequency": "instant"}
    assert pending.id is None
    assert writes == []
    with app.app_context():
        assert NotificationPreference.query.filter_by(user_id=2).count() == 0


def test_in_app_notification_preferences_strict_json_atomic_update_and_no_email_queue(in_app_notification_app):
    app = in_app_notification_app
    client = app.test_client()
    headers = _headers(app)

    invalid = client.put(
        NOTIFICATIONS + "preferences",
        json={"in_app": {"kyc": False}, "settings": {"email_frequency": "hourly"}},
        headers=headers,
    )
    assert invalid.status_code == 400
    with app.app_context():
        assert NotificationPreference.query.filter_by(user_id=2).count() == 0

    response = client.put(
        NOTIFICATIONS + "preferences",
        json={
            "in_app": {"kyc": False},
            "email": {"system": True},
            "settings": {"email_enabled": False, "email_frequency": "daily"},
        },
        headers=headers,
    )
    assert response.status_code == 200
    prefs = response.get_json()["preferences"]
    assert prefs["persisted"] is True and isinstance(prefs["id"], int)
    assert prefs["in_app"]["kyc"] is False
    assert prefs["email"]["system"] is True
    assert prefs["settings"] == {"email_enabled": False, "email_frequency": "daily"}

    duplicate = client.put(
        NOTIFICATIONS + "preferences",
        data='{"in_app":{"kyc":false,"kyc":true}}',
        content_type="application/json",
        headers=headers,
    )
    assert duplicate.status_code == 400
    primitive = client.put(
        NOTIFICATIONS + "preferences",
        json={"in_app": {"kyc": 1}},
        headers=headers,
    )
    assert primitive.status_code == 400
    too_large = client.put(
        NOTIFICATIONS + "preferences",
        data="{" + ('"x":"' + ("z" * (64 * 1024)) + '"}') + "}",
        content_type="application/json",
        headers=headers,
    )
    assert too_large.status_code == 413
    with app.app_context():
        stored = NotificationPreference.query.filter_by(user_id=2).one()
        assert stored.in_app_kyc is False
        assert stored.email_system is True
        assert EmailQueue.query.count() == 0


def test_in_app_notification_cookie_mutation_obeys_existing_csrf_guard(in_app_notification_app):
    app = in_app_notification_app
    with app.app_context():
        row = _notification(2)
        row_id = row.id
        csrf = generate_csrf_token(app.notification_tokens[2])
    client = app.test_client()
    client.set_cookie("access_token", app.notification_tokens[2])
    assert client.post(f"{NOTIFICATIONS}{row_id}/read").status_code == 403
    client.set_cookie("csrf_token", csrf)
    allowed = client.post(f"{NOTIFICATIONS}{row_id}/read", headers={"X-CSRF-Token": csrf})
    assert allowed.status_code == 200


def test_in_app_notification_admin_stats_scope_and_delivery_disabled(in_app_notification_app):
    app = in_app_notification_app
    with app.app_context():
        _notification(1, title="root")
        _notification(5, title="master")
        _notification(6, title="downline")
        _notification(2, title="sibling")
        _notification(3, title="foreign")

    client = app.test_client()
    master_stats = client.get(NOTIFICATIONS + "admin/stats", headers=_headers(app, 5))
    assert master_stats.status_code == 200
    assert master_stats.get_json()["total"] == 2
    root_stats = client.get(NOTIFICATIONS + "admin/stats", headers=_headers(app, 1))
    assert root_stats.status_code == 200
    assert root_stats.get_json()["total"] == 5

    for path in ("admin/send", "admin/broadcast"):
        response = client.post(NOTIFICATIONS + path, json={"user_ids": [2]}, headers=_headers(app, 5))
        assert response.status_code == 503
        assert response.get_json()["code"] == "DELIVERY_NOT_CONFIGURED"
    with app.app_context():
        assert Notification.query.count() == 5
        assert EmailQueue.query.count() == 0


def test_in_app_notification_internal_errors_are_redacted(in_app_notification_app, monkeypatch):
    from src.routes import notifications as notification_routes

    def explode(_actor, **_kwargs):
        raise RuntimeError("database-password=do-not-disclose")

    monkeypatch.setattr(notification_routes, "_owned_notifications", explode)
    response = in_app_notification_app.test_client().get(NOTIFICATIONS, headers=_headers(in_app_notification_app))
    assert response.status_code == 500
    assert response.get_json() == {
        "error": "Unable to process notification request",
        "code": "NOTIFICATION_ERROR",
    }
    assert "database-password" not in response.get_data(as_text=True)
