"""Full-factory customer support and notification wiring, never production data."""
import pytest
from sqlalchemy import event

from src.database import db
from src.models.user import User
from src.models.tenant import Tenant
from src.models.token_blacklist import TokenBlacklist
from src.models.support_ticket import SupportTicket, TicketMessage
from src.models.notification import Notification, NotificationPreference, EmailQueue


@pytest.fixture
def journey_app():
    from src.app import create_app
    app = create_app('testing', config_overrides={
        'EXPANDED_HIERARCHY_ENABLED': False,
        'PLATFORM_ROOT_USER_ID': 1,
        'RATELIMIT_ENABLED': False,
        'PROPAGATE_EXCEPTIONS': False,
    })
    tables = [Tenant.__table__, User.__table__, TokenBlacklist.__table__,
              SupportTicket.__table__, TicketMessage.__table__, Notification.__table__,
              NotificationPreference.__table__, EmailQueue.__table__]
    with app.app_context():
        db.metadata.create_all(bind=db.engine, tables=tables)
        db.session.add_all([
            Tenant(id=1, name='Synthetic Brand', subdomain='synthetic', status='active'),
            Tenant(id=2, name='Other Brand', subdomain='other', status='active'),
        ])
        db.session.add_all([
            User(id=1, email='owner@example.invalid', first_name='Owner', last_name='Synthetic',
                 password_hash='not-a-password', role='supermaster', tenant_id=1, parent_id=None,
                 tree_path='1', level=0, is_active=True, is_verified=True, can_create_same_role=True),
            User(id=2, email='customer@example.invalid', first_name='Customer', last_name='Synthetic',
                 password_hash='not-a-password', role='trader', tenant_id=1, parent_id=1,
                 tree_path='1/2', level=1, is_active=True, is_verified=True),
            User(id=3, email='other@example.invalid', first_name='Other', last_name='Synthetic',
                 password_hash='not-a-password', role='trader', tenant_id=1, parent_id=1,
                 tree_path='1/3', level=1, is_active=True, is_verified=True),
            User(id=4, email='foreign@example.invalid', first_name='Foreign', last_name='Synthetic',
                 password_hash='not-a-password', role='trader', tenant_id=2, parent_id=1,
                 tree_path='1/4', level=1, is_active=True, is_verified=True),
        ])
        db.session.flush()
        db.session.add(SupportTicket(id=50, ticket_number='TICKET-SYNTHETIC', user_id=2,
            email='customer@example.invalid', name='Customer Synthetic', subject='Synthetic request',
            description='Synthetic description', category='general', priority='medium', status='open'))
        db.session.flush()
        db.session.add_all([
            TicketMessage(ticket_id=50, user_id=2, message='Visible synthetic reply',
                          is_staff=False, is_internal=False),
            TicketMessage(ticket_id=50, user_id=1, message='INTERNAL-SYNTHETIC-NOTE',
                          is_staff=True, is_internal=True),
            Notification(id=60, user_id=2, type='system', title='Synthetic notification',
                         message='Synthetic message', priority='normal', is_read=False, is_deleted=False),
            Notification(id=61, user_id=3, type='system', title='Other notification',
                         message='Other message', priority='normal', is_read=False, is_deleted=False),
        ])
        db.session.commit()
        app.journey_headers = {identity: {'Authorization': 'Bearer ' + db.session.get(User, identity).generate_access_token()}
                               for identity in [1, 2, 3, 4]}
    yield app
    with app.app_context():
        db.session.remove()
        db.metadata.drop_all(bind=db.engine, tables=list(reversed(tables)))


def test_journey_factory_owns_ticket_and_excludes_internal_messages(journey_app):
    client = journey_app.test_client()
    headers = journey_app.journey_headers[2]
    response = client.get('/api/v1/support/tickets/TICKET-SYNTHETIC', headers=headers)
    assert response.status_code == 200, response.get_json()
    assert 'INTERNAL-SYNTHETIC-NOTE' not in response.get_data(as_text=True)
    assert response.get_json()['messages'][0]['message'] == 'Visible synthetic reply'
    for identity in [3, 4]:
        response = client.get('/api/v1/support/tickets/TICKET-SYNTHETIC',
                              headers=journey_app.journey_headers[identity])
        assert response.status_code in [401, 404]
    response = client.get('/api/v1/support/tickets/TICKET-SYNTHETIC?email=customer@example.invalid',
                          headers=journey_app.journey_headers[3])
    assert response.status_code == 400
    assert client.get('/api/v1/support/tickets/TICKET-SYNTHETIC?email=customer@example.invalid').status_code == 401


