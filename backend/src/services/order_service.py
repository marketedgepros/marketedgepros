"""Server-priced immutable quotes, deliberately disconnected from settlement."""
from copy import deepcopy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
import re
import uuid
from flask import current_app
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from src.database import db
from src.models.purchase_order import PurchaseOrder
from src.models.trading_program import TradingProgram, ProgramAddOn
from src.models.user import User
from src.middleware.tenant_middleware import get_tenant_from_request
from src.services.program_catalog_service import CatalogValidationError, program_price, program_terms
from src.services.program_evaluation_policy import is_coming_soon_program_type
from src.utils.hierarchy_scoping import without_hierarchy_scope


class OrderError(ValueError):
    def __init__(self, message, code='ORDER_INVALID', status=400):
        super().__init__(message)
        self.code, self.status = code, status


def _canonical(value):
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        raise OrderError('Catalog terms are not serializable', 'CATALOG_INVALID', 409) from None
    if len(encoded.encode('utf-8')) > 65536:
        raise OrderError('Catalog terms exceed the snapshot budget', 'CATALOG_INVALID', 409)
    return encoded


def _digest(encoded):
    return hashlib.sha256(encoded.encode('utf-8')).hexdigest()


def _identity(value):
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value <= 2147483647


def _price(value, *, positive=False):
    if isinstance(value, (bool, float)):
        raise OrderError('Catalog price is not an exact decimal', 'CATALOG_INVALID', 409)
    try:
        result = Decimal(value)
        if not result.is_finite() or result < 0 or result > Decimal('99999999.99') or (positive and result <= 0):
            raise InvalidOperation
        return result
    except (InvalidOperation, ValueError, TypeError):
        raise OrderError('Catalog price is unavailable', 'CATALOG_INVALID', 409) from None


def _money(value):
    return format(value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), '.2f')


