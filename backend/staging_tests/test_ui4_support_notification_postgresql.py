"""UI-4 support/notification PostgreSQL parity on runner-created synthetic resources."""
from __future__ import annotations

import json


def _user(identity, email, tenant_id):
    from src.models.user import User

    return User(
        id=identity,
        email=email,
        password_hash="synthetic-staging-only",
        first_name="UI4",
        last_name="Staging",
        role="trader",
        tenant_id=tenant_id,
        parent_id=None,
        tree_path=str(identity),
        level=0,
        is_active=True,
        is_verified=True,
    )


def test_ui4_support_notification_postgresql_owner_payloads(app, staging_resources, record_property):
    """Exercise real routes against the isolated PostgreSQL/Redis staging factory."""
    from src.database import db
    from src.models.notification import Notification
    from src.models.support_ticket import SupportTicket
    from src.models.tenant import Tenant

    with app.app_context():
        db.session.add_all([
            Tenant(id=1, name="UI4 Staging One", subdomain="ui4-staging-one", status="active"),
            Tenant(id=2, name="UI4 Staging Two", subdomain="ui4-staging-two", status="active"),
        ])
        db.session.add_all([
            _user(2, "ui4-staging-owner@example.invalid", 1),
            _user(3, "ui4-staging-foreign@example.invalid", 2),
        ])
        db.session.flush()
        db.session.add_all([
            SupportTicket(
                id=50,
                ticket_number="TICKET-UI4-STAGE",
                user_id=2,
                email="ui4-staging-owner@example.invalid",
                name="UI4 Staging",
                subject="Staging owned ticket",
                description="Synthetic staging support ticket",
                category="general",
                priority="medium",
                status="open",
            ),
            SupportTicket(
                id=51,
                ticket_number="TICKET-UI4-FOREIGN",
                user_id=3,
                email="ui4-staging-foreign@example.invalid",
                name="UI4 Foreign",
                subject="Staging foreign ticket",
                description="Synthetic foreign support ticket",
                category="general",
                priority="medium",
                status="open",
            ),
            Notification(
                id=60,
                user_id=2,
                type="system",
                title="Read",
                message="Synthetic notification 60",
                priority="normal",
                is_read=False,
                is_deleted=False,
            ),
            Notification(
                id=61,
                user_id=2,
                type="kyc",
                title="Delete",
                message="Synthetic notification 61",
                priority="normal",
                is_read=False,
                is_deleted=False,
            ),
            Notification(
                id=62,
                user_id=2,
                type="payment",
                title="Read all",
                message="Synthetic notification 62",
                priority="normal",
                is_read=False,
                is_deleted=False,
            ),
            Notification(
                id=63,
                user_id=3,
                type="system",
                title="Foreign",
                message="Synthetic notification 63",
                priority="normal",
                is_read=False,
                is_deleted=False,
            ),
        ])
        db.session.commit()
        from src.models.user import User
        owner_token = db.session.get(User, 2).generate_access_token()

    expected_owner = {"user_id": 2, "tenant_id": 1}
    client = app.test_client()
    headers = {"Authorization": "Bearer " + owner_token}
    payloads = {"support": {}, "notifications": {}}

    def request(name, method, path, *, bucket, **kwargs):
        response = getattr(client, method)(path, headers=headers, **kwargs)
        assert response.status_code in {200, 201}, response.get_json()
        body = response.get_json()
        assert body["owner_context"] == expected_owner
        bucket[name] = body
        return body

    support = "/api/v1/support/tickets"
    notifications = "/api/v1/notifications/"
    request("list", "get", support + "/my?per_page=20", bucket=payloads["support"])
    detail_number = request("detail_number", "get", support + "/TICKET-UI4-STAGE", bucket=payloads["support"])
    assert detail_number["id"] == 50
    detail_id = request("detail_id", "get", support + "/50", bucket=payloads["support"])
    assert detail_id["ticket_number"] == "TICKET-UI4-STAGE"
    created = request(
        "create",
        "post",
        support + "/my",
        bucket=payloads["support"],
        json={"subject": "Create", "description": "Synthetic create", "category": "technical", "priority": "high"},
    )
    ticket = created["ticket"]
    reply = request(
        "reply",
        "post",
        support + f"/{ticket['ticket_number']}/messages",
        bucket=payloads["support"],
        json={"message": "Synthetic reply"},
    )
    assert reply["ticket_number"] == ticket["ticket_number"]
    closed = request("close", "post", support + f"/{ticket['id']}/close", bucket=payloads["support"], json={})
    assert closed["ticket"]["status"] == "closed"
    rated = request(
        "rate",
        "post",
        support + f"/{ticket['id']}/rate",
        bucket=payloads["support"],
        json={"rating": 4, "feedback": "Synthetic staging rating"},
    )
    assert rated["ticket"]["rating"] == 4

    request("list", "get", notifications + "?per_page=20", bucket=payloads["notifications"])
    preferences_get = request("preferences_get", "get", notifications + "preferences", bucket=payloads["notifications"])
    assert preferences_get["persisted"] is False
    preferences_put = request(
        "preferences_put",
        "put",
        notifications + "preferences",
        bucket=payloads["notifications"],
        json={"in_app": {"kyc": False}},
    )
    assert preferences_put["preferences"]["persisted"] is True
    counted = request("count", "get", notifications + "unread-count", bucket=payloads["notifications"])
    assert counted["count"] == 3
    read = request("read", "post", notifications + "60/read", bucket=payloads["notifications"])
    assert read["notification"]["is_read"] is True
    deleted = request("delete", "delete", notifications + "61", bucket=payloads["notifications"])
    assert deleted["notification"]["is_deleted"] is True
    read_all = request("read_all", "post", notifications + "read-all", bucket=payloads["notifications"])
    assert read_all["message"] == "Notifications marked as read"
    assert read_all["count"] == 1

    assert client.get(support + "/TICKET-UI4-FOREIGN", headers=headers).status_code == 404
    assert client.post(notifications + "63/read", headers=headers).status_code == 404
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
    record_property("ui4_support_notification_postgresql_payloads", json.dumps(payloads, sort_keys=True))
