"""Hierarchy routes for the bounded, tenant-owned MLM structure."""
from collections import defaultdict, deque
from datetime import datetime

from email_validator import EmailNotValidError, validate_email
from flask import Blueprint, jsonify, request, current_app
from sqlalchemy import case, false, func, literal, or_, union_all
from sqlalchemy.exc import IntegrityError

from src.database import db
from src.models.user import User
from src.utils.decorators import token_required
from src.utils.hierarchy_scoping import (
    escape_hierarchy_path,
    tenant_hierarchy_scope,
)
from src.utils.validators import validate_password_strength


hierarchy_bp = Blueprint('hierarchy', __name__)

@hierarchy_bp.before_request
def expanded_hierarchy_gate():
    if not current_app.config.get('EXPANDED_HIERARCHY_ENABLED', False):
        return jsonify({'error': 'Expanded hierarchy is disabled in launch mode', 'code': 'EXPANDED_HIERARCHY_DISABLED'}), 409


# A hierarchy response must never fan out without a bounded failure mode.  The
# client currently has no pagination contract for these two grouped/tree views.
MAX_DOWNLINE_NODES = 1000
MAX_TREE_NODES = 500
MAX_TREE_DEPTH = 10
MAX_DIRECT_TEAM_PAGE_SIZE = 100
MAX_DIRECT_TEAM_OFFSET = 10000


def _scope_required(actor):
    """Return a fail-closed response when the authenticated owner is incomplete."""
    if tenant_hierarchy_scope(actor):
        return None
    return jsonify({
        'error': 'A complete hierarchy and tenant scope is required',
        'code': 'HIERARCHY_SCOPE_REQUIRED',
    }), 403


def _downline_query(actor, include_self=False):
    """Build the explicit route-level own-subtree query.

    The request-wide ORM criterion is defense in depth.  Hierarchy endpoints
    still bind every resource query to this actor's literal path and tenant so
    the legacy parentless-root ORM exemption cannot expand an HTTP response.
    """
    if not tenant_hierarchy_scope(actor):
        return User.query.filter(false())

    escaped_path = escape_hierarchy_path(actor.tree_path)
    descendant = User.tree_path.like(f'{escaped_path}/%', escape='\\')
    predicate = or_(User.id == actor.id, descendant) if include_self else descendant
    return User.query.filter(User.tenant_id == actor.tenant_id, predicate)


def _relative_path_depth(actor, user):
    """Return a path-derived depth after the caller has applied subtree scope."""
    return user.tree_path.count('/') - actor.tree_path.count('/')


def _path_depth_expression(actor):
    """Portable SQLite/PostgreSQL relative slash count; do not trust ``level``."""
    return (
        func.length(User.tree_path)
        - func.length(func.replace(User.tree_path, '/', ''))
        - actor.tree_path.count('/')
    )


def _children_count_map(actor, parent_ids):
    """Count direct children for a bounded visible cohort in one aggregate query."""
    if not parent_ids:
        return {}
    rows = (
        _downline_query(actor)
        .filter(User.parent_id.in_(parent_ids))
        .with_entities(User.parent_id, func.count(User.id))
        .group_by(User.parent_id)
        .all()
    )
    return {parent_id: int(count) for parent_id, count in rows}


def _downline_count_map(actor, users):
    """Count descendants for a bounded response cohort in one round trip.

    A branch is built from ``_downline_query`` for every visible user, so every
    count retains the explicit actor tenant/subtree predicate.  This avoids an
    alias self-join and its potentially unsafe loader-criterion interactions.
    """
    if not users:
        return {}
    if len(users) > MAX_DIRECT_TEAM_PAGE_SIZE:
        raise ValueError('Downline count cohort exceeds the response limit')

    branches = []
    for user in users:
        escaped_path = escape_hierarchy_path(user.tree_path)
        branches.append(
            _downline_query(actor)
            .filter(User.tree_path.like(f'{escaped_path}/%', escape='\\'))
            .with_entities(
                literal(user.id).label('user_id'),
                func.count(User.id).label('downline_count'),
            )
            .statement
        )
    rows = db.session.execute(union_all(*branches)).all()
    return {int(user_id): int(count) for user_id, count in rows}


def _direct_team_item(user, children_counts, downline_counts):
    return {
        'id': user.id,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'role': user.role,
        'level': user.level,
        'is_active': user.is_active,
        'kyc_status': user.kyc_status,
        'created_at': user.created_at.isoformat() if user.created_at else None,
        'children_count': children_counts.get(user.id, 0),
        'downline_count': downline_counts.get(user.id, 0),
    }