def test_journey_factory_authenticated_create_list_reply(journey_app):
    client = journey_app.test_client()
    headers = journey_app.journey_headers[2]
    created = client.post('/api/v1/support/tickets/my', headers=headers,
                          json={'subject': 'New synthetic request', 'description': 'Synthetic help request',
                                'category': 'general', 'priority': 'medium'})
    assert created.status_code == 201, created.get_json()
    ticket = created.get_json()['ticket']
    assert ticket['user_id'] == 2
    assert 'email' not in ticket
    listing = client.get('/api/v1/support/tickets/my?page=1&per_page=10', headers=headers)
    assert listing.status_code == 200
    assert ticket['id'] in [row['id'] for row in listing.get_json()['tickets']]
    reply = client.post('/api/v1/support/tickets/' + ticket['ticket_number'] + '/messages',
                        headers=headers, json={'message': 'Synthetic follow-up'})
    assert reply.status_code == 201, reply.get_json()
    with journey_app.app_context():
        assert EmailQueue.query.count() == 0
        assert db.session.get(SupportTicket, ticket['id']).user_id == 2
        assert db.session.get(SupportTicket, ticket['id']).email == 'customer@example.invalid'


def test_journey_factory_notifications_are_personal_and_preferences_read_only(journey_app):
    client = journey_app.test_client()
    headers = journey_app.journey_headers[2]
    listing = client.get('/api/v1/notifications/?page=1&per_page=10', headers=headers)
    assert listing.status_code == 200, listing.get_json()
    assert [n['id'] for n in listing.get_json()['notifications']] == [60]
    assert client.get('/api/v1/notifications/unread-count', headers=headers).get_json()['count'] == 1
    writes = []
    with journey_app.app_context():
        engine = db.engine
    def record_statement(conn, cursor, statement, params, context, many):
        if statement.lstrip().split(None, 1)[0].upper() in ['INSERT', 'UPDATE', 'DELETE']:
            writes.append(statement)
    event.listen(engine, 'before_cursor_execute', record_statement)
    try:
        prefs = client.get('/api/v1/notifications/preferences', headers=headers)
        assert prefs.status_code == 200, prefs.get_json()
        assert writes == []
    finally:
        event.remove(engine, 'before_cursor_execute', record_statement)
    assert client.post('/api/v1/notifications/61/read', headers=headers).status_code == 404
    assert client.post('/api/v1/notifications/60/read', headers=headers).status_code == 200
    assert client.post('/api/v1/notifications/60/read', headers=headers).status_code == 200
    assert client.get('/api/v1/notifications/unread-count', headers=headers).get_json()['count'] == 0
    with journey_app.app_context():
        assert NotificationPreference.query.count() == 0
        assert not db.session.get(Notification, 61).is_read


def test_journey_factory_cookie_csrf_before_support_and_notification_mutations(journey_app):
    client = journey_app.test_client()
    with journey_app.app_context():
        token = db.session.get(User, 2).generate_access_token()
    client.set_cookie('access_token', token)
    assert client.get('/api/v1/support/tickets/my').status_code == 200
    for path, data in [('/api/v1/support/tickets/my', {'subject': 'Synthetic', 'description': 'Synthetic'}),
                       ('/api/v1/support/tickets/TICKET-SYNTHETIC/messages', {'message': 'Synthetic'}),
                       ('/api/v1/notifications/60/read', {})]:
        response = client.post(path, json=data)
        assert response.status_code == 403, (path, response.get_json())
    with journey_app.app_context():
        assert SupportTicket.query.count() == 1
        assert TicketMessage.query.count() == 2
        assert not db.session.get(Notification, 60).is_read


@pytest.mark.parametrize('kind', ['support', 'preferences'])
def test_journey_deep_json_is_bounded_client_error(journey_app, kind):
    client = journey_app.test_client()
    headers = journey_app.journey_headers[2]
    body = '{"x":' + '[' * 1500 + '0' + ']' * 1500 + '}'
    if kind == 'support':
        response = client.post('/api/v1/support/tickets/my', headers=headers, data=body, content_type='application/json')
    else:
        response = client.put('/api/v1/notifications/preferences', headers=headers, data=body, content_type='application/json')
    assert response.status_code == 400
    with journey_app.app_context():
        assert SupportTicket.query.count() == 1
        assert NotificationPreference.query.count() == 0


def test_journey_large_numeric_query_is_validation_not_server_error(journey_app):
    response = journey_app.test_client().get('/api/v1/notifications/?page=' + '9' * 5000,
                                              headers=journey_app.journey_headers[2])
    assert response.status_code == 400


@pytest.mark.parametrize('path', [
    '/api/v1/support/tickets/my', '/api/v1/support/tickets/TICKET-SYNTHETIC',
    '/api/v1/notifications/', '/api/v1/notifications/preferences',
])
def test_journey_support_list_does_not_flush_unrelated_pending_state(journey_app, path):
    with journey_app.app_context():
        pending = TicketMessage(ticket_id=50, message='Pending synthetic', is_internal=False)
        db.session.add(pending)
        writes = []
        def observe(conn, cursor, statement, params, context, many):
            if statement.lstrip().split(None, 1)[0].upper() in ['INSERT', 'UPDATE', 'DELETE']:
                writes.append(statement)
        event.listen(db.engine, 'before_cursor_execute', observe)
        try:
            result = journey_app.test_client().get(path, headers=journey_app.journey_headers[2])
            assert result.status_code == 200
            assert pending.id is None
            assert writes == []
        finally:
            event.remove(db.engine, 'before_cursor_execute', observe)
            db.session.rollback()
