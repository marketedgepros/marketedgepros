"""Focused catalog-tamper checks for frozen affiliate and ledger index definitions."""
from __future__ import annotations

import importlib

import pytest
from sqlalchemy import text

from test_affiliate_lifecycle_service import lifecycle_app


def _affiliate_oids(connection, tables):
    rows = connection.execute(text("""
        SELECT relation.relname, relation.oid
        FROM pg_catalog.pg_class AS relation
        JOIN pg_catalog.pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'public' AND relation.relname = ANY(:tables)
    """), {"tables": list(tables)}).all()
    return {name: int(oid) for name, oid in rows}


def test_runtime_rejects_valid_ledger_index_with_shadow_sorting(lifecycle_app):
    """A same-name, valid index with DESC must not satisfy the frozen btree contract."""
    from src.database import db
    from src.services.affiliate_lifecycle_storage import _index_rows, validate_storage

    with lifecycle_app.app_context():
        db.session.remove()
        with db.engine.begin() as connection:
            validate_storage(connection)
            connection.execute(text("DROP INDEX public.ix_entry_journal"))
            connection.execute(text("""
                CREATE INDEX ix_entry_journal
                ON public.settlement_entries (journal_id DESC)
            """))
            index = next(item for item in _index_rows(connection, "settlement_entries")
                         if item["name"] == "ix_entry_journal")
            assert index["is_valid"] and index["is_ready"] and index["is_live"]
            assert index["columns"] == "journal_id"
            assert index["all_sort_options_zero"] is False
            with pytest.raises(RuntimeError, match=r"settlement_entries\.index_definition"):
                validate_storage(connection)


def test_downgrade_preflight_rejects_nondefault_unique_operator_class(lifecycle_app):
    """The ownership preflight refuses a standalone index using a pattern opclass."""
    from src.database import db

    migration = importlib.import_module("migrations.versions.20261012_000001_affiliate_lifecycle")
    with lifecycle_app.app_context():
        db.session.remove()
        with db.engine.begin() as connection:
            oids = _affiliate_oids(connection, migration.TABLES)
            assert set(oids) == set(migration.TABLES)
            assert not migration._ownership_errors(connection, oids)
            connection.execute(text("""
                CREATE INDEX affiliate_order_attributions_order_pattern
                ON public.affiliate_order_attributions (order_id varchar_pattern_ops)
            """))
            errors = migration._ownership_errors(connection, oids)
            assert "affiliate_order_attributions.unowned_index_definition" in errors
            assert "affiliate_order_attributions.indexes" in errors
