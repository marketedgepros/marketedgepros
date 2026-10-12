"""Private-PostgreSQL contract tests for affiliate lifecycle migration 20261012_000001.

Run this module only through ``backend/scripts/run_staging_integration.py``.  Every
case uses a runner-created Unix-socket PostgreSQL database and Alembic revisions;
it never uses pytest directly, ORM ``create_all``, HTTP, a provider, a wallet, or a
production/live database.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from alembic import command
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError

from test_purchase_order_schema import purchase_order_database, record_schema_ddl


BACKEND = Path(__file__).resolve().parents[1]
PREVIOUS = "20261011_000008"
REVISION = "20261012_000001"
IDENTITY = "affiliate_identity_evidence"
ATTRIBUTION = "affiliate_order_attributions"
AWARD = "affiliate_commission_awards"
COMMAND = "affiliate_payout_commands"
TABLES = {IDENTITY, ATTRIBUTION, AWARD, COMMAND}
FUNCTIONS = {
    "marketedgepros_affiliate_lifecycle_immutable": ("", "trigger"),
    "marketedgepros_affiliate_source_context_validate": ("p_attribution_id character varying", "void"),
    "marketedgepros_affiliate_identity_evidence_validate": ("", "trigger"),
    "marketedgepros_affiliate_order_attribution_validate": ("", "trigger"),
    "marketedgepros_affiliate_commission_award_validate": ("", "trigger"),
    "marketedgepros_affiliate_commission_award_transition": ("", "trigger"),
    "marketedgepros_affiliate_payout_command_validate": ("", "trigger"),
    "marketedgepros_affiliate_payout_command_transition": ("", "trigger"),
    "marketedgepros_affiliate_payout_consistency_validate": ("", "trigger"),
}

EXPECTED_COLUMNS = {
    IDENTITY: {
        "id": ("varchar(36)", False), "user_id": ("integer", False),
        "tenant_id": ("integer", False), "subject_hash": ("varchar(64)", False),
        "source": ("varchar(16)", False), "event_key": ("varchar(128)", False),
        "created_at": ("timestamp with time zone", False),
    },
    ATTRIBUTION: {
        "id": ("varchar(36)", False), "order_id": ("varchar(36)", False),
        "affiliate_user_id": ("integer", False), "buyer_evidence_id": ("varchar(36)", False),
        "affiliate_evidence_id": ("varchar(36)", False), "policy_hash": ("varchar(64)", False),
        "policy_json": ("jsonb", False), "created_at": ("timestamp with time zone", False),
    },
    AWARD: {
        "id": ("varchar(36)", False), "attribution_id": ("varchar(36)", False),
        "journal_id": ("varchar(36)", False), "amount_minor": ("bigint", False),
        "state": ("varchar(16)", False), "review_open": ("boolean", False),
        "release_at": ("timestamp with time zone", False),
        "reversal_event_key": ("varchar(128)", True),
        "created_at": ("timestamp with time zone", False),
        "updated_at": ("timestamp with time zone", False),
    },
    COMMAND: {
        "id": ("varchar(36)", False), "award_id": ("varchar(36)", False),
        "approved_by": ("integer", False), "network_id": ("varchar(64)", False),
        "asset_id": ("varchar(64)", False), "recipient_hash": ("varchar(64)", False),
        "amount_atomic": ("numeric(78, 0)", False), "quote_hash": ("varchar(64)", False),
        "attempt_token": ("varchar(36)", True), "transfer_key": ("varchar(128)", True),
        "state": ("varchar(16)", False), "created_at": ("timestamp with time zone", False),
        "updated_at": ("timestamp with time zone", False),
    },
}

EXPECTED_FOREIGN_KEYS = {
    IDENTITY: {
        "fk_affiliate_identity_evidence_user": ("user_id", "users"),
        "fk_affiliate_identity_evidence_tenant": ("tenant_id", "tenants"),
    },
    ATTRIBUTION: {
        "fk_affiliate_order_attributions_order": ("order_id", "purchase_orders"),
        "fk_affiliate_order_attributions_affiliate_user": ("affiliate_user_id", "users"),
        "fk_affiliate_order_attributions_buyer_evidence": ("buyer_evidence_id", IDENTITY),
        "fk_affiliate_order_attributions_affiliate_evidence": ("affiliate_evidence_id", IDENTITY),
    },
    AWARD: {
        "fk_affiliate_commission_awards_attribution": ("attribution_id", ATTRIBUTION),
        "fk_affiliate_commission_awards_journal": ("journal_id", "settlement_journals"),
    },
    COMMAND: {
        "fk_affiliate_payout_commands_award": ("award_id", AWARD),
        "fk_affiliate_payout_commands_approved_by": ("approved_by", "users"),
    },
}

EXPECTED_UNIQUES = {
    IDENTITY: {
        "uq_affiliate_identity_evidence_source_event": ["source", "event_key"],
        "uq_affiliate_identity_evidence_tenant_user": ["tenant_id", "user_id"],
    },
    ATTRIBUTION: {"uq_affiliate_order_attributions_order": ["order_id"]},
    AWARD: {
        "uq_affiliate_commission_awards_attribution": ["attribution_id"],
        "uq_affiliate_commission_awards_journal": ["journal_id"],
    },
    COMMAND: {
        "uq_affiliate_payout_commands_award": ["award_id"],
        "uq_affiliate_payout_commands_transfer": ["network_id", "transfer_key"],
    },
}

EXPECTED_CHECKS = {
    IDENTITY: {
        "ck_affiliate_identity_evidence_id", "ck_affiliate_identity_evidence_user",
        "ck_affiliate_identity_evidence_subject_hash", "ck_affiliate_identity_evidence_source",
        "ck_affiliate_identity_evidence_event_key",
    },
    ATTRIBUTION: {
        "ck_affiliate_order_attributions_id", "ck_affiliate_order_attributions_references",
        "ck_affiliate_order_attributions_policy_hash", "ck_affiliate_order_attributions_policy",
    },
    AWARD: {
        "ck_affiliate_commission_awards_id", "ck_affiliate_commission_awards_references",
        "ck_affiliate_commission_awards_amount", "ck_affiliate_commission_awards_state",
        "ck_affiliate_commission_awards_times", "ck_affiliate_commission_awards_reversal",
    },
    COMMAND: {
        "ck_affiliate_payout_commands_id", "ck_affiliate_payout_commands_award",
        "ck_affiliate_payout_commands_identifiers", "ck_affiliate_payout_commands_hashes",
        "ck_affiliate_payout_commands_amount", "ck_affiliate_payout_commands_state",
        "ck_affiliate_payout_commands_shape", "ck_affiliate_payout_commands_times",
    },
}

# table -> trigger -> (tgtype, function, is_constraint, deferrable, initially_deferred)
EXPECTED_TRIGGERS = {
    IDENTITY: {
        "affiliate_identity_evidence_immutable": (27, "marketedgepros_affiliate_lifecycle_immutable", False, False, False),
        "affiliate_identity_evidence_validate_insert": (7, "marketedgepros_affiliate_identity_evidence_validate", False, False, False),
        "affiliate_identity_evidence_no_truncate": (34, "marketedgepros_affiliate_lifecycle_immutable", False, False, False),
    },
    ATTRIBUTION: {
        "affiliate_order_attributions_immutable": (27, "marketedgepros_affiliate_lifecycle_immutable", False, False, False),
        "affiliate_order_attributions_validate_insert": (7, "marketedgepros_affiliate_order_attribution_validate", False, False, False),
        "affiliate_order_attributions_no_truncate": (34, "marketedgepros_affiliate_lifecycle_immutable", False, False, False),
    },
    AWARD: {
        "affiliate_commission_awards_transition": (27, "marketedgepros_affiliate_commission_award_transition", False, False, False),
        "affiliate_commission_awards_validate_insert": (7, "marketedgepros_affiliate_commission_award_validate", False, False, False),
        "affiliate_commission_awards_payout_consistency": (21, "marketedgepros_affiliate_payout_consistency_validate", True, True, True),
        "affiliate_commission_awards_no_truncate": (34, "marketedgepros_affiliate_lifecycle_immutable", False, False, False),
    },
    COMMAND: {
        "affiliate_payout_commands_transition": (27, "marketedgepros_affiliate_payout_command_transition", False, False, False),
        "affiliate_payout_commands_validate_insert": (7, "marketedgepros_affiliate_payout_command_validate", False, False, False),
        "affiliate_payout_commands_award_consistency": (21, "marketedgepros_affiliate_payout_consistency_validate", True, True, True),
        "affiliate_payout_commands_no_truncate": (34, "marketedgepros_affiliate_lifecycle_immutable", False, False, False),
    },
}

EXPECTED_INDEXES = {
    IDENTITY: {
        ("affiliate_identity_evidence_pkey", True, True, "id"),
        ("uq_affiliate_identity_evidence_source_event", True, False, "source,event_key"),
        ("uq_affiliate_identity_evidence_tenant_user", True, False, "tenant_id,user_id"),
    },
    ATTRIBUTION: {
        ("affiliate_order_attributions_pkey", True, True, "id"),
        ("uq_affiliate_order_attributions_order", True, False, "order_id"),
    },
    AWARD: {
        ("affiliate_commission_awards_pkey", True, True, "id"),
        ("uq_affiliate_commission_awards_attribution", True, False, "attribution_id"),
        ("uq_affiliate_commission_awards_journal", True, False, "journal_id"),
    },
    COMMAND: {
        ("affiliate_payout_commands_pkey", True, True, "id"),
        ("uq_affiliate_payout_commands_award", True, False, "award_id"),
        ("uq_affiliate_payout_commands_transfer", True, False, "network_id,transfer_key"),
    },
}

ORDER_ID = "00000000-0000-0000-0000-000000000101"
BUYER_EVIDENCE_ID = "00000000-0000-0000-0000-000000000201"
AFFILIATE_EVIDENCE_ID = "00000000-0000-0000-0000-000000000202"
ATTRIBUTION_ID = "00000000-0000-0000-0000-000000000301"
RECEIPT_ID = "00000000-0000-0000-0000-000000000401"
JOURNAL_ID = "00000000-0000-0000-0000-000000000501"
AWARD_ID = "00000000-0000-0000-0000-000000000601"
COMMAND_ID = "00000000-0000-0000-0000-000000000701"
TOKEN_ID = "00000000-0000-0000-0000-000000000702"
ORDER_AT = "2026-10-12 11:00:00"
IDENTITY_AT = "2026-10-12 11:30:00+00"
ATTRIBUTION_AT = "2026-10-12 12:00:00+00"
RECEIPT_AT = "2026-10-12 12:01:00"
AWARD_AT = "2026-10-12 12:02:00+00"
RELEASE_AT = "2026-10-12 13:01:00+00"
POLICY = {
    "version": "TST_LIFECYCLE_1", "rate_basis_points": 1500,
    "basis": "paid_order_total", "currency": "USD", "hold_seconds": 3600,
    "minimum_payout_minor": 100, "rounding": "floor", "mode": "synthetic",
}
POLICY_JSON = json.dumps(POLICY, sort_keys=True, separators=(",", ":"))
POLICY_HASH = hashlib.sha256(POLICY_JSON.encode("utf-8")).hexdigest()


def _normalised_type(type_) -> str:
    rendered = str(type_.compile(dialect=postgresql.dialect())).lower()
    return " ".join(rendered.replace("character varying", "varchar").split())


def _upgrade_parent(connection, config) -> None:
    command.upgrade(config, PREVIOUS)
    assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == PREVIOUS


def _upgrade_lifecycle(connection, config) -> None:
    command.upgrade(config, REVISION)
    assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == REVISION


def _parent_schema(connection) -> dict[str, tuple[tuple[str, str, bool], ...]]:
    inspector = inspect(connection)
    return {
        table: tuple(
            (column["name"], _normalised_type(column["type"]), column["nullable"])
            for column in inspector.get_columns(table, schema="public")
        )
        for table in (
            "tenants", "users", "trading_programs", "purchase_orders",
            "payment_event_receipts", "settlement_journals", "settlement_entries",
        )
    }


def _physical_indexes(connection, table: str) -> set[tuple[str, bool, bool, str]]:
    rows = connection.execute(text("""
        SELECT index_relation.relname AS name, index_meta.indisunique AS is_unique,
               index_meta.indisprimary AS is_primary,
               array_to_string(array_agg(attribute.attname ORDER BY key_part.ordinality), ',') AS columns
        FROM pg_index AS index_meta
        JOIN pg_class AS relation ON relation.oid = index_meta.indrelid
        JOIN pg_namespace AS namespace ON namespace.oid = relation.relnamespace
        JOIN pg_class AS index_relation ON index_relation.oid = index_meta.indexrelid
        LEFT JOIN LATERAL unnest(index_meta.indkey) WITH ORDINALITY AS key_part(attnum, ordinality) ON true
        LEFT JOIN pg_attribute AS attribute
          ON attribute.attrelid=index_meta.indrelid AND attribute.attnum=key_part.attnum
        WHERE namespace.nspname='public' AND relation.relname=:table
        GROUP BY index_relation.relname, index_meta.indisunique, index_meta.indisprimary
    """), {"table": table}).all()
    return {(name, unique, primary, columns) for name, unique, primary, columns in rows}


def _insert_lifecycle_parents(connection) -> None:
    """Insert only explicit synthetic parents; this is not application/service setup."""
    connection.execute(text("""INSERT INTO tenants (id,name,slug,subdomain,status) VALUES
        (1,'Synthetic Lifecycle Tenant','synthetic-lifecycle','synthetic-lifecycle','active'),
        (2,'Synthetic Foreign Tenant','synthetic-foreign','synthetic-foreign','active')"""))
    connection.execute(text("""INSERT INTO users
        (id,email,password_hash,first_name,last_name,role,tenant_id,parent_id,level,tree_path,is_active,is_verified,can_create_same_role)
        VALUES
        (1,'synthetic-root@affiliate.invalid','not-a-credential','Synthetic','Root','supermaster',1,NULL,0,'1',true,true,true),
        (2,'synthetic-buyer@affiliate.invalid','not-a-credential','Synthetic','Buyer','trader',1,1,1,'1/2',true,true,false),
        (3,'synthetic-affiliate@affiliate.invalid','not-a-credential','Synthetic','Affiliate','trader',1,1,1,'1/3',true,true,false),
        (4,'synthetic-other@affiliate.invalid','not-a-credential','Synthetic','Other','trader',1,1,1,'1/4',true,true,false),
        (5,'synthetic-foreign@affiliate.invalid','not-a-credential','Synthetic','Foreign','trader',2,NULL,0,'5',true,true,false)"""))
    connection.execute(text("""INSERT INTO trading_programs
        (id,tenant_id,name,program_type,type,account_size,price,rules,is_active,profit_target,max_daily_loss,max_total_loss,profit_split)
        VALUES
        (10,1,'Synthetic Lifecycle Program','one_phase','one_phase',10000,19.99,
         CAST(:rules AS jsonb),true,10,5,10,80),
        (20,2,'Synthetic Foreign Program','one_phase','one_phase',10000,19.99,
         CAST(:rules AS jsonb),true,10,5,10,80)"""), {
        "rules": '{"source":"synthetic","local_only":true}',
    })
    snapshot = json.dumps({
        "schema": 1, "kind": "purchase_quote", "user_id": 2, "tenant_id": 1,
        "program_id": 10, "currency": "USD", "base_amount": "10.01", "addons": [],
        "amount": "10.01", "rounding": "USD cents", "terms": {"synthetic": True},
        "settlement": "not_configured", "entitlement": False,
    }, sort_keys=True, separators=(",", ":"))
    connection.execute(text("""INSERT INTO purchase_orders
        (id,user_id,tenant_id,program_id,idempotency_key,request_hash,snapshot_hash,snapshot_json,amount_minor,currency,state,created_at)
        VALUES (:id,2,1,10,'affiliate-migration-order',:request_hash,:snapshot_hash,:snapshot,1001,'USD','quoted',:created_at)"""), {
        "id": ORDER_ID, "request_hash": hashlib.sha256(b"affiliate-migration-request").hexdigest(),
        "snapshot_hash": hashlib.sha256(snapshot.encode("utf-8")).hexdigest(),
        "snapshot": snapshot, "created_at": ORDER_AT,
    })


def _insert_identity(connection, identifier: str, user_id: int, tenant_id: int,
                     subject_hash: str, event_key: str) -> None:
    connection.execute(text("""INSERT INTO affiliate_identity_evidence
        (id,user_id,tenant_id,subject_hash,source,event_key,created_at)
        VALUES (:id,:user_id,:tenant_id,:subject_hash,'synthetic',:event_key,:created_at)"""), {
        "id": identifier, "user_id": user_id, "tenant_id": tenant_id,
        "subject_hash": subject_hash, "event_key": event_key, "created_at": IDENTITY_AT,
    })


def _insert_attribution(connection, *, identifier: str = ATTRIBUTION_ID,
                        affiliate_user_id: int = 3,
                        buyer_evidence_id: str = BUYER_EVIDENCE_ID,
                        affiliate_evidence_id: str = AFFILIATE_EVIDENCE_ID,
                        policy_json: str = POLICY_JSON) -> None:
    connection.execute(text("""INSERT INTO affiliate_order_attributions
        (id,order_id,affiliate_user_id,buyer_evidence_id,affiliate_evidence_id,policy_hash,policy_json,created_at)
        VALUES (:id,:order_id,:affiliate_user_id,:buyer_evidence_id,:affiliate_evidence_id,
                :policy_hash,CAST(:policy_json AS jsonb),:created_at)"""), {
        "id": identifier, "order_id": ORDER_ID, "affiliate_user_id": affiliate_user_id,
        "buyer_evidence_id": buyer_evidence_id, "affiliate_evidence_id": affiliate_evidence_id,
        "policy_hash": POLICY_HASH, "policy_json": policy_json, "created_at": ATTRIBUTION_AT,
    })


def _insert_complete_lifecycle(connection) -> None:
    """Build one valid synthetic record entirely with direct SQL for trigger authority tests."""
    _insert_lifecycle_parents(connection)
    connection.commit()
    _insert_identity(connection, BUYER_EVIDENCE_ID, 2, 1, "a" * 64, "migration-buyer")
    _insert_identity(connection, AFFILIATE_EVIDENCE_ID, 3, 1, "b" * 64, "migration-affiliate")
    connection.commit()
    _insert_attribution(connection)
    connection.commit()

    connection.execute(text("""INSERT INTO payment_event_receipts
        (id,source,merchant_context,event_key,order_id,amount_minor,currency,payload_hash,created_at)
        VALUES (:id,'synthetic','isolated-tests','migration-receipt',:order_id,1001,'USD',:payload_hash,:created_at)"""), {
        "id": RECEIPT_ID, "order_id": ORDER_ID, "payload_hash": "4" * 64, "created_at": RECEIPT_AT,
    })
    connection.execute(text("""INSERT INTO settlement_journals
        (id,receipt_id,order_id,amount_minor,currency,created_at)
        VALUES (:id,:receipt_id,:order_id,1001,'USD',:created_at)"""), {
        "id": JOURNAL_ID, "receipt_id": RECEIPT_ID, "order_id": ORDER_ID, "created_at": RECEIPT_AT,
    })
    connection.execute(text("""INSERT INTO settlement_entries
        (id,journal_id,line_number,account_code,side,amount_minor) VALUES
        ('00000000-0000-0000-0000-000000000511',:journal_id,1,'provider_clearing','debit',1001),
        ('00000000-0000-0000-0000-000000000512',:journal_id,2,'unapplied_order_receipts','credit',1001)"""), {
        "journal_id": JOURNAL_ID,
    })
    connection.commit()

    connection.execute(text("""INSERT INTO affiliate_commission_awards
        (id,attribution_id,journal_id,amount_minor,state,review_open,release_at,reversal_event_key,created_at,updated_at)
        VALUES (:id,:attribution_id,:journal_id,150,'held',false,:release_at,NULL,:created_at,:updated_at)"""), {
        "id": AWARD_ID, "attribution_id": ATTRIBUTION_ID, "journal_id": JOURNAL_ID,
        "release_at": RELEASE_AT, "created_at": AWARD_AT, "updated_at": AWARD_AT,
    })
    connection.commit()
    connection.execute(text("""UPDATE affiliate_commission_awards
        SET state='available',updated_at=:updated_at WHERE id=:id"""), {
        "id": AWARD_ID, "updated_at": RELEASE_AT,
    })
    connection.commit()

    connection.execute(text("""INSERT INTO affiliate_payout_commands
        (id,award_id,approved_by,network_id,asset_id,recipient_hash,amount_atomic,quote_hash,
         attempt_token,transfer_key,state,created_at,updated_at)
        VALUES (:id,:award_id,1,'synthetic-local-network','TST_TOKEN',:recipient_hash,987654321,
                :quote_hash,NULL,NULL,'planned',:created_at,:updated_at)"""), {
        "id": COMMAND_ID, "award_id": AWARD_ID, "recipient_hash": "d" * 64,
        "quote_hash": "e" * 64, "created_at": "2026-10-12 13:02:00+00",
        "updated_at": "2026-10-12 13:02:00+00",
    })
    # The deferred consistency constraint permits command creation only when this
    # paired reserve transition occurs in the same transaction.
    connection.execute(text("""UPDATE affiliate_commission_awards
        SET state='reserved',updated_at='2026-10-12 13:02:00+00' WHERE id=:id"""), {"id": AWARD_ID})
    connection.commit()


def test_affiliate_lifecycle_migration_is_frozen_synthetic_schema_only(staging_resources):
    """The revision is the isolated 000008 child and creates only its four relations."""
    source = (BACKEND / "migrations/versions/20261012_000001_affiliate_lifecycle.py").read_text(encoding="utf-8")
    assert 'revision = "20261012_000001"' in source
    assert 'down_revision = "20261011_000008"' in source
    assert "src.models" not in source
    assert "create_all" not in source
    assert "CREATE TABLE IF NOT EXISTS" not in source
    assert "source = 'synthetic'" in source

    with purchase_order_database(staging_resources) as (connection, config):
        _upgrade_parent(connection, config)
        parents_before = _parent_schema(connection)
        relations_before = set(inspect(connection).get_table_names(schema="public"))
        _upgrade_lifecycle(connection, config)
        inspector = inspect(connection)
        assert set(inspector.get_table_names(schema="public")) - relations_before == TABLES
        assert _parent_schema(connection) == parents_before

        for table in TABLES:
            columns = {column["name"]: column for column in inspector.get_columns(table, schema="public")}
            assert set(columns) == set(EXPECTED_COLUMNS[table])
            for name, (expected_type, nullable) in EXPECTED_COLUMNS[table].items():
                assert _normalised_type(columns[name]["type"]) == expected_type
                assert columns[name]["nullable"] is nullable
                assert columns[name]["default"] is None
            primary_key = inspector.get_pk_constraint(table, schema="public")
            assert primary_key["constrained_columns"] == ["id"]
            assert primary_key["name"] == table + "_pkey"
            foreign_keys = {item["name"]: item for item in inspector.get_foreign_keys(table, schema="public")}
            assert set(foreign_keys) == set(EXPECTED_FOREIGN_KEYS[table])
            for name, (column, parent) in EXPECTED_FOREIGN_KEYS[table].items():
                actual = foreign_keys[name]
                assert actual["constrained_columns"] == [column]
                assert actual["referred_table"] == parent
                assert actual["referred_columns"] == ["id"]
                assert actual["referred_schema"] in (None, "public")
                assert not actual.get("options")
            uniques = {item["name"]: item["column_names"]
                       for item in inspector.get_unique_constraints(table, schema="public")}
            assert uniques == EXPECTED_UNIQUES[table]
            assert {item["name"] for item in inspector.get_check_constraints(table, schema="public")} == EXPECTED_CHECKS[table]
            assert _physical_indexes(connection, table) == EXPECTED_INDEXES[table]

        trigger_rows = connection.execute(text("""
            SELECT relation.relname, trigger.tgname, trigger.tgtype, procedure.proname,
                   trigger.tgconstraint <> 0 AS is_constraint,
                   trigger.tgdeferrable, trigger.tginitdeferred, trigger.tgenabled,
                   trigger.tgqual IS NULL AS no_when, trigger.tgnargs
            FROM pg_trigger AS trigger
            JOIN pg_class AS relation ON relation.oid=trigger.tgrelid
            JOIN pg_namespace AS namespace ON namespace.oid=relation.relnamespace
            JOIN pg_proc AS procedure ON procedure.oid=trigger.tgfoid
            WHERE namespace.nspname='public' AND relation.relname = ANY(:tables)
              AND NOT trigger.tgisinternal
        """), {"tables": sorted(TABLES)}).all()
        actual_triggers = {
            (table, name): (tgtype, function, constraint, deferrable, deferred)
            for table, name, tgtype, function, constraint, deferrable, deferred, enabled, no_when, nargs in trigger_rows
            if enabled == "O" and no_when and nargs == 0
        }
        expected_triggers = {
            (table, name): definition
            for table, triggers in EXPECTED_TRIGGERS.items()
            for name, definition in triggers.items()
        }
        assert actual_triggers == expected_triggers
        assert len(trigger_rows) == len(expected_triggers)

        functions = connection.execute(text("""
            SELECT procedure.proname, pg_get_function_identity_arguments(procedure.oid),
                   procedure.prorettype::regtype::text, procedure.prokind, language.lanname,
                   procedure.provolatile, procedure.proisstrict, procedure.prosecdef,
                   procedure.proleakproof, procedure.proparallel, procedure.proconfig, procedure.proacl
            FROM pg_proc AS procedure
            JOIN pg_namespace AS namespace ON namespace.oid=procedure.pronamespace
            JOIN pg_language AS language ON language.oid=procedure.prolang
            WHERE namespace.nspname='public' AND procedure.proname = ANY(:names)
            ORDER BY procedure.proname
        """), {"names": sorted(FUNCTIONS)}).all()
        assert len(functions) == len(FUNCTIONS)
        for name, signature, return_type, kind, language, volatility, strict, secdef, leakproof, parallel, config, acl in functions:
            assert (signature, return_type) == FUNCTIONS[name]
            assert (kind, language, volatility, strict, secdef, leakproof, parallel, config, acl) == (
                "f", "plpgsql", "v", False, False, False, "u", None, None,
            )


@pytest.mark.parametrize("kind, setup, colliding_tables", [
    (
        "relation",
        "CREATE TABLE affiliate_identity_evidence (id integer PRIMARY KEY)",
        {IDENTITY},
    ),
    (
        "index",
        "CREATE INDEX uq_affiliate_payout_commands_transfer ON users (id)",
        set(),
    ),
    (
        "function-overload",
        """CREATE FUNCTION public.marketedgepros_affiliate_lifecycle_immutable(ignored integer)
           RETURNS integer LANGUAGE sql AS $$ SELECT ignored $$""",
        set(),
    ),
    (
        "parent-drift",
        "ALTER TABLE purchase_orders ALTER COLUMN amount_minor TYPE integer",
        set(),
    ),
], ids=lambda item: item if isinstance(item, str) else None)
def test_affiliate_lifecycle_online_preflight_refuses_collision_or_parent_drift_before_ddl(
    staging_resources, kind, setup, colliding_tables
):
    """All owned relation/function names and source-parent shape are proved before first DDL."""
    with purchase_order_database(staging_resources) as (connection, config):
        _upgrade_parent(connection, config)
        connection.execute(text(setup))
        connection.commit()
        with record_schema_ddl(connection) as emitted:
            with pytest.raises(RuntimeError, match="Affiliate lifecycle schema collision before DDL"):
                _upgrade_lifecycle(connection, config)
        assert emitted == []
        assert set(inspect(connection).get_table_names(schema="public")).intersection(TABLES) == colliding_tables
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == PREVIOUS


def test_affiliate_lifecycle_empty_downgrade_succeeds_and_reupgrades(staging_resources):
    """An empty, exact schema can be removed online and recreated; no data is inferred."""
    with purchase_order_database(staging_resources) as (connection, config):
        _upgrade_parent(connection, config)
        _upgrade_lifecycle(connection, config)
        command.downgrade(config, PREVIOUS)
        assert not TABLES.intersection(inspect(connection).get_table_names(schema="public"))
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == PREVIOUS
        _upgrade_lifecycle(connection, config)
        assert all(connection.execute(text(f"SELECT count(*) FROM public.{table}")).scalar_one() == 0 for table in TABLES)


def test_affiliate_lifecycle_nonempty_downgrade_refuses_before_drop(staging_resources):
    """A single valid synthetic evidence row blocks every drop and retains the current revision."""
    with purchase_order_database(staging_resources) as (connection, config):
        _upgrade_parent(connection, config)
        _upgrade_lifecycle(connection, config)
        _insert_lifecycle_parents(connection)
        _insert_identity(connection, BUYER_EVIDENCE_ID, 2, 1, "a" * 64, "nonempty-downgrade")
        connection.commit()
        with record_schema_ddl(connection) as emitted:
            with pytest.raises(RuntimeError, match="refuses to delete synthetic lifecycle evidence"):
                command.downgrade(config, PREVIOUS)
        assert emitted == []
        assert connection.execute(text(f"SELECT count(*) FROM {IDENTITY}")).scalar_one() == 1
        assert TABLES.issubset(inspect(connection).get_table_names(schema="public"))
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == REVISION


@pytest.mark.parametrize("alteration", [
    "CREATE INDEX affiliate_lifecycle_foreign_expression ON affiliate_identity_evidence ((lower(event_key)))",
    "ALTER TABLE affiliate_order_attributions DISABLE TRIGGER affiliate_order_attributions_validate_insert",
    """CREATE OR REPLACE FUNCTION public.marketedgepros_affiliate_lifecycle_immutable()
       RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END; $$""",
    "CREATE VIEW affiliate_lifecycle_external_view AS SELECT id FROM affiliate_identity_evidence",
    """CREATE TABLE affiliate_lifecycle_external_fk (
       id integer PRIMARY KEY,
       evidence_id varchar(36) REFERENCES affiliate_identity_evidence(id)
    )""",
], ids=["extra-expression-index", "disabled-trigger", "function-drift", "view-dependent", "foreign-key-dependent"])
def test_affiliate_lifecycle_downgrade_refuses_altered_metadata_or_extra_dependency_before_drop(
    staging_resources, alteration
):
    """No trigger/function/table cleanup begins after ownership metadata or dependents drift."""
    with purchase_order_database(staging_resources) as (connection, config):
        _upgrade_parent(connection, config)
        _upgrade_lifecycle(connection, config)
        connection.execute(text(alteration))
        connection.commit()
        with record_schema_ddl(connection) as emitted:
            with pytest.raises(RuntimeError, match="changed ownership metadata before DDL"):
                command.downgrade(config, PREVIOUS)
        assert emitted == []
        assert TABLES.issubset(inspect(connection).get_table_names(schema="public"))
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == REVISION


def test_affiliate_lifecycle_direct_sql_refuses_self_subject_scope_and_malformed_policy(staging_resources):
    """Triggers, not the service, reject self-referral, same-person, foreign scope, and malformed policy."""
    with purchase_order_database(staging_resources) as (connection, config):
        _upgrade_parent(connection, config)
        _upgrade_lifecycle(connection, config)
        _insert_lifecycle_parents(connection)
        connection.commit()
        # Same evidence/user is a self-referral; a duplicate subject remains evidence but is ineligible.
        _insert_identity(connection, BUYER_EVIDENCE_ID, 2, 1, "a" * 64, "direct-buyer")
        _insert_identity(connection, AFFILIATE_EVIDENCE_ID, 3, 1, "a" * 64, "direct-same-subject")
        _insert_identity(connection, "00000000-0000-0000-0000-000000000203", 4, 1, "c" * 64, "direct-valid-affiliate")
        _insert_identity(connection, "00000000-0000-0000-0000-000000000204", 5, 2, "b" * 64, "direct-foreign-affiliate")
        connection.commit()

        invalid_attributions = [
            {
                "identifier": "00000000-0000-0000-0000-000000000311", "affiliate_user_id": 2,
                "buyer_evidence_id": BUYER_EVIDENCE_ID, "affiliate_evidence_id": BUYER_EVIDENCE_ID,
                "policy_json": POLICY_JSON,
            },
            {
                "identifier": "00000000-0000-0000-0000-000000000312", "affiliate_user_id": 3,
                "buyer_evidence_id": BUYER_EVIDENCE_ID, "affiliate_evidence_id": AFFILIATE_EVIDENCE_ID,
                "policy_json": POLICY_JSON,
            },
            {
                "identifier": "00000000-0000-0000-0000-000000000313", "affiliate_user_id": 5,
                "buyer_evidence_id": BUYER_EVIDENCE_ID,
                "affiliate_evidence_id": "00000000-0000-0000-0000-000000000204",
                "policy_json": POLICY_JSON,
            },
            {
                "identifier": "00000000-0000-0000-0000-000000000314", "affiliate_user_id": 4,
                "buyer_evidence_id": BUYER_EVIDENCE_ID,
                "affiliate_evidence_id": "00000000-0000-0000-0000-000000000203",
                "policy_json": json.dumps({"version": "malformed"}),
            },
        ]
        for values in invalid_attributions:
            with pytest.raises(DBAPIError):
                _insert_attribution(connection, **values)
            connection.rollback()
        assert connection.execute(text("SELECT count(*) FROM affiliate_identity_evidence")).scalar_one() == 4
        assert connection.execute(text("SELECT count(*) FROM affiliate_order_attributions")).scalar_one() == 0


def test_affiliate_lifecycle_direct_sql_cannot_bypass_tokens_state_immutability_or_truncate(staging_resources):
    """Raw SQL cannot null-token a dispatch, skip states, rewrite evidence, or truncate lifecycle rows."""
    with purchase_order_database(staging_resources) as (connection, config):
        _upgrade_parent(connection, config)
        _upgrade_lifecycle(connection, config)
        _insert_complete_lifecycle(connection)

        attempts = [
            ("UPDATE affiliate_identity_evidence SET subject_hash='f' || repeat('a',63) WHERE id=:id", {"id": BUYER_EVIDENCE_ID}),
            ("UPDATE affiliate_order_attributions SET policy_hash=repeat('f',64) WHERE id=:id", {"id": ATTRIBUTION_ID}),
            ("UPDATE affiliate_commission_awards SET state='paid',updated_at='2026-10-12 13:03:00+00' WHERE id=:id", {"id": AWARD_ID}),
            ("""UPDATE affiliate_payout_commands SET state='dispatched',attempt_token=NULL,
                updated_at='2026-10-12 13:03:00+00' WHERE id=:id""", {"id": COMMAND_ID}),
            ("""UPDATE affiliate_payout_commands SET state='confirmed',attempt_token=:token,
                transfer_key='direct-skip-state',updated_at='2026-10-12 13:03:00+00' WHERE id=:id""", {"id": COMMAND_ID, "token": TOKEN_ID}),
            ("DELETE FROM affiliate_commission_awards WHERE id=:id", {"id": AWARD_ID}),
        ]
        for statement, params in attempts:
            with pytest.raises(DBAPIError):
                connection.execute(text(statement), params)
            connection.rollback()

        for table in (IDENTITY, ATTRIBUTION, AWARD, COMMAND):
            with pytest.raises(DBAPIError):
                connection.execute(text(f"TRUNCATE public.{table} CASCADE"))
            connection.rollback()
        assert tuple(connection.execute(text("""SELECT
            (SELECT count(*) FROM affiliate_identity_evidence),
            (SELECT count(*) FROM affiliate_order_attributions),
            (SELECT count(*) FROM affiliate_commission_awards),
            (SELECT count(*) FROM affiliate_payout_commands)
        """)).one()) == (2, 1, 1, 1)
        assert connection.execute(text("SELECT state FROM affiliate_commission_awards WHERE id=:id"), {"id": AWARD_ID}).scalar_one() == "reserved"
        assert connection.execute(text("SELECT state,attempt_token,transfer_key FROM affiliate_payout_commands WHERE id=:id"), {"id": COMMAND_ID}).one() == ("planned", None, None)


def test_affiliate_policy_digest_is_database_authority_not_only_service(staging_resources):
    """Well-shaped wrong digests cannot be persisted by direct SQL."""
    with purchase_order_database(staging_resources) as (connection, config):
        _upgrade_parent(connection, config)
        _upgrade_lifecycle(connection, config)
        _insert_lifecycle_parents(connection)
        connection.commit()
        _insert_identity(connection, BUYER_EVIDENCE_ID, 2, 1, 'a' * 64, 'digest-buyer')
        _insert_identity(connection, AFFILIATE_EVIDENCE_ID, 3, 1, 'b' * 64, 'digest-affiliate')
        connection.commit()
        with pytest.raises(DBAPIError, match='policy fingerprint'):
            connection.execute(text('''INSERT INTO affiliate_order_attributions
                (id,order_id,affiliate_user_id,buyer_evidence_id,affiliate_evidence_id,policy_hash,policy_json,created_at)
                VALUES (:id,:order,3,:buyer,:affiliate,:wrong,CAST(:policy AS jsonb),:at)'''),
                {'id': ATTRIBUTION_ID, 'order': ORDER_ID, 'buyer': BUYER_EVIDENCE_ID,
                 'affiliate': AFFILIATE_EVIDENCE_ID, 'wrong': '0' * 64,
                 'policy': POLICY_JSON, 'at': ATTRIBUTION_AT})
        connection.rollback()
        assert connection.execute(text('SELECT count(*) FROM affiliate_order_attributions')).scalar_one() == 0
        assert connection.execute(text('SELECT count(*) FROM affiliate_commission_awards')).scalar_one() == 0
        _insert_attribution(connection)
        connection.commit()
        assert connection.execute(text('SELECT policy_hash FROM affiliate_order_attributions')).scalar_one() == POLICY_HASH


def test_affiliate_migration_refuses_shadow_search_path_before_any_ddl(staging_resources):
    with purchase_order_database(staging_resources) as (connection, config):
        _upgrade_parent(connection, config)
        connection.execute(text('CREATE SCHEMA affiliate_shadow'))
        connection.commit()
        connection.execute(text('SET search_path TO affiliate_shadow, public'))
        with record_schema_ddl(connection) as emitted:
            with pytest.raises(RuntimeError, match='unsafe search path'):
                _upgrade_lifecycle(connection, config)
        assert emitted == []
        assert not TABLES.intersection(inspect(connection).get_table_names(schema='public'))
        assert not TABLES.intersection(inspect(connection).get_table_names(schema='affiliate_shadow'))
        connection.execute(text('RESET search_path'))
