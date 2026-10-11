"""Real-route regressions for CRM tenant and hierarchy containment.

This module intentionally creates only Tenant, User, TradingProgram, Lead,
LeadNote, and LeadActivity tables.  It does not load the legacy root conftest or
call metadata.create_all().
"""
from collections import Counter

import pytest
from flask import Flask
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from src.database import db
from src.models.lead import Lead, LeadActivity, LeadNote
from src.models.tenant import Tenant
from src.models.trading_program import TradingProgram
from src.models.user import User
from src.routes.crm import crm_bp
from src.services.auth_service import AuthService


@compiles(JSONB, 'sqlite')
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    """SQLite-only test adapter; production PostgreSQL JSONB remains unchanged."""
    return 'JSON'


_TABLES = (
    Tenant.__table__,
    User.__table__,
    TradingProgram.__table__,
    Lead.__table__,
    LeadActivity.__table__,
    LeadNote.__table__,
)


@pytest.fixture
def crm_app(monkeypatch):
    """A minimal real Flask app, real decorator, and real SQLAlchemy tables."""
    app = Flask('crm-scope-security')
    app.config.update(
        EXPANDED_HIERARCHY_ENABLED=True,
        TESTING=True,
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY='crm-scope-test-key',
    )
    db.init_app(app)
    app.register_blueprint(crm_bp, url_prefix='/api/v1/crm')

    # The real token_required decorator still looks up User.query.get().  Token
    # signature/blacklist infrastructure is outside the CRM tables under test.
    def verify_test_token(token, token_type='access'):
        try:
            user_id = int(token)
        except (TypeError, ValueError):
            return None
        return {'user_id': user_id, 'type': token_type}

    monkeypatch.setattr(User, 'verify_token', staticmethod(verify_test_token))
    monkeypatch.setattr(AuthService, 'is_token_blacklisted', lambda _token: False)

    with app.app_context():
        for table in _TABLES:
            table.create(bind=db.engine, checkfirst=False)
    yield app
    with app.app_context():
        db.session.remove()
        for table in reversed(_TABLES):
            table.drop(bind=db.engine, checkfirst=True)


@pytest.fixture
def crm_data(crm_app):
    """Seed two tenants, two unrelated tenant-A trees, and legacy unassigned data."""
    with crm_app.app_context():
        tenant_a = Tenant(id=1, name='Tenant A', subdomain='tenant-a')
        tenant_b = Tenant(id=2, name='Tenant B', subdomain='tenant-b')
        users = [
            # ``%`` is deliberate: it proves the CRM helper escapes LIKE paths.
            User(id=1, email='root@a.test', password_hash='x', first_name='Root', last_name='A',
                 role='master', tenant_id=1, tree_path='root%'),
            User(id=2, email='child@a.test', password_hash='x', first_name='Child', last_name='A',
                 role='agent', tenant_id=1, tree_path='root%/child'),
            # Same tenant but an unrelated path that an unescaped root% LIKE can match.
            User(id=3, email='other@a.test', password_hash='x', first_name='Other', last_name='A',
                 role='master', tenant_id=1, tree_path='rootX/other'),
            User(id=4, email='root@b.test', password_hash='x', first_name='Root', last_name='B',
                 role='master', tenant_id=2, tree_path='tenant-b'),
            User(id=5, email='missing@none.test', password_hash='x', first_name='Missing', last_name='Tenant',
                 role='master', tenant_id=None, tree_path='no-tenant'),
            # This role passes the legacy delete gate, but CRM scope must still
            # keep it inside its own tenant-A hierarchy.
            User(id=6, email='deleter@a.test', password_hash='x', first_name='Delete', last_name='A',
                 role='supermaster', tenant_id=1, tree_path='deleter%'),
        ]
        program_a = TradingProgram(id=1, tenant_id=1, name='A program', type='one_phase',
                                   account_size=10000, price=100)
        program_b = TradingProgram(id=2, tenant_id=2, name='B program', type='one_phase',
                                   account_size=10000, price=100)
        leads = [
            Lead(id=101, first_name='Own', last_name='Lead', email='own@lead.test', status='new', score=10,
                 assigned_to=1, interested_program_id=1),
            Lead(id=102, first_name='Child', last_name='Lead', email='child@lead.test', status='contacted', score=20,
                 assigned_to=2, interested_program_id=1),
            Lead(id=103, first_name='Other', last_name='Lead', email='other@lead.test', status='qualified', score=30,
                 assigned_to=3, interested_program_id=1),
            Lead(id=104, first_name='Foreign', last_name='Lead', email='foreign@lead.test', status='converted', score=40,
                 assigned_to=4, interested_program_id=2),
            Lead(id=105, first_name='Legacy', last_name='Unassigned', email='legacy@lead.test', status='lost', score=50,
                 assigned_to=None),
        ]
        db.session.add_all([tenant_a, tenant_b, *users, program_a, program_b, *leads])
        db.session.commit()
    return {'actor': 1, 'child': 2, 'other': 3, 'foreign': 4, 'missing_tenant': 5,
            'delete_actor': 6,
            'own_lead': 101, 'child_lead': 102, 'other_lead': 103,
            'foreign_lead': 104, 'unassigned_lead': 105, 'foreign_program': 2}


def _client_for(app, user_id):
    client = app.test_client()
    client.environ_base['HTTP_AUTHORIZATION'] = f'Bearer {user_id}'
    return client


def _database_state(app, lead_id):
    with app.app_context():
        lead = db.session.get(Lead, lead_id)
        return {
            'lead': (lead.status, lead.assigned_to, lead.interested_program_id, lead.lost_reason),
            'counts': Counter({
                'leads': Lead.query.count(),
                'notes': LeadNote.query.count(),
                'activities': LeadActivity.query.count(),
            }),
        }


