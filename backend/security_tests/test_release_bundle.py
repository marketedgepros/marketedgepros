"""Focused tests for the offline, deterministic release bundle contract."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

import pytest


BACKEND = Path(__file__).resolve().parents[1]
SCRIPT = BACKEND / "scripts" / "build_release_bundle.py"
SPEC = importlib.util.spec_from_file_location("release_bundle", SCRIPT)
assert SPEC and SPEC.loader
release_bundle = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_bundle)


ROUTES = b'{"routes":[{"path":"/"},{"path":"/dashboard/:id"}]}\n'
INDEX = """<!doctype html><html><head>
<script type=\"module\" src=\"/assets/index-abcdefgh.js\"></script>
<link rel=\"stylesheet\" href=\"/assets/index-abcdefgh.css\">
</head><body><div id=\"root\"></div></body></html>\n"""


def _write(path: Path, data: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _commit_fixture_change(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)


@pytest.fixture
def release_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "source"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "security-tests@example.invalid")
    _git(repo, "config", "user.name", "Security Tests")

    _write(repo / "frontend/public/manus-routes.json", ROUTES)
    _write(repo / "frontend/.gitignore", "dist/\n")
    _write(repo / "frontend/pnpm-lock.yaml", "lockfileVersion: '9.0'\n")
    _write(repo / "frontend/package.json", '{"packageManager":"pnpm@11.25.0"}\n')
    _write(repo / "backend/requirements.txt", "Flask==3.0.0\n")
    _write(repo / "backend/requirements-runtime.in", "Flask==3.0.0\n")
    _write(repo / "backend/requirements-runtime.lock", "Flask==3.0.0 --hash=sha256:abc\n")
    _write(repo / "backend/deploy/nginx-site.conf.template", "server { return 444; }\n")
    _write(repo / "backend/deploy/wsgi.py", "app = object()\n")
    _write(repo / "backend/deploy/gunicorn.conf.py", "bind = '127.0.0.1:5001'\n")
    _write(repo / "backend/deploy/marketedgepros-demo.service.template", "[Service]\n")
    _write(repo / ".github/workflows/audit.yml", "name: audit\n")
    _write(repo / "docs/OPERATIONS.md", "release notes\n")
    _write(repo / "backend/src/app.py", "app = object()\n")
    _write(repo / "backend/.env.example", "EXAMPLE_ONLY=placeholder\n")
    _write(repo / "backend/backups/previous.py", "should_not_ship = True\n")
    _write(repo / "backend/auth-data/session.json", '{"not":"shipped"}\n')

    # The built files intentionally remain ignored and are not part of the SHA
    # being attested.  Synthetic provenance is written only after the source
    # commit, exactly as the production builder does after a real pnpm build.
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture source")

    _write(repo / "frontend/dist/manus-routes.json", ROUTES)
    _write(repo / "frontend/dist/index.html", INDEX)
    _write(repo / "frontend/dist/assets/index-abcdefgh.js", "console.log('entry')\n")
    _write(repo / "frontend/dist/assets/index-abcdefgh.css", "body{color:#111}\n")
    # A lazy chunk is preserved because the complete prebuilt dist is archived, not
    # guessed from page counts or entrypoint references.
    _write(repo / "frontend/dist/assets/Dashboard-abcdefgh.js", "export default {}\n")
    release_bundle.write_build_provenance(repo)
    return repo


def _manifest(result: dict[str, object]) -> dict[str, object]:
    return json.loads(Path(str(result["manifest"])).read_text(encoding="utf-8"))


def _refresh_provenance(repo: Path) -> Path:
    return release_bundle.write_build_provenance(repo)


def _provenance(repo: Path) -> dict[str, object]:
    return json.loads(
        (repo / "frontend/dist/build-provenance.json").read_text(encoding="utf-8")
    )


