"""Retired historical supermaster bootstrap revision.

Revision ID: 003a
Revises: 003
Create Date: 2025-10-23

The revision ID is retained so existing Alembic histories remain interpretable.
It no longer creates a known privileged credential during schema migration.
"""


# revision identifiers, used by Alembic.
revision = '003a'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Keep the historical graph node without creating a login-capable account."""
    # Credential/bootstrap provisioning is intentionally outside Alembic DDL.


def downgrade() -> None:
    """Never delete a user selected only by a historical bootstrap identity."""
    # Existing deployments may have a legitimate account with that former address.
