"""
PaperTrader 모듈 테스트

LIMIT/MARKET 체결, 포지션 관리, PnL 계산 검증
"""

from datetime import datetime

import pytest

from intraday.strategy import Side, OrderType, Order
from intraday.paper_trader import Trade, Position, PaperTrader


class TestTrade:
    """Trade 데이터클래스 테스트"""
    
    def test_trade_creation(self):
        """Trade 생성 테스트"""
        now = datetime.now()
        trade = Trade(
            timestamp=now,
            side=Side.BUY,
            price=100000.0,
            quantity=0.01,
            fee=10.0,
            pnl=0.0,
        )
        
        assert trade.timestamp == now
        assert trade.side == Side.BUY
        assert trade.price == 100000.0
        assert trade.quantity == 0.01
        assert trade.fee == 10.0
        assert trade.pnl == 0.0


class TestPosition:
    """Position 데이터클래스 테스트"""
    
    def test_position_creation(self):
        """Position 생성 테스트"""
        position = Position(
            side=Side.BUY,
            quantity=0.01,
            entry_price=100000.0,
            unrealized_pnl=50.0,
        )
        
        assert position.side == Side.BUY
        assert position.quantity == 0.01
        assert position.entry_price == 100000.0
        assert position.unrealized_pnl == 50.0
    
    def test_empty_position(self):
        """빈 포지션 테스트"""
        position = Position(
            side=None,
            quantity=0.0,
            entry_price=0.0,
            unrealized_pnl=0.0,
        )
        
        assert position.side is None
        assert position.quantity == 0.0


class TestPaperTraderInit:
    """PaperTrader 초기화 테스트"""
    
    def test_default_initialization(self):
        """기본값으로 초기화"""
        trader = PaperTrader(initial_capital=10000.0)
        
        assert trader.initial_capital == 10000.0
        assert trader.fee_rate == 0.001  # 기본 0.1%
        assert trader.capital == 10000.0
        assert trader.position.side is None
        assert trader.realized_pnl == 0.0
        assert len(trader.trades) == 0
    
    def test_custom_fee_rate(self):
        """커스텀 수수료율"""
        trader = PaperTrader(initial_capital=10000.0, fee_rate=0.0005)
        
        assert trader.fee_rate == 0.0005


