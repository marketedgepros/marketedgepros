"""Focused real-route regressions for bounded hierarchy route safety.

The module uses the production ``token_required`` decorator and mapped ``User``
model, but only creates synthetic Tenant/User rows in an in-memory SQLite app.
No production app factory, credentials, network, or external provider is used.
"""
from collections import Counter

import pytest
from flask import Flask
from sqlalchemy import event, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

from src.database import db
from src.models.tenant import Tenant
from src.models.user import User
from src.routes.hierarchy import hierarchy_bp
from src.services.session_service import SessionService
from src.utils.hierarchy_scoping import init_hierarchy_scoping


@compiles(JSONB, 'sqlite')
def _compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    """SQLite-only adapter; production PostgreSQL JSONB is not changed."""
    return 'JSON'


_TABLES = (Tenant.__table__, User.__table__)


@pytest.fixture
def hierarchy_app(monkeypatch):
    """Minimal real Flask host with the real decorator and scoped ORM listener."""
    app = Flask('hierarchy-routes-security')
    app.config.update(
        TESTING=True,
        EXPANDED_HIERARCHY_ENABLED=True,
        SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        JWT_SECRET_KEY='hierarchy-routes-synthetic-key',
    )
    db.init_app(app)
    app.register_blueprint(hierarchy_bp, url_prefix='/api/v1/hierarchy')

    def authenticate_test_token(token, token_type='access'):
        if token_type != 'access':
            raise ValueError('wrong token type')
        try:
            user_id = int(token)
        except (TypeError, ValueError) as exc:
            raise ValueError('invalid synthetic token') from exc
        user = db.session.get(User, user_id)
        if user is None:
            raise ValueError('unknown synthetic user')
        return user, {'user_id': user.id, 'type': 'access'}

    # The route still traverses the real decorator.  Only session cryptography
    # is outside this focused User/Tenant table set.
    monkeypatch.setattr(SessionService, 'authenticate', staticmethod(authenticate_test_token))
    with app.app_context():
        init_hierarchy_scoping(db, User)
        for table in _TABLES:
            table.create(bind=db.engine, checkfirst=False)
    yield app
    with app.app_context():
        db.session.remove()
        for table in reversed(_TABLES):
            table.drop(bind=db.engine, checkfirst=True)


@pytest.fixture
def hierarchy_data(hierarchy_app):
    """Two tenants, two tenant-A trees, a root reviewer, and incomplete actors."""
    with hierarchy_app.app_context():
        tenant_a = Tenant(id=1, name='Synthetic Tenant A', subdomain='synthetic-a')
        tenant_b = Tenant(id=2, name='Synthetic Tenant B', subdomain='synthetic-b')
        users = [
            # '%' proves that every route-level LIKE predicate escapes legacy paths.
            User(id=1, email='actor@example.com', password_hash='x', first_name='Actor',
                 last_name='A', role='master', tenant_id=1, tree_path='actor%', level=0),
            # Deliberately wrong stored levels: tree depth must derive from path.
            User(id=2, email='child@example.com', password_hash='x', first_name='Child',
                 last_name='A', role='agent', tenant_id=1, parent_id=1,
                 tree_path='actor%/child', level=47),
            User(id=3, email='grand@example.com', password_hash='x', first_name='Grand',
                 last_name='A', role='trader', tenant_id=1, parent_id=2,
                 tree_path='actor%/child/grand', level=2),
            # Same tenant, but not below actor 1.  An unescaped 'actor%' query leaks it.
            User(id=4, email='sibling@example.com', password_hash='x', first_name='Sibling',
                 last_name='A', role='master', tenant_id=1, tree_path='actorX/sibling', level=1),
            User(id=5, email='foreign@example.com', password_hash='x', first_name='Foreign',
                 last_name='B', role='master', tenant_id=2, tree_path='foreign', level=0),
            User(id=6, email='missing-path@example.com', password_hash='x', first_name='Missing',
                 last_name='Path', role='master', tenant_id=1, tree_path=None, level=0),
            User(id=7, email='missing-tenant@example.com', password_hash='x', first_name='Missing',
                 last_name='Tenant', role='master', tenant_id=None, tree_path='no-tenant', level=0),
            # A legacy global-root role still receives only its own hierarchy here.
            User(id=8, email='root@example.com', password_hash='x', first_name='Root',
                 last_name='A', role='supermaster', tenant_id=1, tree_path='root', level=0),
            User(id=9, email='root-child@example.com', password_hash='x', first_name='RootChild',
                 last_name='A', role='master', tenant_id=1, parent_id=8,
                 tree_path='root/root-child', level=1),
            # Canonical records exist separately from legacy readable paths so
            # creation can prove it uses the model's canonical writer.
            User(id=10, email='canonical@example.com', password_hash='x', first_name='Canonical',
                 last_name='A', role='master', tenant_id=1, tree_path='10', level=0),
            User(id=11, email='canonical-child@example.com', password_hash='x', first_name='CanonicalChild',
                 last_name='A', role='agent', tenant_id=1, parent_id=10,
                 tree_path='10/11', level=1),
            User(id=12, email='dot-path@example.com', password_hash='x', first_name='Dot',
                 last_name='Path', role='master', tenant_id=1, tree_path='12.bad', level=0),
        ]
        db.session.add_all([tenant_a, tenant_b, *users])
        db.session.commit()
        db.session.remove()
    return {
        'actor': 1,
        'child': 2,
        'grandchild': 3,
        'sibling': 4,
        'foreign': 5,
        'missing_path': 6,
        'missing_tenant': 7,
        'root': 8,
        'root_child': 9,
        'canonical': 10,
        'canonical_child': 11,
        'dot_path': 12,
    }


