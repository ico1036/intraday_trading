"""
BinanceWebSocketClient 통합 테스트

실제 Binance WebSocket에 연결하여 테스트합니다.
네트워크가 필요하므로 기본 테스트에서는 제외됩니다.

실행 방법:
    uv run pytest tests/test_client_integration.py -v
"""

import asyncio

import pytest

from intraday.client import BinanceWebSocketClient, OrderbookSnapshot


# 통합 테스트 마커
pytestmark = pytest.mark.integration


class TestRealConnection:
    """실제 Binance WebSocket 연결 테스트"""
    
    @pytest.mark.asyncio
    async def test_receive_real_orderbook(self):
        """실제 BTC/USDT Orderbook 데이터 수신 테스트"""
        client = BinanceWebSocketClient("btcusdt", depth_levels=5, update_speed="100ms")
        received = []
        
        def on_orderbook(snapshot: OrderbookSnapshot):
            received.append(snapshot)
            # 5개 메시지 수신 후 종료
            if len(received) >= 5:
                client._running = False
        
        # 5초 타임아웃
        try:
            await asyncio.wait_for(
                client.connect(on_orderbook, max_reconnect_attempts=1),
                timeout=5.0
            )
        except asyncio.TimeoutError:
            client._running = False
        
        # 검증
        assert len(received) >= 1, "최소 1개 메시지 수신"
        
        snapshot = received[0]
        assert snapshot.symbol == "BTCUSDT"
        assert len(snapshot.bids) > 0, "Bids가 있어야 함"
        assert len(snapshot.asks) > 0, "Asks가 있어야 함"
        
        # Best bid/ask 가격 검증 (BTC 가격은 $10,000 이상)
        best_bid_price = snapshot.bids[0][0]
        best_ask_price = snapshot.asks[0][0]
        
        assert best_bid_price > 10000, f"Best bid: {best_bid_price}"
        assert best_ask_price > 10000, f"Best ask: {best_ask_price}"
        assert best_ask_price > best_bid_price, "Ask > Bid"
        
        print(f"\n✅ 수신한 메시지: {len(received)}개")
        print(f"   Best Bid: ${best_bid_price:,.2f}")
        print(f"   Best Ask: ${best_ask_price:,.2f}")
        print(f"   Spread: ${best_ask_price - best_bid_price:.2f}")
    
    @pytest.mark.asyncio
    async def test_receive_eth_orderbook(self):
        """실제 ETH/USDT Orderbook 데이터 수신 테스트"""
        client = BinanceWebSocketClient("ethusdt", depth_levels=5, update_speed="100ms")
        received = []
        
        def on_orderbook(snapshot: OrderbookSnapshot):
            received.append(snapshot)
            if len(received) >= 3:
                client._running = False
        
        try:
            await asyncio.wait_for(
                client.connect(on_orderbook, max_reconnect_attempts=1),
                timeout=5.0
            )
        except asyncio.TimeoutError:
            client._running = False
        
        assert len(received) >= 1
        assert received[0].symbol == "ETHUSDT"
        
        print(f"\n✅ ETH/USDT 수신: {len(received)}개 메시지")
    
    @pytest.mark.asyncio
    async def test_async_callback(self):
        """비동기 콜백으로 실제 데이터 수신"""
        client = BinanceWebSocketClient("btcusdt", depth_levels=5, update_speed="100ms")
        received = []
        
        async def on_orderbook(snapshot: OrderbookSnapshot):
            received.append(snapshot)
            # 비동기 처리 시뮬레이션
            await asyncio.sleep(0.01)
            if len(received) >= 3:
                client._running = False
        
        try:
            await asyncio.wait_for(
                client.connect(on_orderbook, max_reconnect_attempts=1),
                timeout=5.0
            )
        except asyncio.TimeoutError:
            client._running = False
        
        assert len(received) >= 1
        print(f"\n✅ 비동기 콜백 수신: {len(received)}개 메시지")
    
    @pytest.mark.asyncio
    async def test_disconnect(self):
        """연결 후 정상 종료 테스트"""
        client = BinanceWebSocketClient("btcusdt", depth_levels=5, update_speed="100ms")
        received = []
        
        async def on_orderbook(snapshot: OrderbookSnapshot):
            received.append(snapshot)
            if len(received) >= 2:
                # _running = False로 종료
                client._running = False
        
        try:
            await asyncio.wait_for(
                client.connect(on_orderbook, max_reconnect_attempts=1),
                timeout=5.0
            )
        except asyncio.TimeoutError:
            pass
        
        assert not client._running
        assert len(received) >= 2
        print(f"\n✅ 정상 종료 확인, {len(received)}개 메시지 수신")

