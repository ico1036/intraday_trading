"""
Strategy 모듈 테스트

Order 생성, MarketState 처리, OBIStrategy 검증
"""

from datetime import datetime

import pytest

from intraday.strategy import (
    Side,
    OrderType,
    Order,
    MarketState,
    OBIStrategy,
)


class TestSideEnum:
    """Side enum 테스트"""
    
    def test_side_values(self):
        """Side enum 값 확인"""
        assert Side.BUY.value == "BUY"
        assert Side.SELL.value == "SELL"


class TestOrderTypeEnum:
    """OrderType enum 테스트"""
    
    def test_order_type_values(self):
        """OrderType enum 값 확인"""
        assert OrderType.MARKET.value == "MARKET"
        assert OrderType.LIMIT.value == "LIMIT"


class TestOrder:
    """Order 데이터클래스 테스트"""
    
    def test_market_order_creation(self):
        """MARKET 주문 생성 테스트"""
        order = Order(
            side=Side.BUY,
            quantity=0.01,
            order_type=OrderType.MARKET,
        )
        
        assert order.side == Side.BUY
        assert order.quantity == 0.01
        assert order.order_type == OrderType.MARKET
        assert order.limit_price is None
        assert order.stop_loss is None
        assert order.take_profit is None
    
    def test_limit_order_creation(self):
        """LIMIT 주문 생성 테스트"""
        order = Order(
            side=Side.SELL,
            quantity=0.05,
            order_type=OrderType.LIMIT,
            limit_price=100000.0,
            stop_loss=99000.0,
            take_profit=101000.0,
        )
        
        assert order.side == Side.SELL
        assert order.quantity == 0.05
        assert order.order_type == OrderType.LIMIT
        assert order.limit_price == 100000.0
        assert order.stop_loss == 99000.0
        assert order.take_profit == 101000.0
    
    def test_order_default_type_is_market(self):
        """기본 주문 타입은 MARKET"""
        order = Order(side=Side.BUY, quantity=0.01)
        assert order.order_type == OrderType.MARKET


class TestMarketState:
    """MarketState 데이터클래스 테스트"""
    
    def test_market_state_creation(self):
        """MarketState 생성 테스트"""
        now = datetime.now()
        state = MarketState(
            timestamp=now,
            mid_price=100000.0,
            imbalance=0.5,
            spread=10.0,
            spread_bps=1.0,
            best_bid=99995.0,
            best_ask=100005.0,
            best_bid_qty=1.5,
            best_ask_qty=0.5,
        )
        
        assert state.timestamp == now
        assert state.mid_price == 100000.0
        assert state.imbalance == 0.5
        assert state.spread == 10.0
        assert state.spread_bps == 1.0
        assert state.best_bid == 99995.0
        assert state.best_ask == 100005.0
        assert state.best_bid_qty == 1.5
        assert state.best_ask_qty == 0.5


class TestOBIStrategy:
    """OBIStrategy 테스트"""
    
    def test_default_initialization(self):
        """기본값으로 초기화"""
        strategy = OBIStrategy()
        
        assert strategy.buy_threshold == 0.3
        assert strategy.sell_threshold == -0.3
        assert strategy.quantity == 0.01
    
    def test_custom_initialization(self):
        """커스텀 값으로 초기화"""
        strategy = OBIStrategy(
            buy_threshold=0.5,
            sell_threshold=-0.5,
            quantity=0.1,
        )
        
        assert strategy.buy_threshold == 0.5
        assert strategy.sell_threshold == -0.5
        assert strategy.quantity == 0.1
    
    def test_generate_buy_order_when_imbalance_high(self):
        """imbalance > buy_threshold 일 때 BUY 주문 생성"""
        strategy = OBIStrategy(buy_threshold=0.3, sell_threshold=-0.3, quantity=0.01)
        
        state = MarketState(
            timestamp=datetime.now(),
            mid_price=100000.0,
            imbalance=0.5,  # > 0.3
            spread=10.0,
            spread_bps=1.0,
            best_bid=99995.0,
            best_ask=100005.0,
            best_bid_qty=1.5,
            best_ask_qty=0.5,
        )
        
        order = strategy.generate_order(state)
        
        assert order is not None
        assert order.side == Side.BUY
        assert order.quantity == 0.01
        assert order.order_type == OrderType.LIMIT
        assert order.limit_price == 100005.0  # best_ask (Taker: 즉시 체결)
    
    def test_generate_sell_order_when_imbalance_low(self):
        """imbalance < sell_threshold 일 때 SELL 주문 생성 (BUY 포지션 보유 시)"""
        strategy = OBIStrategy(buy_threshold=0.3, sell_threshold=-0.3, quantity=0.01)
        
        state = MarketState(
            timestamp=datetime.now(),
            mid_price=100000.0,
            imbalance=-0.5,  # < -0.3
            spread=10.0,
            spread_bps=1.0,
            best_bid=99995.0,
            best_ask=100005.0,
            best_bid_qty=0.5,
            best_ask_qty=1.5,
            position_side=Side.BUY,  # BUY 포지션 보유 시에만 SELL 가능
            position_qty=0.01,
        )
        
        order = strategy.generate_order(state)
        
        assert order is not None
        assert order.side == Side.SELL
        assert order.quantity == 0.01
        assert order.order_type == OrderType.LIMIT
        assert order.limit_price == 99995.0  # best_bid (Taker: 즉시 체결)
    
    def test_no_order_when_imbalance_neutral(self):
        """imbalance가 임계값 사이일 때 주문 없음"""
        strategy = OBIStrategy(buy_threshold=0.3, sell_threshold=-0.3, quantity=0.01)
        
        state = MarketState(
            timestamp=datetime.now(),
            mid_price=100000.0,
            imbalance=0.1,  # -0.3 < 0.1 < 0.3
            spread=10.0,
            spread_bps=1.0,
            best_bid=99995.0,
            best_ask=100005.0,
            best_bid_qty=1.0,
            best_ask_qty=1.0,
        )
        
        order = strategy.generate_order(state)
        
        assert order is None
    
    def test_buy_at_exact_threshold(self):
        """imbalance == buy_threshold 일 때 (경계값)"""
        strategy = OBIStrategy(buy_threshold=0.3, sell_threshold=-0.3, quantity=0.01)
        
        state = MarketState(
            timestamp=datetime.now(),
            mid_price=100000.0,
            imbalance=0.3,  # == 0.3 (경계)
            spread=10.0,
            spread_bps=1.0,
            best_bid=99995.0,
            best_ask=100005.0,
            best_bid_qty=1.0,
            best_ask_qty=1.0,
        )
        
        order = strategy.generate_order(state)
        
        # 경계값은 주문 없음 (> threshold 필요)
        assert order is None
    
    def test_sell_at_exact_threshold(self):
        """imbalance == sell_threshold 일 때 (경계값)"""
        strategy = OBIStrategy(buy_threshold=0.3, sell_threshold=-0.3, quantity=0.01)
        
        state = MarketState(
            timestamp=datetime.now(),
            mid_price=100000.0,
            imbalance=-0.3,  # == -0.3 (경계)
            spread=10.0,
            spread_bps=1.0,
            best_bid=99995.0,
            best_ask=100005.0,
            best_bid_qty=1.0,
            best_ask_qty=1.0,
        )
        
        order = strategy.generate_order(state)
        
        # 경계값은 주문 없음 (< threshold 필요)
        assert order is None

