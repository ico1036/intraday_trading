"""
PaperTrader 잔고 관리 테스트

유저 입장: "내 돈 안에서 거래해야지!"
- USD 잔고 체크
- BTC 잔고 체크
- 공매도 방지
"""

from datetime import datetime

import pytest

from intraday.strategy import Side, OrderType, Order
from intraday.paper_trader import PaperTrader


class TestPaperTraderBalanceProperties:
    """잔고 조회 인터페이스 테스트"""
    
    def test_initial_usd_balance(self):
        """초기 USD 잔고 확인"""
        trader = PaperTrader(initial_capital=10000.0)
        
        assert trader.usd_balance == 10000.0
    
    def test_initial_btc_balance_is_zero(self):
        """초기 BTC 잔고는 0"""
        trader = PaperTrader(initial_capital=10000.0)
        
        assert trader.btc_balance == 0.0
    
    def test_balance_after_buy(self):
        """매수 후 잔고 확인"""
        trader = PaperTrader(initial_capital=10000.0, fee_rate=0.001)
        
        # 100000 가격에 0.01 BTC 매수
        # 비용: 100000 * 0.01 = 1000 + 수수료 1
        order = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(order)
        trader.on_price_update(
            price=100000.0,
            best_bid=99990.0,
            best_ask=100000.0,
            timestamp=datetime.now(),
        )
        
        # USD 잔고: 10000 - 1000 - 1 = 8999
        assert trader.usd_balance == pytest.approx(8999.0, rel=0.01)
        # BTC 잔고: 0.01
        assert trader.btc_balance == pytest.approx(0.01, rel=0.01)
    
    def test_balance_after_sell(self):
        """매도 후 잔고 확인"""
        trader = PaperTrader(initial_capital=10000.0, fee_rate=0.001)
        
        # 먼저 매수
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
        trader.on_price_update(
            price=101000.0,
            best_bid=101000.0,
            best_ask=101010.0,
            timestamp=datetime.now(),
        )
        
        # BTC 잔고: 0
        assert trader.btc_balance == 0.0
        # USD 잔고: 8999 + 1010 - 1.01 = 10007.99 (대략)
        assert trader.usd_balance > 10000.0  # 수익


class TestPaperTraderInsufficientBalance:
    """잔고 부족 체크 테스트"""
    
    def test_buy_fails_when_insufficient_usd(self):
        """
        시나리오: USD 잔고 부족 시 매수 실패
        
        유저 입장: "돈 없으면 못 사지!"
        """
        trader = PaperTrader(initial_capital=100.0)  # 100 USD만 보유
        
        # 100000 가격에 0.01 BTC 매수 시도 (1000 USD 필요)
        order = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(order)
        
        # 잔고 부족으로 체결 안 됨
        trade = trader.on_price_update(
            price=100000.0,
            best_bid=99990.0,
            best_ask=100000.0,
            timestamp=datetime.now(),
        )
        
        # 체결 실패
        assert trade is None
        # 잔고 변화 없음
        assert trader.usd_balance == 100.0
        assert trader.btc_balance == 0.0
        # 주문은 대기열에서 제거됨 (실패)
        assert len(trader.pending_orders) == 0
    
    def test_sell_fails_when_no_btc(self):
        """
        시나리오: BTC 없이 매도 시도 (공매도 방지)
        
        유저 입장: "없는 걸 어떻게 팔아!"
        """
        trader = PaperTrader(initial_capital=10000.0)
        
        # BTC 없이 매도 시도
        order = Order(side=Side.SELL, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(order)
        
        trade = trader.on_price_update(
            price=100000.0,
            best_bid=100000.0,
            best_ask=100010.0,
            timestamp=datetime.now(),
        )
        
        # 체결 실패 (공매도 방지)
        assert trade is None
        # 잔고 변화 없음
        assert trader.usd_balance == 10000.0
        assert trader.btc_balance == 0.0
    
    def test_sell_fails_when_insufficient_btc(self):
        """
        시나리오: 보유 BTC보다 많이 매도 시도
        
        유저 입장: "있는 것보다 더 팔 수 없지!"
        """
        trader = PaperTrader(initial_capital=10000.0, fee_rate=0.001)
        
        # 0.01 BTC 매수
        buy_order = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(buy_order)
        trader.on_price_update(
            price=100000.0,
            best_bid=99990.0,
            best_ask=100000.0,
            timestamp=datetime.now(),
        )
        
        assert trader.btc_balance == pytest.approx(0.01, rel=0.01)
        
        # 0.02 BTC 매도 시도 (보유량 초과)
        sell_order = Order(side=Side.SELL, quantity=0.02, order_type=OrderType.MARKET)
        trader.submit_order(sell_order)
        
        trade = trader.on_price_update(
            price=101000.0,
            best_bid=101000.0,
            best_ask=101010.0,
            timestamp=datetime.now(),
        )
        
        # 체결 실패
        assert trade is None
        # 잔고 변화 없음
        assert trader.btc_balance == pytest.approx(0.01, rel=0.01)


class TestPaperTraderLimitOrderBalance:
    """LIMIT 주문 잔고 체크 테스트"""
    
    def test_limit_buy_fails_when_insufficient_usd(self):
        """LIMIT BUY도 잔고 체크"""
        trader = PaperTrader(initial_capital=100.0)
        
        order = Order(
            side=Side.BUY,
            quantity=0.01,
            order_type=OrderType.LIMIT,
            limit_price=99000.0,
        )
        trader.submit_order(order)
        
        # 가격이 limit_price 이하로 떨어져도 잔고 부족으로 실패
        trade = trader.on_price_update(
            price=98000.0,
            best_bid=97990.0,
            best_ask=98000.0,
            timestamp=datetime.now(),
        )
        
        assert trade is None
        assert trader.usd_balance == 100.0
    
    def test_limit_sell_fails_when_no_btc(self):
        """LIMIT SELL도 잔고 체크"""
        trader = PaperTrader(initial_capital=10000.0)
        
        order = Order(
            side=Side.SELL,
            quantity=0.01,
            order_type=OrderType.LIMIT,
            limit_price=101000.0,
        )
        trader.submit_order(order)
        
        # 가격이 limit_price 이상으로 올라도 BTC 없으면 실패
        trade = trader.on_price_update(
            price=102000.0,
            best_bid=102000.0,
            best_ask=102010.0,
            timestamp=datetime.now(),
        )
        
        assert trade is None
        assert trader.btc_balance == 0.0

