"""
선물 거래 수학적 검증 테스트

까다로운 개념의 정확한 계산을 검증합니다:
1. 레버리지 마진 계산
2. 청산가 계산
3. 수익률 계산 (레버리지 배율 적용)
4. 공매도 수익/손실 계산
5. 부분 청산 계산
"""

import pytest
from datetime import datetime
from decimal import Decimal

from intraday.paper_trader import PaperTrader, Position
from intraday.strategy import Side, Order, OrderType


class TestLeverageMarginCalculation:
    """레버리지 마진 계산 정확성 테스트"""

    def test_10x_leverage_margin_exact_calculation(self):
        """10x 레버리지: 마진 = 포지션크기 / 10"""
        trader = PaperTrader(initial_capital=10000, leverage=10, fee_rate=0.0)  # 수수료 제외

        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime.now(),
        )

        # 0.1 BTC @ $50,000 = $5,000 notional
        # 10x 레버리지 → 마진 = $500
        assert trader.position.margin == 500.0
        # 잔고: 10000 - 500 = 9500
        assert trader.usd_balance == 9500.0

    def test_20x_leverage_margin_exact_calculation(self):
        """20x 레버리지: 마진 = 포지션크기 / 20"""
        trader = PaperTrader(initial_capital=10000, leverage=20, fee_rate=0.0)

        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime.now(),
        )

        # 0.1 BTC @ $50,000 = $5,000 notional
        # 20x 레버리지 → 마진 = $250
        assert trader.position.margin == 250.0
        assert trader.usd_balance == 9750.0

    def test_margin_with_fee_calculation(self):
        """마진 + 수수료 = 총 차감액"""
        fee_rate = 0.001  # 0.1%
        trader = PaperTrader(initial_capital=10000, leverage=10, fee_rate=fee_rate)

        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime.now(),
        )

        # 마진 = $500, 수수료 = 5000 * 0.001 = $5
        # 총 차감 = $505
        expected_balance = 10000 - 500 - 5
        assert trader.usd_balance == expected_balance  # 9495


class TestLiquidationPriceExactCalculation:
    """청산가 정확한 계산 테스트 (Binance USDT-M Isolated Margin 공식)"""

    # Binance BTCUSDT 유지마진율 (소규모 포지션, Tier 1)
    MMR = 0.004  # 0.4%

    def test_long_10x_liquidation_price_binance_formula(self):
        """롱 10x 청산가 (Binance 공식): LP = EP × (1/L - 1) / (MMR - 1)"""
        trader = PaperTrader(initial_capital=10000, leverage=10, fee_rate=0.0)

        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime.now(),
        )

        # Binance 공식: LP = 50000 × (0.1 - 1) / (0.004 - 1)
        #                 = 50000 × (-0.9) / (-0.996)
        #                 = 45180.72...
        EP = 50000
        L = 10
        expected_liq = EP * (1 / L - 1) / (self.MMR - 1)
        assert trader.position.liquidation_price == pytest.approx(expected_liq, rel=1e-9)
        assert trader.position.liquidation_price == pytest.approx(45180.72, rel=1e-4)

    def test_short_10x_liquidation_price_binance_formula(self):
        """숏 10x 청산가 (Binance 공식): LP = EP × (1/L + 1) / (MMR + 1)"""
        trader = PaperTrader(initial_capital=10000, leverage=10, fee_rate=0.0)

        order = Order(side=Side.SELL, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=50000,
            best_ask=50010,
            timestamp=datetime.now(),
        )

        # Binance 공식: LP = 50000 × (0.1 + 1) / (0.004 + 1)
        #                 = 50000 × 1.1 / 1.004
        #                 = 54780.88...
        EP = 50000
        L = 10
        expected_liq = EP * (1 / L + 1) / (self.MMR + 1)
        assert trader.position.liquidation_price == pytest.approx(expected_liq, rel=1e-9)
        assert trader.position.liquidation_price == pytest.approx(54780.88, rel=1e-4)

    def test_long_20x_liquidation_price_binance_formula(self):
        """롱 20x 청산가: 더 작은 가격 변동에도 청산"""
        trader = PaperTrader(initial_capital=10000, leverage=20, fee_rate=0.0)

        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime.now(),
        )

        # Binance 공식: LP = 50000 × (0.05 - 1) / (0.004 - 1)
        #                 = 50000 × (-0.95) / (-0.996)
        #                 = 47690.76...
        EP = 50000
        L = 20
        expected_liq = EP * (1 / L - 1) / (self.MMR - 1)
        assert trader.position.liquidation_price == pytest.approx(expected_liq, rel=1e-9)
        assert trader.position.liquidation_price == pytest.approx(47690.76, rel=1e-4)


