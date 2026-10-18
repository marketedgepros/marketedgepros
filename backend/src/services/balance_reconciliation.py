"""Read-only legacy wallet arithmetic diagnostics, never opening-balance approval.

An arithmetically continuous legacy chain is NOT authenticated provider evidence.
Missing wallets, currencies or provenance must not be inferred as verified zeroes.
This pure bounded function has no DB, Flask, network, secrets or mutation imports.
"""
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal
import re


class ReconciliationInputError(ValueError):
    pass


BUCKET_FIELDS = {'main': 'main_balance', 'commission': 'commission_balance', 'bonus': 'bonus_balance'}
_MAX_MINOR = 999999999999
_MONEY = re.compile(r'-?[0-9]{1,10}(?:\.[0-9]{1,2})?\Z')


def exact_minor(value):
    """Read Numeric(12,2) exactly, rejecting floats, booleans and rounding."""
    if type(value) is int:
        rendered = str(value)
    elif isinstance(value, Decimal):
        if not value.is_finite():
            raise ReconciliationInputError('Amount is not finite')
        rendered = str(value)
    elif isinstance(value, str) and len(value) <= 14:
        rendered = value
    else:
        raise ReconciliationInputError('Amount must be an exact finite decimal')
    if not _MONEY.fullmatch(rendered):
        raise ReconciliationInputError('Amount must fit an exact two-decimal field')
    # Construct cents with integer arithmetic; a caller's Decimal context cannot
    # silently round a legacy amount and manufacture a matching chain.
    negative = rendered.startswith('-')
    whole, dot, fraction = rendered.lstrip('-').partition('.')
    minor = int(whole) * 100 + int(fraction.ljust(2, '0') if dot else '0')
    if negative:
        minor = -minor
    if abs(minor) > _MAX_MINOR:
        raise ReconciliationInputError('Amount exceeds legacy numeric storage range')
    return minor


def _rows(rows, label, maximum):
    if not isinstance(rows, (list, tuple)) or len(rows) > maximum:
        raise ReconciliationInputError(label + ' snapshot is missing or exceeds its row limit')
    result, ids = [], set()
    for row in rows:
        if not isinstance(row, dict) or type(row.get('id')) is not int or row['id'] <= 0:
            raise ReconciliationInputError(label + ' requires positive integer row identifiers')
        if row['id'] in ids:
            raise ReconciliationInputError(label + ' contains duplicate identifiers')
        ids.add(row['id'])
        result.append(row)
    return result


def _timestamp(value):
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str) and 1 <= len(value) <= 40:
        try:
            result = datetime.fromisoformat(value)
        except ValueError:
            raise ReconciliationInputError('Transaction timestamp is invalid') from None
    else:
        raise ReconciliationInputError('Transaction timestamp is missing')
    # Legacy schema uses timestamp WITHOUT timezone. Reject mixtures rather than
    # guessing whether local timestamps should be converted to UTC.
    if result.tzinfo is not None:
        raise ReconciliationInputError('Legacy timestamp must be timezone-naive')
    return result


