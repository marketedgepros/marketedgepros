"""Consistent projected read-only PostgreSQL snapshot for legacy balance diagnostics."""
from sqlalchemy import text
from src.services.balance_reconciliation import ReconciliationInputError, reconcile_snapshot


_PROJECTIONS = {
    'users': 'id',
    'wallets': 'id, user_id, main_balance, commission_balance, bonus_balance',
    'transactions': 'id, wallet_id, type, amount, balance_type, balance_before, balance_after, reference_type, reference_id, created_at',
}


def reconcile_readonly_connection(connection, *, max_rows=10000):
    """Require caller-owned REPEATABLE READ READ ONLY transaction before reads.

    No factory, ORM autoflush, hidden commit, account creation or UPDATE is used.
    A missing table/column is a schema error, never proof of an empty balance.
    """
    if type(max_rows) is not int or not 1 <= max_rows <= 10000:
        raise ReconciliationInputError('A bounded snapshot row budget is required')
    if connection.dialect.name != 'postgresql' or not connection.in_transaction():
        raise ReconciliationInputError('Audit requires an explicit PostgreSQL read-only transaction')
    readonly = connection.execute(text('SHOW transaction_read_only')).scalar_one()
    isolation = connection.execute(text('SHOW transaction_isolation')).scalar_one()
    if readonly != 'on' or isolation not in ('repeatable read', 'serializable'):
        raise ReconciliationInputError('Audit requires a consistent read-only transaction')
    connection.execute(text("SET LOCAL statement_timeout = '5s'"))
    snapshots = {}
    for table, projection in _PROJECTIONS.items():
        snapshots[table] = [dict(row) for row in connection.execute(text(
            f'SELECT {projection} FROM public.{table} ORDER BY id LIMIT :ceiling'
        ), {'ceiling': max_rows + 1}).mappings().all()]
        if len(snapshots[table]) > max_rows:
            raise ReconciliationInputError('Snapshot exceeds row budget; no partial reconciliation was produced')
    return reconcile_snapshot(snapshots['users'], snapshots['wallets'], snapshots['transactions'], max_rows=max_rows)
