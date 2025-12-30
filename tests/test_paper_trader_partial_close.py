"""
부분 청산(Partial Close) 테스트

클라이언트 입장에서 "이게 되면 이게 나와야 한다" 베이스로 작성
"""

from datetime import datetime

import pytest

from intraday.paper_trader import PaperTrader
from intraday.strategy import Order, Side, OrderType


class TestPartialClose:
    """부분 청산 테스트"""

    def test_partial_close_reduces_position_quantity(self):
        """
        부분 청산 시 포지션 수량이 줄어들어야 한다
        
        시나리오:
            - 0.03 BTC 매수 후
            - 0.01 BTC 매도하면
            - 포지션이 0.02 BTC로 줄어야 함
        """
        trader = PaperTrader(initial_capital=10000, fee_rate=0.001)
        
        # 0.03 BTC 매수 @ 100
        trader.submit_order(Order(side=Side.BUY, quantity=0.03, order_type=OrderType.MARKET))
        trader.on_price_update(price=100, best_bid=100, best_ask=100, timestamp=datetime.now())
        
        # 0.01 BTC 부분 청산
        trader.submit_order(Order(side=Side.SELL, quantity=0.01, order_type=OrderType.MARKET))
        trader.on_price_update(price=110, best_bid=110, best_ask=110, timestamp=datetime.now())
        
        # 포지션이 0.02 BTC로 줄어야 함
        assert trader.position.side == Side.BUY
        assert trader.position.quantity == pytest.approx(0.02)

    def test_partial_close_maintains_entry_price(self):
        """
        부분 청산 후에도 평균 진입가가 유지되어야 한다
        
        시나리오:
            - 100에 매수 후
            - 부분 청산해도
            - 진입가는 100 그대로
        """
        trader = PaperTrader(initial_capital=10000, fee_rate=0.001)
        
        # 0.03 BTC 매수 @ 100
        trader.submit_order(Order(side=Side.BUY, quantity=0.03, order_type=OrderType.MARKET))
        trader.on_price_update(price=100, best_bid=100, best_ask=100, timestamp=datetime.now())
        
        original_entry_price = trader.position.entry_price
        
        # 0.01 BTC 부분 청산 @ 120
        trader.submit_order(Order(side=Side.SELL, quantity=0.01, order_type=OrderType.MARKET))
        trader.on_price_update(price=120, best_bid=120, best_ask=120, timestamp=datetime.now())
        
        # 진입가가 유지되어야 함
        assert trader.position.entry_price == original_entry_price

    def test_partial_close_calculates_correct_pnl(self):
        """
        부분 청산 시 PnL이 올바르게 계산되어야 한다
        
        시나리오:
            - 0.03 BTC 매수 @ 100 (수수료 $0.003)
            - 0.01 BTC 매도 @ 130 (수수료 $0.0013)
            - Gross PnL = (130 - 100) * 0.01 = $0.30
            - 배분된 진입 수수료 = $0.003 * (1/3) = $0.001
            - Net PnL = $0.30 - $0.001 - $0.0013 = $0.2977
        """
        trader = PaperTrader(initial_capital=10000, fee_rate=0.001)
        
        # 0.03 BTC 매수 @ 100
        trader.submit_order(Order(side=Side.BUY, quantity=0.03, order_type=OrderType.MARKET))
        trader.on_price_update(price=100, best_bid=100, best_ask=100, timestamp=datetime.now())
        
        # 0.01 BTC 부분 청산 @ 130
        trader.submit_order(Order(side=Side.SELL, quantity=0.01, order_type=OrderType.MARKET))
        trade = trader.on_price_update(price=130, best_bid=130, best_ask=130, timestamp=datetime.now())
        
        # PnL 계산 검증
        expected_gross_pnl = (130 - 100) * 0.01  # $0.30
        expected_entry_fee = 100 * 0.03 * 0.001 * (1/3)  # $0.001
        expected_exit_fee = 130 * 0.01 * 0.001  # $0.0013
        expected_net_pnl = expected_gross_pnl - expected_entry_fee - expected_exit_fee
        
        assert trade is not None
        assert trade.pnl == pytest.approx(expected_net_pnl)

    def test_multiple_partial_closes_then_full_close(self):
        """
        여러 번 부분 청산 후 전량 청산이 가능해야 한다
        
        시나리오:
            - 0.03 BTC 매수
            - 0.01 BTC 청산 (1차)
            - 0.01 BTC 청산 (2차)
            - 0.01 BTC 청산 (3차) → 포지션 종료
        """
        trader = PaperTrader(initial_capital=10000, fee_rate=0.001)
        
        # 0.03 BTC 매수
        trader.submit_order(Order(side=Side.BUY, quantity=0.03, order_type=OrderType.MARKET))
        trader.on_price_update(price=100, best_bid=100, best_ask=100, timestamp=datetime.now())
        
        # 3번 부분 청산
        for price in [110, 120, 130]:
            trader.submit_order(Order(side=Side.SELL, quantity=0.01, order_type=OrderType.MARKET))
            trade = trader.on_price_update(price=price, best_bid=price, best_ask=price, timestamp=datetime.now())
            assert trade is not None, f"청산 @ {price} 실패"
        
        # 포지션이 종료되어야 함
        assert trader.position.side is None
        assert len(trader.trades) == 4  # 1 매수 + 3 매도

    def test_partial_close_updates_btc_balance(self):
        """
        부분 청산 시 BTC 잔고가 줄어들어야 한다
        
        시나리오:
            - 0.03 BTC 매수 → BTC 잔고 0.03
            - 0.01 BTC 매도 → BTC 잔고 0.02
        """
        trader = PaperTrader(initial_capital=10000, fee_rate=0.001)
        
        # 매수
        trader.submit_order(Order(side=Side.BUY, quantity=0.03, order_type=OrderType.MARKET))
        trader.on_price_update(price=100, best_bid=100, best_ask=100, timestamp=datetime.now())
        
        assert trader.btc_balance == pytest.approx(0.03)
        
        # 부분 청산
        trader.submit_order(Order(side=Side.SELL, quantity=0.01, order_type=OrderType.MARKET))
        trader.on_price_update(price=110, best_bid=110, best_ask=110, timestamp=datetime.now())
        
        assert trader.btc_balance == pytest.approx(0.02)

    def test_partial_close_accumulates_realized_pnl(self):
        """
        여러 번 부분 청산 시 실현 손익이 누적되어야 한다
        """
        trader = PaperTrader(initial_capital=10000, fee_rate=0.001)
        
        # 매수
        trader.submit_order(Order(side=Side.BUY, quantity=0.03, order_type=OrderType.MARKET))
        trader.on_price_update(price=100, best_bid=100, best_ask=100, timestamp=datetime.now())
        
        total_pnl = 0.0
        
        # 3번 부분 청산
        for price in [110, 120, 130]:
            trader.submit_order(Order(side=Side.SELL, quantity=0.01, order_type=OrderType.MARKET))
            trade = trader.on_price_update(price=price, best_bid=price, best_ask=price, timestamp=datetime.now())
            total_pnl += trade.pnl
        
        # 누적 실현 손익 확인
        assert trader.realized_pnl == pytest.approx(total_pnl)

    def test_partial_close_with_pyramiding(self):
        """
        피라미딩 후 부분 청산 시 평단가 기준으로 PnL 계산
        
        시나리오:
            - 0.01 BTC 매수 @ 100
            - 0.02 BTC 추가 매수 @ 110 → 평단가 106.67
            - 0.01 BTC 청산 @ 120 → PnL = (120 - 106.67) * 0.01
        """
        trader = PaperTrader(initial_capital=10000, fee_rate=0.001)
        
        # 1차 매수 @ 100
        trader.submit_order(Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET))
        trader.on_price_update(price=100, best_bid=100, best_ask=100, timestamp=datetime.now())
        
        # 2차 매수 @ 110 (피라미딩)
        trader.submit_order(Order(side=Side.BUY, quantity=0.02, order_type=OrderType.MARKET))
        trader.on_price_update(price=110, best_bid=110, best_ask=110, timestamp=datetime.now())
        
        # 평단가 확인: (100*0.01 + 110*0.02) / 0.03 = 106.67
        expected_avg_price = (100 * 0.01 + 110 * 0.02) / 0.03
        assert trader.position.entry_price == pytest.approx(expected_avg_price)
        
        # 부분 청산 @ 120
        trader.submit_order(Order(side=Side.SELL, quantity=0.01, order_type=OrderType.MARKET))
        trade = trader.on_price_update(price=120, best_bid=120, best_ask=120, timestamp=datetime.now())
        
        # 정확한 PnL 계산
        # Gross PnL = (120 - 106.67) * 0.01
        expected_gross_pnl = (120 - expected_avg_price) * 0.01
        
        # 진입 수수료: 1차 + 2차 매수 수수료
        entry_fee_1 = 100 * 0.01 * 0.001  # 1차 매수 수수료
        entry_fee_2 = 110 * 0.02 * 0.001  # 2차 매수 수수료
        total_entry_fee = entry_fee_1 + entry_fee_2
        
        # 부분 청산 비율만큼 진입 수수료 배분
        close_ratio = 0.01 / 0.03
        allocated_entry_fee = total_entry_fee * close_ratio
        
        # 청산 수수료
        exit_fee = 120 * 0.01 * 0.001
        
        # Net PnL = Gross PnL - 배분된 진입 수수료 - 청산 수수료
        expected_net_pnl = expected_gross_pnl - allocated_entry_fee - exit_fee
        
        assert trade.pnl == pytest.approx(expected_net_pnl)

    def test_partial_close_loss_scenario(self):
        """
        손실 상태에서 부분 청산 시 음수 PnL
        
        시나리오:
            - 0.02 BTC 매수 @ 100
            - 0.01 BTC 청산 @ 90 → 손실
        """
        trader = PaperTrader(initial_capital=10000, fee_rate=0.001)
        
        # 매수 @ 100
        trader.submit_order(Order(side=Side.BUY, quantity=0.02, order_type=OrderType.MARKET))
        trader.on_price_update(price=100, best_bid=100, best_ask=100, timestamp=datetime.now())
        
        # 부분 청산 @ 90 (손실)
        trader.submit_order(Order(side=Side.SELL, quantity=0.01, order_type=OrderType.MARKET))
        trade = trader.on_price_update(price=90, best_bid=90, best_ask=90, timestamp=datetime.now())
        
        # 손실이므로 PnL이 음수여야 함
        assert trade.pnl < 0
        
        # 남은 포지션 확인
        assert trader.position.side == Side.BUY
        assert trader.position.quantity == pytest.approx(0.01)

