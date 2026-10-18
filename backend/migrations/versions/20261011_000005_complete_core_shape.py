"""Close the historical core schema shape without inferring business state.

Revision ID: 20261011_000005
Revises: 20261011_000004

This revision is an additive, source-reviewed snapshot of 41 columns that the
active ORM reads from the five historical core tables.  Every added field is
nullable with no server default and no data backfill: NULL continues to mean
unknown for existing rows, including status, type, tier, subdomain, payment,
and approval values.  It deliberately leaves existing legacy precision,
nullability, timestamps, and business semantics unchanged.

Online upgrades preflight every owned column before issuing any DDL.  Existing
out-of-band columns are not adopted.  Downgrade is data-preserving: it refuses
offline SQL generation and online removal whenever any added field is non-NULL.
"""
from __future__ import annotations

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20261011_000005"
down_revision = "20261011_000004"
branch_labels = None
depends_on = None


# Frozen names only; this migration never imports live application metadata.
# The order is also the DDL ownership order and is reversed on safe downgrade.
CORE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("tenants", "accent_color"),
    ("tenants", "contact_email"),
    ("tenants", "contact_phone"),
    ("tenants", "custom_css"),
    ("tenants", "custom_domain"),
    ("tenants", "favicon_url"),
    ("tenants", "logo_url"),
    ("tenants", "primary_color"),
    ("tenants", "secondary_color"),
    ("tenants", "settings"),
    ("tenants", "status"),
    ("tenants", "subdomain"),
    ("tenants", "tier"),
    ("trading_programs", "minimum_payout_amount"),
    ("trading_programs", "payout_mode"),
    ("trading_programs", "profit_split_percentage"),
    ("trading_programs", "rules"),
    ("trading_programs", "type"),
    ("challenges", "account_number"),
    ("challenges", "addons"),
    ("challenges", "approval_status"),
    ("challenges", "approved_at"),
    ("challenges", "approved_by"),
    ("challenges", "created_by"),
    ("challenges", "current_phase"),
    ("challenges", "daily_drawdown_history"),
    ("challenges", "end_date"),
    ("challenges", "max_drawdown"),
    ("challenges", "passed_at"),
    ("challenges", "payment_type"),
    ("challenges", "rejection_reason"),
    ("challenges", "start_date"),
    ("challenges", "total_phases"),
    ("payments", "admin_notes"),
    ("payments", "approval_status"),
    ("payments", "approved_at"),
    ("payments", "approved_by"),
    ("payments", "payment_type"),
    ("payments", "rejection_reason"),
    ("program_addons", "benefits"),
    ("program_addons", "price_type"),
)


UNIQUE_OBJECTS = {('tenants', 'uq_tenants_custom_domain'): ['custom_domain']}
FOREIGN_OBJECTS = {
    ('challenges', 'fk_challenges_approved_by_users'): ['approved_by'],
    ('challenges', 'fk_challenges_created_by_users'): ['created_by'],
    ('payments', 'fk_payments_approved_by_users'): ['approved_by'],
}
INDEX_OBJECTS = {('tenants', 'ix_tenants_subdomain'): (['subdomain'], True)}


