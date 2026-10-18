"""Stage6c support-ticket contract regressions.

These use the real Flask registration, signed JWT/session validation, current token
blacklist model, hierarchy root configuration, and SQLite ORM tables.  The suite
network fixture blocks TCP; delivery methods are additionally made hard failures.
"""
from datetime import datetime, timedelta
import json

import pytest
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles


_API = '/api/v1/support/tickets'
_ROOT_ID = 1


@pytest.fixture(scope='session', autouse=True)
def sqlite_jsonb_compiler():
    @compiles(JSONB, 'sqlite')
    def compile_jsonb(_element, _compiler, **_kwargs):
        return 'JSON'


@pytest.fixture
def application(sqlite_jsonb_compiler):
    """Build a full testing app with only ticket-authentication table dependencies."""
    from src.app import create_app
    from src.database import db
    from src.models import Tenant, TokenBlacklist, User
    from src.models.support_ticket import SupportTicket, TicketMessage

    app = create_app(
        'testing',
        config_overrides={
            'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
            'JWT_ACCESS_TOKEN_EXPIRES': timedelta(hours=1),
            'PLATFORM_ROOT_USER_ID': _ROOT_ID,
            'EXPANDED_HIERARCHY_ENABLED': True,
        },
    )
    tables = [
        Tenant.__table__, User.__table__, TokenBlacklist.__table__,
        SupportTicket.__table__, TicketMessage.__table__,
    ]
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=tables)
    try:
        yield app
    finally:
        with app.app_context():
            db.session.remove()
            db.metadata.drop_all(bind=db.engine, tables=list(reversed(tables)))
            db.engine.dispose()


@pytest.fixture
def actors(application):
    """Persist owner, scoped admin, configured root, foreign and inactive users."""
    from src.database import db
    from src.models import Tenant, User
    from src.models.support_ticket import SupportTicket, TicketMessage

    with application.app_context():
        tenant_one = Tenant(name='Support One', subdomain='support-one')
        tenant_two = Tenant(name='Support Two', subdomain='support-two')
        db.session.add_all([tenant_one, tenant_two])
        db.session.flush()

        root = User(
            id=_ROOT_ID, email='root@support.test', password_hash='test',
            first_name='Root', last_name='Support', role='supermaster',
            parent_id=None, tree_path='1', level=0, tenant_id=tenant_one.id,
            is_active=True, is_verified=True, can_create_same_role=True,
        )
        admin = User(
            id=2, email='admin@support.test', password_hash='test',
            first_name='Scoped', last_name='Admin', role='master',
            parent_id=_ROOT_ID, tree_path='1/2', level=1, tenant_id=tenant_one.id,
            is_active=True, is_verified=True,
        )
        owner = User(
            id=3, email='owner@support.test', password_hash='test',
            first_name='Ticket', last_name='Owner', role='trader',
            parent_id=2, tree_path='1/2/3', level=2, tenant_id=tenant_one.id,
            is_active=True, is_verified=True,
        )
        inactive = User(
            id=4, email='inactive@support.test', password_hash='test',
            first_name='Inactive', last_name='User', role='trader',
            parent_id=2, tree_path='1/2/4', level=2, tenant_id=tenant_one.id,
            is_active=False, is_verified=True,
        )
        foreign = User(
            id=5, email='foreign@support.test', password_hash='test',
            first_name='Foreign', last_name='User', role='trader',
            parent_id=None, tree_path='5', level=0, tenant_id=tenant_two.id,
            is_active=True, is_verified=True,
        )
        db.session.add_all([root, admin, owner, inactive, foreign])
        db.session.flush()

        owned = SupportTicket(
            ticket_number='TICKET-OWNED', user_id=owner.id, email=owner.email,
            name='Ticket Owner', subject='Owned ticket', description='Need help',
            category='general', priority='medium', status='open',
        )
        foreign_ticket = SupportTicket(
            ticket_number='TICKET-FOREIGN', user_id=foreign.id, email=foreign.email,
            name='Foreign User', subject='Foreign ticket', description='Foreign help',
            category='general', priority='medium', status='open',
        )
        guest = SupportTicket(
            ticket_number='TICKET-GUEST', user_id=None, email=owner.email,
            name='Same Email Guest', subject='Guest ticket', description='Unowned',
            category='general', priority='medium', status='open',
        )
        db.session.add_all([owned, foreign_ticket, guest])
        db.session.flush()
        # The internal and NULL-flag messages are newest. Customer summaries must
        # fail closed and expose only the explicitly false-visible message.
        null_flag_message = TicketMessage(
            ticket_id=owned.id, user_id=admin.id, message='legacy null visibility',
            is_staff=True, is_internal=False, created_at=datetime(2026, 1, 1, 12, 1, 0),
        )
        db.session.add_all([
            TicketMessage(
                ticket_id=owned.id, user_id=owner.id, email=owner.email,
                name='Ticket Owner', message='customer visible', is_staff=False,
                is_internal=False, created_at=datetime(2026, 1, 1, 12, 0, 0),
            ),
            null_flag_message,
            TicketMessage(
                ticket_id=owned.id, user_id=admin.id, message='secret staff note',
                is_staff=True, is_internal=True, created_at=datetime(2026, 1, 1, 12, 2, 0),
            ),
        ])
        db.session.flush()
        # SQLAlchemy's Python-side Boolean default replaces constructor None;
        # emulate a pre-constraint legacy row using a direct nullable-column write.
        db.session.execute(
            TicketMessage.__table__.update().where(
                TicketMessage.id == null_flag_message.id
            ).values(is_internal=None)
        )
        db.session.commit()
        return {
            'owner_headers': {'Authorization': f'Bearer {owner.generate_access_token()}'},
            'admin_headers': {'Authorization': f'Bearer {admin.generate_access_token()}'},
            'root_headers': {'Authorization': f'Bearer {root.generate_access_token()}'},
            'foreign_headers': {'Authorization': f'Bearer {foreign.generate_access_token()}'},
            'inactive_headers': {'Authorization': f'Bearer {inactive.generate_access_token()}'},
            'owner_id': owner.id,
            'admin_id': admin.id,
            'foreign_id': foreign.id,
            'owned_id': owned.id,
            'foreign_ticket_id': foreign_ticket.id,
            'guest_ticket_id': guest.id,
        }


