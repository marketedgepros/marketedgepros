"""Add indexes for tables reachable in this migration lineage.

Revision ID: 007_add_performance_indexes
Revises: 006
Create Date: 2025-10-28

The historical file referenced commissions, referrals, and affiliate_links even
though no reachable earlier revision creates those tables.  This revision keeps
its identity but only creates deterministic indexes for tables in the graph.
Missing legacy model tables remain explicit schema-drift work, not silently
invented DDL in an index migration.
"""
from alembic import op


# revision identifiers
revision = '007_add_performance_indexes'
down_revision = '006'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index('ix_challenge_user_status', 'challenges', ['user_id', 'status'], unique=False)
    op.create_index('ix_challenge_program_id', 'challenges', ['program_id'], unique=False)
    op.create_index('ix_challenge_created_at', 'challenges', ['created_at'], unique=False)
    op.create_index('ix_user_role', 'users', ['role'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_user_role', table_name='users')
    op.drop_index('ix_challenge_created_at', table_name='challenges')
    op.drop_index('ix_challenge_program_id', table_name='challenges')
    op.drop_index('ix_challenge_user_status', table_name='challenges')
