#!/usr/bin/env python3
"""Run the opt-in PostgreSQL/Redis staging suite in an isolated Linux net namespace.

This runner deliberately does not use the normal testing application factory: that
factory correctly rejects Unix-socket PostgreSQL and Redis for ordinary test runs.
Here those sockets are permitted only after the process has entered a fresh network
namespace and only when they live in a runner-created, mode-0700 directory.

Usage (isolated virtual environment with requirements-security.lock installed):
    .venv/bin/python backend/scripts/run_staging_integration.py

No service is bound to TCP.  PostgreSQL and Redis are started as ``ubuntu`` inside
an ephemeral directory and are stopped and deleted in a ``finally`` block.
"""
from __future__ import annotations

import argparse
import configparser
import os
import pwd
from pathlib import Path
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from urllib.parse import quote


BACKEND = Path(__file__).resolve().parents[1]
SUITE = BACKEND / "staging_tests"
CLEAN_PYTHON = Path(sys.executable).absolute()
PG_BIN = Path("/usr/lib/postgresql/18/bin")
PG_PORT = "55432"  # Name is private because every run has its own socket directory.
MAX_SUBPROCESS_SECONDS = 480

# The outer process intentionally passes only these variables to the namespace.
# In particular DATABASE_URL, REDIS_URL, cloud/provider keys, and .env loading are
# absent before any application module can be imported.
INNER_ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": "/tmp",
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "FLASK_TESTING": "true",
    "FLASK_ENV": "testing",
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
    "MARKETEDGEPROS_STAGING_INNER": "1",
}


def _run(command: list[str], *, env: dict[str, str], timeout: int, cwd: Path = BACKEND,
         capture: bool = False) -> subprocess.CompletedProcess[str]:
    """Run a bounded child process without inheriting the caller's environment."""
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        timeout=timeout,
        check=False,
    )


def _require_clean_python() -> None:
    if sys.prefix == sys.base_prefix:
        raise RuntimeError('Run with an isolated virtual environment, not system Python')
    if not CLEAN_PYTHON.is_file():
        raise RuntimeError(f"Required clean interpreter is unavailable: {CLEAN_PYTHON}")


def _assert_inner_namespace() -> None:
    """Fail closed unless this is the unprivileged process in the fresh net namespace."""
    if os.environ.get("MARKETEDGEPROS_STAGING_INNER") != "1":
        raise RuntimeError("Inner runner marker is absent")
    if os.geteuid() == 0:
        raise RuntimeError("PostgreSQL/Redis must never run as root")
    interfaces = [name for _, name in socket.if_nameindex()]
    if interfaces != ["lo"]:
        raise RuntimeError(f"Expected a fresh network namespace with only lo, found {interfaces!r}")
    # A new net namespace leaves lo down.  In addition to checking its sole
    # interface, prove that an RFC-5737 external address has no route.
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.settimeout(0.25)
    try:
        try:
            probe.connect(("192.0.2.1", 9))
        except OSError:
            pass
        else:
            raise RuntimeError("Unexpected route to an external TCP address")
    finally:
        probe.close()
    # No process in this namespace may listen on TCP.  Unix-domain entries are
    # intentionally not examined because they are the only allowed transports.
    for proc_file in ("/proc/net/tcp", "/proc/net/tcp6"):
        lines = Path(proc_file).read_text(encoding="ascii").splitlines()[1:]
        if any(line.split()[3] == "0A" for line in lines if len(line.split()) >= 4):
            raise RuntimeError(f"TCP listener unexpectedly present in {proc_file}")


def _safe_rmtree(path: Path | None) -> None:
    """Delete only a path created by this runner directly under the system temp dir."""
    if path is None or not path.exists():
        return
    temp_parent = Path(tempfile.gettempdir()).resolve()
    resolved = path.resolve()
    if (
        resolved.parent != temp_parent
        or not resolved.name.startswith("marketedgepros-staging-")
        or resolved.stat().st_uid != os.geteuid()
    ):
        raise RuntimeError(f"Refusing to remove non-runner path: {resolved}")
    shutil.rmtree(resolved)


def _wait_for_socket(path: Path, *, timeout: float, label: str) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if stat.S_ISSOCK(path.stat().st_mode):
                return
        except FileNotFoundError:
            pass
        time.sleep(0.05)
    raise RuntimeError(f"{label} did not create its Unix socket within {timeout}s")


