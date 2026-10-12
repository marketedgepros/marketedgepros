"""UI-4 support/notification HTTP ownership and payload parity (synthetic SQLite only)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles


SUPPORT = "/api/v1/support/tickets"
NOTIFICATIONS = "/api/v1/notifications/"
EXPECTED_OWNER = {"user_id": 2, "tenant_id": 1}


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(_element, _compiler, **_kwargs):
    """Use the already-modelled JSONB columns in the isolated SQLite factory."""
    return "JSON"


@pytest.fixture
def ui4_support_notification_app():
    """Real full Flask factory with only synthetic support/notification tables."""
    from src.app import create_app
    from src.database import db
    from src.models.notification import EmailQueue, Notification, NotificationPreference
    from src.models.support_ticket import SupportTicket, TicketMessage
    from src.models.tenant import Tenant
    from src.models.token_blacklist import TokenBlacklist
    from src.models.user import User

    app = create_app(
        "testing",
        config_overrides={
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "JWT_ACCESS_TOKEN_EXPIRES": timedelta(hours=1),
            "RATELIMIT_ENABLED": False,
            "PROPAGATE_EXCEPTIONS": False,
            "EXPANDED_HIERARCHY_ENABLED": True,
        },
    )
    tables = [
        Tenant.__table__,
        User.__table__,
        TokenBlacklist.__table__,
        SupportTicket.__table__,
        TicketMessage.__table__,
        Notification.__table__,
        NotificationPreference.__table__,
        EmailQueue.__table__,
    ]
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=tables)
        db.session.add_all([
            Tenant(id=1, name="UI4 Tenant One", subdomain="ui4-one", status="active"),
            Tenant(id=2, name="UI4 Tenant Two", subdomain="ui4-two", status="active"),
        ])
        db.session.add_all([
            User(
                id=2, email="ui4-owner@example.invalid", password_hash="synthetic-only",
                first_name="UI4", last_name="Owner", role="trader", tenant_id=1,
                parent_id=None, tree_path="2", level=0, is_active=True, is_verified=True,
            ),
            User(
                id=3, email="ui4-foreign@example.invalid", password_hash="synthetic-only",
                first_name="UI4", last_name="Foreign", role="trader", tenant_id=2,
                parent_id=None, tree_path="3", level=0, is_active=True, is_verified=True,
            ),
        ])
        db.session.flush()
        db.session.add_all([
            SupportTicket(
                id=50, ticket_number="TICKET-UI4-OWNED", user_id=2,
                email="ui4-owner@example.invalid", name="UI4 Owner",
                subject="Synthetic owned ticket", description="Synthetic detail",
                category="general", priority="medium", status="open",
            ),
            SupportTicket(
                id=51, ticket_number="TICKET-UI4-FOREIGN", user_id=3,
                email="ui4-foreign@example.invalid", name="UI4 Foreign",
                subject="Synthetic foreign ticket", description="Foreign detail",
                category="general", priority="medium", status="open",
            ),
            TicketMessage(
                ticket_id=50, user_id=2, email="ui4-owner@example.invalid", name="UI4 Owner",
                message="Synthetic customer message", is_staff=False, is_internal=False,
            ),
            TicketMessage(
                ticket_id=50, user_id=3, message="INTERNAL-SYNTHETIC-NOTE",
                is_staff=True, is_internal=True,
            ),
            Notification(
                id=60, user_id=2, type="system", title="Read synthetic notification",
                message="Synthetic notification 60", priority="normal", is_read=False,
                is_deleted=False,
            ),
            Notification(
                id=61, user_id=3, type="system", title="Foreign synthetic notification",
                message="Synthetic notification 61", priority="normal", is_read=False,
                is_deleted=False,
            ),
            Notification(
                id=62, user_id=2, type="kyc", title="Delete synthetic notification",
                message="Synthetic notification 62", priority="normal", is_read=False,
                is_deleted=False,
            ),
            Notification(
                id=63, user_id=2, type="payment", title="Read-all synthetic notification",
                message="Synthetic notification 63", priority="normal", is_read=False,
                is_deleted=False,
            ),
        ])
        db.session.commit()
        app.ui4_support_notification_tokens = {
            user_id: db.session.get(User, user_id).generate_access_token()
            for user_id in (2, 3)
        }

    try:
        yield app
    finally:
        with app.app_context():
            db.session.remove()
            db.metadata.drop_all(bind=db.engine, tables=list(reversed(tables)))
            db.engine.dispose()


def _headers(app, user_id=2):
    return {"Authorization": "Bearer " + app.ui4_support_notification_tokens[user_id]}


def _assert_owner(payload):
    assert payload["owner_context"] == EXPECTED_OWNER
    assert isinstance(payload["owner_context"]["user_id"], int)
    assert payload["owner_context"]["tenant_id"] is None or isinstance(
        payload["owner_context"]["tenant_id"], int
    )


def test_ui4_support_notification_payloads_real_factory_and_server_owner_context(
    ui4_support_notification_app, record_property,
):
    """Record all UI-4 customer payloads from real HTTP routes, never fixtures/mocks."""
    app = ui4_support_notification_app
    client = app.test_client()
    headers = _headers(app)
    payloads = {"support": {}, "notifications": {}}

    support_list = client.get(SUPPORT + "/my?page=1&per_page=20", headers=headers)
    assert support_list.status_code == 200, support_list.get_json()
    payloads["support"]["list"] = support_list.get_json()
    _assert_owner(payloads["support"]["list"])
    assert [row["user_id"] for row in payloads["support"]["list"]["tickets"]] == [2]

    detail_number = client.get(SUPPORT + "/TICKET-UI4-OWNED", headers=headers)
    assert detail_number.status_code == 200, detail_number.get_json()
    payloads["support"]["detail_number"] = detail_number.get_json()
    _assert_owner(payloads["support"]["detail_number"])
    assert payloads["support"]["detail_number"]["id"] == 50
    assert "INTERNAL-SYNTHETIC-NOTE" not in detail_number.get_data(as_text=True)

    detail_id = client.get(SUPPORT + "/50", headers=headers)
    assert detail_id.status_code == 200, detail_id.get_json()
    payloads["support"]["detail_id"] = detail_id.get_json()
    _assert_owner(payloads["support"]["detail_id"])
    assert payloads["support"]["detail_id"]["ticket_number"] == "TICKET-UI4-OWNED"

    created = client.post(
        SUPPORT + "/my",
        headers=headers,
        json={
            "subject": "UI4 created ticket",
            "description": "Synthetic create payload for parity",
            "category": "technical",
            "priority": "high",
        },
    )
    assert created.status_code == 201, created.get_json()
    payloads["support"]["create"] = created.get_json()
    _assert_owner(payloads["support"]["create"])
    ticket = payloads["support"]["create"]["ticket"]
    assert ticket["user_id"] == 2 and ticket["status"] == "open"

    reply = client.post(
        SUPPORT + f"/{ticket['ticket_number']}/messages",
        headers=headers,
        json={"message": "Synthetic customer reply"},
    )
    assert reply.status_code == 201, reply.get_json()
    payloads["support"]["reply"] = reply.get_json()
    _assert_owner(payloads["support"]["reply"])
    assert payloads["support"]["reply"]["ticket_number"] == ticket["ticket_number"]
    assert payloads["support"]["reply"]["ticket_message"] == {
        **payloads["support"]["reply"]["ticket_message"],
        "ticket_id": ticket["id"],
        "user_id": 2,
        "is_staff": False,
        "is_internal": False,
    }

    closed = client.post(SUPPORT + f"/{ticket['id']}/close", headers=headers, json={})
    assert closed.status_code == 200, closed.get_json()
    payloads["support"]["close"] = closed.get_json()
    _assert_owner(payloads["support"]["close"])
    assert payloads["support"]["close"]["ticket"]["status"] == "closed"

    rated = client.post(
        SUPPORT + f"/{ticket['id']}/rate",
        headers=headers,
        json={"rating": 5, "feedback": "Synthetic rating"},
    )
    assert rated.status_code == 200, rated.get_json()
    payloads["support"]["rate"] = rated.get_json()
    _assert_owner(payloads["support"]["rate"])
    assert payloads["support"]["rate"]["ticket"]["rating"] == 5

    notification_list = client.get(NOTIFICATIONS + "?page=1&per_page=20", headers=headers)
    assert notification_list.status_code == 200, notification_list.get_json()
    payloads["notifications"]["list"] = notification_list.get_json()
    _assert_owner(payloads["notifications"]["list"])
    assert {row["id"] for row in payloads["notifications"]["list"]["notifications"]} == {60, 62, 63}

    preferences_get = client.get(NOTIFICATIONS + "preferences", headers=headers)
    assert preferences_get.status_code == 200, preferences_get.get_json()
    payloads["notifications"]["preferences_get"] = preferences_get.get_json()
    _assert_owner(payloads["notifications"]["preferences_get"])
    assert payloads["notifications"]["preferences_get"]["persisted"] is False

    preferences_put = client.put(
        NOTIFICATIONS + "preferences",
        headers=headers,
        json={"in_app": {"kyc": False}, "settings": {"email_frequency": "daily"}},
    )
    assert preferences_put.status_code == 200, preferences_put.get_json()
    payloads["notifications"]["preferences_put"] = preferences_put.get_json()
    _assert_owner(payloads["notifications"]["preferences_put"])
    assert payloads["notifications"]["preferences_put"]["preferences"]["persisted"] is True

    unread_count = client.get(NOTIFICATIONS + "unread-count", headers=headers)
    assert unread_count.status_code == 200, unread_count.get_json()
    payloads["notifications"]["count"] = unread_count.get_json()
    _assert_owner(payloads["notifications"]["count"])
    assert payloads["notifications"]["count"]["count"] == 3

    marked_read = client.post(NOTIFICATIONS + "60/read", headers=headers)
    assert marked_read.status_code == 200, marked_read.get_json()
    payloads["notifications"]["read"] = marked_read.get_json()
    _assert_owner(payloads["notifications"]["read"])
    assert payloads["notifications"]["read"]["notification"]["id"] == 60
    assert payloads["notifications"]["read"]["notification"]["is_read"] is True

    deleted = client.delete(NOTIFICATIONS + "62", headers=headers)
    assert deleted.status_code == 200, deleted.get_json()
    payloads["notifications"]["delete"] = deleted.get_json()
    _assert_owner(payloads["notifications"]["delete"])
    assert payloads["notifications"]["delete"]["notification"]["id"] == 62
    assert payloads["notifications"]["delete"]["notification"]["is_deleted"] is True

    read_all = client.post(NOTIFICATIONS + "read-all", headers=headers)
    assert read_all.status_code == 200, read_all.get_json()
    payloads["notifications"]["read_all"] = read_all.get_json()
    _assert_owner(payloads["notifications"]["read_all"])
    assert payloads["notifications"]["read_all"]["message"] == "Notifications marked as read"
    assert payloads["notifications"]["read_all"]["count"] == 1

    # Client-selected tenant inputs never alter ownership: unsupported selectors
    # fail closed, while an unrelated header does not rewrite the JWT principal.
    assert client.get(SUPPORT + "/my?tenant_id=2", headers=headers).status_code == 400
    header_spoof = client.get(
        NOTIFICATIONS + "?page=1", headers={**headers, "X-Tenant-ID": "2"}
    )
    assert header_spoof.status_code == 200
    assert header_spoof.get_json()["owner_context"] == EXPECTED_OWNER
    assert client.get(SUPPORT + "/TICKET-UI4-FOREIGN", headers=headers).status_code == 404
    assert client.get(SUPPORT + "/51", headers=headers).status_code == 404
    assert client.post(NOTIFICATIONS + "61/read", headers=headers).status_code == 404
    assert client.delete(NOTIFICATIONS + "61", headers=headers).status_code == 404

    forbidden = {"email", "name", "assigned_to", "user", "assigned_user", "attachments", "last_message"}

    def assert_customer_allowlist(value):
        if isinstance(value, dict):
            assert not forbidden.intersection(value), value.keys()
            for nested in value.values():
                assert_customer_allowlist(nested)
        elif isinstance(value, list):
            for nested in value:
                assert_customer_allowlist(nested)

    for customer_payload in payloads["support"].values():
        assert_customer_allowlist(customer_payload)
    record_property("ui4_support_notification_payloads", json.dumps(payloads, sort_keys=True))


def test_ui4_support_notification_cookie_csrf_blocks_mutations_before_writes(
    ui4_support_notification_app,
):
    """Cookie JWT mutations retain the shared CSRF boundary and produce no writes."""
    from src.database import db
    from src.models.notification import Notification, NotificationPreference
    from src.models.support_ticket import SupportTicket, TicketMessage

    app = ui4_support_notification_app
    client = app.test_client()
    client.set_cookie("access_token", app.ui4_support_notification_tokens[2])
    with app.app_context():
        baseline = {
            "tickets": SupportTicket.query.count(),
            "messages": TicketMessage.query.count(),
            "read": db.session.get(Notification, 60).is_read,
            "deleted": db.session.get(Notification, 62).is_deleted,
            "preferences": NotificationPreference.query.count(),
        }

    responses = [
        client.post(SUPPORT + "/my", json={"subject": "blocked", "description": "blocked"}),
        client.post(SUPPORT + "/TICKET-UI4-OWNED/messages", json={"message": "blocked"}),
        client.post(NOTIFICATIONS + "60/read"),
        client.post(NOTIFICATIONS + "read-all"),
        client.delete(NOTIFICATIONS + "62"),
        client.put(NOTIFICATIONS + "preferences", json={"in_app": {"kyc": False}}),
    ]
    assert [response.status_code for response in responses] == [403] * len(responses)

    with app.app_context():
        assert SupportTicket.query.count() == baseline["tickets"]
        assert TicketMessage.query.count() == baseline["messages"]
        assert db.session.get(Notification, 60).is_read is baseline["read"]
        assert db.session.get(Notification, 62).is_deleted is baseline["deleted"]
        assert NotificationPreference.query.count() == baseline["preferences"]


def test_ui4_support_notification_reads_never_autoflush_unrelated_pending_data(
    ui4_support_notification_app,
):
    """Customer list/detail/notification reads must not write pending session state."""
    from src.database import db
    from src.models.support_ticket import TicketMessage

    app = ui4_support_notification_app
    client = app.test_client()
    writes = []

    def observe_write(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)

    with app.app_context():
        pending = TicketMessage(
            ticket_id=50, user_id=2, message="must remain pending", is_staff=False, is_internal=False,
        )
        db.session.add(pending)
        event.listen(db.engine, "before_cursor_execute", observe_write)
        try:
            for path in (
                SUPPORT + "/my",
                SUPPORT + "/TICKET-UI4-OWNED",
                SUPPORT + "/50",
                NOTIFICATIONS,
                NOTIFICATIONS + "unread-count",
                NOTIFICATIONS + "preferences",
            ):
                response = client.get(path, headers=_headers(app))
                assert response.status_code == 200, (path, response.get_json())
                _assert_owner(response.get_json())
            assert pending.id is None
            assert writes == []
        finally:
            event.remove(db.engine, "before_cursor_execute", observe_write)
            db.session.rollback()
