"""Add hierarchy and referral code support to users

Revision ID: 006
Revises: 005
Create Date: 2025-10-23 03:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add hierarchy and referral code columns to users table"""
    
    # Add parent_id for hierarchy (who created this user)
    op.add_column('users', sa.Column('parent_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_users_parent_id'), 'users', ['parent_id'], unique=False)
    op.create_foreign_key('fk_users_parent_id', 'users', 'users', ['parent_id'], ['id'])
    
    # Add level for hierarchy depth (0 = top level)
    op.add_column('users', sa.Column('level', sa.Integer(), nullable=False, server_default='0'))
    op.create_index(op.f('ix_users_level'), 'users', ['level'], unique=False)
    
    # Add tree_path for fast hierarchy queries (e.g., "1/5/23/45")
    op.add_column('users', sa.Column('tree_path', sa.String(length=500), nullable=True))
    op.create_index(op.f('ix_users_tree_path'), 'users', ['tree_path'], unique=False)
    
    # Add commission_rate for custom commission rates
    op.add_column('users', sa.Column('commission_rate', sa.Numeric(precision=5, scale=2), nullable=True, server_default='0.00'))
    
    # Add referral_code for agents/masters (unique 8-character code)
    op.add_column('users', sa.Column('referral_code', sa.String(length=20), nullable=True))
    op.create_index(op.f('ix_users_referral_code'), 'users', ['referral_code'], unique=True)
    
    # Add KYC approval/rejection fields that were missing
    op.add_column('users', sa.Column('kyc_approved_at', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('kyc_approved_by', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('kyc_rejected_at', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('kyc_rejected_by', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('kyc_rejection_reason', sa.Text(), nullable=True))
    op.add_column('users', sa.Column('kyc_admin_notes', sa.Text(), nullable=True))
    
    # Add KYC document fields
    op.add_column('users', sa.Column('kyc_id_status', sa.String(length=20), nullable=True, server_default='not_uploaded'))
    op.add_column('users', sa.Column('kyc_id_url', sa.String(length=500), nullable=True))
    op.add_column('users', sa.Column('kyc_id_uploaded_at', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('kyc_id_notes', sa.Text(), nullable=True))
    
    op.add_column('users', sa.Column('kyc_address_status', sa.String(length=20), nullable=True, server_default='not_uploaded'))
    op.add_column('users', sa.Column('kyc_address_url', sa.String(length=500), nullable=True))
    op.add_column('users', sa.Column('kyc_address_uploaded_at', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('kyc_address_notes', sa.Text(), nullable=True))
    
    op.add_column('users', sa.Column('kyc_selfie_status', sa.String(length=20), nullable=True, server_default='not_uploaded'))
    op.add_column('users', sa.Column('kyc_selfie_url', sa.String(length=500), nullable=True))
    op.add_column('users', sa.Column('kyc_selfie_uploaded_at', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('kyc_selfie_notes', sa.Text(), nullable=True))
    
    op.add_column('users', sa.Column('kyc_bank_status', sa.String(length=20), nullable=True, server_default='not_uploaded'))
    op.add_column('users', sa.Column('kyc_bank_url', sa.String(length=500), nullable=True))
    op.add_column('users', sa.Column('kyc_bank_uploaded_at', sa.DateTime(), nullable=True))
    op.add_column('users', sa.Column('kyc_bank_notes', sa.Text(), nullable=True))
    
    # avatar_url is owned by revision 003; do not add it again here.


def downgrade() -> None:
    """Remove hierarchy and referral code columns from users table"""
    
    # Remove KYC document fields
    op.drop_column('users', 'kyc_bank_notes')
    op.drop_column('users', 'kyc_bank_uploaded_at')
    op.drop_column('users', 'kyc_bank_url')
    op.drop_column('users', 'kyc_bank_status')
    
    op.drop_column('users', 'kyc_selfie_notes')
    op.drop_column('users', 'kyc_selfie_uploaded_at')
    op.drop_column('users', 'kyc_selfie_url')
    op.drop_column('users', 'kyc_selfie_status')
    
    op.drop_column('users', 'kyc_address_notes')
    op.drop_column('users', 'kyc_address_uploaded_at')
    op.drop_column('users', 'kyc_address_url')
    op.drop_column('users', 'kyc_address_status')
    
    op.drop_column('users', 'kyc_id_notes')
    op.drop_column('users', 'kyc_id_uploaded_at')
    op.drop_column('users', 'kyc_id_url')
    op.drop_column('users', 'kyc_id_status')
    
    # Remove KYC approval/rejection fields
    op.drop_column('users', 'kyc_admin_notes')
    op.drop_column('users', 'kyc_rejection_reason')
    op.drop_column('users', 'kyc_rejected_by')
    op.drop_column('users', 'kyc_rejected_at')
    op.drop_column('users', 'kyc_approved_by')
    op.drop_column('users', 'kyc_approved_at')
    
    # Remove hierarchy and referral columns
    op.drop_index(op.f('ix_users_referral_code'), table_name='users')
    op.drop_column('users', 'referral_code')
    
    op.drop_column('users', 'commission_rate')
    
    op.drop_index(op.f('ix_users_tree_path'), table_name='users')
    op.drop_column('users', 'tree_path')
    
    op.drop_index(op.f('ix_users_level'), table_name='users')
    op.drop_column('users', 'level')
    
    op.drop_constraint('fk_users_parent_id', 'users', type_='foreignkey')
    op.drop_index(op.f('ix_users_parent_id'), table_name='users')
    op.drop_column('users', 'parent_id')

