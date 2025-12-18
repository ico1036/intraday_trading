"""
PaperTrader 주문 큐 테스트

여러 주문 관리, TTL, 취소 기능 검증
"""

from datetime import datetime, timedelta

import pytest

from intraday.strategy import Side, OrderType, Order
from intraday.paper_trader import PaperTrader


class TestPaperTraderOrderQueue:
    """주문 큐 테스트"""
    
    def test_multiple_orders_in_queue(self):
        """여러 주문을 큐에 추가"""
        trader = PaperTrader(initial_capital=10000.0)
        
        order1 = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.LIMIT, limit_price=99000.0)
        order2 = Order(side=Side.BUY, quantity=0.02, order_type=OrderType.LIMIT, limit_price=98000.0)
        
        trader.submit_order(order1)
        trader.submit_order(order2)
        
        assert len(trader.pending_orders) == 2
    
    def test_first_order_filled_first(self):
        """FIFO: 먼저 제출한 주문이 먼저 체결"""
        trader = PaperTrader(initial_capital=10000.0)
        
        order1 = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.LIMIT, limit_price=99000.0)
        order2 = Order(side=Side.BUY, quantity=0.02, order_type=OrderType.LIMIT, limit_price=98000.0)
        
        trader.submit_order(order1)
        trader.submit_order(order2)
        
        # 가격이 99000 이하로 떨어지면 order1만 체결
        trade = trader.on_price_update(
            price=98500.0,
            best_bid=98490.0,
            best_ask=98500.0,
            timestamp=datetime.now(),
        )
        
        assert trade is not None
        assert trade.quantity == 0.01  # order1 체결
        assert len(trader.pending_orders) == 1  # order2 남음
    
    def test_multiple_orders_filled_same_update(self):
        """한 번의 가격 업데이트에서 여러 주문 체결 가능"""
        trader = PaperTrader(initial_capital=10000.0)
        
        order1 = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.LIMIT, limit_price=99000.0)
        order2 = Order(side=Side.BUY, quantity=0.02, order_type=OrderType.LIMIT, limit_price=98000.0)
        
        trader.submit_order(order1)
        trader.submit_order(order2)
        
        # 가격이 97000으로 떨어지면 둘 다 체결 가능
        trades = trader.on_price_update_all(
            price=97000.0,
            best_bid=96990.0,
            best_ask=97000.0,
            timestamp=datetime.now(),
        )
        
        assert len(trades) == 2
        assert len(trader.pending_orders) == 0
    
    def test_cancel_order_by_id(self):
        """주문 ID로 취소"""
        trader = PaperTrader(initial_capital=10000.0)
        
        order1 = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.LIMIT, limit_price=99000.0)
        
        order_id = trader.submit_order(order1)
        
        assert len(trader.pending_orders) == 1
        
        cancelled = trader.cancel_order(order_id)
        
        assert cancelled is True
        assert len(trader.pending_orders) == 0
    
    def test_cancel_all_orders(self):
        """모든 주문 취소"""
        trader = PaperTrader(initial_capital=10000.0)
        
        order1 = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.LIMIT, limit_price=99000.0)
        order2 = Order(side=Side.SELL, quantity=0.02, order_type=OrderType.LIMIT, limit_price=101000.0)
        
        trader.submit_order(order1)
        trader.submit_order(order2)
        
        assert len(trader.pending_orders) == 2
        
        trader.cancel_all_orders()
        
        assert len(trader.pending_orders) == 0
    
    def test_cancel_orders_by_side(self):
        """방향별 주문 취소"""
        trader = PaperTrader(initial_capital=10000.0)
        
        order1 = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.LIMIT, limit_price=99000.0)
        order2 = Order(side=Side.SELL, quantity=0.02, order_type=OrderType.LIMIT, limit_price=101000.0)
        order3 = Order(side=Side.BUY, quantity=0.03, order_type=OrderType.LIMIT, limit_price=98000.0)
        
        trader.submit_order(order1)
        trader.submit_order(order2)
        trader.submit_order(order3)
        
        trader.cancel_orders_by_side(Side.BUY)
        
        assert len(trader.pending_orders) == 1
        assert trader.pending_orders[0].order.side == Side.SELL


class TestPaperTraderOrderTTL:
    """주문 TTL (Time-To-Live) 테스트"""
    
    def test_order_expires_after_ttl(self):
        """TTL 경과 후 주문 만료"""
        trader = PaperTrader(initial_capital=10000.0)
        
        order = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.LIMIT, limit_price=99000.0)
        
        # 5초 TTL
        trader.submit_order(order, ttl_seconds=5)
        
        assert len(trader.pending_orders) == 1
        
        # 시간 경과 시뮬레이션
        trader.expire_orders(current_time=datetime.now() + timedelta(seconds=6))
        
        assert len(trader.pending_orders) == 0
    
    def test_order_not_expired_before_ttl(self):
        """TTL 이전에는 주문 유효"""
        trader = PaperTrader(initial_capital=10000.0)
        
        order = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.LIMIT, limit_price=99000.0)
        
        trader.submit_order(order, ttl_seconds=10)
        
        # 5초 후 (TTL 이전)
        trader.expire_orders(current_time=datetime.now() + timedelta(seconds=5))
        
        assert len(trader.pending_orders) == 1
    
    def test_order_without_ttl_never_expires(self):
        """TTL 없는 주문은 만료되지 않음"""
        trader = PaperTrader(initial_capital=10000.0)
        
        order = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.LIMIT, limit_price=99000.0)
        
        trader.submit_order(order)  # TTL 없음
        
        # 1시간 후
        trader.expire_orders(current_time=datetime.now() + timedelta(hours=1))
        
        assert len(trader.pending_orders) == 1


class TestPaperTraderMarketMaking:
    """Market Making 시나리오 테스트"""
    
    def test_bid_ask_orders_together(self):
        """양방향 호가 동시 제출"""
        trader = PaperTrader(initial_capital=10000.0)
        
        bid_order = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.LIMIT, limit_price=99000.0)
        ask_order = Order(side=Side.SELL, quantity=0.01, order_type=OrderType.LIMIT, limit_price=101000.0)
        
        trader.submit_order(bid_order)
        trader.submit_order(ask_order)
        
        assert len(trader.pending_orders) == 2
        
        # BUY 방향 주문 확인
        buy_orders = [po for po in trader.pending_orders if po.order.side == Side.BUY]
        sell_orders = [po for po in trader.pending_orders if po.order.side == Side.SELL]
        
        assert len(buy_orders) == 1
        assert len(sell_orders) == 1
    
    def test_replace_order(self):
        """주문 교체 (취소 후 재제출)"""
        trader = PaperTrader(initial_capital=10000.0)
        
        order1 = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.LIMIT, limit_price=99000.0)
        order_id = trader.submit_order(order1)
        
        # 가격 변경을 위해 취소 후 재제출
        trader.cancel_order(order_id)
        
        order2 = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.LIMIT, limit_price=99500.0)
        trader.submit_order(order2)
        
        assert len(trader.pending_orders) == 1
        assert trader.pending_orders[0].order.limit_price == 99500.0

