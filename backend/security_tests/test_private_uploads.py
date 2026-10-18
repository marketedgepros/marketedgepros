"""Focused upload-download containment tests.

Run without the legacy backend/conftest.py or application factory:
    cd backend && ../.venv/bin/python -m pytest --confcutdir=security_tests \
        -c /dev/null -q security_tests/test_private_uploads.py

The fixture imports the actual uploads.py blueprint only.  FileService, token
helpers, and DB are import-time dependencies irrelevant to the GET route, so
they are minimal inert stubs; no configuration, database, or external service
is imported or contacted.
"""
import importlib.util
import sys
import uuid
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from flask import Flask, g, request


BACKEND_DIR = Path(__file__).resolve().parents[1]
UPLOADS_ROUTE = BACKEND_DIR / "src" / "routes" / "uploads.py"


def _package(name):
    package = ModuleType(name)
    package.__path__ = []
    return package


def _load_uploads_blueprint(monkeypatch):
    """Load the production route with only irrelevant import-time stubs."""
    src = _package("src")
    services = _package("src.services")
    utils = _package("src.utils")
    file_service = ModuleType("src.services.file_service")
    decorators = ModuleType("src.utils.decorators")
    database = ModuleType("src.database")

    class FileService:  # GET requests do not invoke this upload-only service.
        pass

    file_service.FileService = FileService
    decorators.token_required = lambda view: view
    database.db = SimpleNamespace(session=SimpleNamespace())

    for name, module in {
        "src": src,
        "src.services": services,
        "src.services.file_service": file_service,
        "src.utils": utils,
        "src.utils.decorators": decorators,
        "src.database": database,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    module_name = f"isolated_uploads_route_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(module_name, UPLOADS_ROUTE)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module.uploads_bp


@pytest.fixture
def app(tmp_path, monkeypatch):
    """A test-only Flask host for the actual generic GET route."""
    app = Flask(__name__)
    app.config.update(
        EXPANDED_HIERARCHY_ENABLED=True,
        TESTING=True,
        SECRET_KEY="upload-route-security-test-only",
        UPLOAD_FOLDER=str(tmp_path / "uploads"),
    )
    # Preserve malformed slash paths for the route instead of redirecting them.
    app.url_map.merge_slashes = False

    @app.before_request
    def install_fake_authenticated_user():
        role = request.headers.get("X-Test-Role")
        if role:
            g.current_user = SimpleNamespace(id=42, role=role)

    app.register_blueprint(
        _load_uploads_blueprint(monkeypatch),
        url_prefix="/api/v1/uploads",
    )
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def upload_root(app):
    root = Path(app.config["UPLOAD_FOLDER"])
    root.mkdir()
    return root


def _write(root, relative_path, contents):
    target = root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(contents)
    return target


def _assert_not_found(response, secret=b"private document"):
    assert response.status_code == 404
    assert secret not in response.data


def test_kyc_documents_are_denied_to_anonymous_and_fake_authenticated_users(
    client, upload_root
):
    """Role presence is not an ownership decision when metadata is absent."""
    _write(upload_root, "kyc/42/id_proof.pdf", b"private document")

    for headers in (
        {},
        {"X-Test-Role": "user"},
        {"X-Test-Role": "admin"},
    ):
        response = client.get(
            "/api/v1/uploads/kyc/42/id_proof.pdf", headers=headers
        )
        _assert_not_found(response)


def test_canonical_public_profile_images_and_tenant_logos_remain_available(
    client, upload_root
):
    """Cover both FileService and StorageService local profile conventions."""
    _write(upload_root, "profiles/profile_42.png", b"file-service-profile")
    _write(upload_root, "profiles/42/avatar.jpg", b"storage-service-profile")
    _write(upload_root, "tenants/7/logo.webp", b"tenant-logo")

    expected = {
        "/api/v1/uploads/profiles/profile_42.png": b"file-service-profile",
        "/api/v1/uploads/profiles/42/avatar.jpg": b"storage-service-profile",
        "/api/v1/uploads/tenants/7/logo.webp": b"tenant-logo",
    }
    for url, contents in expected.items():
        response = client.get(url)
        assert response.status_code == 200
        assert response.data == contents


@pytest.mark.parametrize(
    "url",
    [
        "/api/v1/uploads/documents/private.pdf",
        "/api/v1/uploads/KYC/42/id_proof.pdf",
        "/api/v1/uploads/kyc/42/id_proof.pdf",
        "/api/v1/uploads/unknown/private.png",
        "/api/v1/uploads/profiles/42/./avatar.jpg",
        "/api/v1/uploads/profiles/42/kyc/avatar.png",
        "/api/v1/uploads/tenants/7/kyc/logo.png",
        "/api/v1/uploads/profiles/profile_42.private.png",
        "/api/v1/uploads/profiles/42/avatar.private.jpg",
        "/api/v1/uploads/tenants/7/logo.private.webp",
        "/api/v1/uploads/profiles%2f..%2fkyc%2f42%2fid_proof.pdf",
        "/api/v1/uploads/profiles/%252e%252e/kyc/42/id_proof.pdf",
        "/api/v1/uploads/profiles\\..\\kyc\\42\\id_proof.pdf",
    ],
)
def test_malformed_traversal_encoded_and_nested_private_paths_are_denied(
    client, upload_root, url
):
    _write(upload_root, "kyc/42/id_proof.pdf", b"private document")
    _write(upload_root, "profiles/42/avatar.jpg", b"public profile")

    response = client.get(url)
    _assert_not_found(response)


def test_final_and_directory_symlinks_cannot_escape_public_allowlist(
    client, upload_root, tmp_path
):
    outside_file = _write(tmp_path, "outside/id_proof.pdf", b"private document")
    final_link = upload_root / "profiles" / "profile_99.png"
    final_link.parent.mkdir(parents=True, exist_ok=True)

    outside_directory = tmp_path / "outside-profile"
    outside_directory.mkdir()
    (outside_directory / "avatar.jpg").write_bytes(b"private document")
    directory_link = upload_root / "profiles" / "99"

    try:
        final_link.symlink_to(outside_file)
        directory_link.symlink_to(outside_directory, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"test filesystem does not support symlinks: {exc}")

    _assert_not_found(client.get("/api/v1/uploads/profiles/profile_99.png"))
    _assert_not_found(client.get("/api/v1/uploads/profiles/99/avatar.jpg"))
