"""Server-only NOWPayments credential binding; synthetic values, no network."""
from pathlib import Path
import runpy

import pytest


_CONFIG = Path(__file__).resolve().parents[1] / 'src' / 'config.py'


def _load(monkeypatch, api_key, ipn_secret):
    monkeypatch.setenv('FLASK_TESTING', 'true')
    for name, value in [('NOWPAYMENTS_API_KEY', api_key),
                        ('NOWPAYMENTS_IPN_SECRET', ipn_secret)]:
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    return runpy.run_path(str(_CONFIG))


@pytest.mark.parametrize('value', [None, ''])
def test_missing_nowpayments_credentials_remain_unconfigured(monkeypatch, value):
    config = _load(monkeypatch, value, value)
    for name in ('Config', 'DevelopmentConfig', 'ProductionConfig', 'TestingConfig'):
        assert config[name].NOWPAYMENTS_API_KEY is None
        assert config[name].NOWPAYMENTS_IPN_SECRET is None


def test_runtime_credentials_are_server_only_and_testing_discards_them(monkeypatch):
    config = _load(monkeypatch, 'synthetic-api-key-not-live', 'synthetic-ipn-not-live')
    for name in ('Config', 'DevelopmentConfig', 'ProductionConfig'):
        assert config[name].NOWPAYMENTS_API_KEY == 'synthetic-api-key-not-live'
        assert config[name].NOWPAYMENTS_IPN_SECRET == 'synthetic-ipn-not-live'
        assert config[name].SYNTHETIC_SETTLEMENT_ENABLED is False
        assert config[name].ORDER_QUOTES_ENABLED is False
    assert config['TestingConfig'].NOWPAYMENTS_API_KEY is None
    assert config['TestingConfig'].NOWPAYMENTS_IPN_SECRET is None
