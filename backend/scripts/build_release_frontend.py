#!/usr/bin/env python3
"""Build frontend/dist and bind it to the exact clean tracked frontend source.

This script is the only supported producer of ``frontend/dist/build-provenance.json``.
It deliberately does not deploy, package a backend, or read provider configuration.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Mapping, Sequence


SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))

from build_release_bundle import (  # noqa: E402
    BundleError,
    _assert_clean_tree,
    _git_sha,
    _tracked_paths,
    _validate_route_manifests,
    dist_file_hashes,
    frontend_source_hashes,
    write_build_provenance,
)


# A deliberately small allow-list is safer than attempting to enumerate every
# possible provider credential.  In particular, no inherited VITE_* value is
# allowed to reach Vite; this release intentionally exposes only the demo flag.
_SAFE_BUILD_ENVIRONMENT = ("PATH", "LANG", "LC_ALL", "LC_CTYPE", "TZ")


def sanitized_build_environment(
    inherited: Mapping[str, str] | None = None, *, home: Path | None = None
) -> dict[str, str]:
    """Return the non-secret environment passed to pnpm and Vite.

    ``inherited`` is accepted to make the security contract directly unit-testable.
    Only locale/path plumbing is retained.  A disposable HOME prevents user npm or
    pnpm configuration (including registry credentials) from influencing the build.
    """
    source = os.environ if inherited is None else inherited
    environment = {
        name: source[name]
        for name in _SAFE_BUILD_ENVIRONMENT
        if source.get(name)
    }
    if home is not None:
        environment["HOME"] = str(home)
    environment["VITE_DEMO_RELEASE"] = "true"
    return environment


def _remove_existing_dist(dist: Path) -> None:
    """Remove old ignored output without ever traversing a symlink."""
    try:
        mode = dist.lstat().st_mode
    except FileNotFoundError:
        return
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise BundleError("frontend/dist must be a real directory when it already exists")
    shutil.rmtree(dist)


def _run_pnpm(frontend: Path, arguments: Sequence[str], environment: Mapping[str, str]) -> None:
    try:
        subprocess.run(
            ["pnpm", *arguments],
            cwd=frontend,
            env=dict(environment),
            check=True,
        )
    except FileNotFoundError as error:
        raise BundleError("pnpm is required to build the frontend") from error
    except subprocess.CalledProcessError as error:
        raise BundleError("frontend pnpm command failed") from error


def _assert_sources_stable(
    repo_root: Path, expected_sha: str, expected_hashes: Mapping[str, str]
) -> None:
    if _git_sha(repo_root) != expected_sha:
        raise BundleError("git SHA changed while the frontend was building")
    current_hashes = frontend_source_hashes(repo_root, _tracked_paths(repo_root))
    if current_hashes != expected_hashes:
        raise BundleError("tracked frontend source changed while the frontend was building")
    # This catches changes outside frontend as well as modifications to tracked
    # frontend paths that disappeared between the two source snapshots.
    _assert_clean_tree(repo_root)


def build_release_frontend(repo_root: Path) -> dict[str, object]:
    """Build a clean release frontend and write its checked provenance record."""
    repo_root = repo_root.expanduser().resolve()
    if not (repo_root / ".git").exists():
        raise BundleError("repository root does not contain a git work tree")
    _assert_clean_tree(repo_root)

    tracked = _tracked_paths(repo_root)
    sha = _git_sha(repo_root)
    source_hashes = frontend_source_hashes(repo_root, tracked)
    frontend = repo_root / "frontend"
    dist = frontend / "dist"

    with tempfile.TemporaryDirectory(prefix="marketedgepros-frontend-home-") as temporary_home:
        environment = sanitized_build_environment(home=Path(temporary_home))
        _remove_existing_dist(dist)
        _run_pnpm(frontend, ("install", "--frozen-lockfile"), environment)
        _run_pnpm(frontend, ("build",), environment)

    _assert_sources_stable(repo_root, sha, source_hashes)
    # Confirm the complete source and emitted route lists are equal and contain no
    # wildcard/404 route before writing the evidence record.
    _validate_route_manifests(repo_root, dist)
    provenance = write_build_provenance(repo_root, tracked)
    _assert_sources_stable(repo_root, sha, source_hashes)

    return {
        "git_sha": sha,
        "provenance": str(provenance),
        "frontend_source_file_count": len(source_hashes),
        "dist_file_count": len(dist_file_hashes(dist)),
    }


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build frontend/dist from a clean source tree and write verified provenance."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root (defaults to the repository containing this script).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        result = build_release_frontend(args.repo_root)
    except BundleError as error:
        print(f"frontend release build refused: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
