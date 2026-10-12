"""PostgreSQL staging contract for the UI-4 KYC administration closure.

The staging runner performs the repository's offline Alembic migration inventory
before this test begins, then supplies an isolated PostgreSQL schema.  This test
uses that real PostgreSQL path and synthetic rows only; it is intentionally not run
by an individual domain worker.
"""
from datetime import datetime, timedelta

from sqlalchemy import event, select
from werkzeug.datastructures import MultiDict


def test_ui4_closure_kyc_postgresql_snapshot_scope_and_recorded_document_review(app, staging_resources):
    from src.database import db
    from src.models.tenant import Tenant
    from src.models.user import User
    from src.services.admin_closure_kyc import AdminClosureKycService

    assert staging_resources["pg_url"].startswith("postgresql+")
    with app.app_context():
        assert db.engine.dialect.name == "postgresql"
        app.config["PLATFORM_ROOT_USER_ID"] = 1
        instant = datetime(2026, 10, 12, 12, 0, 0)
        db.session.add_all([
            Tenant(id=1, name="KYC One", subdomain="kyc-one", status="active"),
            Tenant(id=2, name="KYC Two", subdomain="kyc-two", status="active"),
            User(id=1, email="root@example.invalid", password_hash="x", first_name="Root", last_name="One",
                 role="supermaster", tenant_id=1, parent_id=None, tree_path="1", level=0,
                 can_create_same_role=True, is_active=True, is_verified=True),
            User(id=2, email="master@example.invalid", password_hash="x", first_name="Master", last_name="Two",
                 role="master", tenant_id=1, parent_id=1, tree_path="1/2", level=1,
                 is_active=True, is_verified=True),
            User(id=3, email="subject@example.invalid", password_hash="x", first_name="Subject", last_name="Three",
                 role="trader", tenant_id=1, parent_id=2, tree_path="1/2/3", level=2,
                 is_active=True, is_verified=True, kyc_status="pending",
                 kyc_submitted_at=instant + timedelta(minutes=1), kyc_id_status="pending",
                 kyc_id_uploaded_at=instant, kyc_id_url="local-kyc:kyc/3/id_proof_20261012_120000.pdf"),
            User(id=4, email="foreign@example.invalid", password_hash="x", first_name="Foreign", last_name="Four",
                 role="trader", tenant_id=2, parent_id=None, tree_path="4", level=0,
                 is_active=True, is_verified=True, kyc_status="pending",
                 kyc_submitted_at=instant + timedelta(minutes=2)),
        ])
        db.session.commit()
        root = db.session.get(User, 1)
        master = db.session.get(User, 2)

        statements = []
        def observe(_connection, _cursor, statement, _parameters, _context, _executemany):
            statements.append(statement)
        event.listen(db.engine, "before_cursor_execute", observe)
        try:
            arguments = AdminClosureKycService.parse_submissions_query(MultiDict({"page": "1", "per_page": "20", "status": "pending"}))
            root_page = AdminClosureKycService.submissions(root, arguments)
            master_page = AdminClosureKycService.submissions(master, arguments)
        finally:
            event.remove(db.engine, "before_cursor_execute", observe)
        assert [row["user_id"] for row in root_page["submissions"]] == [3]
        assert [row["user_id"] for row in master_page["submissions"]] == [3]
        assert root_page["owner_context"] == {"user_id": 1, "tenant_id": 1}
        assert master_page["owner_context"] == {"user_id": 2, "tenant_id": 1}
        assert root_page["pagination"] == {"page": 1, "per_page": 20, "total": 1, "pages": 1}
        assert sum("SET LOCAL statement_timeout = 1500" in statement for statement in statements) == 2

        review = AdminClosureKycService.parse_document_review({
            "status": "approved", "notes": "reviewed", "acknowledgement": "REVIEW 3 id_proof",
            "expected_uploaded_at": instant.isoformat(),
        }, user_id=3, document_type="id_proof")
        persisted = AdminClosureKycService.review_document(master, 3, "id_proof", review)
        assert persisted["review_recorded"] is True
        assert persisted["document"]["status"] == "approved"
        row = db.session.execute(select(User.kyc_id_status, User.kyc_id_notes, User.kyc_status).where(User.id == 3)).one()
        assert row == ("approved", "reviewed", "pending")