def _client_for(app, user_id):
    client = app.test_client()
    client.environ_base['HTTP_AUTHORIZATION'] = f'Bearer {user_id}'
    return client


def _user_count(app):
    with app.app_context():
        # There is no request scope in this assertion; it observes synthetic rows.
        return db.session.query(User).count()


def _user_state(app, user_id):
    with app.app_context():
        user = db.session.get(User, user_id)
        return (user.first_name, user.role, user.tenant_id, user.tree_path)


def test_real_decorator_injects_current_user_into_every_hierarchy_handler(hierarchy_app, hierarchy_data):
    """All seven current handlers accept the decorator-injected principal."""
    client = _client_for(hierarchy_app, hierarchy_data['canonical'])

    assert client.get('/api/v1/hierarchy/my-downline').status_code == 200
    assert client.get('/api/v1/hierarchy/my-direct-team').status_code == 200
    assert client.get('/api/v1/hierarchy/user/11').status_code == 200
    assert client.put('/api/v1/hierarchy/user/11', json={'first_name': 'Changed'}).status_code == 200
    assert client.get('/api/v1/hierarchy/tree?max_depth=2').status_code == 200
    assert client.get('/api/v1/hierarchy/stats').status_code == 200

    created = client.post('/api/v1/hierarchy/create-user', json={
        'email': 'decorator-created@example.com',
        'password': 'StrongPass1!',
        'first_name': 'Decorator',
        'last_name': 'Created',
        'role': 'trader',
    })
    assert created.status_code == 201
    assert created.get_json()['user']['parent_id'] == hierarchy_data['canonical']


def test_explicit_subtree_query_hides_sibling_foreign_and_global_root_records(hierarchy_app, hierarchy_data):
    actor = _client_for(hierarchy_app, hierarchy_data['actor'])
    root = _client_for(hierarchy_app, hierarchy_data['root'])

    visible = actor.get('/api/v1/hierarchy/user/2')
    assert visible.status_code == 200
    assert visible.get_json()['downline_count'] == 1

    before = _user_state(hierarchy_app, hierarchy_data['sibling'])
    for hidden in (hierarchy_data['sibling'], hierarchy_data['foreign'], hierarchy_data['root']):
        assert actor.get(f'/api/v1/hierarchy/user/{hidden}').status_code == 404
        assert actor.put(
            f'/api/v1/hierarchy/user/{hidden}', json={'first_name': 'Must Not Write'}
        ).status_code == 404
    assert _user_state(hierarchy_app, hierarchy_data['sibling']) == before

    # The legacy parentless supermaster no longer expands this HTTP endpoint.
    root_downline = root.get('/api/v1/hierarchy/my-downline')
    assert root_downline.status_code == 200
    root_ids = {
        user['id']
        for users in root_downline.get_json()['downline_by_level'].values()
        for user in users
    }
    assert root_ids == {hierarchy_data['root_child']}
    assert root.get(f"/api/v1/hierarchy/user/{hierarchy_data['actor']}").status_code == 404


