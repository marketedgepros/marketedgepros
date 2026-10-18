"""
File upload routes
"""
from flask import Blueprint, request, jsonify, g, send_file, current_app
from src.services.file_service import FileService
from src.utils.decorators import token_required
from src.database import db
import logging
import os
from pathlib import Path
import stat
import unicodedata

logger = logging.getLogger(__name__)

uploads_bp = Blueprint('uploads', __name__)


# These are the only local paths this blueprint itself creates for assets that
# are intentionally public.  KYC files are stored below ``kyc/<user_id>`` and
# must never be served by this unauthenticated catch-all route.
_PUBLIC_IMAGE_EXTENSIONS = frozenset({'png', 'jpg', 'jpeg', 'gif', 'webp'})


def _canonical_public_upload_parts(filename):
    """Return a supported public upload path, or ``None`` to fail closed.

    Local profile images are written as either ``profiles/profile_<id>.<ext>``
    (FileService) or ``profiles/<id>/avatar.<ext>`` (StorageService fallback).
    Tenant logos are written as ``tenants/<id>/logo.<ext>``.  There is no
    ownership metadata for other local upload paths, so this generic endpoint
    cannot safely authorize them.
    """
    if not filename or filename != unicodedata.normalize('NFKC', filename):
        return None

    # Generated public filenames are ASCII and never need percent encoding.
    # Reject it rather than relying on a proxy/framework's decode behavior for
    # encoded separators or double-encoded traversal sequences.
    if '%' in filename or '\\' in filename or '\x00' in filename:
        return None

    parts = filename.split('/')
    if any(not part or part in {'.', '..'} for part in parts):
        return None

    def public_image_parts(name):
        stem, separator, extension = name.partition('.')
        if not stem or not separator or '.' in extension:
            return None
        if extension not in _PUBLIC_IMAGE_EXTENSIONS:
            return None
        return stem, extension

    profile_image = public_image_parts(parts[1]) if len(parts) == 2 else None
    nested_profile_image = public_image_parts(parts[2]) if len(parts) == 3 else None

    # FileService.save_profile_image: profiles/profile_<integer>.<image>
    if (
        len(parts) == 2
        and parts[0] == 'profiles'
        and profile_image is not None
        and profile_image[0].startswith('profile_')
        and profile_image[0][len('profile_'):].isdigit()
    ):
        return parts

    # StorageService local fallback: profiles/<integer>/avatar.<image>
    if (
        len(parts) == 3
        and parts[0] == 'profiles'
        and parts[1].isdigit()
        and nested_profile_image is not None
        and nested_profile_image[0] == 'avatar'
    ):
        return parts

    # upload_tenant_logo: tenants/<integer>/logo.<image>
    if (
        len(parts) == 3
        and parts[0] == 'tenants'
        and parts[1].isdigit()
        and nested_profile_image is not None
        and nested_profile_image[0] == 'logo'
    ):
        return parts

    return None


