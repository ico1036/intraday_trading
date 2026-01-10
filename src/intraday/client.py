"""
Binance WebSocket 클라이언트

Binance의 실시간 Orderbook 데이터를 WebSocket으로 수신합니다.
교육 목적으로 상세한 주석을 포함합니다.

Auto-reconnection:
    websockets 라이브러리의 표준 패턴을 사용합니다.
    `async for websocket in connect(uri)` 패턴은 자동으로 무한 재연결합니다.

    참고: https://websockets.readthedocs.io/en/stable/reference/asyncio/client.html
"""

import asyncio
import json
import ssl
from typing import Callable, Optional
from dataclasses import dataclass
from datetime import datetime

import websockets
from websockets.asyncio.client import connect
from websockets.exceptions import (
    ConnectionClosed,
    ConnectionClosedOK,
    ConnectionClosedError,
    InvalidHandshake,
    InvalidURI,
)


@dataclass
class AggTrade:
    """
    집계된 거래 데이터 (Aggregated Trade)
    
    Attributes:
        timestamp: 거래 시간
        symbol: 거래쌍 (예: BTCUSDT)
        price: 거래 가격
        quantity: 거래 수량
        is_buyer_maker: 매수자가 메이커인지 여부
    
    교육 포인트:
        - is_buyer_maker=True: 매수자가 지정가 주문 → 매도자가 시장가로 팔음 → 매도 주도
        - is_buyer_maker=False: 매도자가 지정가 주문 → 매수자가 시장가로 삼 → 매수 주도
        - 이 정보로 시장 참여자들의 공격적인 방향을 파악할 수 있음
    """
    timestamp: datetime
    symbol: str
    price: float
    quantity: float
    is_buyer_maker: bool  # True=매도주도, False=매수주도


@dataclass
class OrderbookSnapshot:
    """
    Orderbook 스냅샷 데이터 클래스
    
    Attributes:
        timestamp: 데이터 수신 시간
        last_update_id: Binance에서 제공하는 업데이트 ID
        bids: 매수 호가 리스트 [(가격, 수량), ...]  - 가격 내림차순
        asks: 매도 호가 리스트 [(가격, 수량), ...]  - 가격 오름차순
        symbol: 거래쌍 (예: BTCUSDT)
    """
    timestamp: datetime
    last_update_id: int
    bids: list[tuple[float, float]]  # [(price, quantity), ...]
    asks: list[tuple[float, float]]  # [(price, quantity), ...]
    symbol: str


