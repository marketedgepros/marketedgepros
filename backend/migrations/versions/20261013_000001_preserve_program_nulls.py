"""Preserve legacy NULL program risk fields during data transfer.

Revision ID: 20261013_000001
Revises: 20261012_000001

Only the three legacy risk-field nullability constraints change.  Their
numeric(10, 2) representation remains unchanged, and this revision does not
write or infer any program value.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20261013_000001"
down_revision = "20261012_000001"
branch_labels = None
depends_on = None


TABLE = "trading_programs"
RISK_COLUMNS = ("profit_target", "max_daily_loss", "max_total_loss")
RISK_TYPE = sa.Numeric(precision=10, scale=2)


def _set_nullable(nullable: bool) -> None:
    for column in RISK_COLUMNS:
        op.alter_column(
            TABLE,
            column,
            schema="public",
            existing_type=RISK_TYPE,
            nullable=nullable,
        )


def upgrade() -> None:
    _set_nullable(True)


def downgrade() -> None:
    bind = op.get_bind()
    # Serialize the proof and constraint restoration so a concurrent legacy
    # insert cannot introduce a NULL after the preflight succeeds.
    bind.execute(sa.text("LOCK TABLE public.trading_programs IN ACCESS EXCLUSIVE MODE"))
    null_count = bind.execute(sa.text("""
        SELECT count(*)
        FROM public.trading_programs
        WHERE profit_target IS NULL
           OR max_daily_loss IS NULL
           OR max_total_loss IS NULL
    """)).scalar_one()
    if null_count:
        raise RuntimeError(
            "20261013_000001 downgrade refuses while trading_programs retains "
            "NULL legacy risk values; populate explicit values before retrying"
        )
    _set_nullable(False)
