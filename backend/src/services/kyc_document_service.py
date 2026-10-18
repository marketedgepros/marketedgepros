"""Private KYC objects: references, never publicly served filesystem URLs."""
import io
import os
from pathlib import Path
import re
import stat
import uuid
from urllib.parse import urlsplit

from flask import current_app, send_file
from src.services.storage_service import storage_service

DOCUMENT_FIELDS = {
    'id_proof': 'kyc_id',
    'address_proof': 'kyc_address',
    'selfie': 'kyc_selfie',
    'bank_statement': 'kyc_bank',
}
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MIME_TYPES = {'pdf': 'application/pdf', 'png': 'image/png', 'jpg': 'image/jpeg', 'jpeg': 'image/jpeg'}


def _root_fd(root, *, create=False, private=False):
    """Walk from / with directory FDs, rejecting all symlink components."""
    path = Path(root).absolute()
    if '..' in path.parts or path == Path('/'):
        raise ValueError('Invalid KYC root')
    descriptor = os.open('/', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:]:
            if create:
                try:
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = next_fd
        info = os.fstat(descriptor)
        if private and (info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077):
            raise ValueError('Private KYC root must be service-owned with mode 0700')
        result, descriptor = descriptor, None
        return result
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _parts_for_owner(key, user_id, document_type):
    """Only service-generated ASCII keys bound to the requested owner/type."""
    if document_type not in DOCUMENT_FIELDS or not isinstance(key, str):
        return None
    pattern = rf'kyc/{int(user_id)}/{document_type}_(?:[0-9a-f]{{32}}|[0-9]{{8}}_[0-9]{{6}})\.(pdf|png|jpg|jpeg)'
    return key.split('/') if re.fullmatch(pattern, key) else None


def _open_local(root, parts, *, private=False):
    """Open using directory descriptors; never follow path symlinks."""
    if not hasattr(os, 'O_NOFOLLOW') or not hasattr(os, 'O_DIRECTORY'):
        raise ValueError('Private documents require secure filesystem support')
    directory_fd = file_fd = None
    try:
        directory_fd = _root_fd(root, private=private)
        for part in parts[:-1]:
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
        file_fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory_fd)
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_DOCUMENT_BYTES:
            raise ValueError('Document is unavailable')
        stream = os.fdopen(file_fd, 'rb')
        file_fd = None
        return stream
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)


def _write_local(root, parts, content):
    directory_fd = file_fd = None
    try:
        directory_fd = _root_fd(root, create=True, private=True)
        for part in parts[:-1]:
            try:
                os.mkdir(part, mode=0o700, dir_fd=directory_fd)
            except FileExistsError:
                pass
            next_fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
            info = os.fstat(directory_fd)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o077:
                raise ValueError('Private KYC directories require service ownership and mode 0700')
        file_fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory_fd)
        with os.fdopen(file_fd, 'wb') as stream:
            file_fd = None
            stream.write(content)
    finally:
        if file_fd is not None:
            os.close(file_fd)
        if directory_fd is not None:
            os.close(directory_fd)


