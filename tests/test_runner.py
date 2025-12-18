"""
ForwardRunner 테스트

실제 시나리오 기반 테스트 - "이럴땐 이래야 맞다!" 원칙 검증
"""

from datetime import datetime

import pytest

from intraday.strategy import Side, OrderType, Order, MarketState, OBIStrategy
from intraday.runner import ForwardRunner
from intraday.client import OrderbookSnapshot, AggTrade


class TestForwardRunnerInit:
    """ForwardRunner 초기화 테스트"""
    
    def test_default_initialization(self):
        """기본값으로 초기화"""
        strategy = OBIStrategy()
        runner = ForwardRunner(strategy)
        
        assert runner.symbol == "btcusdt"
        assert runner.initial_capital == 10000.0
        assert runner.fee_rate == 0.001
        assert runner.is_running is False
    
    def test_custom_initialization(self):
        """커스텀 값으로 초기화"""
        strategy = OBIStrategy()
        runner = ForwardRunner(
            strategy=strategy,
            symbol="ethusdt",
            initial_capital=5000.0,
            fee_rate=0.0005,
        )
        
        assert runner.symbol == "ethusdt"
        assert runner.initial_capital == 5000.0
        assert runner.fee_rate == 0.0005


class TestForwardRunnerOrderbookProcessing:
    """Orderbook 처리 테스트"""
    
    def test_orderbook_creates_market_state(self):
        """Orderbook 수신 시 MarketState 생성"""
        strategy = OBIStrategy()
        runner = ForwardRunner(strategy)
        
        snapshot = OrderbookSnapshot(
            timestamp=datetime.now(),
            last_update_id=123,
            bids=[(100000.0, 1.0), (99900.0, 2.0)],
            asks=[(100100.0, 0.5), (100200.0, 1.5)],
            symbol="BTCUSDT",
        )
        
        runner._on_orderbook(snapshot)
        
        assert runner.market_state is not None
        assert runner.market_state.mid_price == 100050.0  # (100000 + 100100) / 2
        assert runner.market_state.best_bid == 100000.0
        assert runner.market_state.best_ask == 100100.0
    
    def test_orderbook_triggers_strategy(self):
        """Orderbook 수신 시 전략 실행"""
        strategy = OBIStrategy(buy_threshold=0.3, quantity=0.01)
        runner = ForwardRunner(strategy)
        
        # 강한 매수 신호 (imbalance > 0.3)
        snapshot = OrderbookSnapshot(
            timestamp=datetime.now(),
            last_update_id=123,
            bids=[(100000.0, 2.0)],  # 많은 매수 물량
            asks=[(100100.0, 0.5)],  # 적은 매도 물량
            symbol="BTCUSDT",
        )
        
        runner._on_orderbook(snapshot)
        
        # 주문이 제출되었는지 확인
        assert runner._order_count == 1


class TestForwardRunnerTradeProcessing:
    """체결 데이터 처리 테스트"""
    
    def test_trade_updates_paper_trader(self):
        """체결 데이터 수신 시 PaperTrader 업데이트"""
        strategy = OBIStrategy()
        runner = ForwardRunner(strategy)
        
        # 먼저 Orderbook 수신
        snapshot = OrderbookSnapshot(
            timestamp=datetime.now(),
            last_update_id=123,
            bids=[(100000.0, 1.0)],
            asks=[(100100.0, 1.0)],
            symbol="BTCUSDT",
        )
        runner._on_orderbook(snapshot)
        
        # 체결 데이터 수신
        trade = AggTrade(
            timestamp=datetime.now(),
            symbol="BTCUSDT",
            price=100050.0,
            quantity=0.1,
            is_buyer_maker=False,
        )
        
        runner._on_trade(trade)
        
        assert runner._trade_count == 1


