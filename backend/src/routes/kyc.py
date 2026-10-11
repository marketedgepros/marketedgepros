"""
KYC (Know Your Customer) routes for document verification
"""
from flask import Blueprint, request, jsonify, g, current_app
from src.database import db
from src.models.user import User
from src.utils.decorators import token_required, admin_required
from datetime import datetime
from sqlalchemy import desc, or_
from src.services.storage_service import storage_service
from src.services.email_service import EmailService
from src.services.notification_service import NotificationService
from src.services.kyc_document_service import KycDocumentService, DOCUMENT_FIELDS
from src.constants.roles import Roles

kyc_bp = Blueprint('kyc', __name__)


# Document types
DOCUMENT_TYPES = {
    'id_proof': 'ID Proof',
    'address_proof': 'Address Proof',
    'selfie': 'Selfie with ID',
    'bank_statement': 'Bank Statement'
}


def _kyc_users_for_actor(actor):
    query = User.query.filter_by(tenant_id=actor.tenant_id)
    if not actor.tenant_id:
        return query.filter(User.id == -1)
    # Retain the existing root-reviewer privilege but restrict it to its tenant.
    if actor.role == Roles.SUPERMASTER and actor.parent_id is None:
        return query
    path = actor.tree_path
    if not isinstance(path, str) or not path:
        return query.filter(User.id == actor.id)
    escaped = path.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    return query.filter(or_(User.id == actor.id, User.tree_path.like(escaped + '/%', escape='\\')))


@kyc_bp.route('/documents', methods=['GET'])
@token_required
def get_user_documents(current_user):
    """Get current user's KYC documents"""
    try:
        user = g.current_user
        
        # In a real implementation, you'd have a Document model
        # This is a simplified version using user fields
        documents = {
            'id_proof': {
                'type': 'id_proof',
                'name': 'ID Proof',
                'status': user.kyc_id_status or 'not_uploaded',
                'uploaded_at': user.kyc_id_uploaded_at.isoformat() if hasattr(user, 'kyc_id_uploaded_at') and user.kyc_id_uploaded_at else None,
                'notes': user.kyc_id_notes if hasattr(user, 'kyc_id_notes') else None
            },
            'address_proof': {
                'type': 'address_proof',
                'name': 'Address Proof',
                'status': user.kyc_address_status or 'not_uploaded',
                'uploaded_at': user.kyc_address_uploaded_at.isoformat() if hasattr(user, 'kyc_address_uploaded_at') and user.kyc_address_uploaded_at else None,
                'notes': user.kyc_address_notes if hasattr(user, 'kyc_address_notes') else None
            },
            'selfie': {
                'type': 'selfie',
                'name': 'Selfie with ID',
                'status': user.kyc_selfie_status or 'not_uploaded',
                'uploaded_at': user.kyc_selfie_uploaded_at.isoformat() if hasattr(user, 'kyc_selfie_uploaded_at') and user.kyc_selfie_uploaded_at else None,
                'notes': user.kyc_selfie_notes if hasattr(user, 'kyc_selfie_notes') else None
            },
            'bank_statement': {
                'type': 'bank_statement',
                'name': 'Bank Statement',
                'status': user.kyc_bank_status or 'not_uploaded',
                'uploaded_at': user.kyc_bank_uploaded_at.isoformat() if hasattr(user, 'kyc_bank_uploaded_at') and user.kyc_bank_uploaded_at else None,
                'notes': user.kyc_bank_notes if hasattr(user, 'kyc_bank_notes') else None
            }
        }
        
        for document_type, document in documents.items():
            document['url'] = _document_url(user, document_type)

        # Count documents by status
        statuses = [doc['status'] for doc in documents.values()]
        stats = {
            'total': len(DOCUMENT_TYPES),
            'uploaded': len([s for s in statuses if s != 'not_uploaded']),
            'approved': len([s for s in statuses if s == 'approved']),
            'pending': len([s for s in statuses if s == 'pending']),
            'rejected': len([s for s in statuses if s == 'rejected'])
        }
        
        return jsonify({
            'overall_status': user.kyc_status,
            'statistics': stats,
            'documents': list(documents.values())
        }), 200
        
    except Exception as e:
        current_app.logger.error('KYC operation failed')
        return jsonify({'error': 'KYC operation failed'}), 500


