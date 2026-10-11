"""Inventory migration topology only; SQL generation is performed by the runner with --sql."""
from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


BACKEND = Path(__file__).resolve().parents[1]


def test_alembic_inventory_records_the_current_disconnected_token_blacklist_head():
    config = Config(str(BACKEND / "migrations" / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    script = ScriptDirectory.from_config(config)
    revisions = {revision.revision: revision.down_revision for revision in script.walk_revisions()}
    heads = set(script.get_heads())

    assert revisions["001"] is None
    assert revisions["20251110_191500"] == "007_add_performance_indexes"
    assert revisions["token_blacklist_001"] is None
    assert "20251110_191500" in heads
    assert "token_blacklist_001" in heads
    assert len(heads) == 2, "a merge migration is required before an online upgrade can have one head"
