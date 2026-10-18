"""Read-only, tenant-scoped legacy trading-history projection for UI-4."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from math import ceil
from typing import Any

from sqlalchemy import case, desc, func

from src.database import db
from src.models.trade import Trade
from src.models.trading_program import Challenge, TradingProgram


class TradingHistoryArgumentError(ValueError):
    """Raised before any history-resource query for an invalid query string."""


@dataclass(frozen=True)
class TradingHistoryArguments:
    page: int
    per_page: int
    symbol: str
    trade_type: str
    period: str


class TradingHistoryService:
    """Expose only existing, unverified legacy trades owned by the JWT actor."""

    _ALLOWED_ARGUMENTS = {"page", "per_page", "symbol", "type", "period"}
    _SYMBOL_CHARACTERS = frozenset(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-"
    )

    @classmethod
    def parse_arguments(cls, arguments) -> TradingHistoryArguments:
        """Strictly parse one canonical copy of each supported query argument."""
        for name in arguments.keys():
            if name not in cls._ALLOWED_ARGUMENTS or len(arguments.getlist(name)) != 1:
                raise TradingHistoryArgumentError("invalid query")

        page = cls._bounded_integer(arguments, "page", default=1, minimum=1, maximum=1000)
        per_page = cls._bounded_integer(
            arguments, "per_page", default=20, minimum=1, maximum=100
        )
        symbol = arguments.get("symbol", "")
        if (
            not isinstance(symbol, str)
            or len(symbol) > 20
            or not symbol.isascii()
            or any(character not in cls._SYMBOL_CHARACTERS for character in symbol)
        ):
            raise TradingHistoryArgumentError("invalid query")

        trade_type = arguments.get("type", "all")
        if trade_type not in {"all", "buy", "sell"}:
            raise TradingHistoryArgumentError("invalid query")
        period = arguments.get("period", "all")
        if period not in {"all", "today", "week", "month"}:
            raise TradingHistoryArgumentError("invalid query")

        return TradingHistoryArguments(
            page=page,
            per_page=per_page,
            symbol=symbol.upper(),
            trade_type=trade_type,
            period=period,
        )

    @staticmethod
    def _bounded_integer(arguments, name: str, *, default: int, minimum: int, maximum: int) -> int:
        if name not in arguments:
            return default
        raw_value = arguments.get(name)
        if (
            not isinstance(raw_value, str)
            or len(raw_value) > len(str(maximum))
            or not raw_value.isascii()
            or not raw_value.isdecimal()
        ):
            raise TradingHistoryArgumentError("invalid query")
        value = int(raw_value)
        if str(value) != raw_value or not minimum <= value <= maximum:
            raise TradingHistoryArgumentError("invalid query")
        return value

    @classmethod
    def get_history(cls, actor, arguments: TradingHistoryArguments) -> dict[str, Any]:
        """Return one bounded page plus SQL-only aggregate statistics.

        Every row is constrained by both the exact challenge owner and the
        challenge program's tenant.  ``no_autoflush`` is intentional: a read
        must never flush unrelated pending work held by the request session.
        """
        now = datetime.utcnow()
        with db.session.no_autoflush:
            query = cls._filtered_query(actor, arguments, now)
            aggregate = query.with_entities(
                func.count(Trade.id).label("total_trades"),
                func.count(Trade.profit).label("known_profit_trades"),
                func.coalesce(
                    func.sum(case((Trade.profit > 0, 1), else_=0)), 0
                ).label("winning_trades"),
                func.coalesce(
                    func.sum(case((Trade.profit < 0, 1), else_=0)), 0
                ).label("losing_trades"),
                func.sum(Trade.profit).label("total_profit"),
            ).one()

            total = int(aggregate.total_trades or 0)
            rows = query.order_by(
                desc(Trade.close_time).nullslast(), desc(Trade.id)
            ).offset((arguments.page - 1) * arguments.per_page).limit(
                arguments.per_page
            ).all()

        profit_is_incomplete = total != int(aggregate.known_profit_trades or 0)
        statistics = {
            "total_trades": total,
            "winning_trades": None if profit_is_incomplete else int(aggregate.winning_trades or 0),
            "losing_trades": None if profit_is_incomplete else int(aggregate.losing_trades or 0),
            "total_profit": (
                None
                if profit_is_incomplete
                else decimal_string(
                    aggregate.total_profit
                    if aggregate.total_profit is not None
                    else Decimal("0")
                )
            ),
        }
        return {
            "trades": [serialize_trade(trade) for trade in rows],
            "pagination": {
                "page": arguments.page,
                "per_page": arguments.per_page,
                "total": total,
                "pages": ceil(total / arguments.per_page) if total else 0,
            },
            "filters": {
                "symbol": arguments.symbol,
                "type": arguments.trade_type,
                "period": arguments.period,
            },
            "owner_context": {
                "user_id": actor.id,
                "tenant_id": actor.tenant_id,
            },
            "statistics": statistics,
            "data_status": "unverified_legacy",
            "provider_authenticated": False,
            "currency": None,
        }

    @classmethod
    def _filtered_query(cls, actor, arguments: TradingHistoryArguments, now: datetime):
        query = db.session.query(Trade).join(
            Challenge, Trade.challenge_id == Challenge.id
        ).join(
            TradingProgram, Challenge.program_id == TradingProgram.id
        ).filter(
            Challenge.user_id == actor.id,
            TradingProgram.tenant_id == actor.tenant_id,
        )
        if arguments.symbol:
            query = query.filter(func.upper(Trade.symbol) == arguments.symbol)
        if arguments.trade_type != "all":
            query = query.filter(Trade.trade_type == arguments.trade_type)
        if arguments.period != "all":
            query = query.filter(Trade.close_time <= now)
        if arguments.period == "today":
            query = query.filter(
                Trade.close_time >= now.replace(hour=0, minute=0, second=0, microsecond=0)
            )
        elif arguments.period == "week":
            query = query.filter(Trade.close_time >= now - timedelta(days=7))
        elif arguments.period == "month":
            query = query.filter(Trade.close_time >= now - timedelta(days=30))
        return query


def decimal_string(value):
    """Serialize known SQL NUMERIC values without float conversion or zero loss."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def serialize_trade(trade: Trade) -> dict[str, Any]:
    """Project native Trade columns only; no legacy lots/pips aliases are invented."""
    return {
        "id": trade.id,
        "challenge_id": trade.challenge_id,
        "symbol": trade.symbol,
        "trade_type": trade.trade_type,
        "volume": decimal_string(trade.volume),
        "open_price": decimal_string(trade.open_price),
        "close_price": decimal_string(trade.close_price),
        "profit": decimal_string(trade.profit),
        "commission": decimal_string(trade.commission),
        "swap": decimal_string(trade.swap),
        "status": trade.status,
        "open_time": trade.open_time.isoformat() if trade.open_time else None,
        "close_time": trade.close_time.isoformat() if trade.close_time else None,
    }
