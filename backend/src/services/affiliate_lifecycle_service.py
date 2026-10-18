"""Isolated synthetic affiliate lifecycle: no HTTP route, worker or live adapter.

All operations require a runner-owned PostgreSQL socket before SQL. The caller
owns the outer transaction; each mutation has a savepoint and deferred checks.
Unknown dispatch outcomes are never resent. No legacy balance is mutated.
"""
from datetime import timedelta, timezone
import os
from types import SimpleNamespace
from uuid import uuid4

from flask import current_app
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError

from src.database import db
from src.services.affiliate_lifecycle_contract import (
    AffiliatePolicy, LifecycleError, canonical, decode_policy, digest_text,
    exact_int, fail, identifier, utc_datetime, uuid,
)
from src.services.order_service import OrderError, OrderService
from src.utils.hierarchy_scoping import platform_root_scope


IDENTITY = 'affiliate_identity_evidence'
ATTRIBUTION = 'affiliate_order_attributions'
AWARD = 'affiliate_commission_awards'
COMMAND = 'affiliate_payout_commands'
_TABLES = frozenset((IDENTITY, ATTRIBUTION, AWARD, COMMAND))


def _row(statement, values=None):
    # Lock failure is contained too: a caller may safely commit other work after
    # a bounded refusal instead of receiving an aborted outer transaction.
    if any(fragment in statement.upper() for fragment in ('FOR UPDATE', 'FOR SHARE', 'PG_ADVISORY_XACT_LOCK')):
        try:
            with db.session.begin_nested():
                return db.session.execute(text(statement), values or {}).mappings().one_or_none()
        except DBAPIError as error:
            _database_conflict(error)
    return db.session.execute(text(statement), values or {}).mappings().one_or_none()


def _result(row, created=False):
    # Hash-only recipient projection. This is never an executable payment payload.
    result = dict(row)
    result.update(created=created, mode='synthetic', provider_verified=False,
                  payout_authorized=False)
    return result


def _get(table, identity, *, lock=False):
    if table not in _TABLES:
        raise AssertionError('Internal table is not in the bounded registry')
    uuid(identity)
    row = _row(f'SELECT * FROM public.{table} WHERE id=:id' + (' FOR UPDATE' if lock else ''), {'id': identity})
    if row is None:
        fail('Synthetic evidence was not found', 'AFFILIATE_NOT_FOUND', 404)
    return row


def _not_before(at, stored):
    timestamp = stored.replace(tzinfo=timezone.utc) if stored.tzinfo is None else stored
    if at < timestamp:
        fail('Evidence timestamps cannot move backwards', 'AFFILIATE_STATE_CONFLICT')


def _mutate(statement, values):
    """Run a complete service unit, including deferred invariant checks."""
    try:
        with db.session.begin_nested():
            row = _row(statement, values)
            _check_deferred()
        return row
    except DBAPIError as error:
        _database_conflict(error)


def _database_conflict(error):
    # Do not leak SQL, driver strings, identities or connection details.
    code = getattr(error.orig, 'pgcode', None)
    if code in ('23505', '23503', '23514', 'P0001', '55P03', '57014', '40P01', '40001'):
        fail('Synthetic evidence conflicts with the durable contract')
    raise error


def _check_deferred():
    from src.services.affiliate_lifecycle_storage import DEFERRED_CONSTRAINT_NAMES
    names = ', '.join('"' + name + '"' for name in DEFERRED_CONSTRAINT_NAMES)
    if names:
        db.session.execute(text('SET CONSTRAINTS ' + names + ' IMMEDIATE'))
        db.session.execute(text('SET CONSTRAINTS ' + names + ' DEFERRED'))