class TestPaperTraderMarketOrder:
    """MARKET 주문 체결 테스트"""
    
    def test_market_buy_execution(self):
        """MARKET BUY 즉시 체결"""
        trader = PaperTrader(initial_capital=10000.0, fee_rate=0.001)
        
        order = Order(
            side=Side.BUY,
            quantity=0.01,
            order_type=OrderType.MARKET,
        )
        
        trader.submit_order(order)
        
        # MARKET 주문은 다음 가격 업데이트에서 즉시 체결
        trade = trader.on_price_update(
            price=100000.0,
            best_bid=99990.0,
            best_ask=100000.0,
            timestamp=datetime.now(),
        )
        
        assert trade is not None
        assert trade.side == Side.BUY
        assert trade.price == 100000.0  # best_ask에 체결
        assert trade.quantity == 0.01
        # 수수료: 100000 * 0.01 * 0.001 = 1.0
        assert trade.fee == 1.0
        
        # 포지션 확인
        assert trader.position.side == Side.BUY
        assert trader.position.quantity == 0.01
        assert trader.position.entry_price == 100000.0
    
    def test_market_sell_execution(self):
        """MARKET SELL 즉시 체결"""
        trader = PaperTrader(initial_capital=10000.0, fee_rate=0.001)
        
        # 먼저 포지션 진입
        buy_order = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(buy_order)
        trader.on_price_update(price=100000.0, best_bid=99990.0, best_ask=100000.0, timestamp=datetime.now())
        
        # 매도 주문
        sell_order = Order(side=Side.SELL, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(sell_order)
        
        trade = trader.on_price_update(
            price=100100.0,
            best_bid=100100.0,
            best_ask=100110.0,
            timestamp=datetime.now(),
        )
        
        assert trade is not None
        assert trade.side == Side.SELL
        assert trade.price == 100100.0  # best_bid에 체결
        
        # 포지션 청산됨
        assert trader.position.side is None
        assert trader.position.quantity == 0.0


class TestPaperTraderLimitOrder:
    """LIMIT 주문 체결 테스트"""
    
    def test_limit_buy_not_filled_when_price_above(self):
        """LIMIT BUY: 가격이 limit_price 위일 때 체결 안 됨"""
        trader = PaperTrader(initial_capital=10000.0)
        
        order = Order(
            side=Side.BUY,
            quantity=0.01,
            order_type=OrderType.LIMIT,
            limit_price=99000.0,  # 99000에 매수 대기
        )
        
        trader.submit_order(order)
        
        # 현재 가격이 limit_price보다 높음 → 체결 안 됨
        trade = trader.on_price_update(
            price=100000.0,
            best_bid=99990.0,
            best_ask=100000.0,
            timestamp=datetime.now(),
        )
        
        assert trade is None
        assert trader.position.side is None
    
    def test_limit_buy_filled_when_price_drops(self):
        """LIMIT BUY: 가격이 limit_price 이하로 떨어지면 체결"""
        trader = PaperTrader(initial_capital=10000.0)
        
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
        
        assert trade is not None
        assert trade.side == Side.BUY
        assert trade.price == 99000.0  # limit_price에 체결
        assert trader.position.side == Side.BUY
    
    def test_limit_sell_not_filled_when_price_below(self):
        """LIMIT SELL: 가격이 limit_price 아래일 때 체결 안 됨"""
        trader = PaperTrader(initial_capital=10000.0)
        
        # 먼저 포지션 진입
        buy_order = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(buy_order)
        trader.on_price_update(price=100000.0, best_bid=99990.0, best_ask=100000.0, timestamp=datetime.now())
        
        # 매도 대기
        sell_order = Order(
            side=Side.SELL,
            quantity=0.01,
            order_type=OrderType.LIMIT,
            limit_price=101000.0,  # 101000에 매도 대기
        )
        
        trader.submit_order(sell_order)
        
        # 현재 가격이 limit_price보다 낮음 → 체결 안 됨
        trade = trader.on_price_update(
            price=100500.0,
            best_bid=100490.0,
            best_ask=100500.0,
            timestamp=datetime.now(),
        )
        
        assert trade is None
        assert trader.position.side == Side.BUY  # 여전히 포지션 유지
    
    def test_limit_sell_filled_when_price_rises(self):
        """LIMIT SELL: 가격이 limit_price 이상으로 오르면 체결"""
        trader = PaperTrader(initial_capital=10000.0)
        
        # 먼저 포지션 진입
        buy_order = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(buy_order)
        trader.on_price_update(price=100000.0, best_bid=99990.0, best_ask=100000.0, timestamp=datetime.now())
        
        # 매도 대기
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
        
        assert trade is not None
        assert trade.side == Side.SELL
        assert trade.price == 101000.0  # limit_price에 체결
        assert trader.position.side is None  # 포지션 청산


class TestPaperTraderPnL:
    """PnL 계산 테스트"""
    
    def test_realized_pnl_on_profit(self):
        """수익 실현 시 realized_pnl 계산"""
        trader = PaperTrader(initial_capital=10000.0, fee_rate=0.001)
        
        # 100000에 매수
        buy_order = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(buy_order)
        trader.on_price_update(price=100000.0, best_bid=99990.0, best_ask=100000.0, timestamp=datetime.now())
        
        # 101000에 매도 (1000 * 0.01 = 10 이익)
        sell_order = Order(side=Side.SELL, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(sell_order)
        trade = trader.on_price_update(price=101000.0, best_bid=101000.0, best_ask=101010.0, timestamp=datetime.now())
        
        # PnL = (101000 - 100000) * 0.01 = 10
        # 수수료 = 100000 * 0.01 * 0.001 + 101000 * 0.01 * 0.001 = 1.0 + 1.01 = 2.01
        # 순 PnL = 10 - 2.01 = 7.99
        assert trade.pnl == pytest.approx(10.0 - 2.01, rel=0.01)
        assert trader.realized_pnl == pytest.approx(10.0 - 2.01, rel=0.01)
    
    def test_realized_pnl_on_loss(self):
        """손실 실현 시 realized_pnl 계산"""
        trader = PaperTrader(initial_capital=10000.0, fee_rate=0.001)
        
        # 100000에 매수
        buy_order = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(buy_order)
        trader.on_price_update(price=100000.0, best_bid=99990.0, best_ask=100000.0, timestamp=datetime.now())
        
        # 99000에 매도 (1000 * 0.01 = 10 손실)
        sell_order = Order(side=Side.SELL, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(sell_order)
        trade = trader.on_price_update(price=99000.0, best_bid=99000.0, best_ask=99010.0, timestamp=datetime.now())
        
        # PnL = (99000 - 100000) * 0.01 = -10
        # 수수료 = 1.0 + 0.99 = 1.99
        # 순 PnL = -10 - 1.99 = -11.99
        assert trade.pnl == pytest.approx(-10.0 - 1.99, rel=0.01)
        assert trader.realized_pnl == pytest.approx(-10.0 - 1.99, rel=0.01)
    
    def test_unrealized_pnl_calculation(self):
        """미실현 손익 계산"""
        trader = PaperTrader(initial_capital=10000.0, fee_rate=0.001)
        
        # 100000에 매수
        buy_order = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(buy_order)
        trader.on_price_update(price=100000.0, best_bid=99990.0, best_ask=100000.0, timestamp=datetime.now())
        
        # 가격이 101000으로 상승 (미실현 이익)
        trader.update_unrealized_pnl(current_price=101000.0)
        
        # 미실현 PnL = (101000 - 100000) * 0.01 = 10
        assert trader.position.unrealized_pnl == pytest.approx(10.0, rel=0.01)
    
    def test_total_pnl(self):
        """총 PnL (실현 + 미실현)"""
        trader = PaperTrader(initial_capital=10000.0, fee_rate=0.001)
        
        # 첫 번째 거래: 100000 → 101000 (이익)
        buy_order = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(buy_order)
        trader.on_price_update(price=100000.0, best_bid=99990.0, best_ask=100000.0, timestamp=datetime.now())
        
        sell_order = Order(side=Side.SELL, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(sell_order)
        trader.on_price_update(price=101000.0, best_bid=101000.0, best_ask=101010.0, timestamp=datetime.now())
        
        # 두 번째 거래: 새 포지션 진입
        buy_order2 = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(buy_order2)
        trader.on_price_update(price=101500.0, best_bid=101490.0, best_ask=101500.0, timestamp=datetime.now())
        
        # 현재 가격 102000 (미실현 이익)
        trader.update_unrealized_pnl(current_price=102000.0)
        
        # total_pnl = realized_pnl + unrealized_pnl
        assert trader.total_pnl == pytest.approx(trader.realized_pnl + trader.position.unrealized_pnl, rel=0.01)


class TestPaperTraderTradeHistory:
    """거래 내역 테스트"""
    
    def test_trades_list_grows(self):
        """거래 시 trades 리스트에 추가"""
        trader = PaperTrader(initial_capital=10000.0)
        
        # 첫 번째 거래
        order1 = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(order1)
        trader.on_price_update(price=100000.0, best_bid=99990.0, best_ask=100000.0, timestamp=datetime.now())
        
        assert len(trader.trades) == 1
        
        # 두 번째 거래
        order2 = Order(side=Side.SELL, quantity=0.01, order_type=OrderType.MARKET)
        trader.submit_order(order2)
        trader.on_price_update(price=101000.0, best_bid=101000.0, best_ask=101010.0, timestamp=datetime.now())
        
        assert len(trader.trades) == 2
        assert trader.trades[0].side == Side.BUY
        assert trader.trades[1].side == Side.SELL

