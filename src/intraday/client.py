"""
Binance WebSocket 클라이언트

Binance의 실시간 Orderbook 데이터를 WebSocket으로 수신합니다.
교육 목적으로 상세한 주석을 포함합니다.
"""

import asyncio
import json
from typing import Callable, Optional
from dataclasses import dataclass
from datetime import datetime

import websockets


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
        max_reconnect_attempts: int = 5
    ):
        """
        WebSocket 연결 및 데이터 수신 시작
        
        Args:
            on_orderbook: Orderbook 데이터 수신 시 호출될 콜백 함수
            on_error: 에러 발생 시 호출될 콜백 함수 (선택)
            max_reconnect_attempts: 최대 재연결 시도 횟수
        
        교육 포인트:
            - WebSocket은 지속 연결로, HTTP보다 오버헤드가 적습니다.
            - 네트워크 불안정 시 자동 재연결 로직이 중요합니다.
            - 프로덕션에서는 더 견고한 에러 처리가 필요합니다.
        """
        self._running = True
        reconnect_attempts = 0
        
        while self._running and reconnect_attempts < max_reconnect_attempts:
            try:
                print(f"[Client] Connecting to {self.ws_url}...")
                
                async with websockets.connect(self.ws_url) as ws:
                    self._ws = ws
                    reconnect_attempts = 0  # 연결 성공 시 카운터 리셋
                    print(f"[Client] Connected! Receiving {self.symbol.upper()} orderbook...")
                    
                    async for message in ws:
                        if not self._running:
                            break
                        
                        try:
                            data = json.loads(message)
                            snapshot = self._parse_orderbook(data)
                            
                            # 콜백이 코루틴인 경우와 일반 함수인 경우 모두 처리
                            if asyncio.iscoroutinefunction(on_orderbook):
                                await on_orderbook(snapshot)
                            else:
                                on_orderbook(snapshot)
                                
                        except json.JSONDecodeError as e:
                            print(f"[Client] JSON 파싱 에러: {e}")
                            if on_error:
                                on_error(e)
                                
            except websockets.ConnectionClosed as e:
                # 흔한 서버 연결 끊긴 상황 -> 지수 백오프로 최적화된 재연결 시도
                print(f"[Client] Connection closed: {e}")
                reconnect_attempts += 1
                if self._running and reconnect_attempts < max_reconnect_attempts:
                    wait_time = min(2 ** reconnect_attempts, 30)  # 지수 백오프
                    print(f"[Client] Reconnecting in {wait_time}s... (attempt {reconnect_attempts})")
                    await asyncio.sleep(wait_time)
                    
            except Exception as e:
                # something wrong 다른 에러.. 2초만 대기
                print(f"[Client] Error: {e}")
                if on_error:
                    on_error(e)
                reconnect_attempts += 1
                if self._running and reconnect_attempts < max_reconnect_attempts:
                    await asyncio.sleep(2)
        
        if reconnect_attempts >= max_reconnect_attempts:
            print(f"[Client] Max reconnect attempts reached. Stopping.")
    
    async def disconnect(self):
        """WebSocket 연결 종료"""
        self._running = False
        if self._ws:
            await self._ws.close()
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


if __name__ == "__main__":  # pragma: no cover
    print("=== Binance WebSocket Client Test ===")
    print("BTC/USDT Orderbook 데이터를 10개 수신 후 종료합니다.\n")
    asyncio.run(_test())