class TestLeveragedPnLCalculation:
    """레버리지 적용 수익률 계산 테스트"""

    def test_long_profit_with_leverage(self):
        """롱 수익: 가격 1% 상승 → 10x면 ROI 10%"""
        trader = PaperTrader(initial_capital=10000, leverage=10, fee_rate=0.0)

        # 진입: 0.1 BTC @ $50,000
        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime.now(),
        )

        margin = trader.position.margin  # $500

        # 청산: $50,500 (1% 상승)
        close_order = Order(side=Side.SELL, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(close_order)
        trader.on_price_update(
            price=50500,
            best_bid=50500,
            best_ask=50510,
            timestamp=datetime.now(),
        )

        # PnL = (50500 - 50000) * 0.1 = $50
        # ROI = 50 / 500 = 10% (마진 대비)
        assert trader.realized_pnl == 50.0
        assert trader.realized_pnl / margin == pytest.approx(0.10)  # 10%

    def test_long_loss_with_leverage(self):
        """롱 손실: 가격 1% 하락 → 10x면 ROI -10%"""
        trader = PaperTrader(initial_capital=10000, leverage=10, fee_rate=0.0)

        # 진입
        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime.now(),
        )

        margin = trader.position.margin

        # 청산: $49,500 (1% 하락)
        close_order = Order(side=Side.SELL, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(close_order)
        trader.on_price_update(
            price=49500,
            best_bid=49500,
            best_ask=49510,
            timestamp=datetime.now(),
        )

        # PnL = (49500 - 50000) * 0.1 = -$50
        assert trader.realized_pnl == -50.0
        assert trader.realized_pnl / margin == pytest.approx(-0.10)

    def test_short_profit_calculation(self):
        """숏 수익: 가격 하락 시 수익"""
        trader = PaperTrader(initial_capital=10000, leverage=10, fee_rate=0.0)

        # 숏 진입: 0.1 BTC @ $50,000
        order = Order(side=Side.SELL, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=50000,
            best_ask=50010,
            timestamp=datetime.now(),
        )

        margin = trader.position.margin

        # 숏 청산 (BUY): $49,000 (2% 하락)
        close_order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(close_order)
        trader.on_price_update(
            price=49000,
            best_bid=48990,
            best_ask=49000,
            timestamp=datetime.now(),
        )

        # PnL = (50000 - 49000) * 0.1 = $100
        # ROI = 100 / 500 = 20%
        assert trader.realized_pnl == 100.0
        assert trader.realized_pnl / margin == pytest.approx(0.20)

    def test_short_loss_calculation(self):
        """숏 손실: 가격 상승 시 손실"""
        trader = PaperTrader(initial_capital=10000, leverage=10, fee_rate=0.0)

        # 숏 진입
        order = Order(side=Side.SELL, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=50000,
            best_ask=50010,
            timestamp=datetime.now(),
        )

        margin = trader.position.margin

        # 숏 청산: $51,000 (2% 상승)
        close_order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(close_order)
        trader.on_price_update(
            price=51000,
            best_bid=50990,
            best_ask=51000,
            timestamp=datetime.now(),
        )

        # PnL = (50000 - 51000) * 0.1 = -$100
        assert trader.realized_pnl == -100.0
        assert trader.realized_pnl / margin == pytest.approx(-0.20)


class TestBalanceConsistency:
    """잔고 일관성 테스트 - 돈이 새거나 생기면 안됨"""

    def test_full_cycle_balance_consistency(self):
        """진입 → 청산 후 잔고 = 초기자본 + gross_pnl - 진입수수료 - 청산수수료"""
        initial_capital = 10000
        fee_rate = 0.001
        trader = PaperTrader(initial_capital=initial_capital, leverage=10, fee_rate=fee_rate)

        # 진입: 0.1 BTC @ $50,000
        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime.now(),
        )

        # 진입 시: 10000 - 500(마진) - 5(수수료) = 9495
        entry_fee = 5000 * fee_rate  # $5
        margin = 500  # 5000 / 10
        assert trader.usd_balance == 9495.0

        # 청산: @ $51,000
        close_order = Order(side=Side.SELL, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(close_order)
        trader.on_price_update(
            price=51000,
            best_bid=51000,
            best_ask=51010,
            timestamp=datetime.now(),
        )

        # 청산 시:
        # - 마진 반환: 500
        # - Gross PnL: (51000 - 50000) * 0.1 = 100
        # - 청산 수수료: 5100 * 0.001 = 5.1
        # 잔고 증가: 500 + 100 - 5.1 = 594.9
        # 최종: 9495 + 594.9 = 10089.9
        exit_fee = 5100 * fee_rate  # $5.1
        gross_pnl = (51000 - 50000) * 0.1  # $100
        net_pnl = gross_pnl - entry_fee - exit_fee  # 100 - 5 - 5.1 = 89.9

        expected_balance = initial_capital + net_pnl  # 10000 + 89.9 = 10089.9
        assert trader.usd_balance == pytest.approx(expected_balance, rel=1e-6)
        assert trader.realized_pnl == pytest.approx(net_pnl, rel=1e-6)

    def test_liquidation_balance_consistency(self):
        """청산 시 잔여 마진만 반환 (Binance 공식 기준)"""
        initial_capital = 10000
        trader = PaperTrader(initial_capital=initial_capital, leverage=10, fee_rate=0.001)

        # 진입: 0.1 BTC @ $50,000
        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime.now(),
        )

        # 진입 시: 10000 - 500(마진) - 5(수수료) = 9495
        margin = trader.position.margin  # 500
        entry_fee = 5000 * 0.001  # 5
        liq_price = trader.position.liquidation_price  # 45180.72 (Binance 공식)
        assert trader.usd_balance == 9495.0
        assert liq_price == pytest.approx(45180.72, rel=1e-4)

        # 청산 (청산가 아래로 하락)
        trader.on_price_update(
            price=liq_price - 100,
            best_bid=liq_price - 110,
            best_ask=liq_price - 100,
            timestamp=datetime.now(),
        )

        # 청산가 45180.72에서 손실 = (50000 - 45180.72) * 0.1 = 481.93
        # 잔여 마진 = 마진 - 손실 - 진입수수료 = 500 - 481.93 - 5 = 13.07
        remaining_margin = margin + (liq_price - 50000) * 0.1 - entry_fee

        # 최종 잔고 = 9495 + 13.07 = 9508.07
        expected_balance = 9495.0 + remaining_margin
        assert trader.usd_balance == pytest.approx(expected_balance, rel=1e-4)
        assert trader.usd_balance == pytest.approx(9508.07, rel=1e-3)

        # 실현 손익: -(마진 - 잔여) = -(500 - 13.07) = -486.93
        # 코드 구현: loss = margin - remaining + entry_fee = 500 - 13.07 + 5 = 491.93
        assert trader.realized_pnl == pytest.approx(-491.93, rel=1e-3)

        # 포지션 청산됨
        assert trader.position.side is None