def _preflight_named_objects(bind, *, downgrade=False):
    """Check complete expected metadata before any named-object DDL."""
    inspector = sa.inspect(bind)
    expected_constraints = set(UNIQUE_OBJECTS) | set(FOREIGN_OBJECTS)
    expected_relations = {name for _, name in UNIQUE_OBJECTS} | {name for _, name in INDEX_OBJECTS}
    if not downgrade:
        # PostgreSQL index/backing-index names share the relation namespace,
        # even with a sequence/table on another table's name. Check all kinds.
        relation_names = set(bind.execute(sa.text("SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'")).scalars())
        constraints = set(bind.execute(sa.text("SELECT t.relname,c.conname FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname='public'")).all())
        collisions = sorted(expected_relations & relation_names)
        collisions += [f'{table}.{name}' for table,name in sorted(expected_constraints & constraints)]
        if collisions:
            raise RuntimeError('Named schema object collision before DDL: ' + ', '.join(collisions))
        return
    invalid = []
    for (table,name), columns in UNIQUE_OBJECTS.items():
        actual = next((item for item in inspector.get_unique_constraints(table) if item['name']==name), None)
        if actual is None or actual['column_names'] != columns:
            invalid.append(f'{table}.{name}')
    for (table,name), columns in FOREIGN_OBJECTS.items():
        actual = next((item for item in inspector.get_foreign_keys(table) if item['name']==name), None)
        if actual is None or actual['constrained_columns'] != columns or actual['referred_table'] != 'users' or actual['referred_columns'] != ['id'] or actual['referred_schema'] not in (None,'public') or actual.get('options'):
            invalid.append(f'{table}.{name}')
    for (table,name), (columns,unique) in INDEX_OBJECTS.items():
        actual = next((item for item in inspector.get_indexes(table) if item['name']==name), None)
        if actual is None or actual['column_names'] != columns or actual['unique'] is not unique or actual.get('column_sorting') or any(actual.get('dialect_options',{}).get(key) for key in ('postgresql_where','postgresql_include','postgresql_nulls_not_distinct','postgresql_ops')):
            invalid.append(f'{table}.{name}')
    owned_fields = set(CORE_COLUMNS)
    local_dependencies = bind.execute(sa.text("SELECT t.relname,a.attname,c.conname FROM pg_constraint c JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=ANY(c.conkey) WHERE n.nspname='public'")).all()
    for table,column,name in local_dependencies:
        if (table,column) in owned_fields and (table,name) not in expected_constraints:
            invalid.append(f'{table}.{name}')
    external_dependencies = bind.execute(sa.text("SELECT p.relname,a.attname,t.relname,c.conname FROM pg_constraint c JOIN pg_class p ON p.oid=c.confrelid JOIN pg_namespace n ON n.oid=p.relnamespace JOIN pg_attribute a ON a.attrelid=p.oid AND a.attnum=ANY(c.confkey) JOIN pg_class t ON t.oid=c.conrelid WHERE c.contype='f' AND n.nspname='public'")).all()
    for parent,column,child,name in external_dependencies:
        if (parent,column) in owned_fields:
            invalid.append(f'{child}.{name}')
    index_dependencies = bind.execute(sa.text("SELECT t.relname,a.attname,x.relname FROM pg_index i JOIN pg_class x ON x.oid=i.indexrelid JOIN pg_class t ON t.oid=i.indrelid JOIN pg_namespace n ON n.oid=t.relnamespace JOIN pg_depend d ON d.classid='pg_class'::regclass AND d.refclassid='pg_class'::regclass AND d.objid=i.indexrelid AND d.refobjid=i.indrelid JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=d.refobjsubid WHERE n.nspname='public' AND d.refobjsubid>0")).all()
    for table,column,name in index_dependencies:
        if (table,column) in owned_fields and (table,name) not in INDEX_OBJECTS and (table,name) not in UNIQUE_OBJECTS:
            invalid.append(f'{table}.{name}')
    # Refuse removing columns with metadata introduced by someone else later.
    for table in sorted({item[0] for item in CORE_COLUMNS}):
        fields = {column for owner_table,column in CORE_COLUMNS if owner_table==table}
        for item in inspector.get_indexes(table):
            if fields.intersection(item.get('column_names') or ()) and (table,item['name']) not in INDEX_OBJECTS and (table,item['name']) not in UNIQUE_OBJECTS:
                invalid.append(f'{table}.{item["name"]}')
        for item in inspector.get_foreign_keys(table) + inspector.get_unique_constraints(table):
            columns = item.get('constrained_columns') or item.get('column_names') or ()
            if fields.intersection(columns) and (table,item['name']) not in expected_constraints:
                invalid.append(f'{table}.{item["name"]}')
    if invalid:
        raise RuntimeError('Named schema object ownership/definition mismatch before DDL: ' + ', '.join(sorted(set(invalid))))


