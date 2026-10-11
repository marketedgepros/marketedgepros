"""Plan a single-brand data reconciliation without granting roles or inventing funds.

Planning is pure; application is permitted ONLY in the isolated restore runner.
This module is deliberately not a production data-migration CLI.
"""
from __future__ import annotations


class ReconciliationRefused(ValueError):
    pass


def plan_single_brand_reconciliation(users, tenants, challenges, programs, *, owner_id, brand_id):
    users = list(users)
    by_id = {row['id']: row for row in users}
    if len(by_id) != len(users):
        raise ReconciliationRefused('Duplicate user identifiers')
    owner = by_id.get(owner_id)
    if not owner or not (
        owner.get('role') == 'supermaster' and owner.get('parent_id') is None
        and owner.get('tree_path') == str(owner_id) and owner.get('level') == 0
        and owner.get('is_active') is True and owner.get('is_verified') is True
        and owner.get('can_create_same_role') is True
    ):
        raise ReconciliationRefused('Designated owner is not an existing eligible root')
    brands = [row for row in tenants if row['id'] == brand_id]
    if len(brands) != 1 or brands[0].get('status') != 'active':
        raise ReconciliationRefused('Designated brand is not a known active brand')
    if owner.get('tenant_id') not in (None, brand_id):
        raise ReconciliationRefused('Owner already belongs to a different brand')
    program_brand = {row['id']: row.get('tenant_id') for row in programs}
    affected_challenges = {}
    for row in challenges:
        affected_challenges.setdefault(row['user_id'], []).append(row)
    changes, excluded = [], []
    for row in sorted(users, key=lambda item: item['id']):
        if row.get('tenant_id') not in (None, brand_id):
            excluded.append({'user_id': row['id'], 'reason': 'existing_other_brand'})
            continue
        if row['id'] != owner_id and row.get('role') not in {'trader', 'guest', 'affiliate', 'agent'}:
            excluded.append({'user_id': row['id'], 'reason': 'future_role'})
            continue
        # Bounded by the documented hierarchy cap, not by caller input.
        chain, seen, current = [], set(), row
        for _ in range(128):
            if current['id'] in seen:
                raise ReconciliationRefused('Cycle in candidate ancestry')
            seen.add(current['id'])
            chain.append(current['id'])
            if current['id'] == owner_id:
                break
            current = by_id.get(current.get('parent_id'))
            if current is None:
                raise ReconciliationRefused('Candidate has disconnected ancestry')
            if current.get('tenant_id') not in (None, brand_id):
                raise ReconciliationRefused('Candidate crosses an existing brand boundary')
        else:
            raise ReconciliationRefused('Candidate ancestry exceeds depth budget')
        path_ids = list(reversed(chain))
        canonical = '/'.join(map(str, path_ids))
        legacy = '.'.join(map(str, path_ids))
        if len(canonical) > 500 or row.get('tree_path') not in {canonical, legacy}:
            raise ReconciliationRefused('Stored candidate path does not prove parent ownership')
        if row.get('level') != len(path_ids) - 1:
            raise ReconciliationRefused('Candidate level does not match ancestry')
        for challenge in affected_challenges.get(row['id'], []):
            if program_brand.get(challenge.get('program_id')) != brand_id:
                raise ReconciliationRefused('Candidate challenge points to another or unknown brand')
        version = row.get('token_version')
        if not isinstance(version, int) or isinstance(version, bool) or version < 0:
            raise ReconciliationRefused('Candidate token version is not explicit')
        if row.get('tenant_id') != brand_id or row.get('tree_path') != canonical:
            before = {key: row.get(key) for key in ('tenant_id', 'tree_path', 'token_version')}
            after = {'tenant_id': brand_id, 'tree_path': canonical, 'token_version': version + 1}
            changes.append({'user_id': row['id'], 'before': before, 'after': after})
    return {'owner_id': owner_id, 'brand_id': brand_id, 'changes': changes, 'excluded': excluded,
            'preserved_fields': ['role', 'parent_id', 'level', 'is_active', 'is_verified',
                                 'can_create_same_role', 'password_hash', 'money', 'kyc', 'payment', 'challenge_state'],
            'boundary': 'proposal only; application requires isolated restored-copy validation'}


def apply_plan_to_isolated_copy(connection, plan):
    from migrations.target_safety import validate_isolated_postgresql_target
    from sqlalchemy import text
    validate_isolated_postgresql_target(connection.engine.url.render_as_string(hide_password=False))
    # Lock/check every preimage before ANY update. The caller owns one transaction.
    for change in plan['changes']:
        actual = connection.execute(text('SELECT tenant_id, tree_path, token_version FROM users WHERE id=:id FOR UPDATE'),
                                    {'id': change['user_id']}).mappings().one_or_none()
        if actual is None or dict(actual) != change['before']:
            raise ReconciliationRefused('Plan preimage changed; no update permitted')
    for change in plan['changes']:
        params = dict(change['after'], id=change['user_id'])
        connection.execute(text('UPDATE users SET tenant_id=:tenant_id, tree_path=:tree_path, token_version=:token_version WHERE id=:id'), params)
