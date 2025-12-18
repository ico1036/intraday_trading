"""
OBIStrategy 통합 테스트

실제 거래 시나리오를 시뮬레이션하고 결과를 직접 계산해서 검증합니다.
WebSocket 대신 Mock으로 데이터를 주입합니다 (스트리밍 데이터는 매번 달라지므로).

테스트 원칙:
- 각 시나리오마다 "이때는 BUY/SELL이 떠야한다"를 직접 계산
- Win rate, Trade 개수도 직접 계산해서 검증
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from intraday.strategy import Side, OrderType, Order, MarketState, OBIStrategy
from intraday.runner import ForwardRunner
from intraday.client import OrderbookSnapshot, AggTrade
from intraday.paper_trader import PaperTrader
from intraday.performance import PerformanceCalculator


class TestOBIStrategySignalGeneration:
    """
    OBI 시그널 생성 테스트
    
    유저 입장: "imbalance가 이 값이면 당연히 BUY/SELL이 나와야지!"
    """
    
    def test_buy_signal_calculation(self):
        """
        시나리오: 매수 물량이 매도 물량보다 압도적으로 많음
        
        계산:
            bid_qty = 3.0, ask_qty = 1.0
            imbalance = (3.0 - 1.0) / (3.0 + 1.0) = 2.0 / 4.0 = 0.5
            0.5 > buy_threshold(0.3) → BUY 신호!
        """
        strategy = OBIStrategy(buy_threshold=0.3, sell_threshold=-0.3, quantity=0.01)
        
        state = MarketState(
            timestamp=datetime.now(),
            mid_price=100000.0,
            imbalance=0.5,  # 직접 계산: (3.0 - 1.0) / (3.0 + 1.0)
            spread=10.0,
            spread_bps=1.0,
            best_bid=99995.0,
            best_ask=100005.0,
            best_bid_qty=3.0,
            best_ask_qty=1.0,
        )
        
        order = strategy.generate_order(state)
        
        # 검증: 0.5 > 0.3 이므로 BUY
        assert order is not None, "imbalance 0.5 > threshold 0.3 이므로 BUY 주문 생성되어야 함"
        assert order.side == Side.BUY
        assert order.order_type == OrderType.LIMIT
        assert order.limit_price == 100005.0  # best_ask (Taker: 즉시 체결)
        assert order.quantity == 0.01
    
    def test_sell_signal_calculation(self):
        """
        시나리오: 매도 물량이 매수 물량보다 압도적으로 많음 (BUY 포지션 보유)
        
        계산:
            bid_qty = 0.5, ask_qty = 2.5
            imbalance = (0.5 - 2.5) / (0.5 + 2.5) = -2.0 / 3.0 = -0.667
            -0.667 < sell_threshold(-0.3) → SELL 신호!
        
        Note: 현물 거래에서는 BUY 포지션이 있어야 SELL 가능
        """
        strategy = OBIStrategy(buy_threshold=0.3, sell_threshold=-0.3, quantity=0.02)
        
        state = MarketState(
            timestamp=datetime.now(),
            mid_price=100000.0,
            imbalance=-0.667,  # 직접 계산: (0.5 - 2.5) / (0.5 + 2.5)
            spread=10.0,
            spread_bps=1.0,
            best_bid=99995.0,
            best_ask=100005.0,
            best_bid_qty=0.5,
            best_ask_qty=2.5,
            position_side=Side.BUY,  # BUY 포지션 보유 시에만 SELL 가능
            position_qty=0.02,
        )
        
        order = strategy.generate_order(state)
        
        # 검증: -0.667 < -0.3 이므로 SELL (BUY 포지션 청산)
        assert order is not None, "imbalance -0.667 < threshold -0.3 이고 BUY 포지션 보유 시 SELL 주문 생성되어야 함"
        assert order.side == Side.SELL
        assert order.order_type == OrderType.LIMIT
        assert order.limit_price == 99995.0  # best_bid (Taker: 즉시 체결)
        assert order.quantity == 0.02
    
    def test_no_signal_neutral_zone(self):
        """
        시나리오: 매수/매도 물량이 비슷함 (중립 구간)
        
        계산:
            bid_qty = 1.2, ask_qty = 1.0
            imbalance = (1.2 - 1.0) / (1.2 + 1.0) = 0.2 / 2.2 = 0.091
            -0.3 < 0.091 < 0.3 → 신호 없음!
        """
        strategy = OBIStrategy(buy_threshold=0.3, sell_threshold=-0.3, quantity=0.01)
        
        state = MarketState(
            timestamp=datetime.now(),
            mid_price=100000.0,
            imbalance=0.091,  # 직접 계산: (1.2 - 1.0) / (1.2 + 1.0)
            spread=10.0,
            spread_bps=1.0,
            best_bid=99995.0,
            best_ask=100005.0,
            best_bid_qty=1.2,
            best_ask_qty=1.0,
        )
        
        order = strategy.generate_order(state)
        
        # 검증: -0.3 < 0.091 < 0.3 이므로 신호 없음
        assert order is None, "imbalance 0.091은 중립 구간이므로 주문 없어야 함"


class TestOBIStrategyFullTradingCycle:
    """
    전체 거래 사이클 통합 테스트
    
    유저 입장: "매수 신호 → 체결 → 매도 신호 → 체결 → 수익/손실 계산이 정확해야지!"
    """
    
    def test_profitable_trade_cycle(self):
        """
        시나리오: 수익 거래 (Taker 전략)
        
        1. 매수 진입: best_ask(100010)에 0.01 BTC 매수
        2. 매도 청산: best_bid(100990)에 0.01 BTC 매도
        
        계산 (Taker 전략):
            매수 비용: 100010 * 0.01 = 1000.10 USD
            매수 수수료: 1000.10 * 0.001 = 1.0001 USD
            매도 수익: 100990 * 0.01 = 1009.90 USD
            매도 수수료: 1009.90 * 0.001 = 1.0099 USD
            순수익: (100990 - 100010) * 0.01 - 1.0001 - 1.0099 = 9.80 - 2.01 = 7.79 USD
        """
        strategy = OBIStrategy(buy_threshold=0.3, sell_threshold=-0.3, quantity=0.01)
        runner = ForwardRunner(strategy, initial_capital=10000.0, fee_rate=0.001)
        
        # === 1. 매수 신호 ===
        # imbalance = (2.0 - 0.5) / (2.0 + 0.5) = 0.6 > 0.3 → BUY
        snapshot1 = OrderbookSnapshot(
            timestamp=datetime.now(),
            last_update_id=1,
            bids=[(100000.0, 2.0)],
            asks=[(100010.0, 0.5)],
            symbol="BTCUSDT",
        )
        runner._on_orderbook(snapshot1)
        
        # 검증: BUY 주문 생성됨 (Taker: best_ask에 주문)
        assert runner._order_count == 1
        assert len(runner._trader.pending_orders) == 1
        pending = runner._trader.pending_orders[0]
        assert pending.order.side == Side.BUY
        assert pending.order.limit_price == 100010.0  # best_ask (Taker)
        
        # === 2. 매수 체결 ===
        # BUY LIMIT: price <= limit_price 시 체결
        trade1 = AggTrade(
            timestamp=datetime.now(),
            symbol="BTCUSDT",
            price=100005.0,  # <= 100010 → 체결!
            quantity=0.5,
            is_buyer_maker=False,
        )
        runner._on_trade(trade1)
        
        # 검증: 포지션 생성됨
        assert runner._trader.position.side == Side.BUY
        assert runner._trader.position.quantity == 0.01
        assert runner._trader.position.entry_price == 100010.0  # limit_price로 체결
        assert runner._trader.btc_balance == pytest.approx(0.01, rel=0.01)
        
        # === 3. 매도 신호 ===
        # imbalance = (0.3 - 2.0) / (0.3 + 2.0) = -0.739 < -0.3 → SELL
        snapshot2 = OrderbookSnapshot(
            timestamp=datetime.now(),
            last_update_id=2,
            bids=[(100990.0, 0.3)],
            asks=[(101000.0, 2.0)],
            symbol="BTCUSDT",
        )
        runner._on_orderbook(snapshot2)
        
        # 검증: SELL 주문 생성됨 (Taker: best_bid에 주문)
        assert runner._order_count == 2
        pending2 = runner._trader.pending_orders[0]
        assert pending2.order.side == Side.SELL
        assert pending2.order.limit_price == 100990.0  # best_bid (Taker)
        
        # === 4. 매도 체결 ===
        # SELL LIMIT: price >= limit_price 시 체결
        trade2 = AggTrade(
            timestamp=datetime.now(),
            symbol="BTCUSDT",
            price=100995.0,  # >= 100990 → 체결!
            quantity=0.3,
            is_buyer_maker=False,
        )
        runner._on_trade(trade2)
        
        # 검증: 포지션 청산됨
        assert runner._trader.position.side is None
        assert runner._trader.btc_balance == pytest.approx(0.0, abs=0.0001)
        
        # === 5. 수익 검증 ===
        # 직접 계산 (Taker 전략):
        #   매수: 100010 * 0.01 = 1000.10, 수수료 1.0001
        #   매도: 100990 * 0.01 = 1009.90, 수수료 1.0099
        #   순수익: (100990 - 100010) * 0.01 - 1.0001 - 1.0099 = 9.80 - 2.01 = 7.79
        entry_price = 100010.0
        exit_price = 100990.0
        qty = 0.01
        fee_rate = 0.001
        expected_pnl = (exit_price - entry_price) * qty - (entry_price * qty * fee_rate) - (exit_price * qty * fee_rate)
        
        # PaperTrader에서 직접 PnL 확인
        assert runner._trader.realized_pnl == pytest.approx(expected_pnl, rel=0.01)
        
        report = runner.get_performance_report()
        
        assert report.total_trades == 2
        assert report.total_return > 0  # 수익!
    
    def test_losing_trade_cycle(self):
        """
        시나리오: 손실 거래 (Taker 전략)
        
        1. 매수 진입: best_ask(100010)에 0.01 BTC 매수
        2. 매도 청산: best_bid(98990)에 0.01 BTC 매도 (손실)
        
        계산 (Taker 전략):
            순손실: (98990 - 100010) * 0.01 - 수수료
                  = -10.20 - (100010*0.01*0.001 + 98990*0.01*0.001)
                  = -10.20 - 1.0001 - 0.9899 = -12.19 USD
        """
        strategy = OBIStrategy(buy_threshold=0.3, sell_threshold=-0.3, quantity=0.01)
        runner = ForwardRunner(strategy, initial_capital=10000.0, fee_rate=0.001)
        
        # 1. 매수 진입 (Taker: best_ask에 주문)
        snapshot1 = OrderbookSnapshot(
            timestamp=datetime.now(),
            last_update_id=1,
            bids=[(100000.0, 3.0)],  # imbalance = 0.5 > 0.3
            asks=[(100010.0, 1.0)],
            symbol="BTCUSDT",
        )
        runner._on_orderbook(snapshot1)
        
        trade1 = AggTrade(
            timestamp=datetime.now(),
            symbol="BTCUSDT",
            price=100005.0,  # <= 100010 → 체결
            quantity=0.5,
            is_buyer_maker=False,
        )
        runner._on_trade(trade1)
        
        assert runner._trader.position.side == Side.BUY
        assert runner._trader.position.entry_price == 100010.0  # best_ask
        
        # 2. 가격 하락 후 매도 청산 (Taker: best_bid에 주문)
        snapshot2 = OrderbookSnapshot(
            timestamp=datetime.now(),
            last_update_id=2,
            bids=[(98990.0, 0.2)],  # imbalance = (0.2-2.0)/(0.2+2.0) = -0.82 < -0.3
            asks=[(99000.0, 2.0)],
            symbol="BTCUSDT",
        )
        runner._on_orderbook(snapshot2)
        
        trade2 = AggTrade(
            timestamp=datetime.now(),
            symbol="BTCUSDT",
            price=98995.0,  # >= 98990 → 체결
            quantity=0.3,
            is_buyer_maker=False,
        )
        runner._on_trade(trade2)
        
        # 검증: 손실 (Taker 전략 기준)
        entry_price = 100010.0
        exit_price = 98990.0
        qty = 0.01
        fee_rate = 0.001
        expected_pnl = (exit_price - entry_price) * qty - (entry_price * qty * fee_rate) - (exit_price * qty * fee_rate)
        
        # PaperTrader에서 직접 PnL 확인
        assert runner._trader.realized_pnl == pytest.approx(expected_pnl, rel=0.01)
        
        report = runner.get_performance_report()
        
        assert report.total_trades == 2
        assert report.total_return < 0  # 손실!


class TestOBIStrategyWinRateAndTradeCount:
    """
    Win Rate와 Trade Count 검증
    
    유저 입장: "3번 이기고 2번 지면 win rate가 60%여야지!"
    """
    
    def test_win_rate_calculation(self):
        """
        시나리오: 3승 2패
        
        Trade 1: +50 USD (승)
        Trade 2: -30 USD (패)
        Trade 3: +40 USD (승)
        Trade 4: +20 USD (승)
        Trade 5: -10 USD (패)
        
        Win Rate = 3 / 5 = 60%
        Total Trades = 5 (청산 거래만 카운트)
        """
        trader = PaperTrader(initial_capital=100000.0, fee_rate=0.0)  # 수수료 0으로 단순화
        
        # Trade 1: 매수 100000 → 매도 105000 = +50 (승)
        buy1 = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(buy1)
        trader.on_price_update(100000.0, 99990.0, 100000.0, datetime.now())
        
        sell1 = Order(side=Side.SELL, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(sell1)
        trader.on_price_update(105000.0, 105000.0, 105010.0, datetime.now())
        
        # Trade 2: 매수 105000 → 매도 102000 = -30 (패)
        buy2 = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(buy2)
        trader.on_price_update(105000.0, 104990.0, 105000.0, datetime.now())
        
        sell2 = Order(side=Side.SELL, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(sell2)
        trader.on_price_update(102000.0, 102000.0, 102010.0, datetime.now())
        
        # Trade 3: 매수 102000 → 매도 106000 = +40 (승)
        buy3 = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(buy3)
        trader.on_price_update(102000.0, 101990.0, 102000.0, datetime.now())
        
        sell3 = Order(side=Side.SELL, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(sell3)
        trader.on_price_update(106000.0, 106000.0, 106010.0, datetime.now())
        
        # Trade 4: 매수 106000 → 매도 108000 = +20 (승)
        buy4 = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(buy4)
        trader.on_price_update(106000.0, 105990.0, 106000.0, datetime.now())
        
        sell4 = Order(side=Side.SELL, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(sell4)
        trader.on_price_update(108000.0, 108000.0, 108010.0, datetime.now())
        
        # Trade 5: 매수 108000 → 매도 107000 = -10 (패)
        buy5 = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(buy5)
        trader.on_price_update(108000.0, 107990.0, 108000.0, datetime.now())
        
        sell5 = Order(side=Side.SELL, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(sell5)
        trader.on_price_update(107000.0, 107000.0, 107010.0, datetime.now())
        
        # 검증
        trades = trader.trades
        assert len(trades) == 10  # 진입 5 + 청산 5
        
        # 청산 거래만 필터링 (pnl != 0)
        closing_trades = [t for t in trades if t.pnl != 0]
        assert len(closing_trades) == 5
        
        # 직접 계산한 PnL
        # Trade 1: (105000 - 100000) * 0.01 = +50
        # Trade 2: (102000 - 105000) * 0.01 = -30
        # Trade 3: (106000 - 102000) * 0.01 = +40
        # Trade 4: (108000 - 106000) * 0.01 = +20
        # Trade 5: (107000 - 108000) * 0.01 = -10
        expected_pnls = [50, -30, 40, 20, -10]
        
        for i, trade in enumerate(closing_trades):
            assert trade.pnl == pytest.approx(expected_pnls[i], rel=0.01), \
                f"Trade {i+1}: expected {expected_pnls[i]}, got {trade.pnl}"
        
        # Win Rate 계산
        winning_trades = [t for t in closing_trades if t.pnl > 0]
        win_rate = len(winning_trades) / len(closing_trades)
        
        assert win_rate == pytest.approx(0.6, rel=0.01), f"Win rate: {win_rate}"
        
        # PerformanceCalculator로 검증
        now = datetime.now()
        report = PerformanceCalculator.calculate(
            trades=trades, 
            initial_capital=100000.0, 
            strategy_name="TestStrategy",
            symbol="BTCUSDT",
            start_time=now,
            end_time=now,
        )
        
        assert report.total_trades == 10  # 전체 거래 수
        # win_rate는 % 형태 (0.6이 아닌 60.0)
        assert report.win_rate == pytest.approx(60.0, rel=0.01)
        
        # 총 수익: 50 - 30 + 40 + 20 - 10 = 70
        expected_total_pnl = sum(expected_pnls)
        assert trader.realized_pnl == pytest.approx(expected_total_pnl, rel=0.01)
    
    def test_trade_count_precision(self):
        """
        시나리오: 정확히 N번의 거래 사이클
        
        2번의 완전한 거래 사이클 = 4개의 Trade (진입 2 + 청산 2)
        """
        trader = PaperTrader(initial_capital=10000.0, fee_rate=0.001)
        
        # Cycle 1
        buy1 = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(buy1)
        trader.on_price_update(100000.0, 99990.0, 100000.0, datetime.now())
        
        sell1 = Order(side=Side.SELL, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(sell1)
        trader.on_price_update(101000.0, 101000.0, 101010.0, datetime.now())
        
        # Cycle 2
        buy2 = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(buy2)
        trader.on_price_update(101000.0, 100990.0, 101000.0, datetime.now())
        
        sell2 = Order(side=Side.SELL, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(sell2)
        trader.on_price_update(102000.0, 102000.0, 102010.0, datetime.now())
        
        # 검증
        assert len(trader.trades) == 4, f"Expected 4 trades, got {len(trader.trades)}"
        
        # 청산 거래만
        closing_trades = [t for t in trader.trades if t.pnl != 0]
        assert len(closing_trades) == 2, "2번의 청산 거래"


class TestOBIStrategyEdgeCases:
    """
    엣지 케이스 테스트
    """
    
    def test_exact_threshold_buy(self):
        """
        imbalance가 정확히 buy_threshold일 때
        
        계산: imbalance = 0.3 (정확히)
        조건: imbalance > buy_threshold(0.3) → False (초과가 아니므로)
        """
        strategy = OBIStrategy(buy_threshold=0.3, sell_threshold=-0.3, quantity=0.01)
        
        state = MarketState(
            timestamp=datetime.now(),
            mid_price=100000.0,
            imbalance=0.3,  # 정확히 threshold
            spread=10.0,
            spread_bps=1.0,
            best_bid=99995.0,
            best_ask=100005.0,
            best_bid_qty=1.3,
            best_ask_qty=0.7,
        )
        
        order = strategy.generate_order(state)
        
        # 검증: 0.3 > 0.3 은 False이므로 주문 없음
        assert order is None, "imbalance == threshold 이면 주문 없어야 함 (초과가 아님)"
    
    def test_exact_threshold_sell(self):
        """
        imbalance가 정확히 sell_threshold일 때
        
        계산: imbalance = -0.3 (정확히)
        조건: imbalance < sell_threshold(-0.3) → False (미만이 아니므로)
        """
        strategy = OBIStrategy(buy_threshold=0.3, sell_threshold=-0.3, quantity=0.01)
        
        state = MarketState(
            timestamp=datetime.now(),
            mid_price=100000.0,
            imbalance=-0.3,  # 정확히 threshold
            spread=10.0,
            spread_bps=1.0,
            best_bid=99995.0,
            best_ask=100005.0,
            best_bid_qty=0.7,
            best_ask_qty=1.3,
        )
        
        order = strategy.generate_order(state)
        
        # 검증: -0.3 < -0.3 은 False이므로 주문 없음
        assert order is None, "imbalance == threshold 이면 주문 없어야 함 (미만이 아님)"
    
    def test_insufficient_balance_prevents_trade(self):
        """
        잔고 부족 시 거래 실패
        
        시나리오: 100 USD로 0.01 BTC(100000 USD 가치) 매수 시도
        """
        strategy = OBIStrategy(buy_threshold=0.3, sell_threshold=-0.3, quantity=0.01)
        runner = ForwardRunner(strategy, initial_capital=100.0, fee_rate=0.001)  # 100 USD만
        
        # 매수 신호
        snapshot = OrderbookSnapshot(
            timestamp=datetime.now(),
            last_update_id=1,
            bids=[(100000.0, 2.0)],  # imbalance > 0.3
            asks=[(100010.0, 0.5)],
            symbol="BTCUSDT",
        )
        runner._on_orderbook(snapshot)
        
        # 체결 시도
        trade = AggTrade(
            timestamp=datetime.now(),
            symbol="BTCUSDT",
            price=99990.0,
            quantity=0.5,
            is_buyer_maker=False,
        )
        runner._on_trade(trade)
        
        # 검증: 잔고 부족으로 체결 안 됨
        assert runner._trader.position.side is None, "잔고 부족으로 포지션 없어야 함"
        assert runner._trader.usd_balance == 100.0, "잔고 변화 없어야 함"
        assert runner._trader.btc_balance == 0.0

