"""Small, auditable Binance USDⓈ-M Futures REST client.

Only endpoints required by the daily target-weight executor are exposed.
Secrets are accepted by the constructor and are never logged or persisted.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

import requests


class BinanceAPIError(RuntimeError):
    """A Binance request failed or returned an ambiguous order result."""


@dataclass(frozen=True)
class SymbolRules:
    symbol: str
    status: str
    contract_type: str
    step_size: Decimal
    min_qty: Decimal
    max_qty: Decimal
    min_notional: Decimal

    @property
    def tradable(self) -> bool:
        return self.status == "TRADING" and self.contract_type == "PERPETUAL"


class BinanceFuturesClient:
    MAINNET_URL = "https://fapi.binance.com"
    TESTNET_URL = "https://demo-fapi.binance.com"

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        base_url: str | None = None,
        timeout: float = 15.0,
        recv_window: int = 5000,
        session: requests.Session | None = None,
    ):
        if not api_key or not api_secret:
            raise ValueError("Binance API key and secret are required")
        self.api_key = api_key
        self._secret = api_secret.encode()
        self.base_url = (base_url or self.MAINNET_URL).rstrip("/")
        self.timeout = float(timeout)
        self.recv_window = int(recv_window)
        self.session = session or requests.Session()
        self.session.headers.update({"X-MBX-APIKEY": api_key})

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        signed: bool = False,
    ) -> Any:
        payload = {k: v for k, v in (params or {}).items() if v is not None}
        if signed:
            payload["recvWindow"] = self.recv_window
            payload["timestamp"] = int(time.time() * 1000)
            query = urlencode(payload)
            payload["signature"] = hmac.new(
                self._secret, query.encode(), hashlib.sha256
            ).hexdigest()
        try:
            response = self.session.request(
                method,
                f"{self.base_url}{path}",
                params=payload,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise BinanceAPIError(f"{method} {path} transport failure: {exc}") from exc
        try:
            body = response.json()
        except ValueError:
            body = {"msg": response.text[:500]}
        if not response.ok:
            raise BinanceAPIError(
                f"{method} {path} failed HTTP {response.status_code}: "
                f"{body.get('code', '?')} {body.get('msg', body)}"
            )
        return body

    def server_time(self) -> int:
        return int(self._request("GET", "/fapi/v1/time")["serverTime"])

    def symbol_rules(self) -> dict[str, SymbolRules]:
        payload = self._request("GET", "/fapi/v1/exchangeInfo")
        result: dict[str, SymbolRules] = {}
        for item in payload.get("symbols", []):
            filters = {f["filterType"]: f for f in item.get("filters", [])}
            lot = filters.get("MARKET_LOT_SIZE") or filters.get("LOT_SIZE") or {}
            notion = filters.get("MIN_NOTIONAL") or {}
            symbol = str(item["symbol"]).upper()
            result[symbol] = SymbolRules(
                symbol=symbol,
                status=str(item.get("status", "")),
                contract_type=str(item.get("contractType", "")),
                step_size=Decimal(str(lot.get("stepSize", "0"))),
                min_qty=Decimal(str(lot.get("minQty", "0"))),
                max_qty=Decimal(str(lot.get("maxQty", "0"))),
                min_notional=Decimal(str(notion.get("notional", "0"))),
            )
        return result

    def mark_prices(self) -> dict[str, Decimal]:
        payload = self._request("GET", "/fapi/v1/premiumIndex")
        return {
            str(row["symbol"]).upper(): Decimal(str(row["markPrice"]))
            for row in payload
            if Decimal(str(row.get("markPrice", "0"))) > 0
        }

    def balances(self) -> list[dict[str, Any]]:
        return list(self._request("GET", "/fapi/v3/balance", signed=True))

    def positions(self) -> dict[str, Decimal]:
        payload = self._request("GET", "/fapi/v3/positionRisk", signed=True)
        return {
            str(row["symbol"]).upper(): Decimal(str(row["positionAmt"]))
            for row in payload
            if Decimal(str(row.get("positionAmt", "0"))) != 0
        }

    def is_hedge_mode(self) -> bool:
        payload = self._request("GET", "/fapi/v1/positionSide/dual", signed=True)
        return bool(payload.get("dualSidePosition"))

    def open_orders(self) -> list[dict[str, Any]]:
        return list(self._request("GET", "/fapi/v1/openOrders", signed=True))

    def market_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: Decimal,
        reduce_only: bool,
        client_order_id: str,
    ) -> dict[str, Any]:
        return dict(
            self._request(
                "POST",
                "/fapi/v1/order",
                signed=True,
                params={
                    "symbol": symbol,
                    "side": side,
                    "type": "MARKET",
                    "quantity": format(quantity, "f"),
                    "reduceOnly": "true" if reduce_only else "false",
                    "newClientOrderId": client_order_id[:36],
                    "newOrderRespType": "RESULT",
                },
            )
        )

    def set_leverage(self, symbol: str, leverage: int = 1) -> dict[str, Any]:
        return dict(
            self._request(
                "POST",
                "/fapi/v1/leverage",
                signed=True,
                params={"symbol": symbol, "leverage": int(leverage)},
            )
        )
