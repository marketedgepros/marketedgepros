"""Isolated synthetic receipt/journal rehearsal, never an activated provider adapter.

There is deliberately no public endpoint, environment-secret fallback or wallet
mutation. Production is refused before any SQL even if an enablement flag is set.
"""
from dataclasses import dataclass
import hashlib
import os
import re
from uuid import uuid4

from flask import current_app
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from src.database import db
from src.models.purchase_order import PurchaseOrder
from src.models.settlement_ledger import PaymentEventReceipt, SettlementJournal, SettlementEntry
from src.services.order_service import OrderService, OrderError
from src.utils.hierarchy_scoping import without_hierarchy_scope


class LedgerError(ValueError):
    def __init__(self, message, code='LEDGER_INVALID', status=400):
        super().__init__(message)
        self.code, self.status = code, status


@dataclass(frozen=True)
class LedgerResult:
    receipt_id: str
    journal_id: str
    order_id: str
    amount_minor: int
    currency: str
    created: bool


_REQUIRED = frozenset({'source', 'merchant_context', 'event_key', 'order_id', 'amount_minor', 'currency', 'payload_hash'})
_IDENTIFIER = re.compile(r'[A-Za-z0-9_-]{1,128}\Z')
_HEX_HASH = re.compile(r'[0-9a-f]{64}\Z')
_UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z')


