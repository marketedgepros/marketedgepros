"""Real full-factory quote requests against synthetic, isolated data."""
from decimal import Decimal
import json
import pytest
from sqlalchemy import select
from src.database import db
from src.models.user import User
from src.models.tenant import Tenant
from src.models.token_blacklist import TokenBlacklist
from src.models.trading_program import TradingProgram, ProgramAddOn, Challenge
from src.models.payment import Payment
from src.models.purchase_order import PurchaseOrder


@pytest.fixture
def quote_app():
    from src.app import create_app
    app = create_app('testing', config_overrides={'EXPANDED_HIERARCHY_ENABLED': False, 'PLATFORM_ROOT_USER_ID': 1,
                                                'ORDER_QUOTES_ENABLED': True, 'ORDER_QUOTE_CURRENCY': 'USD',
                                                'PROPAGATE_EXCEPTIONS': False})
    tables = [Tenant.__table__, User.__table__, TokenBlacklist.__table__, TradingProgram.__table__,
              ProgramAddOn.__table__, Challenge.__table__, Payment.__table__, PurchaseOrder.__table__]
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=tables)
        db.session.add_all([Tenant(id=1, name='Synthetic Brand', subdomain='quote-brand', status='active'),
                            Tenant(id=2, name='Other Brand', subdomain='other-quote-brand', status='active')])
        for identity, tenant, role in [(1, 1, 'supermaster'), (2, 1, 'trader'), (3, 1, 'affiliate'), (4, 2, 'trader'), (5, 1, 'trader')]:
            db.session.add(User(id=identity, email=f'quote-{identity}@example.invalid', password_hash='not-a-credential',
                                first_name='Synthetic', last_name='Actor', tenant_id=tenant, role=role,
                                is_active=True, is_verified=True, can_create_same_role=identity == 1,
                                parent_id=None if identity == 1 else 1, tree_path='1' if identity == 1 else f'1/{identity}',
                                level=0 if identity == 1 else 1))
        db.session.add_all([TradingProgram(id=10, tenant_id=1, name='Synthetic Program', type='one_phase', account_size=10000,
                                          price=Decimal('19.99'), is_active=True, rules={'rule': {'target': None}}),
                            TradingProgram(id=11, tenant_id=2, name='Other Program', type='one_phase', account_size=10000,
                                          price=Decimal('1.00'), is_active=True),
                            TradingProgram(id=12, tenant_id=1, name='Inactive Program', type='one_phase', account_size=10000,
                                          price=Decimal('1.00'), is_active=False)])
        db.session.add_all([ProgramAddOn(id=20, program_id=10, name='Fixed', price=Decimal('0.10'), price_type='fixed', is_active=True, benefits={'unknown': None}),
                            ProgramAddOn(id=21, program_id=10, name='Percent', price=Decimal('10.00'), price_type='percentage', is_active=True),
                            ProgramAddOn(id=22, program_id=11, name='Foreign', price=Decimal('0.10'), price_type='fixed', is_active=True),
                            ProgramAddOn(id=23, program_id=10, name='Inactive', price=Decimal('0.10'), price_type='fixed', is_active=False)])
        db.session.commit()
        app.quote_tokens = {identity: db.session.get(User, identity).generate_access_token() for identity in [1, 2, 3, 4, 5]}
    yield app
    with app.app_context():
        db.session.remove()
        db.metadata.drop_all(bind=db.engine, tables=list(reversed(tables)))


def _headers(app, actor=2, key='synthetic_quote_key_0001'):
    return {'Authorization': 'Bearer ' + app.quote_tokens[actor], 'Idempotency-Key': key}


def _create(app, body=None, actor=2, key='synthetic_quote_key_0001'):
    return app.test_client().post('/api/v1/orders/', json=body if body is not None else {'program_id': 10, 'addon_ids': [21, 20]}, headers=_headers(app, actor, key))