@pytest.fixture
def delivery_blocked(monkeypatch):
    """Ticket requests must never call historical inline email delivery methods."""
    from src.services.email_service import EmailService

    def forbidden(*_args, **_kwargs):
        raise AssertionError('Inline support-ticket email delivery is forbidden')

    monkeypatch.setattr(EmailService, 'queue_email', forbidden)
    monkeypatch.setattr(EmailService, 'send_notification_email', forbidden)


def test_canonical_create_and_guest_isolation(application, actors, delivery_blocked):
    from src.database import db
    from src.models.support_ticket import SupportTicket

    client = application.test_client()
    created = client.post(
        _API + '/my', headers=actors['owner_headers'], json={
            'subject': 'Account ticket', 'description': 'Account-created request',
            'category': 'technical', 'priority': 'high',
        },
    )
    assert created.status_code == 201
    payload = created.get_json()
    assert payload['delivery_status'] == 'not_configured'
    assert payload['ticket']['user_id'] == actors['owner_id']
    assert len(payload['ticket']['ticket_number']) <= 20

    with application.app_context():
        persisted = db.session.get(SupportTicket, payload['ticket']['id'])
        assert persisted.user_id == actors['owner_id']
        assert persisted.email == 'owner@support.test'
        assert persisted.attachments is None

    # Guest tickets are still accepted, but are unowned and cannot piggyback on
    # a matching account email. Attachments are rejected until private upload.
    guest = client.post(_API + '/', json={
        'email': 'owner@support.test', 'name': 'Guest Caller',
        'subject': 'Guest request', 'description': 'Unowned guest issue',
    })
    assert guest.status_code == 201
    guest_number = guest.get_json()['ticket']['ticket_number']
    assert guest.get_json()['ticket']['user_id'] is None
    assert guest.get_json()['delivery_status'] == 'not_configured'
    assert client.post(_API + '/', json={
        'email': 'guest@support.test', 'name': 'Guest Caller', 'subject': 'No files',
        'description': 'Reject URL attachment', 'attachments': ['https://attacker.test/file'],
    }).status_code == 400

    # Public email-as-proof retrieval is gone; even the email-matching account
    # gets no access to an older or newly created unowned guest ticket.
    assert client.get(_API + '/' + guest_number + '?email=owner@support.test').status_code == 401
    assert client.get(_API + '/' + guest_number, headers=actors['owner_headers']).status_code == 404
    assert client.get(_API + '/TICKET-GUEST', headers=actors['owner_headers']).status_code == 404