def _preflight_upgrade() -> None:
    """Reject every collision before adding even the first column online."""
    if context.is_offline_mode():
        # Offline SQL has no catalog to inspect, but remains a non-destructive
        # additive upgrade script for a clean historical graph.
        return

    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names(schema="public"))
    expected_tables = {table_name for table_name, _ in CORE_COLUMNS}
    missing_tables = sorted(expected_tables - existing_tables)
    collisions: list[str] = []
    for table_name in sorted(expected_tables):
        if table_name not in existing_tables:
            continue
        existing_columns = {
            column["name"]
            for column in inspector.get_columns(table_name, schema="public")
        }
        collisions.extend(
            f"{candidate_table}.{column_name}"
            for candidate_table, column_name in CORE_COLUMNS
            if candidate_table == table_name and column_name in existing_columns
        )
    if missing_tables or collisions:
        details = []
        if missing_tables:
            details.append("missing tables: " + ", ".join(missing_tables))
        if collisions:
            details.append("existing columns: " + ", ".join(sorted(collisions)))
        raise RuntimeError(
            "Core schema reconciliation required before upgrade; " + "; ".join(details)
        )
    _preflight_named_objects(op.get_bind())


def _preflight_downgrade() -> None:
    """Refuse any destructive reversal unless all owned fields are NULL."""
    if context.is_offline_mode():
        raise RuntimeError(
            "20261011_000005 offline downgrade is unsupported; "
            "an online data preflight must prove all added fields are NULL"
        )

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names(schema="public"))
    expected_tables = {table_name for table_name, _ in CORE_COLUMNS}
    missing_tables = sorted(expected_tables - existing_tables)
    missing_columns: list[str] = []
    for table_name in sorted(expected_tables):
        if table_name not in existing_tables:
            continue
        existing = {
            column["name"]
            for column in inspector.get_columns(table_name, schema="public")
        }
        missing_columns.extend(
            f"{candidate_table}.{column_name}"
            for candidate_table, column_name in CORE_COLUMNS
            if candidate_table == table_name and column_name not in existing
        )
    if missing_tables or missing_columns:
        details = []
        if missing_tables:
            details.append("missing tables: " + ", ".join(missing_tables))
        if missing_columns:
            details.append("missing columns: " + ", ".join(sorted(missing_columns)))
        raise RuntimeError(
            "Core schema downgrade refuses partial ownership; " + "; ".join(details)
        )
    _preflight_named_objects(bind, downgrade=True)

    # Names here are immutable source constants.  IS NOT NULL rejects every
    # value, including zero, false, empty strings, and empty JSON objects/arrays.
    populated: list[str] = []
    for table_name in sorted(expected_tables):
        columns = [
            column_name
            for candidate_table, column_name in CORE_COLUMNS
            if candidate_table == table_name
        ]
        predicate = " OR ".join(f'"{column_name}" IS NOT NULL' for column_name in columns)
        has_values = bind.execute(
            sa.text(f'SELECT EXISTS (SELECT 1 FROM "{table_name}" WHERE {predicate})')
        ).scalar_one()
        if has_values:
            populated.append(table_name)
    if populated:
        raise RuntimeError(
            "Core schema downgrade refused: populated fields require preservation in "
            + ", ".join(populated)
        )