def _tree_node(user, children_counts):
    return {
        'id': user.id,
        'email': user.email,
        'name': f'{user.first_name} {user.last_name}',
        'role': user.role,
        'level': user.level,
        'is_active': user.is_active,
        'children_count': children_counts.get(user.id, 0),
        'children': [],
    }


def _parse_bounded_positive_int(name, value, maximum):
    """Parse a public integer parameter without silently clamping it."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None, (jsonify({'error': f'{name} must be an integer'}), 400)
    if parsed < 1 or parsed > maximum:
        return None, (jsonify({
            'error': f'{name} must be between 1 and {maximum}',
            'code': 'HIERARCHY_PARAMETER_OUT_OF_RANGE',
        }), 400)
    return parsed, None


@hierarchy_bp.route('/my-downline', methods=['GET'])
@token_required
def get_my_downline(current_user):
    """Get the caller's entire bounded downline, grouped by path-derived depth."""
    denied = _scope_required(current_user)
    if denied:
        return denied

    try:
        descendants = (
            _downline_query(current_user)
            .order_by(User.tree_path, User.id)
            .limit(MAX_DOWNLINE_NODES + 1)
            .all()
        )
        if len(descendants) > MAX_DOWNLINE_NODES:
            return jsonify({
                'error': 'Downline exceeds the response limit',
                'code': 'HIERARCHY_RESPONSE_TOO_LARGE',
            }), 413

        children_counts = _children_count_map(
            current_user, [user.id for user in descendants]
        )
        downline_by_level = defaultdict(list)
        for user in descendants:
            level_diff = _relative_path_depth(current_user, user)
            downline_by_level[level_diff].append({
                'id': user.id,
                'email': user.email,
                'first_name': user.first_name,
                'last_name': user.last_name,
                'role': user.role,
                'level': user.level,
                'parent_id': user.parent_id,
                'is_active': user.is_active,
                'created_at': user.created_at.isoformat() if user.created_at else None,
                'children_count': children_counts.get(user.id, 0),
            })

        return jsonify({
            'total_downline': len(descendants),
            'downline_by_level': dict(downline_by_level),
            'levels_deep': max(downline_by_level.keys()) if downline_by_level else 0,
        }), 200
    except Exception:
        return jsonify({'error': 'Unable to load downline'}), 500


@hierarchy_bp.route('/my-direct-team', methods=['GET'])
@token_required
def get_my_direct_team(current_user):
    """Get a bounded page of the caller's direct children."""
    denied = _scope_required(current_user)
    if denied:
        return denied

    page, error = _parse_bounded_positive_int('page', request.args.get('page', 1), 2**31 - 1)
    if error:
        return error
    per_page, error = _parse_bounded_positive_int(
        'per_page', request.args.get('per_page', 20), MAX_DIRECT_TEAM_PAGE_SIZE
    )
    if error:
        return error

    if (page - 1) * per_page > MAX_DIRECT_TEAM_OFFSET:
        return jsonify({'error': 'Pagination offset exceeds the supported limit', 'code': 'HIERARCHY_OFFSET_TOO_LARGE'}), 400

    try:
        role = request.args.get('role')
        status = request.args.get('status')
        search = request.args.get('search', '')

        query = _downline_query(current_user).filter(User.parent_id == current_user.id)
        if role:
            query = query.filter(User.role == role)
        if status:
            query = query.filter(User.is_active.is_(status == 'active'))
        if search:
            query = query.filter(or_(
                User.email.ilike(f'%{search}%'),
                User.first_name.ilike(f'%{search}%'),
                User.last_name.ilike(f'%{search}%'),
            ))

        pagination = query.order_by(User.id).paginate(
            page=page, per_page=per_page, error_out=False
        )
        user_ids = [user.id for user in pagination.items]
        children_counts = _children_count_map(current_user, user_ids)
        downline_counts = _downline_count_map(current_user, pagination.items)
        users = [
            _direct_team_item(user, children_counts, downline_counts)
            for user in pagination.items
        ]
        return jsonify({
            'users': users,
            'total': pagination.total,
            'pages': pagination.pages,
            'current_page': page,
            'per_page': per_page,
        }), 200
    except Exception:
        return jsonify({'error': 'Unable to load direct team'}), 500