def _write_provenance(repo: Path, provenance: dict[str, object]) -> None:
    _write(
        repo / "frontend/dist/build-provenance.json",
        json.dumps(provenance, sort_keys=True, indent=2) + "\n",
    )


def test_bundle_contains_clean_source_full_dist_and_verified_hashes(release_repo: Path, tmp_path: Path):
    output = tmp_path / "output"
    result = release_bundle.build_release_bundle(release_repo, output)
    manifest = _manifest(result)
    archive = Path(str(result["archive"]))

    assert manifest["git_sha"] == _git_sha(release_repo)
    assert manifest["archive"]["sha256"] == _sha256(archive)
    paths = {entry["path"]: entry for entry in manifest["files"]}
    assert ".github/workflows/audit.yml" in paths
    assert "docs/OPERATIONS.md" in paths
    assert "frontend/dist/assets/Dashboard-abcdefgh.js" in paths
    assert "frontend/dist/build-provenance.json" in paths
    assert paths["frontend/dist/release.json"]["category"] == "release_metadata"
    assert json.loads(_member_bytes(archive, "frontend/dist/release.json")) == {
        "git_sha": _git_sha(release_repo)
    }
    assert _member_bytes(archive, "frontend/dist/assets/index-abcdefgh.js") == (
        release_repo / "frontend/dist/assets/index-abcdefgh.js"
    ).read_bytes()
    for path, entry in paths.items():
        assert hashlib.sha256(_member_bytes(archive, path)).hexdigest() == entry["sha256"]
        assert len(_member_bytes(archive, path)) == entry["bytes"]

    excluded = {entry["path"]: entry["category"] for entry in manifest["excluded_tracked_files"]}
    assert excluded["backend/backups/previous.py"] == "source_backup"
    assert excluded["backend/auth-data/session.json"] == "auth_data"
    assert "backend/.env.example" in paths
    assert "backend/backups/previous.py" not in paths
    assert "backend/auth-data/session.json" not in paths

    first_digest = _sha256(archive)
    second = release_bundle.build_release_bundle(release_repo, output)
    assert _sha256(Path(str(second["archive"]))) == first_digest


def test_bundle_refuses_dirty_source_tree(release_repo: Path, tmp_path: Path):
    _write(release_repo / "untracked.txt", "not clean\n")
    with pytest.raises(release_bundle.BundleError, match="not clean"):
        release_bundle.build_release_bundle(release_repo, tmp_path / "output")


def test_bundle_refuses_missing_build_provenance(release_repo: Path, tmp_path: Path):
    (release_repo / "frontend/dist/build-provenance.json").unlink()
    with pytest.raises(release_bundle.BundleError, match="provenance is missing"):
        release_bundle.build_release_bundle(release_repo, tmp_path / "output")


def test_bundle_refuses_provenance_with_wrong_source_sha(release_repo: Path, tmp_path: Path):
    provenance = _provenance(release_repo)
    provenance["git_sha"] = "0" * 40
    _write_provenance(release_repo, provenance)
    with pytest.raises(release_bundle.BundleError, match="git SHA"):
        release_bundle.build_release_bundle(release_repo, tmp_path / "output")


def test_bundle_refuses_changed_lazy_chunk_even_when_dist_is_ignored(
    release_repo: Path, tmp_path: Path
):
    _write(
        release_repo / "frontend/dist/assets/Dashboard-abcdefgh.js",
        "export default { stale: true }\n",
    )
    with pytest.raises(release_bundle.BundleError, match="dist hashes"):
        release_bundle.build_release_bundle(release_repo, tmp_path / "output")


def test_bundle_refuses_changed_lock_when_provenance_lock_hash_is_stale(
    release_repo: Path, tmp_path: Path
):
    provenance = _provenance(release_repo)
    _write(release_repo / "frontend/pnpm-lock.yaml", "lockfileVersion: '9.1'\n")
    _commit_fixture_change(release_repo, "changed lock")
    expected = release_bundle.build_provenance_payload(release_repo)
    provenance["git_sha"] = expected["git_sha"]
    provenance["frontend_source_hashes"] = expected["frontend_source_hashes"]
    _write_provenance(release_repo, provenance)
    with pytest.raises(release_bundle.BundleError, match="lock hash"):
        release_bundle.build_release_bundle(release_repo, tmp_path / "output")


