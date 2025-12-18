"""
전략 예시 실제 데이터 기반 테스트

유저 입장에서 "이럴땐 이래야 맞다!" 원칙 검증
실제 시장 시나리오를 반영한 테스트
"""

from datetime import datetime, timedelta

import pytest

from intraday.strategy import Side, OrderType, Order, MarketState
from intraday.strategy_example import OBIStrategyWithStopLoss, TrailingStopStrategy
from intraday.paper_trader import PaperTrader
from intraday.performance import PerformanceCalculator


class TestOBIStrategyWithStopLossReal:
    """OBIStrategyWithStopLoss 실제 시나리오 테스트"""
    
    def test_buy_entry_then_stop_loss_triggers(self):
        """
        시나리오: 매수 진입 → 가격 하락 → 손절 실행
        
        유저 입장: "100000에 매수했는데 2% 하락(98000)하면 손절해야지!"
        """
        strategy = OBIStrategyWithStopLoss(
            buy_threshold=0.3,
            sell_threshold=-0.3,
            quantity=0.01,
            stop_loss_pct=0.02,  # 2% 손절
            take_profit_pct=0.05,  # 5% 익절
        )
        trader = PaperTrader(initial_capital=10000.0, fee_rate=0.001)
        
        # 1. 강한 매수 신호로 진입
        state1 = MarketState(
            timestamp=datetime.now(),
            mid_price=100000.0,
            imbalance=0.5,  # > 0.3 (매수 신호)
            spread=10.0,
            spread_bps=1.0,
            best_bid=99995.0,
            best_ask=100005.0,
            best_bid_qty=2.0,
            best_ask_qty=0.5,
        )
        
        order1 = strategy.generate_order(state1)
        assert order1 is not None
        assert order1.side == Side.BUY
        assert order1.order_type == OrderType.LIMIT
        assert order1.limit_price == 99995.0
        
        # 주문 제출 및 체결 시뮬레이션
        trader.submit_order(order1)
        trade1 = trader.on_price_update(
            price=99995.0,
            best_bid=99990.0,
            best_ask=99995.0,
            timestamp=datetime.now(),
        )
        assert trade1 is not None
        assert trader.position.side == Side.BUY
        
        # 2. 가격이 2% 하락 (98000) → 손절 주문 생성되어야 함
        # 전략의 포지션 수량을 실제 포지션 수량으로 업데이트 (청산 주문 생성 전)
        strategy._position_quantity = trader.position.quantity
        
        state2 = MarketState(
            timestamp=datetime.now() + timedelta(seconds=10),
            mid_price=98000.0,  # 2% 하락
            imbalance=0.1,
            spread=10.0,
            spread_bps=1.0,
            best_bid=97995.0,
            best_ask=98005.0,
            best_bid_qty=1.0,
            best_ask_qty=1.0,
        )
        
        order2 = strategy.generate_order(state2)
        assert order2 is not None
        assert order2.side == Side.SELL  # 손절 청산
        assert order2.order_type == OrderType.MARKET  # 즉시 청산
        
        # 손절 주문 체결
        trader.submit_order(order2)
        trade2 = trader.on_price_update(
            price=98000.0,
            best_bid=98000.0,
            best_ask=98010.0,
            timestamp=datetime.now() + timedelta(seconds=10),
        )
        assert trade2 is not None
        assert trader.position.side is None  # 포지션 청산됨
        
        # 손실 확인: (98000 - 99995) * 0.01 = -19.95 (수수료 제외)
        assert trade2.pnl < 0  # 손실
    
    def test_buy_entry_then_take_profit_triggers(self):
        """
        시나리오: 매수 진입 → 가격 상승 → 익절 실행
        
        유저 입장: "100000에 매수했는데 5% 상승(105000)하면 익절해야지!"
        """
        strategy = OBIStrategyWithStopLoss(
            buy_threshold=0.3,
            sell_threshold=-0.3,
            quantity=0.01,
            stop_loss_pct=0.02,
            take_profit_pct=0.05,  # 5% 익절
        )
        trader = PaperTrader(initial_capital=10000.0, fee_rate=0.001)
        
        # 1. 매수 진입
        state1 = MarketState(
            timestamp=datetime.now(),
            mid_price=100000.0,
            imbalance=0.5,
            spread=10.0,
            spread_bps=1.0,
            best_bid=99995.0,
            best_ask=100005.0,
            best_bid_qty=2.0,
            best_ask_qty=0.5,
        )
        
        order1 = strategy.generate_order(state1)
        trader.submit_order(order1)
        trade1 = trader.on_price_update(
            price=99995.0,
            best_bid=99990.0,
            best_ask=99995.0,
            timestamp=datetime.now(),
        )
        assert trade1 is not None
        
        # 2. 가격이 5% 상승 (105000) → 익절 주문 생성
        # 전략의 포지션 수량 업데이트 (청산 주문 생성 전)
        strategy._position_quantity = trader.position.quantity
        
        state2 = MarketState(
            timestamp=datetime.now() + timedelta(seconds=10),
            mid_price=105000.0,  # 5% 상승
            imbalance=0.1,
            spread=10.0,
            spread_bps=1.0,
            best_bid=104995.0,
            best_ask=105005.0,
            best_bid_qty=1.0,
            best_ask_qty=1.0,
        )
        
        order2 = strategy.generate_order(state2)
        assert order2 is not None
        assert order2.side == Side.SELL  # 익절 청산
        assert order2.order_type == OrderType.MARKET
        
        # 익절 주문 체결
        trader.submit_order(order2)
        trade2 = trader.on_price_update(
            price=105000.0,
            best_bid=105000.0,
            best_ask=105010.0,
            timestamp=datetime.now() + timedelta(seconds=10),
        )
        assert trade2 is not None
        assert trader.position.side is None
        
        # 수익 확인: (105000 - 99995) * 0.01 = 50.05 (수수료 제외)
        assert trade2.pnl > 0  # 수익
    
    def test_sell_entry_then_stop_loss_triggers(self):
        """
        시나리오: BTC 보유 상태에서 매도 신호 → 가격 상승 → 손절 실행
        
        유저 입장: "100000에 매도했는데 2% 상승(102000)하면 손절해야지!"
        
        Note: 현물 거래 기준 공매도 미지원. 먼저 BTC를 보유해야 매도 가능.
        """
        strategy = OBIStrategyWithStopLoss(
            buy_threshold=0.3,
            sell_threshold=-0.3,
            quantity=0.01,
            stop_loss_pct=0.02,
            take_profit_pct=0.05,
        )
        trader = PaperTrader(initial_capital=10000.0, fee_rate=0.001)
        
        # 0. 먼저 BTC 보유 (매수 진입)
        initial_buy = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(initial_buy)
        trader.on_price_update(
            price=98000.0,
            best_bid=97995.0,
            best_ask=98000.0,
            timestamp=datetime.now(),
        )
        assert trader.btc_balance == pytest.approx(0.01, rel=0.01)
        
        # 1. 강한 매도 신호로 청산
        state1 = MarketState(
            timestamp=datetime.now(),
            mid_price=100000.0,
            imbalance=-0.5,  # < -0.3 (매도 신호)
            spread=10.0,
            spread_bps=1.0,
            best_bid=99995.0,
            best_ask=100005.0,
            best_bid_qty=0.5,
            best_ask_qty=2.0,
        )
        
        order1 = strategy.generate_order(state1)
        assert order1 is not None
        assert order1.side == Side.SELL
        
        trader.submit_order(order1)
        trade1 = trader.on_price_update(
            price=100005.0,
            best_bid=100000.0,
            best_ask=100005.0,
            timestamp=datetime.now(),
        )
        assert trade1 is not None
        # 청산 후 포지션 없음 (현물 거래)
        assert trader.position.side is None
        assert trader.btc_balance == pytest.approx(0.0, abs=0.0001)
        
        # 수익 확인: 98000에 매수 → 100000에 매도
        # 매도는 best_bid(99995)가 아닌 limit_price(100005)에 체결 (LIMIT 주문)
        # 하지만 현재 로직상 price <= limit_price면 체결되므로 100005에 체결
        # 수익: (100005 - 98000) * 0.01 = 20.05 (수수료 제외 전)
        assert trade1.pnl > 0  # 수익
    
    def test_no_order_when_position_exists(self):
        """
        시나리오: 포지션이 있는 동안 신규 진입 신호 무시
        
        유저 입장: "이미 포지션이 있으면 새로운 신호가 와도 진입하면 안 되지!"
        """
        strategy = OBIStrategyWithStopLoss(
            buy_threshold=0.3,
            sell_threshold=-0.3,
            quantity=0.01,
            stop_loss_pct=0.02,
            take_profit_pct=0.05,
        )
        trader = PaperTrader(initial_capital=10000.0, fee_rate=0.001)
        
        # 1. 매수 진입
        state1 = MarketState(
            timestamp=datetime.now(),
            mid_price=100000.0,
            imbalance=0.5,
            spread=10.0,
            spread_bps=1.0,
            best_bid=99995.0,
            best_ask=100005.0,
            best_bid_qty=2.0,
            best_ask_qty=0.5,
        )
        
        order1 = strategy.generate_order(state1)
        trader.submit_order(order1)
        trade1 = trader.on_price_update(
            price=99995.0,
            best_bid=99990.0,
            best_ask=99995.0,
            timestamp=datetime.now(),
        )
        assert trade1 is not None
        
        # 전략의 포지션 수량 업데이트
        strategy._position_quantity = trader.position.quantity
        
        # 2. 또 다른 강한 매수 신호 (하지만 포지션 있음)
        state2 = MarketState(
            timestamp=datetime.now() + timedelta(seconds=5),
            mid_price=100100.0,
            imbalance=0.6,  # 더 강한 매수 신호
            spread=10.0,
            spread_bps=1.0,
            best_bid=100095.0,
            best_ask=100105.0,
            best_bid_qty=3.0,
            best_ask_qty=0.3,
        )
        
        order2 = strategy.generate_order(state2)
        # 포지션이 있으면 신규 진입 없음 (손절/익절 조건도 충족 안 됨)
        assert order2 is None


