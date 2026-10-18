"""Support ticket endpoints with explicit ownership and bounded responses.

Guest submissions remain deliberately unowned and are not retrievable by email.  All
customer ticket reads and mutations use the authenticated ``user_id`` binding.
"""
import json
import logging
import re
from datetime import datetime

from flask import Blueprint, jsonify, request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from src.database import db
from src.models.support_ticket import SupportTicket, TicketMessage
from src.models.user import User
from src.utils import crm_scope
from src.utils.decorators import admin_required, token_required
from src.utils.hierarchy_scoping import platform_root_scope

logger = logging.getLogger(__name__)

tickets_bp = Blueprint('support_tickets', __name__)

# The private upload/attachment contract has not been implemented.  Never accept
# caller supplied URLs, including from legacy guest flows.
_MAX_JSON_BODY = 32 * 1024
_MAX_PAGE = 1000
_MAX_PER_PAGE = 100
_MAX_EMAIL = 255
_MAX_NAME = 200
_MAX_SUBJECT = 500
_MAX_DESCRIPTION = 20_000
_MAX_MESSAGE = 4_000
_MAX_FEEDBACK = 4_000
_ALLOWED_CATEGORIES = {'technical', 'billing', 'account', 'general', 'kyc', 'withdrawal'}
_ALLOWED_PRIORITIES = {'low', 'medium', 'high', 'urgent'}
_ALLOWED_STATUSES = {'open', 'in_progress', 'waiting_customer', 'resolved', 'closed'}
_TICKET_NUMBER = re.compile(r'^[A-Za-z0-9_-]{1,20}$')


class _InputError(ValueError):
    def __init__(self, message, status=400, code='INPUT_INVALID'):
        super().__init__(message)
        self.status = status
        self.code = code


def _error(message, status=400, code='INPUT_INVALID'):
    return jsonify({'error': message, 'code': code}), status


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _InputError('Duplicate JSON keys are not allowed')
        result[key] = value
    return result


def _reject_json_constant(_value):
    raise _InputError('Invalid JSON value')


