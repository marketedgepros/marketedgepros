"""Challenge management tables.

Revision ID: 005
Revises: 004
Create Date: 2025-10-18

``challenges`` is owned by revision 001.  A historical duplicate CREATE TABLE
here made an empty-database upgrade impossible; this revision now creates only
its distinct tables and indexes the existing challenge table.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = '005'
down_revision = '004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'programs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('price', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=True),
        sa.Column('initial_balance', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('profit_target', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('max_daily_loss', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('max_total_loss', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('min_trading_days', sa.Integer(), nullable=True),
        sa.Column('max_trading_days', sa.Integer(), nullable=True),
        sa.Column('leverage', sa.String(length=20), nullable=True),
        sa.Column('allowed_instruments', sa.Text(), nullable=True),
        sa.Column('profit_split', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('program_type', sa.String(length=50), nullable=True),
        sa.Column('phase', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('is_featured', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_table(
        'payments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('currency', sa.String(length=3), nullable=True),
        sa.Column('payment_method', sa.String(length=50), nullable=True),
        sa.Column('transaction_id', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=50), nullable=True),
        sa.Column('purpose', sa.String(length=100), nullable=True),
        sa.Column('reference_id', sa.Integer(), nullable=True),
        sa.Column('provider_response', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('transaction_id'),
    )
    op.create_table(
        'trades',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('challenge_id', sa.Integer(), nullable=False),
        sa.Column('ticket', sa.String(length=100), nullable=True),
        sa.Column('symbol', sa.String(length=20), nullable=False),
        sa.Column('trade_type', sa.String(length=10), nullable=False),
        sa.Column('volume', sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column('open_price', sa.Numeric(precision=15, scale=5), nullable=False),
        sa.Column('close_price', sa.Numeric(precision=15, scale=5), nullable=True),
        sa.Column('stop_loss', sa.Numeric(precision=15, scale=5), nullable=True),
        sa.Column('take_profit', sa.Numeric(precision=15, scale=5), nullable=True),
        sa.Column('profit', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('commission', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('swap', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('open_time', sa.DateTime(), nullable=False),
        sa.Column('close_time', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['challenge_id'], ['challenges.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ticket'),
    )
    op.create_index('idx_programs_active', 'programs', ['is_active'])
    op.create_index('idx_challenges_user', 'challenges', ['user_id'])
    op.create_index('idx_challenges_status', 'challenges', ['status'])
    op.create_index('idx_payments_user', 'payments', ['user_id'])
    op.create_index('idx_payments_status', 'payments', ['status'])
    op.create_index('idx_trades_challenge', 'trades', ['challenge_id'])


def downgrade() -> None:
    op.drop_index('idx_trades_challenge', table_name='trades')
    op.drop_index('idx_payments_status', table_name='payments')
    op.drop_index('idx_payments_user', table_name='payments')
    op.drop_index('idx_challenges_status', table_name='challenges')
    op.drop_index('idx_challenges_user', table_name='challenges')
    op.drop_index('idx_programs_active', table_name='programs')
    op.drop_table('trades')
    op.drop_table('payments')
    op.drop_table('programs')