def test_server_exact_decimal_price_and_unknown_terms_without_financial_side_effects(quote_app):
    response = _create(quote_app)
    assert response.status_code == 201
    order = response.get_json()['order']
    assert order['amount'] == '22.09' and order['amount_minor'] == 2209 and order['currency'] == 'USD'
    assert order['state'] == 'quoted' and order['paid'] is False
    assert order['snapshot']['entitlement'] is False
    assert order['snapshot']['terms']['rules'] == {'rule': {'target': None}}
    assert order['snapshot']['terms']['minimum_payout_amount'] == '50.00'  # actual stored catalog, not a service-created rule
    with quote_app.app_context():
        assert db.session.query(PurchaseOrder).count() == 1
        assert db.session.query(Payment).count() == db.session.query(Challenge).count() == 0


@pytest.mark.parametrize('field,value', [('amount', '0.01'), ('user_id', 5), ('tenant_id', 2), ('currency', 'EUR'),
                                       ('payment_status', 'paid'), ('payment_type', 'free'), ('status', 'active'), ('discount', 99)])
def test_request_cannot_control_money_identity_or_status(quote_app, field, value):
    response = _create(quote_app, {'program_id': 10, field: value})
    assert response.status_code == 400
    with quote_app.app_context():
        assert db.session.query(PurchaseOrder).count() == db.session.query(Payment).count() == db.session.query(Challenge).count() == 0


@pytest.mark.parametrize('body', [[], {'program_id': True}, {'program_id': '10'}, {'program_id': -1},
                                 {'program_id': 10, 'addon_ids': [20, 20]}, {'program_id': 10, 'addon_ids': [True]},
                                 {'program_id': 10, 'addon_ids': [20] * 21}, {'program_id': 10, 'addon_ids': '20'}])
def test_invalid_request_refused(quote_app, body):
    assert _create(quote_app, body).status_code == 400


@pytest.mark.parametrize('key', ['', 'short', 'a' * 129, 'x' * 16 + ' ', 'עברית' * 5])
def test_invalid_idempotency_keys_refused(quote_app, key):
    assert _create(quote_app, key=key).status_code == 400


@pytest.mark.parametrize('body', [{'program_id': 11}, {'program_id': 12}, {'program_id': 999},
                                 {'program_id': 10, 'addon_ids': [22]}, {'program_id': 10, 'addon_ids': [23]},
                                 {'program_id': 10, 'addon_ids': [999]}])
def test_catalog_foreign_inactive_or_missing_selection_is_not_silently_ignored(quote_app, body):
    assert _create(quote_app, body).status_code == 404


def test_replay_returns_same_snapshot_after_catalog_changes_and_conflict_refused(quote_app):
    first = _create(quote_app).get_json()['order']
    with quote_app.app_context():
        db.session.get(TradingProgram, 10).price = Decimal('79.99')
        db.session.get(TradingProgram, 10).is_active = False
        db.session.get(ProgramAddOn, 20).benefits = {'changed': True}
        db.session.commit()
    replay = _create(quote_app, {'program_id': 10, 'addon_ids': [20, 21]})
    assert replay.status_code == 200 and replay.get_json()['replayed'] is True
    assert replay.get_json()['order'] == first
    assert _create(quote_app, {'program_id': 10, 'addon_ids': []}).status_code == 409
    with quote_app.app_context():
        assert db.session.query(PurchaseOrder).count() == 1


def test_instant_funding_refuses_a_new_quote_before_insert_even_without_policy_metadata(quote_app):
    with quote_app.app_context():
        db.session.add(TradingProgram(
            id=13, tenant_id=1, name='Coming soon instant', type='instant_funding',
            account_size=Decimal('10000.00'), price=Decimal('19.99'), is_active=True,
            # No evaluation_policy is required for this refusal: old/current
            # direct links may not manufacture a quote during Coming soon.
            rules={'unknown_legacy_rule': True},
        ))
        db.session.commit()
    response = _create(quote_app, {'program_id': 13}, key='synthetic_instant_quote_0001')
    assert response.status_code == 409 and response.get_json()['code'] == 'PROGRAM_COMING_SOON'
    with quote_app.app_context():
        assert db.session.query(PurchaseOrder).count() == 0


def test_stored_quote_replay_precedes_later_instant_catalog_guard(quote_app):
    original = _create(quote_app, {'program_id': 10}, key='synthetic_replay_instant_0001')
    assert original.status_code == 201
    with quote_app.app_context():
        db.session.get(TradingProgram, 10).type = 'instant_funding'
        db.session.commit()
    replay = _create(quote_app, {'program_id': 10}, key='synthetic_replay_instant_0001')
    assert replay.status_code == 200 and replay.get_json()['replayed'] is True
    assert replay.get_json()['order'] == original.get_json()['order']


