"""Ledger rehearsal has no remotely accessible or production execution path."""
import hashlib
import pytest
from flask import Flask
from src.database import db
from src.services.settlement_ledger_service import SettlementLedgerService, LedgerError


def _data(**changes):
    body = {'source': 'synthetic', 'merchant_context': 'isolated-tests', 'event_key': 'test-event',
            'order_id': '12345678-1234-1234-1234-123456789abc', 'amount_minor': 1999,
            'currency': 'USD', 'payload_hash': hashlib.sha256(b'synthetic').hexdigest()}
    body.update(changes)
    return body


@pytest.mark.parametrize('testing,enabled,inner', [(False, True, '1'), (True, False, '1'), (True, True, None)])
def test_ledger_refuses_before_any_database_access(monkeypatch, testing, enabled, inner):
    app = Flask('ledger-rehearsal-gate')
    app.config.update(TESTING=testing, SYNTHETIC_SETTLEMENT_ENABLED=enabled)
    monkeypatch.setenv('FLASK_TESTING', 'true')
    if inner is None:
        monkeypatch.delenv('MARKETEDGEPROS_STAGING_INNER', raising=False)
    else:
        monkeypatch.setenv('MARKETEDGEPROS_STAGING_INNER', inner)
    calls = []
    def forbidden(*args, **kwargs):
        calls.append('sql')
        raise AssertionError('SQL/engine must not be reached')
    monkeypatch.setattr(db.session, 'get_bind', forbidden)
    monkeypatch.setattr(db.session, 'execute', forbidden)
    with app.app_context(), pytest.raises(LedgerError) as error:
        SettlementLedgerService.record_synthetic_receipt(_data())
    assert error.value.code == 'LEDGER_NOT_CONFIGURED' and calls == []


def test_forged_runner_flag_with_remote_target_refuses_before_engine(monkeypatch):
    app = Flask('ledger-invalid-target')
    app.config.update(TESTING=True, SYNTHETIC_SETTLEMENT_ENABLED=True,
                      SQLALCHEMY_DATABASE_URI='postgresql://remote.invalid/production')
    monkeypatch.setenv('FLASK_TESTING', 'true')
    monkeypatch.setenv('MARKETEDGEPROS_STAGING_INNER', '1')
    for name in ['STAGING_RUN_ROOT', 'STAGING_PG_SOCKET', 'STAGING_PG_PORT', 'STAGING_RUNTIME_USER']:
        monkeypatch.delenv(name, raising=False)
    def forbidden(*args, **kwargs):
        raise AssertionError('Engine must not be reached before validated isolation')
    monkeypatch.setattr(db.session, 'get_bind', forbidden)
    with app.app_context(), pytest.raises(LedgerError) as error:
        SettlementLedgerService.record_synthetic_receipt(_data())
    assert error.value.code == 'LEDGER_ISOLATION_REQUIRED'


@pytest.mark.parametrize('changes', [
    {'amount_minor': True}, {'amount_minor': 19.99}, {'amount_minor': 0}, {'amount_minor': -1},
    {'amount_minor': 10000000000}, {'amount_minor': '1999'}, {'currency': 'EUR'},
    {'source': 'stripe'}, {'merchant_context': 'live'}, {'event_key': 'x' * 129},
    {'event_key': ' '}, {'event_key': 'מפתח'}, {'payload_hash': 'a' * 63},
    {'payload_hash': 'Z' * 64}, {'order_id': 1}, {'order_id': 'not-an-order'},
])
def test_exact_normalized_synthetic_receipt_input_is_bounded(changes):
    with pytest.raises(LedgerError):
        SettlementLedgerService._request(_data(**changes))


@pytest.mark.parametrize('data', [None, [], {}, {'paid': True}])
def test_arbitrary_unverified_payload_cannot_be_recorded(data):
    with pytest.raises(LedgerError):
        SettlementLedgerService._request(data)


def test_synthetic_flag_is_disabled_in_all_default_configuration_classes():
    from src.config import Config, DevelopmentConfig, TestingConfig, ProductionConfig
    assert all(config.SYNTHETIC_SETTLEMENT_ENABLED is False for config in [Config, DevelopmentConfig, TestingConfig, ProductionConfig])


def test_no_settlement_route_is_registered_by_actual_factory():
    from src.app import create_app
    app = create_app('testing')
    assert not any('settlement' in rule.rule or 'ledger' in rule.rule for rule in app.url_map.iter_rules())
