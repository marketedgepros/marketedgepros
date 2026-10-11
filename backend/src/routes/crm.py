"""CRM routes for tenant-bound lead management."""
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import logging
import re

from flask import Blueprint, jsonify, request
from sqlalchemy import func, or_

from src.database import db
from src.models.lead import Lead, LeadActivity, LeadNote
from src.models.user import User
from src.utils import crm_scope
from src.utils.decorators import token_required
from src.utils.permissions import PermissionManager


crm_bp = Blueprint('crm', __name__)
logger = logging.getLogger(__name__)

_ALLOWED_STATUSES = {
    'new', 'contacted', 'qualified', 'proposal', 'negotiation', 'converted', 'lost'
}
_EMAIL_PATTERN = re.compile(r'^[^@\s]{1,64}@[^@\s]{1,253}\.[^@\s]+$')
_MAX_BUDGET = Decimal('99999999.99')


def _error(message, status):
    return jsonify({'error': message}), status


def _internal_error():
    """Keep unexpected database/validation internals out of CRM responses."""
    return _error('Unable to process CRM request', 500)


def _crm_actor(current_user, *, manage=False):
    """Use only the user authenticated by ``token_required`` and fail closed."""
    policy = PermissionManager.can_manage_leads if manage else PermissionManager.can_access_crm
    if not policy(current_user):
        return None
    if crm_scope.tenant_id_for(current_user) is None:
        return None
    return current_user