@pytest.mark.parametrize(
    "required_path",
    (
        "backend/requirements-runtime.in",
        "backend/requirements-runtime.lock",
        "backend/deploy/wsgi.py",
        "backend/deploy/gunicorn.conf.py",
        "backend/deploy/marketedgepros-demo.service.template",
    ),
)
def test_bundle_requires_specific_runtime_and_deployment_inputs(
    release_repo: Path, tmp_path: Path, required_path: str
):
    (release_repo / required_path).unlink()
    _git(release_repo, "add", "-u")
    _git(release_repo, "commit", "-m", "remove required release input")
    with pytest.raises(release_bundle.BundleError, match=required_path):
        release_bundle.build_release_bundle(release_repo, tmp_path / "output")


def test_bundle_refuses_mismatched_route_manifest(release_repo: Path, tmp_path: Path):
    wildcard = b'{"routes":[{"path":"*"}]}\n'
    _write(release_repo / "frontend/public/manus-routes.json", wildcard)
    _commit_fixture_change(release_repo, "invalid wildcard route")
    _write(release_repo / "frontend/dist/manus-routes.json", wildcard)
    _refresh_provenance(release_repo)
    with pytest.raises(release_bundle.BundleError, match="wildcard"):
        release_bundle.build_release_bundle(release_repo, tmp_path / "output")


def test_bundle_refuses_configured_secret_without_echoing_it(release_repo: Path, tmp_path: Path):
    secret = b"do-not-print-this-release-secret"
    _write(release_repo / "frontend/dist/assets/Dashboard-abcdefgh.js", b"const token='" + secret + b"';\n")
    _refresh_provenance(release_repo)
    with pytest.raises(release_bundle.BundleError) as error:
        release_bundle.build_release_bundle(release_repo, tmp_path / "output", secret_values=[secret])
    assert "configured secret" in str(error.value)
    assert secret.decode("utf-8") not in str(error.value)


def test_bundle_refuses_missing_index_asset(release_repo: Path, tmp_path: Path):
    (release_repo / "frontend/dist/assets/index-abcdefgh.css").unlink()
    _refresh_provenance(release_repo)
    with pytest.raises(release_bundle.BundleError, match="disappeared"):
        release_bundle.build_release_bundle(release_repo, tmp_path / "output")


def test_nginx_template_has_canonical_api_and_spa_guards():
    template = (BACKEND / "deploy/nginx-site.conf.template").read_text(encoding="utf-8")
    assert "root @RELEASE_PATH@/frontend/dist;" in template
    assert "server 127.0.0.1:5001;" in template
    assert 'location ~ "^/assets/' in template
    assert 'location ~* "\\.[A-Za-z0-9]{1,16}$" {' in template
    assert "location ^~ /api/" in template
    assert "location = /health" in template
    assert "location ^~ /health/" in template
    assert "location = /api" in template
    assert "location = /release.json" in template
    assert "location /assets/" in template
    assert "proxy_connect_timeout 5s;" in template
    assert "proxy_send_timeout 35s;" in template
    assert "proxy_read_timeout 35s;" in template
    assert "try_files $uri =404;" in template
    assert 'add_header Cache-Control "no-store" always;' in template
    assert "try_files $uri $uri/ /index.html;" in template
    assert "location /auth" not in template
    assert "location /users" not in template


def _member_bytes(archive_path: Path, member: str) -> bytes:
    with tarfile.open(archive_path, "r") as archive:
        extracted = archive.extractfile(member)
        assert extracted is not None
        return extracted.read()


def _git_sha(repo: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
