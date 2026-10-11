"""Focused model-level hierarchy safety regressions; uses an isolated SQLite database."""
from types import SimpleNamespace

import pytest
from flask import Flask
from sqlalchemy import text

from src.config import TestingConfig
from src.database import db
from src.models.user import User


@pytest.fixture
def hierarchy_model_app():
    app = Flask(__name__)
    app.config.from_object(TestingConfig)
    app.config['PLATFORM_ROOT_USER_ID']=1
    db.init_app(app)
    with app.app_context():
        db.metadata.create_all(db.engine, tables=[User.__table__])
    yield app
    with app.app_context():
        db.session.remove()
        db.metadata.drop_all(db.engine, tables=[User.__table__])
        db.engine.dispose()


def _user(user_id, path, tenant_id=1, parent_id=None, role='admin'):
    return User(
        id=user_id,
        email=f'user-{user_id}@example.test',
        password_hash='not-used',
        first_name='Hierarchy',
        last_name='Test',
        role=role,
        is_active=True,
        is_verified=True,
        tenant_id=tenant_id,
        parent_id=parent_id,
        tree_path=path,
    )


def _actor(user_id=1, path='1', tenant_id=1, parent_id=None, role='admin'):
    return SimpleNamespace(
        id=user_id,
        tree_path=path,
        tenant_id=tenant_id,
        parent_id=parent_id,
        role=role,
        can_create_same_role=role=='supermaster',
        is_active=True,
        is_verified=True,
    )


def test_hierarchy_model_filter_is_identity_and_slash_bounded_with_literal_wildcards(hierarchy_model_app):
    with hierarchy_model_app.app_context():
        db.session.add_all([
            _user(1, '7%_\\', tenant_id=1),
            _user(2, '7%_\\/2', tenant_id=1, parent_id=1),
            _user(3, '7%_\\', tenant_id=1),
            _user(4, '7XQ\\/4', tenant_id=1),
            _user(5, '7%_\\/2', tenant_id=2, parent_id=1),
        ])
        db.session.commit()

        condition = User.hierarchy_filter_for_entity(_actor(1, '7%_\\', tenant_id=1))
        visible_ids = [user.id for user in User.query.filter(condition).order_by(User.id).all()]

    assert visible_ids == [1, 2]


def test_hierarchy_model_filter_does_not_match_numeric_path_prefixes(hierarchy_model_app):
    with hierarchy_model_app.app_context():
        db.session.add_all([
            _user(2, '1/2', tenant_id=1),
            _user(3, '1/2/3', tenant_id=1, parent_id=2),
            _user(20, '1/20', tenant_id=1),
        ])
        db.session.commit()

        condition = User.hierarchy_filter_for_entity(_actor(2, '1/2', tenant_id=1))
        visible_ids = [user.id for user in User.query.filter(condition).order_by(User.id).all()]

    assert visible_ids == [2, 3]


@pytest.mark.parametrize('actor', [
    _actor(user_id=None),
    _actor(path=None),
    _actor(path=''),
    _actor(tenant_id=None),
    _actor(tenant_id=0),
])
def test_hierarchy_model_filter_fails_closed_for_incomplete_or_tenantless_nonroot_scope(
        hierarchy_model_app, actor):
    with hierarchy_model_app.app_context():
        db.session.add_all([_user(1, '1'), _user(2, '1/2', parent_id=1)])
        db.session.commit()
        condition = User.hierarchy_filter_for_entity(actor)
        assert User.query.filter(condition).count() == 0


def test_hierarchy_model_legacy_root_exemption_requires_a_complete_path(hierarchy_model_app):
    with hierarchy_model_app.app_context():
        db.session.add_all([_user(1, '1'), _user(2, '2', tenant_id=2)])
        db.session.commit()
        assert User.hierarchy_filter_for_entity(
            _actor(1, '1', tenant_id=None, parent_id=None, role='supermaster')
        ) is None
        missing_path = _actor(1, None, tenant_id=1, parent_id=None, role='supermaster')
        assert User.query.filter(User.hierarchy_filter_for_entity(missing_path)).count() == 0


def test_hierarchy_model_descendants_are_tenant_limited_and_counted_in_sql(hierarchy_model_app):
    with hierarchy_model_app.app_context():
        actor = _user(1, '1', tenant_id=1)
        db.session.add_all([
            actor,
            _user(2, '1/2', tenant_id=1, parent_id=1),
            _user(3, '1/20', tenant_id=1, parent_id=1),
            _user(4, '1/2/4', tenant_id=2, parent_id=2),
        ])
        db.session.commit()

        assert [user.id for user in actor.get_all_descendants()] == [2, 3]
        assert actor.get_downline_count() == 2


def test_hierarchy_model_ancestors_detect_direct_sql_cycle(hierarchy_model_app):
    with hierarchy_model_app.app_context():
        db.session.add_all([_user(1, '1'), _user(2, '1/2', parent_id=1)])
        db.session.commit()
        # Deliberately bypass ORM relationship events to model a corrupted stored cycle.
        db.session.execute(text('UPDATE users SET parent_id = :parent_id WHERE id = :id'),
                           {'parent_id': 2, 'id': 1})
        db.session.commit()
        db.session.expire_all()

        with pytest.raises(ValueError, match='cycle'):
            db.session.get(User, 1).get_ancestors()


def test_hierarchy_model_ancestors_have_a_hard_depth_limit_without_database_access():
    class Node:
        def __init__(self, node_id, parent=None):
            self.id = node_id
            self.parent = parent

    leaf = Node(1)
    current = leaf
    for node_id in range(2, User.MAX_ANCESTOR_DEPTH + 3):
        current = Node(node_id, current)
    leaf.parent = current

    with pytest.raises(ValueError, match='maximum depth'):
        User.get_ancestors(leaf)


def test_hierarchy_model_new_path_writer_rejects_legacy_dot_parent_path(hierarchy_model_app):
    with hierarchy_model_app.app_context():
        parent = _user(1, '1.2')
        parent.level = 1
        child = _user(3, None, parent_id=1)
        child.parent = parent

        with pytest.raises(ValueError, match='Cannot build hierarchy path'):
            User.update_tree_path(child)


@pytest.mark.parametrize('path,level',[(None,0),('',0),('1',True),('1',-1)])
def test_hierarchy_model_path_refusal_does_not_guess_or_change_state(hierarchy_model_app,path,level):
    with hierarchy_model_app.app_context():
        parent=_user(1,path)
        parent.level=level
        child=_user(3,'legacy-unchanged',parent_id=1)
        child.level=42
        child.parent=parent
        before=(parent.tree_path,parent.level,child.tree_path,child.level,child.parent_id,child.tenant_id)
        with pytest.raises(ValueError,match='Cannot build hierarchy path'):
            child.update_tree_path()
        assert (parent.tree_path,parent.level,child.tree_path,child.level,child.parent_id,child.tenant_id)==before
