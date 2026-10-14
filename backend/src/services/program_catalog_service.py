"""Fail-closed, configured-root public trading-program catalog reads.

This module deliberately owns only read serialization and validation.  It does not
select a tenant from HTTP input, mutate catalog rows, infer a fallback brand, or
claim that catalog terms are verified or live.
"""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, InvalidOperation
import json

from flask import current_app
from sqlalchemy import select, text

from src.database import db
from src.middleware.tenant_middleware import get_tenant_from_request
from src.models.trading_program import ProgramAddOn, TradingProgram
from src.services.program_evaluation_policy import (
    EvaluationPolicyError,
    public_program_rules,
    validate_program_evaluation_policy,
)
from src.utils.hierarchy_scoping import without_hierarchy_scope


_MAX_ROWS = 200
_MONEY_QUANTUM = Decimal("0.01")
_MAX_PRICE = Decimal("99999999.99")
_MAX_ACCOUNT_SIZE = Decimal("9999999999.99")


class ProgramCatalogError(ValueError):
    """Expected catalog failure; routes map it to a non-disclosing response."""

    status = 503


class ProgramCatalogNotFound(ProgramCatalogError):
    """Missing, foreign, and inactive programs intentionally share one result."""

    status = 404


class CatalogValidationError(ProgramCatalogError):
    """A stored catalog row cannot be safely represented as a purchasable offer."""


def _catalog_error(field: str) -> CatalogValidationError:
    return CatalogValidationError(f"Catalog field is invalid: {field}")


def _decimal(
    value,
    field: str,
    *,
    optional: bool = False,
    percentage: bool = False,
    positive: bool = False,
    maximum: Decimal | None = None,
) -> Decimal | None:
    """Pure exact-decimal validation; never coerce floats or silently round."""
    if value is None:
        if optional:
            return None
        raise _catalog_error(field)
    if isinstance(value, bool) or isinstance(value, float):
        raise _catalog_error(field)
    try:
        decimal_value = Decimal(value)
        if not decimal_value.is_finite() or decimal_value < 0:
            raise InvalidOperation
        if positive and decimal_value <= 0:
            raise InvalidOperation
        if percentage and decimal_value > Decimal("100"):
            raise InvalidOperation
        if maximum is not None and decimal_value > maximum:
            raise InvalidOperation
        # A public exact-money contract must not silently display a rounded value.
        if decimal_value != decimal_value.quantize(_MONEY_QUANTUM):
            raise InvalidOperation
    except (InvalidOperation, TypeError, ValueError):
        raise _catalog_error(field) from None
    return decimal_value


def _money(value: Decimal) -> str:
    return format(value.quantize(_MONEY_QUANTUM), ".2f")


def _required_text(value, field: str, *, limit: int, ascii_label: bool = False) -> str:
    if not isinstance(value, str) or not value or len(value) > limit:
        raise _catalog_error(field)
    if ascii_label and (not value.isascii() or any(ord(character) < 32 or ord(character) > 126 for character in value)):
        raise _catalog_error(field)
    return value


def _optional_text(value, field: str, *, limit: int, ascii_label: bool = False) -> str | None:
    if value is None:
        return None
    return _required_text(value, field, limit=limit, ascii_label=ascii_label)