def _json_object():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def _positive_id(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isdigit() and int(value) > 0:
        return int(value)
    return None


def _page_value(value, default, maximum):
    if value is None:
        return default
    parsed = _positive_id(value)
    if parsed is None or parsed > maximum:
        return None
    return parsed


def _clean_string(value, *, maximum, required=False):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if (required and not value) or len(value) > maximum:
        return None
    return value


def _valid_email(value):
    email = _clean_string(value, maximum=255, required=True)
    if not email or not _EMAIL_PATTERN.fullmatch(email):
        return None
    return email.lower()


def _budget(value):
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        return False
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return False
    if not amount.is_finite() or amount < 0 or amount > _MAX_BUDGET:
        return False
    return amount


def _datetime_value(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    # The current model stores naive datetimes.  Reject offsets rather than
    # silently changing a follow-up time.
    if parsed.tzinfo is not None:
        return None
    return parsed


def _scoped_assigned_users(current_user, leads):
    user_ids = {lead.assigned_to for lead in leads if lead.assigned_to is not None}
    if not user_ids:
        return {}
    users = crm_scope.scoped_users(current_user).filter(User.id.in_(user_ids)).all()
    return {user.id: user for user in users}


def _assigned_user_data(user, *, include_email=False):
    if user is None:
        return None
    data = {'id': user.id, 'name': f'{user.first_name} {user.last_name}'}
    if include_email:
        data['email'] = user.email
    return data


def _get_visible_lead(current_user, lead_id):
    # Deliberately return the same response for inaccessible and absent IDs.
    lead = crm_scope.get_scoped_lead(current_user, lead_id)
    if lead is None:
        return None, _error('Lead not found', 404)
    return lead, None


def _target_user(current_user, value):
    target_id = _positive_id(value)
    if target_id is None:
        return None, _error('assigned_to must be a positive integer', 400)
    target = crm_scope.get_assignment_target(current_user, target_id)
    if target is None:
        return None, _error('Assignment target is not available', 403)
    return target, None


def _target_program(current_user, value):
    if value is None:
        return None, None
    program_id = _positive_id(value)
    if program_id is None:
        return None, _error('interested_program_id must be a positive integer', 400)
    program = crm_scope.get_tenant_program(current_user, program_id)
    if program is None:
        return None, _error('Interested program is not available', 403)
    return program, None


@crm_bp.route('/leads', methods=['GET'])
@token_required
def get_leads(current_user):
    """List only assigned leads owned by this tenant and hierarchy."""
    actor = _crm_actor(current_user)
    if actor is None:
        return _error('Access denied', 403)

    page = _page_value(request.args.get('page'), 1, 1_000_000)
    per_page = _page_value(request.args.get('per_page'), 20, 100)
    if page is None or per_page is None:
        return _error('Invalid pagination', 400)

    status = request.args.get('status')
    source = request.args.get('source')
    assigned_to = request.args.get('assigned_to')
    search = request.args.get('search', '')
    if status and (status not in _ALLOWED_STATUSES or len(status) > 20):
        return _error('Invalid status', 400)
    if source and len(source) > 50:
        return _error('Invalid source', 400)
    if len(search) > 100:
        return _error('Search is too long', 400)

    try:
        query = crm_scope.scoped_leads(actor)
        if status:
            query = query.filter(Lead.status == status)
        if source:
            query = query.filter(Lead.source == source)
        if assigned_to is not None:
            assigned_id = _positive_id(assigned_to)
            if assigned_id is None:
                return _error('assigned_to must be a positive integer', 400)
            query = query.filter(Lead.assigned_to == assigned_id)
        if search:
            escaped = search.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            query = query.filter(or_(
                Lead.first_name.ilike(f'%{escaped}%', escape='\\'),
                Lead.last_name.ilike(f'%{escaped}%', escape='\\'),
                Lead.email.ilike(f'%{escaped}%', escape='\\'),
                Lead.phone.ilike(f'%{escaped}%', escape='\\'),
            ))

        pagination = query.order_by(Lead.score.desc(), Lead.created_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )
        assigned_users = _scoped_assigned_users(actor, pagination.items)
        leads = []
        for lead in pagination.items:
            lead_data = lead.to_dict()
            assigned = _assigned_user_data(assigned_users.get(lead.assigned_to), include_email=True)
            if assigned:
                lead_data['assigned_user'] = assigned
            leads.append(lead_data)
        return jsonify({
            'leads': leads,
            'total': pagination.total,
            'pages': pagination.pages,
            'current_page': page,
            'per_page': per_page,
        }), 200
    except Exception:
        logger.error('CRM lead listing failed')
        return _internal_error()


@crm_bp.route('/leads', methods=['POST'])
@token_required
def create_lead(current_user):
    """Create a lead only after tenant-bound assignment targets are verified."""
    actor = _crm_actor(current_user, manage=True)
    if actor is None:
        return _error('Access denied', 403)

    data = _json_object()
    if data is None:
        return _error('JSON object required', 400)

    first_name = _clean_string(data.get('first_name'), maximum=100, required=True)
    last_name = _clean_string(data.get('last_name'), maximum=100, required=True)
    email = _valid_email(data.get('email'))
    if not first_name or not last_name or not email:
        return _error('Valid first_name, last_name, and email are required', 400)

    phone = data.get('phone')
    if phone is not None:
        phone = _clean_string(phone, maximum=20)
        if phone is None:
            return _error('Invalid phone', 400)
    country_code = data.get('country_code')
    if country_code is not None:
        country_code = _clean_string(country_code, maximum=2, required=True)
        if country_code is None or not country_code.isalpha():
            return _error('Invalid country_code', 400)
        country_code = country_code.upper()
    source = _clean_string(data.get('source', 'manual'), maximum=50, required=True)
    status = data.get('status', 'new')
    if not source:
        return _error('Invalid source', 400)
    if not isinstance(status, str) or status not in _ALLOWED_STATUSES:
        return _error('Invalid status', 400)

    assigned_value = data.get('assigned_to', actor.id)
    target, target_error = _target_user(actor, assigned_value)
    if target_error:
        return target_error
    program, program_error = _target_program(actor, data.get('interested_program_id'))
    if program_error:
        return program_error

    budget = _budget(data.get('budget'))
    if budget is False:
        return _error('Invalid budget', 400)
    company = data.get('company')
    job_title = data.get('job_title')
    notes = data.get('notes')
    tags = data.get('tags', '')
    for field, value, maximum in (
        ('company', company, 200), ('job_title', job_title, 100),
        ('notes', notes, 10_000), ('tags', tags, 500),
    ):
        if value is not None and (not isinstance(value, str) or len(value) > maximum):
            return _error(f'Invalid {field}', 400)

    try:
        # Check only already-visible leads, so a foreign tenant cannot turn this
        # validation into an email-existence oracle.
        existing = crm_scope.scoped_leads(actor).filter(func.lower(Lead.email) == email).first()
        if existing:
            return _error('Lead with this email already exists', 400)

        lead = Lead(
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            country_code=country_code,
            source=source,
            status=status,
            assigned_to=target.id,
            assigned_at=datetime.utcnow(),
            interested_program_id=program.id if program else None,
            budget=budget,
            company=company,
            job_title=job_title,
            notes=notes,
            tags=tags or '',
        )
        db.session.add(lead)
        db.session.flush()
        lead.calculate_score()
        db.session.add(LeadActivity(
            lead_id=lead.id,
            user_id=actor.id,
            activity_type='note',
            subject='Lead created',
            description='Lead created',
        ))
        db.session.commit()
        return jsonify({'message': 'Lead created successfully', 'lead': lead.to_dict()}), 201
    except Exception:
        db.session.rollback()
        logger.error('CRM lead creation failed')
        return _internal_error()


@crm_bp.route('/leads/<int:lead_id>', methods=['GET'])
@token_required
def get_lead_details(current_user, lead_id):
    """Get a single lead through the same tenant/hierarchy scope as lists."""
    actor = _crm_actor(current_user)
    if actor is None:
        return _error('Access denied', 403)
    try:
        lead, lead_error = _get_visible_lead(actor, lead_id)
        if lead_error:
            return lead_error
        lead_data = lead.to_dict()
        assigned = _assigned_user_data(_scoped_assigned_users(actor, [lead]).get(lead.assigned_to), include_email=True)
        if assigned:
            lead_data['assigned_user'] = assigned
        lead_data['activity_count'] = LeadActivity.query.filter(LeadActivity.lead_id == lead.id).count()
        lead_data['notes_count'] = LeadNote.query.filter(LeadNote.lead_id == lead.id).count()
        return jsonify(lead_data), 200
    except Exception:
        logger.error('CRM lead detail lookup failed')
        return _internal_error()


@crm_bp.route('/leads/<int:lead_id>/notes', methods=['GET'])
@token_required
def get_lead_notes(current_user, lead_id):
    """List notes only after the parent lead has passed the CRM scope."""
    actor = _crm_actor(current_user)
    if actor is None:
        return _error('Access denied', 403)
    try:
        lead, lead_error = _get_visible_lead(actor, lead_id)
        if lead_error:
            return lead_error
        notes = LeadNote.query.filter(LeadNote.lead_id == lead.id).order_by(LeadNote.created_at.desc()).all()
        creator_ids = {note.user_id for note in notes}
        creators = {}
        if creator_ids:
            creators = {
                user.id: user
                for user in crm_scope.scoped_users(actor).filter(User.id.in_(creator_ids)).all()
            }
        return jsonify({'notes': [
            {
                'id': note.id,
                'content': note.content,
                'created_at': note.created_at.isoformat() if note.created_at else None,
                # LeadNote has user_id; it does not have a created_by column.
                'created_by': (
                    f'{creators[note.user_id].first_name} {creators[note.user_id].last_name}'
                    if note.user_id in creators else None
                ),
            }
            for note in notes
        ]}), 200
    except Exception:
        logger.error('CRM lead notes lookup failed')
        return _internal_error()


@crm_bp.route('/leads/<int:lead_id>/notes', methods=['POST'])
@token_required
def add_lead_note(current_user, lead_id):
    """Add a note without exposing or writing outside the scoped parent lead."""
    actor = _crm_actor(current_user, manage=True)
    if actor is None:
        return _error('Access denied', 403)
    data = _json_object()
    if data is None:
        return _error('JSON object required', 400)
    content = _clean_string(data.get('content'), maximum=10_000, required=True)
    if not content:
        return _error('Note content is required', 400)
    try:
        lead, lead_error = _get_visible_lead(actor, lead_id)
        if lead_error:
            return lead_error
        note = LeadNote(lead_id=lead.id, content=content, user_id=actor.id)
        db.session.add(note)
        db.session.add(LeadActivity(
            lead_id=lead.id,
            activity_type='note_added',
            description='Note added',
            user_id=actor.id,
        ))
        db.session.commit()
        return jsonify({
            'message': 'Note added successfully',
            'note': {
                'id': note.id,
                'content': note.content,
                'created_at': note.created_at.isoformat(),
                'created_by': f'{actor.first_name} {actor.last_name}',
            },
        }), 201
    except Exception:
        db.session.rollback()
        logger.error('CRM lead note creation failed')
        return _internal_error()


@crm_bp.route('/leads/<int:lead_id>', methods=['PATCH', 'PUT'])
@token_required
def update_lead(current_user, lead_id):
    """Update a scoped lead and validate reassignment before changing it."""
    actor = _crm_actor(current_user, manage=True)
    if actor is None:
        return _error('Access denied', 403)
    data = _json_object()
    if data is None:
        return _error('JSON object required', 400)

    try:
        lead, lead_error = _get_visible_lead(actor, lead_id)
        if lead_error:
            return lead_error

        updates = {}
        assignment_target = None
        if 'assigned_to' in data:
            assignment_target, target_error = _target_user(actor, data['assigned_to'])
            if target_error:
                return target_error
            updates['assigned_to'] = assignment_target.id
        if 'interested_program_id' in data:
            program, program_error = _target_program(actor, data['interested_program_id'])
            if program_error:
                return program_error
            updates['interested_program_id'] = program.id if program else None
        if 'status' in data:
            if not isinstance(data['status'], str) or data['status'] not in _ALLOWED_STATUSES:
                return _error('Invalid status', 400)
            updates['status'] = data['status']
        if 'score' in data:
            score = data['score']
            if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
                return _error('Invalid score', 400)
            updates['score'] = score
        if 'budget' in data:
            budget = _budget(data['budget'])
            if budget is False:
                return _error('Invalid budget', 400)
            updates['budget'] = budget
        if 'notes' in data:
            if data['notes'] is not None and (not isinstance(data['notes'], str) or len(data['notes']) > 10_000):
                return _error('Invalid notes', 400)
            updates['notes'] = data['notes']

        follow_up_present = 'next_follow_up' in data or 'next_followup' in data
        if follow_up_present:
            raw_follow_up = data.get('next_follow_up', data.get('next_followup'))
            if raw_follow_up is None:
                updates['next_follow_up'] = None
            else:
                follow_up = _datetime_value(raw_follow_up)
                if follow_up is None:
                    return _error('Invalid next_follow_up', 400)
                updates['next_follow_up'] = follow_up

        changed = []
        for field, value in updates.items():
            if getattr(lead, field) != value:
                setattr(lead, field, value)
                changed.append(field)
        if assignment_target is not None and 'assigned_to' in changed:
            lead.assigned_at = datetime.utcnow()

        if changed:
            lead.updated_at = datetime.utcnow()
            db.session.add(LeadActivity(
                lead_id=lead.id,
                activity_type='lead_updated',
                description=f"Lead updated: {', '.join(changed)}",
                user_id=actor.id,
            ))
        db.session.commit()
        return jsonify({'message': 'Lead updated successfully', 'lead': lead.to_dict()}), 200
    except Exception:
        db.session.rollback()
        logger.error('CRM lead update failed')
        return _internal_error()


@crm_bp.route('/leads/<int:lead_id>', methods=['DELETE'])
@token_required
def delete_lead(current_user, lead_id):
    """Delete only a visible lead and retain the pre-existing admin-only policy."""
    actor = _crm_actor(current_user, manage=True)
    if actor is None:
        return _error('Access denied', 403)
    if actor.role not in ['admin', 'supermaster']:
        return _error('Admin access required', 403)
    try:
        lead, lead_error = _get_visible_lead(actor, lead_id)
        if lead_error:
            return lead_error
        LeadNote.query.filter(LeadNote.lead_id == lead.id).delete(synchronize_session=False)
        LeadActivity.query.filter(LeadActivity.lead_id == lead.id).delete(synchronize_session=False)
        db.session.delete(lead)
        db.session.commit()
        return jsonify({'message': 'Lead deleted successfully'}), 200
    except Exception:
        db.session.rollback()
        logger.error('CRM lead deletion failed')
        return _internal_error()


@crm_bp.route('/leads/<int:lead_id>/activities', methods=['POST'])
@token_required
def add_lead_activity(current_user, lead_id):
    """Create a valid activity on a scoped lead without a nonexistent metadata field."""
    actor = _crm_actor(current_user, manage=True)
    if actor is None:
        return _error('Access denied', 403)
    data = _json_object()
    if data is None:
        return _error('JSON object required', 400)
    activity_type = _clean_string(data.get('activity_type'), maximum=50, required=True)
    if not activity_type:
        return _error('activity_type is required', 400)
    subject = data.get('subject')
    description = data.get('description', '')
    outcome = data.get('outcome')
    if subject is not None and (not isinstance(subject, str) or len(subject) > 200):
        return _error('Invalid subject', 400)
    if not isinstance(description, str) or len(description) > 10_000:
        return _error('Invalid description', 400)
    if outcome is not None and (not isinstance(outcome, str) or len(outcome) > 50):
        return _error('Invalid outcome', 400)
    scheduled_at = None
    if 'scheduled_at' in data:
        scheduled_at = _datetime_value(data['scheduled_at'])
        if scheduled_at is None:
            return _error('Invalid scheduled_at', 400)

    try:
        lead, lead_error = _get_visible_lead(actor, lead_id)
        if lead_error:
            return lead_error
        # Legacy clients may send metadata.  LeadActivity has no mapped metadata
        # column, so do not pass it to SQLAlchemy or turn a valid activity into 500.
        activity = LeadActivity(
            lead_id=lead.id,
            user_id=actor.id,
            activity_type=activity_type,
            subject=subject,
            description=description,
            outcome=outcome,
            scheduled_at=scheduled_at,
        )
        db.session.add(activity)
        db.session.commit()
        return jsonify({'message': 'Activity added successfully', 'activity': activity.to_dict()}), 201
    except Exception:
        db.session.rollback()
        logger.error('CRM activity creation failed')
        return _internal_error()


@crm_bp.route('/leads/<int:lead_id>/convert', methods=['POST'])
@token_required
def convert_lead(current_user, lead_id):
    """Mark only a scoped lead converted; conversion actor is stored in activity."""
    actor = _crm_actor(current_user, manage=True)
    if actor is None:
        return _error('Access denied', 403)
    try:
        lead, lead_error = _get_visible_lead(actor, lead_id)
        if lead_error:
            return lead_error
        lead.status = 'converted'
        lead.converted_at = datetime.utcnow()
        db.session.add(LeadActivity(
            lead_id=lead.id,
            user_id=actor.id,
            activity_type='converted',
            description='Lead converted to customer',
        ))
        db.session.commit()
        return jsonify({'message': 'Lead converted successfully', 'lead': lead.to_dict()}), 200
    except Exception:
        db.session.rollback()
        logger.error('CRM lead conversion failed')
        return _internal_error()


@crm_bp.route('/leads/<int:lead_id>/lost', methods=['POST'])
@token_required
def mark_lead_lost(current_user, lead_id):
    """Mark only a scoped lead lost and avoid placing reason text in activity logs."""
    actor = _crm_actor(current_user, manage=True)
    if actor is None:
        return _error('Access denied', 403)
    data = _json_object()
    if data is None:
        data = {}
    reason = data.get('reason', '')
    if not isinstance(reason, str) or len(reason) > 50:
        return _error('Invalid reason', 400)
    try:
        lead, lead_error = _get_visible_lead(actor, lead_id)
        if lead_error:
            return lead_error
        lead.status = 'lost'
        lead.lost_reason = reason
        lead.lost_at = datetime.utcnow()
        db.session.add(LeadActivity(
            lead_id=lead.id,
            user_id=actor.id,
            activity_type='lost',
            description='Lead marked as lost',
        ))
        db.session.commit()
        return jsonify({'message': 'Lead marked as lost', 'lead': lead.to_dict()}), 200
    except Exception:
        db.session.rollback()
        logger.error('CRM lead lost update failed')
        return _internal_error()


@crm_bp.route('/stats', methods=['GET'])
@token_required
def get_crm_stats(current_user):
    """Calculate statistics from exactly the same visible lead scope as lists."""
    actor = _crm_actor(current_user)
    if actor is None:
        return _error('Access denied', 403)
    try:
        base_query = crm_scope.scoped_leads(actor)
        total_leads = base_query.count()
        new_leads = base_query.filter(Lead.status == 'new').count()
        contacted_leads = base_query.filter(Lead.status == 'contacted').count()
        qualified_leads = base_query.filter(Lead.status == 'qualified').count()
        converted_leads = base_query.filter(Lead.status == 'converted').count()
        lost_leads = base_query.filter(Lead.status == 'lost').count()
        recent_leads = base_query.filter(
            Lead.created_at >= datetime.utcnow() - timedelta(days=30)
        ).count()
        avg_score = base_query.with_entities(func.avg(Lead.score)).scalar() or 0
        conversion_rate = (converted_leads / total_leads * 100) if total_leads else 0
        return jsonify({
            'total_leads': total_leads,
            'new_leads': new_leads,
            'contacted_leads': contacted_leads,
            'qualified_leads': qualified_leads,
            'converted_leads': converted_leads,
            'lost_leads': lost_leads,
            'conversion_rate': round(conversion_rate, 2),
            'recent_leads_30d': recent_leads,
            'average_score': round(float(avg_score), 2),
        }), 200
    except Exception:
        logger.error('CRM statistics lookup failed')
        return _internal_error()


@crm_bp.route('/pipeline', methods=['GET'])
@token_required
def get_crm_pipeline(current_user):
    """Build pipeline output from the same scoped lead query as all CRM views."""
    actor = _crm_actor(current_user)
    if actor is None:
        return _error('Access denied', 403)
    try:
        pipeline = {status: [] for status in (
            'new', 'contacted', 'qualified', 'proposal', 'negotiation', 'converted', 'lost'
        )}
        leads = crm_scope.scoped_leads(actor).order_by(Lead.score.desc()).all()
        assigned_users = _scoped_assigned_users(actor, leads)
        for lead in leads:
            status = lead.status or 'new'
            if status not in pipeline:
                continue
            lead_data = lead.to_dict()
            assigned = _assigned_user_data(assigned_users.get(lead.assigned_to))
            if assigned:
                lead_data['assigned_user'] = assigned
            pipeline[status].append(lead_data)
        return jsonify({
            'pipeline': pipeline,
            'counts': {status: len(items) for status, items in pipeline.items()},
        }), 200
    except Exception:
        logger.error('CRM pipeline lookup failed')
        return _internal_error()
