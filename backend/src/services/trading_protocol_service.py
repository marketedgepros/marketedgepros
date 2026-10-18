"""Durable isolated rehearsal only: no provider adapter, entitlement or worker.

The caller owns commit/rollback. A dispatched command is NEVER retried: ambiguous
outcomes become uncertain and require acknowledgement of the original attempt.
"""
from dataclasses import fields
from datetime import timezone
import hashlib
import json
import os
from uuid import uuid4

from flask import current_app
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from src.database import db
from src.services.trading_risk_contract import TradingRules, RiskLimit, exact_int, exact_text, utc_datetime
from src.services.trading_risk_rehearsal import RiskObservation


class ProtocolError(ValueError):
    def __init__(self, message, code='PROTOCOL_INVALID', status=400):
        super().__init__(message)
        self.code, self.status = code, status


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _hash(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def _identifier(value, name, length=64):
    return exact_text(value, r'[A-Za-z0-9_.:-]+', length, name)


def _uuid(value):
    return exact_text(value, r'[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}', 36, 'command ID/token')


def _failure(message, code='PROTOCOL_CONFLICT', status=409):
    raise ProtocolError(message, code, status)


def _result(row, created=False):
    names = ('id', 'tenant_id', 'challenge_id', 'phase', 'provider_id', 'rule_snapshot_id',
             'status', 'attempt_token', 'account_id', 'rules_digest', 'sequence', 'event_id')
    result = {name: row[name] for name in names if name in row}
    result.update(created=created, source='synthetic', provider_verified=False,
                  authorized=False, phase_transition_authorized=False, account_disable_authorized=False)
    # "created" describes rows in the caller's transaction, not a committed provider action.
    return result


class TradingProtocolRehearsal:
    @staticmethod
    def _isolated_target():
        if (current_app.testing is not True
                or current_app.config.get('TRADING_PROTOCOL_REHEARSAL_ENABLED') is not True
                or os.environ.get('FLASK_TESTING') != 'true'
                or os.environ.get('MARKETEDGEPROS_STAGING_INNER') != '1'):
            _failure('Trading protocol rehearsal is not configured', 'PROTOCOL_NOT_CONFIGURED', 503)
        try:
            from migrations.target_safety import validate_isolated_postgresql_target
            from src.testing_safety import validate_testing_resources
            configured = current_app.config['SQLALCHEMY_DATABASE_URI']
            validate_isolated_postgresql_target(configured)
            if current_app.config.get('ISOLATED_STAGING_DATABASE') is not True:
                raise ValueError('Explicit factory isolation required')
            validate_testing_resources(current_app.config)
            engine = db.session.get_bind()
            if engine.dialect.name != 'postgresql' or engine.url != make_url(configured):
                raise ValueError('Engine differs from validated private target')
        except Exception:
            _failure('Validated isolated PostgreSQL required', 'PROTOCOL_ISOLATION_REQUIRED', 503)
        if db.session.new or db.session.dirty or db.session.deleted:
            _failure('Commit or rollback pending ORM changes before protocol work', 'PROTOCOL_DIRTY_SESSION', 409)

    @staticmethod
    def _storage_ready():
        db.session.execute(text("SET LOCAL lock_timeout = '3s'"))
        db.session.execute(text("SET LOCAL statement_timeout = '5s'"))
        if db.session.execute(text('SHOW session_replication_role')).scalar_one() != 'origin':
            _failure('Origin trigger execution required', 'PROTOCOL_STORAGE_NOT_READY', 503)
        try:
            heads = db.session.execute(text('SELECT version_num FROM public.alembic_version')).scalars().all()
            if heads != ['20261011_000008']:
                raise ValueError('Trading protocol migration required')
            from src.services.trading_protocol_storage_contract import validate_storage
            validate_storage(db.session.connection())
        except Exception:
            _failure('Canonical trading protocol storage required', 'PROTOCOL_STORAGE_NOT_READY', 503)

    @staticmethod
    def _prepare(at):
        TradingProtocolRehearsal._isolated_target()
        utc_datetime(at)
        TradingProtocolRehearsal._storage_ready()

    @staticmethod
    def _snapshot(identity):
        exact_text(identity, r'[a-f0-9]{64}', 64, 'snapshot ID')
        row = db.session.execute(text('SELECT * FROM public.trading_rule_snapshots WHERE id=:id'),
                                 {'id': identity}).mappings().one_or_none()
        if row is None:
            _failure('Rule snapshot not found', 'PROTOCOL_NOT_FOUND', 404)
        try:
            content = row['canonical_rules']
            if type(content) is not dict or set(content) != {field.name for field in fields(TradingRules)}:
                raise ValueError('Exact canonical rules schema required')
            decoded = dict(content)
            for name in ('profit_target', 'daily_loss', 'total_loss'):
                item = content[name]
                if type(item) is not dict or set(item) != {'unit', 'value'}:
                    raise ValueError('Exact risk limit schema required')
                decoded[name] = RiskLimit(**item)
            TradingRules(**decoded).__post_init__()
        except (ValueError, TypeError, KeyError):
            _failure('Stored rule shape is invalid', 'PROTOCOL_STORAGE_NOT_READY', 503)
        if (row['source'] != 'synthetic' or type(row['canonical_rules']) is not dict
                or _hash(row['canonical_rules']) != row['rules_digest']
                or _hash({'tenant_id': row['tenant_id'], 'rules': row['canonical_rules']}) != row['id']
                or row['canonical_rules'].get('program_id') != row['program_id']
                or row['canonical_rules'].get('phase') != row['phase']
                or row['canonical_rules'].get('rules_version') != row['rules_version']):
            _failure('Rule snapshot content is inconsistent', 'PROTOCOL_STORAGE_NOT_READY', 503)
        return row

    @staticmethod
    def store_rules(tenant_id, rules, *, at):
        TradingProtocolRehearsal._prepare(at)
        exact_int(tenant_id, 1, 2 ** 31 - 1, 'tenant')
        if type(rules) is not TradingRules:
            _failure('Typed draft TradingRules required', 'PROTOCOL_INVALID', 400)
        rules.__post_init__()
        content = rules.canonical_dict()
        identity = _hash({'tenant_id': tenant_id, 'rules': content})
        program = db.session.execute(text('SELECT tenant_id FROM public.trading_programs WHERE id=:id FOR SHARE'),
                                     {'id': rules.program_id}).mappings().one_or_none()
        if program is None or program['tenant_id'] != tenant_id:
            _failure('Program does not belong to this tenant', 'PROTOCOL_SCOPE_MISMATCH')
        values = {'id': identity, 'tenant_id': tenant_id, 'program_id': rules.program_id,
                  'phase': rules.phase, 'rules_version': rules.rules_version, 'rules_digest': rules.digest,
                  'canonical_rules': _canonical(content), 'at': at}
        def existing():
            return db.session.execute(text('''SELECT * FROM public.trading_rule_snapshots
                WHERE tenant_id=:tenant_id AND program_id=:program_id AND phase=:phase
                  AND rules_version=:rules_version'''), values).mappings().one_or_none()
        row = existing()
        if row is not None:
            TradingProtocolRehearsal._snapshot(row['id'])
            if row['id'] != identity:
                _failure('This rule version already identifies different content')
            return _result(row)
        try:
            with db.session.begin_nested():
                db.session.execute(text('''INSERT INTO public.trading_rule_snapshots
                    (id, tenant_id, program_id, phase, rules_version, rules_digest, canonical_rules, source, created_at)
                    VALUES (:id, :tenant_id, :program_id, :phase, :rules_version, :rules_digest,
                            CAST(:canonical_rules AS jsonb), 'synthetic', :at)'''), values)
            return _result(TradingProtocolRehearsal._snapshot(identity), True)
        except IntegrityError:
            row = existing()
            if row is None or row['id'] != identity:
                _failure('Rule identity/version conflict')
            return _result(TradingProtocolRehearsal._snapshot(row['id']))

    @staticmethod
    def plan_command(tenant_id, challenge_id, provider_id, snapshot_id, *, at):
        TradingProtocolRehearsal._prepare(at)
        exact_int(tenant_id, 1, 2 ** 31 - 1, 'tenant')
        exact_int(challenge_id, 1, 2 ** 31 - 1, 'challenge')
        _identifier(provider_id, 'provider')
        snapshot = TradingProtocolRehearsal._snapshot(snapshot_id)
        if at < snapshot['created_at']:
            _failure('Command cannot predate its rule snapshot', 'PROTOCOL_STATE_CONFLICT')
        challenge = db.session.execute(text('''SELECT u.tenant_id AS tenant_id, c.program_id, u.tenant_id AS owner_tenant,
                   p.tenant_id AS program_tenant
            FROM public.challenges c JOIN public.users u ON u.id=c.user_id
            JOIN public.trading_programs p ON p.id=c.program_id
            WHERE c.id=:id FOR UPDATE OF c FOR SHARE OF u,p'''), {'id': challenge_id}).mappings().one_or_none()
        if (challenge is None or snapshot['tenant_id'] != tenant_id
                or challenge['tenant_id'] != tenant_id or challenge['owner_tenant'] != tenant_id
                or challenge['program_tenant'] != tenant_id or challenge['program_id'] != snapshot['program_id']):
            _failure('Challenge, owner, program and rules must share a tenant', 'PROTOCOL_SCOPE_MISMATCH')
        values = dict(tenant_id=tenant_id, challenge_id=challenge_id, phase=snapshot['phase'],
                      provider_id=provider_id, rule_snapshot_id=snapshot_id, at=at, id=str(uuid4()))
        row = db.session.execute(text('''SELECT * FROM public.trading_provision_commands
            WHERE tenant_id=:tenant_id AND challenge_id=:challenge_id AND phase=:phase'''),
            values).mappings().one_or_none()
        if row is not None:
            if row['rule_snapshot_id'] != snapshot_id or row['provider_id'] != provider_id:
                _failure('Command already binds a different rule version')
            return _result(row)
        with db.session.begin_nested():
            row = db.session.execute(text('''INSERT INTO public.trading_provision_commands
                (id, tenant_id, challenge_id, phase, provider_id, rule_snapshot_id, source, status,
                 attempt_token, account_id, created_at, updated_at)
                VALUES (:id, :tenant_id, :challenge_id, :phase, :provider_id, :rule_snapshot_id,
                        'synthetic', 'planned', NULL, NULL, :at, :at) RETURNING *'''), values).mappings().one()
        return _result(row, True)

    @staticmethod
    def _command(identity, at):
        _uuid(identity)
        row = db.session.execute(text('SELECT * FROM public.trading_provision_commands WHERE id=:id FOR UPDATE'),
                                 {'id': identity}).mappings().one_or_none()
        if row is None:
            _failure('Command not found', 'PROTOCOL_NOT_FOUND', 404)
        if row['source'] != 'synthetic':
            _failure('Only synthetic rehearsal commands are supported', 'PROTOCOL_STORAGE_NOT_READY', 503)
        if at < row['updated_at']:
            _failure('Command time must not move backwards', 'PROTOCOL_STATE_CONFLICT')
        snapshot = TradingProtocolRehearsal._snapshot(row['rule_snapshot_id'])
        scope = db.session.execute(text('''SELECT u.tenant_id AS tenant_id, c.program_id, u.tenant_id AS owner_tenant,
            p.tenant_id AS program_tenant FROM public.challenges c JOIN public.users u ON u.id=c.user_id
            JOIN public.trading_programs p ON p.id=c.program_id WHERE c.id=:id FOR SHARE OF c,u,p'''),
            {'id': row['challenge_id']}).mappings().one_or_none()
        if (scope is None or any(scope[key] != row['tenant_id'] for key in ('tenant_id', 'owner_tenant', 'program_tenant'))
                or snapshot['tenant_id'] != row['tenant_id'] or snapshot['program_id'] != scope['program_id']
                or snapshot['phase'] != row['phase']):
            _failure('Command scope changed after planning', 'PROTOCOL_SCOPE_MISMATCH')
        return row

    @staticmethod
    def claim_command(command_id, *, at):
        TradingProtocolRehearsal._prepare(at)
        row = TradingProtocolRehearsal._command(command_id, at)
        if row['status'] != 'planned':
            _failure('Command was dispatched; reconcile its original attempt, never retry', 'PROTOCOL_STATE_CONFLICT')
        with db.session.begin_nested():
            updated = db.session.execute(text('''UPDATE public.trading_provision_commands
                SET status='dispatched', attempt_token=:token, updated_at=:at WHERE id=:id RETURNING *'''),
                dict(id=command_id, token=str(uuid4()), at=at)).mappings().one()
        return _result(updated)

    @staticmethod
    def mark_uncertain(command_id, attempt_token, *, at):
        TradingProtocolRehearsal._prepare(at)
        _uuid(attempt_token)
        row = TradingProtocolRehearsal._command(command_id, at)
        if row['attempt_token'] != attempt_token or row['status'] not in ('dispatched', 'uncertain'):
            _failure('Only the dispatched attempt can become uncertain', 'PROTOCOL_STATE_CONFLICT')
        if row['status'] == 'uncertain':
            return _result(row)
        with db.session.begin_nested():
            updated = db.session.execute(text('''UPDATE public.trading_provision_commands
                SET status='uncertain', updated_at=:at WHERE id=:id RETURNING *'''),
                dict(id=command_id, at=at)).mappings().one()
        return _result(updated)

    @staticmethod
    def acknowledge(command_id, attempt_token, account_id, *, at):
        TradingProtocolRehearsal._prepare(at)
        _uuid(attempt_token)
        _identifier(account_id, 'account')
        row = TradingProtocolRehearsal._command(command_id, at)
        if row['attempt_token'] != attempt_token or row['status'] not in ('dispatched', 'uncertain', 'acknowledged'):
            _failure('Acknowledgement must match the original attempt', 'PROTOCOL_STATE_CONFLICT')
        if row['status'] == 'acknowledged':
            if row['account_id'] != account_id:
                _failure('Command already acknowledges a different account')
            return _result(row)
        try:
            with db.session.begin_nested():
                updated = db.session.execute(text('''UPDATE public.trading_provision_commands
                    SET status='acknowledged', account_id=:account, updated_at=:at WHERE id=:id RETURNING *'''),
                    dict(id=command_id, account=account_id, at=at)).mappings().one()
            return _result(updated)
        except IntegrityError:
            _failure('Account already belongs to another command')

    @staticmethod
    def record_observation(command_id, observation, *, at):
        TradingProtocolRehearsal._prepare(at)
        if type(observation) is not RiskObservation:
            _failure('Typed synthetic observation required', 'PROTOCOL_INVALID', 400)
        observation.__post_init__()
        command = TradingProtocolRehearsal._command(command_id, at)
        snapshot = TradingProtocolRehearsal._snapshot(command['rule_snapshot_id'])
        rules = snapshot['canonical_rules']
        if (command['status'] != 'acknowledged' or command['tenant_id'] != observation.tenant_id
                or command['challenge_id'] != observation.challenge_id or command['provider_id'] != observation.provider_id
                or command['account_id'] != observation.account_id or snapshot['rules_digest'] != observation.rules_digest
                or rules['currency'] != observation.currency or rules['currency_scale'] != observation.currency_scale):
            _failure('Observation does not match the acknowledged command and frozen rules', 'PROTOCOL_SCOPE_MISMATCH')
        if observation.observed_at > at:
            _failure('Cannot receive an observation from the future')
        content = {field.name: getattr(observation, field.name) for field in fields(RiskObservation)}
        content['observed_at'] = observation.observed_at.astimezone(timezone.utc).isoformat(timespec='microseconds')
        payload = {'schema_version': 1, 'source': 'synthetic', 'local_only': True, 'observation': content}
        values = dict(id=str(uuid4()), command_id=command_id, provider_id=observation.provider_id,
                      account_id=observation.account_id, event_id=observation.event_id, sequence=observation.sequence,
                      payload_hash=_hash(payload), payload=_canonical(payload), at=at)
        def existing():
            return db.session.execute(text('''SELECT * FROM public.trading_event_inbox
                WHERE provider_id=:provider_id AND account_id=:account_id
                  AND (event_id=:event_id OR sequence=:sequence) LIMIT 2'''), values).mappings().all()
        def replay(rows):
            if len(rows) != 1:
                _failure('Event identity or sequence conflicts with another stored observation')
            row = rows[0]
            expected = ('command_id', 'provider_id', 'account_id', 'event_id', 'sequence', 'payload_hash')
            if any(row[key] != values[key] for key in expected) or row['payload'] != payload or _hash(row['payload']) != row['payload_hash']:
                _failure('Event identity or sequence already binds different content')
            return _result(row)
        rows = existing()
        if rows:
            return replay(rows)
        try:
            with db.session.begin_nested():
                row = db.session.execute(text('''INSERT INTO public.trading_event_inbox
                    (id, command_id, provider_id, account_id, event_id, sequence, payload_hash, payload, received_at)
                    VALUES (:id, :command_id, :provider_id, :account_id, :event_id, :sequence,
                            :payload_hash, CAST(:payload AS jsonb), :at) RETURNING *'''), values).mappings().one()
            return _result(row, True)
        except IntegrityError:
            return replay(existing())