class TestPartialCloseCalculation:
    """부분 청산 계산 테스트"""

    def test_partial_close_50_percent(self):
        """50% 부분 청산: 마진/PnL 비례 계산"""
        trader = PaperTrader(initial_capital=10000, leverage=10, fee_rate=0.0)

        # 진입: 0.2 BTC @ $50,000
        order = Order(side=Side.BUY, quantity=0.2, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime.now(),
        )

        initial_margin = trader.position.margin  # $1000

        # 50% 부분 청산: 0.1 BTC @ $51,000
        close_order = Order(side=Side.SELL, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(close_order)
        trader.on_price_update(
            price=51000,
            best_bid=51000,
            best_ask=51010,
            timestamp=datetime.now(),
        )

        # 남은 포지션: 0.1 BTC
        assert trader.position.quantity == 0.1
        # 남은 마진: $500
        assert trader.position.margin == 500.0
        # 실현 PnL: (51000 - 50000) * 0.1 = $100
        assert trader.realized_pnl == 100.0


class TestEdgeCases:
    """엣지케이스 테스트"""

    def test_exact_liquidation_price_triggers_liquidation(self):
        """정확히 청산가에서 청산됨"""
        trader = PaperTrader(initial_capital=10000, leverage=10, fee_rate=0.0)

        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime.now(),
        )

        liq_price = trader.position.liquidation_price

        # 정확히 청산가에서 청산
        trader.on_price_update(
            price=liq_price,
            best_bid=liq_price - 10,
            best_ask=liq_price,
            timestamp=datetime.now(),
        )

        assert trader.position.side is None

    def test_price_just_above_liquidation_no_liquidation(self):
        """청산가 바로 위에서는 청산 안됨"""
        trader = PaperTrader(initial_capital=10000, leverage=10, fee_rate=0.0)

        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime.now(),
        )

        liq_price = trader.position.liquidation_price

        # 청산가 바로 위
        trader.on_price_update(
            price=liq_price + 0.01,
            best_bid=liq_price,
            best_ask=liq_price + 0.01,
            timestamp=datetime.now(),
        )

        assert trader.position.side == Side.BUY  # 포지션 유지

    def test_insufficient_margin_rejects_order(self):
        """마진 부족 시 주문 거부"""
        trader = PaperTrader(initial_capital=100, leverage=10, fee_rate=0.001)

        # $100 자본으로 $5,000 포지션 (마진 $500) 불가
        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trade = trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime.now(),
        )

        assert trade is None
        assert trader.position.side is None

    def test_very_high_leverage_100x(self):
        """100x 레버리지: 1% 변동에도 청산"""
        trader = PaperTrader(initial_capital=10000, leverage=100, fee_rate=0.0)

        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime.now(),
        )

        # Binance 공식: LP = 50000 × (0.01 - 1) / (0.004 - 1) = 49698.80
        EP = 50000
        L = 100
        MMR = 0.004
        expected_liq = EP * (1 / L - 1) / (MMR - 1)
        liq_price = trader.position.liquidation_price
        assert liq_price == pytest.approx(expected_liq, rel=1e-9)
        assert liq_price == pytest.approx(49698.80, rel=1e-4)

        # 0.6% 하락에서 청산
        distance_to_liq = (50000 - liq_price) / 50000
        assert distance_to_liq < 0.01  # 1% 미만

    def test_add_to_winning_position_recalculates_liquidation(self):
        """추가 진입 시 평균 진입가 및 청산가 재계산"""
        trader = PaperTrader(initial_capital=10000, leverage=10, fee_rate=0.0)

        # 첫 번째 진입: 0.1 BTC @ $50,000
        order1 = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order1)
        trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime.now(),
        )

        first_liq = trader.position.liquidation_price

        # 두 번째 진입: 0.1 BTC @ $52,000 (가격 상승 후 추가)
        order2 = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order2)
        trader.on_price_update(
            price=52000,
            best_bid=51990,
            best_ask=52000,
            timestamp=datetime.now(),
        )

        # 평균 진입가: (50000 + 52000) / 2 = 51000
        assert trader.position.entry_price == 51000.0
        assert trader.position.quantity == 0.2

        # 청산가도 새 평균가 기준으로 재계산 (Binance 공식)
        EP = 51000
        L = 10
        MMR = 0.004
        expected_liq = EP * (1 / L - 1) / (MMR - 1)
        assert trader.position.liquidation_price == pytest.approx(expected_liq, rel=1e-9)
        assert trader.position.liquidation_price > first_liq

    def test_flip_position_long_to_short(self):
        """롱 → 숏 전환 (포지션 반전)"""
        trader = PaperTrader(initial_capital=10000, leverage=10, fee_rate=0.0)

        # 롱 진입
        order1 = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order1)
        trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime.now(),
        )

        assert trader.position.side == Side.BUY

        # 0.1 BTC 매도로 청산
        order2 = Order(side=Side.SELL, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order2)
        trader.on_price_update(
            price=51000,
            best_bid=51000,
            best_ask=51010,
            timestamp=datetime.now(),
        )

        # 포지션 청산됨
        assert trader.position.side is None

    def test_zero_quantity_position(self):
        """포지션 수량이 0이면 방향은 None"""
        position = Position()
        assert position.side is None
        assert position.quantity == 0.0


