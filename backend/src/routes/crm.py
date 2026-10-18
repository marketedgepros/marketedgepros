"""Canonical CRM routes for tenant-bound lead management."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
import logging
import re

from flask import Blueprint, jsonify, request
from sqlalchemy import func

from src.database import db
from src.models.lead import Lead, LeadActivity, LeadNote
from src.services.admin_closure_crm import (
    AdminClosureCrmArgumentError,
    AdminClosureCrmService,
)
from src.utils import crm_scope
from src.utils.decorators import token_required
from src.utils.permissions import PermissionManager


crm_bp = Blueprint('crm', __name__)
logger = logging.getLogger(__name__)

_ALLOWED_STATUSES = {
    'new', 'contacted', 'qualified', 'proposal', 'negotiation', 'converted', 'lost',
}
_ACTIVITY_TYPES = {'call', 'meeting', 'follow_up', 'other'}
_EMAIL_PATTERN = re.compile(r'^[^@\s]{1,64}@[^@\s]{1,253}\.[^@\s]+$')
_MAX_BUDGET = Decimal('99999999.99')


def _error(message, status, code=None):
    payload = {'error': message}
    if code:
        payload['code'] = code
    return jsonify(payload), status


def _internal_error():
    """Keep unexpected database/validation internals out of CRM responses."""
    return _error('Unable to process CRM request', 500)


def _crm_actor(current_user, *, manage=False):
    """Apply role and positive tenant context after JWT/CSRF/hierarchy decoration."""
    policy = PermissionManager.can_manage_leads if manage else PermissionManager.can_access_crm
    if not policy(current_user):
        return None
    try:
        AdminClosureCrmService.require_owner(current_user)
    except PermissionError:
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
    if isinstance(value, str) and value.isascii() and value.isdecimal() and int(value) > 0:
        return int(value)
    return None


def _clean_string(value, *, maximum, required=False):
    if not isinstance(value, str):
        return None
    value = value.strip()
    if (required and not value) or len(value) > maximum or any(ord(character) < 32 for character in value):
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
    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError:
        return None
    # The mapped fields intentionally store naive wall time; never alter it silently.
    if parsed.tzinfo is not None:
        return None
    return parsed


def _get_visible_lead(current_user, lead_id):
    """Fetch one lead through the same tenant/hierarchy scope as all CRM actions."""
    with db.session.no_autoflush:
        lead = crm_scope.get_scoped_lead(current_user, lead_id)
    if lead is None:
        # Do not create an existence oracle across tenant or hierarchy boundaries.
        return None, _error('Lead not found', 404)
    return lead, None


def _target_user(current_user, value):
    target_id = _positive_id(value)
    if target_id is None:
        return None, _error('assigned_to must be a positive integer', 400)
    with db.session.no_autoflush:
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
    with db.session.no_autoflush:
        program = crm_scope.get_tenant_program(current_user, program_id)
    if program is None:
        return None, _error('Interested program is not available', 403)
    return program, None


def _assigned_user(current_user, assigned_to):
    if assigned_to is None:
        return None
    with db.session.no_autoflush:
        return crm_scope.get_assignment_target(current_user, assigned_to)


def _lead_response(actor, lead, message, status=200):
    return jsonify({
        'message': message,
        'lead': AdminClosureCrmService.serialize_lead(lead, _assigned_user(actor, lead.assigned_to)),
        'owner_context': AdminClosureCrmService.owner_context(actor),
    }), status


def _note_response(actor, note, message, status=201):
    return jsonify({
        'message': message,
        'note': AdminClosureCrmService.serialize_note(note, actor),
        'owner_context': AdminClosureCrmService.owner_context(actor),
    }), status


def _activity_response(actor, activity, message, status=201):
    return jsonify({
        'message': message,
        'activity': AdminClosureCrmService.serialize_activity(activity, actor),
        'owner_context': AdminClosureCrmService.owner_context(actor),
    }), status


def _request_matches_version(lead, data):
    """Return False only for a supplied optimistic version that is stale or malformed."""
    if 'expected_updated_at' not in data:
        return True
    expected = data['expected_updated_at']
    if expected is not None and (not isinstance(expected, str) or _datetime_value(expected) is None):
        return None
    current = AdminClosureCrmService.iso_or_none(lead.updated_at)
    return expected == current


def _record_update_activity(lead, actor, changed):
    activity_type = 'status_change' if changed == ['status'] else 'lead_updated'
    db.session.add(LeadActivity(
        lead_id=lead.id,
        activity_type=activity_type,
        description='Lead updated: ' + ', '.join(changed),
        user_id=actor.id,
    ))


@crm_bp.route('/leads', methods=['GET'])
@token_required
def get_leads(current_user):
    """List a bounded, owner-scoped lead page from a coherent read snapshot."""
    actor = _crm_actor(current_user)
    if actor is None:
        return _error('Access denied', 403)
    try:
        arguments = AdminClosureCrmService.parse_list_arguments(request.args)
        payload = AdminClosureCrmService.list_leads(actor, arguments)
        # Retain the established pagination aliases while the dedicated UI-4 client
        # consumes the explicit nested contract.
        payload.update({
            'total': payload['pagination']['total'],
            'pages': payload['pagination']['pages'],
            'current_page': payload['pagination']['page'],
            'per_page': payload['pagination']['per_page'],
        })
        return jsonify(payload), 200
    except AdminClosureCrmArgumentError:
        return _error('Invalid CRM query', 400, 'INVALID_CRM_QUERY')
    except PermissionError:
        return _error('Access denied', 403)
    except Exception:
        logger.exception('CRM lead listing failed')
        return _internal_error()


@crm_bp.route('/leads', methods=['POST'])
@token_required
def create_lead(current_user):
    """Create a scoped lead after validating the full allow-list before DML."""
    actor = _crm_actor(current_user, manage=True)
    if actor is None:
        return _error('Access denied', 403)
    data = _json_object()
    if data is None:
        return _error('JSON object required', 400)
    allowed = {
        'first_name', 'last_name', 'email', 'phone', 'country_code', 'source', 'status',
        'assigned_to', 'interested_program_id', 'budget', 'company', 'job_title', 'notes', 'tags',
    }
    if set(data) - allowed:
        return _error('Unsupported lead fields', 400)

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
    if not source or not isinstance(status, str) or status not in _ALLOWED_STATUSES:
        return _error('Invalid source or status', 400)
    budget = _budget(data.get('budget'))
    if budget is False:
        return _error('Invalid budget', 400)
    values = {}
    for field, maximum in (('company', 200), ('job_title', 100), ('notes', 10_000), ('tags', 500)):
        value = data.get(field)
        if value is not None and (not isinstance(value, str) or len(value) > maximum):
            return _error(f'Invalid {field}', 400)
        values[field] = value

    target, target_error = _target_user(actor, data.get('assigned_to', actor.id))
    if target_error:
        return target_error
    program, program_error = _target_program(actor, data.get('interested_program_id'))
    if program_error:
        return program_error
    try:
        with db.session.no_autoflush:
            existing = crm_scope.scoped_leads(actor).filter(func.lower(Lead.email) == email).first()
        if existing:
            return _error('Lead with this email already exists', 400)
        lead = Lead(
            first_name=first_name, last_name=last_name, email=email, phone=phone,
            country_code=country_code, source=source, status=status, assigned_to=target.id,
            assigned_at=datetime.utcnow(), interested_program_id=program.id if program else None,
            budget=budget, **values,
        )
        db.session.add(lead)
        db.session.flush()
        lead.calculate_score()
        db.session.add(LeadActivity(
            lead_id=lead.id, user_id=actor.id, activity_type='lead_created',
            subject='Lead created', description='Lead created',
        ))
        db.session.commit()
        return _lead_response(actor, lead, 'Lead created successfully', 201)
    except Exception:
        db.session.rollback()
        logger.exception('CRM lead creation failed')
        return _internal_error()


@crm_bp.route('/leads/<int:lead_id>', methods=['GET'])
@token_required
def get_lead_details(current_user, lead_id):
    """Read one scoped lead; the response includes a server owner context."""
    actor = _crm_actor(current_user)
    if actor is None:
        return _error('Access denied', 403)
    try:
        payload = AdminClosureCrmService.lead_detail(actor, lead_id)
        if payload is None:
            return _error('Lead not found', 404)
        return jsonify(payload), 200
    except PermissionError:
        return _error('Access denied', 403)
    except Exception:
        logger.exception('CRM lead detail lookup failed')
        return _internal_error()


@crm_bp.route('/leads/<int:lead_id>/notes', methods=['GET'])
@token_required
def get_lead_notes(current_user, lead_id):
    """List bounded notes only after the parent lead has passed scope checks."""
    actor = _crm_actor(current_user)
    if actor is None:
        return _error('Access denied', 403)
    try:
        arguments = AdminClosureCrmService.parse_child_arguments(request.args)
        payload = AdminClosureCrmService.list_notes(actor, lead_id, arguments)
        if payload is None:
            return _error('Lead not found', 404)
        return jsonify(payload), 200
    except AdminClosureCrmArgumentError:
        return _error('Invalid CRM query', 400, 'INVALID_CRM_QUERY')
    except PermissionError:
        return _error('Access denied', 403)
    except Exception:
        logger.exception('CRM lead notes lookup failed')
        return _internal_error()


@crm_bp.route('/leads/<int:lead_id>/notes', methods=['POST'])
@token_required
def add_lead_note(current_user, lead_id):
    """Persist an explicitly supplied note and return that persisted row."""
    actor = _crm_actor(current_user, manage=True)
    if actor is None:
        return _error('Access denied', 403)
    data = _json_object()
    if data is None:
        return _error('JSON object required', 400)
    if set(data) != {'content'}:
        return _error('Unsupported note fields', 400)
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
            lead_id=lead.id, activity_type='note_added', description='Note added', user_id=actor.id,
        ))
        db.session.commit()
        return _note_response(actor, note, 'Note added successfully')
    except Exception:
        db.session.rollback()
        logger.exception('CRM lead note creation failed')
        return _internal_error()


@crm_bp.route('/leads/<int:lead_id>/activities', methods=['GET'])
@token_required
def get_lead_activities(current_user, lead_id):
    """Read persisted activity history; it does not invent provider/email events."""
    actor = _crm_actor(current_user)
    if actor is None:
        return _error('Access denied', 403)
    try:
        arguments = AdminClosureCrmService.parse_child_arguments(request.args)
        payload = AdminClosureCrmService.list_activities(actor, lead_id, arguments)
        if payload is None:
            return _error('Lead not found', 404)
        return jsonify(payload), 200
    except AdminClosureCrmArgumentError:
        return _error('Invalid CRM query', 400, 'INVALID_CRM_QUERY')
    except PermissionError:
        return _error('Access denied', 403)
    except Exception:
        logger.exception('CRM lead activity lookup failed')
        return _internal_error()


@crm_bp.route('/leads/<int:lead_id>/activities', methods=['POST'])
@token_required
def add_lead_activity(current_user, lead_id):
    """Persist a bounded internal CRM activity; scheduled_at is not a reminder service."""
    actor = _crm_actor(current_user, manage=True)
    if actor is None:
        return _error('Access denied', 403)
    data = _json_object()
    if data is None:
        return _error('JSON object required', 400)
    # ``metadata`` is an accepted legacy no-op.  The mapped LeadActivity model
    # has no metadata column, so it is deliberately never persisted.
    allowed = {'activity_type', 'subject', 'description', 'outcome', 'scheduled_at', 'metadata'}
    if set(data) - allowed:
        return _error('Unsupported activity fields', 400)
    activity_type = _clean_string(data.get('activity_type'), maximum=50, required=True)
    if activity_type not in _ACTIVITY_TYPES:
        return _error('Unsupported activity_type', 400)
    subject = data.get('subject')
    description = data.get('description', '')
    outcome = data.get('outcome')
    if subject is not None and _clean_string(subject, maximum=200) is None:
        return _error('Invalid subject', 400)
    if _clean_string(description, maximum=10_000) is None:
        return _error('Invalid description', 400)
    if outcome is not None and _clean_string(outcome, maximum=50) is None:
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
        activity = LeadActivity(
            lead_id=lead.id, user_id=actor.id, activity_type=activity_type, subject=subject,
            description=description, outcome=outcome, scheduled_at=scheduled_at,
        )
        db.session.add(activity)
        db.session.commit()
        return _activity_response(actor, activity, 'Activity added successfully')
    except Exception:
        db.session.rollback()
        logger.exception('CRM lead activity creation failed')
        return _internal_error()


@crm_bp.route('/leads/<int:lead_id>', methods=['PATCH', 'PUT'])
@token_required
def update_lead(current_user, lead_id):
    """Apply an allow-listed update only when its supplied version remains current."""
    actor = _crm_actor(current_user, manage=True)
    if actor is None:
        return _error('Access denied', 403)
    data = _json_object()
    if data is None:
        return _error('JSON object required', 400)
    allowed = {
        'assigned_to', 'interested_program_id', 'status', 'score', 'budget', 'notes',
        'next_follow_up', 'next_followup', 'expected_updated_at',
    }
    if not data or set(data) - allowed:
        return _error('Unsupported lead fields', 400)
    if 'next_follow_up' in data and 'next_followup' in data:
        return _error('Provide one follow-up field', 400)
    try:
        lead, lead_error = _get_visible_lead(actor, lead_id)
        if lead_error:
            return lead_error
        version_match = _request_matches_version(lead, data)
        if version_match is None:
            return _error('Invalid expected_updated_at', 400)
        if not version_match:
            return _error('Lead changed; reload before saving', 409, 'CRM_LEAD_STALE')

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
            if data['notes'] is not None and _clean_string(data['notes'], maximum=10_000) is None:
                return _error('Invalid notes', 400)
            updates['notes'] = data['notes']
        if 'next_follow_up' in data or 'next_followup' in data:
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
            _record_update_activity(lead, actor, changed)
        db.session.commit()
        return _lead_response(actor, lead, 'Lead updated successfully')
    except Exception:
        db.session.rollback()
        logger.exception('CRM lead update failed')
        return _internal_error()


@crm_bp.route('/leads/<int:lead_id>', methods=['DELETE'])
@token_required
def delete_lead(current_user, lead_id):
    """Retain the existing server-authoritative supermaster/admin delete policy."""
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
        return jsonify({
            'message': 'Lead deleted successfully',
            'lead_id': lead_id,
            'owner_context': AdminClosureCrmService.owner_context(actor),
        }), 200
    except Exception:
        db.session.rollback()
        logger.exception('CRM lead deletion failed')
        return _internal_error()


@crm_bp.route('/leads/<int:lead_id>/convert', methods=['POST'])
@token_required
def convert_lead(current_user, lead_id):
    """Mark a scoped record converted; this endpoint never creates a user account."""
    actor = _crm_actor(current_user, manage=True)
    if actor is None:
        return _error('Access denied', 403)
    data = _json_object()
    if data not in (None, {}):
        return _error('No conversion payload is supported', 400)
    try:
        lead, lead_error = _get_visible_lead(actor, lead_id)
        if lead_error:
            return lead_error
        if lead.status != 'converted':
            lead.status = 'converted'
            lead.converted_at = datetime.utcnow()
            lead.updated_at = datetime.utcnow()
            db.session.add(LeadActivity(
                lead_id=lead.id, user_id=actor.id, activity_type='status_change',
                description='Lead status set to converted',
            ))
        db.session.commit()
        return _lead_response(actor, lead, 'Lead marked converted')
    except Exception:
        db.session.rollback()
        logger.exception('CRM lead conversion failed')
        return _internal_error()


@crm_bp.route('/leads/<int:lead_id>/lost', methods=['POST'])
@token_required
def mark_lead_lost(current_user, lead_id):
    """Keep the existing explicit lost transition while avoiding untrusted log text."""
    actor = _crm_actor(current_user, manage=True)
    if actor is None:
        return _error('Access denied', 403)
    data = _json_object()
    if data is None:
        data = {}
    if set(data) - {'reason'}:
        return _error('Unsupported lost fields', 400)
    reason = data.get('reason', '')
    if not isinstance(reason, str) or len(reason) > 50 or any(ord(character) < 32 for character in reason):
        return _error('Invalid reason', 400)
    try:
        lead, lead_error = _get_visible_lead(actor, lead_id)
        if lead_error:
            return lead_error
        lead.status = 'lost'
        lead.lost_reason = reason
        lead.lost_at = datetime.utcnow()
        lead.updated_at = datetime.utcnow()
        db.session.add(LeadActivity(
            lead_id=lead.id, user_id=actor.id, activity_type='status_change',
            description='Lead status set to lost',
        ))
        db.session.commit()
        return _lead_response(actor, lead, 'Lead marked lost')
    except Exception:
        db.session.rollback()
        logger.exception('CRM lead lost update failed')
        return _internal_error()


@crm_bp.route('/stats', methods=['GET'])
@token_required
def get_crm_stats(current_user):
    """Return only scoped status counts; unavailable data is never represented as zero."""
    actor = _crm_actor(current_user)
    if actor is None:
        return _error('Access denied', 403)
    try:
        return jsonify(AdminClosureCrmService.stats(actor)), 200
    except PermissionError:
        return _error('Access denied', 403)
    except Exception:
        logger.exception('CRM statistics lookup failed')
        return _internal_error()


@crm_bp.route('/pipeline', methods=['GET'])
@token_required
def get_crm_pipeline(current_user):
    """Compatibility projection: a bounded first page, not an unbounded pipeline dump."""
    actor = _crm_actor(current_user)
    if actor is None:
        return _error('Access denied', 403)
    try:
        arguments = AdminClosureCrmService.parse_list_arguments(request.args)
        if arguments.page != 1:
            return _error('Pipeline supports only the first bounded page', 400, 'INVALID_CRM_QUERY')
        arguments = arguments.__class__(1, 100, arguments.status, arguments.source, arguments.search)
        result = AdminClosureCrmService.list_leads(actor, arguments)
        pipeline = {status: [] for status in sorted(_ALLOWED_STATUSES)}
        for lead in result['leads']:
            pipeline[lead['status']].append(lead)
        return jsonify({
            'owner_context': result['owner_context'],
            'pipeline': pipeline,
            'counts': {status: len(rows) for status, rows in pipeline.items()},
            'pagination': result['pagination'],
            'filters': result['filters'],
            'truncated': result['pagination']['total'] > len(result['leads']),
        }), 200
    except AdminClosureCrmArgumentError:
        return _error('Invalid CRM query', 400, 'INVALID_CRM_QUERY')
    except PermissionError:
        return _error('Access denied', 403)
    except Exception:
        logger.exception('CRM pipeline lookup failed')
        return _internal_error()