class BinanceWebSocketClient:
    """
    Binance WebSocket 클라이언트
    
    실시간 Orderbook 데이터를 수신하기 위한 WebSocket 클라이언트입니다.
    
    사용 예시:
        async def on_orderbook(snapshot: OrderbookSnapshot):
            print(f"Best Bid: {snapshot.bids[0]}, Best Ask: {snapshot.asks[0]}")
        
        client = BinanceWebSocketClient("btcusdt")
        await client.connect(on_orderbook)
    
    교육 포인트:
        - Binance는 API 키 없이도 공개 시장 데이터를 제공합니다.
        - depth20@100ms: 상위 20개 호가를 100ms마다 업데이트
        - WebSocket을 사용하면 HTTP 폴링보다 지연시간이 훨씬 짧습니다.
    """
    
    # Binance WebSocket 스트림 기본 URL
    BASE_URL = "wss://stream.binance.com:9443/ws"
    
    def __init__(
        self,
        symbol: str = "btcusdt",
        depth_levels: int = 20,
        update_speed: str = "100ms"
    ):
        """
        Args:
            symbol: 거래쌍 (소문자, 예: btcusdt, ethusdt)
            depth_levels: 호가 깊이 (5, 10, 20 중 선택)
            update_speed: 업데이트 속도 ("100ms" 또는 "1000ms")
        
        교육 포인트:
            - depth_levels가 높을수록 더 많은 호가 정보를 받지만 데이터량 증가
            - update_speed가 빠를수록 실시간성이 좋지만 처리 부하 증가
            - 실전에서는 전략에 맞는 적절한 값을 선택해야 합니다.
        """
        self.symbol = symbol.lower()
        self.depth_levels = depth_levels
        self.update_speed = update_speed
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        
    @property
    def stream_name(self) -> str:
        """
        Binance 스트림 이름 생성
        
        형식: {symbol}@depth{levels}@{speed}
        예: btcusdt@depth20@100ms
        """
        return f"{self.symbol}@depth{self.depth_levels}@{self.update_speed}"
    
    @property
    def ws_url(self) -> str:
        """WebSocket 연결 URL"""
        return f"{self.BASE_URL}/{self.stream_name}"
    
    def _parse_orderbook(self, data: dict) -> OrderbookSnapshot:
        """
        Binance WebSocket 메시지를 OrderbookSnapshot으로 파싱
        
        Binance 응답 형식:
        {
            "lastUpdateId": 160,
            "bids": [["가격", "수량"], ...],  # 가격 내림차순 (최고 매수가가 첫 번째)
            "asks": [["가격", "수량"], ...]   # 가격 오름차순 (최저 매도가가 첫 번째)
        }
        
        교육 포인트:
            - bids[0]은 Best Bid (최고 매수 호가) - 시장에서 가장 높은 가격에 사려는 주문
            - asks[0]은 Best Ask (최저 매도 호가) - 시장에서 가장 낮은 가격에 팔려는 주문
            - 시장가 매수 시 asks[0] 가격에 체결, 시장가 매도 시 bids[0] 가격에 체결
        """

        # Binance 는 가격을 문자열로 보냄. 이걸 float 으로 변환함
        bids = [(float(price), float(qty)) for price, qty in data.get("bids", [])]
        asks = [(float(price), float(qty)) for price, qty in data.get("asks", [])]
        
        return OrderbookSnapshot(
            timestamp=datetime.now(),
            last_update_id=data.get("lastUpdateId", 0),
            bids=bids,
            asks=asks,
            symbol=self.symbol.upper()
        )
    
    async def connect(
        self,
        on_orderbook: Callable[[OrderbookSnapshot], None],
        on_error: Optional[Callable[[Exception], None]] = None,
    ):
        """
        WebSocket 연결 및 데이터 수신 시작 (무한 자동 재연결)

        Args:
            on_orderbook: Orderbook 데이터 수신 시 호출될 콜백 함수
            on_error: 에러 발생 시 호출될 콜백 함수 (선택)

        교육 포인트:
            - websockets 표준 패턴: `async for ws in connect(uri)` 사용
            - ConnectionClosed 발생 시 자동으로 재연결 (무한)
            - 429 (Rate Limit) 에러는 즉시 중단 (더 이상 시도해도 무의미)
            - SSL, Network 에러는 자동 재연결
        """
        self._running = True

        print(f"[Client] Connecting to {self.ws_url}...")

        # websockets 표준 패턴: async for로 자동 재연결
        async for ws in connect(self.ws_url):
            if not self._running:
                break

            try:
                self._ws = ws
                print(f"[Client] Connected! Receiving {self.symbol.upper()} orderbook...")

                async for message in ws:
                    if not self._running:
                        break

                    try:
                        data = json.loads(message)
                        snapshot = self._parse_orderbook(data)

                        if asyncio.iscoroutinefunction(on_orderbook):
                            await on_orderbook(snapshot)
                        else:
                            on_orderbook(snapshot)

                    except json.JSONDecodeError as e:
                        print(f"[Client] JSON 파싱 에러: {e}")
                        if on_error:
                            on_error(e)

            except ConnectionClosedOK:
                # 정상 종료 (close frame 교환 완료)
                print("[Client] Connection closed normally.")
                if not self._running:
                    break
                print("[Client] Reconnecting...")
                continue

            except ConnectionClosedError as e:
                # 비정상 종료 (에러로 인한 종료)
                print(f"[Client] Connection closed with error: {e}")
                if not self._running:
                    break
                print("[Client] Reconnecting...")
                continue

            except ConnectionClosed as e:
                # 일반 연결 종료 (fallback)
                print(f"[Client] Connection closed: {e}")
                if not self._running:
                    break
                print("[Client] Reconnecting...")
                continue

            except InvalidHandshake as e:
                # HTTP 핸드셰이크 실패 (4xx, 5xx 포함)
                error_str = str(e)
                if "429" in error_str:
                    print(f"[Client] Rate limited (429). Stopping.")
                    self._running = False
                    if on_error:
                        on_error(e)
                    break
                print(f"[Client] Handshake failed: {e}")
                if on_error:
                    on_error(e)
                continue

            except InvalidURI as e:
                # 잘못된 URI - 재연결 의미 없음
                print(f"[Client] Invalid URI: {e}")
                self._running = False
                if on_error:
                    on_error(e)
                break

            except (ssl.SSLError, OSError, ConnectionResetError) as e:
                print(f"[Client] Network error: {e}")
                if on_error:
                    on_error(e)
                continue

            except Exception as e:
                print(f"[Client] Unexpected error: {e}")
                if on_error:
                    on_error(e)
                continue

        print("[Client] Connection loop ended.")
    
    async def disconnect(self):
        """WebSocket 연결 종료"""
        self._running = False
        if self._ws:
            try:
                # Graceful close 시도하되 1초 타임아웃
                await asyncio.wait_for(self._ws.close(), timeout=1.0)
            except asyncio.TimeoutError:
                print("[Client] WebSocket close timed out, socket might be left open.")
            except Exception as e:
                print(f"[Client] Error closing websocket: {e}")
            self._ws = None
        print("[Client] Disconnected.")


