"""MT5 containment proofs; no provider account, credentials or trading orders."""
import ast
import asyncio
import importlib
import inspect
from flask import Flask
import pytest

from src.services.mt5_service import MT5Service, MT5ProviderNotConfigured
from src.services.mt5_challenge_service import MT5ChallengeService
from src.services.mt5_websocket_service import MT5WebSocketService


class Poison:
    def __getattribute__(self, name):
        raise AssertionError('unconfigured MT5 must not inspect caller transports or data')


@pytest.mark.parametrize('method', ['authenticate', 'create_account', 'get_account_info', 'get_positions',
                                    'get_trade_history', 'update_balance', 'disable_account', 'disable_trading'])
def test_mt5_service_boundary_refuses_all_provider_calls(method, monkeypatch):
    monkeypatch.setenv('MT5_API_URL', 'https://configured.invalid')
    monkeypatch.setenv('MT5_USERNAME', 'TEST_ONLY')
    monkeypatch.setenv('MT5_PASSWORD', 'TEST_ONLY')
    client = MT5Service()
    with pytest.raises(MT5ProviderNotConfigured) as error:
        getattr(client, method)() if method == 'authenticate' else getattr(client, method)(Poison())
    assert error.value.code == 'MT5_PROVIDER_NOT_CONFIGURED'
    assert error.value.status == 503
    assert not hasattr(client, 'session')
    assert not hasattr(client, 'password')
    assert not hasattr(client, 'api_url')


@pytest.mark.parametrize('method', ['create_mt5_account_for_challenge', 'disable_mt5_account_for_challenge',
                                    'update_challenge_from_mt5'])
def test_mt5_service_boundary_async_challenge_refusal_before_lookup(method):
    with pytest.raises(MT5ProviderNotConfigured):
        asyncio.run(getattr(MT5ChallengeService, method)(Poison()))


def test_mt5_service_boundary_credentials_and_parameters_are_not_guessed_or_disclosed():
    with pytest.raises(MT5ProviderNotConfigured):
        MT5ChallengeService.get_mt5_credentials(Poison(), Poison())
    with pytest.raises(MT5ProviderNotConfigured):
        MT5ChallengeService._get_account_parameters(Poison(), Poison())


@pytest.mark.parametrize('method', ['start', 'connect_deal_stream', 'connect_account_stream', 'connect_position_stream',
                                    'handle_deal_update', 'handle_account_update', 'handle_position_update',
                                    'calculate_challenge_progress'])
def test_mt5_service_boundary_stream_never_reads_data_or_reconnects(method):
    stream = MT5WebSocketService(Poison(), Poison())
    args = () if method in {'start', 'connect_deal_stream', 'connect_account_stream', 'connect_position_stream'} else (Poison(),)
    with pytest.raises(MT5ProviderNotConfigured):
        asyncio.run(getattr(stream, method)(*args))
    assert stream.running is False
    asyncio.run(stream.stop())
    assert stream.running is False


@pytest.mark.parametrize('path', ['/trade', '/balance', '/equity'])
def test_mt5_service_boundary_webhook_refuses_even_if_mounted_without_parsing(path, monkeypatch):
    from src.webhooks.mt5_webhook_handler import mt5_webhooks_bp, verify_mt5_signature
    from werkzeug.wrappers import Request
    monkeypatch.setattr(Request, 'get_json', lambda *a, **k: pytest.fail('no callback body parsing before refusal'))
    app = Flask(__name__)
    app.config['MT5_WEBHOOK_SECRET'] = 'TEST_ONLY'
    app.register_blueprint(mt5_webhooks_bp)
    response = app.test_client().post('/webhooks/mt5' + path, data='{malformed', content_type='application/json')
    assert response.status_code == 503
    assert response.get_json()['code'] == 'MT5_PROVIDER_NOT_CONFIGURED'
    assert verify_mt5_signature(Poison(), Poison(), Poison()) is False
    assert app.test_client().get('/webhooks/mt5/status').status_code == 503


@pytest.mark.parametrize('name,args', [
    ('sync_mt5_trades', ()), ('sync_challenge_data', (Poison(),)), ('check_all_violations', ()),
    ('check_challenge_violations', (Poison(),)), ('disable_mt5_account_task', (Poison(), Poison())),
    ('send_violation_notifications', (Poison(), Poison())), ('sync_challenge_immediate', (Poison(),)),
    ('log_monitoring_event', (Poison(), Poison(), Poison())),
    ('log_violation', (Poison(), Poison(), Poison(), Poison())),
])
def test_mt5_service_boundary_monitoring_never_claims_violation_or_provider_suspension(name, args):
    module = importlib.import_module('src.tasks.monitoring_tasks')
    result = getattr(module, name)(*args)
    assert result['success'] is False
    assert result['provider_confirmed'] is False
    assert result['code'] == 'MT5_PROVIDER_NOT_CONFIGURED'
    assert 'violation_detected' not in result
    assert 'synced' not in result


@pytest.mark.parametrize('name', ['src.services.mt5_service', 'src.services.mt5_challenge_service',
                                  'src.services.mt5_websocket_service', 'src.tasks.monitoring_tasks',
                                  'src.webhooks.mt5_webhook_handler'])
def test_mt5_service_boundary_import_surface_has_no_database_network_or_credentials(name):
    tree = ast.parse(inspect.getsource(importlib.import_module(name)))
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append(node.module or '')
    assert not any(n.startswith(('requests', 'websockets', 'socket', 'os', 'src.database', 'src.models',
                                  'src.services.notification')) for n in imports)
    assert not any(isinstance(n, (ast.While, ast.AsyncFor)) for n in ast.walk(tree))


def test_mt5_service_boundary_legacy_payment_confirmation_cannot_activate_after_provisioning_failure(monkeypatch):
    from src.services.payment_service import PaymentService

    monkeypatch.setattr(PaymentService, '_get_stripe_key', lambda: pytest.fail('no secret/provider work'))
    result = PaymentService.confirm_payment(Poison())
    assert result['status'] == 'error'
    assert result['confirmed'] is False
    assert result['code'] == 'ORDER_SETTLEMENT_NOT_CONFIGURED'
    # The gate must work without Flask context/DB initialization as well.
    assert 'client_secret' not in result
