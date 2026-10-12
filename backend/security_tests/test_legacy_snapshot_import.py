"""Synthetic-only tests for the reviewed legacy snapshot importer.

No test imports the Flask app, opens a database connection, invokes a subprocess,
or reads a real snapshot.  The importer driver is loaded as a plain module and its
pure planning/serialization functions are exercised with catalog fixtures.
"""
from __future__ import annotations

from decimal import Decimal
import importlib.util
import json
from pathlib import Path
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "import_legacy_snapshot.py"
SPEC = importlib.util.spec_from_file_location("legacy_snapshot_import_under_test", SCRIPT)
assert SPEC and SPEC.loader
legacy = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = legacy
SPEC.loader.exec_module(legacy)


def column(name, display_type="character varying(255)", nullable=False, default=None):
    return legacy.CatalogColumn(
        name=name,
        metadata_type=legacy._base_type(display_type),
        nullable=nullable,
        display_type=display_type,
        default=default,
        identity=False,
        generated=False,
    )


def metadata_for(*table_rows):
    """Create the smallest reviewed-metadata object needed by pure planner tests."""
    counts = {"old": {}, "new": {}}
    columns = {"old": {}, "new": {}}
    csv_rows = {}
    for table, source, target, rows in table_rows:
        counts["old"][table] = rows
        counts["new"][table] = 0
        columns["old"][table] = {
            name: {"type": spec.metadata_type, "nullable": "YES" if spec.nullable else "NO"}
            for name, spec in source.items()
        }
        columns["new"][table] = {
            name: {"type": spec.metadata_type, "nullable": "YES" if spec.nullable else "NO"}
            for name, spec in target.items()
        }
        csv_rows[table] = tuple(
            {
                "table": table,
                "column": name,
                "status": "same",
                "old_type": source[name].metadata_type,
                "new_type": target[name].metadata_type,
                "old_nullable": "YES" if source[name].nullable else "NO",
                "new_nullable": "YES" if target[name].nullable else "NO",
            }
            for name in source.keys() & target.keys()
        )
    return legacy.ReviewedMetadata(
        counts=counts,
        columns=columns,
        csv_rows=csv_rows,
        metadata_digest="a" * 64,
        csv_digest="b" * 64,
    )


def test_cli_is_dry_run_by_default_and_disallows_dsn_switches():
    args = legacy._parser().parse_args([
        "--metadata", "/tmp/review.json",
        "--schema-csv", "/tmp/review.csv",
        "--expected-source-digest", "a" * 64,
        "--expected-metadata-digest", "b" * 64,
        "--expected-schema-csv-digest", "c" * 64,
    ])
    assert args.apply is False
    assert legacy.SOURCE_DATABASE == "marketedgepros_transfer_source_20261013"
    assert legacy.TARGET_DATABASE == "marketedgepros_demo_20261012"
    source = SCRIPT.read_text(encoding="utf-8")
    assert "subprocess" not in source
    assert "--source-dsn" not in source
    assert "--target-dsn" not in source
    assert "postgresql://" not in source


def test_reviewed_tenant_mappings_are_closed_and_do_not_infer_unknown_status():
    source = {
        "subdomain": column("subdomain"),
        "status": column("status"),
    }
    target = {
        "slug": column("slug"),
        "is_active": column("is_active", "boolean"),
    }
    review = metadata_for(("tenants", source, target, 2))
    plan = legacy._build_table_plans(review, {"tenants": source}, {"tenants": target}, {"tenants": 2})["tenants"]
    assert plan.active
    assert {(item.source, item.target, item.transform) for item in plan.mappings} == {
        ("subdomain", "slug", "copy"),
        ("status", "is_active", "tenant_status_to_is_active"),
    }
    assert legacy._materialize_row(plan, '{"subdomain":"known","status":"active"}') == {
        "slug": "known", "is_active": True
    }
    assert legacy._materialize_row(plan, '{"subdomain":"known","status":"suspended"}') == {
        "slug": "known", "is_active": False
    }
    with pytest.raises(legacy.ImportRefusal, match="unknown_tenant_status"):
        legacy._materialize_row(plan, '{"subdomain":"known","status":"pending_review"}')


def test_reviewed_program_renames_never_turn_instant_funding_into_type():
    source = {
        "type": column("type"),
        "minimum_trading_days": column("minimum_trading_days", "integer", nullable=True),
        "instant_funding": column("instant_funding", "boolean", nullable=True),
    }
    target = {
        "program_type": column("program_type"),
        "min_trading_days": column("min_trading_days", "integer", nullable=True),
        "type": column("type", nullable=True),
    }
    review = metadata_for(("trading_programs", source, target, 1))
    plan = legacy._build_table_plans(review, {"trading_programs": source}, {"trading_programs": target}, {"trading_programs": 1})["trading_programs"]
    mapping = {(item.source, item.target) for item in plan.mappings}
    assert ("type", "program_type") in mapping
    assert ("minimum_trading_days", "min_trading_days") in mapping
    assert all(source_name != "instant_funding" for source_name, _ in mapping)


