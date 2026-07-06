"""AlpacaBrokerClient — Alpaca paper trading REST client (dry-run default).

Mirrors the `AlpacaNewsClient` / `ProvenanceWriter(None)` graceful-offline pattern:
with no API key the client is *disabled* — `is_enabled()` is False, reads return an
empty `Portfolio`/`{}`, and `submit_order` is a logged no-op. The REST transports live
in overridable `_get`/`_post`/`_delete` so unit tests inject fixtures instead of
hitting `paper-api.alpaca.markets`.

SAFETY — dry-run by default. `submit_order(order, *, dry_run=True)` does NOT POST: it
returns the order marked SUBMITTED with a simulated `dry-...` id and logs the intent,
making ZERO network calls. Only `dry_run=False` POSTs to `/orders`. This is the
Phase-5 broker-boundary safety invariant.

Alpaca v2 shapes (subset consumed here):
    /account   -> {equity, cash, buying_power, daytrade_count, ...}
    /positions -> [{symbol, qty, avg_entry_price, market_value, unrealized_pl}, ...]
    /orders    -> {id, symbol, side, qty, order_type|type, limit_price, stop_price,
                   status, filled_qty, filled_avg_price}
Auth via `APCA-API-KEY-ID` / `APCA-API-SECRET-KEY` headers (same as alpaca_news.py).
"""

from __future__ import annotations

import logging
import time

from services.trader.execution.model import (
    Order,
    OrderStatus,
    OrderType,
    Portfolio,
    Position,
    Side,
)

logger = logging.getLogger(__name__)

_ACCOUNT_PATH = "/account"
_POSITIONS_PATH = "/positions"
_ORDERS_PATH = "/orders"

_SIDE_TO_ALPACA = {Side.BUY: "buy", Side.SELL: "sell"}
_TYPE_TO_ALPACA = {OrderType.MARKET: "market", OrderType.LIMIT: "limit"}
_STATUS_FROM_ALPACA = {
    "new": OrderStatus.NEW,
    "accepted": OrderStatus.SUBMITTED,
    "pending_new": OrderStatus.SUBMITTED,
    "submitted": OrderStatus.SUBMITTED,
    "filled": OrderStatus.FILLED,
    "partially_filled": OrderStatus.PARTIAL,
    "canceled": OrderStatus.CANCELED,
    "cancelled": OrderStatus.CANCELED,
    "expired": OrderStatus.CANCELED,
    "rejected": OrderStatus.REJECTED,
    # Extended lifecycle states (C10) bucketed by their practical meaning:
    "done_for_day": OrderStatus.CANCELED,    # no longer working today
    "stopped": OrderStatus.FILLED,           # execution guaranteed by the venue
    "pending_cancel": OrderStatus.CANCELED,  # on its way out
    "replaced": OrderStatus.CANCELED,        # superseded by a new order
    "pending_replace": OrderStatus.SUBMITTED,
    "held": OrderStatus.SUBMITTED,           # e.g. an OTO stop leg awaiting trigger
    "suspended": OrderStatus.SUBMITTED,      # accepted but not currently workable
    "calculated": OrderStatus.FILLED,        # done, settlement figures pending
}