def _start_postgres(root: Path, env: dict[str, str]) -> tuple[Path, Path, str, str]:
    runtime_user = env.get("STAGING_RUNTIME_USER")
    if not runtime_user:
        raise RuntimeError("STAGING_RUNTIME_USER is required for the isolated PostgreSQL cluster")
    for binary in ("initdb", "pg_ctl", "createdb"):
        if not (PG_BIN / binary).is_file():
            raise RuntimeError(f"PostgreSQL 18 binary is required: {PG_BIN / binary}")
    data_dir = root / "pgdata"
    socket_dir = root / "pgsocket"
    socket_dir.mkdir(mode=0o700)
    os.chmod(socket_dir, 0o700)
    init = _run(
        [str(PG_BIN / "initdb"), "-D", str(data_dir), "--username", runtime_user,
         "--auth", "trust", "--encoding", "UTF8", "--no-locale"],
        env=env,
        timeout=60,
        capture=True,
    )
    if init.returncode:
        raise RuntimeError(f"initdb failed:\n{init.stdout[-4000:]}")
    options = (
        f"-k {socket_dir} -p {PG_PORT} -c listen_addresses='' "
        "-c unix_socket_permissions=0700 -c fsync=off -c synchronous_commit=off"
    )
    start = _run(
        [str(PG_BIN / "pg_ctl"), "-D", str(data_dir), "-l", str(root / "postgres.log"),
         "-o", options, "-w", "-t", "30", "start"],
        env=env,
        timeout=45,
        capture=True,
    )
    if start.returncode:
        raise RuntimeError(f"pg_ctl start failed:\n{start.stdout[-4000:]}")
    pg_socket = socket_dir / f".s.PGSQL.{PG_PORT}"
    _wait_for_socket(pg_socket, timeout=5, label="PostgreSQL")
    db_name = f"marketedgepros_test_{uuid.uuid4().hex}"
    createdb = _run(
        [str(PG_BIN / "createdb"), "-h", str(socket_dir), "-p", PG_PORT,
         "-O", runtime_user, db_name],
        env=env,
        timeout=30,
        capture=True,
    )
    if createdb.returncode:
        raise RuntimeError(f"createdb failed:\n{createdb.stdout[-4000:]}")
    # No hostname is present.  libpq uses the explicitly validated private socket
    # query value instead of any TCP address.
    pg_url = f"postgresql+psycopg2://{quote(runtime_user, safe='')}@/{db_name}?host={socket_dir}&port={PG_PORT}"
    return data_dir, socket_dir, db_name, pg_url