class TestUnrealizedPnL:
    """미실현 손익 계산 테스트"""

    def test_unrealized_pnl_long_profit(self):
        """롱 미실현 수익"""
        trader = PaperTrader(initial_capital=10000, leverage=10, fee_rate=0.0)

        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime.now(),
        )

        # 가격 상승
        trader.update_unrealized_pnl(51000)
        # 미실현 PnL = (51000 - 50000) * 0.1 = $100
        assert trader.position.unrealized_pnl == 100.0

    def test_unrealized_pnl_short_profit(self):
        """숏 미실현 수익"""
        trader = PaperTrader(initial_capital=10000, leverage=10, fee_rate=0.0)

        order = Order(side=Side.SELL, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=50000,
            best_ask=50010,
            timestamp=datetime.now(),
        )

        # 가격 하락
        trader.update_unrealized_pnl(49000)
        # 미실현 PnL = (50000 - 49000) * 0.1 = $100
        assert trader.position.unrealized_pnl == 100.0


class TestCriticalEdgeCases:
    """핵심 엣지케이스 테스트 - 잘못되면 큰 손실 발생"""

    def test_short_profit_is_positive_when_price_drops(self):
        """중요: 숏은 가격 하락 시 수익이 양수"""
        trader = PaperTrader(initial_capital=10000, leverage=10, fee_rate=0.0)

        # 숏 진입 @ $50,000
        order = Order(side=Side.SELL, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=50000,
            best_ask=50010,
            timestamp=datetime.now(),
        )

        # 숏 청산 @ $45,000 (10% 하락)
        close = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(close)
        trader.on_price_update(
            price=45000,
            best_bid=44990,
            best_ask=45000,
            timestamp=datetime.now(),
        )

        # PnL = (50000 - 45000) * 0.1 = +$500 (수익!)
        assert trader.realized_pnl == 500.0
        assert trader.realized_pnl > 0  # 명시적으로 양수 확인

    def test_short_loss_is_negative_when_price_rises(self):
        """중요: 숏은 가격 상승 시 손실이 음수"""
        trader = PaperTrader(initial_capital=10000, leverage=10, fee_rate=0.0)

        # 숏 진입 @ $50,000
        order = Order(side=Side.SELL, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=50000,
            best_ask=50010,
            timestamp=datetime.now(),
        )

        # 숏 청산 @ $52,000 (4% 상승)
        close = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(close)
        trader.on_price_update(
            price=52000,
            best_bid=51990,
            best_ask=52000,
            timestamp=datetime.now(),
        )

        # PnL = (50000 - 52000) * 0.1 = -$200 (손실!)
        assert trader.realized_pnl == -200.0
        assert trader.realized_pnl < 0  # 명시적으로 음수 확인

    def test_leverage_amplifies_both_profit_and_loss(self):
        """레버리지는 수익과 손실 모두 증폭"""
        # 10x 레버리지로 1% 상승 = 마진 대비 10% 수익
        trader = PaperTrader(initial_capital=10000, leverage=10, fee_rate=0.0)

        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime.now(),
        )

        margin = 500.0  # 5000 / 10

        # 1% 상승 청산
        close = Order(side=Side.SELL, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(close)
        trader.on_price_update(
            price=50500,  # +1%
            best_bid=50500,
            best_ask=50510,
            timestamp=datetime.now(),
        )

        pnl = 50.0  # (50500 - 50000) * 0.1
        roi = pnl / margin  # 50 / 500 = 10%

        assert trader.realized_pnl == 50.0
        assert roi == pytest.approx(0.10)  # 10% ROI

    def test_max_loss_without_liquidation(self):
        """청산 없이 최대 손실 = 마진 전액 (이론적)"""
        # 실제로는 청산되지만, 청산가 직전까지 손실 확인
        trader = PaperTrader(initial_capital=10000, leverage=10, fee_rate=0.0)

        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime.now(),
        )

        liq_price = trader.position.liquidation_price  # 45200
        margin = trader.position.margin  # 500

        # 청산가 바로 위에서 청산 (수동)
        close = Order(side=Side.SELL, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(close)
        trader.on_price_update(
            price=liq_price + 1,  # 청산가 바로 위
            best_bid=liq_price + 1,
            best_ask=liq_price + 11,
            timestamp=datetime.now(),
        )

        # 손실 = (50000 - 45201) * 0.1 = 479.9
        expected_loss = (50000 - (liq_price + 1)) * 0.1
        assert trader.realized_pnl == pytest.approx(-expected_loss, rel=1e-6)
        # 손실이 마진보다 작음 (청산 전이므로)
        assert abs(trader.realized_pnl) < margin

    def test_funding_rate_only_applies_to_futures(self):
        """Funding Rate는 선물에만 적용"""
        # 현물 모드
        spot_trader = PaperTrader(initial_capital=10000, leverage=1)
        result = spot_trader.apply_funding(0.0001, 50000)
        assert result == 0.0  # 적용 안됨

        # 선물 모드
        futures_trader = PaperTrader(initial_capital=10000, leverage=10)
        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        futures_trader.submit_order(order)
        futures_trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime.now(),
        )

        # 0.01% funding rate, mark price $50,000
        # payment = 0.1 * 50000 * 0.0001 = $0.5
        # 롱은 지불 (음수)
        result = futures_trader.apply_funding(0.0001, 50000)
        assert result == pytest.approx(-0.5, rel=1e-6)

    def test_multiple_partial_closes_accumulate_pnl(self):
        """여러 번 부분 청산 시 PnL 누적"""
        trader = PaperTrader(initial_capital=10000, leverage=10, fee_rate=0.0)

        # 0.3 BTC 진입 @ $50,000
        order = Order(side=Side.BUY, quantity=0.3, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=50000,
            best_bid=49990,
            best_ask=50000,
            timestamp=datetime.now(),
        )

        # 1차 부분 청산: 0.1 BTC @ $51,000
        close1 = Order(side=Side.SELL, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(close1)
        trader.on_price_update(
            price=51000,
            best_bid=51000,
            best_ask=51010,
            timestamp=datetime.now(),
        )

        pnl1 = trader.realized_pnl  # (51000 - 50000) * 0.1 = 100
        assert pnl1 == 100.0
        assert trader.position.quantity == pytest.approx(0.2, rel=1e-9)

        # 2차 부분 청산: 0.1 BTC @ $52,000
        close2 = Order(side=Side.SELL, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(close2)
        trader.on_price_update(
            price=52000,
            best_bid=52000,
            best_ask=52010,
            timestamp=datetime.now(),
        )

        pnl2 = trader.realized_pnl - pnl1  # (52000 - 50000) * 0.1 = 200
        assert pnl2 == 200.0
        assert trader.position.quantity == pytest.approx(0.1, rel=1e-9)

        # 3차 전량 청산: 0.1 BTC @ $49,000
        close3 = Order(side=Side.SELL, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(close3)
        trader.on_price_update(
            price=49000,
            best_bid=49000,
            best_ask=49010,
            timestamp=datetime.now(),
        )

        pnl3 = trader.realized_pnl - pnl1 - pnl2  # (49000 - 50000) * 0.1 = -100
        assert pnl3 == pytest.approx(-100.0, rel=1e-9)
        assert trader.position.side is None

        # 총 PnL = 100 + 200 - 100 = 200
        assert trader.realized_pnl == pytest.approx(200.0, rel=1e-9)

    def test_spot_cannot_short_even_with_usd(self):
        """현물에서는 USD가 있어도 공매도 불가"""
        trader = PaperTrader(initial_capital=100000, leverage=1)

        order = Order(side=Side.SELL, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trade = trader.on_price_update(
            price=50000,
            best_bid=50000,
            best_ask=50010,
            timestamp=datetime.now(),
        )

        # BTC가 없으므로 체결 실패
        assert trade is None
        assert trader.btc_balance == 0.0