def upgrade() -> None:
    _preflight_upgrade()

    # All fields are nullable and intentionally have neither a server default
    # nor an UPDATE/backfill.  The legacy schema remains the compatibility floor.
    op.add_column("tenants", sa.Column("accent_color", sa.String(length=7), nullable=True))
    op.add_column("tenants", sa.Column("contact_email", sa.String(length=255), nullable=True))
    op.add_column("tenants", sa.Column("contact_phone", sa.String(length=20), nullable=True))
    op.add_column("tenants", sa.Column("custom_css", sa.Text(), nullable=True))
    op.add_column("tenants", sa.Column("custom_domain", sa.String(length=255), nullable=True))
    op.add_column("tenants", sa.Column("favicon_url", sa.String(length=500), nullable=True))
    op.add_column("tenants", sa.Column("logo_url", sa.String(length=500), nullable=True))
    op.add_column("tenants", sa.Column("primary_color", sa.String(length=7), nullable=True))
    op.add_column("tenants", sa.Column("secondary_color", sa.String(length=7), nullable=True))
    op.add_column("tenants", sa.Column("settings", postgresql.JSONB(), nullable=True))
    op.add_column("tenants", sa.Column("status", sa.String(length=20), nullable=True))
    op.add_column("tenants", sa.Column("subdomain", sa.String(length=100), nullable=True))
    op.add_column("tenants", sa.Column("tier", sa.String(length=20), nullable=True))

    op.add_column("trading_programs", sa.Column("minimum_payout_amount", sa.Numeric(10, 2), nullable=True))
    op.add_column("trading_programs", sa.Column("payout_mode", sa.String(length=50), nullable=True))
    op.add_column("trading_programs", sa.Column("profit_split_percentage", sa.Numeric(5, 2), nullable=True))
    op.add_column("trading_programs", sa.Column("rules", postgresql.JSONB(), nullable=True))
    op.add_column("trading_programs", sa.Column("type", sa.String(length=50), nullable=True))

    op.add_column("challenges", sa.Column("account_number", sa.String(length=50), nullable=True))
    op.add_column("challenges", sa.Column("addons", postgresql.JSONB(), nullable=True))
    op.add_column("challenges", sa.Column("approval_status", sa.String(length=20), nullable=True))
    op.add_column("challenges", sa.Column("approved_at", sa.DateTime(), nullable=True))
    op.add_column("challenges", sa.Column("approved_by", sa.Integer(), nullable=True))
    op.add_column("challenges", sa.Column("created_by", sa.Integer(), nullable=True))
    op.add_column("challenges", sa.Column("current_phase", sa.Integer(), nullable=True))
    op.add_column("challenges", sa.Column("daily_drawdown_history", postgresql.JSONB(), nullable=True))
    op.add_column("challenges", sa.Column("end_date", sa.DateTime(), nullable=True))
    op.add_column("challenges", sa.Column("max_drawdown", sa.Numeric(12, 2), nullable=True))
    op.add_column("challenges", sa.Column("passed_at", sa.DateTime(), nullable=True))
    op.add_column("challenges", sa.Column("payment_type", sa.String(length=20), nullable=True))
    op.add_column("challenges", sa.Column("rejection_reason", sa.Text(), nullable=True))
    op.add_column("challenges", sa.Column("start_date", sa.DateTime(), nullable=True))
    op.add_column("challenges", sa.Column("total_phases", sa.Integer(), nullable=True))

    op.add_column("payments", sa.Column("admin_notes", sa.Text(), nullable=True))
    op.add_column("payments", sa.Column("approval_status", sa.String(length=20), nullable=True))
    op.add_column("payments", sa.Column("approved_at", sa.DateTime(), nullable=True))
    op.add_column("payments", sa.Column("approved_by", sa.Integer(), nullable=True))
    op.add_column("payments", sa.Column("payment_type", sa.String(length=20), nullable=True))
    op.add_column("payments", sa.Column("rejection_reason", sa.Text(), nullable=True))

    op.add_column("program_addons", sa.Column("benefits", postgresql.JSONB(), nullable=True))
    op.add_column("program_addons", sa.Column("price_type", sa.String(length=20), nullable=True))

    # New columns begin NULL, so these ORM-declared relations and uniqueness
    # constraints add no inferred facts to historical data.
    op.create_unique_constraint("uq_tenants_custom_domain", "tenants", ["custom_domain"])
    op.create_foreign_key(
        "fk_challenges_approved_by_users", "challenges", "users", ["approved_by"], ["id"]
    )
    op.create_foreign_key(
        "fk_challenges_created_by_users", "challenges", "users", ["created_by"], ["id"]
    )
    op.create_foreign_key(
        "fk_payments_approved_by_users", "payments", "users", ["approved_by"], ["id"]
    )
    op.create_index("ix_tenants_subdomain", "tenants", ["subdomain"], unique=True)


def downgrade() -> None:
    _preflight_downgrade()

    # Reverse only this revision's objects after the complete data gate passed.
    op.drop_index("ix_tenants_subdomain", table_name="tenants")
    op.drop_constraint("fk_payments_approved_by_users", "payments", type_="foreignkey")
    op.drop_constraint("fk_challenges_created_by_users", "challenges", type_="foreignkey")
    op.drop_constraint("fk_challenges_approved_by_users", "challenges", type_="foreignkey")
    op.drop_constraint("uq_tenants_custom_domain", "tenants", type_="unique")
    for table_name, column_name in reversed(CORE_COLUMNS):
        op.drop_column(table_name, column_name)