class AffiliateLifecycleRehearsal:
    @staticmethod
    def _isolated_target():
        if (current_app.testing is not True
                or current_app.config.get('AFFILIATE_LIFECYCLE_REHEARSAL_ENABLED') is not True
                or os.environ.get('FLASK_TESTING') != 'true'
                or os.environ.get('MARKETEDGEPROS_STAGING_INNER') != '1'):
            fail('Affiliate rehearsal is not configured', 'AFFILIATE_NOT_CONFIGURED', 503)
        try:
            from src.isolated_postgresql_target import validate_isolated_postgresql_target
            from src.testing_safety import validate_testing_resources
            configured = current_app.config['SQLALCHEMY_DATABASE_URI']
            validate_isolated_postgresql_target(configured)
            if current_app.config.get('ISOLATED_STAGING_DATABASE') is not True:
                raise ValueError('Explicit isolated factory required')
            validate_testing_resources(current_app.config)
            if current_app.config.get('SQLALCHEMY_BINDS'):
                raise ValueError('No alternate binds are supported')
            engine = db.session.get_bind()
            if engine.dialect.name != 'postgresql' or engine.url != make_url(configured):
                raise ValueError('Engine differs from validated target')
        except Exception:
            fail('Validated private PostgreSQL required', 'AFFILIATE_ISOLATION_REQUIRED', 503)
        if db.session.new or db.session.dirty or db.session.deleted:
            fail('Commit or rollback pending ORM work first', 'AFFILIATE_STATE_CONFLICT')

    @staticmethod
    def _prepare(at):
        AffiliateLifecycleRehearsal._isolated_target()
        utc_datetime(at)
        try:
            db.session.execute(text("SET LOCAL lock_timeout = '3s'"))
            db.session.execute(text("SET LOCAL statement_timeout = '5s'"))
            from src.services.affiliate_lifecycle_storage import require_storage_ready
            require_storage_ready()
        except Exception:
            fail('Canonical affiliate storage is required', 'AFFILIATE_STORAGE_NOT_READY', 503)

    @staticmethod
    def _user(user_id, tenant_id):
        exact_int(user_id, 1, 2147483647, 'user ID')
        exact_int(tenant_id, 1, 2147483647, 'tenant ID')
        row = _row('SELECT * FROM public.users WHERE id=:id FOR SHARE', {'id': user_id})
        if row is None or row['tenant_id'] != tenant_id or row['is_active'] is not True:
            fail('Evidence owner is not active in this tenant', 'AFFILIATE_SCOPE_MISMATCH')
        tenant = _row('SELECT status FROM public.tenants WHERE id=:id FOR SHARE', {'id': tenant_id})
        if tenant is None or tenant['status'] != 'active':
            fail('An active tenant is required', 'AFFILIATE_SCOPE_MISMATCH')
        return row

    @staticmethod
    def _order(order_id):
        uuid(order_id)
        _row('SELECT pg_advisory_xact_lock(hashtextextended(:id, 731212))', {'id': order_id})
        row = _row('SELECT * FROM public.purchase_orders WHERE id=:id FOR UPDATE', {'id': order_id})
        if row is None:
            fail('Order was not found', 'AFFILIATE_NOT_FOUND', 404)
        try:
            OrderService._integrity(SimpleNamespace(**row))
        except OrderError:
            fail('Order snapshot is inconsistent', 'AFFILIATE_STORAGE_NOT_READY', 503)
        AffiliateLifecycleRehearsal._user(row['user_id'], row['tenant_id'])
        program = _row('SELECT tenant_id FROM public.trading_programs WHERE id=:id FOR SHARE', {'id': row['program_id']})
        if program is None or program['tenant_id'] != row['tenant_id']:
            fail('Order program ownership changed', 'AFFILIATE_SCOPE_MISMATCH')
        return row

    @staticmethod
    def _binding(attribution, at):
        order = AffiliateLifecycleRehearsal._order(attribution['order_id'])
        buyer = _get(IDENTITY, attribution['buyer_evidence_id'])
        affiliate = _get(IDENTITY, attribution['affiliate_evidence_id'])
        AffiliateLifecycleRehearsal._user(attribution['affiliate_user_id'], order['tenant_id'])
        if (buyer['user_id'] != order['user_id'] or affiliate['user_id'] != attribution['affiliate_user_id']
                or buyer['tenant_id'] != order['tenant_id'] or affiliate['tenant_id'] != order['tenant_id']):
            fail('Order and identity tenant binding differs', 'AFFILIATE_SCOPE_MISMATCH')
        if buyer['user_id'] == affiliate['user_id'] or buyer['subject_hash'] == affiliate['subject_hash']:
            fail('Self-referral is not eligible', 'AFFILIATE_SELF_REFERRAL')
        if buyer['source'] != 'synthetic' or affiliate['source'] != 'synthetic':
            fail('Only synthetic identity evidence is supported', 'AFFILIATE_STORAGE_NOT_READY', 503)
        for stamp in (attribution['created_at'], buyer['created_at'], affiliate['created_at'], order['created_at']):
            _not_before(at, stamp)
        policy = decode_policy(attribution['policy_json'], attribution['policy_hash'])
        return order, policy

    @staticmethod
    def record_identity(user_id, tenant_id, subject_hash, event_key, *, at):
        AffiliateLifecycleRehearsal._prepare(at)
        exact_int(user_id, 1, 2147483647, 'user ID')
        exact_int(tenant_id, 1, 2147483647, 'tenant ID')
        digest_text(subject_hash)
        identifier(event_key)
        # Serialize a user's single immutable identity; global event uniqueness is
        # still a DB authority across two different users.
        _row('SELECT id FROM public.users WHERE id=:id FOR UPDATE', {'id': user_id})
        AffiliateLifecycleRehearsal._user(user_id, tenant_id)
        values = dict(user_id=user_id, tenant_id=tenant_id, subject_hash=subject_hash, event_key=event_key,
                      id=str(uuid4()), at=at)
        def existing():
            return db.session.execute(text('''SELECT * FROM public.affiliate_identity_evidence
                WHERE (tenant_id=:tenant_id AND user_id=:user_id) OR (source='synthetic' AND event_key=:event_key)
                LIMIT 2'''), values).mappings().all()
        def replay(rows):
            if len(rows) != 1 or any(rows[0][key] != values[key] for key in ('user_id', 'tenant_id', 'subject_hash', 'event_key')):
                fail('Identity event already binds different evidence')
            _not_before(at, rows[0]['created_at'])
            return _result(rows[0])
        rows = existing()
        if rows:
            return replay(rows)
        try:
            with db.session.begin_nested():
                row = _row('''INSERT INTO public.affiliate_identity_evidence
                    (id,user_id,tenant_id,subject_hash,source,event_key,created_at)
                    VALUES (:id,:user_id,:tenant_id,:subject_hash,'synthetic',:event_key,:at) RETURNING *''', values)
                _check_deferred()
            return _result(row, True)
        except IntegrityError:
            return replay(existing())

    @staticmethod
    def attribute_order(order_id, affiliate_user_id, buyer_evidence_id, affiliate_evidence_id, policy, *, at):
        AffiliateLifecycleRehearsal._prepare(at)
        uuid(order_id)
        uuid(buyer_evidence_id)
        uuid(affiliate_evidence_id)
        exact_int(affiliate_user_id, 1, 2147483647, 'affiliate ID')
        if type(policy) is not AffiliatePolicy:
            fail('An explicit typed synthetic policy is required', 'AFFILIATE_INVALID', 400)
        policy.__post_init__()
        order = AffiliateLifecycleRehearsal._order(order_id)
        values = dict(id=str(uuid4()), order_id=order_id, affiliate_user_id=affiliate_user_id,
                      buyer_evidence_id=buyer_evidence_id, affiliate_evidence_id=affiliate_evidence_id,
                      policy_hash=policy.digest, policy_json=canonical(policy.canonical_dict()), at=at)
        binding = dict(values, created_at=at, policy_json=policy.canonical_dict())
        AffiliateLifecycleRehearsal._binding(binding, at)
        row = _row('SELECT * FROM public.affiliate_order_attributions WHERE order_id=:id', {'id': order_id})
        if row:
            if any(row[key] != values[key] for key in ('affiliate_user_id', 'buyer_evidence_id', 'affiliate_evidence_id', 'policy_hash')):
                fail('The order already binds a different attribution')
            _not_before(at, row['created_at'])
            return _result(row)
        received = _row('''SELECT id FROM public.payment_event_receipts WHERE order_id=:id LIMIT 1''', {'id': order_id})
        settled = _row('SELECT id FROM public.settlement_journals WHERE order_id=:id', {'id': order_id})
        if received or settled:
            fail('Attribution cannot be backfilled after a receipt', 'AFFILIATE_STATE_CONFLICT')
        _not_before(at, order['created_at'])
        row = _mutate('''INSERT INTO public.affiliate_order_attributions
            (id,order_id,affiliate_user_id,buyer_evidence_id,affiliate_evidence_id,policy_hash,policy_json,created_at)
            VALUES (:id,:order_id,:affiliate_user_id,:buyer_evidence_id,:affiliate_evidence_id,:policy_hash,
                    CAST(:policy_json AS jsonb),:at) RETURNING *''', values)
        return _result(row, True)

    @staticmethod
    def _journal(journal_id, order):
        uuid(journal_id)
        journal = _row('SELECT * FROM public.settlement_journals WHERE id=:id', {'id': journal_id})
        if journal is None:
            fail('Journal was not found', 'AFFILIATE_NOT_FOUND', 404)
        receipt = _row('SELECT * FROM public.payment_event_receipts WHERE id=:id', {'id': journal['receipt_id']})
        if (journal['order_id'] != order['id'] or receipt is None or receipt['order_id'] != order['id']
                or receipt['source'] != 'synthetic' or receipt['merchant_context'] != 'isolated-tests'
                or any(row['amount_minor'] != order['amount_minor'] or row['currency'] != 'USD' for row in (journal, receipt))):
            fail('Synthetic journal does not match the order', 'AFFILIATE_SCOPE_MISMATCH')
        entries = db.session.execute(text('''SELECT line_number,account_code,side,amount_minor
            FROM public.settlement_entries WHERE journal_id=:id ORDER BY line_number LIMIT 3'''), {'id': journal_id}).all()
        if entries != [(1, 'provider_clearing', 'debit', order['amount_minor']),
                       (2, 'unapplied_order_receipts', 'credit', order['amount_minor'])]:
            fail('Receipt journal balance is inconsistent', 'AFFILIATE_STORAGE_NOT_READY', 503)
        return journal, receipt

    @staticmethod
    def accrue(attribution_id, journal_id, *, at):
        AffiliateLifecycleRehearsal._prepare(at)
        attribution = _get(ATTRIBUTION, attribution_id)
        order, policy = AffiliateLifecycleRehearsal._binding(attribution, at)
        journal, receipt = AffiliateLifecycleRehearsal._journal(journal_id, order)
        _not_before(at, receipt['created_at'])
        _not_before(at, journal['created_at'])
        _not_before(receipt['created_at'].replace(tzinfo=timezone.utc), attribution['created_at'])
        amount = policy.commission_minor(journal['amount_minor'])
        release = receipt['created_at'].replace(tzinfo=timezone.utc) + timedelta(seconds=policy.hold_seconds)
        rows = db.session.execute(text('''SELECT * FROM public.affiliate_commission_awards
            WHERE attribution_id=:a OR journal_id=:j LIMIT 2'''), {'a': attribution_id, 'j': journal_id}).mappings().all()
        if rows:
            if len(rows) != 1 or rows[0]['attribution_id'] != attribution_id or rows[0]['journal_id'] != journal_id or rows[0]['amount_minor'] != amount or rows[0]['release_at'] != release:
                fail('Award already binds different evidence')
            _not_before(at, rows[0]['updated_at'])
            return _result(rows[0])
        row = _mutate('''INSERT INTO public.affiliate_commission_awards
            (id,attribution_id,journal_id,amount_minor,state,review_open,reversal_event_key,release_at,created_at,updated_at)
            VALUES (:id,:a,:j,:amount,'held',false,NULL,:release,:at,:at) RETURNING *''',
            dict(id=str(uuid4()), a=attribution_id, j=journal_id, amount=amount, release=release, at=at))
        return _result(row, True)

    @staticmethod
    def _award(award_id, at):
        award = _get(AWARD, award_id, lock=True)
        _not_before(at, award['updated_at'])
        attribution = _get(ATTRIBUTION, award['attribution_id'])
        order, policy = AffiliateLifecycleRehearsal._binding(attribution, at)
        journal, receipt = AffiliateLifecycleRehearsal._journal(award['journal_id'], order)
        release = receipt['created_at'].replace(tzinfo=timezone.utc) + timedelta(seconds=policy.hold_seconds)
        if award['amount_minor'] != policy.commission_minor(journal['amount_minor']) or award['release_at'] != release:
            fail('Award money differs from frozen policy', 'AFFILIATE_STORAGE_NOT_READY', 503)
        return award, attribution, policy

    @staticmethod
    def review(award_id, opened, *, at):
        AffiliateLifecycleRehearsal._prepare(at)
        if type(opened) is not bool:
            fail('An explicit review boolean is required', 'AFFILIATE_INVALID', 400)
        award, _, _ = AffiliateLifecycleRehearsal._award(award_id, at)
        if award['state'] not in ('held', 'available'):
            fail('Reserved or terminal awards cannot change review', 'AFFILIATE_STATE_CONFLICT')
        if award['review_open'] is opened:
            return _result(award)
        return _result(_mutate('''UPDATE public.affiliate_commission_awards
            SET review_open=:opened,updated_at=:at WHERE id=:id RETURNING *''', dict(id=award_id, opened=opened, at=at)))

    @staticmethod
    def release(award_id, *, at):
        AffiliateLifecycleRehearsal._prepare(at)
        award, _, _ = AffiliateLifecycleRehearsal._award(award_id, at)
        if award['state'] not in ('held', 'available') or award['review_open'] or at < award['release_at']:
            fail('Award is not mature and review-free', 'AFFILIATE_STATE_CONFLICT')
        if award['state'] == 'available':
            return _result(award)
        return _result(_mutate('''UPDATE public.affiliate_commission_awards
            SET state='available',updated_at=:at WHERE id=:id RETURNING *''', dict(id=award_id, at=at)))

    @staticmethod
    def reverse(award_id, reason_event_key, *, at):
        AffiliateLifecycleRehearsal._prepare(at)
        identifier(reason_event_key)
        award, _, _ = AffiliateLifecycleRehearsal._award(award_id, at)
        if award['state'] == 'reversed':
            if award['reversal_event_key'] != reason_event_key:
                fail('Reversal already binds another event')
            return _result(award)
        if award['state'] not in ('held', 'available'):
            fail('Reserved or paid awards require separate reconciliation', 'AFFILIATE_STATE_CONFLICT')
        return _result(_mutate('''UPDATE public.affiliate_commission_awards
            SET state='reversed',reversal_event_key=:event,updated_at=:at WHERE id=:id RETURNING *''',
            dict(id=award_id, event=reason_event_key, at=at)))

    @staticmethod
    def _root(approved_by, tenant_id):
        exact_int(approved_by, 1, 2147483647, 'approver ID')
        root = _row('SELECT * FROM public.users WHERE id=:id FOR SHARE', {'id': approved_by})
        if root is None or not platform_root_scope(SimpleNamespace(**root)) or root['tenant_id'] != tenant_id:
            fail('Only the configured platform owner may plan payout', 'AFFILIATE_ROOT_REQUIRED', 403)

    @staticmethod
    def prepare_payout(award_id, approved_by, network_id, asset_id, recipient_hash, amount_atomic, quote_hash, *, at):
        AffiliateLifecycleRehearsal._prepare(at)
        identifier(network_id, 64)
        identifier(asset_id, 64)
        digest_text(recipient_hash)
        digest_text(quote_hash)
        exact_int(amount_atomic, 1, 10 ** 78 - 1, 'quoted atomic units')
        award, attribution, policy = AffiliateLifecycleRehearsal._award(award_id, at)
        order = AffiliateLifecycleRehearsal._order(attribution['order_id'])
        AffiliateLifecycleRehearsal._root(approved_by, order['tenant_id'])
        values = dict(id=str(uuid4()), award_id=award_id, approved_by=approved_by, network_id=network_id,
                      asset_id=asset_id, recipient_hash=recipient_hash, amount_atomic=amount_atomic, quote_hash=quote_hash, at=at)
        existing = _row('SELECT * FROM public.affiliate_payout_commands WHERE award_id=:id', {'id': award_id})
        if existing:
            if any(existing[key] != values[key] for key in ('approved_by', 'network_id', 'asset_id', 'recipient_hash', 'amount_atomic', 'quote_hash')):
                fail('Award already binds a different payout proposal')
            _not_before(at, existing['updated_at'])
            return _result(existing)
        if award['state'] != 'available' or award['review_open'] or award['amount_minor'] < policy.minimum_payout_minor:
            fail('Award is not eligible for a payout proposal', 'AFFILIATE_STATE_CONFLICT')
        try:
            with db.session.begin_nested():
                row = _row('''INSERT INTO public.affiliate_payout_commands
                    (id,award_id,approved_by,network_id,asset_id,recipient_hash,amount_atomic,quote_hash,
                     attempt_token,transfer_key,state,created_at,updated_at)
                    VALUES (:id,:award_id,:approved_by,:network_id,:asset_id,:recipient_hash,:amount_atomic,:quote_hash,
                            NULL,NULL,'planned',:at,:at) RETURNING *''', values)
                _row('''UPDATE public.affiliate_commission_awards SET state='reserved',updated_at=:at
                    WHERE id=:id RETURNING *''', dict(id=award_id, at=at))
                _check_deferred()
            return _result(row, True)
        except DBAPIError as error:
            _database_conflict(error)

    @staticmethod
    def _command(command_id, at):
        # All service paths lock award then command, preventing opposite-order
        # deadlocks against prepare/reverse/confirm on the same award.
        preview = _get(COMMAND, command_id)
        award, attribution, _ = AffiliateLifecycleRehearsal._award(preview['award_id'], at)
        row = _get(COMMAND, command_id, lock=True)
        _not_before(at, row['updated_at'])
        order = AffiliateLifecycleRehearsal._order(attribution['order_id'])
        AffiliateLifecycleRehearsal._root(row['approved_by'], order['tenant_id'])
        expected = 'paid' if row['state'] == 'confirmed' else 'reserved'
        if award['state'] != expected:
            fail('Payout reservation is inconsistent', 'AFFILIATE_STORAGE_NOT_READY', 503)
        return row

    @staticmethod
    def claim_payout(command_id, *, at):
        AffiliateLifecycleRehearsal._prepare(at)
        row = AffiliateLifecycleRehearsal._command(command_id, at)
        if row['state'] != 'planned':
            fail('A dispatched payout must be reconciled, never resent', 'AFFILIATE_STATE_CONFLICT')
        return _result(_mutate('''UPDATE public.affiliate_payout_commands
            SET state='dispatched',attempt_token=:token,updated_at=:at WHERE id=:id RETURNING *''',
            dict(id=command_id, token=str(uuid4()), at=at)))

    @staticmethod
    def mark_uncertain(command_id, attempt_token, *, at):
        AffiliateLifecycleRehearsal._prepare(at)
        uuid(attempt_token)
        row = AffiliateLifecycleRehearsal._command(command_id, at)
        if row['state'] not in ('dispatched', 'uncertain') or row['attempt_token'] != attempt_token:
            fail('Only the original dispatch can become uncertain', 'AFFILIATE_STATE_CONFLICT')
        if row['state'] == 'uncertain':
            return _result(row)
        return _result(_mutate('''UPDATE public.affiliate_payout_commands
            SET state='uncertain',updated_at=:at WHERE id=:id RETURNING *''', dict(id=command_id, at=at)))

    @staticmethod
    def confirm_payout(command_id, attempt_token, transfer_key, *, at):
        AffiliateLifecycleRehearsal._prepare(at)
        uuid(attempt_token)
        identifier(transfer_key)
        row = AffiliateLifecycleRehearsal._command(command_id, at)
        if row['state'] not in ('dispatched', 'uncertain', 'confirmed') or row['attempt_token'] != attempt_token:
            fail('Confirmation must bind the original dispatch', 'AFFILIATE_STATE_CONFLICT')
        if row['state'] == 'confirmed':
            if row['transfer_key'] != transfer_key:
                fail('Command already confirms another transfer')
            return _result(row)
        try:
            with db.session.begin_nested():
                updated = _row('''UPDATE public.affiliate_payout_commands
                    SET state='confirmed',transfer_key=:transfer,updated_at=:at WHERE id=:id RETURNING *''',
                    dict(id=command_id, transfer=transfer_key, at=at))
                _row('''UPDATE public.affiliate_commission_awards SET state='paid',updated_at=:at
                    WHERE id=:id RETURNING *''', dict(id=row['award_id'], at=at))
                _check_deferred()
            return _result(updated)
        except DBAPIError as error:
            _database_conflict(error)
