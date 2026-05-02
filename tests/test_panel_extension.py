"""
패널 데이터 확장 테스트

TDD: MarketState, StrategyBase, PaperTrader를 포트폴리오 지원으로 확장
하위 호환성 유지 필수
"""

import pytest
from datetime import datetime
from dataclasses import dataclass

from intraday.strategy import MarketState, Order, Side, OrderType


# ============================================================
# Phase 1: MarketState 패널 확장
# ============================================================

class TestMarketStatePanelExtension:
    """MarketState에 패널 데이터 추가 - 하위 호환"""
    
    def test_existing_marketstate_unchanged(self):
        """기존 MarketState 사용법이 깨지지 않음"""
        state = MarketState(
            timestamp=datetime.now(),
            mid_price=50000,
            imbalance=0.5,
            spread=1.0,
            spread_bps=0.02,
            best_bid=49999.5,
            best_ask=50000.5,
            best_bid_qty=10,
            best_ask_qty=8,
        )
        
        assert state.mid_price == 50000
        assert state.imbalance == 0.5
        assert state.position_side is None
    
    def test_panel_field_defaults_to_none(self):
        """panel 필드가 없어도 기존 코드 작동"""
        state = MarketState(
            timestamp=datetime.now(),
            mid_price=50000,
            imbalance=0.5,
            spread=1.0,
            spread_bps=0.02,
            best_bid=49999.5,
            best_ask=50000.5,
            best_bid_qty=10,
            best_ask_qty=8,
        )
        
        assert state.panel is None
    
    def test_panel_with_multi_coin_data(self):
        """패널 데이터로 다른 코인 정보 접근"""
        panel = {
            "ETHUSDT": {
                "price": 3000,
                "return_1h": 0.02,
                "volume": 500,
                "imbalance": 0.3,
            },
            "SOLUSDT": {
                "price": 100,
                "return_1h": -0.01,
                "volume": 200,
                "imbalance": -0.2,
            },
        }
        
        state = MarketState(
            timestamp=datetime.now(),
            mid_price=50000,  # BTC
            imbalance=0.5,
            spread=1.0,
            spread_bps=0.02,
            best_bid=49999.5,
            best_ask=50000.5,
            best_bid_qty=10,
            best_ask_qty=8,
            panel=panel,
        )
        
        assert state.panel is not None
        assert state.panel["ETHUSDT"]["price"] == 3000
        assert state.panel["SOLUSDT"]["return_1h"] == -0.01
    
    def test_panel_symbol_field(self):
        """현재 심볼 식별 필드"""
        state = MarketState(
            timestamp=datetime.now(),
            mid_price=50000,
            imbalance=0.5,
            spread=1.0,
            spread_bps=0.02,
            best_bid=49999.5,
            best_ask=50000.5,
            best_bid_qty=10,
            best_ask_qty=8,
            symbol="BTCUSDT",
        )
        
        assert state.symbol == "BTCUSDT"
    
    def test_symbol_defaults_to_none(self):
        """symbol 없어도 기존 코드 작동"""
        state = MarketState(
            timestamp=datetime.now(),
            mid_price=50000,
            imbalance=0.5,
            spread=1.0,
            spread_bps=0.02,
            best_bid=49999.5,
            best_ask=50000.5,
            best_bid_qty=10,
            best_ask_qty=8,
        )
        
        assert state.symbol is None


# ============================================================
# Phase 2: 기존 전략 하위 호환
# ============================================================

class TestBackwardCompatibility:
    """기존 단일 코인 전략이 panel 무시하고 작동"""
    
    def test_obi_strategy_with_panel(self):
        """OBI 전략이 panel 있어도 정상 작동"""
        from intraday.strategy import OBIStrategy
        
        strategy = OBIStrategy(buy_threshold=0.3, quantity=0.01)
        
        state = MarketState(
            timestamp=datetime.now(),
            mid_price=50000,
            imbalance=0.5,
            spread=1.0,
            spread_bps=0.02,
            best_bid=49999.5,
            best_ask=50000.5,
            best_bid_qty=10,
            best_ask_qty=8,
            panel={"ETHUSDT": {"price": 3000}},  # 추가되어도
        )
        
        order = strategy.generate_order(state)
        
        # 기존 로직 그대로 작동
        assert order is not None
        assert order.side == Side.BUY


# ============================================================
# Phase 3: 포트폴리오 전략 인터페이스
# ============================================================

class TestPortfolioStrategyInterface:
    """포트폴리오 전략을 위한 확장 인터페이스"""
    
    def test_portfolio_order(self):
        """포트폴리오 주문 - 여러 코인 동시 주문"""
        from intraday.strategy import PortfolioOrder
        
        orders = PortfolioOrder(orders={
            "BTCUSDT": Order(side=Side.BUY, quantity=0.1),
            "ETHUSDT": Order(side=Side.SELL, quantity=1.0),
            "SOLUSDT": None,  # 이 코인은 주문 없음
        })
        
        assert orders["BTCUSDT"].side == Side.BUY
        assert orders["ETHUSDT"].side == Side.SELL
        assert orders["SOLUSDT"] is None
        assert len(orders.active_orders) == 2
    
    def test_portfolio_position_state(self):
        """포트폴리오 포지션 상태를 MarketState로 전달"""
        state = MarketState(
            timestamp=datetime.now(),
            mid_price=50000,
            imbalance=0.5,
            spread=1.0,
            spread_bps=0.02,
            best_bid=49999.5,
            best_ask=50000.5,
            best_bid_qty=10,
            best_ask_qty=8,
            symbol="BTCUSDT",
            positions={
                "BTCUSDT": {"side": "BUY", "qty": 0.1, "entry_price": 49000},
                "ETHUSDT": {"side": "SELL", "qty": 1.0, "entry_price": 3100},
            },
        )
        
        assert state.positions is not None
        assert state.positions["BTCUSDT"]["side"] == "BUY"
        assert state.positions["ETHUSDT"]["qty"] == 1.0
    
    def test_positions_defaults_to_none(self):
        """positions 없어도 기존 코드 작동"""
        state = MarketState(
            timestamp=datetime.now(),
            mid_price=50000,
            imbalance=0.5,
            spread=1.0,
            spread_bps=0.02,
            best_bid=49999.5,
            best_ask=50000.5,
            best_bid_qty=10,
            best_ask_qty=8,
        )
        
        assert state.positions is None