def test_list_detail_stats_and_pipeline_share_tenant_hierarchy_scope(crm_app, crm_data):
    client = _client_for(crm_app, crm_data['actor'])

    listing = client.get('/api/v1/crm/leads')
    assert listing.status_code == 200
    visible_ids = {lead['id'] for lead in listing.get_json()['leads']}
    assert visible_ids == {crm_data['own_lead'], crm_data['child_lead']}

    assert client.get(f"/api/v1/crm/leads/{crm_data['own_lead']}").status_code == 200
    assert client.get(f"/api/v1/crm/leads/{crm_data['child_lead']}").status_code == 200
    for hidden in ('other_lead', 'foreign_lead', 'unassigned_lead'):
        assert client.get(f"/api/v1/crm/leads/{crm_data[hidden]}").status_code == 404

    stats = client.get('/api/v1/crm/stats')
    assert stats.status_code == 200
    assert stats.get_json()['total_leads'] == 2
    assert stats.get_json()['new_leads'] == 1
    assert stats.get_json()['contacted_leads'] == 1
    assert stats.get_json()['converted_leads'] == 0

    pipeline = client.get('/api/v1/crm/pipeline')
    assert pipeline.status_code == 200
    pipeline_ids = {
        lead['id']
        for bucket in pipeline.get_json()['pipeline'].values()
        for lead in bucket
    }
    assert pipeline_ids == visible_ids


def test_unassigned_and_missing_tenant_are_fail_closed(crm_app, crm_data):
    actor = _client_for(crm_app, crm_data['actor'])
    missing_tenant = _client_for(crm_app, crm_data['missing_tenant'])

    assert actor.get(f"/api/v1/crm/leads/{crm_data['unassigned_lead']}").status_code == 404
    assert missing_tenant.get('/api/v1/crm/leads').status_code == 403
    assert missing_tenant.get('/api/v1/crm/stats').status_code == 403
    assert missing_tenant.get('/api/v1/crm/pipeline').status_code == 403


def test_every_hidden_lead_mutation_is_denied_without_database_change(crm_app, crm_data):
    client = _client_for(crm_app, crm_data['actor'])
    delete_client = _client_for(crm_app, crm_data['delete_actor'])
    hidden_id = crm_data['foreign_lead']
    before = _database_state(crm_app, hidden_id)

    requests = (
        (client, 'post', f'/api/v1/crm/leads/{hidden_id}/notes', {'content': 'deny'}),
        (client, 'patch', f'/api/v1/crm/leads/{hidden_id}', {'status': 'lost'}),
        (delete_client, 'delete', f'/api/v1/crm/leads/{hidden_id}', None),
        (client, 'post', f'/api/v1/crm/leads/{hidden_id}/activities', {'activity_type': 'call'}),
        (client, 'post', f'/api/v1/crm/leads/{hidden_id}/convert', None),
        (client, 'post', f'/api/v1/crm/leads/{hidden_id}/lost', {'reason': 'other'}),
    )
    for request_client, method, path, payload in requests:
        response = getattr(request_client, method)(path, json=payload) if payload is not None else getattr(request_client, method)(path)
        assert response.status_code in {403, 404}
        assert _database_state(crm_app, hidden_id) == before

    # Creation validates the assignment before persisting anything.
    response = client.post('/api/v1/crm/leads', json={
        'first_name': 'Denied', 'last_name': 'Create', 'email': 'denied-create@lead.test',
        'assigned_to': crm_data['foreign'],
    })
    assert response.status_code == 403
    assert _database_state(crm_app, hidden_id) == before


def test_cross_tenant_assignment_and_program_are_rejected_before_own_lead_write(crm_app, crm_data):
    client = _client_for(crm_app, crm_data['actor'])
    own_id = crm_data['own_lead']
    before = _database_state(crm_app, own_id)

    reassignment = client.patch(f'/api/v1/crm/leads/{own_id}', json={
        'assigned_to': crm_data['foreign'], 'status': 'lost',
    })
    assert reassignment.status_code == 403
    assert _database_state(crm_app, own_id) == before

    program_change = client.patch(f'/api/v1/crm/leads/{own_id}', json={
        'interested_program_id': crm_data['foreign_program'], 'status': 'lost',
    })
    assert program_change.status_code == 403
    assert _database_state(crm_app, own_id) == before

    create_with_program = client.post('/api/v1/crm/leads', json={
        'first_name': 'Denied', 'last_name': 'Program', 'email': 'denied-program@lead.test',
        'interested_program_id': crm_data['foreign_program'],
    })
    assert create_with_program.status_code == 403
    assert _database_state(crm_app, own_id) == before


def test_valid_note_uses_user_id_and_activity_ignores_unmapped_metadata(crm_app, crm_data):
    client = _client_for(crm_app, crm_data['actor'])
    lead_id = crm_data['own_lead']

    note = client.post(f'/api/v1/crm/leads/{lead_id}/notes', json={'content': 'Scoped note'})
    assert note.status_code == 201
    notes = client.get(f'/api/v1/crm/leads/{lead_id}/notes')
    assert notes.status_code == 200
    assert notes.get_json()['notes'][0]['created_by'] == 'Root A'

    activity = client.post(f'/api/v1/crm/leads/{lead_id}/activities', json={
        'activity_type': 'call', 'description': 'Callback scheduled', 'metadata': {'legacy': 'ignored'},
    })
    assert activity.status_code == 201
    assert activity.get_json()['activity']['activity_type'] == 'call'