# 단독 실행 시 테스트 코드
async def _test():  # pragma: no cover
    """클라이언트 테스트"""
    client = BinanceWebSocketClient("btcusdt")
    count = 0
    
    def on_data(snapshot: OrderbookSnapshot):
        nonlocal count
        count += 1
        if snapshot.bids and snapshot.asks:
            best_bid = snapshot.bids[0]
            best_ask = snapshot.asks[0]
            spread = best_ask[0] - best_bid[0]
            print(
                f"[{count}] {snapshot.symbol} | "
                f"Bid: ${best_bid[0]:,.2f} ({best_bid[1]:.4f}) | "
                f"Ask: ${best_ask[0]:,.2f} ({best_ask[1]:.4f}) | "
                f"Spread: ${spread:.2f}"
            )
        
        # 테스트: 10개 메시지 후 종료
        if count >= 10:
            asyncio.create_task(client.disconnect())
    
    await client.connect(on_data)


class BinanceCombinedClient:
    """
    Binance Combined WebSocket 클라이언트
    
    Orderbook + AggTrade를 하나의 WebSocket으로 수신합니다.
    
    사용 예시:
        async def on_orderbook(snapshot: OrderbookSnapshot):
            print(f"Orderbook: {snapshot}")
        
        async def on_trade(trade: AggTrade):
            print(f"Trade: {trade}")
        
        client = BinanceCombinedClient("btcusdt")
        await client.connect(on_orderbook, on_trade)
    
    교육 포인트:
        - Combined Stream은 여러 스트림을 하나의 연결로 받음
        - 네트워크 오버헤드 감소
        - 각 메시지에 stream 필드가 추가됨
    """
    
    # Binance Combined Stream URL
    BASE_URL = "wss://stream.binance.com:9443/stream"
    
    def __init__(
        self,
        symbol: str = "btcusdt",
        depth_levels: int = 20,
        update_speed: str = "100ms"
    ):
        """
        Args:
            symbol: 거래쌍 (소문자, 예: btcusdt, ethusdt)
            depth_levels: 호가 깊이 (5, 10, 20 중 선택)
            update_speed: 업데이트 속도 ("100ms" 또는 "1000ms")
        """
        self.symbol = symbol.lower()
        self.depth_levels = depth_levels
        self.update_speed = update_speed
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
    
    @property
    def orderbook_stream(self) -> str:
        """Orderbook 스트림 이름"""
        return f"{self.symbol}@depth{self.depth_levels}@{self.update_speed}"
    
    @property
    def aggtrade_stream(self) -> str:
        """AggTrade 스트림 이름"""
        return f"{self.symbol}@aggTrade"
    
    @property
    def ws_url(self) -> str:
        """Combined WebSocket URL"""
        streams = f"{self.orderbook_stream}/{self.aggtrade_stream}"
        return f"{self.BASE_URL}?streams={streams}"
    
    def _parse_aggtrade(self, data: dict) -> AggTrade:
        """
        Binance aggTrade 메시지를 AggTrade로 파싱
        
        Binance 응답 형식:
        {
            "e": "aggTrade",     # 이벤트 타입
            "E": 123456789,      # 이벤트 시간
            "s": "BTCUSDT",      # 심볼
            "a": 12345,          # Aggregate trade ID
            "p": "0.001",        # 가격
            "q": "100",          # 수량
            "f": 100,            # First trade ID
            "l": 105,            # Last trade ID
            "T": 123456785,      # 거래 시간
            "m": true,           # Is buyer maker
            "M": true            # Ignore
        }
        """
        return AggTrade(
            timestamp=datetime.fromtimestamp(data.get("T", 0) / 1000),
            symbol=data.get("s", self.symbol.upper()),
            price=float(data.get("p", 0)),
            quantity=float(data.get("q", 0)),
            is_buyer_maker=data.get("m", False),
        )
    
    def _parse_orderbook(self, data: dict) -> OrderbookSnapshot:
        """Orderbook 메시지 파싱 (BinanceWebSocketClient와 동일)"""
        bids = [(float(price), float(qty)) for price, qty in data.get("bids", [])]
        asks = [(float(price), float(qty)) for price, qty in data.get("asks", [])]
        
        return OrderbookSnapshot(
            timestamp=datetime.now(),
            last_update_id=data.get("lastUpdateId", 0),
            bids=bids,
            asks=asks,
            symbol=self.symbol.upper()
        )
    
    async def connect(
        self,
        on_orderbook: Callable[[OrderbookSnapshot], None],
        on_trade: Callable[[AggTrade], None],
        on_error: Optional[Callable[[Exception], None]] = None,
    ):
        """
        WebSocket 연결 및 데이터 수신 시작 (무한 자동 재연결)

        Args:
            on_orderbook: Orderbook 데이터 수신 시 콜백
            on_trade: AggTrade 데이터 수신 시 콜백
            on_error: 에러 발생 시 콜백 (선택)

        교육 포인트:
            - websockets 표준 패턴: `async for ws in connect(uri)` 사용
            - ConnectionClosed 발생 시 자동으로 재연결 (무한)
            - 429 (Rate Limit) 에러는 즉시 중단 (더 이상 시도해도 무의미)
            - SSL, Network 에러는 자동 재연결
        """
        self._running = True

        print(f"[CombinedClient] Connecting to {self.ws_url}...")

        # websockets 표준 패턴: async for로 자동 재연결
        async for ws in connect(self.ws_url):
            if not self._running:
                break

            try:
                self._ws = ws
                print(f"[CombinedClient] Connected! Receiving {self.symbol.upper()} data...")

                async for message in ws:
                    if not self._running:
                        break

                    try:
                        raw = json.loads(message)
                        stream = raw.get("stream", "")
                        data = raw.get("data", {})

                        if "depth" in stream:
                            snapshot = self._parse_orderbook(data)
                            if asyncio.iscoroutinefunction(on_orderbook):
                                await on_orderbook(snapshot)
                            else:
                                on_orderbook(snapshot)

                        elif "aggTrade" in stream:
                            trade = self._parse_aggtrade(data)
                            if asyncio.iscoroutinefunction(on_trade):
                                await on_trade(trade)
                            else:
                                on_trade(trade)

                    except json.JSONDecodeError as e:
                        print(f"[CombinedClient] JSON 파싱 에러: {e}")
                        if on_error:
                            on_error(e)

            except ConnectionClosedOK:
                # 정상 종료 (close frame 교환 완료)
                print("[CombinedClient] Connection closed normally.")
                if not self._running:
                    break
                print("[CombinedClient] Reconnecting...")
                continue

            except ConnectionClosedError as e:
                # 비정상 종료 (에러로 인한 종료)
                print(f"[CombinedClient] Connection closed with error: {e}")
                if not self._running:
                    break
                print("[CombinedClient] Reconnecting...")
                continue

            except ConnectionClosed as e:
                # 일반 연결 종료 (fallback)
                print(f"[CombinedClient] Connection closed: {e}")
                if not self._running:
                    break
                print("[CombinedClient] Reconnecting...")
                continue

            except InvalidHandshake as e:
                # HTTP 핸드셰이크 실패 (4xx, 5xx 포함)
                error_str = str(e)
                if "429" in error_str:
                    print(f"[CombinedClient] Rate limited (429). Stopping.")
                    self._running = False
                    if on_error:
                        on_error(e)
                    break
                print(f"[CombinedClient] Handshake failed: {e}")
                if on_error:
                    on_error(e)
                continue

            except InvalidURI as e:
                # 잘못된 URI - 재연결 의미 없음
                print(f"[CombinedClient] Invalid URI: {e}")
                self._running = False
                if on_error:
                    on_error(e)
                break

            except (ssl.SSLError, OSError, ConnectionResetError) as e:
                print(f"[CombinedClient] Network error: {e}")
                if on_error:
                    on_error(e)
                continue

            except Exception as e:
                print(f"[CombinedClient] Unexpected error: {e}")
                if on_error:
                    on_error(e)
                continue

        print("[CombinedClient] Connection loop ended.")
    
    async def disconnect(self):
        """WebSocket 연결 종료"""
        self._running = False
        if self._ws:
            try:
                # Graceful close 시도하되 1초 타임아웃
                await asyncio.wait_for(self._ws.close(), timeout=1.0)
            except asyncio.TimeoutError:
                print("[CombinedClient] WebSocket close timed out.")
            except Exception as e:
                print(f"[CombinedClient] Error closing websocket: {e}")
            self._ws = None
        print("[CombinedClient] Disconnected.")


if __name__ == "__main__":  # pragma: no cover
    print("=== Binance WebSocket Client Test ===")
    print("BTC/USDT Orderbook 데이터를 10개 수신 후 종료합니다.\n")
    asyncio.run(_test())

