"""PostgreSQL canaries for the bounded public catalog and immutable quote parity."""
from sqlalchemy import text

from test_order_quote_concurrency import quote_database


def test_program_catalog_postgresql_head_and_quote_parity(staging_resources, monkeypatch, record_property):
    """The real current migration head permits only explicitly enabled quote reads."""
    from src.database import db
    from src.models.user import User
    from src.services.order_service import OrderError, OrderService
    from src.services.program_catalog_service import ProgramCatalogService

    with quote_database(staging_resources, monkeypatch, revision='heads') as app:
        assert app.config["ORDER_QUOTES_ENABLED"] is True
        assert app.config["ORDER_QUOTE_CURRENCY"] == "USD"
        with app.app_context():
            # The helper upgrades this private database to the actual Alembic head,
            # not merely the frozen purchase-order revision.
            assert db.session.execute(text("SELECT version_num FROM alembic_version")).scalars().all() == [
                "20261013_000002"
            ]

            # A historical merge-head label is whitelisted syntactically but lacks
            # the original immutable trigger attestation and must remain unavailable.
            db.session.execute(text("UPDATE alembic_version SET version_num = '20261011_000001'"))
            db.session.commit()
            with app.test_request_context("/api/v1/orders/"):
                try:
                    OrderService.create_quote(
                        db.session.get(User, 2), {"program_id": 10}, "catalog_pg_old_head_0001"
                    )
                except OrderError as error:
                    assert error.code == "ORDER_STORAGE_NOT_READY"
                else:
                    raise AssertionError("quote unexpectedly accepted a non-attested historical head")
                db.session.rollback()

            db.session.execute(text("UPDATE alembic_version SET version_num = '20261013_000002'"))
            db.session.commit()
            with app.test_request_context("/api/v1/programs/10"):
                catalog = ProgramCatalogService.get_program(10)
                order, created = OrderService.create_quote(
                    db.session.get(User, 2), {"program_id": 10, "addon_ids": [20]},
                    "catalog_pg_head_parity_0001",
                )
                db.session.commit()
                serialized = order.to_dict()
                snapshot = serialized["snapshot"]
                assert serialized["user_id"] == snapshot["user_id"] == 2
                assert serialized["tenant_id"] == snapshot["tenant_id"] == 1
                import json
                record_property("catalog_detail_json", json.dumps(catalog, sort_keys=True))
                record_property("quote_response_json", json.dumps({"order": serialized, "replayed": False}, sort_keys=True))

        assert created is True
        assert catalog["currency"] == "USD"
        assert catalog["price"] == snapshot["base_amount"] == "19.99"
        assert catalog["terms"] == snapshot["terms"]
        assert catalog["addons"] == [{
            "id": 20,
            "program_id": 10,
            "name": "Synthetic Add-on",
            "description": None,
            "price": "10.00",
            "price_type": "percentage",
            "benefits": {},
            "is_active": True,
        }]
