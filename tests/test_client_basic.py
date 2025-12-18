"""
BinanceWebSocketClient 기본 테스트

초기화, 속성, 파싱 등 단순한 동기 테스트
"""

from datetime import datetime

import pytest

from intraday.client import (
    BinanceWebSocketClient,
    OrderbookSnapshot,
    AggTrade,
    BinanceCombinedClient,
)


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


class TestAggTrade:
    """AggTrade 데이터클래스 테스트"""
    
    def test_creation(self):
        """AggTrade 생성 테스트"""
        now = datetime.now()
        trade = AggTrade(
            timestamp=now,
            symbol="BTCUSDT",
            price=100000.0,
            quantity=0.5,
            is_buyer_maker=True,
        )
        
        assert trade.timestamp == now
        assert trade.symbol == "BTCUSDT"
        assert trade.price == 100000.0
        assert trade.quantity == 0.5
        assert trade.is_buyer_maker is True
    
    def test_buyer_maker_meanings(self):
        """is_buyer_maker 필드 의미 테스트"""
        # is_buyer_maker=True: 매수자가 메이커 = 매도 주도 거래
        seller_driven = AggTrade(
            timestamp=datetime.now(),
            symbol="BTCUSDT",
            price=100000.0,
            quantity=0.5,
            is_buyer_maker=True,
        )
        assert seller_driven.is_buyer_maker is True  # 매도 주도
        
        # is_buyer_maker=False: 매도자가 메이커 = 매수 주도 거래
        buyer_driven = AggTrade(
            timestamp=datetime.now(),
            symbol="BTCUSDT",
            price=100000.0,
            quantity=0.5,
            is_buyer_maker=False,
        )
        assert buyer_driven.is_buyer_maker is False  # 매수 주도


class TestBinanceCombinedClientInit:
    """BinanceCombinedClient 초기화 테스트"""
    
    def test_default_initialization(self):
        """기본값으로 초기화"""
        client = BinanceCombinedClient()
        
        assert client.symbol == "btcusdt"
        assert client.depth_levels == 20
        assert client.update_speed == "100ms"
        assert client._running is False
    
    def test_custom_initialization(self):
        """커스텀 값으로 초기화"""
        client = BinanceCombinedClient(
            symbol="ETHUSDT",
            depth_levels=10,
            update_speed="1000ms",
        )
        
        assert client.symbol == "ethusdt"
        assert client.depth_levels == 10
        assert client.update_speed == "1000ms"


class TestBinanceCombinedClientProperties:
    """BinanceCombinedClient 속성 테스트"""
    
    def test_combined_stream_url(self):
        """Combined stream URL 테스트"""
        client = BinanceCombinedClient("btcusdt", depth_levels=20, update_speed="100ms")
        
        # Combined stream URL 형식
        expected = "wss://stream.binance.com:9443/stream?streams=btcusdt@depth20@100ms/btcusdt@aggTrade"
        assert client.ws_url == expected
    
    def test_stream_names(self):
        """스트림 이름 테스트"""
        client = BinanceCombinedClient("ethusdt", depth_levels=5, update_speed="1000ms")
        
        assert client.orderbook_stream == "ethusdt@depth5@1000ms"
        assert client.aggtrade_stream == "ethusdt@aggTrade"


class TestBinanceCombinedClientParsing:
    """BinanceCombinedClient 파싱 테스트"""
    
    def test_parse_aggtrade(self):
        """AggTrade 데이터 파싱 테스트"""
        client = BinanceCombinedClient("btcusdt")
        
        # Binance aggTrade 메시지 형식
        data = {
            "e": "aggTrade",        # 이벤트 타입
            "E": 1672531200000,      # 이벤트 시간
            "s": "BTCUSDT",          # 심볼
            "a": 12345,              # Aggregate trade ID
            "p": "100000.00",        # 가격
            "q": "0.5",              # 수량
            "f": 100,                # First trade ID
            "l": 105,                # Last trade ID
            "T": 1672531200000,      # 거래 시간
            "m": True,               # is buyer maker
            "M": True,               # ignore
        }
        
        trade = client._parse_aggtrade(data)
        
        assert trade.symbol == "BTCUSDT"
        assert trade.price == 100000.0
        assert trade.quantity == 0.5
        assert trade.is_buyer_maker is True
        assert isinstance(trade.timestamp, datetime)
    
    def test_parse_aggtrade_buyer_driven(self):
        """매수 주도 거래 파싱 테스트"""
        client = BinanceCombinedClient("btcusdt")
        
        data = {
            "e": "aggTrade",
            "E": 1672531200000,
            "s": "BTCUSDT",
            "a": 12346,
            "p": "100100.00",
            "q": "1.0",
            "f": 106,
            "l": 110,
            "T": 1672531200000,
            "m": False,  # 매수 주도
            "M": True,
        }
        
        trade = client._parse_aggtrade(data)
        
        assert trade.is_buyer_maker is False  # 매수 주도