def test_user_password_hash_is_preserved_but_token_version_is_separated():
    source = {
        "password_hash": column("password_hash"),
        "token_version": column("token_version", "integer", nullable=True),
    }
    target = {
        "password_hash": column("password_hash"),
        "token_version": column("token_version", "integer"),
        "can_create_same_role": column("can_create_same_role", "boolean"),
    }
    review = metadata_for(("users", source, target, 1))
    plan = legacy._build_table_plans(review, {"users": source}, {"users": target}, {"users": 1})["users"]
    assert legacy._materialize_row(plan, '{"password_hash":"stored-only-hash","token_version":4}') == {
        "password_hash": "stored-only-hash", "token_version": 5
    }
    assert legacy._materialize_row(plan, '{"password_hash":"stored-only-hash","token_version":null}')["token_version"] == 1
    with pytest.raises(legacy.ImportRefusal, match="invalid_source_token_version"):
        legacy._materialize_row(plan, '{"password_hash":"stored-only-hash","token_version":-1}')


def test_tokens_are_archive_only_and_old_alembic_is_archived_not_active():
    source = {"token": column("token")}
    target = {"token": column("token")}
    alembic_source = {"version_num": column("version_num")}
    review = metadata_for(
        ("email_verification_tokens", source, target, 1),
        ("alembic_version", alembic_source, alembic_source, 1),
    )
    plans = legacy._build_table_plans(
        review,
        {"email_verification_tokens": source, "alembic_version": alembic_source},
        {"email_verification_tokens": target, "alembic_version": alembic_source},
        {"email_verification_tokens": 1, "alembic_version": 1},
    )
    assert plans["email_verification_tokens"].active is False
    assert "archive_only" in plans["email_verification_tokens"].archive_only_reason
    assert plans["alembic_version"].active is False
    assert plans["alembic_version"].archive_only_reason == "obsolete_alembic_control_record_archive_only"


def test_unmapped_required_target_field_makes_a_nonempty_table_archive_only():
    source = {"id": column("id", "integer")}
    target = {"id": column("id", "integer"), "phase": column("phase", "integer")}
    review = metadata_for(("challenges", source, target, 1))
    plan = legacy._build_table_plans(review, {"challenges": source}, {"challenges": target}, {"challenges": 1})["challenges"]
    assert plan.active is False
    assert plan.mappings == ()
    assert plan.archive_only_reason == "required_target_field_unmapped:phase"


def test_nullability_blocker_is_aggregate_only_and_has_no_source_value(monkeypatch):
    source = {"profit_target": column("profit_target", "numeric(15,2)", nullable=True)}
    target = {"profit_target": column("profit_target", "numeric(10,2)")}
    review = metadata_for(("trading_programs", source, target, 2))
    plan = legacy._build_table_plans(review, {"trading_programs": source}, {"trading_programs": target}, {"trading_programs": 2})["trading_programs"]
    plan.source_rows = ['{"profit_target":null}', '{"profit_target":123.45}']
    monkeypatch.setattr(legacy, "_SOURCE_DISPLAY_TYPES", {"trading_programs": {"profit_target": "numeric(15,2)"}})
    legacy._collect_compatibility_issues({"trading_programs": plan})
    assert "required_target_value_missing:profit_target:count=1" in plan.compatibility_issues
    assert all("123.45" not in item for item in plan.compatibility_issues)


def test_archive_serialization_keeps_decimal_numbers_as_numbers_and_report_has_no_row_content():
    raw = '{"email":"private@example.test","amount":12345678901234567890.00100,"nested":{"n":1.20}}'
    decoded = legacy._decode_record(raw)
    assert decoded["amount"] == Decimal("12345678901234567890.00100")
    rendered = legacy._decimal_json(decoded)
    assert '"12345678901234567890.00100"' not in rendered
    assert "12345678901234567890.00100" in rendered
    plan = legacy.TablePlan(name="leads", source_columns=("email", "amount"), source_rows=[raw])
    snapshot = legacy.Snapshot(
        tables={"leads": plan}, digest="d" * 64,
        table_fingerprints={"leads": legacy._fingerprint_rows("leads", [raw])},
    )
    review = legacy.ReviewedMetadata({"old": {}, "new": {}}, {"old": {}, "new": {}}, {}, "a" * 64, "b" * 64)
    report = json.dumps(legacy._report(snapshot, review, apply=False, runtime_role=None))
    assert "private@example.test" not in report
    assert "12345678901234567890.00100" not in report


