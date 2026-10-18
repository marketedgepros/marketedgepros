"""No production/provider execution path for durable protocol rehearsal."""
from datetime import datetime, timezone
from flask import Flask
import pytest
from src.database import db
from src.services.trading_protocol_service import TradingProtocolRehearsal, ProtocolError

AT = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)
COMMAND = '12345678-1234-1234-1234-123456789abc'


def _calls():
    return (
        lambda: TradingProtocolRehearsal.store_rules(1, None, at=AT),
        lambda: TradingProtocolRehearsal.plan_command(1, 1, 'synthetic', 'a' * 64, at=AT),
        lambda: TradingProtocolRehearsal.claim_command(COMMAND, at=AT),
        lambda: TradingProtocolRehearsal.mark_uncertain(COMMAND, COMMAND, at=AT),
        lambda: TradingProtocolRehearsal.acknowledge(COMMAND, COMMAND, 'synthetic-account', at=AT),
        lambda: TradingProtocolRehearsal.record_observation(COMMAND, None, at=AT),
    )


@pytest.mark.parametrize('testing,enabled,inner', [(False, True, '1'), (True, False, '1'), (True, True, None)])
def test_all_protocol_operations_refuse_before_engine_without_isolated_opt_in(monkeypatch, testing, enabled, inner):
    app = Flask('synthetic-protocol')
    app.config.update(TESTING=testing, TRADING_PROTOCOL_REHEARSAL_ENABLED=enabled)
    monkeypatch.setenv('FLASK_TESTING', 'true')
    if inner is None:
        monkeypatch.delenv('MARKETEDGEPROS_STAGING_INNER', raising=False)
    else:
        monkeypatch.setenv('MARKETEDGEPROS_STAGING_INNER', inner)
    def forbidden(*args, **kwargs):
        raise AssertionError('Engine/SQL accessed before isolation')
    monkeypatch.setattr(db.session, 'get_bind', forbidden)
    monkeypatch.setattr(db.session, 'execute', forbidden)
    with app.app_context():
        for call in _calls():
            with pytest.raises(ProtocolError) as error:
                call()
            assert error.value.code == 'PROTOCOL_NOT_CONFIGURED'


def test_protocol_forged_runner_with_remote_target_refuses_before_engine(monkeypatch):
    app = Flask('protocol-forged-target')
    app.config.update(TESTING=True, TRADING_PROTOCOL_REHEARSAL_ENABLED=True,
                      SQLALCHEMY_DATABASE_URI='postgresql://remote.invalid/production', ISOLATED_STAGING_DATABASE=True)
    monkeypatch.setenv('FLASK_TESTING', 'true')
    monkeypatch.setenv('MARKETEDGEPROS_STAGING_INNER', '1')
    for name in ('STAGING_RUN_ROOT', 'STAGING_PG_SOCKET', 'STAGING_PG_PORT', 'STAGING_RUNTIME_USER'):
        monkeypatch.delenv(name, raising=False)
    def forbidden(*args, **kwargs):
        raise AssertionError('Engine accessed before target validation')
    monkeypatch.setattr(db.session, 'get_bind', forbidden)
    with app.app_context():
        for call in _calls():
            with pytest.raises(ProtocolError) as error:
                call()
            assert error.value.code == 'PROTOCOL_ISOLATION_REQUIRED'


def test_protocol_has_no_default_activation_or_registered_endpoint():
    from src.config import Config, TestingConfig, DevelopmentConfig, ProductionConfig
    assert all(c.TRADING_PROTOCOL_REHEARSAL_ENABLED is False for c in
               (Config, TestingConfig, DevelopmentConfig, ProductionConfig))
    from src.app import create_app
    app = create_app('testing')
    assert not any('protocol' in rule.rule or 'provision' in rule.rule for rule in app.url_map.iter_rules())