def _start_redis(root: Path, env: dict[str, str]) -> tuple[subprocess.Popen[str], Path, str]:
    redis_server = shutil.which("redis-server", path=env["PATH"])
    if not redis_server:
        raise RuntimeError(
            "redis-server is required. Install the local package (for example: "
            "sudo apt-get update && sudo apt-get install -y redis-server) and retry."
        )
    socket_path = root / "redis.sock"
    process = subprocess.Popen(
        [redis_server, "--port", "0", "--unixsocket", str(socket_path),
         "--unixsocketperm", "700", "--save", "", "--appendonly", "no",
         "--protected-mode", "yes", "--daemonize", "no"],
        cwd=BACKEND,
        env=env,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_for_socket(socket_path, timeout=15, label="Redis")
    except Exception:
        process.kill()
        process.wait(timeout=5)
        stderr = process.stderr.read() if process.stderr else ""
        raise RuntimeError(f"Redis failed to start: {stderr[-4000:]}")
    return process, socket_path, f"unix://{socket_path}?db=0"


def _run_offline_migration_inventory(root: Path, env: dict[str, str], pg_url: str) -> int:
    """Generate Alembic SQL only; never invoke an online migration connection."""
    original = BACKEND / "migrations" / "alembic.ini"
    parser = configparser.ConfigParser()
    parser.read(original)
    parser["alembic"]["script_location"] = str(BACKEND / "migrations")
    parser["alembic"]["sqlalchemy.url"] = pg_url
    config_path = root / "offline-alembic.ini"
    with config_path.open("w", encoding="utf-8") as config_file:
        parser.write(config_file)
    migration_env = dict(env)
    migration_env["TEST_DATABASE_URL"] = pg_url
    command = [str(CLEAN_PYTHON), "-m", "alembic", "-c", str(config_path), "upgrade", "heads", "--sql"]
    result = _run(command, env=migration_env, timeout=90, capture=True)
    status = "PASS" if result.returncode == 0 else "BLOCKED"
    print(f"OFFLINE_MIGRATION_SQL_{status}: returncode={result.returncode}", flush=True)
    if result.returncode:
        # This text is intentionally bounded and contains only source/migration
        # diagnostics; the synthetic cluster has no user or production records.
        print(result.stdout[-4000:], file=sys.stderr, flush=True)
    return result.returncode


def _stop_postgres(data_dir: Path | None, env: dict[str, str]) -> None:
    if data_dir is None or not data_dir.exists():
        return
    try:
        _run(
            [str(PG_BIN / "pg_ctl"), "-D", str(data_dir), "-m", "immediate", "-w", "-t", "30", "stop"],
            env=env,
            timeout=45,
            capture=True,
        )
    except (OSError, subprocess.SubprocessError):
        pass


def _stop_redis(process: subprocess.Popen[str] | None) -> None:
    if process is None:
        return
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _inner_main(pytest_args: list[str]) -> int:
    _require_clean_python()
    _assert_inner_namespace()
    root: Path | None = None
    data_dir: Path | None = None
    redis_process: subprocess.Popen[str] | None = None
    env = dict(INNER_ENV)
    runtime_user = os.environ.get("STAGING_RUNTIME_USER")
    runtime_uid_value = os.environ.get("STAGING_RUNTIME_UID")
    if not runtime_user or not runtime_uid_value:
        raise RuntimeError("Outer runner did not provide STAGING_RUNTIME_USER and STAGING_RUNTIME_UID")
    try:
        runtime_uid = int(runtime_uid_value)
    except ValueError as exc:
        raise RuntimeError("STAGING_RUNTIME_UID must be an integer") from exc
    if os.getuid() != runtime_uid or os.geteuid() != runtime_uid:
        raise RuntimeError("Inner runner UID does not match STAGING_RUNTIME_UID")
    if pwd.getpwuid(runtime_uid).pw_name != runtime_user:
        raise RuntimeError("STAGING_RUNTIME_USER does not map to STAGING_RUNTIME_UID")
    env["STAGING_RUNTIME_USER"] = runtime_user
    env["STAGING_RUNTIME_UID"] = str(runtime_uid)
    try:
        root = Path(tempfile.mkdtemp(prefix="marketedgepros-staging-"))
        os.chmod(root, 0o700)
        # Register cleanup before any start call can partially succeed.
        data_dir = root / 'pgdata'
        data_dir, pg_socket, db_name, pg_url = _start_postgres(root, env)
        redis_process, redis_socket, redis_url = _start_redis(root, env)
        env.update({
            "PYTHONPATH": str(BACKEND),
            "STAGING_RUN_ROOT": str(root),
            "STAGING_DATABASE_NAME": db_name,
            "STAGING_PG_SOCKET": str(pg_socket),
            "STAGING_PG_PORT": PG_PORT,
            "STAGING_PG_URL": pg_url,
            "STAGING_REDIS_SOCKET": str(redis_socket),
            "STAGING_REDIS_URL": redis_url,
        })
        migration_rc = _run_offline_migration_inventory(root, env, pg_url)
        pytest_command = [
            str(CLEAN_PYTHON), "-m", "pytest", "-q", "--disable-warnings",
            "-c", str(SUITE / "pytest.ini"), "--confcutdir=" + str(SUITE),
            "--basetemp=" + str(root / "pytest"),
            str(SUITE), *pytest_args,
        ]
        test_result = _run(pytest_command, env=env, timeout=MAX_SUBPROCESS_SECONDS)
        if test_result.returncode:
            return test_result.returncode
        # A test pass does not hide an offline Alembic blocker.  The runner is
        # still safe, and callers receive a distinct status for report triage.
        return 3 if migration_rc else 0
    except subprocess.TimeoutExpired as exc:
        print(f"STAGING_RUN_TIMEOUT: {exc}", file=sys.stderr)
        return 124
    finally:
        _stop_redis(redis_process)
        _stop_postgres(data_dir, env)
        _safe_rmtree(root)


def _outer_main(pytest_args: list[str]) -> int:
    _require_clean_python()
    if os.geteuid() == 0:
        raise RuntimeError("Invoke as an unprivileged user; the runner uses sudo only for unshare")
    unshare = shutil.which("unshare")
    runuser = shutil.which("runuser")
    sudo = shutil.which("sudo")
    if not all((unshare, runuser, sudo)):
        raise RuntimeError("sudo, unshare, and runuser are required for the isolated runner")
    # Root is used only for CLONE_NEWNET.  runuser immediately drops to the
    # invoking unprivileged account, so initdb and daemons have no root mapping.
    runtime_uid = os.getuid()
    runtime_user = pwd.getpwuid(runtime_uid).pw_name
    command = [
        sudo, "-n", unshare, "--net", "--fork", "--kill-child", "--mount-proc", "--",
        runuser, "-u", runtime_user, "--", "/usr/bin/env", "-i",
        *[f"{key}={value}" for key, value in INNER_ENV.items()],
        f"STAGING_RUNTIME_USER={runtime_user}",
        f"STAGING_RUNTIME_UID={runtime_uid}",
        str(CLEAN_PYTHON), str(Path(__file__).resolve()), "--inner", *pytest_args,
    ]
    result = subprocess.run(command, cwd=BACKEND, timeout=MAX_SUBPROCESS_SECONDS + 180)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inner", action="store_true", help=argparse.SUPPRESS)
    args, pytest_args = parser.parse_known_args()
    if args.inner:
        return _inner_main(pytest_args)
    return _outer_main(pytest_args)


if __name__ == "__main__":
    raise SystemExit(main())