def test_archive_identity_has_an_ordinal_so_duplicate_source_rows_are_not_lost():
    duplicate = '{"same":"record"}'
    assert legacy._fingerprint_rows("legacy_table", [duplicate, duplicate]) != legacy._fingerprint_rows(
        "legacy_table", [duplicate]
    )
    source = SCRIPT.read_text(encoding="utf-8")
    assert "archive_ordinal bigint NOT NULL" in source
    assert "PRIMARY KEY (source_table, archive_ordinal)" in source


def test_nondeferrable_cross_table_cycle_refuses_but_self_edges_are_not_a_cycle():
    assert legacy._topological_order({"tenants": set(), "users": {"tenants"}}) == ["tenants", "users"]
    with pytest.raises(legacy.ImportRefusal, match="non_deferrable_foreign_key_cycle"):
        legacy._topological_order({"users": {"tenants"}, "tenants": {"users"}})


def test_canonical_json_fingerprints_ignore_key_spacing_and_numeric_scale_without_rounding():
    assert legacy._canonical_json_text('{"z":1.00,"a":{"n":123456789012345678901234567890.1200}}') == legacy._canonical_json_text('{ "a": {"n":123456789012345678901234567890.12}, "z":1 }')
    assert legacy._canonical_json_text('{"n":-0.00}') == '{"n":0}'


def test_reviewed_json_and_integral_numeric_transports_are_semantic_and_null_preserving():
    source = {"tags": column("tags", "jsonb", nullable=True), "profit_split_percentage": column("profit_split_percentage", "integer", nullable=True)}
    target = {"tags": column("tags", "json", nullable=True), "profit_split_percentage": column("profit_split_percentage", "numeric(10,2)", nullable=True)}
    review = metadata_for(("trading_programs", source, target, 1))
    plan = legacy._build_table_plans(review, {"trading_programs": source}, {"trading_programs": target}, {"trading_programs": 1})["trading_programs"]
    assert legacy._materialize_row(plan, '{"tags":["a", "b"],"profit_split_percentage":80}') == {"tags": ["a", "b"], "profit_split_percentage": Decimal(80)}
    assert legacy._materialize_row(plan, '{"tags":null,"profit_split_percentage":null}') == {"tags": None, "profit_split_percentage": None}
    with pytest.raises(legacy.ImportRefusal, match="integer_to_numeric_source_invalid"):
        legacy._materialize_row(plan, '{"tags":[],"profit_split_percentage":80.1}')


def test_explicit_brand_rename_preserves_ids_and_unrelated_fields_instead_of_remapping_owner():
    plan = legacy.TablePlan(name="tenants", source_columns=("id", "name", "slug", "subdomain", "parent_id"), mappings=tuple(legacy.FieldMap(field,field) for field in ("id", "name", "slug", "subdomain", "parent_id")), approved_brand_tenant_id=17)
    original = '{"id":17,"name":"old-name","slug":"old-slug","subdomain":"old-slug","parent_id":null}'
    mapped=legacy._materialize_row(plan, original)
    assert mapped == {"id":17,"name":"MarketEdgePros","slug":"marketedgepros","subdomain":"marketedgepros","parent_id":None}
    assert legacy._materialize_row(plan, original.replace('17','18'))["name"] == "old-name"
    assert legacy._decode_record(original)["name"] == "old-name"


@pytest.mark.parametrize('status',['old_only','new_only','ignored','pending',''])
def test_direct_mapping_rejects_unapproved_or_inconsistent_review_status(status):
    source = {'id':column('id','integer')}
    review = metadata_for(('leads',source,source,1))
    rows = [dict(item,status=status) for item in review.csv_rows['leads']]
    review = legacy.ReviewedMetadata(review.counts,review.columns,{'leads':tuple(rows)},review.metadata_digest,review.csv_digest)
    with pytest.raises(legacy.ImportRefusal, match='reviewed_csv_status'):
        legacy._build_table_plans(review,{'leads':source},{'leads':source},{'leads':1})


@pytest.mark.parametrize('metadata_digest,csv_digest',[('0'*64,'b'*64),('a'*64,'0'*64),('bad','b'*64)])
def test_review_digest_mismatch_refuses_before_any_database_connection(monkeypatch,metadata_digest,csv_digest):
    from argparse import Namespace
    monkeypatch.setattr(legacy,'_read_reviewed_metadata',lambda *args: legacy.ReviewedMetadata({'old':{},'new':{}},{'old':{},'new':{}},{},'a'*64,'b'*64))
    monkeypatch.setattr(legacy,'_connect',lambda *args,**kwargs: pytest.fail('must refuse before database access'))
    args=Namespace(expected_source_digest='c'*64,runtime_role=None,apply=False,metadata=Path('/tmp/synthetic.json'),schema_csv=Path('/tmp/synthetic.csv'),expected_metadata_digest=metadata_digest,expected_schema_csv_digest=csv_digest)
    with pytest.raises(legacy.ImportRefusal,match='reviewed_metadata_digest_mismatch'):
        legacy.run(args)