def test_same_key_is_separate_per_owner_and_quote_read_is_exact_owner_only(quote_app):
    first = _create(quote_app).get_json()['order']
    second = _create(quote_app, actor=3).get_json()['order']
    assert first['id'] != second['id']
    assert quote_app.test_client().get('/api/v1/orders/' + first['id'], headers=_headers(quote_app)).status_code == 200
    for actor in [1, 3, 5]:
        assert quote_app.test_client().get('/api/v1/orders/' + first['id'], headers=_headers(quote_app, actor)).status_code == 404
    assert quote_app.test_client().get('/api/v1/orders/' + first['id'], headers=_headers(quote_app, 4)).status_code == 401
    assert _create(quote_app, actor=4).status_code == 401


def test_anonymous_and_malformed_requests_never_write(quote_app):
    assert quote_app.test_client().post('/api/v1/orders/', json={'program_id': 10}).status_code == 401
    assert quote_app.test_client().post('/api/v1/orders/', data='{', content_type='application/json', headers=_headers(quote_app)).status_code == 400
    assert quote_app.test_client().post('/api/v1/orders/', data='x' * 4097, content_type='application/json', headers=_headers(quote_app)).status_code == 413


@pytest.mark.parametrize('overrides', [{'ORDER_QUOTES_ENABLED': False}, {'ORDER_QUOTE_CURRENCY': None}, {'ORDER_QUOTE_CURRENCY': 'EUR'}])
def test_quotes_require_explicit_enablement_and_supported_currency(quote_app, overrides):
    quote_app.config.update(overrides)
    assert _create(quote_app).status_code == 503


@pytest.mark.parametrize('field,value', [('price_type', 'unknown'), ('price', Decimal('-0.01'))])
def test_invalid_catalog_price_refused_before_insert(quote_app, field, value):
    with quote_app.app_context():
        setattr(db.session.get(ProgramAddOn, 20), field, value)
        db.session.commit()
    assert _create(quote_app).status_code == 409


def test_mapper_disallows_snapshot_update_and_delete(quote_app):
    identity = _create(quote_app).get_json()['order']['id']
    with quote_app.app_context():
        order = db.session.get(PurchaseOrder, identity)
        order.amount_minor = 1
        with pytest.raises(ValueError, match='immutable'):
            db.session.commit()
        db.session.rollback()
        db.session.delete(db.session.get(PurchaseOrder, identity))
        with pytest.raises(ValueError, match='immutable'):
            db.session.commit()
        db.session.rollback()
        assert db.session.get(PurchaseOrder, identity).amount_minor == 2209


@pytest.mark.parametrize('raw', ['{"program_id":10,"program_id":11}', '{"program_id":NaN}', '[' * 1100 + ']' * 1100])
def test_ambiguous_nonfinite_or_excessive_depth_json_refused(quote_app, raw):
    response = quote_app.test_client().post('/api/v1/orders/', data=raw, content_type='application/json', headers=_headers(quote_app))
    assert response.status_code == 400


