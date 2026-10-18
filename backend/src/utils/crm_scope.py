"""Fail-closed tenant and hierarchy scoping for CRM lead access.

CRM leads predate a tenant_id column.  Until that migration is complete, a lead is
owned by the tenant and hierarchy of its assigned user.  Unassigned leads (and
leads whose assigned user no longer exists) are deliberately excluded.
"""
from sqlalchemy import false, or_

from src.models.lead import Lead
from src.models.user import User


def tenant_id_for(current_user):
    """Return the authenticated user's tenant id, or ``None`` to deny access."""
    tenant_id = getattr(current_user, 'tenant_id', None)
    user_id = getattr(current_user, 'id', None)
    if tenant_id is None or user_id is None:
        return None
    return tenant_id


def _escape_like(value):
    """Escape a tree path before using it in a SQL LIKE predicate."""
    return value.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')


def _permitted_user_clause(current_user):
    """Return self plus a lexically bounded descendant predicate.

    The slash suffix prevents ``1/2`` from matching a sibling such as ``1/20``;
    explicit escaping prevents stored legacy ``%`` and ``_`` path characters
    from broadening the SQL predicate.
    """
    user_id = getattr(current_user, 'id', None)
    if user_id is None:
        return false()

    clauses = [User.id == user_id]
    tree_path = getattr(current_user, 'tree_path', None)
    if isinstance(tree_path, str) and tree_path:
        pattern = f"{_escape_like(tree_path)}/%"
        clauses.append(User.tree_path.like(pattern, escape='\\'))
    return or_(*clauses)


def scoped_users(current_user, query=None):
    """Constrain a user query to the actor's tenant and permitted hierarchy."""
    tenant_id = tenant_id_for(current_user)
    query = query if query is not None else User.query
    if tenant_id is None:
        return query.filter(false())
    return query.filter(
        User.tenant_id == tenant_id,
        _permitted_user_clause(current_user),
    )


def scoped_leads(current_user, query=None):
    """Constrain leads to assigned users in the actor's tenant/downline.

    If a future Lead model exposes ``tenant_id``, it is required to agree with
    the assigned user's tenant as a defense in depth.  The present model has no
    such column, so this remains compatible with the deployed schema.
    """
    tenant_id = tenant_id_for(current_user)
    query = query if query is not None else Lead.query
    if tenant_id is None:
        return query.filter(false())

    query = query.join(User, Lead.assigned_to == User.id).filter(
        User.tenant_id == tenant_id,
        _permitted_user_clause(current_user),
    )
    lead_tenant_id = getattr(Lead, 'tenant_id', None)
    if lead_tenant_id is not None:
        query = query.filter(lead_tenant_id == tenant_id)
    return query


def get_scoped_lead(current_user, lead_id):
    """Fetch one visible lead without an unscoped primary-key lookup."""
    if tenant_id_for(current_user) is None:
        return None
    return scoped_leads(current_user).filter(Lead.id == lead_id).first()


def get_assignment_target(current_user, user_id):
    """Return a target user only when it is in the actor's tenant/downline."""
    if tenant_id_for(current_user) is None:
        return None
    return scoped_users(current_user).filter(User.id == user_id).first()


def get_tenant_program(current_user, program_id):
    """Return a program only when it belongs to the actor's tenant."""
    tenant_id = tenant_id_for(current_user)
    if tenant_id is None:
        return None
    from src.models.trading_program import TradingProgram
    return TradingProgram.query.filter(
        TradingProgram.id == program_id,
        TradingProgram.tenant_id == tenant_id,
    ).first()