@hierarchy_bp.route('/create-user', methods=['POST'])
@token_required
def create_downline_user(current_user):
    """Create a permitted child only inside the actor's known tenant and subtree."""
    denied = _scope_required(current_user)
    if denied:
        return denied

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'A JSON object is required'}), 400
    if 'tenant_id' in data and data['tenant_id'] != current_user.tenant_id:
        return jsonify({'error': 'tenant_id must match the authenticated tenant'}), 403

    required = ('email', 'password', 'first_name', 'last_name', 'role')
    for field in required:
        if field not in data:
            return jsonify({'error': f'{field} is required'}), 400
        if not isinstance(data[field], str) or not data[field].strip():
            return jsonify({'error': f'{field} must be a non-empty string'}), 400

    try:
        normalized_email = validate_email(
            data['email'].strip(), check_deliverability=False
        ).email
    except EmailNotValidError as exc:
        return jsonify({'error': str(exc)}), 400

    password_valid, password_message = validate_password_strength(data['password'])
    if not password_valid:
        return jsonify({'error': password_message}), 400

    target_role = data['role'].strip()
    if not current_user.can_create_user(target_role):
        return jsonify({
            'error': f'You cannot create users with role: {target_role}'
        }), 403

    try:
        if User.query.filter(User.email == normalized_email).first():
            return jsonify({'error': 'Email already exists'}), 400

        new_user = User(
            email=normalized_email,
            first_name=data['first_name'].strip(),
            last_name=data['last_name'].strip(),
            role=target_role,
            parent_id=current_user.id,
            level=current_user.level + 1,
            phone=data.get('phone'),
            is_active=True,
            is_verified=data.get('email_verified', False),
            commission_rate=data.get('commission_rate', 0.00),
            # This is actor ownership, not a tenant inferred from request data.
            tenant_id=current_user.tenant_id,
        )
        new_user.set_password(data['password'])
        db.session.add(new_user)
        db.session.flush()
        new_user.parent = current_user
        new_user.update_tree_path()
        db.session.commit()
        return jsonify({
            'message': 'User created successfully',
            'user': {
                'id': new_user.id,
                'email': new_user.email,
                'role': new_user.role,
                'level': new_user.level,
                'parent_id': new_user.parent_id,
                'tree_path': new_user.tree_path,
            },
        }), 201
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Email already exists'}), 400
    except ValueError:
        db.session.rollback()
        return jsonify({'error': 'Unable to create hierarchy path'}), 400
    except Exception:
        db.session.rollback()
        return jsonify({'error': 'Unable to create user'}), 500


@hierarchy_bp.route('/user/<int:user_id>', methods=['GET'])
@token_required
def get_downline_user(current_user, user_id):
    """Get one self/downline user, with an explicit scoped target lookup."""
    denied = _scope_required(current_user)
    if denied:
        return denied

    try:
        user = _downline_query(current_user, include_self=True).filter(
            User.id == user_id
        ).first()
        if not user:
            return jsonify({'error': 'User not found'}), 404

        parent = None
        if user.parent_id is not None:
            parent = _downline_query(current_user, include_self=True).filter(
                User.id == user.parent_id
            ).first()
        children_counts = _children_count_map(current_user, [user.id])
        downline_counts = _downline_count_map(current_user, [user])
        return jsonify({
            'id': user.id,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'phone': user.phone,
            'role': user.role,
            'level': user.level,
            'parent_id': user.parent_id,
            'tree_path': user.tree_path,
            'commission_rate': float(user.commission_rate) if user.commission_rate else 0.00,
            'is_active': user.is_active,
            'is_verified': user.is_verified,
            'kyc_status': user.kyc_status,
            'created_at': user.created_at.isoformat() if user.created_at else None,
            'parent': {
                'id': parent.id,
                'email': parent.email,
                'name': f'{parent.first_name} {parent.last_name}',
                'role': parent.role,
            } if parent else None,
            'children_count': children_counts.get(user.id, 0),
            'downline_count': downline_counts.get(user.id, 0),
        }), 200
    except Exception:
        return jsonify({'error': 'Unable to load user'}), 500


@hierarchy_bp.route('/user/<int:user_id>', methods=['PUT'])
@token_required
def update_downline_user(current_user, user_id):
    """Update existing allowed fields for an explicitly scoped target only."""
    denied = _scope_required(current_user)
    if denied:
        return denied

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'A JSON object is required'}), 400
    if 'tenant_id' in data and data['tenant_id'] != current_user.tenant_id:
        return jsonify({'error': 'tenant_id must match the authenticated tenant'}), 403
    if 'role' in data and (not isinstance(data['role'], str) or not data['role'].strip()):
        return jsonify({'error': 'role must be a non-empty string'}), 400

    try:
        user = _downline_query(current_user, include_self=True).filter(
            User.id == user_id
        ).first()
        if not user:
            return jsonify({'error': 'User not found'}), 404

        new_role = data.get('role')
        if new_role is not None:
            new_role = new_role.strip()
            if not current_user.can_create_user(new_role):
                db.session.rollback()
                return jsonify({'error': f'You cannot assign role: {new_role}'}), 403

        for field in ('first_name', 'last_name', 'phone', 'is_active', 'commission_rate'):
            if field in data:
                setattr(user, field, data[field])

        if new_role is not None:
            user.role = new_role

        user.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({
            'message': 'User updated successfully',
            'user': user.to_dict(),
        }), 200
    except Exception:
        db.session.rollback()
        return jsonify({'error': 'Unable to update user'}), 500