@kyc_bp.route('/documents/<document_type>/upload', methods=['POST'])
@token_required
def upload_document(current_user, document_type):
    """Upload a KYC document"""
    try:
        if document_type not in DOCUMENT_TYPES:
            return jsonify({'error': 'Invalid document type'}), 400
        
        user = g.current_user
        
        # Check if file is present
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        # Validate file type
        allowed_extensions = {'pdf', 'jpg', 'jpeg', 'png'}
        file_ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
        
        if file_ext not in allowed_extensions:
            return jsonify({
                'error': f'Invalid file type. Allowed: {", ".join(allowed_extensions)}'
            }), 400
        
        if not user.tenant_id:
            return jsonify({'error': 'Tenant membership required'}), 403
        reference = KycDocumentService.store(file, user.id, document_type)
        field = DOCUMENT_FIELDS[document_type]
        setattr(user, field + '_status', 'pending')
        setattr(user, field + '_uploaded_at', datetime.utcnow())
        setattr(user, field + '_url', reference)

        # Update overall KYC status to pending if all required docs are uploaded
        # Required docs: id_proof, address_proof, selfie
        if (hasattr(user, 'kyc_id_status') and user.kyc_id_status == 'pending' and
            hasattr(user, 'kyc_address_status') and user.kyc_address_status == 'pending' and
            hasattr(user, 'kyc_selfie_status') and user.kyc_selfie_status == 'pending'):
            user.kyc_status = 'pending'
        
        user.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'message': 'Document uploaded successfully',
            'document': {
                'type': document_type,
                'name': DOCUMENT_TYPES[document_type],
                'status': 'pending',
                'uploaded_at': datetime.utcnow().isoformat()
            }
        }), 200
        
    except ValueError as e:
        db.session.rollback()
        return jsonify({'error': 'Invalid document data'}), 400
    except Exception as e:
        db.session.rollback()
        current_app.logger.error('KYC operation failed')
        return jsonify({'error': 'KYC operation failed'}), 500


@kyc_bp.route('/admin/submissions', methods=['GET'])
@token_required
@admin_required
def get_kyc_submissions(current_user):
    """Get all KYC submissions for admin review"""
    try:
        # Get query parameters
        status = request.args.get('status', 'pending')
        page = max(1, request.args.get('page', 1, type=int))
        per_page = min(100, max(1, request.args.get('per_page', 20, type=int)))
        
        # Build query
        if not current_user.tenant_id:
            return jsonify({'error': 'Tenant membership required'}), 403
        query = _kyc_users_for_actor(current_user)
        
        if status:
            query = query.filter_by(kyc_status=status)
        
        # Paginate
        pagination = query.order_by(desc(User.updated_at)).paginate(
            page=page, per_page=per_page, error_out=False
        )
        
        # Count by status
        stats = {
            'pending': _kyc_users_for_actor(current_user).filter_by(kyc_status='pending').count(),
            'approved': _kyc_users_for_actor(current_user).filter_by(kyc_status='approved').count(),
            'rejected': _kyc_users_for_actor(current_user).filter_by(kyc_status='rejected').count(),
            'not_submitted': _kyc_users_for_actor(current_user).filter(
                or_(User.kyc_status == None, User.kyc_status == 'not_submitted')
            ).count()
        }
        
        return jsonify({
            'statistics': stats,
            'submissions': [{
                'user_id': user.id,
                'name': f"{user.first_name} {user.last_name}",
                'email': user.email,
                'kyc_status': user.kyc_status,
                'submitted_at': user.updated_at.isoformat(),
                'documents': {
                    'id_proof': getattr(user, 'kyc_id_status', 'not_uploaded'),
                    'address_proof': getattr(user, 'kyc_address_status', 'not_uploaded'),
                    'selfie': getattr(user, 'kyc_selfie_status', 'not_uploaded'),
                    'bank_statement': getattr(user, 'kyc_bank_status', 'not_uploaded')
                }
            } for user in pagination.items],
            'pagination': {
                'page': pagination.page,
                'per_page': pagination.per_page,
                'total': pagination.total,
                'pages': pagination.pages
            }
        }), 200
        
    except Exception as e:
        current_app.logger.error('KYC operation failed')
        return jsonify({'error': 'KYC operation failed'}), 500


