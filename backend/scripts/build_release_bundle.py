#!/usr/bin/env python3
"""Create a deterministic, auditable MarketEdgePros release bundle.

This program packages an already-built ``frontend/dist`` and tracked source only.  It
never invokes npm, pnpm, pip, or a deployment command.  Operators must prepare the
frontend separately with Node 22 and a frozen pnpm install before running it.
"""
from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from typing import Iterable, Sequence
from urllib.parse import unquote, urlsplit


class BundleError(RuntimeError):
    """A release input violates a bundle safety or reproducibility contract."""


FORMAT = "marketedgepros.release-bundle.v1"
ROUTE_MANIFEST = PurePosixPath("frontend/public/manus-routes.json")
DIST_ROUTE_MANIFEST = PurePosixPath("frontend/dist/manus-routes.json")
DIST_PREFIX = PurePosixPath("frontend/dist")
BUILD_PROVENANCE_NAME = "build-provenance.json"
BUILD_PROVENANCE_FORMAT = "marketedgepros.frontend-build-provenance.v1"
BUILD_METADATA = {
    "install_command": ["pnpm", "install", "--frozen-lockfile"],
    "command": ["pnpm", "build"],
    "environment": {"VITE_DEMO_RELEASE": "true"},
}
REQUIRED_RELEASE_INPUTS = (
    "backend/deploy/nginx-site.conf.template",
    "backend/requirements.txt",
    "backend/requirements-runtime.in",
    "backend/requirements-runtime.lock",
    "backend/deploy/wsgi.py",
    "backend/deploy/gunicorn.conf.py",
    "backend/deploy/marketedgepros-demo.service.template",
    "frontend/package.json",
    "frontend/pnpm-lock.yaml",
)
_HASHED_ASSET = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*-[A-Za-z0-9_-]{8,}\.[A-Za-z0-9]+(?:\.(?:br|gz))?$"
)
_ENVIRONMENT_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class _AssetReferenceParser(HTMLParser):
    """Collect the local JavaScript and stylesheet references in the document shell."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in {"script", "link"}:
            return
        values = {name.lower(): value for name, value in attrs}
        candidate = values.get("src") if tag == "script" else values.get("href")
        if candidate is None:
            return
        path = urlsplit(candidate).path.lower()
        if path.endswith((".js", ".mjs", ".css")):
            self.references.append(candidate)


def _run_git(repo_root: Path, *arguments: str) -> bytes:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=repo_root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as error:
        raise BundleError("git is required to create a release bundle") from error
    except subprocess.CalledProcessError as error:
        message = error.stderr.decode("utf-8", "replace").strip()
        raise BundleError(f"git validation failed: {message or 'command failed'}") from error
    return completed.stdout


def _assert_clean_tree(repo_root: Path) -> None:
    status = _run_git(repo_root, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise BundleError("source tree is not clean; commit or remove all changes before bundling")


def _git_sha(repo_root: Path) -> str:
    sha = _run_git(repo_root, "rev-parse", "HEAD").decode("ascii", "strict").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise BundleError("source git SHA is invalid")
    return sha


def _tracked_paths(repo_root: Path) -> list[PurePosixPath]:
    raw_paths = _run_git(repo_root, "ls-files", "-z")
    entries = [entry for entry in raw_paths.decode("utf-8", "strict").split("\0") if entry]
    paths = [PurePosixPath(entry) for entry in entries]
    if not paths:
        raise BundleError("source tree has no tracked files")
    for path in paths:
        if path.is_absolute() or ".." in path.parts or path.parts[0] == ".git":
            raise BundleError("tracked file path is unsafe")
    return sorted(paths, key=lambda path: path.as_posix())


def _assert_no_tracked_symlinks(repo_root: Path) -> None:
    output = _run_git(repo_root, "ls-files", "-s")
    for line in output.decode("utf-8", "strict").splitlines():
        if line.startswith("120000 "):
            raise BundleError("tracked symlinks are not permitted in a release bundle")


def _is_safe_env_example(name: str) -> bool:
    lowered = name.lower()
    return lowered in {".env.example", "env.example"} or lowered.endswith(".env.example")


def _is_environment_file(name: str) -> bool:
    lowered = name.lower()
    if _is_safe_env_example(lowered):
        return False
    return (
        lowered in {".env", "env"}
        or lowered.startswith(".env.")
        or lowered.endswith(".env")
        or ".env." in lowered
    )


def _excluded_category(path: PurePosixPath) -> str | None:
    parts = tuple(part.lower() for part in path.parts)
    name = parts[-1]
    if path == DIST_PREFIX or path.is_relative_to(DIST_PREFIX):
        return "frontend_build_replaced"
    if any("backup" in part for part in parts):
        return "source_backup"
    if any(
        part in {"auth-data", "auth_data"}
        or part.startswith("auth-data.")
        or part.startswith("auth_data.")
        for part in parts
    ):
        return "auth_data"
    if _is_environment_file(name):
        return "environment"
    return None


def _assert_required_inputs(tracked: Iterable[PurePosixPath]) -> None:
    tracked_set = {path.as_posix() for path in tracked}
    missing = [path for path in REQUIRED_RELEASE_INPUTS if path not in tracked_set]
    if missing:
        raise BundleError("required release input is not tracked: " + ", ".join(missing))


def _assert_regular_file(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as error:
        raise BundleError("release input disappeared during validation") from error
    if stat.S_ISLNK(mode):
        raise BundleError("symlinks are not permitted in a release bundle")
    if not stat.S_ISREG(mode):
        raise BundleError("release bundle inputs must be regular files")


def _assert_directory_not_symlink(path: Path, label: str) -> None:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as error:
        raise BundleError(f"{label} does not exist") from error
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise BundleError(f"{label} must be a real directory, not a symlink")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def frontend_source_hashes(
    repo_root: Path, tracked: Iterable[PurePosixPath] | None = None
) -> dict[str, str]:
    """Return hashes for every releasable tracked frontend source file.

    Generated dist files, environment files, and backup material are deliberately
    excluded even if a historical commit tracked them.  The returned path keys are
    repository-relative POSIX paths so they can be written directly to JSON.
    """
    selected = _tracked_paths(repo_root) if tracked is None else tracked
    hashes: dict[str, str] = {}
    for tracked_path in sorted(selected, key=lambda path: path.as_posix()):
        if not tracked_path.parts or tracked_path.parts[0] != "frontend":
            continue
        if _excluded_category(tracked_path):
            continue
        source = repo_root.joinpath(*tracked_path.parts)
        _assert_regular_file(source)
        hashes[tracked_path.as_posix()] = _sha256(source)
    if not hashes:
        raise BundleError("no releasable tracked frontend source files were found")
    return hashes


def dist_file_hashes(dist: Path) -> dict[str, str]:
    """Hash every built file except mutable provenance and release metadata."""
    ignored = {BUILD_PROVENANCE_NAME, "release.json"}
    hashes: dict[str, str] = {}
    for source, archive_path in _collect_dist_files(dist):
        relative = archive_path.relative_to(DIST_PREFIX)
        if relative.as_posix() in ignored:
            continue
        hashes[relative.as_posix()] = _sha256(source)
    return hashes


def build_provenance_payload(
    repo_root: Path, tracked: Iterable[PurePosixPath] | None = None
) -> dict[str, object]:
    """Create, but do not write, provenance for an already completed frontend build."""
    repo_root = repo_root.expanduser().resolve()
    selected = _tracked_paths(repo_root) if tracked is None else list(tracked)
    lock_path = repo_root / "frontend/pnpm-lock.yaml"
    route_manifest = repo_root / "frontend/dist/manus-routes.json"
    _assert_regular_file(lock_path)
    _assert_regular_file(route_manifest)
    return {
        "format": BUILD_PROVENANCE_FORMAT,
        "git_sha": _git_sha(repo_root),
        "frontend_source_hashes": frontend_source_hashes(repo_root, selected),
        "lock_hash": _sha256(lock_path),
        "build": BUILD_METADATA,
        "route_manifest_hash": _sha256(route_manifest),
        "dist_hashes": dist_file_hashes(repo_root / DIST_PREFIX),
    }


def write_build_provenance(
    repo_root: Path, tracked: Iterable[PurePosixPath] | None = None
) -> Path:
    """Write deterministic build provenance; exposed for isolated fixture creation."""
    repo_root = repo_root.expanduser().resolve()
    destination = repo_root / DIST_PREFIX / BUILD_PROVENANCE_NAME
    payload = build_provenance_payload(repo_root, tracked)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def _file_record(path: Path, archive_path: PurePosixPath, category: str) -> dict[str, object]:
    _assert_regular_file(path)
    return {
        "path": archive_path.as_posix(),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
        "category": category,
    }


def _collect_dist_files(dist: Path) -> list[tuple[Path, PurePosixPath]]:
    _assert_directory_not_symlink(dist, "frontend/dist")
    results: list[tuple[Path, PurePosixPath]] = []
    for candidate in sorted(dist.rglob("*"), key=lambda value: value.relative_to(dist).as_posix()):
        rel = PurePosixPath(candidate.relative_to(dist).as_posix())
        mode = candidate.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise BundleError("symlinks are not permitted in frontend/dist")
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise BundleError("frontend/dist contains a non-regular file")
        if candidate.name.lower().endswith(".map") or ".map." in candidate.name.lower():
            raise BundleError("source maps are not permitted in frontend/dist")
        if _is_environment_file(candidate.name):
            raise BundleError("environment files are not permitted in frontend/dist")
        results.append((candidate, PurePosixPath("frontend/dist") / rel))
    if not results:
        raise BundleError("frontend/dist is empty")
    return results


def _read_route_manifest(path: Path) -> dict[str, object]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BundleError("route manifest is not valid UTF-8 JSON") from error
    routes = manifest.get("routes") if isinstance(manifest, dict) else None
    if not isinstance(routes, list):
        raise BundleError("route manifest must contain a routes list")
    for route in routes:
        if not isinstance(route, dict) or not isinstance(route.get("path"), str):
            raise BundleError("route manifest contains an invalid route")
        # The published manifest describes pages only; a wildcard would be a 404 route.
        if "*" in route["path"]:
            raise BundleError("route manifest must not include a wildcard or 404 route")
    return manifest


def _validate_route_manifests(repo_root: Path, dist: Path) -> dict[str, object]:
    source_manifest = repo_root / ROUTE_MANIFEST
    built_manifest = dist / "manus-routes.json"
    _assert_regular_file(source_manifest)
    _assert_regular_file(built_manifest)
    # Validate both complete manifests.  Equality alone would otherwise describe a
    # matching but invalid wildcard/404 manifest as a valid release artifact.
    _read_route_manifest(source_manifest)
    if source_manifest.read_bytes() != built_manifest.read_bytes():
        raise BundleError("public and built route manifests do not match exactly")
    return _read_route_manifest(built_manifest)


def _read_build_provenance(path: Path) -> dict[str, object]:
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError as error:
        raise BundleError("frontend build provenance is missing") from error
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise BundleError("frontend build provenance must be a regular file")
    try:
        provenance = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BundleError("frontend build provenance is not valid UTF-8 JSON") from error
    if not isinstance(provenance, dict):
        raise BundleError("frontend build provenance must be a JSON object")
    return provenance


def _validate_build_provenance(
    repo_root: Path,
    dist: Path,
    sha: str,
    tracked: Iterable[PurePosixPath],
) -> None:
    """Bind ignored dist bytes to the current immutable frontend source snapshot."""
    provenance = _read_build_provenance(dist / BUILD_PROVENANCE_NAME)
    if provenance.get("format") != BUILD_PROVENANCE_FORMAT:
        raise BundleError("frontend build provenance format is invalid")
    if provenance.get("git_sha") != sha:
        raise BundleError("frontend build provenance git SHA does not match source")

    expected_sources = frontend_source_hashes(repo_root, tracked)
    if provenance.get("frontend_source_hashes") != expected_sources:
        raise BundleError("frontend build provenance source hashes do not match source")

    lock_path = repo_root / "frontend/pnpm-lock.yaml"
    _assert_regular_file(lock_path)
    if provenance.get("lock_hash") != _sha256(lock_path):
        raise BundleError("frontend build provenance lock hash does not match source")
    if provenance.get("build") != BUILD_METADATA:
        raise BundleError("frontend build provenance build metadata is invalid")

    route_manifest = dist / "manus-routes.json"
    _assert_regular_file(route_manifest)
    if provenance.get("route_manifest_hash") != _sha256(route_manifest):
        raise BundleError("frontend build provenance route manifest hash does not match dist")
    if provenance.get("dist_hashes") != dist_file_hashes(dist):
        raise BundleError("frontend build provenance dist hashes do not match dist")


def _local_asset_path(dist: Path, reference: str) -> Path:
    parsed = urlsplit(reference)
    if parsed.scheme or parsed.netloc or parsed.path.startswith("//"):
        raise BundleError("index HTML must use local JavaScript and CSS assets")
    decoded = unquote(parsed.path)
    relative = PurePosixPath(decoded.lstrip("/"))
    if not decoded or relative.is_absolute() or ".." in relative.parts:
        raise BundleError("index HTML contains an unsafe asset path")
    if not relative.parts or relative.parts[0] != "assets":
        raise BundleError("index HTML JavaScript and CSS assets must be hashed Vite assets")
    return dist.joinpath(*relative.parts)


def _validate_index_assets(dist: Path) -> None:
    index = dist / "index.html"
    _assert_regular_file(index)
    parser = _AssetReferenceParser()
    try:
        parser.feed(index.read_text(encoding="utf-8"))
        parser.close()
    except UnicodeDecodeError as error:
        raise BundleError("frontend/dist/index.html is not valid UTF-8") from error
    if not parser.references:
        raise BundleError("frontend/dist/index.html has no JavaScript or CSS asset references")
    for reference in parser.references:
        candidate = _local_asset_path(dist, reference)
        _assert_regular_file(candidate)
        if not _HASHED_ASSET.fullmatch(candidate.name):
            raise BundleError("index HTML references a non-hashed JavaScript or CSS asset")


def _validate_asset_names(dist_files: Iterable[tuple[Path, PurePosixPath]]) -> None:
    for _, archive_path in dist_files:
        relative = archive_path.relative_to(DIST_PREFIX)
        if relative.parts and relative.parts[0] == "assets" and not _HASHED_ASSET.fullmatch(relative.name):
            raise BundleError("frontend/dist/assets contains a non-hashed asset")


def _scan_static_files_for_secrets(
    dist_files: Iterable[tuple[Path, PurePosixPath]], secret_values: Sequence[bytes]
) -> None:
    needles = tuple(value for value in secret_values if value)
    if not needles:
        return
    for path, _ in dist_files:
        with path.open("rb") as handle:
            data = handle.read()
        if any(secret in data for secret in needles):
            # Do not expose a value, variable name, or matching file in console output.
            raise BundleError("static content matched a configured secret value")


def _safe_output_directory(repo_root: Path, output_dir: Path) -> Path:
    resolved_repo = repo_root.resolve()
    resolved_output = output_dir.expanduser().resolve()
    try:
        resolved_output.relative_to(resolved_repo)
    except ValueError:
        return resolved_output
    raise BundleError("output directory must be outside the source repository")


def _tar_add_file(archive: tarfile.TarFile, source: Path, archive_path: PurePosixPath) -> None:
    _assert_regular_file(source)
    source_mode = source.stat().st_mode
    info = tarfile.TarInfo(archive_path.as_posix())
    info.size = source.stat().st_size
    info.mode = 0o755 if source_mode & 0o111 else 0o644
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    with source.open("rb") as handle:
        archive.addfile(info, handle)


def _tar_add_bytes(archive: tarfile.TarFile, payload: bytes, archive_path: PurePosixPath) -> None:
    import io

    info = tarfile.TarInfo(archive_path.as_posix())
    info.size = len(payload)
    info.mode = 0o644
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    archive.addfile(info, io.BytesIO(payload))


def _release_json(sha: str) -> bytes:
    return json.dumps({"git_sha": sha}, sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"


def build_release_bundle(
    repo_root: Path,
    output_dir: Path,
    *,
    secret_values: Sequence[bytes] = (),
) -> dict[str, object]:
    """Validate immutable inputs and write a tar plus external JSON sidecar manifest."""
    repo_root = repo_root.expanduser().resolve()
    if not (repo_root / ".git").exists():
        raise BundleError("repository root does not contain a git work tree")
    output_dir = _safe_output_directory(repo_root, output_dir)
    _assert_clean_tree(repo_root)
    sha = _git_sha(repo_root)
    tracked = _tracked_paths(repo_root)
    _assert_no_tracked_symlinks(repo_root)
    _assert_required_inputs(tracked)

    source_files: list[tuple[Path, PurePosixPath]] = []
    excluded: list[dict[str, str]] = []
    for tracked_path in tracked:
        category = _excluded_category(tracked_path)
        if category:
            excluded.append({"path": tracked_path.as_posix(), "category": category})
            continue
        source = repo_root.joinpath(*tracked_path.parts)
        _assert_regular_file(source)
        source_files.append((source, tracked_path))

    dist = repo_root / DIST_PREFIX
    _validate_build_provenance(repo_root, dist, sha, tracked)
    routes = _validate_route_manifests(repo_root, dist)
    dist_files = _collect_dist_files(dist)
    _validate_index_assets(dist)
    _validate_asset_names(dist_files)
    _scan_static_files_for_secrets(dist_files, secret_values)

    release_json_path = PurePosixPath("frontend/dist/release.json")
    release_payload = _release_json(sha)
    entries = [
        _file_record(source, archive_path, "source") for source, archive_path in source_files
    ]
    entries.extend(
        _file_record(source, archive_path, "frontend_build")
        for source, archive_path in dist_files
    )
    entries.append(
        {
            "path": release_json_path.as_posix(),
            "bytes": len(release_payload),
            "sha256": hashlib.sha256(release_payload).hexdigest(),
            "category": "release_metadata",
        }
    )
    entries.sort(key=lambda entry: str(entry["path"]))
    if len({str(entry["path"]) for entry in entries}) != len(entries):
        raise BundleError("release archive would contain duplicate paths")

    output_dir.mkdir(parents=True, exist_ok=True)
    archive_name = f"marketedgepros-release-{sha}.tar"
    manifest_name = f"marketedgepros-release-{sha}.manifest.json"
    archive_path = output_dir / archive_name
    manifest_path = output_dir / manifest_name

    with tempfile.TemporaryDirectory(prefix=".release-bundle-", dir=output_dir) as temporary:
        temporary_dir = Path(temporary)
        pending_archive = temporary_dir / archive_name
        with tarfile.open(pending_archive, mode="w", format=tarfile.PAX_FORMAT) as archive:
            source_by_path = {archive_path: source for source, archive_path in source_files}
            dist_by_path = {archive_path: source for source, archive_path in dist_files}
            for entry in entries:
                archive_member = PurePosixPath(str(entry["path"]))
                if archive_member == release_json_path:
                    _tar_add_bytes(archive, release_payload, archive_member)
                elif archive_member in source_by_path:
                    _tar_add_file(archive, source_by_path[archive_member], archive_member)
                else:
                    _tar_add_file(archive, dist_by_path[archive_member], archive_member)
        archive_sha = _sha256(pending_archive)
        manifest = {
            "format": FORMAT,
            "git_sha": sha,
            "routes": routes["routes"],
            "archive": {
                "name": archive_name,
                "bytes": pending_archive.stat().st_size,
                "sha256": archive_sha,
            },
            "files": entries,
            "excluded_tracked_files": excluded,
        }
        pending_manifest = temporary_dir / manifest_name
        pending_manifest.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(pending_archive, archive_path)
        os.replace(pending_manifest, manifest_path)

    return {
        "archive": str(archive_path),
        "manifest": str(manifest_path),
        "git_sha": sha,
        "file_count": len(entries),
        "excluded_tracked_file_count": len(excluded),
    }


def _secret_values_from_environment(names: Sequence[str]) -> list[bytes]:
    values: list[bytes] = []
    for name in names:
        if not _ENVIRONMENT_NAME.fullmatch(name):
            raise BundleError("secret environment variable names must be valid identifiers")
        value = os.environ.get(name)
        if value:
            values.append(value.encode("utf-8"))
    return values


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Package a prebuilt frontend/dist and clean tracked source without running npm, pnpm, or pip."
        )
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        type=Path,
        help="Directory outside the source repository for the tar and sidecar manifest.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="Repository root (defaults to the repository containing this script).",
    )
    parser.add_argument(
        "--secret-env",
        action="append",
        default=[],
        metavar="NAME",
        help="Environment variable whose non-empty value must not appear in static build files; repeatable.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        result = build_release_bundle(
            args.repo_root,
            args.output_dir,
            secret_values=_secret_values_from_environment(args.secret_env),
        )
    except BundleError as error:
        print(f"release bundle refused: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
