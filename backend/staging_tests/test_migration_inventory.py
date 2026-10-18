"""Inventory the explicit two-root dependency graph and its singleton merge head."""
from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


BACKEND = Path(__file__).resolve().parents[1]
MERGE_REVISION = "20261011_000001"
SCHEMA_COMPLETION_REVISION = "20261011_000003"
USER_SCHEMA_REVISION = "20261011_000004"
CORE_SCHEMA_REVISION = "20261011_000005"
PURCHASE_ORDER_REVISION = "20261011_000006"
SETTLEMENT_LEDGER_REVISION = "20261011_000007"
TRADING_PROTOCOL_REVISION = "20261011_000008"
AFFILIATE_LIFECYCLE_REVISION = "20261012_000001"
PROGRAM_NULL_PRESERVATION_REVISION = "20261013_000001"
HEAD = "20261013_000002"


def test_alembic_inventory_records_roots_dependencies_and_explicit_merge_head():
    config = Config(str(BACKEND / "migrations" / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    script = ScriptDirectory.from_config(config)
    revisions = {revision.revision: revision for revision in script.walk_revisions()}

    assert len(revisions) == 21
    assert revisions["001"].down_revision is None
    assert revisions["20251110_191500"].down_revision == "007_add_performance_indexes"
    assert revisions["token_blacklist_001"].down_revision is None
    assert revisions["token_blacklist_001"].dependencies == "001"
    assert revisions[MERGE_REVISION].down_revision == ("20251110_191500", "token_blacklist_001")
    assert revisions["20261011_000002"].down_revision == MERGE_REVISION
    assert revisions[SCHEMA_COMPLETION_REVISION].down_revision == "20261011_000002"
    assert revisions[USER_SCHEMA_REVISION].down_revision == SCHEMA_COMPLETION_REVISION
    assert revisions[CORE_SCHEMA_REVISION].down_revision == USER_SCHEMA_REVISION
    assert revisions[PURCHASE_ORDER_REVISION].down_revision == CORE_SCHEMA_REVISION
    assert revisions[SETTLEMENT_LEDGER_REVISION].down_revision == PURCHASE_ORDER_REVISION
    assert revisions[TRADING_PROTOCOL_REVISION].down_revision == SETTLEMENT_LEDGER_REVISION
    assert revisions[AFFILIATE_LIFECYCLE_REVISION].down_revision == TRADING_PROTOCOL_REVISION
    assert revisions[PROGRAM_NULL_PRESERVATION_REVISION].down_revision == AFFILIATE_LIFECYCLE_REVISION
    assert revisions[HEAD].down_revision == PROGRAM_NULL_PRESERVATION_REVISION
    assert script.get_heads() == [HEAD]
