"""Retired historical bootstrap data revision.

Revision ID: 002
Revises: 001
Create Date: 2025-10-17 09:05:00.000000

This revision intentionally retains its historical identity.  New installations
must provision tenants, products, and administrator identities through an
explicit, separately authorised bootstrap process; schema migrations do not
create business fixtures or login credentials.
"""
from alembic import op


# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Preserve historical graph identity without creating default business data.

    Deployments that applied the former revision already retain their data:
    changing this source file does not retroactively remove or alter it.
    """
    # Deliberately no schema or data operation.  Demo data is not migration data.


def downgrade() -> None:
    """Do not delete tenant, product, add-on, or user rows by guessed identity."""
    # Deliberately no data deletion.  Rows may be legitimate operator-managed data.