class OrderService:
    @staticmethod
    def _query_budget():
        if db.session.get_bind().dialect.name == 'postgresql':
            db.session.execute(text("SET LOCAL lock_timeout = '3s'"))
            db.session.execute(text("SET LOCAL statement_timeout = '5s'"))

    @staticmethod
    def _actor(actor):
        identity = getattr(actor, 'id', None)
        if not _identity(identity):
            raise OrderError('Authenticated owner required', 'ORDER_FORBIDDEN', 403)
        # Exact owner refresh; no user_id accepted from an HTTP body.
        with without_hierarchy_scope(db.session):
            user = db.session.execute(select(User).where(User.id == identity).execution_options(populate_existing=True)).scalar_one_or_none()
        brand = get_tenant_from_request()
        if user is None or not user.is_active or brand is None or user.tenant_id != brand.id:
            raise OrderError('Active configured brand is required', 'ORDER_FORBIDDEN', 403)
        return user, brand

    @staticmethod
    def _enabled():
        if current_app.config.get('ORDER_QUOTES_ENABLED') is not True or current_app.config.get('ORDER_QUOTE_CURRENCY') != 'USD':
            raise OrderError('Purchase quotes are not configured', 'ORDER_QUOTES_NOT_CONFIGURED', 503)
        dialect = db.session.get_bind().dialect.name
        if dialect == 'postgresql':
            OrderService._query_budget()
            # Runtime readiness is independent of an operator's enablement flag.
            # Bind explicitly to public, the frozen migration's owned namespace.
            ready = db.session.execute(text("""
                SELECT
                    (SELECT count(*) FROM public.alembic_version) = 1
                    AND (SELECT min(version_num) FROM public.alembic_version) IN (
                        '20261011_000006', '20261011_000007',
                        '20261011_000008', '20261012_000001', '20261013_000001',
                        '20261013_000002'
                    )
                    AND EXISTS (
                    SELECT 1 FROM pg_trigger t
                    JOIN pg_class c ON c.oid = t.tgrelid
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    JOIN pg_proc p ON p.oid = t.tgfoid
                    JOIN pg_namespace pn ON pn.oid = p.pronamespace
                    JOIN pg_language l ON l.oid = p.prolang
                    WHERE n.nspname = 'public' AND c.relname = 'purchase_orders'
                      AND t.tgname = 'purchase_orders_immutable' AND t.tgtype = 27
                      AND t.tgenabled = 'O' AND NOT t.tgisinternal AND t.tgqual IS NULL
                      AND pn.nspname = 'public' AND p.proname = 'marketedgepros_purchase_orders_immutable'
                      AND p.pronargs = 0 AND p.prorettype = 'trigger'::regtype AND l.lanname = 'plpgsql'
                      AND NOT p.prosecdef AND p.proconfig IS NULL
                      AND p.proowner = c.relowner
                      AND p.proowner = (SELECT oid FROM pg_roles WHERE rolname = session_user)
                      AND btrim(p.prosrc, chr(32) || chr(10) || chr(13) || chr(9)) = :body
                    )
            """), {'body': "BEGIN\n    RAISE EXCEPTION 'purchase_orders are immutable';\nEND;"}).scalar_one()
            if not ready:
                raise OrderError('Immutable quote storage is not ready', 'ORDER_STORAGE_NOT_READY', 503)
        elif dialect != 'sqlite' or not current_app.testing:
            raise OrderError('Immutable quote storage is not ready', 'ORDER_STORAGE_NOT_READY', 503)

    @staticmethod
    def _request(data, key):
        if not isinstance(data, dict) or set(data) - {'program_id', 'addon_ids'}:
            raise OrderError('Only program_id and addon_ids are accepted')
        if not _identity(data.get('program_id')):
            raise OrderError('A positive program_id is required')
        addons = data.get('addon_ids', [])
        if not isinstance(addons, list) or len(addons) > 20 or not all(_identity(item) for item in addons) or len(set(addons)) != len(addons):
            raise OrderError('addon_ids must contain at most 20 unique positive identifiers')
        if not isinstance(key, str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,128}', key, flags=re.ASCII):
            raise OrderError('An Idempotency-Key of 16-128 ASCII characters is required')
        return data['program_id'], sorted(addons)

    @staticmethod
    def _existing(user, key, request_hash):
        order = db.session.execute(select(PurchaseOrder).where(PurchaseOrder.user_id == user.id, PurchaseOrder.idempotency_key == key)).scalar_one_or_none()
        if order is not None:
            if order.tenant_id != user.tenant_id or order.request_hash != request_hash:
                raise OrderError('Idempotency-Key was already used for another request', 'ORDER_IDEMPOTENCY_CONFLICT', 409)
            OrderService._integrity(order)
        return order

    @staticmethod
    def _integrity(order):
        try:
            snapshot = json.loads(order.snapshot_json)
            valid = (
                _digest(order.snapshot_json) == order.snapshot_hash
                and snapshot['user_id'] == order.user_id and snapshot['tenant_id'] == order.tenant_id
                and snapshot['program_id'] == order.program_id and snapshot['currency'] == order.currency == 'USD'
                and Decimal(snapshot['amount']) * 100 == order.amount_minor
                and order.state == 'quoted' and snapshot['entitlement'] is False
            )
        except (ValueError, TypeError, KeyError, InvalidOperation):
            valid = False
        if not valid:
            raise OrderError('Stored quote integrity failed', 'ORDER_INTEGRITY_FAILED', 503)

    @staticmethod
    def create_quote(actor, data, idempotency_key):
        """Return (order, created); caller commits. No provider or entitlement call."""
        OrderService._enabled()
        program_id, addon_ids = OrderService._request(data, idempotency_key)
        OrderService._query_budget()
        user, brand = OrderService._actor(actor)
        request_json = _canonical({'schema': 1, 'tenant_id': brand.id, 'program_id': program_id, 'addon_ids': addon_ids, 'currency': 'USD'})
        request_hash = _digest(request_json)
        existing = OrderService._existing(user, idempotency_key, request_hash)
        if existing is not None:
            return existing, False
        # PostgreSQL shared row locks keep catalog edits outside this quote's
        # transaction until its frozen snapshot is committed. Queries are bounded.
        program = db.session.execute(select(TradingProgram).where(TradingProgram.id == program_id, TradingProgram.tenant_id == brand.id,
                                           TradingProgram.is_active.is_(True)).with_for_update(read=True).execution_options(populate_existing=True)).scalar_one_or_none()
        if program is None:
            raise OrderError('Program is unavailable', 'PROGRAM_UNAVAILABLE', 404)
        # An existing immutable order was returned above before this mutable
        # catalog lookup.  Direct links and current row metadata therefore
        # cannot create a new Instant Funding quote, but cannot erase a stored
        # historical quote replay either.
        if program.type == 'instant_funding' or is_coming_soon_program_type(program.type):
            raise OrderError('Program is coming soon', 'PROGRAM_COMING_SOON', 409)
        try:
            # Catalog and quote snapshots share the same stored-term validation
            # and exact-cent base price representation; neither coerces a row.
            base = _price(program_price(program), positive=True)
            terms = program_terms(program)
        except CatalogValidationError:
            raise OrderError('Catalog terms are unavailable', 'CATALOG_INVALID', 409) from None
        addons = db.session.execute(select(ProgramAddOn).where(ProgramAddOn.id.in_(addon_ids), ProgramAddOn.program_id == program_id,
                                          ProgramAddOn.is_active.is_(True)).order_by(ProgramAddOn.id).with_for_update(read=True).execution_options(populate_existing=True)).scalars().all() if addon_ids else []
        if len(addons) != len(addon_ids):
            raise OrderError('An add-on is unavailable for this program', 'ADDON_UNAVAILABLE', 404)
        total = base
        line_items = []
        for addon in addons:
            value = _price(addon.price)
            if addon.price_type == 'fixed':
                line = value
            elif addon.price_type == 'percentage':
                if value > Decimal('100'):
                    raise OrderError('Add-on pricing is unspecified', 'CATALOG_INVALID', 409)
                line = (base * value / Decimal(100)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            else:
                raise OrderError('Add-on pricing is unspecified', 'CATALOG_INVALID', 409)
            total += line
            line_items.append({'id': addon.id, 'name': addon.name, 'price_type': addon.price_type,
                               'catalog_price': _money(value), 'amount': _money(line), 'benefits': deepcopy(addon.benefits)})
        total = _price(total, positive=True).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        if total <= 0:
            raise OrderError('Quote must be positive', 'CATALOG_INVALID', 409)
        snapshot = {'schema': 1, 'kind': 'purchase_quote', 'user_id': user.id, 'tenant_id': brand.id, 'program_id': program_id,
                    'currency': 'USD', 'base_amount': _money(base), 'addons': line_items, 'amount': _money(total),
                    'rounding': 'USD cents; ROUND_HALF_UP per add-on line', 'terms': terms,
                    'settlement': 'not_configured', 'entitlement': False}
        snapshot_json = _canonical(snapshot)
        order = PurchaseOrder(id=str(uuid.uuid4()), user_id=user.id, tenant_id=brand.id, program_id=program_id,
                              idempotency_key=idempotency_key, request_hash=request_hash, snapshot_hash=_digest(snapshot_json),
                              snapshot_json=snapshot_json, amount_minor=int(total * 100), currency='USD', state='quoted')
        try:
            # DB uniqueness is the final concurrent-request authority. A losing
            # insert rolls back only its savepoint, then reads the committed winner.
            with db.session.begin_nested():
                db.session.add(order)
                db.session.flush()
        except IntegrityError:
            existing = OrderService._existing(user, idempotency_key, request_hash)
            if existing is None:
                raise
            return existing, False
        return order, True

    @staticmethod
    def get_quote(actor, order_id):
        OrderService._enabled()
        OrderService._query_budget()
        user, brand = OrderService._actor(actor)
        if not isinstance(order_id, str) or len(order_id) != 36:
            raise OrderError('Order not found', 'ORDER_NOT_FOUND', 404)
        order = db.session.execute(select(PurchaseOrder).where(PurchaseOrder.id == order_id, PurchaseOrder.user_id == user.id,
                                                         PurchaseOrder.tenant_id == brand.id)).scalar_one_or_none()
        if order is None:
            raise OrderError('Order not found', 'ORDER_NOT_FOUND', 404)
        OrderService._integrity(order)
        return order
