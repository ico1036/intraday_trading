"""
PaperTrader Maker/Taker 수수료 테스트

Maker (Limit Order): 0.02%
Taker (Market Order): 0.05%

Binance 선물 기준: https://www.binance.com/en/fee/schedule
"""

from datetime import datetime

import pytest

from intraday.strategy import Side, OrderType, Order
from intraday.paper_trader import PaperTrader


class TestMakerTakerFeeRates:
    """Maker/Taker 수수료율 설정 테스트"""

    def test_default_maker_taker_rates(self):
        """기본 maker/taker 수수료율 확인"""
        trader = PaperTrader(initial_capital=10000.0)

        assert trader.maker_fee_rate == 0.0002  # 0.02%
        assert trader.taker_fee_rate == 0.0005  # 0.05%

    def test_custom_maker_taker_rates(self):
        """커스텀 maker/taker 수수료율"""
        trader = PaperTrader(
            initial_capital=10000.0,
            maker_fee_rate=0.0001,  # 0.01%
            taker_fee_rate=0.0003,  # 0.03%
        )

        assert trader.maker_fee_rate == 0.0001
        assert trader.taker_fee_rate == 0.0003

    def test_backward_compat_single_fee_rate(self):
        """하위 호환: fee_rate 지정 시 maker/taker 동일하게 설정"""
        trader = PaperTrader(
            initial_capital=10000.0,
            fee_rate=0.001,  # 0.1% (old style)
        )

        assert trader.fee_rate == 0.001
        assert trader.maker_fee_rate == 0.001
        assert trader.taker_fee_rate == 0.001