def _bounded_json_object():
    """Parse a small JSON object without trusting Flask's permissive decoder."""
    content_length = request.content_length
    if content_length is not None and content_length > _MAX_JSON_BODY:
        raise _InputError('Request body is too large', 413, 'BODY_TOO_LARGE')
    if not request.is_json:
        raise _InputError('JSON request body is required', 415, 'JSON_REQUIRED')

    # Bound the read itself, including chunked requests without Content-Length.
    raw = request.stream.read(_MAX_JSON_BODY + 1)
    if len(raw) > _MAX_JSON_BODY:
        raise _InputError('Request body is too large', 413, 'BODY_TOO_LARGE')
    try:
        value = json.loads(
            raw.decode('utf-8'),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
    except (_InputError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise _InputError('Invalid JSON request body') from None
    if not isinstance(value, dict):
        raise _InputError('JSON object is required')
    return value


def _only_fields(data, allowed):
    unexpected = set(data).difference(allowed)
    if unexpected:
        # Do not reflect field names: callers should not be able to use an error
        # response as a schema oracle for internal fields.
        raise _InputError('Unsupported request field')


def _required_string(data, field, maximum):
    value = data.get(field)
    if not isinstance(value, str):
        raise _InputError(f'{field.replace("_", " ").title()} is required')
    value = value.strip()
    if not value or len(value) > maximum:
        raise _InputError(f'Invalid {field.replace("_", " ")}')
    return value


def _optional_string(data, field, maximum, default=''):
    value = data.get(field, default)
    if not isinstance(value, str):
        raise _InputError(f'Invalid {field.replace("_", " ")}')
    value = value.strip()
    if len(value) > maximum:
        raise _InputError(f'Invalid {field.replace("_", " ")}')
    return value


def _email(data):
    value = _required_string(data, 'email', _MAX_EMAIL)
    # This is deliberately only a submission-format check.  It is never used to
    # look up, attach, or retrieve a ticket.
    if value.count('@') != 1 or value.startswith('@') or value.endswith('@'):
        raise _InputError('Invalid email')
    return value


def _ticket_fields(data):
    subject = _required_string(data, 'subject', _MAX_SUBJECT)
    description = _required_string(data, 'description', _MAX_DESCRIPTION)
    category = data.get('category', 'general')
    priority = data.get('priority', 'medium')
    if not isinstance(category, str) or category not in _ALLOWED_CATEGORIES:
        raise _InputError('Invalid category')
    if not isinstance(priority, str) or priority not in _ALLOWED_PRIORITIES:
        raise _InputError('Invalid priority')
    return subject, description, category, priority


def _strict_positive_query_integer(name, default, maximum):
    values = request.args.getlist(name)
    if len(values) > 1:
        return None
    value = default if not values else values[0]
    if not isinstance(value, str) or not value.isascii() or not value.isdecimal():
        return None
    if len(value) > len(str(maximum)):
        return None
    parsed = int(value)
    if not 1 <= parsed <= maximum or str(parsed) != value:
        return None
    return parsed


def _pagination_arguments(allowed_filters):
    allowed = {'page', 'per_page', *allowed_filters}
    if any(key not in allowed for key in request.args):
        return None, _error('Invalid query parameters', code='QUERY_INVALID')
    if any(len(request.args.getlist(key)) > 1 for key in allowed):
        return None, _error('Duplicate query parameters are not allowed', code='QUERY_INVALID')
    page = _strict_positive_query_integer('page', '1', _MAX_PAGE)
    per_page = _strict_positive_query_integer('per_page', '20', _MAX_PER_PAGE)
    if page is None or per_page is None:
        return None, _error('Invalid pagination', code='PAGINATION_INVALID')
    return {'page': page, 'per_page': per_page}, None


def _my_list_arguments():
    result, error = _pagination_arguments({'status'})
    if error:
        return None, error
    status = request.args.get('status')
    if status is not None and status not in _ALLOWED_STATUSES:
        return None, _error('Invalid status', code='QUERY_INVALID')
    result['status'] = status
    return result, None


def _admin_list_arguments():
    result, error = _pagination_arguments({'status', 'category', 'priority', 'assigned_to'})
    if error:
        return None, error
    status = request.args.get('status')
    category = request.args.get('category')
    priority = request.args.get('priority')
    if status is not None and status not in _ALLOWED_STATUSES:
        return None, _error('Invalid status', code='QUERY_INVALID')
    if category is not None and category not in _ALLOWED_CATEGORIES:
        return None, _error('Invalid category', code='QUERY_INVALID')
    if priority is not None and priority not in _ALLOWED_PRIORITIES:
        return None, _error('Invalid priority', code='QUERY_INVALID')
    assigned_to = request.args.get('assigned_to')
    if assigned_to is not None:
        assigned_to = _strict_positive_query_integer('assigned_to', assigned_to, 2_147_483_647)
        if assigned_to is None:
            return None, _error('Invalid assignee', code='QUERY_INVALID')
    result.update(status=status, category=category, priority=priority, assigned_to=assigned_to)
    return result, None


def _message_page_arguments():
    return _pagination_arguments(set())


def _iso(value):
    return value.isoformat() if value is not None else None


def _safe_user_payload(user):
    if user is None:
        return None
    return {
        'id': user.id,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
    }


def _message_payload(message):
    """A message projection that never carries unvalidated attachment URLs."""
    payload = {
        'id': message.id,
        'ticket_id': message.ticket_id,
        'user_id': message.user_id,
        'email': message.email,
        'name': message.name,
        'message': message.message,
        'is_staff': bool(message.is_staff),
        'is_internal': bool(message.is_internal),
        'attachments': [],
        'created_at': _iso(message.created_at),
    }
    return payload


def _ticket_payload(ticket, *, message_count=0, last_message=None, include_related=False):
    """Serialize declared ticket fields without relationship/message lazy loads."""
    payload = {
        'id': ticket.id,
        'ticket_number': ticket.ticket_number,
        'user_id': ticket.user_id,
        'email': ticket.email,
        'name': ticket.name,
        'subject': ticket.subject,
        'description': ticket.description,
        'category': ticket.category,
        'priority': ticket.priority,
        'status': ticket.status,
        'assigned_to': ticket.assigned_to,
        'attachments': [],
        'first_response_at': _iso(ticket.first_response_at),
        'resolved_at': _iso(ticket.resolved_at),
        'closed_at': _iso(ticket.closed_at),
        'rating': ticket.rating,
        'feedback': ticket.feedback,
        'created_at': _iso(ticket.created_at),
        'updated_at': _iso(ticket.updated_at),
        'message_count': int(message_count or 0),
        'last_message': _message_payload(last_message) if last_message is not None else None,
    }
    if include_related:
        # Callers pre-load these relationships for a bounded number of tickets.
        user = _safe_user_payload(ticket.user)
        assigned_user = _safe_user_payload(ticket.assigned_user)
        if user is not None:
            payload['user'] = user
        if assigned_user is not None:
            payload['assigned_user'] = assigned_user
    return payload


def _pagination_payload(pagination, page, per_page, total_key='total_tickets'):
    return {
        'page': page,
        'per_page': per_page,
        total_key: pagination.total,
        'total_pages': pagination.pages,
        'has_next': pagination.has_next,
        'has_prev': pagination.has_prev,
    }


def _owner_context(current_user):
    """Return the JWT-authenticated account binding for customer responses.

    ``support_tickets`` deliberately has no tenant column.  Its account owner is
    therefore joined to the principal's current tenant in every customer query;
    this response receipt does not invent ticket-level tenant attribution.
    """
    user_id = getattr(current_user, 'id', None)
    tenant_id = getattr(current_user, 'tenant_id', None)
    if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id < 1:
        raise RuntimeError('Authenticated support principal has no valid user id')
    if isinstance(tenant_id, bool) or not isinstance(tenant_id, int) or tenant_id < 1:
        tenant_id = None
    return {'user_id': user_id, 'tenant_id': tenant_id}


_CUSTOMER_TICKET_FIELDS = frozenset({
    'id', 'ticket_number', 'user_id', 'subject', 'description', 'category',
    'priority', 'status', 'first_response_at', 'resolved_at', 'closed_at',
    'rating', 'feedback', 'created_at', 'updated_at', 'message_count',
})
_CUSTOMER_MESSAGE_FIELDS = frozenset({
    'id', 'ticket_id', 'user_id', 'message', 'is_staff', 'is_internal', 'created_at',
})


def _customer_ticket_projection(payload):
    """Customer HTTP must not carry staff/contact/attachment/preview metadata."""
    projected = {key: value for key, value in payload.items() if key in _CUSTOMER_TICKET_FIELDS}
    if 'messages' in payload:
        projected['messages'] = [
            {key: value for key, value in message.items() if key in _CUSTOMER_MESSAGE_FIELDS}
            for message in payload['messages'] if message.get('is_internal') is False
        ]
    if 'message_pagination' in payload:
        projected['message_pagination'] = payload['message_pagination']
    return projected


def _customer_response(current_user, payload):
    """Apply a customer allow-list before HTTP, not after delivery in the UI."""
    if 'id' in payload and 'ticket_number' in payload:
        response = _customer_ticket_projection(payload)
    else:
        response = dict(payload)
        if 'ticket' in response:
            response['ticket'] = _customer_ticket_projection(response['ticket'])
        if 'tickets' in response:
            response['tickets'] = [_customer_ticket_projection(ticket) for ticket in response['tickets']]
        if 'ticket_message' in response:
            response['ticket_message'] = {
                key: value for key, value in response['ticket_message'].items()
                if key in _CUSTOMER_MESSAGE_FIELDS
            }
    response['owner_context'] = _owner_context(current_user)
    return response


def _visible_customer_message_clause():
    # A legacy NULL does not prove that a note is customer-safe.  Fail closed:
    # only an explicitly false flag is visible outside support administration.
    return TicketMessage.is_internal.is_(False)


def _ticket_list_page(query, arguments, *, customer_visible):
    """Return page summaries using aggregate subqueries, never per-ticket SQL."""
    message_filter = [TicketMessage.ticket_id == SupportTicket.id]
    if customer_visible:
        message_filter.append(_visible_customer_message_clause())
    message_count = select(func.count(TicketMessage.id)).where(*message_filter).correlate(SupportTicket).scalar_subquery()
    latest_id = select(TicketMessage.id).where(*message_filter).order_by(
        TicketMessage.created_at.desc(), TicketMessage.id.desc()
    ).limit(1).correlate(SupportTicket).scalar_subquery()

    page = query.add_columns(
        message_count.label('message_count'), latest_id.label('latest_message_id')
    ).order_by(SupportTicket.created_at.desc(), SupportTicket.id.desc()).paginate(
        page=arguments['page'], per_page=arguments['per_page'], error_out=False
    )
    latest_ids = [row.latest_message_id for row in page.items if row.latest_message_id is not None]
    latest_messages = {}
    if latest_ids:
        latest_query = TicketMessage.query.filter(TicketMessage.id.in_(latest_ids))
        if customer_visible:
            latest_query = latest_query.filter(_visible_customer_message_clause())
        latest_messages = {message.id: message for message in latest_query.all()}
    tickets = [
        _ticket_payload(
            row.SupportTicket,
            message_count=row.message_count,
            last_message=latest_messages.get(row.latest_message_id),
            include_related=True,
        )
        for row in page.items
    ]
    return tickets, page


def _owned_ticket_query(current_user):
    owner = _owner_context(current_user)
    query = SupportTicket.query.join(User, SupportTicket.user_id == User.id).filter(
        SupportTicket.user_id == owner['user_id'],
        User.id == owner['user_id'],
    )
    if owner['tenant_id'] is None:
        return query.filter(User.tenant_id.is_(None))
    return query.filter(User.tenant_id == owner['tenant_id'])


def _admin_ticket_query(current_user):
    """Owned tickets only; email-bearing guest rows never gain inferred scope."""
    query = SupportTicket.query.join(User, SupportTicket.user_id == User.id)
    if not platform_root_scope(current_user):
        # crm_scope returns no rows when tenant/hierarchy data is incomplete.
        scoped_user_ids = crm_scope.scoped_users(current_user).with_entities(User.id)
        query = query.filter(SupportTicket.user_id.in_(scoped_user_ids))
    return query


def _admin_ticket_scope_allowed(current_user):
    """Require a verified principal before using a non-root CRM hierarchy scope."""
    if platform_root_scope(current_user):
        return True
    return (
        getattr(current_user, 'is_active', False) is True
        and getattr(current_user, 'is_verified', False) is True
        and crm_scope.tenant_id_for(current_user) is not None
    )


def _get_owned_ticket(current_user, *, ticket_id=None, ticket_number=None, lock=False):
    query = _owned_ticket_query(current_user)
    if ticket_id is not None:
        query = query.filter(SupportTicket.id == ticket_id)
    if ticket_number is not None:
        query = query.filter(SupportTicket.ticket_number == ticket_number)
    if lock:
        query = query.with_for_update()
    with db.session.no_autoflush:
        return query.options(selectinload(SupportTicket.user), selectinload(SupportTicket.assigned_user)).first()


def _get_admin_ticket(current_user, ticket_id, *, lock=False):
    query = _admin_ticket_query(current_user).filter(SupportTicket.id == ticket_id)
    if lock:
        query = query.with_for_update()
    with db.session.no_autoflush:
        return query.options(selectinload(SupportTicket.user), selectinload(SupportTicket.assigned_user)).first()


def _customer_messages(ticket_id, arguments):
    query = TicketMessage.query.filter(
        TicketMessage.ticket_id == ticket_id,
        _visible_customer_message_clause(),
    ).order_by(TicketMessage.created_at.asc(), TicketMessage.id.asc())
    with db.session.no_autoflush:
        page = query.paginate(page=arguments['page'], per_page=arguments['per_page'], error_out=False)
    return [_message_payload(message) for message in page.items], page


def _ticket_number_collision(error):
    text = str(getattr(error, 'orig', error)).lower()
    return 'ticket_number' in text or 'support_tickets.ticket_number' in text


def _persist_ticket(**values):
    """Commit once per bounded unique-number attempt; no preflight uniqueness race."""
    for _attempt in range(8):
        ticket = SupportTicket(ticket_number=SupportTicket.generate_ticket_number(), status='open', **values)
        try:
            db.session.add(ticket)
            db.session.commit()
            return ticket
        except IntegrityError as error:
            db.session.rollback()
            if not _ticket_number_collision(error):
                logger.exception('Support ticket create failed')
                return None
        except Exception:
            db.session.rollback()
            logger.exception('Support ticket create failed')
            return None
    logger.warning('Support ticket number allocation exhausted')
    return None


def _valid_ticket_number(value):
    return isinstance(value, str) and _TICKET_NUMBER.fullmatch(value) is not None


# ---------------------------------------------------------------------------
# Guest submissions: intentionally unowned, non-retrievable, and no delivery.
# ---------------------------------------------------------------------------
@tickets_bp.route('/', methods=['POST'])
def create_guest_ticket():
    """Accept an isolated guest submission without linking it to any account."""
    try:
        data = _bounded_json_object()
        _only_fields(data, {'email', 'name', 'subject', 'description', 'category', 'priority'})
        email = _email(data)
        name = _required_string(data, 'name', _MAX_NAME)
        subject, description, category, priority = _ticket_fields(data)
    except _InputError as error:
        return _error(str(error), error.status, error.code)

    ticket = _persist_ticket(
        user_id=None,
        email=email,
        name=name,
        subject=subject,
        description=description,
        category=category,
        priority=priority,
    )
    if ticket is None:
        return _error('Unable to create ticket', 503, 'TICKET_CREATE_UNAVAILABLE')
    logger.info('Guest support ticket created id=%s', ticket.id)
    return jsonify({
        'message': 'Support ticket created successfully',
        'ticket': _ticket_payload(ticket),
        'delivery_status': 'not_configured',
    }), 201


# ---------------------------------------------------------------------------
# Canonical customer endpoints.
# ---------------------------------------------------------------------------
@tickets_bp.route('/my', methods=['POST'])
@token_required
def create_my_ticket(current_user):
    """Create a customer-owned ticket from the authenticated account profile."""
    try:
        data = _bounded_json_object()
        _only_fields(data, {'subject', 'description', 'category', 'priority'})
        subject, description, category, priority = _ticket_fields(data)
    except _InputError as error:
        return _error(str(error), error.status, error.code)

    name = f'{current_user.first_name} {current_user.last_name}'.strip()
    ticket = _persist_ticket(
        user_id=current_user.id,
        email=current_user.email,
        name=name or 'Account customer',
        subject=subject,
        description=description,
        category=category,
        priority=priority,
    )
    if ticket is None:
        return _error('Unable to create ticket', 503, 'TICKET_CREATE_UNAVAILABLE')
    logger.info('Account support ticket created id=%s owner_id=%s', ticket.id, current_user.id)
    return jsonify(_customer_response(current_user, {
        'message': 'Support ticket created successfully',
        'ticket': _ticket_payload(ticket, include_related=False),
        'delivery_status': 'not_configured',
    })), 201


@tickets_bp.route('/my', methods=['GET'])
@token_required
def get_my_tickets(current_user):
    """List the caller's owned tickets with bounded customer-visible summaries."""
    arguments, error = _my_list_arguments()
    if error:
        return error
    try:
        query = _owned_ticket_query(current_user).options(
            selectinload(SupportTicket.user), selectinload(SupportTicket.assigned_user)
        )
        if arguments['status'] is not None:
            query = query.filter(SupportTicket.status == arguments['status'])
        with db.session.no_autoflush:
            tickets, pagination = _ticket_list_page(query, arguments, customer_visible=True)
        return jsonify(_customer_response(current_user, {
            'tickets': tickets,
            'pagination': _pagination_payload(pagination, arguments['page'], arguments['per_page']),
        })), 200
    except Exception:
        logger.exception('Customer support ticket list failed owner_id=%s', current_user.id)
        return _error('Unable to retrieve tickets', 500, 'TICKET_READ_UNAVAILABLE')


@tickets_bp.route('/<ticket_number>', methods=['GET'])
@token_required
def get_ticket_by_number(current_user, ticket_number):
    """Return only a caller-owned ticket; guest email retrieval is retired."""
    if not _valid_ticket_number(ticket_number):
        return _error('Ticket not found', 404, 'TICKET_NOT_FOUND')
    arguments, error = _message_page_arguments()
    if error:
        return error
    try:
        ticket = _get_owned_ticket(current_user, ticket_number=ticket_number)
        if ticket is None:
            # Do not distinguish a guest, foreign, or absent number.
            return _error('Ticket not found', 404, 'TICKET_NOT_FOUND')
        messages, pagination = _customer_messages(ticket.id, arguments)
        payload = _ticket_payload(ticket, message_count=pagination.total, include_related=True)
        payload['messages'] = messages
        payload['message_pagination'] = _pagination_payload(
            pagination, arguments['page'], arguments['per_page'], total_key='total_messages'
        )
        return jsonify(_customer_response(current_user, payload)), 200
    except Exception:
        logger.exception('Customer ticket detail failed owner_id=%s', current_user.id)
        return _error('Unable to retrieve ticket', 500, 'TICKET_READ_UNAVAILABLE')


@tickets_bp.route('/<ticket_number>/messages', methods=['POST'])
@token_required
def add_ticket_message(current_user, ticket_number):
    """Add a bounded customer message to a caller-owned, open ticket."""
    if not _valid_ticket_number(ticket_number):
        return _error('Ticket not found', 404, 'TICKET_NOT_FOUND')
    try:
        data = _bounded_json_object()
        _only_fields(data, {'message'})
        message_text = _required_string(data, 'message', _MAX_MESSAGE)
    except _InputError as error:
        return _error(str(error), error.status, error.code)

    try:
        ticket = _get_owned_ticket(current_user, ticket_number=ticket_number, lock=True)
        if ticket is None:
            return _error('Ticket not found', 404, 'TICKET_NOT_FOUND')
        if ticket.status == 'closed':
            return _error('Cannot add message to closed ticket', 400, 'TICKET_CLOSED')
        message = TicketMessage(
            ticket_id=ticket.id,
            user_id=current_user.id,
            email=current_user.email,
            name=f'{current_user.first_name} {current_user.last_name}'.strip() or 'Account customer',
            message=message_text,
            is_staff=False,
            is_internal=False,
        )
        db.session.add(message)
        if ticket.status == 'waiting_customer':
            ticket.status = 'in_progress'
        db.session.commit()
        return jsonify(_customer_response(current_user, {
            'message': 'Message added successfully',
            'ticket_number': ticket.ticket_number,
            'ticket_message': _message_payload(message),
        })), 201
    except Exception:
        db.session.rollback()
        logger.exception('Customer ticket message failed owner_id=%s', current_user.id)
        return _error('Unable to add message', 500, 'TICKET_WRITE_UNAVAILABLE')


@tickets_bp.route('/<int:ticket_id>', methods=['GET'])
@token_required
def get_ticket(current_user, ticket_id):
    """Compatibility ID detail route with the same customer-visible projection."""
    arguments, error = _message_page_arguments()
    if error:
        return error
    try:
        ticket = _get_owned_ticket(current_user, ticket_id=ticket_id)
        if ticket is None:
            return _error('Ticket not found', 404, 'TICKET_NOT_FOUND')
        messages, pagination = _customer_messages(ticket.id, arguments)
        payload = _ticket_payload(ticket, message_count=pagination.total, include_related=True)
        payload['messages'] = messages
        payload['message_pagination'] = _pagination_payload(
            pagination, arguments['page'], arguments['per_page'], total_key='total_messages'
        )
        return jsonify(_customer_response(current_user, payload)), 200
    except Exception:
        logger.exception('Customer ticket id detail failed owner_id=%s', current_user.id)
        return _error('Unable to retrieve ticket', 500, 'TICKET_READ_UNAVAILABLE')


@tickets_bp.route('/<int:ticket_id>/close', methods=['POST'])
@token_required
def close_ticket(current_user, ticket_id):
    """Close only the caller's ticket, under a database row lock where supported."""
    # Compatibility clients sometimes send ``{}``; accept only that bounded empty
    # object and never allow it to smuggle a mutable ticket field.
    if request.content_length not in (None, 0):
        try:
            data = _bounded_json_object()
            _only_fields(data, set())
        except _InputError as error:
            return _error(str(error), error.status, error.code)
    try:
        ticket = _get_owned_ticket(current_user, ticket_id=ticket_id, lock=True)
        if ticket is None:
            return _error('Ticket not found', 404, 'TICKET_NOT_FOUND')
        ticket.status = 'closed'
        if ticket.closed_at is None:
            ticket.closed_at = datetime.utcnow()
        db.session.commit()
        return jsonify(_customer_response(current_user, {
            'message': 'Ticket closed successfully',
            'ticket': _ticket_payload(ticket, include_related=True),
        })), 200
    except Exception:
        db.session.rollback()
        logger.exception('Customer ticket close failed owner_id=%s', current_user.id)
        return _error('Unable to close ticket', 500, 'TICKET_WRITE_UNAVAILABLE')


@tickets_bp.route('/<int:ticket_id>/rate', methods=['POST'])
@token_required
def rate_ticket(current_user, ticket_id):
    """Record one bounded rating for the caller's closed ticket."""
    try:
        data = _bounded_json_object()
        _only_fields(data, {'rating', 'feedback'})
        rating = data.get('rating')
        if isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
            raise _InputError('Rating must be an integer between 1 and 5')
        feedback = _optional_string(data, 'feedback', _MAX_FEEDBACK)
    except _InputError as error:
        return _error(str(error), error.status, error.code)

    try:
        ticket = _get_owned_ticket(current_user, ticket_id=ticket_id, lock=True)
        if ticket is None:
            return _error('Ticket not found', 404, 'TICKET_NOT_FOUND')
        if ticket.status != 'closed':
            return _error('Can only rate closed tickets', 400, 'TICKET_NOT_CLOSED')
        ticket.rating = rating
        ticket.feedback = feedback
        db.session.commit()
        return jsonify(_customer_response(current_user, {
            'message': 'Thank you for your feedback',
            'ticket': _ticket_payload(ticket, include_related=True),
        })), 200
    except Exception:
        db.session.rollback()
        logger.exception('Customer ticket rating failed owner_id=%s', current_user.id)
        return _error('Unable to rate ticket', 500, 'TICKET_WRITE_UNAVAILABLE')


# ---------------------------------------------------------------------------
# Support-admin endpoints.  Decorator order is intentional: token_required
# establishes g.current_user before admin_required evaluates it.
# ---------------------------------------------------------------------------
@tickets_bp.route('/admin/all', methods=['GET'])
@token_required
@admin_required
def get_all_tickets(current_user):
    """List only explicitly scoped, account-owned tickets for support staff."""
    arguments, error = _admin_list_arguments()
    if error:
        return error
    if not _admin_ticket_scope_allowed(current_user):
        return _error('Verified tenant scope is required', 403, 'ADMIN_SCOPE_UNAVAILABLE')
    try:
        query = _admin_ticket_query(current_user).options(
            selectinload(SupportTicket.user), selectinload(SupportTicket.assigned_user)
        )
        if arguments['status'] is not None:
            query = query.filter(SupportTicket.status == arguments['status'])
        if arguments['category'] is not None:
            query = query.filter(SupportTicket.category == arguments['category'])
        if arguments['priority'] is not None:
            query = query.filter(SupportTicket.priority == arguments['priority'])
        if arguments['assigned_to'] is not None:
            query = query.filter(SupportTicket.assigned_to == arguments['assigned_to'])
        with db.session.no_autoflush:
            tickets, pagination = _ticket_list_page(query, arguments, customer_visible=False)
        return jsonify({
            'tickets': tickets,
            'pagination': _pagination_payload(pagination, arguments['page'], arguments['per_page']),
        }), 200
    except Exception:
        logger.exception('Admin support ticket list failed actor_id=%s', current_user.id)
        return _error('Unable to retrieve tickets', 500, 'TICKET_READ_UNAVAILABLE')


def _scoped_assignee(current_user, assigned_to):
    if isinstance(assigned_to, bool) or not isinstance(assigned_to, int) or assigned_to < 1:
        return None
    if platform_root_scope(current_user):
        return User.query.filter(
            User.id == assigned_to,
            User.is_active.is_(True),
            User.is_verified.is_(True),
        ).first()
    return crm_scope.scoped_users(current_user).filter(
        User.id == assigned_to,
        User.is_active.is_(True),
        User.is_verified.is_(True),
    ).first()


@tickets_bp.route('/admin/<int:ticket_id>/assign', methods=['PUT'])
@token_required
@admin_required
def assign_ticket(current_user, ticket_id):
    """Assign a scoped ticket only to a verified active user in the same scope."""
    try:
        data = _bounded_json_object()
        _only_fields(data, {'assigned_to'})
        assigned_to = data.get('assigned_to')
        if isinstance(assigned_to, bool) or not isinstance(assigned_to, int) or assigned_to < 1:
            raise _InputError('Invalid assignee')
    except _InputError as error:
        return _error(str(error), error.status, error.code)

    if not _admin_ticket_scope_allowed(current_user):
        return _error('Verified tenant scope is required', 403, 'ADMIN_SCOPE_UNAVAILABLE')
    try:
        ticket = _get_admin_ticket(current_user, ticket_id, lock=True)
        if ticket is None:
            return _error('Ticket not found', 404, 'TICKET_NOT_FOUND')
        assignee = _scoped_assignee(current_user, assigned_to)
        if assignee is None:
            return _error('Assignee not found', 404, 'ASSIGNEE_NOT_FOUND')
        ticket.assigned_to = assignee.id
        ticket.assigned_user = assignee
        if ticket.status == 'open':
            ticket.status = 'in_progress'
        db.session.commit()
        return jsonify({
            'message': 'Ticket assigned successfully',
            'ticket': _ticket_payload(ticket, include_related=True),
        }), 200
    except Exception:
        db.session.rollback()
        logger.exception('Admin ticket assignment failed actor_id=%s', current_user.id)
        return _error('Unable to assign ticket', 500, 'TICKET_WRITE_UNAVAILABLE')


@tickets_bp.route('/admin/<int:ticket_id>/status', methods=['PUT'])
@token_required
@admin_required
def update_ticket_status(current_user, ticket_id):
    """Update a scoped ticket status under a row lock where the database supports it."""
    try:
        data = _bounded_json_object()
        _only_fields(data, {'status'})
        status = data.get('status')
        if not isinstance(status, str) or status not in _ALLOWED_STATUSES:
            raise _InputError('Invalid status')
    except _InputError as error:
        return _error(str(error), error.status, error.code)

    if not _admin_ticket_scope_allowed(current_user):
        return _error('Verified tenant scope is required', 403, 'ADMIN_SCOPE_UNAVAILABLE')
    try:
        ticket = _get_admin_ticket(current_user, ticket_id, lock=True)
        if ticket is None:
            return _error('Ticket not found', 404, 'TICKET_NOT_FOUND')
        old_status = ticket.status
        ticket.status = status
        if status == 'resolved' and old_status != 'resolved':
            ticket.resolved_at = datetime.utcnow()
        elif status == 'closed' and old_status != 'closed':
            ticket.closed_at = datetime.utcnow()
        db.session.commit()
        return jsonify({
            'message': 'Ticket status updated successfully',
            'ticket': _ticket_payload(ticket, include_related=True),
        }), 200
    except Exception:
        db.session.rollback()
        logger.exception('Admin ticket status update failed actor_id=%s', current_user.id)
        return _error('Unable to update ticket status', 500, 'TICKET_WRITE_UNAVAILABLE')


@tickets_bp.route('/admin/<int:ticket_id>/reply', methods=['POST'])
@token_required
@admin_required
def reply_to_ticket(current_user, ticket_id):
    """Add a scoped staff reply or internal note; outbound delivery is disabled."""
    try:
        data = _bounded_json_object()
        _only_fields(data, {'message', 'is_internal'})
        message_text = _required_string(data, 'message', _MAX_MESSAGE)
        is_internal = data.get('is_internal', False)
        if not isinstance(is_internal, bool):
            raise _InputError('Invalid internal note flag')
    except _InputError as error:
        return _error(str(error), error.status, error.code)

    if not _admin_ticket_scope_allowed(current_user):
        return _error('Verified tenant scope is required', 403, 'ADMIN_SCOPE_UNAVAILABLE')
    try:
        ticket = _get_admin_ticket(current_user, ticket_id, lock=True)
        if ticket is None:
            return _error('Ticket not found', 404, 'TICKET_NOT_FOUND')
        message = TicketMessage(
            ticket_id=ticket.id,
            user_id=current_user.id,
            message=message_text,
            is_staff=True,
            is_internal=is_internal,
        )
        db.session.add(message)
        if ticket.first_response_at is None:
            ticket.first_response_at = datetime.utcnow()
        if ticket.status == 'open':
            ticket.status = 'in_progress'
        elif not is_internal:
            ticket.status = 'waiting_customer'
        db.session.commit()
        return jsonify({
            'message': 'Reply added successfully',
            'ticket_message': _message_payload(message),
            'delivery_status': 'not_configured',
        }), 201
    except Exception:
        db.session.rollback()
        logger.exception('Admin ticket reply failed actor_id=%s', current_user.id)
        return _error('Unable to add reply', 500, 'TICKET_WRITE_UNAVAILABLE')