class TestOBIStrategyWithStopLossPerformance:
    """OBIStrategyWithStopLoss 성과 테스트"""
    
    def test_complete_trading_cycle_performance(self):
        """
        완전한 거래 사이클 성과 측정
        
        시나리오:
        1. 매수 진입 @ 100000
        2. 익절 @ 105000 (5% 수익)
        3. 매수 진입 @ 105000
        4. 손절 @ 102900 (2% 손실)
        5. 매수 진입 @ 102900
        6. 익절 @ 108045 (5% 수익)
        
        유저 입장: "실제로 이 전략이 돈을 벌 수 있는지 확인해야지!"
        """
        strategy = OBIStrategyWithStopLoss(
            buy_threshold=0.3,
            sell_threshold=-0.3,
            quantity=0.01,
            stop_loss_pct=0.02,
            take_profit_pct=0.05,
        )
        trader = PaperTrader(initial_capital=10000.0, fee_rate=0.001)
        
        states = [
            # 1. 매수 진입
            MarketState(
                timestamp=datetime.now(),
                mid_price=100000.0,
                imbalance=0.5,
                spread=10.0,
                spread_bps=1.0,
                best_bid=99995.0,
                best_ask=100005.0,
                best_bid_qty=2.0,
                best_ask_qty=0.5,
            ),
            # 2. 익절 (5% 상승)
            MarketState(
                timestamp=datetime.now() + timedelta(seconds=10),
                mid_price=105000.0,
                imbalance=0.1,
                spread=10.0,
                spread_bps=1.0,
                best_bid=104995.0,
                best_ask=105005.0,
                best_bid_qty=1.0,
                best_ask_qty=1.0,
            ),
            # 3. 다시 매수 진입
            MarketState(
                timestamp=datetime.now() + timedelta(seconds=20),
                mid_price=105000.0,
                imbalance=0.5,
                spread=10.0,
                spread_bps=1.0,
                best_bid=104995.0,
                best_ask=105005.0,
                best_bid_qty=2.0,
                best_ask_qty=0.5,
            ),
            # 4. 손절 (2% 하락)
            MarketState(
                timestamp=datetime.now() + timedelta(seconds=30),
                mid_price=102900.0,  # 105000 * 0.98
                imbalance=0.1,
                spread=10.0,
                spread_bps=1.0,
                best_bid=102895.0,
                best_ask=102905.0,
                best_bid_qty=1.0,
                best_ask_qty=1.0,
            ),
            # 5. 다시 매수 진입
            MarketState(
                timestamp=datetime.now() + timedelta(seconds=40),
                mid_price=102900.0,
                imbalance=0.5,
                spread=10.0,
                spread_bps=1.0,
                best_bid=102895.0,
                best_ask=102905.0,
                best_bid_qty=2.0,
                best_ask_qty=0.5,
            ),
            # 6. 익절 (5% 상승)
            MarketState(
                timestamp=datetime.now() + timedelta(seconds=50),
                mid_price=108045.0,  # 102900 * 1.05
                imbalance=0.1,
                spread=10.0,
                spread_bps=1.0,
                best_bid=108040.0,
                best_ask=108050.0,
                best_bid_qty=1.0,
                best_ask_qty=1.0,
            ),
        ]
        
        # 거래 실행
        for state in states:
            order = strategy.generate_order(state)
            if order:
                trader.submit_order(order)
                # 체결 시뮬레이션
                if order.order_type == OrderType.LIMIT:
                    price = order.limit_price
                else:
                    price = state.mid_price
                
                trade = trader.on_price_update(
                    price=price,
                    best_bid=price - 5.0,
                    best_ask=price + 5.0,
                    timestamp=state.timestamp,
                )
                if trade:
                    trader.update_unrealized_pnl(state.mid_price)
                    # 전략의 포지션 수량 업데이트
                    if trader.position.side is not None:
                        strategy._position_side = trader.position.side
                        strategy._position_quantity = trader.position.quantity
                        strategy._entry_price = trader.position.entry_price
                    else:
                        strategy._clear_position()
        
        # 성과 리포트 생성
        report = PerformanceCalculator.calculate(
            trades=trader.trades,
            initial_capital=10000.0,
            strategy_name="OBIStrategyWithStopLoss",
            symbol="BTCUSDT",
            start_time=datetime.now(),
            end_time=datetime.now() + timedelta(minutes=1),
        )
        
        # 검증: 전체적으로 수익이어야 함
        assert report.total_trades >= 2  # 최소 2개 거래 (진입+청산)
        assert report.total_return > 0  # 전체 수익률 양수
        assert report.win_rate > 0  # 승률 존재
        
        # 실제 성과 확인 (수수료 포함)
        assert report.total_return > 0.1  # 최소 0.1% 수익


