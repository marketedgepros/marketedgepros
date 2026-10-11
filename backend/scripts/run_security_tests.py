#!/usr/bin/env python3
"""Run focused regressions in an OS network namespace and clean environment."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

BACKEND = Path(__file__).resolve().parents[1]
SUITE = BACKEND / 'security_tests'


def main():
    # A fresh network namespace (no interfaces except down loopback) is inherited
    # by execnet workers and subprocesses before any suite module is imported.
    # Fail closed instead of silently falling back to Python monkeypatch alone.
    unshare = shutil.which('unshare')
    if not unshare:
        print('util-linux unshare is required for network-isolated tests', file=sys.stderr)
        return 2
    env = {
        'PATH': os.defpath,
        'HOME': '/tmp',
        'LANG': 'C.UTF-8',
        'FLASK_TESTING': 'true',
        'FLASK_ENV': 'testing',
        'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1',
        'MARKETEDGEPROS_NETWORK_NAMESPACE': '1',
    }
    code = '''
import socket, sys
# Do not trust an environment flag alone: the network must be a fresh namespace.
if [name for _, name in socket.if_nameindex()] != ['lo']:
    raise SystemExit('Refusing test run outside an isolated network namespace')

def denied(*args, **kwargs):
    raise AssertionError('Python TCP access forbidden in focused security suite')
socket.socket.connect = denied
socket.socket.connect_ex = denied
socket.create_connection = denied
sys.path.insert(0, sys.argv[1])
import pytest
raise SystemExit(pytest.main(sys.argv[2:]))
'''
    command = [unshare, '--user', '--map-root-user', '--net', '--',
               sys.executable, '-I', '-c', code, str(BACKEND),
               '-p', 'xdist.plugin', '--confcutdir=' + str(SUITE),
               '-c', str(SUITE / 'pytest.ini'), str(SUITE), *sys.argv[1:]]
    return subprocess.call(command, cwd=BACKEND, env=env)


if __name__ == '__main__':
    raise SystemExit(main())
