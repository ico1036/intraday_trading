"""
WebSocket 클라이언트 자동 재연결 테스트

websockets 표준 패턴(async for ws in connect())을 사용한 무한 재연결 동작을 검증합니다.
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from typing import AsyncIterator

import pytest
from websockets.exceptions import (
    ConnectionClosed,
    ConnectionClosedOK,
    ConnectionClosedError,
    InvalidHandshake,
    InvalidURI,
)

from intraday.client import (
    BinanceWebSocketClient,
    BinanceCombinedClient,
    OrderbookSnapshot,
    AggTrade,
)


def create_mock_websocket(messages: list[str], exception_at_end=None):
    """메시지 목록을 반환하는 mock WebSocket 생성"""
    mock_ws = MagicMock()
    mock_ws.close = AsyncMock()

    async def message_iterator():
        for msg in messages:
            yield msg
        if exception_at_end:
            raise exception_at_end

    mock_ws.__aiter__ = lambda self: message_iterator()
    return mock_ws


class MockConnectIterator:
    """async for ws in connect(uri) 패턴을 모방하는 이터레이터"""

    def __init__(self, websockets_sequence: list):
        """
        Args:
            websockets_sequence: list of (messages, exception_at_end) tuples
        """
        self.websockets_sequence = websockets_sequence
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.index >= len(self.websockets_sequence):
            raise StopAsyncIteration

        messages, exception = self.websockets_sequence[self.index]
        self.index += 1
        return create_mock_websocket(messages, exception)


class TestBinanceWebSocketClientReconnect:
    """BinanceWebSocketClient 자동 재연결 테스트"""

    @pytest.mark.asyncio
    async def test_reconnects_on_connection_closed_ok(self):
        """정상 종료(ConnectionClosedOK) 시 자동 재연결"""
        client = BinanceWebSocketClient("btcusdt")
        received_snapshots = []

        # 3번 연결: 첫 2번은 ConnectionClosedOK, 3번째는 정상 종료
        websockets_seq = [
            (['{"lastUpdateId": 1, "bids": [], "asks": []}'], ConnectionClosedOK(None, None)),
            (['{"lastUpdateId": 2, "bids": [], "asks": []}'], ConnectionClosedOK(None, None)),
            (['{"lastUpdateId": 3, "bids": [], "asks": []}'], None),  # 마지막: 정상
        ]

        def on_orderbook(snapshot: OrderbookSnapshot):
            received_snapshots.append(snapshot)
            if len(received_snapshots) >= 3:
                client._running = False

        def mock_connect(uri):
            return MockConnectIterator(websockets_seq)

        with patch("intraday.client.connect", mock_connect):
            await client.connect(on_orderbook)

        assert len(received_snapshots) == 3, "Should receive all 3 messages across reconnections"

    @pytest.mark.asyncio
    async def test_reconnects_on_connection_closed_error(self):
        """비정상 종료(ConnectionClosedError) 시 자동 재연결"""
        client = BinanceWebSocketClient("btcusdt")
        received_snapshots = []

        websockets_seq = [
            (['{"lastUpdateId": 1, "bids": [], "asks": []}'], ConnectionClosedError(None, None)),
            (['{"lastUpdateId": 2, "bids": [], "asks": []}'], None),
        ]

        def on_orderbook(snapshot: OrderbookSnapshot):
            received_snapshots.append(snapshot)
            if len(received_snapshots) >= 2:
                client._running = False

        def mock_connect(uri):
            return MockConnectIterator(websockets_seq)

        with patch("intraday.client.connect", mock_connect):
            await client.connect(on_orderbook)

        assert len(received_snapshots) == 2

    @pytest.mark.asyncio
    async def test_stops_on_rate_limit_429(self):
        """Rate Limit (429) 시 즉시 중단"""
        client = BinanceWebSocketClient("btcusdt")
        error_received = []

        # 429 에러로 시작
        websockets_seq = [
            ([], InvalidHandshake("server rejected WebSocket connection: HTTP 429")),
        ]

        def on_orderbook(snapshot):
            pass

        def on_error(e):
            error_received.append(e)

        def mock_connect(uri):
            return MockConnectIterator(websockets_seq)

        with patch("intraday.client.connect", mock_connect):
            await client.connect(on_orderbook, on_error)

        assert client._running is False, "Should stop running on 429"
        assert len(error_received) == 1

    @pytest.mark.asyncio
    async def test_stops_on_invalid_uri(self):
        """잘못된 URI 시 즉시 중단 (재연결 의미 없음)"""
        client = BinanceWebSocketClient("btcusdt")
        error_received = []

        websockets_seq = [
            ([], InvalidURI("ws://invalid", "Invalid URI")),
        ]

        def on_orderbook(snapshot):
            pass

        def on_error(e):
            error_received.append(e)

        def mock_connect(uri):
            return MockConnectIterator(websockets_seq)

        with patch("intraday.client.connect", mock_connect):
            await client.connect(on_orderbook, on_error)

        assert client._running is False, "Should stop running on invalid URI"

    @pytest.mark.asyncio
    async def test_reconnects_on_network_error(self):
        """네트워크 에러(OSError) 시 자동 재연결"""
        client = BinanceWebSocketClient("btcusdt")
        received_snapshots = []

        websockets_seq = [
            ([], OSError("Network unreachable")),
            (['{"lastUpdateId": 1, "bids": [], "asks": []}'], None),
        ]

        def on_orderbook(snapshot: OrderbookSnapshot):
            received_snapshots.append(snapshot)
            client._running = False

        def mock_connect(uri):
            return MockConnectIterator(websockets_seq)

        with patch("intraday.client.connect", mock_connect):
            await client.connect(on_orderbook)

        assert len(received_snapshots) == 1, "Should receive message after network recovery"

    @pytest.mark.asyncio
    async def test_disconnect_stops_reconnection(self):
        """disconnect() 호출 시 재연결 중단"""
        client = BinanceWebSocketClient("btcusdt")

        # 많은 메시지가 있지만 중간에 disconnect
        messages = [f'{{"lastUpdateId": {i}, "bids": [], "asks": []}}' for i in range(10)]
        websockets_seq = [
            (messages, None),
        ]

        message_count = 0

        def on_orderbook(snapshot):
            nonlocal message_count
            message_count += 1
            if message_count >= 3:
                client._running = False  # disconnect 시뮬레이션

        def mock_connect(uri):
            return MockConnectIterator(websockets_seq)

        with patch("intraday.client.connect", mock_connect):
            await client.connect(on_orderbook)

        assert client._running is False
        assert message_count == 3  # 3번째에서 중단


class TestBinanceCombinedClientReconnect:
    """BinanceCombinedClient 자동 재연결 테스트"""

    @pytest.mark.asyncio
    async def test_reconnects_on_connection_closed(self):
        """연결 종료 시 자동 재연결"""
        client = BinanceCombinedClient("btcusdt")
        received_orderbooks = []

        websockets_seq = [
            (['{"stream": "btcusdt@depth20@100ms", "data": {"lastUpdateId": 1, "bids": [], "asks": []}}'],
             ConnectionClosedOK(None, None)),
            (['{"stream": "btcusdt@depth20@100ms", "data": {"lastUpdateId": 2, "bids": [], "asks": []}}'],
             None),
        ]

        def on_orderbook(snapshot):
            received_orderbooks.append(snapshot)
            if len(received_orderbooks) >= 2:
                client._running = False

        def on_trade(trade):
            pass

        def mock_connect(uri):
            return MockConnectIterator(websockets_seq)

        with patch("intraday.client.connect", mock_connect):
            await client.connect(on_orderbook, on_trade)

        assert len(received_orderbooks) == 2

    @pytest.mark.asyncio
    async def test_handles_both_orderbook_and_trade_streams(self):
        """Orderbook과 Trade 스트림 모두 처리"""
        client = BinanceCombinedClient("btcusdt")
        orderbooks = []
        trades = []

        messages = [
            '{"stream": "btcusdt@depth20@100ms", "data": {"lastUpdateId": 1, "bids": [["100", "1"]], "asks": [["101", "1"]]}}',
            '{"stream": "btcusdt@aggTrade", "data": {"T": 1609459200000, "s": "BTCUSDT", "p": "100.5", "q": "0.5", "m": false}}',
        ]
        websockets_seq = [(messages, None)]

        def on_orderbook(snapshot: OrderbookSnapshot):
            orderbooks.append(snapshot)
            if len(orderbooks) >= 1 and len(trades) >= 1:
                client._running = False

        def on_trade(trade: AggTrade):
            trades.append(trade)
            if len(orderbooks) >= 1 and len(trades) >= 1:
                client._running = False

        def mock_connect(uri):
            return MockConnectIterator(websockets_seq)

        with patch("intraday.client.connect", mock_connect):
            await client.connect(on_orderbook, on_trade)

        assert len(orderbooks) == 1
        assert len(trades) == 1
        assert orderbooks[0].bids[0][0] == 100.0
        assert trades[0].price == 100.5

    @pytest.mark.asyncio
    async def test_stops_on_rate_limit_429(self):
        """Rate Limit (429) 시 즉시 중단"""
        client = BinanceCombinedClient("btcusdt")
        error_received = []

        websockets_seq = [
            ([], InvalidHandshake("server rejected WebSocket connection: HTTP 429")),
        ]

        def on_orderbook(snapshot):
            pass

        def on_trade(trade):
            pass

        def on_error(e):
            error_received.append(e)

        def mock_connect(uri):
            return MockConnectIterator(websockets_seq)

        with patch("intraday.client.connect", mock_connect):
            await client.connect(on_orderbook, on_trade, on_error)

        assert client._running is False
        assert len(error_received) == 1


class TestReconnectionForLongRunningSession:
    """장시간 실행 세션에서의 재연결 테스트 (BB Squeeze 워밍업 시뮬레이션)"""

    @pytest.mark.asyncio
    async def test_survives_multiple_disconnections(self):
        """다수의 연결 끊김에서 생존 (웜업 기간 시뮬레이션)"""
        client = BinanceCombinedClient("btcusdt")
        total_messages = 0

        # 5번 연결, 각각 3개 메시지
        websockets_seq = []
        for i in range(5):
            messages = [
                f'{{"stream": "btcusdt@depth20@100ms", "data": {{"lastUpdateId": {i*3+j}, "bids": [], "asks": []}}}}'
                for j in range(3)
            ]
            if i < 4:
                websockets_seq.append((messages, ConnectionClosedError(None, None)))
            else:
                websockets_seq.append((messages, None))

        def on_orderbook(snapshot):
            nonlocal total_messages
            total_messages += 1
            if total_messages >= 15:
                client._running = False

        def on_trade(trade):
            pass

        def mock_connect(uri):
            return MockConnectIterator(websockets_seq)

        with patch("intraday.client.connect", mock_connect):
            await client.connect(on_orderbook, on_trade)

        assert total_messages == 15, "Should have received 15 messages across 5 connections"

    @pytest.mark.asyncio
    async def test_handles_json_parse_error_without_disconnecting(self):
        """JSON 파싱 에러는 연결 유지하고 계속 진행"""
        client = BinanceCombinedClient("btcusdt")
        json_errors = []
        valid_messages = []

        messages = [
            "invalid json {",
            '{"stream": "btcusdt@depth20@100ms", "data": {"lastUpdateId": 1, "bids": [], "asks": []}}',
            "another invalid",
            '{"stream": "btcusdt@depth20@100ms", "data": {"lastUpdateId": 2, "bids": [], "asks": []}}',
        ]
        websockets_seq = [(messages, None)]

        def on_orderbook(snapshot):
            valid_messages.append(snapshot)
            if len(valid_messages) >= 2:
                client._running = False

        def on_trade(trade):
            pass

        def on_error(e):
            json_errors.append(e)

        def mock_connect(uri):
            return MockConnectIterator(websockets_seq)

        with patch("intraday.client.connect", mock_connect):
            await client.connect(on_orderbook, on_trade, on_error)

        assert len(json_errors) == 2, "Should have logged 2 JSON errors"
        assert len(valid_messages) == 2, "Should have processed 2 valid messages"

    @pytest.mark.asyncio
    async def test_reconnects_continuously_without_limit(self):
        """재연결 횟수 제한 없이 무한 재연결 (100회 시뮬레이션)"""
        client = BinanceCombinedClient("btcusdt")
        reconnection_count = 0
        max_reconnections = 10  # 테스트 시간을 위해 10회로 제한

        websockets_seq = []
        for i in range(max_reconnections):
            messages = [f'{{"stream": "btcusdt@depth20@100ms", "data": {{"lastUpdateId": {i}, "bids": [], "asks": []}}}}']
            if i < max_reconnections - 1:
                websockets_seq.append((messages, ConnectionClosedError(None, None)))
            else:
                websockets_seq.append((messages, None))

        def on_orderbook(snapshot):
            nonlocal reconnection_count
            reconnection_count += 1
            if reconnection_count >= max_reconnections:
                client._running = False

        def on_trade(trade):
            pass

        def mock_connect(uri):
            return MockConnectIterator(websockets_seq)

        with patch("intraday.client.connect", mock_connect):
            await client.connect(on_orderbook, on_trade)

        assert reconnection_count == max_reconnections, f"Should have survived {max_reconnections} reconnections"


class TestRealBinanceIntegration:
    """실제 Binance WebSocket 연결 테스트 (네트워크 필요)"""

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        True,  # 실제 네트워크 테스트는 기본적으로 스킵
        reason="Integration test - run manually with --run-integration"
    )
    async def test_connects_and_receives_data(self):
        """실제 Binance에 연결하여 데이터 수신"""
        from intraday.client import BinanceCombinedClient

        client = BinanceCombinedClient("btcusdt")
        orderbooks = []
        trades = []

        def on_orderbook(snapshot):
            orderbooks.append(snapshot)
            if len(orderbooks) >= 5:
                asyncio.create_task(client.disconnect())

        def on_trade(trade):
            trades.append(trade)

        # 5초 타임아웃
        try:
            await asyncio.wait_for(
                client.connect(on_orderbook, on_trade),
                timeout=5.0
            )
        except asyncio.TimeoutError:
            await client.disconnect()

        assert len(orderbooks) >= 1, "Should have received orderbook data"
        # trades는 활동이 없으면 0일 수 있음

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        True,
        reason="Integration test - run manually with --run-integration"
    )
    async def test_reconnects_after_simulated_disconnect(self):
        """연결 끊김 후 실제 재연결 테스트"""
        from intraday.client import BinanceCombinedClient

        client = BinanceCombinedClient("btcusdt")
        orderbooks = []
        reconnect_triggered = False

        async def on_orderbook(snapshot):
            nonlocal reconnect_triggered
            orderbooks.append(snapshot)

            # 3개 받은 후 강제로 WebSocket 닫기 (재연결 트리거)
            if len(orderbooks) == 3 and not reconnect_triggered:
                reconnect_triggered = True
                if client._ws:
                    await client._ws.close()

            # 6개 받으면 종료 (재연결 성공 확인)
            if len(orderbooks) >= 6:
                await client.disconnect()

        def on_trade(trade):
            pass

        try:
            await asyncio.wait_for(
                client.connect(on_orderbook, on_trade),
                timeout=10.0
            )
        except asyncio.TimeoutError:
            await client.disconnect()

        assert len(orderbooks) >= 6, "Should have received data before and after reconnect"
