"""Create the model tables absent from the historical Alembic graph.

Revision ID: 20261011_000003
Revises: 20261011_000002
Create Date: 2026-10-11 00:00:03

This is a source-reviewed static snapshot of all 34 active model tables that
were absent from a clean upgrade through 20261011_000002.  It deliberately
creates no rows, applies no defaults/backfills to existing tables, imports no
application models, and does not call metadata.create_all().  Existing-table
collisions fail closed: deployments with historical out-of-band tables require
a separately reviewed baseline/compatibility plan, not automatic adoption.
"""
from __future__ import annotations

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20261011_000003"
down_revision = "20261011_000002"
branch_labels = None
depends_on = None

OWNED_TABLES = (
    'affiliate_commissions',
    'affiliate_links',
    'affiliate_payouts',
    'affiliate_referrals',
    'affiliate_settings',
    'agents',
    'blog_posts',
    'commissions',
    'course_enrollments',
    'email_queue',
    'faqs',
    'lead_activities',
    'lead_notes',
    'leads',
    'monitoring_alerts',
    'monitoring_events',
    'mt5_accounts',
    'mt5_positions',
    'mt5_trades',
    'notification_preferences',
    'notifications',
    'payment_approval_requests',
    'payment_methods',
    'payout_requests',
    'referrals',
    'roles',
    'support_articles',
    'support_tickets',
    'ticket_messages',
    'transactions',
    'verification_attempts',
    'violation_logs',
    'wallets',
    'withdrawals',
)


def _existing_public_tables(bind) -> set[str]:
    """Return public tables once, before any DDL, for an all-or-nothing gate."""
    return set(sa.inspect(bind).get_table_names(schema="public"))


def _preflight_upgrade() -> None:
    # SQL generation has no database catalog to inspect.  Online upgrades must
    # reject every collision before creating even the first table.
    if context.is_offline_mode():
        return
    collisions = sorted(set(OWNED_TABLES) & _existing_public_tables(op.get_bind()))
    if collisions:
        raise RuntimeError(
            "20261011_000003 refuses to adopt existing model tables; "
            "planned baseline/compatibility review required for: " + ", ".join(collisions)
        )


def _preflight_downgrade() -> None:
    """Fail closed before any drop when ownership or data safety is uncertain."""
    if context.is_offline_mode():
        # A SQL script has no catalog or row visibility, so it cannot prove both
        # that every table is owned by this revision and that none contains data.
        # Refuse to emit destructive SQL rather than make an unsafe promise.
        raise RuntimeError(
            "20261011_000003 offline downgrade is unsupported; "
            "run the online ownership/data preflight on an isolated reviewed target"
        )
    bind = op.get_bind()
    existing = _existing_public_tables(bind)
    missing = sorted(set(OWNED_TABLES) - existing)
    if missing:
        raise RuntimeError(
            "20261011_000003 downgrade refuses partial ownership; missing: " + ", ".join(missing)
        )
    nonempty = []
    for table_name in OWNED_TABLES:
        # Names are immutable source constants, not user/database values.
        has_rows = bind.execute(sa.text(f'SELECT EXISTS (SELECT 1 FROM "{table_name}" LIMIT 1)')).scalar_one()
        if has_rows:
            nonempty.append(table_name)
    if nonempty:
        raise RuntimeError(
            "20261011_000003 downgrade refuses to delete rows from owned tables: "
            + ", ".join(sorted(nonempty))
        )