def _open_public_upload(upload_folder, parts):
    """Open a regular allowlisted file without following user-path symlinks."""
    no_follow = getattr(os, 'O_NOFOLLOW', 0)
    directory = getattr(os, 'O_DIRECTORY', 0)
    if not no_follow or not directory:
        # This service is deployed on Linux.  Do not weaken the private-file
        # boundary on a platform that cannot provide no-follow directory opens.
        return None

    upload_root = Path(upload_folder).resolve(strict=False)
    flags = os.O_RDONLY | no_follow | getattr(os, 'O_NONBLOCK', 0)
    root_fd = current_fd = file_fd = None
    try:
        root_fd = current_fd = os.open(upload_root, os.O_RDONLY | directory)
        for directory_name in parts[:-1]:
            next_fd = os.open(directory_name, flags | directory, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd

        file_fd = os.open(parts[-1], flags, dir_fd=current_fd)
        if not stat.S_ISREG(os.fstat(file_fd).st_mode):
            os.close(file_fd)
            return None
        return os.fdopen(file_fd, 'rb')
    except OSError:
        if file_fd is not None:
            os.close(file_fd)
        return None
    finally:
        if current_fd is not None:
            os.close(current_fd)
        elif root_fd is not None:
            os.close(root_fd)


@uploads_bp.route('/kyc', methods=['POST'])
@token_required
def upload_kyc_document(current_user):
    """Legacy upload compatibility through the canonical private KYC service."""
    from src.routes.kyc import upload_document
    document_type = request.form.get('document_type', 'id')
    document_type = {'id': 'id_proof', 'address': 'address_proof', 'bank': 'bank_statement'}.get(document_type, document_type)
    # Call the already-authenticated view body, not a second auth wrapper.
    return upload_document.__wrapped__(current_user, document_type)


@uploads_bp.route('/profile-image', methods=['POST'])
@token_required
def upload_profile_image():
    """Upload profile image"""
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    try:
        # Validate file type
        if not FileService.allowed_file(file.filename, 'images'):
            return jsonify({'error': 'Invalid file type. Only images allowed'}), 400
        
        # Validate file size (5MB max for profile images)
        FileService.validate_file_size(file, max_size_mb=5)
        
        result = FileService.save_profile_image(file, g.current_user.id)
        
        return jsonify({
            'message': 'Profile image uploaded successfully',
            'file': result
        }), 201
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f'Profile image upload failed: {str(e)}')
        return jsonify({'error': 'Upload failed'}), 500


@uploads_bp.route('/tenant-logo', methods=['POST'])
@token_required
def upload_tenant_logo():
    """Upload tenant logo (admin only)"""
    if g.current_user.role != 'admin':
        return jsonify({'error': 'Admin access required'}), 403
    
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    tenant_id = request.form.get('tenant_id')
    if not tenant_id:
        return jsonify({'error': 'Tenant ID required'}), 400
    
    try:
        if not FileService.allowed_file(file.filename, 'images'):
            return jsonify({'error': 'Invalid file type. Only images allowed'}), 400
        
        FileService.validate_file_size(file, max_size_mb=2)
        
        result = FileService.save_local_file(
            file,
            subfolder=f'tenants/{tenant_id}',
            custom_filename=f'logo.{file.filename.rsplit(".", 1)[1].lower()}'
        )
        
        # Update tenant logo URL
        from src.models import Tenant
        tenant = Tenant.query.get(tenant_id)
        if tenant:
            tenant.logo_url = result['url']
            db.session.commit()
        
        return jsonify({
            'message': 'Tenant logo uploaded successfully',
            'file': result
        }), 201
        
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except Exception as e:
        logger.error(f'Tenant logo upload failed: {str(e)}')
        return jsonify({'error': 'Upload failed'}), 500


@uploads_bp.route('/<path:filename>', methods=['GET'])
def serve_file(filename):
    """Serve only canonical, intentionally-public local upload assets."""
    try:
        # RAW_URI retains percent-encoding with standard WSGI servers.  Deny
        # encoded paths as well as decoded '%' paths, so separator decoding is
        # never a path-validation bypass.
        raw_uri = request.environ.get('RAW_URI') or request.environ.get('REQUEST_URI') or ''
        if '%' in raw_uri.split('?', 1)[0]:
            return jsonify({'error': 'File not found'}), 404

        parts = _canonical_public_upload_parts(filename)
        if parts is None:
            return jsonify({'error': 'File not found'}), 404

        upload_folder = current_app.config.get('UPLOAD_FOLDER', '/tmp/uploads')
        file_handle = _open_public_upload(upload_folder, parts)
        if file_handle is None:
            return jsonify({'error': 'File not found'}), 404

        return send_file(file_handle, download_name=parts[-1], conditional=True)
    except Exception as e:
        logger.error(f'File serving failed: {str(e)}')
        return jsonify({'error': 'File not found'}), 404