class SettlementLedgerService:
    @staticmethod
    def _isolated_target():
        """Validate OS namespace, owned socket and exact DB URL before SQL/I/O."""
        if (current_app.testing is not True or current_app.config.get('SYNTHETIC_SETTLEMENT_ENABLED') is not True
                or os.environ.get('FLASK_TESTING') != 'true'
                or os.environ.get('MARKETEDGEPROS_STAGING_INNER') != '1'):
            raise LedgerError('Synthetic ledger is unavailable outside an isolated rehearsal', 'LEDGER_NOT_CONFIGURED', 503)
        try:
            from migrations.target_safety import validate_isolated_postgresql_target
            from sqlalchemy.engine import make_url
            from src.testing_safety import validate_testing_resources
            configured = current_app.config['SQLALCHEMY_DATABASE_URI']
            validate_isolated_postgresql_target(configured)
            if current_app.config.get('ISOLATED_STAGING_DATABASE') is not True:
                raise ValueError('Explicit isolated factory configuration required')
            validate_testing_resources(current_app.config)
            if current_app.config.get('SQLALCHEMY_BINDS'):
                raise ValueError('Binds not supported')
            # The target was validated before an engine could open a connection.
            bind = db.session.get_bind()
            if bind.dialect.name != 'postgresql' or bind.url != make_url(configured):
                raise ValueError('Engine differs from validated target')
        except Exception:
            raise LedgerError('Synthetic ledger requires validated private PostgreSQL', 'LEDGER_ISOLATION_REQUIRED', 503) from None

    @staticmethod
    def _request(data):
        if not isinstance(data, dict) or set(data) != _REQUIRED:
            raise LedgerError('An exact normalized receipt object is required')
        if data['source'] != 'synthetic' or data['merchant_context'] != 'isolated-tests':
            raise LedgerError('No provider settlement adapter is configured', 'LEDGER_SOURCE_NOT_CONFIGURED', 503)
        if not isinstance(data['event_key'], str) or not _IDENTIFIER.fullmatch(data['event_key']):
            raise LedgerError('A bounded ASCII source event key is required')
        if not isinstance(data['order_id'], str) or not _UUID.fullmatch(data['order_id']):
            raise LedgerError('A canonical order identifier is required')
        amount = data['amount_minor']
        if type(amount) is not int or not 1 <= amount <= 9999999999 or data['currency'] != 'USD':
            raise LedgerError('Only positive exact USD minor units are supported')
        if not isinstance(data['payload_hash'], str) or not _HEX_HASH.fullmatch(data['payload_hash']):
            raise LedgerError('A lowercase SHA-256 payload digest is required')
        return dict(data)

    @staticmethod
    def _storage_ready():
        """Fail closed unless immutable and deferred balance checks are installed."""
        db.session.execute(text("SET LOCAL lock_timeout = '3s'"))
        db.session.execute(text("SET LOCAL statement_timeout = '5s'"))
        if db.session.execute(text('SHOW session_replication_role')).scalar_one() != 'origin':
            raise LedgerError('Ledger checks require origin trigger execution', 'LEDGER_STORAGE_NOT_READY', 503)
        head = db.session.execute(text('SELECT version_num FROM public.alembic_version')).scalars().all()
        if head != ['20261011_000007']:
            raise LedgerError('Receipt ledger storage is not ready', 'LEDGER_STORAGE_NOT_READY', 503)
        # Canonical trigger and function definitions are pinned below once the
        # frozen revision is built; this assertion must never silently opt out.
        from src.services.settlement_ledger_contract import EXPECTED_TRIGGERS, EXPECTED_FUNCTION_HASHES
        rows = db.session.execute(text("""
            SELECT c.relname AS table_name, t.tgname AS name, t.tgtype,
                   t.tgenabled, t.tgdeferrable, t.tginitdeferred,
                   t.tgnargs, t.tgconstraint,
                   t.tgqual IS NULL AS unconditional, p.proname AS function_name,
                   p.prosrc, p.prosecdef, p.proconfig, p.pronargs,
                   p.prokind, p.provolatile, p.proisstrict, p.proleakproof, p.proparallel,
                   l.lanname AS language, p.prorettype::regtype::text AS return_type
            FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            JOIN pg_proc p ON p.oid=t.tgfoid
            JOIN pg_namespace pn ON pn.oid=p.pronamespace
            JOIN pg_language l ON l.oid=p.prolang
            WHERE n.nspname='public' AND pn.nspname='public' AND NOT t.tgisinternal
              AND c.relname IN ('purchase_orders', 'payment_event_receipts', 'settlement_journals', 'settlement_entries')
        """)).mappings().all()
        actual = {(r['table_name'], r['name']): r for r in rows}
        if set(actual) != set(EXPECTED_TRIGGERS):
            raise LedgerError('Ledger trigger set differs from canonical storage', 'LEDGER_STORAGE_NOT_READY', 503)
        for key, expected in EXPECTED_TRIGGERS.items():
            row = actual[key]
            body_hash = hashlib.sha256(row['prosrc'].strip().encode()).hexdigest()
            if (row['tgtype'], row['tgdeferrable'], row['tginitdeferred'], row['function_name']) != expected or (
                row['tgenabled'] != 'O' or not row['unconditional'] or row['prosecdef'] or row['proconfig'] is not None
                or row['tgnargs'] != 0 or (row['tgconstraint'] != 0) != expected[1]
                or row['prokind'] != 'f' or row['provolatile'] != 'v' or row['proisstrict']
                or row['proleakproof'] or row['proparallel'] != 'u'
                or row['pronargs'] != 0 or row['language'] != 'plpgsql' or row['return_type'] != 'trigger'
                or body_hash != EXPECTED_FUNCTION_HASHES.get(row['function_name'])
            ):
                raise LedgerError('Ledger checks differ from canonical storage', 'LEDGER_STORAGE_NOT_READY', 503)

        expected_unique = {
            ('payment_event_receipts', 'uq_payment_event_identity'): ['source', 'merchant_context', 'event_key'],
            ('settlement_journals', 'uq_journal_receipt'): ['receipt_id'],
            ('settlement_journals', 'uq_journal_order'): ['order_id'],
            ('settlement_entries', 'uq_journal_line'): ['journal_id', 'line_number'],
        }
        constraint_rows = db.session.execute(text("""
            SELECT c.relname AS table_name, con.conname AS name, con.contype,
                   con.convalidated, con.condeferrable, i.indisvalid,
                   ARRAY(SELECT a.attname FROM unnest(con.conkey) WITH ORDINALITY k(num, pos)
                         JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=k.num ORDER BY k.pos) AS columns
            FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            LEFT JOIN pg_index i ON i.indexrelid=con.conindid
            WHERE n.nspname='public' AND con.contype='u'
              AND c.relname IN ('payment_event_receipts','settlement_journals','settlement_entries')
        """)).mappings().all()
        actual_unique = {(r['table_name'], r['name']): r for r in constraint_rows}
        if set(actual_unique) != set(expected_unique) or any(
            actual_unique[key]['columns'] != columns or not actual_unique[key]['convalidated']
            or actual_unique[key]['condeferrable'] or not actual_unique[key]['indisvalid']
            for key, columns in expected_unique.items()
        ):
            raise LedgerError('Ledger deduplication constraints are not ready', 'LEDGER_STORAGE_NOT_READY', 503)

        expected_fks = {
            ('payment_event_receipts', 'fk_receipt_order'): ('order_id', 'purchase_orders'),
            ('settlement_journals', 'fk_journal_receipt'): ('receipt_id', 'payment_event_receipts'),
            ('settlement_journals', 'fk_journal_order'): ('order_id', 'purchase_orders'),
            ('settlement_entries', 'fk_entry_journal'): ('journal_id', 'settlement_journals'),
        }
        fk_rows = db.session.execute(text("""
            SELECT c.relname AS table_name, con.conname AS name, target.relname AS parent,
                   a.attname AS column_name, pa.attname AS parent_column,
                   con.convalidated, con.condeferrable, con.confupdtype, con.confdeltype,
                   array_length(con.conkey, 1) AS key_count
            FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace
            JOIN pg_class target ON target.oid=con.confrelid
            JOIN pg_namespace pn ON pn.oid=target.relnamespace
            JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum=con.conkey[1]
            JOIN pg_attribute pa ON pa.attrelid=target.oid AND pa.attnum=con.confkey[1]
            WHERE n.nspname='public' AND pn.nspname='public' AND con.contype='f'
              AND c.relname IN ('payment_event_receipts','settlement_journals','settlement_entries')
        """)).mappings().all()
        actual_fks = {(r['table_name'], r['name']): r for r in fk_rows}
        if set(actual_fks) != set(expected_fks) or any(
            (actual_fks[key]['column_name'], actual_fks[key]['parent']) != expected
            or actual_fks[key]['parent_column'] != 'id' or actual_fks[key]['key_count'] != 1
            or not actual_fks[key]['convalidated'] or actual_fks[key]['condeferrable']
            or actual_fks[key]['confupdtype'] != 'a' or actual_fks[key]['confdeltype'] != 'a'
            for key, expected in expected_fks.items()
        ):
            raise LedgerError('Ledger source references are not ready', 'LEDGER_STORAGE_NOT_READY', 503)

    @staticmethod
    def _receipt(data):
        return db.session.execute(select(PaymentEventReceipt).where(
            PaymentEventReceipt.source == data['source'],
            PaymentEventReceipt.merchant_context == data['merchant_context'],
            PaymentEventReceipt.event_key == data['event_key'],
        ).execution_options(populate_existing=True)).scalar_one_or_none()

    @staticmethod
    def _replay(receipt, data):
        if any(getattr(receipt, field) != data[field] for field in _REQUIRED):
            raise LedgerError('Source event identity conflicts with recorded evidence', 'LEDGER_EVENT_CONFLICT', 409)
        journal = db.session.execute(select(SettlementJournal).where(
            SettlementJournal.receipt_id == receipt.id).execution_options(populate_existing=True)).scalar_one_or_none()
        if journal is None or journal.order_id != receipt.order_id or journal.amount_minor != receipt.amount_minor or journal.currency != receipt.currency:
            raise LedgerError('Stored receipt journal is inconsistent', 'LEDGER_INTEGRITY_FAILED', 503)
        lines = db.session.execute(select(SettlementEntry).where(SettlementEntry.journal_id == journal.id)
                                  .order_by(SettlementEntry.line_number).limit(3).execution_options(populate_existing=True)).scalars().all()
        expected = [(1, 'provider_clearing', 'debit', journal.amount_minor), (2, 'unapplied_order_receipts', 'credit', journal.amount_minor)]
        if [(r.line_number, r.account_code, r.side, r.amount_minor) for r in lines] != expected:
            raise LedgerError('Stored ledger lines are inconsistent', 'LEDGER_INTEGRITY_FAILED', 503)
        return LedgerResult(receipt.id, journal.id, journal.order_id, journal.amount_minor, journal.currency, False)

    @staticmethod
    def record_synthetic_receipt(data):
        """Atomic synthetic event/2-line journal; caller owns the outer commit.

        A nested savepoint is an error boundary, not an implicit commit. No user
        balance, paid flag, challenge, commission or provider side effect occurs.
        """
        SettlementLedgerService._isolated_target()
        data = SettlementLedgerService._request(data)
        SettlementLedgerService._storage_ready()
        with without_hierarchy_scope(db.session):
            order = db.session.execute(select(PurchaseOrder).where(PurchaseOrder.id == data['order_id'])
                                       .with_for_update().execution_options(skip_hierarchy_scope=True, populate_existing=True)).scalar_one_or_none()
        if order is None:
            raise LedgerError('Order evidence was not found', 'LEDGER_ORDER_NOT_FOUND', 404)
        try:
            OrderService._integrity(order)
        except OrderError:
            raise LedgerError('Order evidence is inconsistent', 'LEDGER_INTEGRITY_FAILED', 503) from None
        if order.amount_minor != data['amount_minor'] or order.currency != data['currency']:
            raise LedgerError('Receipt money does not match frozen order', 'LEDGER_ORDER_MISMATCH', 409)
        existing = SettlementLedgerService._receipt(data)
        if existing is not None:
            return SettlementLedgerService._replay(existing, data)
        if db.session.execute(select(SettlementJournal.id).where(SettlementJournal.order_id == order.id)).scalar_one_or_none() is not None:
            raise LedgerError('The order already has a receipt journal', 'LEDGER_ORDER_ALREADY_RECORDED', 409)
        try:
            with db.session.begin_nested():
                receipt_id, journal_id = str(uuid4()), str(uuid4())
                receipt = PaymentEventReceipt(id=receipt_id, **data)
                db.session.add(receipt)
                db.session.flush()
                db.session.add(SettlementJournal(id=journal_id, receipt_id=receipt_id, order_id=order.id,
                                                amount_minor=order.amount_minor, currency=order.currency))
                db.session.flush()
                db.session.add_all([
                    SettlementEntry(id=str(uuid4()), journal_id=journal_id, line_number=1, account_code='provider_clearing', side='debit', amount_minor=order.amount_minor),
                    SettlementEntry(id=str(uuid4()), journal_id=journal_id, line_number=2, account_code='unapplied_order_receipts', side='credit', amount_minor=order.amount_minor),
                ])
                db.session.flush()
                # Fire only this ledger's deferred checks inside the savepoint:
                # malformed evidence cannot escape even if a caller later commits.
                from src.services.settlement_ledger_contract import DEFERRED_CONSTRAINT_NAMES
                constraint_names = ', '.join('"' + name + '"' for name in DEFERRED_CONSTRAINT_NAMES)
                db.session.execute(text('SET CONSTRAINTS ' + constraint_names + ' IMMEDIATE'))
                db.session.execute(text('SET CONSTRAINTS ' + constraint_names + ' DEFERRED'))
            return LedgerResult(receipt_id, journal_id, order.id, order.amount_minor, order.currency, True)
        except IntegrityError:
            # The DB remains the final authority across different locked orders
            # sharing a source identity. The failed savepoint removed all writes.
            existing = SettlementLedgerService._receipt(data)
            if existing is not None:
                return SettlementLedgerService._replay(existing, data)
            raise LedgerError('Ledger identity or balance conflict', 'LEDGER_EVENT_CONFLICT', 409) from None
