"""
PnL 계산 검증 테스트

목적: 백테스트 시스템의 PnL 계산이 정확한지 검증
방법: 단순한 "무조건 매수 → 다음 바에 매도" 전략으로 수동 계산과 비교

핵심 검증 항목:
1. 수수료 계산 정확성
2. PnL = Gross PnL - Entry Fee - Exit Fee
3. 가격 상승 시 양수 PnL, 하락 시 음수 PnL
"""

from datetime import datetime, timezone, timedelta
from decimal import Decimal
import pytest

from intraday.paper_trader import PaperTrader
from intraday.strategy import Order, Side, OrderType


class TestPaperTraderPnLCalculation:
    """PaperTrader의 PnL 계산 정확성 검증"""

    def test_fee_calculation(self):
        """수수료 계산 검증: fee = notional * fee_rate"""
        trader = PaperTrader(initial_capital=10000, fee_rate=0.001)  # 0.1%

        # 주문: 0.01 BTC @ $50,000 = $500 notional
        order = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(order)

        # 체결
        ts = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        trade = trader.on_price_update(
            price=50000, best_bid=49990, best_ask=50000, timestamp=ts
        )

        assert trade is not None
        # fee = 500 * 0.001 = 0.5
        assert trade.fee == pytest.approx(0.5, rel=1e-9)

    def test_pnl_positive_when_price_goes_up(self):
        """가격 상승 시 양수 PnL"""
        fee_rate = 0.001  # 0.1%
        trader = PaperTrader(initial_capital=10000, fee_rate=fee_rate)

        # 1. BUY @ $50,000
        buy_order = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(buy_order)
        ts1 = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        buy_trade = trader.on_price_update(
            price=50000, best_bid=49990, best_ask=50000, timestamp=ts1
        )
        assert buy_trade is not None

        # 2. SELL @ $51,000 (가격 2% 상승)
        sell_order = Order(side=Side.SELL, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(sell_order)
        ts2 = datetime(2024, 1, 1, 12, 5, tzinfo=timezone.utc)
        sell_trade = trader.on_price_update(
            price=51000, best_bid=51000, best_ask=51010, timestamp=ts2
        )
        assert sell_trade is not None

        # 수동 계산
        # Entry: 50000 * 0.01 = 500, fee = 0.5
        # Exit:  51000 * 0.01 = 510, fee = 0.51
        # Gross PnL = 510 - 500 = 10
        # Net PnL = 10 - 0.5 - 0.51 = 8.99
        expected_gross_pnl = (51000 - 50000) * 0.01  # = 10
        expected_entry_fee = 50000 * 0.01 * fee_rate  # = 0.5
        expected_exit_fee = 51000 * 0.01 * fee_rate   # = 0.51
        expected_net_pnl = expected_gross_pnl - expected_entry_fee - expected_exit_fee

        assert sell_trade.pnl == pytest.approx(expected_net_pnl, rel=1e-9)
        assert sell_trade.pnl > 0, "가격 상승 시 PnL은 양수여야 함"

    def test_pnl_negative_when_price_goes_down(self):
        """가격 하락 시 음수 PnL"""
        fee_rate = 0.001  # 0.1%
        trader = PaperTrader(initial_capital=10000, fee_rate=fee_rate)

        # 1. BUY @ $50,000
        buy_order = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(buy_order)
        ts1 = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        buy_trade = trader.on_price_update(
            price=50000, best_bid=49990, best_ask=50000, timestamp=ts1
        )
        assert buy_trade is not None

        # 2. SELL @ $49,000 (가격 2% 하락)
        sell_order = Order(side=Side.SELL, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(sell_order)
        ts2 = datetime(2024, 1, 1, 12, 5, tzinfo=timezone.utc)
        sell_trade = trader.on_price_update(
            price=49000, best_bid=49000, best_ask=49010, timestamp=ts2
        )
        assert sell_trade is not None

        # 수동 계산
        # Gross PnL = (49000 - 50000) * 0.01 = -10
        # Entry fee = 500 * 0.001 = 0.5
        # Exit fee = 490 * 0.001 = 0.49
        # Net PnL = -10 - 0.5 - 0.49 = -10.99
        expected_gross_pnl = (49000 - 50000) * 0.01
        expected_entry_fee = 50000 * 0.01 * fee_rate
        expected_exit_fee = 49000 * 0.01 * fee_rate
        expected_net_pnl = expected_gross_pnl - expected_entry_fee - expected_exit_fee

        assert sell_trade.pnl == pytest.approx(expected_net_pnl, rel=1e-9)
        assert sell_trade.pnl < 0, "가격 하락 시 PnL은 음수여야 함"

    def test_breakeven_requires_price_increase_to_cover_fees(self):
        """손익분기점: 수수료를 커버하려면 가격이 올라야 함"""
        fee_rate = 0.001  # 0.1%
        trader = PaperTrader(initial_capital=10000, fee_rate=fee_rate)

        entry_price = 50000
        quantity = 0.01

        # BUY
        buy_order = Order(side=Side.BUY, quantity=quantity, order_type=OrderType.MARKET)
        trader.submit_order(buy_order)
        ts1 = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        trader.on_price_update(price=entry_price, best_bid=49990, best_ask=entry_price, timestamp=ts1)

        # 손익분기점 계산:
        # 0 = gross_pnl - entry_fee - exit_fee
        # 0 = (exit_price - entry_price) * qty - entry_notional * fee_rate - exit_notional * fee_rate
        # exit_price * qty - entry_price * qty = entry_price * qty * fee_rate + exit_price * qty * fee_rate
        # exit_price * qty * (1 - fee_rate) = entry_price * qty * (1 + fee_rate)
        # exit_price = entry_price * (1 + fee_rate) / (1 - fee_rate)
        breakeven_price = entry_price * (1 + fee_rate) / (1 - fee_rate)

        # 손익분기점 가격에서 매도
        sell_order = Order(side=Side.SELL, quantity=quantity, order_type=OrderType.MARKET)
        trader.submit_order(sell_order)
        ts2 = datetime(2024, 1, 1, 12, 5, tzinfo=timezone.utc)
        sell_trade = trader.on_price_update(
            price=breakeven_price, best_bid=breakeven_price, best_ask=breakeven_price + 10, timestamp=ts2
        )

        assert sell_trade is not None
        # 손익분기점에서 PnL ≈ 0 (부동소수점 오차 허용)
        assert abs(sell_trade.pnl) < 0.01, f"손익분기점에서 PnL은 0에 가까워야 함, got {sell_trade.pnl}"

    def test_fee_impact_on_frequent_trading(self):
        """빈번한 거래 시 수수료 누적 영향"""
        fee_rate = 0.001  # 0.1%
        trader = PaperTrader(initial_capital=10000, fee_rate=fee_rate)

        price = 50000
        quantity = 0.01
        num_trades = 10  # 10번 왕복

        ts = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

        for i in range(num_trades):
            # BUY
            trader.submit_order(Order(side=Side.BUY, quantity=quantity, order_type=OrderType.MARKET))
            trader.on_price_update(price=price, best_bid=price-10, best_ask=price, timestamp=ts)
            ts += timedelta(minutes=1)

            # SELL (같은 가격에 - 가격 변동 없음)
            trader.submit_order(Order(side=Side.SELL, quantity=quantity, order_type=OrderType.MARKET))
            trader.on_price_update(price=price, best_bid=price, best_ask=price+10, timestamp=ts)
            ts += timedelta(minutes=1)

        # 가격 변동 없이 10번 왕복 = 20번 수수료 부과
        # 매 거래당 수수료: 50000 * 0.01 * 0.001 = 0.5
        # 총 수수료: 0.5 * 20 = 10
        # 총 PnL: -10 (가격 변동 없이 수수료만 손실)
        total_fees = price * quantity * fee_rate * num_trades * 2

        assert trader.realized_pnl == pytest.approx(-total_fees, rel=1e-6)
        assert trader.realized_pnl < 0, "가격 변동 없이 거래하면 수수료로 인해 손실"


class TestFeeRateImpact:
    """수수료율에 따른 손익 분석"""

    def test_high_fee_makes_small_gains_unprofitable(self):
        """높은 수수료율은 작은 이익을 손실로 만듦"""
        high_fee_rate = 0.001  # 0.1% = 왕복 0.2%
        trader = PaperTrader(initial_capital=10000, fee_rate=high_fee_rate)

        entry_price = 50000
        # 0.1% 가격 상승 (50 달러)
        exit_price = entry_price * 1.001  # 50050
        quantity = 0.01

        # BUY
        trader.submit_order(Order(side=Side.BUY, quantity=quantity, order_type=OrderType.MARKET))
        ts1 = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        trader.on_price_update(price=entry_price, best_bid=entry_price-10, best_ask=entry_price, timestamp=ts1)

        # SELL
        trader.submit_order(Order(side=Side.SELL, quantity=quantity, order_type=OrderType.MARKET))
        ts2 = datetime(2024, 1, 1, 12, 5, tzinfo=timezone.utc)
        sell_trade = trader.on_price_update(
            price=exit_price, best_bid=exit_price, best_ask=exit_price+10, timestamp=ts2
        )

        # Gross PnL = (50050 - 50000) * 0.01 = 0.50
        # Entry fee = 500 * 0.001 = 0.50
        # Exit fee ≈ 500.5 * 0.001 ≈ 0.5005
        # Net PnL ≈ 0.50 - 0.50 - 0.5005 ≈ -0.5005

        assert sell_trade.pnl < 0, "0.1% 이익은 0.2% 왕복 수수료에 먹힘"

    def test_realistic_futures_fee_rate(self):
        """실제 선물 수수료율 (0.04%)로 같은 테스트"""
        low_fee_rate = 0.0004  # 0.04% = 바이낸스 선물 테이커
        trader = PaperTrader(initial_capital=10000, fee_rate=low_fee_rate)

        entry_price = 50000
        exit_price = entry_price * 1.001  # 0.1% 상승
        quantity = 0.01

        # BUY
        trader.submit_order(Order(side=Side.BUY, quantity=quantity, order_type=OrderType.MARKET))
        ts1 = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
        trader.on_price_update(price=entry_price, best_bid=entry_price-10, best_ask=entry_price, timestamp=ts1)

        # SELL
        trader.submit_order(Order(side=Side.SELL, quantity=quantity, order_type=OrderType.MARKET))
        ts2 = datetime(2024, 1, 1, 12, 5, tzinfo=timezone.utc)
        sell_trade = trader.on_price_update(
            price=exit_price, best_bid=exit_price, best_ask=exit_price+10, timestamp=ts2
        )

        # Gross PnL = 0.50
        # Entry fee = 500 * 0.0004 = 0.20
        # Exit fee ≈ 500.5 * 0.0004 ≈ 0.2002
        # Net PnL ≈ 0.50 - 0.20 - 0.2002 ≈ 0.0998

        assert sell_trade.pnl > 0, "0.04% 수수료로는 0.1% 이익이 양수"

    def test_minimum_profitable_move_by_fee_rate(self):
        """수수료율별 최소 수익 가격 변동률 계산"""
        test_cases = [
            (0.001, "0.1%"),   # 현재 기본값
            (0.0004, "0.04%"), # 바이낸스 선물 테이커
            (0.0002, "0.02%"), # 바이낸스 선물 메이커
        ]

        for fee_rate, label in test_cases:
            trader = PaperTrader(initial_capital=10000, fee_rate=fee_rate)

            entry_price = 50000
            quantity = 0.01

            # 손익분기점 계산
            breakeven_price = entry_price * (1 + fee_rate) / (1 - fee_rate)
            breakeven_move = (breakeven_price / entry_price - 1) * 100  # %

            # 손익분기점 바로 위에서 거래
            exit_price = breakeven_price * 1.0001  # 0.01% 추가 상승

            trader.submit_order(Order(side=Side.BUY, quantity=quantity, order_type=OrderType.MARKET))
            ts1 = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
            trader.on_price_update(price=entry_price, best_bid=entry_price-10, best_ask=entry_price, timestamp=ts1)

            trader.submit_order(Order(side=Side.SELL, quantity=quantity, order_type=OrderType.MARKET))
            ts2 = datetime(2024, 1, 1, 12, 5, tzinfo=timezone.utc)
            sell_trade = trader.on_price_update(
                price=exit_price, best_bid=exit_price, best_ask=exit_price+10, timestamp=ts2
            )

            assert sell_trade.pnl > 0, f"손익분기점 위에서는 수익이어야 함 (fee_rate={label})"
            print(f"[{label}] 손익분기점: {breakeven_move:.4f}%")


class TestTickRunnerFeeConfiguration:
    """TickBacktestRunner의 수수료 설정 검증"""

    def test_tick_runner_default_fee_rate(self):
        """TickBacktestRunner 기본 수수료율 확인"""
        from intraday.backtest.tick_runner import TickBacktestRunner
        from intraday.strategies.base import StrategyBase, MarketState
        from intraday.data import TickDataLoader
        from pathlib import Path

        # 기본값 확인 (실제 러너 생성 없이 시그니처에서)
        import inspect
        sig = inspect.signature(TickBacktestRunner.__init__)

        fee_rate_param = sig.parameters.get('fee_rate')
        if fee_rate_param is not None:
            default_fee = fee_rate_param.default
            print(f"TickBacktestRunner 기본 fee_rate: {default_fee}")

            # 0.1%는 선물 기준 너무 높음 (바이낸스 테이커 0.04%)
            if default_fee == 0.001:
                print("⚠️ 경고: 기본 수수료율 0.1%는 선물 거래 기준 2.5배 높음")
                print("   권장: 0.0004 (바이낸스 선물 테이커)")


class TestPnLAccumulation:
    """PnL 누적 계산 검증"""

    def test_realized_pnl_accumulates_correctly(self):
        """realized_pnl이 정확히 누적되는지 검증"""
        fee_rate = 0.0004  # 0.04%
        trader = PaperTrader(initial_capital=10000, fee_rate=fee_rate)

        trades_data = [
            # (entry_price, exit_price) - 각각 독립적인 거래
            (50000, 50100),  # +$1 gross
            (50000, 49900),  # -$1 gross
            (50000, 50200),  # +$2 gross
        ]

        quantity = 0.01
        ts = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

        expected_total_pnl = 0.0

        for entry_price, exit_price in trades_data:
            # BUY
            trader.submit_order(Order(side=Side.BUY, quantity=quantity, order_type=OrderType.MARKET))
            trader.on_price_update(price=entry_price, best_bid=entry_price-10, best_ask=entry_price, timestamp=ts)
            ts += timedelta(minutes=1)

            # SELL
            trader.submit_order(Order(side=Side.SELL, quantity=quantity, order_type=OrderType.MARKET))
            sell_trade = trader.on_price_update(
                price=exit_price, best_bid=exit_price, best_ask=exit_price+10, timestamp=ts
            )
            ts += timedelta(minutes=1)

            # 수동 계산
            gross_pnl = (exit_price - entry_price) * quantity
            entry_fee = entry_price * quantity * fee_rate
            exit_fee = exit_price * quantity * fee_rate
            net_pnl = gross_pnl - entry_fee - exit_fee
            expected_total_pnl += net_pnl

        assert trader.realized_pnl == pytest.approx(expected_total_pnl, rel=1e-6)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