@hierarchy_bp.route('/tree', methods=['GET'])
@token_required
def get_hierarchy_tree(current_user):
    """Return a bounded, iterative tree rooted at the current user."""
    denied = _scope_required(current_user)
    if denied:
        return denied

    max_depth, error = _parse_bounded_positive_int(
        'max_depth', request.args.get('max_depth', 5), MAX_TREE_DEPTH
    )
    if error:
        return error

    try:
        depth_expression = _path_depth_expression(current_user)
        nodes = (
            _downline_query(current_user)
            .filter(depth_expression <= max_depth)
            .order_by(User.tree_path, User.id)
            .limit(MAX_TREE_NODES + 1)
            .all()
        )
        if len(nodes) > MAX_TREE_NODES:
            return jsonify({
                'error': 'Hierarchy tree exceeds the response limit',
                'code': 'HIERARCHY_TREE_TOO_LARGE',
            }), 413

        # The count is a SQL aggregate against the same literal actor predicate;
        # it remains truthful even when the requested visual depth is smaller.
        total_downline = _downline_query(current_user).count()
        all_visible_ids = [current_user.id, *(user.id for user in nodes)]
        children_counts = _children_count_map(current_user, all_visible_ids)
        rendered = {current_user.id: _tree_node(current_user, children_counts)}
        users_by_id = {current_user.id: current_user}
        users_by_id.update({user.id: user for user in nodes})

        # Only immediate, path-consistent parent edges are eligible.  The BFS
        # visited set makes malformed legacy cycles harmless and avoids recursion.
        candidates = defaultdict(list)
        for user in nodes:
            parent = users_by_id.get(user.parent_id)
            if not parent:
                continue
            if (
                user.tree_path.startswith(parent.tree_path + '/')
                and user.tree_path.count('/') == parent.tree_path.count('/') + 1
            ):
                candidates[parent.id].append(user)

        seen = {current_user.id}
        queue = deque([current_user.id])
        while queue:
            parent_id = queue.popleft()
            for child in candidates.get(parent_id, ()):
                if child.id in seen:
                    continue
                seen.add(child.id)
                child_node = _tree_node(child, children_counts)
                rendered[child.id] = child_node
                rendered[parent_id]['children'].append(child_node)
                queue.append(child.id)

        return jsonify({
            'tree': rendered[current_user.id],
            'total_downline': total_downline,
        }), 200
    except Exception:
        return jsonify({'error': 'Unable to load hierarchy tree'}), 500


@hierarchy_bp.route('/stats', methods=['GET'])
@token_required
def get_hierarchy_stats(current_user):
    """Aggregate own-subtree statistics in SQL without materializing descendants."""
    denied = _scope_required(current_user)
    if denied:
        return denied

    try:
        query = _downline_query(current_user)
        total_downline = query.count()
        direct_children = query.filter(User.parent_id == current_user.id).count()
        role_counts = dict(
            query.with_entities(User.role, func.count(User.id)).group_by(User.role).all()
        )
        depth_expression = _path_depth_expression(current_user)
        level_counts = {
            int(depth): int(count)
            for depth, count in (
                query.with_entities(depth_expression, func.count(User.id))
                .group_by(depth_expression)
                .all()
            )
        }
        active_count, inactive_count = query.with_entities(
            func.coalesce(func.sum(case((User.is_active.is_(True), 1), else_=0)), 0),
            func.coalesce(func.sum(case((User.is_active.is_(False), 1), else_=0)), 0),
        ).one()
        return jsonify({
            'total_downline': total_downline,
            'direct_children': direct_children,
            'by_role': {role: int(count) for role, count in role_counts.items()},
            'by_level': level_counts,
            'active': int(active_count),
            'inactive': int(inactive_count),
            'max_depth': max(level_counts.keys()) if level_counts else 0,
        }), 200
    except Exception:
        return jsonify({'error': 'Unable to load hierarchy statistics'}), 500
