#!/usr/bin/env python3
"""Validate a reviewed private pg_dump in a disposable, no-network restore.

No DATABASE_URL, production connection, role elevation, financial backfill or
blind Alembic stamp is accepted. The legacy out-of-band schema remains explicitly
labelled: this is a restore rehearsal, NOT a production deployment tool.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import socket
import stat
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

import run_staging_integration as isolated

BACKEND = Path(__file__).resolve().parents[1]
LEGACY_HEAD = '20251110_191500'
MONITOR_TABLES = {'monitoring_alerts', 'monitoring_events', 'violation_logs'}


def _private_backup(path, expected):
    path = Path(path).absolute()
    if not re.fullmatch(r'[0-9a-f]{64}', expected):
        raise ValueError('An explicit reviewed backup digest is required')
    for part in [path, *path.parents]:
        if part.is_symlink():
            raise ValueError('Backup path must not contain symlinks')
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError('Backup must be a private caller-owned regular file')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected:
        raise ValueError('Backup digest differs from the reviewed snapshot')
    return path


def _json_rows(con, table):
    from sqlalchemy import text
    return [row[0] for row in con.execute(text(f'SELECT to_jsonb(t) FROM "{table}" t'))]


def _fingerprints(con, tables, *, user_identity=False):
    from sqlalchemy import text
    result = {}
    for table in tables:
        value = 'to_jsonb(t)'
        if table == 'users' and user_identity:
            value += " - ARRAY['tenant_id','tree_path','token_version']"
        row = con.execute(text(f"SELECT count(*), md5(COALESCE(string_agg(doc, chr(10) ORDER BY doc), '')) FROM (SELECT ({value})::text AS doc FROM \"{table}\" t) s")).one()
        result[table] = {'rows': row[0], 'digest': row[1]}
    return result


def _missing_shape(engine, metadata):
    from sqlalchemy import inspect
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    missing_tables = sorted(set(metadata.tables) - tables)
    missing_columns = {}
    for name, table in metadata.tables.items():
        if name in tables:
            names = {c['name'] for c in inspector.get_columns(name)}
            if set(table.columns.keys()) - names:
                missing_columns[name] = sorted(set(table.columns.keys()) - names)
    return missing_tables, missing_columns


def _restore_monitoring_shape(con):
    """Replay only the three reviewed frozen DDL definitions, never all models.

    Legacy rows/core columns are not touched; no schema ownership is stamped.
    """
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    import sqlalchemy as sa
    from sqlalchemy.dialects import postgresql
    source = BACKEND / 'migrations/versions/20261011_000003_add_missing_model_tables.py'
    syntax = ast.parse(source.read_text())
    upgrade = next(node for node in syntax.body if isinstance(node, ast.FunctionDef) and node.name == 'upgrade')
    selected = []
    for node in upgrade.body:
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        if not isinstance(call.func, ast.Attribute) or not isinstance(call.func.value, ast.Name) or call.func.value.id != 'op':
            continue
        index = 0 if call.func.attr == 'create_table' else 1 if call.func.attr == 'create_index' else None
        if index is not None and len(call.args) > index and isinstance(call.args[index], ast.Constant) and call.args[index].value in MONITOR_TABLES:
            selected.append(node)
    table_calls = [node for node in selected if node.value.func.attr == 'create_table']
    if {node.value.args[0].value for node in table_calls} != MONITOR_TABLES:
        raise RuntimeError('Frozen monitoring DDL snapshot is incomplete')
    namespace = {'op': Operations(MigrationContext.configure(con)), 'sa': sa, 'postgresql': postgresql}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(source), 'exec'), namespace)


def _inner(args):
    isolated._require_clean_python()
    isolated._assert_inner_namespace()
    backup = _private_backup(args.backup, args.backup_sha256)
    sys.path.insert(0, str(BACKEND))
    root = Path(tempfile.mkdtemp(prefix='marketedgepros-staging-'))
    os.chmod(root, 0o700)
    env = dict(os.environ)
    data = None
    engine = None
    checks = []
    report = {'mode': 'isolated-restored-copy-only', 'production_modified': False,
              'backup_sha256': args.backup_sha256, 'checks': checks,
              'schema_history_boundary': 'Legacy out-of-band schema: no blind upgrade/stamp; original Alembic version is preserved.'}

    def check(name, condition):
        checks.append({'name': name, 'passed': bool(condition)})
        if not condition:
            raise AssertionError(name)

    try:
        data, sock, database, url = isolated._start_postgres(root, env)
        env.update({'PYTHONPATH': str(BACKEND), 'STAGING_RUN_ROOT': str(root),
                    'STAGING_DATABASE_NAME': database, 'STAGING_PG_SOCKET': str(sock),
                    'STAGING_PG_PORT': isolated.PG_PORT, 'STAGING_PG_URL': url,
                    'TEST_DATABASE_URL': url})
        os.environ.update(env)
        result = subprocess.run([str(isolated.PG_BIN / 'pg_restore'), '-h', str(sock), '-p', isolated.PG_PORT,
                                 '-U', env['STAGING_RUNTIME_USER'], '-d', database, '--single-transaction',
                                 '--exit-on-error', '--no-owner', '--no-acl', str(backup)],
                                env=env, capture_output=True, timeout=90)
        check('restore_single_transaction', result.returncode == 0)
        from sqlalchemy import create_engine, inspect, text
        from src.schema_inventory import load_complete_model_inventory
        from src.database import db
        from src.services.launch_reconciliation_service import plan_single_brand_reconciliation, apply_plan_to_isolated_copy
        from src.app import create_app
        from src.models.user import User
        from src.utils.hierarchy_scoping import without_hierarchy_scope
        load_complete_model_inventory()
        engine = create_engine(url)
        original_tables = sorted(inspect(engine).get_table_names())
        with engine.connect() as con:
            before = _fingerprints(con, original_tables)
            identity_before = _fingerprints(con, ['users'], user_identity=True)
            versions = list(con.execute(text('SELECT version_num FROM alembic_version')).scalars())
            check('legacy_version_provenance', versions == [LEGACY_HEAD])
            users, tenants, challenges, programs = [_json_rows(con, name) for name in ('users', 'tenants', 'challenges', 'trading_programs')]
        report['original_rows'] = sum(value['rows'] for value in before.values())
        report['original_tables'] = len(original_tables)
        plan = plan_single_brand_reconciliation(users, tenants, challenges, programs, owner_id=args.owner_id, brand_id=args.brand_id)
        report['identity_changes_proposed'] = len(plan['changes'])
        report['other_brand_users_preserved'] = sum(item['reason'] == 'existing_other_brand' for item in plan['excluded'])
        missing_tables, missing_columns = _missing_shape(engine, db.metadata)
        report['restored_missing_tables_before'] = missing_tables
        check('reviewed_missing_shape_only', set(missing_tables) == MONITOR_TABLES and not missing_columns)
        with engine.begin() as con:
            _restore_monitoring_shape(con)
        check('all_declared_model_columns_available', _missing_shape(engine, db.metadata) == ([], {}))
        app = create_app('testing', config_overrides={
            'SQLALCHEMY_DATABASE_URI': url, 'ISOLATED_STAGING_DATABASE': True,
            'EXPANDED_HIERARCHY_ENABLED': False, 'PLATFORM_ROOT_USER_ID': args.owner_id,
            'SECRET_KEY': 'isolated-restored-acceptance-not-a-production-secret-2026',
            'JWT_SECRET_KEY': 'isolated-restored-acceptance-not-a-production-secret-2026',
            'RATELIMIT_ENABLED': False, 'PROPAGATE_EXCEPTIONS': False,
        })
        client = app.test_client()
        response = client.get('/api/v1/tenants/current')
        check('unmapped_brand_fails_closed', response.status_code == 503)
        with app.app_context(), without_hierarchy_scope(db.session):
            old_tokens = {change['user_id']: db.session.get(User, change['user_id']).generate_access_token() for change in plan['changes']}
        # Prove transaction rollback on the actual original rows first.
        with engine.connect() as con:
            transaction = con.begin()
            apply_plan_to_isolated_copy(con, plan)
            transaction.rollback()
            check('identity_trial_rollback_preserves_all_rows', _fingerprints(con, original_tables) == before)
        with engine.begin() as con:
            apply_plan_to_isolated_copy(con, plan)
        with engine.connect() as con:
            after = _fingerprints(con, original_tables)
            check('all_non_user_records_unchanged', all(after[name] == before[name] for name in original_tables if name != 'users'))
            check('every_table_row_count_preserved', all(after[name]['rows'] == before[name]['rows'] for name in original_tables))
            check('user_non_identity_fields_unchanged', _fingerprints(con, ['users'], user_identity=True) == identity_before)
            fresh = _json_rows(con, 'users')
            check('reconciliation_is_idempotent', not plan_single_brand_reconciliation(fresh, tenants, challenges, programs, owner_id=args.owner_id, brand_id=args.brand_id)['changes'])
        check('health_works_with_real_factory', client.get('/health').status_code == 200)
        response = client.get('/api/v1/tenants/current?tenant_id=999', headers={'X-Tenant-ID': '999', 'Host': 'unrelated.example.invalid'})
        check('public_brand_ignores_untrusted_selectors', response.status_code == 200 and response.get_json()['tenant']['id'] == args.brand_id)
        with app.app_context(), without_hierarchy_scope(db.session):
            tokens = {user.id: user.generate_access_token() for user in User.query.all()}
        statuses = {}
        for row in fresh:
            response = client.get('/api/v1/auth/me', headers={'Authorization': 'Bearer ' + tokens[row['id']]})
            belongs = row['id'] == args.owner_id or row.get('tenant_id') == args.brand_id
            expected = 200 if belongs and row.get('is_active') else 401
            check('principal_brand_policy_' + str(row['id']), response.status_code == expected)
            statuses[str(expected)] = statuses.get(str(expected), 0) + 1
        report['principal_status_counts'] = statuses
        for identity, token in old_tokens.items():
            check('old_session_revoked_' + str(identity), client.get('/api/v1/auth/me', headers={'Authorization': 'Bearer ' + token}).status_code == 401)
        ordinary = next(row['id'] for row in fresh if row.get('tenant_id') == args.brand_id and row.get('role') == 'trader')
        headers = {'Authorization': 'Bearer ' + tokens[ordinary]}
        check('ordinary_user_reads_own_profile', client.get('/api/v1/users/profile', headers=headers).status_code == 200)
        check('ordinary_user_cannot_list_admin_users', client.get('/api/v1/admin/users', headers=headers).status_code == 403)
        root_headers = {'Authorization': 'Bearer ' + tokens[args.owner_id]}
        check('designated_owner_reads_admin_users', client.get('/api/v1/admin/users', headers=root_headers).status_code == 200)
        for path in ('/api/v1/hierarchy/tree', '/api/v1/tenants/', '/api/v1/users/hierarchy'):
            check('future_product_disabled_' + path, client.get(path, headers=root_headers).status_code == 409)
        with engine.connect() as con:
            check('http_read_acceptance_has_no_record_side_effects', _fingerprints(con, original_tables) == after)
        report['success'] = True
    except Exception as exc:
        report['success'] = False
        report['error_type'] = type(exc).__name__
        # No row value, credential, SQL detail or untrusted error text leaves here.
        raise
    finally:
        if engine is not None:
            engine.dispose()
        isolated._stop_postgres(data, env)
        isolated._safe_rmtree(root)
        report['ephemeral_cluster_removed'] = not root.exists()
        Path(args.report).write_text(json.dumps(report, indent=2) + '\n')
        suite = ET.Element('testsuite', name='restored_mvp_acceptance', tests=str(len(checks)),
                           failures=str(sum(not item['passed'] for item in checks)), errors='0')
        for item in checks:
            case = ET.SubElement(suite, 'testcase', name=item['name'])
            if not item['passed']:
                ET.SubElement(case, 'failure', message='Acceptance invariant failed')
        if not report.get('success') and all(item['passed'] for item in checks):
            suite.set('errors', '1')
            case = ET.SubElement(suite, 'testcase', name='runner_exception')
            ET.SubElement(case, 'error', message=report.get('error_type', 'RunnerFailure'))
        ET.ElementTree(suite).write(str(Path(args.report).with_suffix('.xml')), encoding='utf-8', xml_declaration=True)
        print(json.dumps({'success': report.get('success'), 'checks': len(checks), 'cleanup': report['ephemeral_cluster_removed']}), flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', required=True)
    parser.add_argument('--backup-sha256', required=True)
    parser.add_argument('--owner-id', type=int, required=True)
    parser.add_argument('--brand-id', type=int, required=True)
    parser.add_argument('--report', required=True)
    parser.add_argument('--inner', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    _private_backup(args.backup, args.backup_sha256)
    isolated._require_clean_python()
    if args.inner:
        return _inner(args)
    if os.geteuid() == 0:
        raise RuntimeError('Invoke as an unprivileged caller')
    runtime_user = pwd.getpwuid(os.getuid()).pw_name
    command = ['sudo', '-n', 'unshare', '--net', '--fork', '--kill-child', '--mount-proc', '--',
               'runuser', '-u', runtime_user, '--', '/usr/bin/env', '-i',
               *[f'{key}={value}' for key, value in isolated.INNER_ENV.items()],
               f'STAGING_RUNTIME_USER={runtime_user}', f'STAGING_RUNTIME_UID={os.getuid()}',
               str(isolated.CLEAN_PYTHON), str(Path(__file__).resolve()), '--inner', *sys.argv[1:]]
    return subprocess.run(command, cwd=BACKEND, timeout=240).returncode


if __name__ == '__main__':
    raise SystemExit(main())
