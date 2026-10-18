"""Harden token_version for deployments that applied the historical token root.

Revision ID: 20261011_000002
Revises: 20261011_000001
Create Date: 2026-10-11 00:00:02

The historical token blacklist revision may already be recorded with nullable
``users.token_version``.  This additive revision preserves every user and only
normalizes NULL token versions to the existing semantic default before enforcing
the invariant for future writes.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20261011_000002"
down_revision = "20261011_000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE users SET token_version = 0 WHERE token_version IS NULL")
    op.alter_column(
        "users",
        "token_version",
        existing_type=sa.Integer(),
        nullable=False,
        server_default=sa.text("0"),
    )


def downgrade() -> None:
    # Schema-only reversal: preserve normalized values and every user row.
    op.alter_column(
        "users",
        "token_version",
        existing_type=sa.Integer(),
        nullable=True,
        server_default=sa.text("0"),
    )
