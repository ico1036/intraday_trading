"""
선물 거래 테스트

TDD 방식으로 선물 거래 기능을 검증합니다.
"""

import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

from intraday.paper_trader import PaperTrader, Position
from intraday.strategy import Side, Order, OrderType, MarketState
from intraday.backtest.tick_runner import TickBacktestRunner
from intraday.candle_builder import CandleType


class TestFuturesPosition:
    """선물 포지션 테스트"""

    def test_position_has_leverage_field(self):
        """Position에 leverage 필드가 있어야 한다"""
        position = Position(
            side=Side.BUY,
            quantity=0.1,
            entry_price=50000,
            leverage=10,
        )
        assert position.leverage == 10

    def test_position_has_liquidation_price_field(self):
        """Position에 liquidation_price 필드가 있어야 한다"""
        position = Position(
            side=Side.BUY,
            quantity=0.1,
            entry_price=50000,
            leverage=10,
            liquidation_price=45000,
        )
        assert position.liquidation_price == 45000

    def test_position_has_margin_field(self):
        """Position에 margin 필드가 있어야 한다"""
        position = Position(
            side=Side.BUY,
            quantity=0.1,
            entry_price=50000,
            leverage=10,
            margin=500,  # 5000 / 10
        )
        assert position.margin == 500

    def test_position_defaults_to_spot_mode(self):
        """기본값은 현물 모드 (leverage=1)"""
        position = Position()
        assert position.leverage == 1
        assert position.liquidation_price is None
        assert position.margin == 0.0


class TestFuturesPaperTrader:
    """선물 PaperTrader 테스트"""

    def test_paper_trader_accepts_leverage_parameter(self):
        """PaperTrader가 leverage 파라미터를 받아야 한다"""
        trader = PaperTrader(initial_capital=10000, leverage=10)
        assert trader.leverage == 10

    def test_paper_trader_defaults_to_spot_mode(self):
        """기본값은 현물 모드 (leverage=1)"""
        trader = PaperTrader(initial_capital=10000)
        assert trader.leverage == 1

    def test_futures_long_position_uses_margin(self):
        """선물 롱 포지션은 마진만 사용한다"""
        trader = PaperTrader(initial_capital=10000, leverage=10)

        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)

        # 체결: 0.1 BTC @ $50,000 = $5,000 notional
        # 10x 레버리지 → 마진 = $500
        trade = trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime.now(),
        )

        assert trade is not None
        # 마진 $500 + 수수료만 차감되어야 함 (현물은 $5,000 + 수수료)
        assert trader.usd_balance > 9000  # 마진 기반

    def test_futures_position_has_liquidation_price(self):
        """선물 포지션은 청산가가 계산되어야 한다"""
        trader = PaperTrader(initial_capital=10000, leverage=10)

        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)

        trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime.now(),
        )

        # 10x 롱 → 약 10% 하락 시 청산
        assert trader.position.liquidation_price is not None
        assert 44000 < trader.position.liquidation_price < 46000


class TestLiquidation:
    """청산 로직 테스트"""

    def test_long_position_liquidated_when_price_drops_below_liquidation(self):
        """롱 포지션은 가격이 청산가 이하로 떨어지면 청산된다"""
        trader = PaperTrader(initial_capital=10000, leverage=10)

        # 포지션 오픈
        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime.now(),
        )

        assert trader.position.side == Side.BUY
        liq_price = trader.position.liquidation_price

        # 청산가 이하로 가격 하락
        trader.on_price_update(
            price=liq_price - 100,
            best_bid=liq_price - 110,
            best_ask=liq_price - 100,
            timestamp=datetime.now(),
        )

        # 포지션이 청산되어야 함
        assert trader.position.side is None
        assert trader.position.quantity == 0.0

    def test_short_position_liquidated_when_price_rises_above_liquidation(self):
        """숏 포지션은 가격이 청산가 이상으로 오르면 청산된다"""
        trader = PaperTrader(initial_capital=10000, leverage=10)

        # 먼저 롱 포지션 오픈 후 청산하여 BTC 확보 (현물 모드 호환)
        # 선물에서는 공매도 가능해야 함
        order = Order(side=Side.SELL, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=50000,
            best_ask=50010,
            timestamp=datetime.now(),
        )

        assert trader.position.side == Side.SELL
        liq_price = trader.position.liquidation_price

        # 청산가 이상으로 가격 상승
        trader.on_price_update(
            price=liq_price + 100,
            best_bid=liq_price + 100,
            best_ask=liq_price + 110,
            timestamp=datetime.now(),
        )

        # 포지션이 청산되어야 함
        assert trader.position.side is None

    def test_liquidation_results_in_margin_loss(self):
        """청산 시 마진을 잃는다"""
        trader = PaperTrader(initial_capital=10000, leverage=10)

        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime.now(),
        )

        initial_balance = 10000
        liq_price = trader.position.liquidation_price

        # 청산
        trader.on_price_update(
            price=liq_price - 100,
            best_bid=liq_price - 110,
            best_ask=liq_price - 100,
            timestamp=datetime.now(),
        )

        # 초기 자본 대비 손실 발생
        # 마진 $500 + 수수료 $5 중 대부분 손실
        assert trader.usd_balance < initial_balance
        # 실현 손익이 음수여야 함
        assert trader.realized_pnl < 0

    def test_spot_mode_no_liquidation(self):
        """현물 모드에서는 청산이 없다"""
        trader = PaperTrader(initial_capital=10000, leverage=1)  # 현물

        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime.now(),
        )

        assert trader.position.liquidation_price is None

        # 가격이 90% 하락해도 청산 안 됨
        trader.on_price_update(
            price=5000,
            best_bid=4990,
            best_ask=5000,
            timestamp=datetime.now(),
        )

        assert trader.position.side == Side.BUY  # 포지션 유지


