"""Add missing user schema without assigning identity or inventing balances.

Revision ID: 20261011_000004
Revises: 20261011_000003

Existing rows receive can_create_same_role=False; no role or parent is changed.
Financial fields are nullable and have no server default or data backfill. NULL
means unknown, not a reconstructed zero balance. Python model defaults are not
changed. Existing deployments with any column collision require reconciliation
before this revision; no partial/adoptive migration is attempted.
"""
from alembic import op
import sqlalchemy as sa

revision = '20261011_000004'
down_revision = '20261011_000003'
branch_labels = None
depends_on = None

COLUMNS = ('can_create_same_role', 'available_balance', 'total_withdrawn', 'payout_count')


def upgrade():
    if not op.get_context().as_sql:
        existing = {column['name'] for column in sa.inspect(op.get_bind()).get_columns('users')}
        collisions = sorted(existing.intersection(COLUMNS))
        if collisions:
            raise RuntimeError('User schema reconciliation required before upgrade: ' + ', '.join(collisions))
    op.add_column('users', sa.Column('can_create_same_role', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('users', sa.Column('available_balance', sa.Numeric(12, 2), nullable=True))
    op.add_column('users', sa.Column('total_withdrawn', sa.Numeric(12, 2), nullable=True))
    op.add_column('users', sa.Column('payout_count', sa.Integer(), nullable=True))


def downgrade():
    guard = """
        SELECT EXISTS (
            SELECT 1 FROM users WHERE can_create_same_role IS TRUE
                OR available_balance IS NOT NULL OR total_withdrawn IS NOT NULL
                OR payout_count IS NOT NULL
        )
    """
    if op.get_context().as_sql:
        # Offline reversal must enforce the same guard, not bypass the data gate.
        op.execute("""DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM users WHERE can_create_same_role IS TRUE
                OR available_balance IS NOT NULL OR total_withdrawn IS NOT NULL
                OR payout_count IS NOT NULL) THEN
                RAISE EXCEPTION 'User schema downgrade refused: populated fields require preservation';
            END IF;
        END $$""")
    elif op.get_bind().execute(sa.text(guard)).scalar_one():
        raise RuntimeError('User schema downgrade refused: populated fields require preservation')
    for column in reversed(COLUMNS):
        op.drop_column('users', column)