def _json_object(value, field: str) -> dict:
    """Copy a bounded JSON object without normalizing unknown rule vocabulary."""
    if not isinstance(value, dict):
        raise _catalog_error(field)
    copied = deepcopy(value)
    try:
        # This is validation, not output normalization: unknown JSON fields remain
        # exactly as stored, while NaN/non-JSON values are refused.
        encoded = json.dumps(copied, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise _catalog_error(field) from None
    if len(encoded.encode("utf-8")) > 65536:
        raise _catalog_error(field)
    return copied


def _terms_budget(terms: dict) -> dict:
    """Refuse an oversized complete term snapshot before it reaches an HTTP client."""
    try:
        encoded = json.dumps(terms, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise _catalog_error("terms") from None
    if len(encoded.encode("utf-8")) > 65536:
        raise _catalog_error("terms")
    return terms


def program_price(program: TradingProgram) -> str:
    """Return quote-compatible base price as an exact USD-cent string."""
    return _money(_decimal(program.price, "price", positive=True, maximum=_MAX_PRICE))


def program_terms(program: TradingProgram) -> dict:
    """Return the immutable quote-term shape shared by catalog and OrderService.

    The keys intentionally match the existing order snapshot terms block.  Values
    are validated before serialization so a malformed legacy row fails closed rather
    than changing a displayed or quoted rule by coercion.
    """
    try:
        # Assigned rows must carry the full canonical policy snapshot, while
        # unassigned legacy rows remain their stored facts.  The private
        # challenge archive is validated and removed only from public/quote
        # serialization; every other unknown rule remains untouched.
        rules = public_program_rules(_json_object(program.rules, "rules"))
        validate_program_evaluation_policy(program, program.rules)
    except EvaluationPolicyError:
        raise _catalog_error("evaluation_policy") from None
    terms = {
        "name": _required_text(program.name, "name", limit=255),
        # Preserve unknown legacy/program labels when they are a safe bounded ASCII
        # label; clients may render a generic tab rather than invent a phase model.
        "type": _required_text(program.type, "type", limit=50, ascii_label=True),
        "description": _optional_text(program.description, "description", limit=65536),
        "payout_mode": _optional_text(program.payout_mode, "payout_mode", limit=50, ascii_label=True),
        "account_size": _money(
            _decimal(program.account_size, "account_size", positive=True, maximum=_MAX_ACCOUNT_SIZE)
        ),
        "profit_target": _optional_money(program.profit_target, "profit_target", percentage=True),
        "max_daily_loss": _optional_money(program.max_daily_loss, "max_daily_loss", percentage=True),
        "max_total_loss": _optional_money(program.max_total_loss, "max_total_loss", percentage=True),
        "profit_split": _optional_money(program.profit_split, "profit_split", percentage=True),
        "profit_split_percentage": _optional_money(
            program.profit_split_percentage, "profit_split_percentage", percentage=True
        ),
        "minimum_payout_amount": _optional_money(
            program.minimum_payout_amount, "minimum_payout_amount", maximum=_MAX_PRICE
        ),
        "rules": rules,
    }
    return _terms_budget(terms)


def _optional_money(value, field: str, **kwargs) -> str | None:
    decimal_value = _decimal(value, field, optional=True, **kwargs)
    return _money(decimal_value) if decimal_value is not None else None


def _addon_payload(addon: ProgramAddOn) -> dict:
    if not isinstance(addon.id, int) or isinstance(addon.id, bool) or addon.id <= 0:
        raise _catalog_error("addon.id")
    if not isinstance(addon.program_id, int) or isinstance(addon.program_id, bool) or addon.program_id <= 0:
        raise _catalog_error("addon.program_id")
    price_type = _required_text(addon.price_type, "addon.price_type", limit=20, ascii_label=True)
    if price_type not in {"fixed", "percentage"}:
        raise _catalog_error("addon.price_type")
    price = _decimal(
        addon.price,
        "addon.price",
        maximum=_MAX_PRICE,
    )
    return {
        "id": addon.id,
        "program_id": addon.program_id,
        "name": _required_text(addon.name, "addon.name", limit=255),
        "description": _optional_text(addon.description, "addon.description", limit=65536),
        "price": _money(price),
        "price_type": price_type,
        "benefits": _json_object(addon.benefits, "addon.benefits"),
        "is_active": True,
    }


class ProgramCatalogService:
    """Configured-root public catalog query service with bounded SQL reads."""

    @staticmethod
    def _currency() -> str:
        # Currency is a quote policy.  Do not guess USD from a missing/unsupported
        # setting and do not enable order quoting from this read path.
        if current_app.config.get("ORDER_QUOTE_CURRENCY") != "USD":
            raise ProgramCatalogError("Program catalog currency is unavailable")
        return "USD"

    @staticmethod
    def _query_budget() -> None:
        if db.session.get_bind().dialect.name == "postgresql":
            db.session.execute(text("SET LOCAL lock_timeout = '3s'"))
            db.session.execute(text("SET LOCAL statement_timeout = '5s'"))

    @staticmethod
    def _brand_id() -> int:
        # This configuration lookup intentionally precedes every TradingProgram
        # statement.  It has no Host/header/query-string selector and no fallback.
        brand = get_tenant_from_request()
        brand_id = getattr(brand, "id", None)
        if not isinstance(brand_id, int) or isinstance(brand_id, bool) or brand_id <= 0:
            raise ProgramCatalogError("Configured brand is unavailable")
        return brand_id

    @staticmethod
    def _program_payload(program: TradingProgram, currency: str) -> dict:
        if not isinstance(program.id, int) or isinstance(program.id, bool) or program.id <= 0:
            raise _catalog_error("id")
        if not isinstance(program.tenant_id, int) or isinstance(program.tenant_id, bool) or program.tenant_id <= 0:
            raise _catalog_error("tenant_id")
        if program.is_active is not True:
            raise _catalog_error("is_active")
        terms = program_terms(program)
        return {
            # Existing public keys retain their names; exact numeric strings avoid
            # JavaScript float conversion and preserve zero versus a missing value.
            "id": program.id,
            "tenant_id": program.tenant_id,
            "name": terms["name"],
            "type": terms["type"],
            "description": terms["description"],
            "account_size": terms["account_size"],
            "profit_target": terms["profit_target"],
            "max_daily_loss": terms["max_daily_loss"],
            "max_total_loss": terms["max_total_loss"],
            "price": program_price(program),
            "profit_split": terms["profit_split"],
            "rules": terms["rules"],
            "is_active": True,
            "currency": currency,
            "terms": terms,
        }

    @classmethod
    def list_programs(cls) -> list[dict]:
        currency = cls._currency()
        cls._query_budget()
        brand_id = cls._brand_id()
        statement = (
            select(TradingProgram)
            .where(TradingProgram.tenant_id == brand_id, TradingProgram.is_active.is_(True))
            .order_by(TradingProgram.id)
            .limit(_MAX_ROWS + 1)
            .execution_options(skip_hierarchy_scope=True, populate_existing=True)
        )
        with without_hierarchy_scope(db.session):
            programs = db.session.execute(statement).scalars().all()
        if len(programs) > _MAX_ROWS:
            raise ProgramCatalogError("Program catalog exceeds the public read budget")
        # There is deliberately no add-on relationship access in the list path.
        return [cls._program_payload(program, currency) for program in programs]

    @classmethod
    def get_program(cls, program_id: int) -> dict:
        currency = cls._currency()
        if not isinstance(program_id, int) or isinstance(program_id, bool) or program_id <= 0:
            raise ProgramCatalogNotFound("Program is unavailable")
        cls._query_budget()
        brand_id = cls._brand_id()
        statement = (
            select(TradingProgram)
            .where(
                TradingProgram.id == program_id,
                TradingProgram.tenant_id == brand_id,
                TradingProgram.is_active.is_(True),
            )
            .execution_options(skip_hierarchy_scope=True, populate_existing=True)
        )
        with without_hierarchy_scope(db.session):
            program = db.session.execute(statement).scalar_one_or_none()
        if program is None:
            raise ProgramCatalogNotFound("Program is unavailable")
        addon_statement = (
            select(ProgramAddOn)
            .where(ProgramAddOn.program_id == program.id, ProgramAddOn.is_active.is_(True))
            .order_by(ProgramAddOn.id)
            .limit(_MAX_ROWS + 1)
            .execution_options(skip_hierarchy_scope=True, populate_existing=True)
        )
        with without_hierarchy_scope(db.session):
            addons = db.session.execute(addon_statement).scalars().all()
        if len(addons) > _MAX_ROWS:
            raise ProgramCatalogError("Program add-on catalog exceeds the public read budget")
        payload = cls._program_payload(program, currency)
        payload["addons"] = [_addon_payload(addon) for addon in addons]
        return payload
