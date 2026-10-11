"""Request-scoped ORM hierarchy criteria, with missing-scope refusal.

This is defense in depth for mapped hierarchy entities, not a complete access
control system: raw SQL, identity-map hits and instance flushes still require
explicit route/service authorization. Trusted server bypasses are kept explicit.
Global scope is restricted to the configured stable platform-owner ID with an
existing verified, active supermaster capability. No account is promoted here.
"""
from dataclasses import dataclass

from flask import current_app, g, has_app_context, has_request_context
from sqlalchemy import event, false, or_, select
from sqlalchemy.orm import with_loader_criteria

_MISSING_PARENT = object()


def escape_hierarchy_path(path):
    """Treat stored legacy wildcard characters literally in LIKE predicates."""
    return path.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def complete_hierarchy_scope(actor):
    user_id = getattr(actor, 'id', None)
    role = getattr(actor, 'role', None)
    path = getattr(actor, 'tree_path', None)
    return (
        isinstance(user_id, int) and not isinstance(user_id, bool) and user_id > 0
        and isinstance(role, str) and bool(role.strip())
        and isinstance(path, str) and bool(path.strip()) and len(path) <= 500
    )


def configured_platform_root_id():
    if not has_app_context():
        return None
    value = current_app.config.get('PLATFORM_ROOT_USER_ID')
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    if isinstance(value, str) and value.isascii() and value.isdecimal() and len(value) <= 10:
        identity = int(value)
        if identity > 0 and str(identity) == value:
            return identity
    return None


def platform_root_scope(actor):
    """One stable owner; never infer global authority from email or parentlessness."""
    return (
        complete_hierarchy_scope(actor)
        and actor.id == configured_platform_root_id()
        and actor.role == 'supermaster'
        and getattr(actor, 'parent_id', _MISSING_PARENT) is None
        and getattr(actor, 'can_create_same_role', False) is True
        and getattr(actor, 'is_active', False) is True
        and getattr(actor, 'is_verified', False) is True
    )


def legacy_root_scope(actor):
    """Compatibility name; all old call sites now use the one-owner predicate."""
    return platform_root_scope(actor)


def tenant_hierarchy_scope(actor):
    """Require known actor ownership for non-global hierarchy access."""
    tenant_id = getattr(actor, 'tenant_id', None)
    return complete_hierarchy_scope(actor) and isinstance(tenant_id, int) and not isinstance(tenant_id, bool) and tenant_id > 0


@dataclass(frozen=True)
class _ScopeData:
    id: object
    role: object
    tree_path: object
    parent_id: object
    tenant_id: object
    can_create_same_role: object
    is_active: object
    is_verified: object


class HierarchyScopedMixin:
    __hierarchy_user_fk__ = 'user_id'

    @classmethod
    def hierarchy_filter_for_entity(cls, current_user):
        from src.models.user import User
        if not complete_hierarchy_scope(current_user):
            return false()
        if legacy_root_scope(current_user):
            return None
        if not tenant_hierarchy_scope(current_user):
            return false()
        path = escape_hierarchy_path(current_user.tree_path)
        users = select(User.id).where(User.tenant_id == current_user.tenant_id, or_(
            User.id == current_user.id,
            User.tree_path.like(f'{path}/%', escape='\\'),
        ))
        return getattr(cls, cls.__hierarchy_user_fk__).in_(users)


def set_request_hierarchy_scope(session, current_user):
    """Snapshot scalar principal fields before ORM events; never lazy-load in hook."""
    if has_request_context():
        g.hierarchy_scope_user = current_user
        g.hierarchy_scope_user_id = getattr(current_user, 'id', None)
        g.hierarchy_scope_role = getattr(current_user, 'role', None)
        g.hierarchy_scope_tree_path = getattr(current_user, 'tree_path', None)
        g.hierarchy_scope_parent_id = getattr(current_user, 'parent_id', _MISSING_PARENT)
        g.hierarchy_scope_tenant_id = getattr(current_user, 'tenant_id', None)
        g.hierarchy_scope_capability = getattr(current_user, 'can_create_same_role', False)
        g.hierarchy_scope_active = getattr(current_user, 'is_active', False)
        g.hierarchy_scope_verified = getattr(current_user, 'is_verified', False)
        g.hierarchy_scope_enabled = True


def without_hierarchy_scope(session):
    """Trusted server-side context only; this is not a user-selectable permission."""
    class _ScopeDisabler:
        def __enter__(self):
            if has_request_context():
                self._previous_state = getattr(g, 'hierarchy_scope_enabled', False)
                g.hierarchy_scope_enabled = False
            return self

        def __exit__(self, *args):
            if has_request_context():
                g.hierarchy_scope_enabled = getattr(self, '_previous_state', False)
    return _ScopeDisabler()


def init_hierarchy_scoping(db, user_model):
    """Register exactly one handler for this database's scoped Session target."""
    previous = getattr(db, '_hierarchy_scope_listener', None)
    if previous is not None:
        if previous[0] is not user_model:
            raise RuntimeError('Hierarchy scope listener already uses another user model')
        if event.contains(db.session, 'do_orm_execute', previous[1]):
            return

    def _apply_hierarchy_scope(execute_state):
        if not has_request_context() or not getattr(g, 'hierarchy_scope_enabled', False):
            return
        if execute_state.execution_options.get('skip_hierarchy_scope', False):
            return  # Explicit, trusted server-side bypass, never HTTP input.
        scope = _ScopeData(
            getattr(g, 'hierarchy_scope_user_id', None),
            getattr(g, 'hierarchy_scope_role', None),
            getattr(g, 'hierarchy_scope_tree_path', None),
            getattr(g, 'hierarchy_scope_parent_id', _MISSING_PARENT),
            getattr(g, 'hierarchy_scope_tenant_id', None),
            getattr(g, 'hierarchy_scope_capability', False),
            getattr(g, 'hierarchy_scope_active', False),
            getattr(g, 'hierarchy_scope_verified', False),
        )
        if legacy_root_scope(scope):
            return
        if not (execute_state.is_select or execute_state.is_update or execute_state.is_delete):
            return
        # Applying criteria to mapped classes also covers aliases, relationship
        # loads and joins that hide User from the primary column descriptions.
        # The registry is small and bounded by the application's model set.
        for mapper in tuple(db.Model.registry.mappers):
            model = mapper.class_
            if not issubclass(model, HierarchyScopedMixin):
                continue
            condition = false() if not tenant_hierarchy_scope(scope) else model.hierarchy_filter_for_entity(scope)
            if condition is None:
                # Only the root exemption above may mean no criteria. A child
                # supermaster or incomplete scope must not inherit an exemption.
                condition = false()
            execute_state.statement = execute_state.statement.options(
                with_loader_criteria(model, condition, include_aliases=True, propagate_to_loaders=True)
            )

    event.listen(db.session, 'do_orm_execute', _apply_hierarchy_scope)
    db._hierarchy_scope_listener = (user_model, _apply_hierarchy_scope)


def unscoped_query(query):
    """Explicit trusted internal query bypass; callers own its authorization."""
    return query.execution_options(skip_hierarchy_scope=True)
