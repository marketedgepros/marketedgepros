"""Focused security regressions: never load the legacy production-prone suite."""
import os
import socket

import pytest

os.environ['FLASK_TESTING'] = 'true'
os.environ['FLASK_ENV'] = 'testing'
os.environ.pop('DATABASE_URL', None)
os.environ.pop('TEST_DATABASE_URL', None)

if os.environ.get('MARKETEDGEPROS_NETWORK_NAMESPACE') == '1':
    if [name for _, name in socket.if_nameindex()] != ['lo']:
        raise RuntimeError('Security collection must run in an isolated network namespace')


@pytest.fixture(autouse=True)
def deny_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError('Network access is forbidden in security regressions')
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket.socket, 'connect_ex', blocked)
    monkeypatch.setattr(socket, 'create_connection', blocked)
    monkeypatch.setenv('FLASK_TESTING', 'true')
    monkeypatch.setenv('FLASK_ENV', 'testing')
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.delenv('TEST_DATABASE_URL', raising=False)