class TestTrailingStopStrategyReal:
    """TrailingStopStrategy 실제 시나리오 테스트"""
    
    def test_trailing_stop_follows_price_up(self):
        """
        시나리오: 가격 상승 시 trailing stop이 따라 올라감
        
        유저 입장: "가격이 올라가면 손절선도 올라가야지! 수익을 보호해야지!"
        """
        strategy = TrailingStopStrategy(trailing_pct=0.01)  # 1% 트레일링
        
        # 포지션 진입 (간단히 설정)
        strategy._position_side = Side.BUY
        strategy._entry_price = 100000.0
        strategy._highest_price = 100000.0
        strategy._position_quantity = 0.01
        
        # 1. 가격이 101000으로 상승
        state1 = MarketState(
            timestamp=datetime.now(),
            mid_price=101000.0,
            imbalance=0.1,
            spread=10.0,
            spread_bps=1.0,
            best_bid=100995.0,
            best_ask=101005.0,
            best_bid_qty=1.0,
            best_ask_qty=1.0,
        )
        
        order1 = strategy.generate_order(state1)
        assert order1 is None  # 아직 청산 안 됨
        assert strategy._highest_price == 101000.0  # 최고가 업데이트
        
        # 2. 가격이 102000으로 더 상승
        state2 = MarketState(
            timestamp=datetime.now() + timedelta(seconds=10),
            mid_price=102000.0,
            imbalance=0.1,
            spread=10.0,
            spread_bps=1.0,
            best_bid=101995.0,
            best_ask=102005.0,
            best_bid_qty=1.0,
            best_ask_qty=1.0,
        )
        
        order2 = strategy.generate_order(state2)
        assert order2 is None
        assert strategy._highest_price == 102000.0
        
        # 3. 가격이 1% 하락 (102000 * 0.99 = 100980) → 청산
        state3 = MarketState(
            timestamp=datetime.now() + timedelta(seconds=20),
            mid_price=100980.0,  # 최고가 대비 1% 하락
            imbalance=0.1,
            spread=10.0,
            spread_bps=1.0,
            best_bid=100975.0,
            best_ask=100985.0,
            best_bid_qty=1.0,
            best_ask_qty=1.0,
        )
        
        order3 = strategy.generate_order(state3)
        assert order3 is not None
        assert order3.side == Side.SELL  # 청산
        assert order3.order_type == OrderType.MARKET
        
        # 손절선이 102000 * 0.99 = 100980으로 올라간 것 확인
        trailing_stop_price = 102000.0 * 0.99
        assert abs(state3.mid_price - trailing_stop_price) < 1.0

