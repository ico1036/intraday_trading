"""Binance aggTrade WebSocket client."""

import asyncio
import json
import ssl
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Optional

import websockets
from websockets.asyncio.client import connect
from websockets.exceptions import (
    ConnectionClosed,
    ConnectionClosedError,
    ConnectionClosedOK,
    InvalidHandshake,
    InvalidURI,
)


@dataclass
class AggTrade:
    """Aggregated trade event used by backtests and forward tests."""

    timestamp: datetime
    symbol: str
    price: float
    quantity: float
    is_buyer_maker: bool


class BinanceAggTradeClient:
    """Binance aggTrade-only WebSocket client with automatic reconnect."""

    BASE_URL = "wss://stream.binance.com:9443/ws"

    def __init__(self, symbol: str = "btcusdt"):
        self.symbol = symbol.lower()
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False

    @property
    def ws_url(self) -> str:
        return f"{self.BASE_URL}/{self.symbol}@aggTrade"

    def _parse_aggtrade(self, data: dict) -> AggTrade:
        return AggTrade(
            timestamp=datetime.fromtimestamp(data.get("T", 0) / 1000),
            symbol=data.get("s", self.symbol.upper()),
            price=float(data.get("p", 0)),
            quantity=float(data.get("q", 0)),
            is_buyer_maker=data.get("m", False),
        )

    async def connect(
        self,
        on_trade: Callable[[AggTrade], None],
        on_error: Optional[Callable[[Exception], None]] = None,
    ) -> None:
        self._running = True
        print(f"[AggTradeClient] Connecting to {self.ws_url}...")

        async for ws in connect(self.ws_url):
            if not self._running:
                break

            try:
                self._ws = ws
                print(f"[AggTradeClient] Connected! Receiving {self.symbol.upper()} trades...")

                async for message in ws:
                    if not self._running:
                        break

                    try:
                        trade = self._parse_aggtrade(json.loads(message))
                        if asyncio.iscoroutinefunction(on_trade):
                            await on_trade(trade)
                        else:
                            on_trade(trade)
                    except json.JSONDecodeError as exc:
                        print(f"[AggTradeClient] JSON parse error: {exc}")
                        if on_error:
                            on_error(exc)

            except ConnectionClosedOK:
                print("[AggTradeClient] Connection closed normally.")
                if not self._running:
                    break
                print("[AggTradeClient] Reconnecting...")
                continue
            except ConnectionClosedError as exc:
                print(f"[AggTradeClient] Connection closed with error: {exc}")
                if not self._running:
                    break
                print("[AggTradeClient] Reconnecting...")
                continue
            except ConnectionClosed as exc:
                print(f"[AggTradeClient] Connection closed: {exc}")
                if not self._running:
                    break
                print("[AggTradeClient] Reconnecting...")
                continue
            except InvalidHandshake as exc:
                if "429" in str(exc):
                    print("[AggTradeClient] Rate limited (429). Stopping.")
                    self._running = False
                    if on_error:
                        on_error(exc)
                    break
                print(f"[AggTradeClient] Handshake failed: {exc}")
                if on_error:
                    on_error(exc)
                continue
            except InvalidURI as exc:
                print(f"[AggTradeClient] Invalid URI: {exc}")
                self._running = False
                if on_error:
                    on_error(exc)
                break
            except (ssl.SSLError, OSError, ConnectionResetError) as exc:
                print(f"[AggTradeClient] Network error: {exc}")
                if on_error:
                    on_error(exc)
                continue
            except Exception as exc:
                print(f"[AggTradeClient] Unexpected error: {exc}")
                if on_error:
                    on_error(exc)
                continue

        print("[AggTradeClient] Connection loop ended.")

    async def disconnect(self) -> None:
        self._running = False
        if self._ws:
            try:
                await asyncio.wait_for(self._ws.close(), timeout=1.0)
            except asyncio.TimeoutError:
                print("[AggTradeClient] WebSocket close timed out.")
            except Exception as exc:
                print(f"[AggTradeClient] Error closing websocket: {exc}")
            self._ws = None
        print("[AggTradeClient] Disconnected.")