@kyc_bp.route('/admin/submissions/<int:user_id>', methods=['GET'])
@token_required
@admin_required
def get_kyc_submission_details(current_user, user_id):
    """Get detailed KYC submission for a specific user"""
    try:
        if not current_user.tenant_id:
            return jsonify({'error': 'Tenant membership required'}), 403
        user = _kyc_users_for_actor(current_user).filter_by(id=user_id).first()
        if user is None:
            return jsonify({'error': 'Submission not found'}), 404
        
        documents = {
            'id_proof': {
                'type': 'id_proof',
                'name': 'ID Proof',
                'status': getattr(user, 'kyc_id_status', 'not_uploaded'),
                'uploaded_at': getattr(user, 'kyc_id_uploaded_at', None),
                'notes': getattr(user, 'kyc_id_notes', None),
                'url': _document_url(user, 'id_proof')  # File URL
            },
            'address_proof': {
                'type': 'address_proof',
                'name': 'Address Proof',
                'status': getattr(user, 'kyc_address_status', 'not_uploaded'),
                'uploaded_at': getattr(user, 'kyc_address_uploaded_at', None),
                'notes': getattr(user, 'kyc_address_notes', None),
                'url': _document_url(user, 'address_proof')
            },
            'selfie': {
                'type': 'selfie',
                'name': 'Selfie with ID',
                'status': getattr(user, 'kyc_selfie_status', 'not_uploaded'),
                'uploaded_at': getattr(user, 'kyc_selfie_uploaded_at', None),
                'notes': getattr(user, 'kyc_selfie_notes', None),
                'url': _document_url(user, 'selfie')
            },
            'bank_statement': {
                'type': 'bank_statement',
                'name': 'Bank Statement',
                'status': getattr(user, 'kyc_bank_status', 'not_uploaded'),
                'uploaded_at': getattr(user, 'kyc_bank_uploaded_at', None),
                'notes': getattr(user, 'kyc_bank_notes', None),
                'url': _document_url(user, 'bank_statement')
            }
        }
        
        return jsonify({
            'user': {
                'id': user.id,
                'name': f"{user.first_name} {user.last_name}",
                'email': user.email,
                'phone': user.phone,
                'country_code': user.country_code,
                'kyc_status': user.kyc_status,
                'created_at': user.created_at.isoformat()
            },
            'documents': list(documents.values())
        }), 200
        
    except Exception as e:
        current_app.logger.error('KYC operation failed')
        return jsonify({'error': 'KYC operation failed'}), 500