class KycDocumentService:
    @staticmethod
    def store(file, user_id, document_type):
        if document_type not in DOCUMENT_FIELDS:
            raise ValueError('Invalid document type')
        filename = file.filename or ''
        extension = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        if extension not in MIME_TYPES:
            raise ValueError('Allowed document formats: PDF, PNG, JPG')
        content = file.stream.read(MAX_DOCUMENT_BYTES + 1)
        if not content or len(content) > MAX_DOCUMENT_BYTES:
            raise ValueError('Document must be nonempty and at most 10 MB')
        signatures = {
            'pdf': content.startswith(b'%PDF-'),
            'png': content.startswith(b'\x89PNG\r\n\x1a\n'),
            'jpg': content.startswith(b'\xff\xd8\xff'),
            'jpeg': content.startswith(b'\xff\xd8\xff'),
        }
        if not signatures[extension]:
            raise ValueError('Document contents do not match the file format')
        key = f'kyc/{int(user_id)}/{document_type}_{uuid.uuid4().hex}.{extension}'
        if storage_service.client is not None:
            # A provider failure must not switch silently to local/public storage.
            storage_service.client.upload_fileobj(
                io.BytesIO(content), storage_service.spaces_name, key,
                ExtraArgs={'ContentType': MIME_TYPES[extension], 'ACL': 'private'},
            )
            return 'spaces-kyc:' + key
        if not current_app.config.get('KYC_ALLOW_PRIVATE_LOCAL_STORAGE', False):
            raise RuntimeError('Private KYC storage is not configured')
        root = current_app.config.get('KYC_PRIVATE_UPLOAD_FOLDER', '/var/lib/marketedgepros/private-kyc')
        private_root = Path(root).absolute()
        public_root = Path(current_app.config.get('UPLOAD_FOLDER', '/tmp/uploads')).absolute()
        if private_root == public_root or public_root in private_root.parents:
            raise RuntimeError('Private KYC storage must be outside public uploads')
        _write_local(root, key.split('/'), content)
        return 'local-kyc:' + key

    @staticmethod
    def reference(user, document_type):
        field = DOCUMENT_FIELDS.get(document_type)
        reference = getattr(user, field + '_url', None) if field else None
        if not isinstance(reference, str):
            return None
        if reference.startswith('local-kyc:'):
            backend, key = 'local', reference[len('local-kyc:'):]
        elif reference.startswith('spaces-kyc:'):
            backend, key = 'spaces', reference[len('spaces-kyc:'):]
        elif reference.startswith('/uploads/kyc/'):
            backend, key = 'legacy-local', reference[len('/uploads/'):]
        elif reference.startswith('/api/v1/uploads/kyc/'):
            backend, key = 'legacy-local', reference[len('/api/v1/uploads/'):]
        else:
            parsed = urlsplit(reference)
            allowed_hosts = {
                f'{storage_service.spaces_name}.{storage_service.spaces_region}.digitaloceanspaces.com',
                f'{storage_service.spaces_name}.{storage_service.spaces_region}.cdn.digitaloceanspaces.com',
            }
            if parsed.scheme != 'https' or parsed.netloc not in allowed_hosts or parsed.fragment:
                return None
            backend, key = 'spaces', parsed.path.lstrip('/')
        parts = _parts_for_owner(key, user.id, document_type)
        return (backend, key, parts) if parts else None

    @staticmethod
    def download(user, document_type):
        reference = KycDocumentService.reference(user, document_type)
        if reference is None:
            raise FileNotFoundError('Document not found')
        backend, key, parts = reference
        extension = parts[-1].rsplit('.', 1)[1]
        if backend == 'spaces':
            if storage_service.client is None:
                raise FileNotFoundError('Document not found')
            result = storage_service.client.get_object(Bucket=storage_service.spaces_name, Key=key)
            body = result['Body']
            try:
                if result.get('ContentLength', MAX_DOCUMENT_BYTES + 1) > MAX_DOCUMENT_BYTES:
                    raise ValueError('Document is unavailable')
                content = body.read(MAX_DOCUMENT_BYTES + 1)
                if not content or len(content) > MAX_DOCUMENT_BYTES:
                    raise ValueError('Document is unavailable')
                stream = io.BytesIO(content)
            finally:
                body.close()
        else:
            config_key = 'UPLOAD_FOLDER' if backend == 'legacy-local' else 'KYC_PRIVATE_UPLOAD_FOLDER'
            default = '/tmp/uploads' if backend == 'legacy-local' else '/var/lib/marketedgepros/private-kyc'
            stream = _open_local(current_app.config.get(config_key, default), parts, private=backend == 'local')
        try:
            response = send_file(stream, as_attachment=True,
                                 download_name=f'{document_type}.{extension}',
                                 mimetype=MIME_TYPES[extension], conditional=False, max_age=0)
            response.headers['Cache-Control'] = 'private, no-store, max-age=0'
            response.headers['Pragma'] = 'no-cache'
            response.headers['X-Content-Type-Options'] = 'nosniff'
            return response
        except Exception:
            stream.close()
            raise