def test_incomplete_owner_scope_fails_closed_and_never_creates_unknown_brand_users(hierarchy_app, hierarchy_data):
    missing_path = _client_for(hierarchy_app, hierarchy_data['missing_path'])
    missing_tenant = _client_for(hierarchy_app, hierarchy_data['missing_tenant'])
    before = _user_count(hierarchy_app)
    payload = {
        'email': 'not-created@example.com', 'password': 'StrongPass1!',
        'first_name': 'No', 'last_name': 'Tenant', 'role': 'trader',
    }

    for path in ('/my-downline', '/my-direct-team', '/tree', '/stats'):
        assert missing_path.get('/api/v1/hierarchy' + path).status_code == 403
    assert missing_path.get('/api/v1/hierarchy/user/2').status_code == 403
    assert missing_tenant.post('/api/v1/hierarchy/create-user', json=payload).status_code == 403
    assert _user_count(hierarchy_app) == before


def test_create_validates_json_and_binds_known_actor_tenant_without_body_authority(hierarchy_app, hierarchy_data):
    client = _client_for(hierarchy_app, hierarchy_data['canonical'])
    before = _user_count(hierarchy_app)

    for payload in (None, [], 'not-an-object'):
        response = client.post('/api/v1/hierarchy/create-user', json=payload)
        assert response.status_code == 400
    assert client.post('/api/v1/hierarchy/create-user', json={
        'email': 'wrong-tenant@example.com', 'password': 'StrongPass1!',
        'first_name': 'Wrong', 'last_name': 'Tenant', 'role': 'trader', 'tenant_id': 2,
    }).status_code == 403
    child_before = _user_state(hierarchy_app, hierarchy_data['canonical_child'])
    assert client.put(f"/api/v1/hierarchy/user/{hierarchy_data['canonical_child']}", json=[]).status_code == 400
    assert client.put(f"/api/v1/hierarchy/user/{hierarchy_data['canonical_child']}", json={
        'tenant_id': 2, 'first_name': 'Must Not Write',
    }).status_code == 403
    assert _user_state(hierarchy_app, hierarchy_data['canonical_child']) == child_before
    # Role authorization occurs before any allowed field is staged or flushed.
    assert client.put(f"/api/v1/hierarchy/user/{hierarchy_data['canonical_child']}", json={
        'first_name': 'Must Not Write', 'role': 'master',
    }).status_code == 403
    assert _user_state(hierarchy_app, hierarchy_data['canonical_child']) == child_before
    # A request body cannot manufacture the same-role capability.
    assert client.post('/api/v1/hierarchy/create-user', json={
        'email': 'same-role@example.com', 'password': 'StrongPass1!',
        'first_name': 'Same', 'last_name': 'Role', 'role': 'master',
        'can_create_same_role': True,
    }).status_code == 403
    assert _user_count(hierarchy_app) == before

    response = client.post('/api/v1/hierarchy/create-user', json={
        'email': 'tenant-bound@example.com', 'password': 'StrongPass1!',
        'first_name': 'Tenant', 'last_name': 'Bound', 'role': 'trader', 'tenant_id': 1,
    })
    assert response.status_code == 201
    created_id = response.get_json()['user']['id']
    with hierarchy_app.app_context():
        created = db.session.get(User, created_id)
        assert created.tenant_id == 1
        assert created.parent_id == hierarchy_data['canonical']
        assert created.tree_path == f'10/{created_id}'
        assert created.can_create_same_role is False


def test_legacy_readable_paths_cannot_create_noncanonical_children(hierarchy_app, hierarchy_data):
    before = _user_count(hierarchy_app)
    payload = {
        'password': 'StrongPass1!', 'first_name': 'Blocked', 'last_name': 'Child', 'role': 'trader',
    }
    for actor_id, email in (
        (hierarchy_data['actor'], 'wild-path-child@example.com'),
        (hierarchy_data['dot_path'], 'dot-path-child@example.com'),
    ):
        response = _client_for(hierarchy_app, actor_id).post(
            '/api/v1/hierarchy/create-user', json={**payload, 'email': email}
        )
        assert response.status_code == 400
        assert response.get_json()['error'] == 'Unable to create hierarchy path'
        assert _user_count(hierarchy_app) == before


def test_direct_team_page_bounds_and_union_descendant_count_are_safe(hierarchy_app, hierarchy_data):
    client = _client_for(hierarchy_app, hierarchy_data['actor'])
    for suffix in ('?page=0', '?page=nope', '?per_page=0', '?per_page=101'):
        assert client.get('/api/v1/hierarchy/my-direct-team' + suffix).status_code == 400

    response = client.get('/api/v1/hierarchy/my-direct-team?page=1&per_page=20')
    assert response.status_code == 200
    users = response.get_json()['users']
    assert [user['id'] for user in users] == [hierarchy_data['child']]
    assert users[0]['children_count'] == 1
    assert users[0]['downline_count'] == 1