class TestMarketOrderTakerFee:
    """Market Order는 Taker 수수료 적용"""

    def test_market_buy_uses_taker_fee(self):
        """MARKET BUY는 taker 수수료 사용"""
        trader = PaperTrader(
            initial_capital=10000.0,
            maker_fee_rate=0.0002,
            taker_fee_rate=0.0005,
        )

        order = Order(
            side=Side.BUY,
            quantity=0.01,
            order_type=OrderType.MARKET,
        )

        trader.submit_order(order)
        trade = trader.on_price_update(
            price=100000.0,
            best_bid=99990.0,
            best_ask=100000.0,
            timestamp=datetime.now(),
        )

        # 수수료: 100000 * 0.01 * 0.0005 = 0.5 (taker)
        assert trade is not None
        assert trade.fee == pytest.approx(0.5, rel=0.01)

    def test_market_sell_uses_taker_fee(self):
        """MARKET SELL는 taker 수수료 사용"""
        trader = PaperTrader(
            initial_capital=10000.0,
            maker_fee_rate=0.0002,
            taker_fee_rate=0.0005,
        )

        # 먼저 포지션 진입
        buy_order = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(buy_order)
        trader.on_price_update(
            price=100000.0,
            best_bid=99990.0,
            best_ask=100000.0,
            timestamp=datetime.now(),
        )

        # 매도
        sell_order = Order(side=Side.SELL, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(sell_order)
        trade = trader.on_price_update(
            price=101000.0,
            best_bid=101000.0,
            best_ask=101010.0,
            timestamp=datetime.now(),
        )

        # 수수료: 101000 * 0.01 * 0.0005 = 0.505 (taker)
        assert trade is not None
        assert trade.fee == pytest.approx(0.505, rel=0.01)


class TestLimitOrderMakerFee:
    """Limit Order는 Maker 수수료 적용"""

    def test_limit_buy_uses_maker_fee(self):
        """LIMIT BUY는 maker 수수료 사용"""
        trader = PaperTrader(
            initial_capital=10000.0,
            maker_fee_rate=0.0002,
            taker_fee_rate=0.0005,
        )

        order = Order(
            side=Side.BUY,
            quantity=0.01,
            order_type=OrderType.LIMIT,
            limit_price=99000.0,
        )

        trader.submit_order(order)

        # 가격이 limit_price 이하로 떨어짐 → 체결
        trade = trader.on_price_update(
            price=98900.0,
            best_bid=98890.0,
            best_ask=98900.0,
            timestamp=datetime.now(),
        )

        # 수수료: 99000 * 0.01 * 0.0002 = 0.198 (maker)
        assert trade is not None
        assert trade.price == 99000.0
        assert trade.fee == pytest.approx(0.198, rel=0.01)

    def test_limit_sell_uses_maker_fee(self):
        """LIMIT SELL는 maker 수수료 사용"""
        trader = PaperTrader(
            initial_capital=10000.0,
            maker_fee_rate=0.0002,
            taker_fee_rate=0.0005,
        )

        # 먼저 포지션 진입 (market order)
        buy_order = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(buy_order)
        trader.on_price_update(
            price=100000.0,
            best_bid=99990.0,
            best_ask=100000.0,
            timestamp=datetime.now(),
        )

        # 매도 대기 (limit order)
        sell_order = Order(
            side=Side.SELL,
            quantity=0.01,
            order_type=OrderType.LIMIT,
            limit_price=101000.0,
        )

        trader.submit_order(sell_order)

        # 가격이 limit_price 이상으로 오름 → 체결
        trade = trader.on_price_update(
            price=101100.0,
            best_bid=101090.0,
            best_ask=101100.0,
            timestamp=datetime.now(),
        )

        # 수수료: 101000 * 0.01 * 0.0002 = 0.202 (maker)
        assert trade is not None
        assert trade.price == 101000.0
        assert trade.fee == pytest.approx(0.202, rel=0.01)


class TestMakerTakerFeeComparison:
    """Maker vs Taker 수수료 비교 테스트"""

    def test_maker_fee_is_lower_than_taker(self):
        """Maker 수수료가 Taker보다 낮음 확인"""
        trader = PaperTrader(
            initial_capital=10000.0,
            maker_fee_rate=0.0002,  # 0.02%
            taker_fee_rate=0.0005,  # 0.05%
        )

        # Taker 수수료가 2.5배 높음
        assert trader.taker_fee_rate / trader.maker_fee_rate == 2.5

    def test_round_trip_fee_difference(self):
        """왕복 거래 시 Maker vs Taker 수수료 차이"""
        # Taker only (Market Order 전용)
        taker_trader = PaperTrader(
            initial_capital=10000.0,
            maker_fee_rate=0.0005,  # force taker rate
            taker_fee_rate=0.0005,
        )

        # Maker only (Limit Order 전용)
        maker_trader = PaperTrader(
            initial_capital=10000.0,
            maker_fee_rate=0.0002,
            taker_fee_rate=0.0002,  # force maker rate
        )

        # 동일한 거래 실행 (100000 → 101000)
        for trader in [taker_trader, maker_trader]:
            buy = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
            trader.submit_order(buy)
            trader.on_price_update(
                price=100000.0,
                best_bid=99990.0,
                best_ask=100000.0,
                timestamp=datetime.now(),
            )

            sell = Order(side=Side.SELL, quantity=0.01, order_type=OrderType.MARKET)
            trader.submit_order(sell)
            trader.on_price_update(
                price=101000.0,
                best_bid=101000.0,
                best_ask=101010.0,
                timestamp=datetime.now(),
            )

        # Taker 총 수수료: (100000 + 101000) * 0.01 * 0.0005 = 1.005
        taker_fees = sum(t.fee for t in taker_trader.trades)
        assert taker_fees == pytest.approx(1.005, rel=0.01)

        # Maker 총 수수료: (100000 + 101000) * 0.01 * 0.0002 = 0.402
        maker_fees = sum(t.fee for t in maker_trader.trades)
        assert maker_fees == pytest.approx(0.402, rel=0.01)

        # Maker가 2.5배 저렴
        assert taker_fees / maker_fees == pytest.approx(2.5, rel=0.01)


class TestMixedMakerTakerOrders:
    """Maker/Taker 혼합 주문 테스트"""

    def test_market_entry_limit_exit(self):
        """Market으로 진입, Limit으로 청산"""
        trader = PaperTrader(
            initial_capital=10000.0,
            maker_fee_rate=0.0002,
            taker_fee_rate=0.0005,
        )

        # Market BUY (taker)
        buy_order = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(buy_order)
        entry_trade = trader.on_price_update(
            price=100000.0,
            best_bid=99990.0,
            best_ask=100000.0,
            timestamp=datetime.now(),
        )

        # 진입 수수료: 100000 * 0.01 * 0.0005 = 0.5 (taker)
        assert entry_trade.fee == pytest.approx(0.5, rel=0.01)

        # Limit SELL (maker)
        sell_order = Order(
            side=Side.SELL,
            quantity=0.01,
            order_type=OrderType.LIMIT,
            limit_price=101000.0,
        )
        trader.submit_order(sell_order)
        exit_trade = trader.on_price_update(
            price=101100.0,
            best_bid=101090.0,
            best_ask=101100.0,
            timestamp=datetime.now(),
        )

        # 청산 수수료: 101000 * 0.01 * 0.0002 = 0.202 (maker)
        assert exit_trade.fee == pytest.approx(0.202, rel=0.01)

        # 총 수수료: 0.5 + 0.202 = 0.702
        total_fees = sum(t.fee for t in trader.trades)
        assert total_fees == pytest.approx(0.702, rel=0.01)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