def test_customer_detail_list_and_messages_filter_internal(application, actors):
    client = application.test_client()
    headers = actors['owner_headers']

    detail = client.get(_API + '/TICKET-OWNED?per_page=100', headers=headers)
    assert detail.status_code == 200
    payload = detail.get_json()
    assert payload['message_count'] == 1
    assert payload['message_pagination'] == {
        'page': 1, 'per_page': 100, 'total_messages': 1, 'total_pages': 1,
        'has_next': False, 'has_prev': False,
    }
    assert [message['message'] for message in payload['messages']] == ['customer visible']
    assert all(message['is_internal'] is not True for message in payload['messages'])

    listing = client.get(_API + '/my?per_page=100', headers=headers)
    assert listing.status_code == 200
    owned = next(ticket for ticket in listing.get_json()['tickets'] if ticket['ticket_number'] == 'TICKET-OWNED')
    assert owned['message_count'] == 1
    assert 'last_message' not in owned
    assert not {'attachments', 'email', 'name', 'assigned_user', 'assigned_to', 'user'}.intersection(owned)
    assert client.get(_API + '/TICKET-OWNED?per_page=101', headers=headers).status_code == 400

    # The customer endpoint accepts message only and derives identity from JWT.
    rejected = client.post(_API + '/TICKET-OWNED/messages', headers=headers, json={
        'email': 'forged@support.test', 'message': 'forged identity',
    })
    assert rejected.status_code == 400
    accepted = client.post(_API + '/TICKET-OWNED/messages', headers=headers, json={'message': 'real owner update'})
    assert accepted.status_code == 201
    assert accepted.get_json()['ticket_message']['user_id'] == actors['owner_id']
    assert not {'email', 'name', 'attachments'}.intersection(accepted.get_json()['ticket_message'])


def test_foreign_inactive_and_admin_scope_contract(application, actors):
    client = application.test_client()

    # Cross-account reads look absent, while an inactive JWT principal fails the
    # real SessionService principal check before ticket code is reached.
    assert client.get(_API + '/TICKET-FOREIGN', headers=actors['owner_headers']).status_code == 404
    assert client.get(_API + '/TICKET-OWNED', headers=actors['foreign_headers']).status_code == 404
    assert client.get(_API + '/my', headers=actors['inactive_headers']).status_code == 401
    assert client.get(_API + '/admin/all').status_code == 401
    assert client.get(_API + '/admin/all', headers=actors['owner_headers']).status_code == 403

    scoped = client.get(_API + '/admin/all?per_page=100', headers=actors['admin_headers'])
    assert scoped.status_code == 200
    scoped_numbers = {ticket['ticket_number'] for ticket in scoped.get_json()['tickets']}
    assert 'TICKET-OWNED' in scoped_numbers
    assert 'TICKET-FOREIGN' not in scoped_numbers
    assert 'TICKET-GUEST' not in scoped_numbers
    assert client.put(
        _API + f"/admin/{actors['foreign_ticket_id']}/status",
        headers=actors['admin_headers'], json={'status': 'closed'},
    ).status_code == 404
    assert client.put(
        _API + f"/admin/{actors['owned_id']}/assign",
        headers=actors['admin_headers'], json={'assigned_to': actors['foreign_id']},
    ).status_code == 404
    assigned = client.put(
        _API + f"/admin/{actors['owned_id']}/assign",
        headers=actors['admin_headers'], json={'assigned_to': actors['owner_id']},
    )
    assert assigned.status_code == 200

    # Only the configured active/verified platform root gets the wide view; even
    # that explicit scope excludes unowned guest rows rather than guessing email.
    root = client.get(_API + '/admin/all?per_page=100', headers=actors['root_headers'])
    assert root.status_code == 200
    root_numbers = {ticket['ticket_number'] for ticket in root.get_json()['tickets']}
    assert {'TICKET-OWNED', 'TICKET-FOREIGN'}.issubset(root_numbers)
    assert 'TICKET-GUEST' not in root_numbers

    # The current TokenBlacklist table participates in real SessionService
    # authentication, so a revoked access token cannot reach support routes.
    from src.database import db
    from src.models import TokenBlacklist, User
    owner_token = actors['owner_headers']['Authorization'].split(' ', 1)[1]
    with application.app_context():
        token_payload = User.verify_token(owner_token, token_type='access')
        db.session.add(TokenBlacklist(
            jti=token_payload['jti'], token_type='access', user_id=actors['owner_id'],
            expires_at=datetime.utcnow() + timedelta(hours=1),
        ))
        db.session.commit()
    assert client.get(_API + '/my', headers=actors['owner_headers']).status_code == 401


def test_bounded_json_duplicate_keys_and_ticket_number_retry(application, actors, monkeypatch):
    from src.models.support_ticket import SupportTicket

    client = application.test_client()
    duplicate = b'{"subject":"one","subject":"two","description":"body"}'
    response = client.post(
        _API + '/my', headers=actors['owner_headers'], data=duplicate,
        content_type='application/json',
    )
    assert response.status_code == 400
    too_large = {'subject': 'x', 'description': 'x' * (32 * 1024)}
    response = client.post(_API + '/my', headers=actors['owner_headers'], json=too_large)
    assert response.status_code == 413

    candidates = iter(['TICKET-OWNED', 'TICKET-RETRIED'])
    monkeypatch.setattr(SupportTicket, 'generate_ticket_number', staticmethod(lambda: next(candidates)))
    retried = client.post(_API + '/my', headers=actors['owner_headers'], json={
        'subject': 'Retry collision', 'description': 'Database uniqueness retry',
    })
    assert retried.status_code == 201
    assert retried.get_json()['ticket']['ticket_number'] == 'TICKET-RETRIED'