def test_direct_team_query_count_is_constant_for_twenty_members(hierarchy_app, hierarchy_data):
    with hierarchy_app.app_context():
        for user_id in range(200, 220):
            db.session.add(User(
                id=user_id, email=f'team-{user_id}@example.com', password_hash='x',
                first_name='Team', last_name=str(user_id), role='trader', tenant_id=1,
                parent_id=hierarchy_data['actor'], tree_path=f'actor%/team-{user_id}', level=1,
            ))
        db.session.commit()
        db.session.remove()

    statements = Counter()

    def count_sql(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements[statement] += 1

    with hierarchy_app.app_context():
        engine = db.engine
    event.listen(engine, 'before_cursor_execute', count_sql)
    try:
        response = _client_for(hierarchy_app, hierarchy_data['actor']).get(
            '/api/v1/hierarchy/my-direct-team?per_page=100'
        )
    finally:
        event.remove(engine, 'before_cursor_execute', count_sql)
    assert response.status_code == 200
    assert len(response.get_json()['users']) == 21
    assert sum(statements.values()) <= 5


def test_tree_is_bounded_iterative_path_derived_and_cycle_safe(hierarchy_app, hierarchy_data):
    client = _client_for(hierarchy_app, hierarchy_data['actor'])
    for suffix in ('?max_depth=0', '?max_depth=11', '?max_depth=wrong'):
        assert client.get('/api/v1/hierarchy/tree' + suffix).status_code == 400

    tree = client.get('/api/v1/hierarchy/tree?max_depth=2')
    assert tree.status_code == 200
    body = tree.get_json()
    assert body['total_downline'] == 2
    assert body['tree']['children'][0]['id'] == hierarchy_data['child']
    assert body['tree']['children'][0]['children'][0]['id'] == hierarchy_data['grandchild']

    # Synthetic corruption bypasses ORM cycle listeners.  The route must still
    # terminate and must not attach a malformed cyclic component to the root.
    with hierarchy_app.app_context():
        db.session.execute(text('UPDATE users SET parent_id = 3 WHERE id = 2'))
        db.session.execute(text('UPDATE users SET parent_id = 2 WHERE id = 3'))
        db.session.commit()
        db.session.remove()
    cycle_response = client.get('/api/v1/hierarchy/tree?max_depth=2')
    assert cycle_response.status_code == 200
    assert cycle_response.get_json()['tree']['children'] == []


def test_tree_query_count_is_constant_for_twenty_nodes(hierarchy_app, hierarchy_data):
    """The tree does auth load + count + bounded node fetch + child aggregate."""
    with hierarchy_app.app_context():
        for user_id in range(100, 120):
            db.session.add(User(
                id=user_id, email=f'node-{user_id}@example.com', password_hash='x',
                first_name='Node', last_name=str(user_id), role='trader', tenant_id=1,
                parent_id=hierarchy_data['actor'], tree_path=f'actor%/node-{user_id}', level=1,
            ))
        db.session.commit()
        db.session.remove()

    statements = Counter()

    def count_sql(_connection, _cursor, statement, _parameters, _context, _executemany):
        statements[statement] += 1

    with hierarchy_app.app_context():
        engine = db.engine
    event.listen(engine, 'before_cursor_execute', count_sql)
    try:
        response = _client_for(hierarchy_app, hierarchy_data['actor']).get(
            '/api/v1/hierarchy/tree?max_depth=1'
        )
    finally:
        event.remove(engine, 'before_cursor_execute', count_sql)
    assert response.status_code == 200
    assert response.get_json()['tree']['children_count'] == 21
    assert sum(statements.values()) <= 4


def test_tree_rejects_an_over_cap_result_instead_of_returning_a_partial_tree(hierarchy_app, hierarchy_data):
    with hierarchy_app.app_context():
        for user_id in range(1000, 1501):
            db.session.add(User(
                id=user_id, email=f'cap-{user_id}@example.com', password_hash='x',
                first_name='Cap', last_name=str(user_id), role='trader', tenant_id=1,
                parent_id=hierarchy_data['actor'], tree_path=f'actor%/cap-{user_id}', level=1,
            ))
        db.session.commit()
        db.session.remove()

    response = _client_for(hierarchy_app, hierarchy_data['actor']).get(
        '/api/v1/hierarchy/tree?max_depth=1'
    )
    assert response.status_code == 413
    assert response.get_json()['code'] == 'HIERARCHY_TREE_TOO_LARGE'