def reconcile_snapshot(users, wallets, transactions, *, max_rows=10000):
    """Compare all supplied rows without inferring source, currency or authority.

    The caller must obtain the entire snapshot from a consistent read-only DB
    transaction. This function refuses over-limit inputs; it never truncates rows
    while claiming completeness. No imported/opening balance is approved here.
    """
    if type(max_rows) is not int or not 1 <= max_rows <= 10000:
        raise ReconciliationInputError('A bounded snapshot row budget is required')
    user_rows = _rows(users, 'users', max_rows)
    wallet_rows = _rows(wallets, 'wallets', max_rows)
    transaction_rows = _rows(transactions, 'transactions', max_rows)
    user_ids = {row['id'] for row in user_rows}
    wallet_ids = {row['id'] for row in wallet_rows}
    issues, grouped, owner_counts = [], defaultdict(list), Counter()
    def issue(code, wallet_id=None, transaction_id=None):
        item = {'code': code}
        if wallet_id is not None:
            item['wallet_id'] = wallet_id
        if transaction_id is not None:
            item['transaction_id'] = transaction_id
        issues.append(item)
    for row in wallet_rows:
        owner = row.get('user_id')
        if type(owner) is not int or owner not in user_ids:
            issue('WALLET_OWNER_MISSING', row['id'])
        else:
            owner_counts[owner] += 1
    for row in wallet_rows:
        if type(row.get('user_id')) is int and owner_counts[row['user_id']] > 1:
            issue('DUPLICATE_WALLET_OWNER', row['id'])
    for row in transaction_rows:
        wallet_id, bucket = row.get('wallet_id'), row.get('balance_type')
        if type(wallet_id) is not int or wallet_id not in wallet_ids:
            issue('TRANSACTION_WALLET_MISSING', transaction_id=row['id'])
        elif not isinstance(bucket, str) or bucket not in BUCKET_FIELDS:
            issue('TRANSACTION_BUCKET_UNKNOWN', wallet_id, row['id'])
        else:
            grouped[(wallet_id, bucket)].append(row)
    results = []
    for wallet in sorted(wallet_rows, key=lambda row: row['id']):
        buckets = {}
        references = set()
        for bucket, field in BUCKET_FIELDS.items():
            bucket_issues = []
            def problem(code, transaction_id=None):
                bucket_issues.append(code)
                issue(code, wallet['id'], transaction_id)
            try:
                current = exact_minor(wallet.get(field))
                if current < 0:
                    problem('NEGATIVE_STORED_BALANCE')
            except ReconciliationInputError:
                current = None
                problem('STORED_BALANCE_UNKNOWN_OR_INVALID')
            rows = grouped[(wallet['id'], bucket)]
            ordered = []
            for row in rows:
                try:
                    ordered.append((_timestamp(row.get('created_at')), row['id'], row))
                except ReconciliationInputError:
                    problem('TRANSACTION_TIME_INVALID', row['id'])
            ordered.sort(key=lambda item: (item[0], item[1]))
            # IDs are a reproducible tie-break, not proof of commit-time ordering.
            time_counts = Counter(item[0] for item in ordered)
            if any(count > 1 for count in time_counts.values()):
                problem('TRANSACTION_ORDER_AMBIGUOUS')
            opening_observed, last = None, None
            for _time, _id, row in ordered:
                try:
                    before = exact_minor(row.get('balance_before'))
                    after = exact_minor(row.get('balance_after'))
                    amount = exact_minor(row.get('amount'))
                except ReconciliationInputError:
                    problem('TRANSACTION_MONEY_INVALID', row['id'])
                    # Never bridge a malformed row to manufacture a continuous chain.
                    last = None
                    continue
                if before < 0 or after < 0 or amount <= 0:
                    problem('TRANSACTION_MONEY_NONPOSITIVE_OR_NEGATIVE', row['id'])
                kind = row.get('type')
                if not isinstance(kind, str):
                    kind = None
                delta = after - before
                if kind in ('deposit', 'commission', 'bonus'):
                    if delta != amount:
                        problem('TRANSACTION_DELTA_MISMATCH', row['id'])
                elif kind == 'withdrawal':
                    if delta != -amount:
                        problem('TRANSACTION_DELTA_MISMATCH', row['id'])
                elif kind == 'adjustment':
                    if abs(delta) != amount:
                        problem('TRANSACTION_DELTA_MISMATCH', row['id'])
                else:
                    problem('TRANSACTION_TYPE_UNKNOWN', row['id'])
                if opening_observed is None:
                    opening_observed = before
                if last is not None and before != last:
                    problem('TRANSACTION_CHAIN_GAP', row['id'])
                last = after
                reference_type, reference_id = row.get('reference_type'), row.get('reference_id')
                if not isinstance(reference_type, str) or not 1 <= len(reference_type) <= 50 or type(reference_id) is not int or reference_id <= 0:
                    problem('TRANSACTION_SOURCE_REFERENCE_MISSING', row['id'])
                else:
                    key = (reference_type, reference_id)
                    if key in references:
                        problem('TRANSACTION_SOURCE_REFERENCE_REUSED', row['id'])
                    references.add(key)
            if rows and last is not None and current is not None and last != current:
                problem('STORED_BALANCE_CHAIN_MISMATCH')
            buckets[bucket] = {
                'stored_minor': current,
                'transaction_count': len(rows),
                'opening_observed_minor': opening_observed,
                'closing_observed_minor': last,
                'arithmetic_continuity': 'inconsistent' if bucket_issues else ('consistent' if rows else 'no_history'),
                'verified_balance': False,
                'source_provenance': 'unverified_legacy',
                'currency': None,
                'issues': sorted(set(bucket_issues)),
            }
        results.append({'wallet_id': wallet['id'], 'user_id': wallet.get('user_id'), 'buckets': buckets,
                        'verified_balance': False})
    assigned = set(owner_counts)
    missing_wallet_count = len(user_ids - assigned)
    return {
        'schema_version': 1,
        'complete_supplied_snapshot': True,
        'status': 'blocked' if issues else 'unverified',
        'verified_balance_count': 0,
        'counts': {'users': len(user_rows), 'wallets': len(wallet_rows), 'transactions': len(transaction_rows),
                   'users_without_wallet': missing_wallet_count, 'issues': len(issues)},
        'wallets': results,
        'issues': issues,
        'limitations': ['No provider/source authenticity was verified', 'No opening balance or currency was inferred',
                        'Missing wallet is unknown, not verified zero', 'No wallet or journal was created or updated'],
    }


def aggregate_summary(report):
    """Redact row-level identifiers and balances for user-facing audit summaries."""
    return {'schema_version': report['schema_version'], 'status': report['status'],
            'counts': dict(report['counts']), 'verified_balance_count': report['verified_balance_count'],
            'issue_counts': dict(sorted(Counter(row['code'] for row in report['issues']).items())),
            'limitations': list(report['limitations'])}
