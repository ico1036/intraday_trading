"""
BinanceWebSocketClient 기본 테스트

초기화, 속성, 파싱 등 단순한 동기 테스트
"""

from datetime import datetime

import pytest

from intraday.client import BinanceWebSocketClient, OrderbookSnapshot


class TestOrderbookSnapshot:
    """OrderbookSnapshot 데이터클래스 테스트"""
    
    def test_creation(self):
        """OrderbookSnapshot 생성 테스트"""
        snapshot = OrderbookSnapshot(
            timestamp=datetime.now(),
            last_update_id=123,
            bids=[(100.0, 1.5), (99.0, 2.0)],
            asks=[(101.0, 1.0), (102.0, 3.0)],
            symbol="BTCUSDT"
        )
        
        assert snapshot.last_update_id == 123
        assert len(snapshot.bids) == 2
        assert len(snapshot.asks) == 2
        assert snapshot.symbol == "BTCUSDT"


class TestBinanceWebSocketClientInit:
    """BinanceWebSocketClient 초기화 테스트"""
    
    def test_default(self):
        """기본값으로 초기화 테스트"""
        client = BinanceWebSocketClient()
        
        assert client.symbol == "btcusdt"
        assert client.depth_levels == 20
        assert client.update_speed == "100ms"
        assert client._ws is None
        assert client._running is False
    
    def test_custom(self):
        """커스텀 값으로 초기화 테스트"""
        client = BinanceWebSocketClient(
            symbol="ETHUSDT",
            depth_levels=10,
            update_speed="1000ms"
        )
        
        assert client.symbol == "ethusdt"  # 소문자 변환 확인
        assert client.depth_levels == 10
        assert client.update_speed == "1000ms"


class TestBinanceWebSocketClientProperties:
    """BinanceWebSocketClient 속성 테스트"""
    
    def test_stream_name(self):
        """stream_name property 테스트"""
        client = BinanceWebSocketClient("btcusdt", depth_levels=20, update_speed="100ms")
        assert client.stream_name == "btcusdt@depth20@100ms"
        
        client2 = BinanceWebSocketClient("ethusdt", depth_levels=5, update_speed="1000ms")
        assert client2.stream_name == "ethusdt@depth5@1000ms"
    
    def test_ws_url(self):
        """ws_url property 테스트"""
        client = BinanceWebSocketClient("btcusdt")
        expected = "wss://stream.binance.com:9443/ws/btcusdt@depth20@100ms"
        assert client.ws_url == expected


class TestBinanceWebSocketClientParsing:
    """BinanceWebSocketClient 파싱 테스트"""
    
    def test_parse_orderbook_normal(self):
        """정상적인 Orderbook 데이터 파싱 테스트"""
        client = BinanceWebSocketClient("btcusdt")
        
        data = {
            "lastUpdateId": 12345,
            "bids": [["100000.00", "1.5"], ["99900.00", "2.0"]],
            "asks": [["101000.00", "1.0"], ["102000.00", "3.0"]]
        }
        
        snapshot = client._parse_orderbook(data)
        
        assert snapshot.last_update_id == 12345
        assert snapshot.bids == [(100000.0, 1.5), (99900.0, 2.0)]
        assert snapshot.asks == [(101000.0, 1.0), (102000.0, 3.0)]
        assert snapshot.symbol == "BTCUSDT"
        assert isinstance(snapshot.timestamp, datetime)
    
    def test_parse_orderbook_empty(self):
        """빈 Orderbook 데이터 파싱 테스트"""
        client = BinanceWebSocketClient("btcusdt")
        
        data = {
            "lastUpdateId": 0,
            "bids": [],
            "asks": []
        }
        
        snapshot = client._parse_orderbook(data)
        
        assert snapshot.last_update_id == 0
        assert snapshot.bids == []
        assert snapshot.asks == []
    
    def test_parse_orderbook_missing_fields(self):
        """필드가 없는 경우 기본값 테스트"""
        client = BinanceWebSocketClient("btcusdt")
        
        data = {}
        
        snapshot = client._parse_orderbook(data)
        
        assert snapshot.last_update_id == 0
        assert snapshot.bids == []
        assert snapshot.asks == []