def test_browser_cors_preflight_allows_required_idempotency_header(quote_app):
    response = quote_app.test_client().options('/api/v1/orders/', headers={'Origin': 'http://localhost:3000',
        'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'authorization,content-type,idempotency-key'})
    assert response.status_code == 200
    assert 'idempotency-key' in response.headers.get('Access-Control-Allow-Headers', '').lower()


def test_cookie_auth_without_csrf_cannot_create_quote(quote_app):
    client = quote_app.test_client()
    client.set_cookie('access_token', quote_app.quote_tokens[2])
    response = client.post('/api/v1/orders/', json={'program_id': 10}, headers={'Idempotency-Key': 'synthetic_csrf_key_0001'})
    assert response.status_code == 403
    with quote_app.app_context():
        assert db.session.query(PurchaseOrder).count() == 0


def test_stored_snapshot_corruption_is_not_returned_as_valid_quote(quote_app):
    from sqlalchemy import text
    identity = _create(quote_app).get_json()['order']['id']
    with quote_app.app_context():
        # SQLite has only the ORM guard. PostgreSQL trigger behavior is proved in
        # revision tests. Deliberately simulate at-rest corruption here.
        db.session.execute(text("UPDATE purchase_orders SET snapshot_json = '{}' WHERE id = :id"), {'id': identity})
        db.session.commit()
    response = quote_app.test_client().get('/api/v1/orders/' + identity, headers=_headers(quote_app))
    assert response.status_code == 503 and response.get_json()['code'] == 'ORDER_INTEGRITY_FAILED'
    assert _create(quote_app).status_code == 503


def test_legacy_cash_free_approval_cannot_bypass_canonical_order(quote_app, monkeypatch):
    from src.services.payment_approval_service import PaymentApprovalService
    calls = []
    def forbidden(*args, **kwargs):
        calls.append('legacy approval')
        raise AssertionError('Unverified legacy cash/free settlement was invoked')
    monkeypatch.setattr(PaymentApprovalService, 'create_approval_request', forbidden)
    monkeypatch.setattr(PaymentApprovalService, 'approve_request', forbidden)
    for path, body in [('/api/v1/payment-approvals/create', {'requested_for': 5, 'amount': 0, 'payment_type': 'free'}),
                        ('/api/v1/payment-approvals/999/approve', {})]:
        response = quote_app.test_client().post(path, json=body, headers=_headers(quote_app, 1))
        assert response.status_code == 503 and response.get_json()['code'] == 'ORDER_SETTLEMENT_NOT_CONFIGURED'
        assert quote_app.test_client().post(path, json=body, headers=_headers(quote_app, 2)).status_code == 403
        assert quote_app.test_client().post(path, json=body).status_code == 401
    assert calls == []


def test_quote_amount_column_must_match_snapshot_even_with_unchanged_hash(quote_app):
    from sqlalchemy import text
    identity = _create(quote_app).get_json()['order']['id']
    with quote_app.app_context():
        db.session.execute(text('UPDATE purchase_orders SET amount_minor = 1 WHERE id = :id'), {'id': identity})
        db.session.commit()
    response = quote_app.test_client().get('/api/v1/orders/' + identity, headers=_headers(quote_app))
    assert response.status_code == 503 and response.get_json()['code'] == 'ORDER_INTEGRITY_FAILED'


@pytest.mark.parametrize('program_type,targets', [('one_phase', ['10.00']), ('two_phase', ['8.00', '5.00']), ('three_phase', ['5.00', '5.00', '5.00'])])
def test_versioned_family_policy_is_frozen_in_new_quote_without_private_history_or_entitlement(quote_app, program_type, targets):
    from src.services.program_catalog_service import program_terms
    from src.services.program_evaluation_policy import build_evaluation_policy
    with quote_app.app_context():
        program = db.session.get(TradingProgram, 10)
        old_terms = program_terms(program)
        policy = build_evaluation_policy(program_type)
        program.type = program_type
        program.profit_target = Decimal(targets[0])
        program.max_daily_loss = Decimal('5.00')
        program.max_total_loss = Decimal('10.00')
        program.profit_split = program.profit_split_percentage = Decimal('90.00')
        program.rules = {'drawdown_type': 'static', 'evaluation_policy': policy, '_mep_legacy_challenge_terms': {'999': old_terms}}
        db.session.commit()
    response = _create(quote_app, {'program_id': 10, 'addon_ids': []}, key='synthetic_versioned_family_quote_0001')
    assert response.status_code == 201
    order = response.get_json()['order']
    terms = order['snapshot']['terms']
    assert terms['rules']['evaluation_policy'] == policy
    assert terms['rules']['evaluation_policy']['phase_targets'] == targets
    assert terms['profit_split'] == terms['profit_split_percentage'] == '90.00'
    assert '_mep_legacy_challenge_terms' not in terms['rules']
    assert order['amount'] == '19.99' and order['state'] == 'quoted' and order['paid'] is False
    assert order['snapshot']['entitlement'] is False
    with quote_app.app_context():
        assert db.session.query(PurchaseOrder).count() == 1
        assert db.session.query(Payment).count() == db.session.query(Challenge).count() == 0
