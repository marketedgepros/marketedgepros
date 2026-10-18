"""Namespace proof runs during collection, including in each xdist worker."""
import os
import subprocess
import sys

import pytest


# This has to execute at module import, not in a fixture. The fresh child does
# not inherit any Python socket monkeypatch, but inherits the OS namespace.
if os.environ.get('MARKETEDGEPROS_NETWORK_NAMESPACE') == '1':
    probe = subprocess.run([sys.executable, '-I', '-c', '''
import socket
assert [name for _, name in socket.if_nameindex()] == ['lo']
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    s.connect(('192.0.2.1', 9))
except OSError:
    pass
else:
    raise SystemExit('Unexpected route to an external address')
finally:
    s.close()
'''], capture_output=True, text=True, timeout=5)
    assert probe.returncode == 0, 'Collection-time OS namespace probe failed'


def test_child_process_network_namespace():
    if os.environ.get('MARKETEDGEPROS_NETWORK_NAMESPACE') != '1':
        pytest.skip('OS isolation proof requires scripts/run_security_tests.py')
    assert probe.returncode == 0