@kyc_bp.route('/admin/submissions/<int:user_id>/approve', methods=['POST'])
@token_required
@admin_required
def approve_kyc(current_user, user_id):
    """Approve a user's KYC submission"""
    try:
        if not current_user.tenant_id:
            return jsonify({'error': 'Tenant membership required'}), 403
        user = _kyc_users_for_actor(current_user).filter_by(id=user_id).first()
        if user is None:
            return jsonify({'error': 'Submission not found'}), 404
        data = request.get_json() or {}
        
        # Update KYC status
        user.kyc_status = 'approved'
        
        # Approve all documents
        if hasattr(user, 'kyc_id_status'):
            user.kyc_id_status = 'approved'
        if hasattr(user, 'kyc_address_status'):
            user.kyc_address_status = 'approved'
        if hasattr(user, 'kyc_selfie_status'):
            user.kyc_selfie_status = 'approved'
        if hasattr(user, 'kyc_bank_status') and user.kyc_bank_status == 'pending':
            user.kyc_bank_status = 'approved'
        
        # Add admin notes
        if data.get('notes'):
            user.kyc_admin_notes = data['notes']
        
        user.kyc_approved_at = datetime.utcnow()
        user.kyc_approved_by = g.current_user.id
        user.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        # Send notification
        NotificationService.create_notification(
            user_id=user.id,
            notification_type='kyc',
            title='KYC Approved',
            message='Your KYC verification has been approved. You can now access all features.',
            data={'kyc_status': 'approved'},
            priority='high'
        )
        
        # Send KYC approval email
        try:
            EmailService.send_kyc_approved_email(user)
        except Exception as email_error:
            # Log but don't fail the approval
            print(f"Failed to send KYC approval email: {email_error}")
        
        return jsonify({
            'message': 'KYC approved successfully',
            'user': {
                'id': user.id,
                'name': f"{user.first_name} {user.last_name}",
                'kyc_status': user.kyc_status
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error('KYC operation failed')
        return jsonify({'error': 'KYC operation failed'}), 500


@kyc_bp.route('/admin/submissions/<int:user_id>/reject', methods=['POST'])
@token_required
@admin_required
def reject_kyc(current_user, user_id):
    """Reject a user's KYC submission"""
    try:
        if not current_user.tenant_id:
            return jsonify({'error': 'Tenant membership required'}), 403
        user = _kyc_users_for_actor(current_user).filter_by(id=user_id).first()
        if user is None:
            return jsonify({'error': 'Submission not found'}), 404
        data = request.get_json()
        
        if not data or not data.get('reason'):
            return jsonify({'error': 'Rejection reason is required'}), 400
        
        # Update KYC status
        user.kyc_status = 'rejected'
        user.kyc_rejection_reason = data['reason']
        
        # Update document statuses based on which ones were rejected
        rejected_documents = data.get('rejected_documents', [])
        
        for doc_type in rejected_documents:
            if doc_type not in DOCUMENT_FIELDS:
                continue
            status_field = DOCUMENT_FIELDS[doc_type] + '_status'
            notes_field = DOCUMENT_FIELDS[doc_type] + '_notes'
            
            if hasattr(user, status_field):
                setattr(user, status_field, 'rejected')
            if hasattr(user, notes_field):
                setattr(user, notes_field, data['reason'])
        
        user.kyc_rejected_at = datetime.utcnow()
        user.kyc_rejected_by = g.current_user.id
        user.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        # Send notification
        NotificationService.create_notification(
            user_id=user.id,
            notification_type='kyc',
            title='KYC Rejected',
            message=f'Your KYC verification has been rejected. Reason: {data["reason"]}',
            data={'kyc_status': 'rejected', 'reason': data['reason']},
            priority='high'
        )
        
        # Send KYC rejection email
        try:
            EmailService.send_kyc_rejected_email(user, data['reason'])
        except Exception as email_error:
            # Log but don't fail the rejection
            print(f"Failed to send KYC rejection email: {email_error}")
        
        return jsonify({
            'message': 'KYC rejected',
            'user': {
                'id': user.id,
                'name': f"{user.first_name} {user.last_name}",
                'kyc_status': user.kyc_status,
                'rejection_reason': user.kyc_rejection_reason
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error('KYC operation failed')
        return jsonify({'error': 'KYC operation failed'}), 500


@kyc_bp.route('/admin/submissions/<int:user_id>/documents/<document_type>', methods=['PUT'])
@token_required
@admin_required
def update_document_status(current_user, user_id, document_type):
    """Update status of a specific document"""
    try:
        if document_type not in DOCUMENT_TYPES:
            return jsonify({'error': 'Invalid document type'}), 400
        
        if not current_user.tenant_id:
            return jsonify({'error': 'Tenant membership required'}), 403
        user = _kyc_users_for_actor(current_user).filter_by(id=user_id).first()
        if user is None:
            return jsonify({'error': 'Submission not found'}), 404
        data = request.get_json()
        
        if not data or 'status' not in data:
            return jsonify({'error': 'Status is required'}), 400
        
        status = data['status']
        if status not in ['pending', 'approved', 'rejected']:
            return jsonify({'error': 'Invalid status'}), 400
        
        # Update document status
        status_field = DOCUMENT_FIELDS[document_type] + '_status'
        notes_field = DOCUMENT_FIELDS[document_type] + '_notes'
        
        if hasattr(user, status_field):
            setattr(user, status_field, status)
        
        if data.get('notes') and hasattr(user, notes_field):
            setattr(user, notes_field, data['notes'])
        
        user.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'message': 'Document status updated',
            'document': {
                'type': document_type,
                'status': status,
                'notes': data.get('notes')
            }
        }), 200
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error('KYC operation failed')
        return jsonify({'error': 'KYC operation failed'}), 500




def _document_url(user, document_type):
    if KycDocumentService.reference(user, document_type) is None:
        return None
    return f'/api/v1/kyc/documents/{user.id}/{document_type}/download'


@kyc_bp.route('/documents/<int:user_id>/<document_type>/download', methods=['GET'])
@token_required
def download_document(current_user, user_id, document_type):
    # Owner access or the existing reviewer role, never arbitrary URL/filename.
    # The existing hierarchy hook stays active for reviewer User queries.
    if not current_user.tenant_id:
        return jsonify({'error': 'Document not found'}), 404
    if user_id != current_user.id and not Roles.is_admin(current_user.role):
        return jsonify({'error': 'Document not found'}), 404
    user = _kyc_users_for_actor(current_user).filter_by(id=user_id).first()
    if user is None or document_type not in DOCUMENT_FIELDS:
        return jsonify({'error': 'Document not found'}), 404
    try:
        response = KycDocumentService.download(user, document_type)
        current_app.logger.info('KYC download actor=%s subject=%s type=%s tenant=%s',
                                current_user.id, user.id, document_type, current_user.tenant_id)
        return response
    except Exception:
        current_app.logger.warning('KYC document unavailable actor=%s subject=%s', current_user.id, user_id)
        return jsonify({'error': 'Document not found'}), 404
