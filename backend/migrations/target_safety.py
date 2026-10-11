"""Fail-closed target validation for isolated Alembic rehearsal only."""
from __future__ import annotations

import os
from pathlib import Path
import re
import socket
import stat
import tempfile
from typing import Mapping, Sequence

from sqlalchemy.engine import make_url


SYNTHETIC_DATABASE_RE = re.compile(r"marketedgepros_test_[0-9a-f]{32}\Z")


class IsolatedMigrationTargetError(RuntimeError):
    """Raised before Alembic can operate on a non-runner target in testing."""


def _tcp_listener_present() -> bool:
    for proc_file in ("/proc/net/tcp", "/proc/net/tcp6"):
        lines = Path(proc_file).read_text(encoding="ascii").splitlines()[1:]
        if any(line.split()[3] == "0A" for line in lines if len(line.split()) >= 4):
            return True
    return False


def validate_isolated_postgresql_target(
    database_url: str,
    *,
    environment: Mapping[str, str] | None = None,
    uid: int | None = None,
    interface_names: Sequence[str] | None = None,
    tcp_listener_present: bool | None = None,
) -> None:
    """Require a runner-created PostgreSQL Unix-socket target before migration.

    This validates identifiers and local resource ownership only; it performs no
    database connection.  Callers must still compare a supplied Connection with
    this URL before invoking Alembic.
    """
    env = os.environ if environment is None else environment
    required = ("STAGING_RUN_ROOT", "STAGING_PG_SOCKET", "STAGING_PG_PORT", "STAGING_RUNTIME_USER")
    missing = [name for name in required if not env.get(name)]
    if missing:
        raise IsolatedMigrationTargetError(
            f"Testing Alembic target lacks runner resource metadata: {', '.join(missing)}"
        )

    root = Path(env["STAGING_RUN_ROOT"]).resolve()
    socket_dir = Path(env["STAGING_PG_SOCKET"]).resolve()
    temp_parent = Path(tempfile.gettempdir()).resolve()
    expected_socket_dir = root / "pgsocket"
    target_uid = os.geteuid() if uid is None else uid
    if (
        root.parent != temp_parent
        or not root.name.startswith("marketedgepros-staging-")
        or not root.is_dir()
        or root.stat().st_uid != target_uid
        or stat.S_IMODE(root.stat().st_mode) != 0o700
    ):
        raise IsolatedMigrationTargetError("Testing Alembic target has an invalid runner root")
    if (
        socket_dir != expected_socket_dir
        or not socket_dir.is_dir()
        or socket_dir.stat().st_uid != target_uid
        or stat.S_IMODE(socket_dir.stat().st_mode) != 0o700
    ):
        raise IsolatedMigrationTargetError("Testing Alembic target has an invalid private socket directory")

    url = make_url(database_url)
    if url.get_backend_name() != "postgresql":
        raise IsolatedMigrationTargetError("Testing Alembic target must use PostgreSQL")
    if not url.database or not SYNTHETIC_DATABASE_RE.fullmatch(url.database):
        raise IsolatedMigrationTargetError("Testing Alembic target database is not a synthetic UUID database")
    if url.host is not None or url.password is not None:
        raise IsolatedMigrationTargetError("Testing Alembic target must not include a TCP host or password")
    if url.username != env["STAGING_RUNTIME_USER"]:
        raise IsolatedMigrationTargetError("Testing Alembic target user differs from runner runtime user")
    expected_query = {"host": str(socket_dir), "port": env["STAGING_PG_PORT"]}
    if dict(url.query) != expected_query:
        raise IsolatedMigrationTargetError("Testing Alembic target must use the runner private Unix socket")

    actual_interfaces = list(interface_names) if interface_names is not None else [
        name for _, name in socket.if_nameindex()
    ]
    if actual_interfaces != ["lo"]:
        raise IsolatedMigrationTargetError("Testing Alembic target requires a fresh loopback-only namespace")
    tcp_listener = _tcp_listener_present() if tcp_listener_present is None else tcp_listener_present
    if tcp_listener:
        raise IsolatedMigrationTargetError("Testing Alembic target refuses a namespace with TCP listeners")