def upgrade() -> None:
    _preflight_upgrade()
    op.create_table("affiliate_links",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=True),
        sa.Column('clicks', sa.Integer(), nullable=True),
        sa.Column('conversions', sa.Integer(), nullable=True),
        sa.Column('total_revenue', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('total_commission', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('commission_rate', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('last_click_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_affiliate_links_user_id_users'),
    )

    op.create_table("affiliate_payouts",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('affiliate_user_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('method', sa.String(length=50), nullable=True),
        sa.Column('payment_details', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('transaction_id', sa.String(length=100), nullable=True),
        sa.Column('requested_at', sa.DateTime(), nullable=True),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['affiliate_user_id'], ['users.id'], name='fk_affiliate_payouts_affiliate_user_id_users'),
    )

    op.create_table("affiliate_settings",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('default_commission_rate', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('min_payout_amount', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('cookie_duration_days', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('auto_approve_affiliates', sa.Boolean(), nullable=True),
        sa.Column('auto_approve_commissions', sa.Boolean(), nullable=True),
        sa.Column('terms_and_conditions', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )

    op.create_table("agents",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('agent_code', sa.String(length=50), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('commission_rate', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('total_earned', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('total_withdrawn', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('pending_balance', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('referral_count', sa.Integer(), nullable=False),
        sa.Column('active_referrals', sa.Integer(), nullable=False),
        sa.Column('total_sales', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_agents_user_id_users'),
    )

    op.create_table("blog_posts",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('slug', sa.String(length=250), nullable=False),
        sa.Column('excerpt', sa.Text(), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('featured_image', sa.String(length=500), nullable=True),
        sa.Column('featured_image_alt', sa.String(length=200), nullable=True),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('tags', sa.String(length=500), nullable=True),
        sa.Column('meta_title', sa.String(length=200), nullable=True),
        sa.Column('meta_description', sa.String(length=300), nullable=True),
        sa.Column('meta_keywords', sa.String(length=500), nullable=True),
        sa.Column('author_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.Column('view_count', sa.Integer(), nullable=True),
        sa.Column('featured', sa.Boolean(), nullable=True),
        sa.Column('reading_time', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], name='fk_blog_posts_author_id_users'),
    )

    op.create_table("course_enrollments",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('enrolled_at', sa.DateTime(), nullable=False),
        sa.Column('module_1_sent', sa.Boolean(), nullable=True),
        sa.Column('module_1_sent_at', sa.DateTime(), nullable=True),
        sa.Column('module_2_sent', sa.Boolean(), nullable=True),
        sa.Column('module_2_sent_at', sa.DateTime(), nullable=True),
        sa.Column('module_3_sent', sa.Boolean(), nullable=True),
        sa.Column('module_3_sent_at', sa.DateTime(), nullable=True),
        sa.Column('module_4_sent', sa.Boolean(), nullable=True),
        sa.Column('module_4_sent_at', sa.DateTime(), nullable=True),
        sa.Column('module_5_sent', sa.Boolean(), nullable=True),
        sa.Column('module_5_sent_at', sa.DateTime(), nullable=True),
        sa.Column('last_email_opened_at', sa.DateTime(), nullable=True),
        sa.Column('unsubscribed', sa.Boolean(), nullable=True),
        sa.Column('unsubscribed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )

    op.create_table("email_queue",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('to_email', sa.String(length=255), nullable=False),
        sa.Column('subject', sa.String(length=255), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('html_body', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=True),
        sa.Column('max_attempts', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_email_queue_user_id_users', ondelete='CASCADE'),
    )

    op.create_table("faqs",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('question', sa.String(length=500), nullable=False),
        sa.Column('answer', sa.Text(), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('order', sa.Integer(), nullable=True),
        sa.Column('is_featured', sa.Boolean(), nullable=True),
        sa.Column('is_published', sa.Boolean(), nullable=True),
        sa.Column('view_count', sa.Integer(), nullable=True),
        sa.Column('helpful_count', sa.Integer(), nullable=True),
        sa.Column('not_helpful_count', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )

    op.create_table("leads",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('first_name', sa.String(length=100), nullable=False),
        sa.Column('last_name', sa.String(length=100), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('phone', sa.String(length=20), nullable=True),
        sa.Column('country_code', sa.String(length=2), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('source', sa.String(length=50), nullable=True),
        sa.Column('score', sa.Integer(), nullable=True),
        sa.Column('assigned_to', sa.Integer(), nullable=True),
        sa.Column('assigned_at', sa.DateTime(), nullable=True),
        sa.Column('interested_program_id', sa.Integer(), nullable=True),
        sa.Column('budget', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('converted_to_user_id', sa.Integer(), nullable=True),
        sa.Column('converted_at', sa.DateTime(), nullable=True),
        sa.Column('lost_reason', sa.String(length=50), nullable=True),
        sa.Column('lost_notes', sa.Text(), nullable=True),
        sa.Column('lost_at', sa.DateTime(), nullable=True),
        sa.Column('company', sa.String(length=200), nullable=True),
        sa.Column('job_title', sa.String(length=100), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('tags', sa.String(length=500), nullable=True),
        sa.Column('last_contacted_at', sa.DateTime(), nullable=True),
        sa.Column('next_follow_up', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['assigned_to'], ['users.id'], name='fk_leads_assigned_to_users'),
        sa.ForeignKeyConstraint(['converted_to_user_id'], ['users.id'], name='fk_leads_converted_to_user_id_users'),
        sa.ForeignKeyConstraint(['interested_program_id'], ['trading_programs.id'], name='fk_leads_interested_program_id_trading_programs'),
    )

    op.create_table("monitoring_alerts",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('challenge_id', sa.Integer(), nullable=False),
        sa.Column('alert_type', sa.String(length=50), nullable=False),
        sa.Column('alert_level', sa.String(length=20), nullable=False),
        sa.Column('alert_message', sa.Text(), nullable=True),
        sa.Column('alert_data', postgresql.JSONB(), nullable=True),
        sa.Column('channels', postgresql.JSONB(), nullable=True),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('acknowledged', sa.Boolean(), nullable=True),
        sa.Column('acknowledged_at', sa.DateTime(), nullable=True),
        sa.Column('acknowledged_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['acknowledged_by'], ['users.id'], name='fk_monitoring_alerts_acknowledged_by_users'),
        sa.ForeignKeyConstraint(['challenge_id'], ['challenges.id'], name='fk_monitoring_alerts_challenge_id_challenges'),
    )

    op.create_table("monitoring_events",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('challenge_id', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('event_data', postgresql.JSONB(), nullable=True),
        sa.Column('severity', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['challenge_id'], ['challenges.id'], name='fk_monitoring_events_challenge_id_challenges'),
    )

    op.create_table("mt5_accounts",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('challenge_id', sa.Integer(), nullable=True),
        sa.Column('mt5_login', sa.String(length=50), nullable=False),
        sa.Column('mt5_password_encrypted', sa.Text(), nullable=False),
        sa.Column('mt5_group', sa.String(length=100), nullable=True),
        sa.Column('mt5_server', sa.String(length=100), nullable=True),
        sa.Column('balance', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('equity', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('margin', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('free_margin', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('margin_level', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['challenge_id'], ['challenges.id'], name='fk_mt5_accounts_challenge_id_challenges'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_mt5_accounts_user_id_users'),
        sa.UniqueConstraint('mt5_login', name='uq_mt5_accounts_mt5_login'),
    )

    op.create_table("notification_preferences",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('in_app_withdrawal', sa.Boolean(), nullable=True),
        sa.Column('in_app_commission', sa.Boolean(), nullable=True),
        sa.Column('in_app_kyc', sa.Boolean(), nullable=True),
        sa.Column('in_app_system', sa.Boolean(), nullable=True),
        sa.Column('in_app_payment', sa.Boolean(), nullable=True),
        sa.Column('in_app_challenge', sa.Boolean(), nullable=True),
        sa.Column('email_withdrawal', sa.Boolean(), nullable=True),
        sa.Column('email_commission', sa.Boolean(), nullable=True),
        sa.Column('email_kyc', sa.Boolean(), nullable=True),
        sa.Column('email_system', sa.Boolean(), nullable=True),
        sa.Column('email_payment', sa.Boolean(), nullable=True),
        sa.Column('email_challenge', sa.Boolean(), nullable=True),
        sa.Column('email_enabled', sa.Boolean(), nullable=True),
        sa.Column('email_frequency', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_notification_preferences_user_id_users', ondelete='CASCADE'),
        sa.UniqueConstraint('user_id', name='uq_notification_preferences_user_id'),
    )

    op.create_table("notifications",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('type', sa.String(length=50), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('data', sa.JSON(), nullable=True),
        sa.Column('priority', sa.String(length=20), nullable=True),
        sa.Column('is_read', sa.Boolean(), nullable=True),
        sa.Column('read_at', sa.DateTime(), nullable=True),
        sa.Column('is_deleted', sa.Boolean(), nullable=True),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_notifications_user_id_users', ondelete='CASCADE'),
    )

    op.create_table("payment_approval_requests",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('challenge_id', sa.Integer(), nullable=True),
        sa.Column('payment_id', sa.Integer(), nullable=True),
        sa.Column('requested_by', sa.Integer(), nullable=False),
        sa.Column('requested_for', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('payment_type', sa.String(length=20), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('reviewed_by', sa.Integer(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('admin_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['challenge_id'], ['challenges.id'], name='fk_payment_approval_requests_challenge_id_challenges', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['payment_id'], ['payments.id'], name='fk_payment_approval_requests_payment_id_payments', ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['requested_by'], ['users.id'], name='fk_payment_approval_requests_requested_by_users'),
        sa.ForeignKeyConstraint(['requested_for'], ['users.id'], name='fk_payment_approval_requests_requested_for_users'),
        sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], name='fk_payment_approval_requests_reviewed_by_users'),
    )

    op.create_table("payment_methods",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('method_type', sa.String(length=20), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('bank_name', sa.String(length=100), nullable=True),
        sa.Column('account_number', sa.String(length=100), nullable=True),
        sa.Column('branch_number', sa.String(length=20), nullable=True),
        sa.Column('account_holder_name', sa.String(length=100), nullable=True),
        sa.Column('paypal_email', sa.String(length=100), nullable=True),
        sa.Column('crypto_address', sa.String(length=200), nullable=True),
        sa.Column('crypto_network', sa.String(length=20), nullable=True),
        sa.Column('wise_email', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_payment_methods_user_id_users', ondelete='CASCADE'),
    )

    op.create_table("payout_requests",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('program_id', sa.Integer(), nullable=True),
        sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('profit_split_amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('payout_mode', sa.String(length=20), nullable=False),
        sa.Column('payment_method', sa.String(length=50), nullable=True),
        sa.Column('payment_details', sa.JSON(), nullable=True),
        sa.Column('request_date', sa.DateTime(), nullable=False),
        sa.Column('approved_date', sa.DateTime(), nullable=True),
        sa.Column('processed_date', sa.DateTime(), nullable=True),
        sa.Column('paid_date', sa.DateTime(), nullable=True),
        sa.Column('approved_by', sa.Integer(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['approved_by'], ['users.id'], name='fk_payout_requests_approved_by_users'),
        sa.ForeignKeyConstraint(['program_id'], ['trading_programs.id'], name='fk_payout_requests_program_id_trading_programs', ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_payout_requests_user_id_users', ondelete='CASCADE'),
    )

    op.create_table("roles",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('label', sa.String(length=100), nullable=False),
        sa.Column('label_he', sa.String(length=100), nullable=True),
        sa.Column('color', sa.String(length=100), nullable=True),
        sa.Column('icon', sa.String(length=10), nullable=True),
        sa.Column('hierarchy', sa.Integer(), nullable=False),
        sa.Column('permissions', sa.JSON(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('name', name='uq_roles_name'),
    )

    op.create_table("support_articles",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('slug', sa.String(length=255), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('excerpt', sa.String(length=500), nullable=True),
        sa.Column('category', sa.String(length=100), nullable=False),
        sa.Column('subcategory', sa.String(length=100), nullable=True),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('meta_description', sa.String(length=160), nullable=True),
        sa.Column('meta_keywords', sa.String(length=255), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.Column('author_id', sa.Integer(), nullable=True),
        sa.Column('views', sa.Integer(), nullable=True),
        sa.Column('helpful_count', sa.Integer(), nullable=True),
        sa.Column('not_helpful_count', sa.Integer(), nullable=True),
        sa.Column('order', sa.Integer(), nullable=True),
        sa.Column('featured', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], name='fk_support_articles_author_id_users'),
    )

    op.create_table("support_tickets",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('ticket_number', sa.String(length=20), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('subject', sa.String(length=500), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('priority', sa.String(length=20), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('assigned_to', sa.Integer(), nullable=True),
        sa.Column('attachments', sa.Text(), nullable=True),
        sa.Column('first_response_at', sa.DateTime(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('closed_at', sa.DateTime(), nullable=True),
        sa.Column('rating', sa.Integer(), nullable=True),
        sa.Column('feedback', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['assigned_to'], ['users.id'], name='fk_support_tickets_assigned_to_users'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_support_tickets_user_id_users'),
        sa.UniqueConstraint('ticket_number', name='uq_support_tickets_ticket_number'),
    )

    op.create_table("verification_attempts",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('code_entered', sa.String(length=6), nullable=False),
        sa.Column('success', sa.Boolean(), nullable=False),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.String(length=500), nullable=True),
        sa.Column('failure_reason', sa.String(length=200), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )

    op.create_table("violation_logs",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('challenge_id', sa.Integer(), nullable=False),
        sa.Column('violation_type', sa.String(length=50), nullable=False),
        sa.Column('violation_data', postgresql.JSONB(), nullable=True),
        sa.Column('action_taken', sa.String(length=50), nullable=True),
        sa.Column('action_timestamp', sa.DateTime(), nullable=True),
        sa.Column('resolved', sa.Boolean(), nullable=True),
        sa.Column('resolved_at', sa.DateTime(), nullable=True),
        sa.Column('resolved_by', sa.Integer(), nullable=True),
        sa.Column('resolution_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['challenge_id'], ['challenges.id'], name='fk_violation_logs_challenge_id_challenges'),
        sa.ForeignKeyConstraint(['resolved_by'], ['users.id'], name='fk_violation_logs_resolved_by_users'),
    )

    op.create_table("wallets",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('main_balance', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('commission_balance', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('bonus_balance', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('last_transaction_at', sa.DateTime(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_wallets_user_id_users'),
        sa.UniqueConstraint('user_id', name='uq_wallets_user_id'),
    )

    op.create_table("affiliate_referrals",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('affiliate_link_id', sa.Integer(), nullable=False),
        sa.Column('affiliate_user_id', sa.Integer(), nullable=False),
        sa.Column('referred_user_id', sa.Integer(), nullable=True),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.String(length=500), nullable=True),
        sa.Column('landing_page', sa.String(length=500), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('program_id', sa.Integer(), nullable=True),
        sa.Column('purchase_amount', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('commission_amount', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('click_date', sa.DateTime(), nullable=True),
        sa.Column('conversion_date', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['affiliate_link_id'], ['affiliate_links.id'], name='fk_affiliate_referrals_affiliate_link_id_affiliate_links'),
        sa.ForeignKeyConstraint(['affiliate_user_id'], ['users.id'], name='fk_affiliate_referrals_affiliate_user_id_users'),
        sa.ForeignKeyConstraint(['program_id'], ['programs.id'], name='fk_affiliate_referrals_program_id_programs'),
        sa.ForeignKeyConstraint(['referred_user_id'], ['users.id'], name='fk_affiliate_referrals_referred_user_id_users'),
    )

    op.create_table("lead_activities",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('lead_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('activity_type', sa.String(length=50), nullable=False),
        sa.Column('subject', sa.String(length=200), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('outcome', sa.String(length=50), nullable=True),
        sa.Column('scheduled_at', sa.DateTime(), nullable=True),
        sa.Column('completed', sa.Boolean(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], name='fk_lead_activities_lead_id_leads'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_lead_activities_user_id_users'),
    )

    op.create_table("lead_notes",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('lead_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('is_important', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], name='fk_lead_notes_lead_id_leads'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_lead_notes_user_id_users'),
    )

    op.create_table("mt5_positions",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('mt5_account_id', sa.Integer(), nullable=False),
        sa.Column('ticket', sa.BigInteger(), nullable=False),
        sa.Column('symbol', sa.String(length=20), nullable=True),
        sa.Column('position_type', sa.String(length=10), nullable=True),
        sa.Column('volume', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('price_open', sa.Numeric(precision=15, scale=5), nullable=True),
        sa.Column('price_current', sa.Numeric(precision=15, scale=5), nullable=True),
        sa.Column('stop_loss', sa.Numeric(precision=15, scale=5), nullable=True),
        sa.Column('take_profit', sa.Numeric(precision=15, scale=5), nullable=True),
        sa.Column('profit', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('swap', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('commission', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('open_time', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['mt5_account_id'], ['mt5_accounts.id'], name='fk_mt5_positions_mt5_account_id_mt5_accounts'),
        sa.UniqueConstraint('ticket', name='uq_mt5_positions_ticket'),
    )

    op.create_table("mt5_trades",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('mt5_account_id', sa.Integer(), nullable=False),
        sa.Column('ticket', sa.BigInteger(), nullable=False),
        sa.Column('symbol', sa.String(length=20), nullable=True),
        sa.Column('trade_type', sa.String(length=10), nullable=True),
        sa.Column('volume', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('open_price', sa.Numeric(precision=15, scale=5), nullable=True),
        sa.Column('close_price', sa.Numeric(precision=15, scale=5), nullable=True),
        sa.Column('stop_loss', sa.Numeric(precision=15, scale=5), nullable=True),
        sa.Column('take_profit', sa.Numeric(precision=15, scale=5), nullable=True),
        sa.Column('open_time', sa.DateTime(), nullable=True),
        sa.Column('close_time', sa.DateTime(), nullable=True),
        sa.Column('profit', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('commission', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('swap', sa.Numeric(precision=15, scale=2), nullable=True),
        sa.Column('comment', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['mt5_account_id'], ['mt5_accounts.id'], name='fk_mt5_trades_mt5_account_id_mt5_accounts'),
        sa.UniqueConstraint('ticket', name='uq_mt5_trades_ticket'),
    )

    op.create_table("referrals",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('agent_id', sa.Integer(), nullable=False),
        sa.Column('referred_user_id', sa.Integer(), nullable=False),
        sa.Column('referral_code', sa.String(length=50), nullable=False),
        sa.Column('ip_address', sa.String(length=45), nullable=True),
        sa.Column('user_agent', sa.String(length=500), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('first_purchase_at', sa.DateTime(), nullable=True),
        sa.Column('total_purchases', sa.Integer(), nullable=False),
        sa.Column('total_spent', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], name='fk_referrals_agent_id_agents'),
        sa.ForeignKeyConstraint(['referred_user_id'], ['users.id'], name='fk_referrals_referred_user_id_users'),
    )

    op.create_table("ticket_messages",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('ticket_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('email', sa.String(length=255), nullable=True),
        sa.Column('name', sa.String(length=200), nullable=True),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('is_staff', sa.Boolean(), nullable=True),
        sa.Column('is_internal', sa.Boolean(), nullable=True),
        sa.Column('attachments', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['ticket_id'], ['support_tickets.id'], name='fk_ticket_messages_ticket_id_support_tickets'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_ticket_messages_user_id_users'),
    )

    op.create_table("transactions",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('wallet_id', sa.Integer(), nullable=False),
        sa.Column('type', sa.String(length=50), nullable=False),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('balance_type', sa.String(length=20), nullable=False),
        sa.Column('balance_before', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('balance_after', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('reference_type', sa.String(length=50), nullable=True),
        sa.Column('reference_id', sa.Integer(), nullable=True),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], name='fk_transactions_created_by_users'),
        sa.ForeignKeyConstraint(['wallet_id'], ['wallets.id'], name='fk_transactions_wallet_id_wallets'),
    )

    op.create_table("withdrawals",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('agent_id', sa.Integer(), nullable=True),
        sa.Column('challenge_id', sa.Integer(), nullable=True),
        sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('fee', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('net_amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('payment_method', sa.String(length=50), nullable=False),
        sa.Column('withdrawal_method', sa.String(length=50), nullable=True),
        sa.Column('payment_details', sa.JSON(), nullable=True),
        sa.Column('account_details', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('approved_by', sa.Integer(), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('processed_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('transaction_id', sa.String(length=100), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], name='fk_withdrawals_agent_id_agents'),
        sa.ForeignKeyConstraint(['approved_by'], ['users.id'], name='fk_withdrawals_approved_by_users'),
        sa.ForeignKeyConstraint(['challenge_id'], ['challenges.id'], name='fk_withdrawals_challenge_id_challenges'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], name='fk_withdrawals_user_id_users'),
    )

    op.create_table("affiliate_commissions",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('affiliate_user_id', sa.Integer(), nullable=False),
        sa.Column('referral_id', sa.Integer(), nullable=True),
        sa.Column('amount', sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column('type', sa.String(length=20), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('description', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('paid_at', sa.DateTime(), nullable=True),
        sa.Column('payout_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['affiliate_user_id'], ['users.id'], name='fk_affiliate_commissions_affiliate_user_id_users'),
        sa.ForeignKeyConstraint(['payout_id'], ['affiliate_payouts.id'], name='fk_affiliate_commissions_payout_id_affiliate_payouts'),
        sa.ForeignKeyConstraint(['referral_id'], ['affiliate_referrals.id'], name='fk_affiliate_commissions_referral_id_affiliate_referrals'),
    )

    op.create_table("commissions",
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('agent_id', sa.Integer(), nullable=False),
        sa.Column('referral_id', sa.Integer(), nullable=False),
        sa.Column('challenge_id', sa.Integer(), nullable=False),
        sa.Column('sale_amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('commission_rate', sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column('commission_amount', sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('approved_at', sa.DateTime(), nullable=True),
        sa.Column('paid_at', sa.DateTime(), nullable=True),
        sa.Column('payment_method', sa.String(length=50), nullable=True),
        sa.Column('transaction_id', sa.String(length=100), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['agent_id'], ['agents.id'], name='fk_commissions_agent_id_agents'),
        sa.ForeignKeyConstraint(['challenge_id'], ['challenges.id'], name='fk_commissions_challenge_id_challenges'),
        sa.ForeignKeyConstraint(['referral_id'], ['referrals.id'], name='fk_commissions_referral_id_referrals'),
    )
    op.create_index('ix_affiliate_links_code', 'affiliate_links', ['code'], unique=True)
    op.create_index('ix_agents_agent_code', 'agents', ['agent_code'], unique=True)
    op.create_index('idx_blog_category_status', 'blog_posts', ['category', 'status'], unique=False)
    op.create_index('idx_blog_featured_status', 'blog_posts', ['featured', 'status'], unique=False)
    op.create_index('idx_blog_status_published', 'blog_posts', ['status', 'published_at'], unique=False)
    op.create_index('ix_blog_posts_author_id', 'blog_posts', ['author_id'], unique=False)
    op.create_index('ix_blog_posts_category', 'blog_posts', ['category'], unique=False)
    op.create_index('ix_blog_posts_featured', 'blog_posts', ['featured'], unique=False)
    op.create_index('ix_blog_posts_published_at', 'blog_posts', ['published_at'], unique=False)
    op.create_index('ix_blog_posts_slug', 'blog_posts', ['slug'], unique=True)
    op.create_index('ix_blog_posts_status', 'blog_posts', ['status'], unique=False)
    op.create_index('ix_course_enrollments_email', 'course_enrollments', ['email'], unique=False)
    op.create_index('idx_email_queue_created_at', 'email_queue', ['created_at'], unique=False)
    op.create_index('idx_email_queue_status', 'email_queue', ['status'], unique=False)
    op.create_index('ix_leads_assigned_to', 'leads', ['assigned_to'], unique=False)
    op.create_index('ix_leads_email', 'leads', ['email'], unique=False)
    op.create_index('ix_leads_next_follow_up', 'leads', ['next_follow_up'], unique=False)
    op.create_index('ix_leads_source', 'leads', ['source'], unique=False)
    op.create_index('ix_leads_status', 'leads', ['status'], unique=False)
    op.create_index('idx_monitoring_alerts_acknowledged', 'monitoring_alerts', ['acknowledged'], unique=False)
    op.create_index('idx_monitoring_alerts_challenge', 'monitoring_alerts', ['challenge_id'], unique=False)
    op.create_index('idx_monitoring_alerts_level', 'monitoring_alerts', ['alert_level'], unique=False)
    op.create_index('idx_monitoring_alerts_sent', 'monitoring_alerts', ['sent_at'], unique=False)
    op.create_index('idx_monitoring_events_challenge', 'monitoring_events', ['challenge_id'], unique=False)
    op.create_index('idx_monitoring_events_created', 'monitoring_events', ['created_at'], unique=False)
    op.create_index('idx_monitoring_events_severity', 'monitoring_events', ['severity'], unique=False)
    op.create_index('idx_monitoring_events_type', 'monitoring_events', ['event_type'], unique=False)
    op.create_index('idx_notifications_created_at', 'notifications', ['created_at'], unique=False)
    op.create_index('idx_notifications_is_read', 'notifications', ['is_read'], unique=False)
    op.create_index('idx_notifications_type', 'notifications', ['type'], unique=False)
    op.create_index('idx_notifications_user_id', 'notifications', ['user_id'], unique=False)
    op.create_index('ix_support_articles_category', 'support_articles', ['category'], unique=False)
    op.create_index('ix_support_articles_slug', 'support_articles', ['slug'], unique=True)
    op.create_index('idx_email_created', 'verification_attempts', ['email', 'created_at'], unique=False)
    op.create_index('idx_ip_created', 'verification_attempts', ['ip_address', 'created_at'], unique=False)
    op.create_index('idx_success_created', 'verification_attempts', ['success', 'created_at'], unique=False)
    op.create_index('ix_verification_attempts_email', 'verification_attempts', ['email'], unique=False)
    op.create_index('idx_violation_logs_challenge', 'violation_logs', ['challenge_id'], unique=False)
    op.create_index('idx_violation_logs_created', 'violation_logs', ['created_at'], unique=False)
    op.create_index('idx_violation_logs_resolved', 'violation_logs', ['resolved'], unique=False)
    op.create_index('idx_violation_logs_type', 'violation_logs', ['violation_type'], unique=False)
    op.create_index('ix_wallet_user_id', 'wallets', ['user_id'], unique=False)
    op.create_index('ix_lead_activities_activity_type', 'lead_activities', ['activity_type'], unique=False)
    op.create_index('ix_lead_activities_lead_id', 'lead_activities', ['lead_id'], unique=False)
    op.create_index('ix_lead_notes_lead_id', 'lead_notes', ['lead_id'], unique=False)
    op.create_index('ix_referrals_referral_code', 'referrals', ['referral_code'], unique=False)
    op.create_index('ix_transaction_created_at', 'transactions', ['created_at'], unique=False)
    op.create_index('ix_transaction_type', 'transactions', ['type'], unique=False)
    op.create_index('ix_transaction_wallet_id', 'transactions', ['wallet_id'], unique=False)
    op.create_index('ix_commission_agent_id', 'commissions', ['agent_id'], unique=False)
    op.create_index('ix_commission_agent_status', 'commissions', ['agent_id', 'status'], unique=False)
    op.create_index('ix_commission_created_at', 'commissions', ['created_at'], unique=False)
    op.create_index('ix_commission_status', 'commissions', ['status'], unique=False)


def downgrade() -> None:
    _preflight_downgrade()
    op.drop_table('commissions')
    op.drop_table('affiliate_commissions')
    op.drop_table('withdrawals')
    op.drop_table('transactions')
    op.drop_table('ticket_messages')
    op.drop_table('referrals')
    op.drop_table('mt5_trades')
    op.drop_table('mt5_positions')
    op.drop_table('lead_notes')
    op.drop_table('lead_activities')
    op.drop_table('affiliate_referrals')
    op.drop_table('wallets')
    op.drop_table('violation_logs')
    op.drop_table('verification_attempts')
    op.drop_table('support_tickets')
    op.drop_table('support_articles')
    op.drop_table('roles')
    op.drop_table('payout_requests')
    op.drop_table('payment_methods')
    op.drop_table('payment_approval_requests')
    op.drop_table('notifications')
    op.drop_table('notification_preferences')
    op.drop_table('mt5_accounts')
    op.drop_table('monitoring_events')
    op.drop_table('monitoring_alerts')
    op.drop_table('leads')
    op.drop_table('faqs')
    op.drop_table('email_queue')
    op.drop_table('course_enrollments')
    op.drop_table('blog_posts')
    op.drop_table('agents')
    op.drop_table('affiliate_settings')
    op.drop_table('affiliate_payouts')
    op.drop_table('affiliate_links')
