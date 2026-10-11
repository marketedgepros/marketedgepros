"""Merge the historical application and token-blacklist heads.

Revision ID: 20261011_000001
Revises: 20251110_191500, token_blacklist_001
Create Date: 2026-10-11 00:00:01

This is an explicit graph merge.  It neither stamps a database nor removes
historical revisions; Alembic records it only after both parent heads apply.
"""

# revision identifiers, used by Alembic.
revision = '20261011_000001'
down_revision = ('20251110_191500', 'token_blacklist_001')
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Merge-only revision; schema operations belong to their owning revisions."""


def downgrade() -> None:
    """Split only Alembic graph state; parent revisions own their schema changes."""
