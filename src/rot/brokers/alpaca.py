"""Alpaca Markets paper-trading integration for ROT signal execution.

Uses Alpaca's REST API v2 + Options endpoints (available on their Broker API and
paper-trading sandbox).  Paper trading is the default for safety.

Required environment variables
-------------------------------
ALPACA_API_KEY    -- Alpaca API key ID
ALPACA_SECRET_KEY -- Alpaca API secret key

Optional
--------
ALPACA_PAPER      -- Set to "false" to use the live endpoint (default: "true")
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

try:
    import httpx
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "httpx is required for AlpacaBroker.  Install it with: pip install httpx"
    ) from exc

from rot.brokers.base import AccountInfo, BrokerClient, OptionOrder, OrderResult


class AlpacaError(Exception):
    """Raised when the Alpaca API returns a non-2xx response."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Alpaca API error {status_code}: {detail}")


class AlpacaBroker(BrokerClient):
    """Alpaca Markets paper trading integration for ROT signal execution.

    Uses Alpaca's REST API v2.  Defaults to the paper-trading endpoint for
    safety -- set ``paper=False`` *only* in a fully-reviewed production setup.

    Args:
        api_key:    Alpaca API key ID.
        secret_key: Alpaca API secret key.
        paper:      When True (default), route all requests to the paper-trading
                    sandbox (``paper-api.alpaca.markets``).
        timeout:    Per-request timeout in seconds (default: 15).
    """

    PAPER_URL = "https://paper-api.alpaca.markets"
    LIVE_URL = "https://api.alpaca.markets"
    DATA_URL = "https://data.alpaca.markets"

    # Alpaca API version prefix
    _API_V2 = "/v2"
    _API_V1B1 = "/v1beta1"

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        paper: bool = True,
        timeout: float = 15.0,
    ) -> None:
        self._api_key = api_key or os.environ.get("ALPACA_API_KEY", "")
        self._secret_key = secret_key or os.environ.get("ALPACA_SECRET_KEY", "")
        if not self._api_key or not self._secret_key:
            raise ValueError(
                "Alpaca credentials not found. "
                "Set ALPACA_API_KEY and ALPACA_SECRET_KEY environment variables, "
                "or pass api_key and secret_key arguments."
            )
        self._base_url = self.PAPER_URL if paper else self.LIVE_URL
        self._timeout = timeout
        self._headers = {
            "APCA-API-KEY-ID": self._api_key,
            "APCA-API-SECRET-KEY": self._secret_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    # ------------------------------------------------------------------
    # Internal HTTP helpers
    # ------------------------------------------------------------------

    async def _get(self, path: str, base: Optional[str] = None, **params: Any) -> Any:
        url = (base or self._base_url) + path
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.get(url, headers=self._headers, params=params)
        self._raise_for_status(response)
        return response.json()

    async def _post(self, path: str, body: Dict[str, Any]) -> Any:
        url = self._base_url + path
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(url, headers=self._headers, json=body)
        self._raise_for_status(response)
        return response.json()

    async def _delete(self, path: str) -> Any:
        url = self._base_url + path
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.delete(url, headers=self._headers)
        # 204 No Content is a valid success for cancellations
        if response.status_code not in (200, 204):
            self._raise_for_status(response)
        return response.status_code in (200, 204)

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        if response.status_code >= 400:
            try:
                detail = response.json().get("message", response.text)
            except Exception:
                detail = response.text
            raise AlpacaError(response.status_code, detail)

    # ------------------------------------------------------------------
    # BrokerClient implementation
    # ------------------------------------------------------------------

    async def get_account(self) -> AccountInfo:
        """Fetch account snapshot from Alpaca /v2/account."""
        data = await self._get(f"{self._API_V2}/account")
        return AccountInfo(
            account_id=data.get("id", ""),
            buying_power=Decimal(str(data.get("buying_power", "0"))),
            portfolio_value=Decimal(str(data.get("portfolio_value", "0"))),
            open_positions=await self.get_positions(),
        )

    async def submit_order(self, order: OptionOrder) -> OrderResult:
        """Submit an options order via Alpaca /v2/orders.

        Alpaca represents options legs using an OCC-style symbol:
        ``{symbol}{expiry_YYMMDD}{C|P}{strike*1000:08d}``

        The method builds this symbol from the structured :class:`OptionOrder`
        fields automatically.
        """
        occ_symbol = self._build_occ_symbol(order)
        body: Dict[str, Any] = {
            "symbol": occ_symbol,
            "qty": str(order.quantity),
            "side": self._map_action_to_side(order.action),
            "type": order.order_type,
            "time_in_force": "day",
        }
        if order.order_type == "limit" and order.limit_price is not None:
            body["limit_price"] = str(order.limit_price)

        data = await self._post(f"{self._API_V2}/orders", body)
        return self._parse_order_result(data)

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open Alpaca order by ID."""
        result = await self._delete(f"{self._API_V2}/orders/{order_id}")
        return bool(result)

    async def get_option_chain(self, symbol: str, expiry: str) -> List[dict]:
        """Fetch option contracts for *symbol* expiring on *expiry* (YYYY-MM-DD).

        Uses the Alpaca Options Contracts endpoint (v1beta1).  Returns a list of
        contract dicts normalised to the common schema used by ROT.
        """
        params = {
            "underlying_symbols": symbol,
            "expiration_date": expiry,
            "limit": 1000,
        }
        data = await self._get(
            f"{self._API_V1B1}/options/contracts",
            base=self.DATA_URL,
            **params,
        )
        contracts = data.get("option_contracts", [])
        return [self._normalise_contract(c) for c in contracts]

    async def get_positions(self) -> List[dict]:
        """Return all open positions from Alpaca /v2/positions."""
        data = await self._get(f"{self._API_V2}/positions")
        return [
            {
                "symbol": p.get("symbol"),
                "qty": int(p.get("qty", 0)),
                "avg_entry_price": p.get("avg_entry_price"),
                "market_value": p.get("market_value"),
                "unrealized_pl": p.get("unrealized_pl"),
                "side": p.get("side"),
                "asset_class": p.get("asset_class"),
            }
            for p in (data if isinstance(data, list) else [])
        ]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_occ_symbol(order: OptionOrder) -> str:
        """Convert an OptionOrder to OCC option symbol format.

        Format: ``{SYMBOL:<6}{YYMMDD}{C|P}{STRIKE*1000:08d}``
        Example: AAPL  261219C00150000  (AAPL $150 call, 19-Dec-2026)
        """
        symbol_padded = order.symbol.upper().ljust(6)
        expiry = datetime.strptime(order.expiry, "%Y-%m-%d")
        date_part = expiry.strftime("%y%m%d")
        cp = "C" if order.option_type.lower() == "call" else "P"
        strike_int = int(order.strike * 1000)
        return f"{symbol_padded}{date_part}{cp}{strike_int:08d}"

    @staticmethod
    def _map_action_to_side(action: str) -> str:
        """Map ROT order action strings to Alpaca side strings."""
        mapping = {
            "buy_to_open": "buy",
            "buy_to_close": "buy",
            "sell_to_open": "sell",
            "sell_to_close": "sell",
        }
        return mapping.get(action.lower(), "buy")

    @staticmethod
    def _parse_order_result(data: Dict[str, Any]) -> OrderResult:
        filled_qty_raw = data.get("filled_qty")
        filled_qty = int(filled_qty_raw) if filled_qty_raw else 0
        avg_price_raw = data.get("filled_avg_price")
        avg_price = Decimal(str(avg_price_raw)) if avg_price_raw else None
        return OrderResult(
            order_id=data.get("id", ""),
            status=data.get("status", "unknown"),
            filled_qty=filled_qty,
            avg_price=avg_price,
            timestamp=data.get("created_at", datetime.now(tz=timezone.utc).isoformat()),
        )

    @staticmethod
    def _normalise_contract(c: Dict[str, Any]) -> dict:
        """Normalise an Alpaca options contract dict to ROT's common schema."""
        return {
            "symbol": c.get("symbol"),
            "underlying": c.get("underlying_symbol"),
            "option_type": c.get("type", "").lower(),
            "strike": c.get("strike_price"),
            "expiry": c.get("expiration_date"),
            "bid": c.get("bid_price"),
            "ask": c.get("ask_price"),
            "volume": c.get("volume"),
            "open_interest": c.get("open_interest"),
            "implied_volatility": c.get("implied_volatility"),
            "delta": c.get("delta"),
            "gamma": c.get("gamma"),
            "theta": c.get("theta"),
            "vega": c.get("vega"),
        }