class AlpacaBrokerClient:
    """Alpaca paper trading client. No key -> disabled, safe no-op. Dry-run default."""

    def __init__(
        self,
        key: str | None = None,
        secret: str | None = None,
        endpoint: str = "https://paper-api.alpaca.markets/v2",
    ) -> None:
        self.key = key
        self.secret = secret
        self.endpoint = endpoint.rstrip("/")

    def is_enabled(self) -> bool:
        return bool(self.key and self.secret)

    def account(self) -> Portfolio:
        """GET /account + /positions -> Portfolio. Disabled -> empty Portfolio."""
        if not self.is_enabled():
            return Portfolio(equity=0, cash=0, buying_power=0, positions={})
        account = self._get(_ACCOUNT_PATH)
        positions = self._get(_POSITIONS_PATH)
        return self._map_account(account, positions)

    def positions(self) -> dict[str, Position]:
        """GET /positions -> {ticker: Position}. Disabled -> {}."""
        if not self.is_enabled():
            return {}
        raw = self._get(_POSITIONS_PATH)
        return {p["symbol"]: self._map_position(p) for p in raw}

    def submit_order(self, order: Order, *, dry_run: bool = True) -> Order:
        """Submit an order. dry_run=True (default) does NOT POST — no network call.

        Dry-run returns a copy of `order` marked SUBMITTED with a simulated `dry-...`
        id and logs the intent. `dry_run=False` POSTs to /orders and maps the response.
        A disabled (no-key) client is always a dry no-op regardless of `dry_run`.
        """
        if dry_run or not self.is_enabled():
            sim_id = f"dry-{order.ticker}-{int(time.time() * 1000)}"
            logger.info(
                "DRY-RUN submit_order %s %s qty=%s type=%s (id=%s) — NOT posted",
                order.side,
                order.ticker,
                order.qty,
                order.order_type,
                sim_id,
            )
            return Order(
                id=sim_id,
                ticker=order.ticker,
                side=order.side,
                qty=order.qty,
                order_type=order.order_type,
                limit_price=order.limit_price,
                stop_price=order.stop_price,
                status=OrderStatus.SUBMITTED,
                filled_qty=order.filled_qty,
                filled_avg_price=order.filled_avg_price,
            )
        body = self._order_to_body(order)
        logger.info("LIVE submit_order %s %s qty=%s", order.side, order.ticker, order.qty)
        return self._map_order(self._post(_ORDERS_PATH, body))

    def cancel_order(self, order_id: str) -> bool:
        """DELETE /orders/{id}. Disabled -> False."""
        if not self.is_enabled():
            return False
        return self._delete(f"{_ORDERS_PATH}/{order_id}")

    def get_order(self, order_id: str) -> Order | None:
        """GET /orders/{id} -> Order. Disabled -> None."""
        if not self.is_enabled():
            return None
        return self._map_order(self._get(f"{_ORDERS_PATH}/{order_id}"))

    # ------------------------------------------------------------------ mappers
    def _map_account(self, account: dict, positions: list) -> Portfolio:
        """Map Alpaca /account + /positions payloads to a Portfolio."""
        return Portfolio(
            equity=float(account["equity"]),
            cash=float(account["cash"]),
            buying_power=float(account["buying_power"]),
            positions={p["symbol"]: self._map_position(p) for p in positions},
            day_trade_count=int(account.get("daytrade_count", 0)),
        )

    @staticmethod
    def _map_position(raw: dict) -> Position:
        """Map one Alpaca position payload to a Position."""
        return Position(
            ticker=raw["symbol"],
            qty=float(raw["qty"]),
            avg_entry=float(raw["avg_entry_price"]),
            market_value=float(raw["market_value"]),
            unrealized_pl=float(raw["unrealized_pl"]),
        )

    @staticmethod
    def _map_order(raw: dict) -> Order:
        """Map an Alpaca order payload to an Order."""
        raw_type = raw.get("order_type") or raw.get("type") or "market"
        order_type = OrderType.LIMIT if str(raw_type).lower() == "limit" else OrderType.MARKET
        side = Side.SELL if str(raw["side"]).lower() == "sell" else Side.BUY
        raw_status = str(raw["status"]).lower()
        status = _STATUS_FROM_ALPACA.get(raw_status)
        if status is None:
            logger.debug("unknown Alpaca order status %r — mapping to NEW", raw_status)
            status = OrderStatus.NEW
        limit_price = raw.get("limit_price")
        stop_price = raw.get("stop_price")
        filled_avg = raw.get("filled_avg_price")
        return Order(
            id=raw.get("id"),
            ticker=raw["symbol"],
            side=side,
            qty=float(raw["qty"]),
            order_type=order_type,
            limit_price=float(limit_price) if limit_price is not None else None,
            stop_price=float(stop_price) if stop_price is not None else None,
            status=status,
            filled_qty=float(raw.get("filled_qty") or 0),
            filled_avg_price=float(filled_avg) if filled_avg is not None else None,
        )

    @staticmethod
    def _order_to_body(order: Order) -> dict:
        """Build the Alpaca /orders POST body from an Order.

        C6 — real stops via OTO (one-triggers-other): a BUY entry carrying a
        `stop_price` becomes `order_class="oto"` with a nested `stop_loss` leg,
        so the protective stop rests at the venue the moment the entry fills.
        (OTO, not `bracket`: Alpaca's bracket class requires a take_profit leg
        we do not use; OTO needs only the stop_loss.)

        A bare top-level `stop_price` NEVER rides on a market/limit order — on
        Alpaca that field turns the order itself into a stop/stop-limit trigger
        order, which is not what an entry-with-protective-stop means. A SELL
        (exit/short) with a stop attached simply drops it from the body.
        """
        body: dict[str, object] = {
            "symbol": order.ticker,
            "qty": str(order.qty),
            "side": _SIDE_TO_ALPACA[order.side],
            "type": _TYPE_TO_ALPACA[order.order_type],
            "time_in_force": "day",
        }
        if order.limit_price is not None:
            body["limit_price"] = f"{order.limit_price:.2f}"
        if order.stop_price is not None and order.side is Side.BUY:
            # Alpaca rejects sub-penny prices (42210000) — round to the cent.
            body["order_class"] = "oto"
            body["stop_loss"] = {"stop_price": f"{order.stop_price:.2f}"}
        return body

    def daily_pl_pct(self) -> float | None:
        """Today's realized+unrealized P&L pct: (equity - last_equity) / last_equity.

        Alpaca's `/account` exposes `equity` (now) and `last_equity` (previous
        trading day's close). Returns None when the client is disabled or
        `last_equity` is missing/non-positive — the caller (context factory)
        turns None into 0.0 WITH a warning, so a missing feed is loud.
        """
        if not self.is_enabled():
            return None
        account = self._get(_ACCOUNT_PATH)
        if not isinstance(account, dict):
            return None
        last_equity = float(account.get("last_equity") or 0.0)
        if last_equity <= 0:
            return None
        return (float(account["equity"]) - last_equity) / last_equity

    # --------------------------------------------------------------- transports
    def _headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.key or "",
            "APCA-API-SECRET-KEY": self.secret or "",
        }

    def _get(self, path: str) -> dict | list:
        """REST GET transport (overridable in tests). Lazy httpx import."""
        import httpx  # noqa: PLC0415 (lazy: only on a real network call)

        resp = httpx.get(f"{self.endpoint}{path}", headers=self._headers(), timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: dict) -> dict:
        """REST POST transport (overridable in tests). Lazy httpx import."""
        import httpx  # noqa: PLC0415 (lazy: only on a real network call)

        resp = httpx.post(
            f"{self.endpoint}{path}", headers=self._headers(), json=body, timeout=30
        )
        if resp.status_code >= 400:
            # Surface the broker's rejection reason — a bare 422 is undiagnosable.
            logger.error(
                "Alpaca %s %s -> %s: %s", path, body, resp.status_code, resp.text
            )
        resp.raise_for_status()
        return resp.json()

    def _delete(self, path: str) -> bool:
        """REST DELETE transport (overridable in tests). Lazy httpx import."""
        import httpx  # noqa: PLC0415 (lazy: only on a real network call)

        resp = httpx.delete(f"{self.endpoint}{path}", headers=self._headers(), timeout=30)
        resp.raise_for_status()
        return True