class TestForwardRunnerPerformanceReport:
    """성과 리포트 테스트"""
    
    def test_get_performance_report_empty(self):
        """거래 없이 성과 리포트"""
        strategy = OBIStrategy()
        runner = ForwardRunner(strategy)
        
        report = runner.get_performance_report()
        
        assert report.strategy_name == "OBIStrategy"
        assert report.total_trades == 0
        assert report.total_return == 0.0
    
    def test_get_performance_report_with_trades(self):
        """
        시나리오: 완전한 거래 사이클 성과 측정
        
        유저 입장: "매수 → 체결 → 매도 → 체결 → 성과 리포트가 정확해야지!"
        """
        strategy = OBIStrategy(buy_threshold=0.3, sell_threshold=-0.3, quantity=0.01)
        runner = ForwardRunner(strategy, initial_capital=10000.0)
        
        # 1. 강한 매수 신호 → LIMIT BUY 주문 생성
        snapshot1 = OrderbookSnapshot(
            timestamp=datetime.now(),
            last_update_id=1,
            bids=[(100000.0, 2.0)],  # imbalance = (2.0 - 0.5) / (2.0 + 0.5) = 0.6 > 0.3
            asks=[(100100.0, 0.5)],
            symbol="BTCUSDT",
        )
        runner._on_orderbook(snapshot1)
        
        # 주문이 제출되었는지 확인
        assert runner._order_count == 1
        assert len(runner._trader.pending_orders) == 1
        
        # 2. LIMIT 주문 체결 (가격이 limit_price 이하로 떨어짐)
        trade1 = AggTrade(
            timestamp=datetime.now(),
            symbol="BTCUSDT",
            price=99995.0,  # limit_price(100000) 이하
            quantity=0.1,
            is_buyer_maker=False,
        )
        runner._on_trade(trade1)
        
        # 포지션 확인
        assert runner._trader.position.side == Side.BUY
        assert runner._trader.position.quantity == 0.01
        
        # 3. 강한 매도 신호 → LIMIT SELL 주문 생성
        snapshot2 = OrderbookSnapshot(
            timestamp=datetime.now(),
            last_update_id=2,
            bids=[(100000.0, 0.5)],  # imbalance = (0.5 - 2.0) / (0.5 + 2.0) = -0.6 < -0.3
            asks=[(100100.0, 2.0)],
            symbol="BTCUSDT",
        )
        runner._on_orderbook(snapshot2)
        
        assert runner._order_count == 2
        
        # 4. LIMIT SELL 주문 체결 (가격이 limit_price 이상으로 올라감)
        trade2 = AggTrade(
            timestamp=datetime.now(),
            symbol="BTCUSDT",
            price=100105.0,  # limit_price(100100) 이상
            quantity=0.1,
            is_buyer_maker=False,
        )
        runner._on_trade(trade2)
        
        # 포지션 청산 확인
        assert runner._trader.position.side is None
        
        # 5. 성과 리포트 확인
        report = runner.get_performance_report()
        
        assert report.strategy_name == "OBIStrategy"
        assert report.total_trades == 2  # 진입 + 청산
        assert report.initial_capital == 10000.0
        
        # 수익 확인: (100105 - 99995) * 0.01 = 1.1 (수수료 제외)
        # 수수료: 99995 * 0.01 * 0.001 + 100105 * 0.01 * 0.001 ≈ 2.0
        # 순 수익: 약 -0.9 (손실)
        assert report.total_return < 0.1  # 수수료로 인해 소폭 손실 가능


class TestForwardRunnerMarketStateThin:
    """MarketState가 OrderbookState의 thin wrapper인지 확인"""
    
    def test_market_state_contains_all_orderbook_info(self):
        """MarketState가 필요한 모든 정보를 포함"""
        strategy = OBIStrategy()
        runner = ForwardRunner(strategy)
        
        snapshot = OrderbookSnapshot(
            timestamp=datetime.now(),
            last_update_id=123,
            bids=[(100000.0, 1.5), (99900.0, 2.0)],
            asks=[(100100.0, 0.8), (100200.0, 1.2)],
            symbol="BTCUSDT",
        )
        
        runner._on_orderbook(snapshot)
        
        state = runner.market_state
        
        # 모든 필드 확인
        assert state.mid_price == (100000.0 + 100100.0) / 2
        assert state.best_bid == 100000.0
        assert state.best_ask == 100100.0
        assert state.best_bid_qty == 1.5
        assert state.best_ask_qty == 0.8
        assert state.spread == 100.0
        # imbalance = (1.5 - 0.8) / (1.5 + 0.8) = 0.7 / 2.3 ≈ 0.304
        assert abs(state.imbalance - 0.304) < 0.01