class TestFuturesShortSelling:
    """선물 공매도 테스트"""

    def test_futures_allows_short_selling_without_btc(self):
        """선물 모드에서는 BTC 없이 공매도 가능"""
        trader = PaperTrader(initial_capital=10000, leverage=10)

        assert trader.btc_balance == 0.0

        order = Order(side=Side.SELL, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trade = trader.on_price_update(
            price=50000,
            best_bid=50000,
            best_ask=50010,
            timestamp=datetime.now(),
        )

        assert trade is not None
        assert trader.position.side == Side.SELL
        assert trader.position.quantity == 0.1

    def test_spot_rejects_short_selling_without_btc(self):
        """현물 모드에서는 BTC 없이 공매도 불가"""
        trader = PaperTrader(initial_capital=10000, leverage=1)

        order = Order(side=Side.SELL, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trade = trader.on_price_update(
            price=50000,
            best_bid=50000,
            best_ask=50010,
            timestamp=datetime.now(),
        )

        assert trade is None  # 체결 실패
        assert trader.position.side is None


class TestLiquidationPriceCalculation:
    """청산가 계산 테스트"""

    def test_long_liquidation_price_formula(self):
        """롱 청산가 = entry * (1 - 1/leverage + MMR)"""
        trader = PaperTrader(initial_capital=10000, leverage=10)

        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime.now(),
        )

        # 10x leverage, MMR ~0.4% for small positions
        # liq_price ≈ 50000 * (1 - 0.1 + 0.004) = 50000 * 0.904 = 45200
        liq_price = trader.position.liquidation_price
        assert 45000 < liq_price < 46000

    def test_short_liquidation_price_formula(self):
        """숏 청산가 = entry * (1 + 1/leverage - MMR)"""
        trader = PaperTrader(initial_capital=10000, leverage=10)

        order = Order(side=Side.SELL, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=50000,
            best_ask=50010,
            timestamp=datetime.now(),
        )

        # 10x leverage, MMR ~0.4%
        # liq_price ≈ 50000 * (1 + 0.1 - 0.004) = 50000 * 1.096 = 54800
        liq_price = trader.position.liquidation_price
        assert 54000 < liq_price < 56000

    def test_higher_leverage_closer_liquidation(self):
        """레버리지가 높을수록 청산가가 진입가에 가깝다"""
        trader_10x = PaperTrader(initial_capital=10000, leverage=10)
        trader_20x = PaperTrader(initial_capital=10000, leverage=20)

        for trader in [trader_10x, trader_20x]:
            order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
            trader.submit_order(order)
            trader.on_price_update(
                price=50000,
                best_bid=49990,
                best_ask=50000,
                timestamp=datetime.now(),
            )

        liq_10x = trader_10x.position.liquidation_price
        liq_20x = trader_20x.position.liquidation_price

        # 20x가 진입가(50000)에 더 가까움
        assert liq_20x > liq_10x
        assert 50000 - liq_20x < 50000 - liq_10x


class TestTickBacktestRunnerFutures:
    """TickBacktestRunner 선물 모드 테스트"""

    def test_runner_accepts_leverage_parameter(self):
        """Runner가 leverage 파라미터를 받아야 한다"""
        mock_loader = Mock()
        mock_strategy = Mock()

        runner = TickBacktestRunner(
            strategy=mock_strategy,
            data_loader=mock_loader,
            leverage=10,
        )

        assert runner.leverage == 10
        assert runner._trader.leverage == 10

    def test_runner_defaults_to_spot_mode(self):
        """기본값은 현물 모드"""
        mock_loader = Mock()
        mock_strategy = Mock()

        runner = TickBacktestRunner(
            strategy=mock_strategy,
            data_loader=mock_loader,
        )

        assert runner.leverage == 1
        assert runner._trader.leverage == 1

    def test_runner_futures_mode_enables_short_selling(self):
        """선물 모드에서 공매도 가능"""
        mock_loader = Mock()
        mock_strategy = Mock()

        runner = TickBacktestRunner(
            strategy=mock_strategy,
            data_loader=mock_loader,
            leverage=10,
        )

        # 공매도 주문
        order = Order(side=Side.SELL, quantity=0.1, order_type=OrderType.MARKET)
        runner._trader.submit_order(order)
        trade = runner._trader.on_price_update(
            price=50000,
            best_bid=50000,
            best_ask=50010,
            timestamp=datetime.now(),
        )

        assert trade is not None
        assert runner._trader.position.side == Side.SELL
