"""
Latency 시뮬레이션 통합 테스트

Quant 연구원 관점에서 latency가 백테스트 결과에 미치는 영향을 검증합니다.

시나리오:
    - "캔들 보고 주문 넣으면, 네트워크 지연(50ms) 후에 체결되어야 함"
    - "지연 중에 가격이 변하면, 변한 가격에 체결되어야 함"
    - "latency가 길면 더 불리한 가격에 체결되어 PnL이 나빠짐"
"""

from datetime import datetime, timedelta

import pytest

from intraday.paper_trader import PaperTrader
from intraday.strategy import Order, Side, OrderType


class TestLatencyExecutionTiming:
    """
    시나리오: 주문 제출 후 latency 시간이 지나야 체결된다
    
    유저 입장:
        "주문 버튼 누르면 바로 체결되는 게 아니라,
         네트워크 지연만큼 기다려야 거래소에 도착해서 체결됨"
    """
    
    def test_order_should_not_execute_before_latency_passes(self):
        """
        시나리오: 50ms latency 설정 → 49ms 후에는 체결 안됨
        
        유저 입장: "50ms 지연인데 아직 49ms밖에 안 지났으면 당연히 안 되지!"
        """
        trader = PaperTrader(initial_capital=10000.0)
        
        # 12:00:00.000에 주문 제출
        order_time = datetime(2024, 1, 1, 12, 0, 0, 0)
        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order, timestamp=order_time)
        
        # 12:00:00.049 (49ms 후) - 아직 체결되면 안됨
        tick_time = order_time + timedelta(milliseconds=49)
        trade = trader.on_price_update(
            price=50000.0,
            best_bid=49999.0,
            best_ask=50000.0,
            timestamp=tick_time,
            latency_ms=50.0,
        )
        
        assert trade is None, "49ms 후에는 체결되면 안됨 (50ms latency)"
        assert len(trader.pending_orders) == 1, "주문은 아직 대기 중이어야 함"
    
    def test_order_should_execute_after_latency_passes(self):
        """
        시나리오: 50ms latency 설정 → 50ms 후에는 체결됨
        
        유저 입장: "50ms 지났으니까 이제 체결되어야지!"
        """
        trader = PaperTrader(initial_capital=10000.0)
        
        # 12:00:00.000에 주문 제출
        order_time = datetime(2024, 1, 1, 12, 0, 0, 0)
        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order, timestamp=order_time)
        
        # 12:00:00.050 (50ms 후) - 이제 체결되어야 함
        tick_time = order_time + timedelta(milliseconds=50)
        trade = trader.on_price_update(
            price=50000.0,
            best_bid=49999.0,
            best_ask=50000.0,
            timestamp=tick_time,
            latency_ms=50.0,
        )
        
        assert trade is not None, "50ms 후에는 체결되어야 함"
        assert trade.side == Side.BUY
        assert trade.quantity == 0.1
        assert trade.price == 50000.0
        assert len(trader.pending_orders) == 0, "체결 후 주문은 대기열에서 제거"


class TestLatencyAffectsExecutionPrice:
    """
    시나리오: latency 동안 가격이 변하면 변한 가격에 체결된다
    
    유저 입장:
        "내가 50000에 사려고 했는데, 주문 전송 중에 가격이 50500으로 올랐으면
         50500에 체결되어야 하는 거 아냐? 그게 현실이잖아!"
    """
    
    def test_buy_order_executes_at_delayed_price_not_signal_price(self):
        """
        시나리오: BUY 주문 제출 → 가격 상승 → 상승한 가격에 체결
        
        유저 입장: 
            "50000에 사려고 했는데 주문 전송 중에 50500으로 올랐어.
             실제로는 50500에 체결됐겠지. 백테스트도 이래야 현실적이야!"
        """
        trader = PaperTrader(initial_capital=10000.0)
        
        # 50000에서 매수 신호 발생 → 주문 제출
        signal_time = datetime(2024, 1, 1, 12, 0, 0, 0)
        signal_price = 50000.0
        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order, timestamp=signal_time)
        
        # latency 동안 가격 상승: 50000 → 50500
        execution_time = signal_time + timedelta(milliseconds=50)
        execution_price = 50500.0  # 상승한 가격
        
        trade = trader.on_price_update(
            price=execution_price,
            best_bid=execution_price - 1,
            best_ask=execution_price,
            timestamp=execution_time,
            latency_ms=50.0,
        )
        
        # 신호 발생 가격(50000)이 아닌 체결 시점 가격(50500)에 체결
        assert trade is not None
        assert trade.price == execution_price, \
            f"체결가는 신호가 아닌 실제 도착 시점 가격이어야 함: {signal_price} vs {execution_price}"
        assert trade.price > signal_price, "가격 상승으로 더 비싸게 체결됨"
    
    def test_sell_order_executes_at_delayed_price_not_signal_price(self):
        """
        시나리오: SELL 주문 제출 → 가격 하락 → 하락한 가격에 체결
        
        유저 입장:
            "50000에 팔려고 했는데 주문 전송 중에 49500으로 떨어졌어.
             실제로는 49500에 체결됐겠지. 손해 봤네..."
        """
        trader = PaperTrader(initial_capital=10000.0)
        
        # 먼저 BTC 보유 (매도하려면 있어야 함)
        trader._btc_balance = 0.1
        
        # 50000에서 매도 신호 발생 → 주문 제출
        signal_time = datetime(2024, 1, 1, 12, 0, 0, 0)
        signal_price = 50000.0
        order = Order(side=Side.SELL, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order, timestamp=signal_time)
        
        # latency 동안 가격 하락: 50000 → 49500
        execution_time = signal_time + timedelta(milliseconds=50)
        execution_price = 49500.0  # 하락한 가격
        
        trade = trader.on_price_update(
            price=execution_price,
            best_bid=execution_price,
            best_ask=execution_price + 1,
            timestamp=execution_time,
            latency_ms=50.0,
        )
        
        # 신호 발생 가격(50000)이 아닌 체결 시점 가격(49500)에 체결
        assert trade is not None
        assert trade.price == execution_price, \
            f"체결가는 신호가 아닌 실제 도착 시점 가격이어야 함"
        assert trade.price < signal_price, "가격 하락으로 더 싸게 체결됨 (손해)"


class TestLatencyImpactOnPnL:
    """
    시나리오: latency가 PnL에 미치는 영향
    
    유저 입장:
        "latency가 길면 그만큼 불리한 가격에 체결되니까 수익이 줄어들겠지?
         이걸 백테스트에서 시뮬레이션 해야 현실적인 성과를 알 수 있어!"
    """
    
    def test_higher_latency_results_in_worse_buy_price(self):
        """
        시나리오: 가격 상승 중 BUY → latency 길수록 더 비싸게 산다
        
        유저 입장:
            "나는 0ms로 빠르게 사고, 경쟁자는 100ms 걸려. 
             가격이 오르는 중이면 나는 싸게, 경쟁자는 비싸게 사겠지!"
        """
        # 가격 상승 시나리오: 50000 → 50100 → 50200 (매 50ms마다)
        order_time = datetime(2024, 1, 1, 12, 0, 0, 0)
        
        # Trader A: 0ms latency (빠른 트레이더)
        trader_fast = PaperTrader(initial_capital=10000.0)
        order_a = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader_fast.submit_order(order_a, timestamp=order_time)
        
        # 1ms 후 체결 (latency 0)
        t1 = order_time + timedelta(milliseconds=1)
        trade_fast = trader_fast.on_price_update(
            price=50000.0,  # 아직 초기 가격
            best_bid=49999.0,
            best_ask=50000.0,
            timestamp=t1,
            latency_ms=0,
        )
        
        # Trader B: 100ms latency (느린 트레이더)
        trader_slow = PaperTrader(initial_capital=10000.0)
        order_b = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader_slow.submit_order(order_b, timestamp=order_time)
        
        # 100ms 후 체결 (latency 100)
        t2 = order_time + timedelta(milliseconds=100)
        trade_slow = trader_slow.on_price_update(
            price=50200.0,  # 가격 상승 후
            best_bid=50199.0,
            best_ask=50200.0,
            timestamp=t2,
            latency_ms=100.0,
        )
        
        # 빠른 트레이더가 더 싸게 샀음
        assert trade_fast.price == 50000.0
        assert trade_slow.price == 50200.0
        assert trade_fast.price < trade_slow.price, \
            "빠른 트레이더가 더 유리한 가격에 체결"
        
        # 비용 차이 계산
        cost_diff = (trade_slow.price - trade_fast.price) * 0.1
        assert cost_diff == 20.0, f"느린 트레이더는 $20 더 비싸게 샀음"
    
    def test_complete_trade_cycle_pnl_with_latency(self):
        """
        시나리오: 완전한 거래 사이클에서 latency로 인한 PnL 차이
        
        유저 입장:
            "매수 → 매도 왕복 거래에서 latency가 얼마나 수익을 깎아먹는지 알고 싶어!"
        """
        order_time = datetime(2024, 1, 1, 12, 0, 0, 0)
        
        # === 이상적인 시나리오 (latency=0) ===
        trader_ideal = PaperTrader(initial_capital=10000.0, fee_rate=0.001)
        
        # BUY @ 50000
        buy_order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader_ideal.submit_order(buy_order, timestamp=order_time)
        t1 = order_time + timedelta(milliseconds=1)
        trader_ideal.on_price_update(50000.0, 49999.0, 50000.0, t1, latency_ms=0)
        
        # SELL @ 51000 (2% 수익)
        sell_order = Order(side=Side.SELL, quantity=0.1, order_type=OrderType.MARKET)
        t2 = order_time + timedelta(seconds=60)
        trader_ideal.submit_order(sell_order, timestamp=t2)
        t3 = t2 + timedelta(milliseconds=1)
        trader_ideal.on_price_update(51000.0, 51000.0, 51001.0, t3, latency_ms=0)
        
        # === 현실적인 시나리오 (latency=50ms) ===
        trader_real = PaperTrader(initial_capital=10000.0, fee_rate=0.001)
        
        # BUY @ 50100 (latency 동안 가격 상승)
        buy_order2 = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader_real.submit_order(buy_order2, timestamp=order_time)
        t1_real = order_time + timedelta(milliseconds=50)
        trader_real.on_price_update(50100.0, 50099.0, 50100.0, t1_real, latency_ms=50.0)
        
        # SELL @ 50900 (latency 동안 가격 하락)
        sell_order2 = Order(side=Side.SELL, quantity=0.1, order_type=OrderType.MARKET)
        t2_real = order_time + timedelta(seconds=60)
        trader_real.submit_order(sell_order2, timestamp=t2_real)
        t3_real = t2_real + timedelta(milliseconds=50)
        trader_real.on_price_update(50900.0, 50900.0, 50901.0, t3_real, latency_ms=50.0)
        
        # PnL 비교
        ideal_pnl = trader_ideal.realized_pnl
        real_pnl = trader_real.realized_pnl
        
        # 이상적 시나리오가 더 수익이 좋음
        assert ideal_pnl > real_pnl, \
            f"latency 없는 경우가 수익이 더 좋아야 함: {ideal_pnl} vs {real_pnl}"
        
        # 차이 계산 (latency로 인한 슬리피지 비용)
        slippage_cost = ideal_pnl - real_pnl
        assert slippage_cost > 0, f"latency로 인한 슬리피지 비용: ${slippage_cost:.2f}"


class TestLatencyWithLimitOrders:
    """
    시나리오: LIMIT 주문에서 latency 동작
    
    유저 입장:
        "지정가 주문도 네트워크 지연이 있으니까, 
         주문이 거래소에 도착한 후에야 가격 조건 체크가 시작되어야지!"
    """
    
    def test_limit_order_condition_checked_after_latency(self):
        """
        시나리오: LIMIT BUY @ 50000 제출 → latency 후 가격 체크 시작
        
        유저 입장:
            "지정가 50000에 사려고 했는데, 주문이 도착하기 전에 가격이 
             49000으로 떨어졌다가 50500으로 올랐어. 
             도착 시점(50500)에는 조건 미충족이니까 체결 안 되겠지!"
        """
        trader = PaperTrader(initial_capital=10000.0)
        
        order_time = datetime(2024, 1, 1, 12, 0, 0, 0)
        order = Order(
            side=Side.BUY,
            quantity=0.1,
            order_type=OrderType.LIMIT,
            limit_price=50000.0,
        )
        trader.submit_order(order, timestamp=order_time)
        
        # 30ms 후: 가격 49000 (조건 충족하지만 latency 미경과)
        t1 = order_time + timedelta(milliseconds=30)
        trade = trader.on_price_update(
            price=49000.0,  # limit_price 이하
            best_bid=48999.0,
            best_ask=49000.0,
            timestamp=t1,
            latency_ms=50.0,
        )
        assert trade is None, "latency 미경과로 체결 안됨"
        
        # 50ms 후: 가격 50500 (latency 경과했지만 조건 미충족)
        t2 = order_time + timedelta(milliseconds=50)
        trade = trader.on_price_update(
            price=50500.0,  # limit_price 초과 (조건 미충족)
            best_bid=50499.0,
            best_ask=50500.0,
            timestamp=t2,
            latency_ms=50.0,
        )
        assert trade is None, "latency 경과했지만 가격 조건 미충족으로 체결 안됨"
        assert len(trader.pending_orders) == 1, "주문은 계속 대기 중"
        
        # 100ms 후: 가격 49500 (latency 경과 + 조건 충족)
        t3 = order_time + timedelta(milliseconds=100)
        trade = trader.on_price_update(
            price=49500.0,  # limit_price 이하 (조건 충족)
            best_bid=49499.0,
            best_ask=49500.0,
            timestamp=t3,
            latency_ms=50.0,
        )
        assert trade is not None, "latency 경과 + 조건 충족 = 체결"
        assert trade.price == 50000.0, "체결가는 limit_price"


class TestLatencyBackwardCompatibility:
    """
    하위 호환성 테스트
    
    유저 입장:
        "기존 코드가 깨지면 안 돼! latency 파라미터 안 넣으면 예전처럼 동작해야 함"
    """
    
    def test_no_latency_parameter_defaults_to_immediate_execution(self):
        """
        시나리오: latency_ms 파라미터 생략 → 기존처럼 즉시 체결
        
        유저 입장: "예전 코드 그대로 쓰면 예전처럼 동작해야지!"
        """
        trader = PaperTrader(initial_capital=10000.0)
        
        order_time = datetime(2024, 1, 1, 12, 0, 0, 0)
        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order, timestamp=order_time)
        
        # latency_ms 파라미터 생략
        t1 = order_time + timedelta(milliseconds=1)
        trade = trader.on_price_update(
            price=50000.0,
            best_bid=49999.0,
            best_ask=50000.0,
            timestamp=t1,
            # latency_ms 생략 → 기본값 0
        )
        
        assert trade is not None, "기본값은 즉시 체결 (하위 호환성)"
    
    def test_zero_latency_same_as_no_latency(self):
        """
        시나리오: latency_ms=0 → 즉시 체결 (명시적)
        
        유저 입장: "latency 0으로 설정하면 이상적인 즉시 체결이지!"
        """
        trader = PaperTrader(initial_capital=10000.0)
        
        order_time = datetime(2024, 1, 1, 12, 0, 0, 0)
        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order, timestamp=order_time)
        
        t1 = order_time + timedelta(milliseconds=1)
        trade = trader.on_price_update(
            price=50000.0,
            best_bid=49999.0,
            best_ask=50000.0,
            timestamp=t1,
            latency_ms=0,  # 명시적으로 0
        )
        
        assert trade is not None, "latency=0은 즉시 체결"
    
    def test_submit_order_without_timestamp_uses_current_time(self):
        """
        시나리오: timestamp 생략 → datetime.now() 사용 (기존 동작)
        
        유저 입장: "실시간 트레이딩에서는 timestamp 안 넣으니까 현재 시간 쓰면 됨"
        """
        trader = PaperTrader(initial_capital=10000.0)
        
        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        order_id = trader.submit_order(order)  # timestamp 생략
        
        pending = trader.pending_orders[0]
        now = datetime.now()
        
        # submitted_at이 현재 시간과 1초 이내 차이
        time_diff = abs((pending.submitted_at - now).total_seconds())
        assert time_diff < 1.0, "timestamp 생략 시 현재 시간 사용"


class TestMultipleOrdersWithDifferentLatencies:
    """
    시나리오: 여러 주문이 다른 시점에 체결됨
    
    유저 입장:
        "주문 두 개를 연속으로 넣었는데, 각각 제출 시점 기준으로 
         latency가 지나야 체결되어야 해!"
    """
    
    def test_orders_execute_based_on_individual_submit_time(self):
        """
        시나리오: 주문1 @ t=0, 주문2 @ t=30ms → 각각 개별 latency 적용
        
        유저 입장:
            "첫 주문은 0ms에 넣고 두 번째는 30ms에 넣었어.
             latency 50ms면, 첫 주문은 50ms에, 두 번째는 80ms에 체결되어야지!"
        """
        trader = PaperTrader(initial_capital=10000.0)
        latency_ms = 50.0
        
        # 주문1 @ t=0
        t0 = datetime(2024, 1, 1, 12, 0, 0, 0)
        order1 = Order(side=Side.BUY, quantity=0.05, order_type=OrderType.MARKET)
        trader.submit_order(order1, timestamp=t0)
        
        # 주문2 @ t=30ms
        t1 = t0 + timedelta(milliseconds=30)
        order2 = Order(side=Side.BUY, quantity=0.05, order_type=OrderType.MARKET)
        trader.submit_order(order2, timestamp=t1)
        
        assert len(trader.pending_orders) == 2
        
        # t=40ms: 둘 다 체결 안됨 (order1: 40ms < 50ms, order2: 10ms < 50ms)
        t2 = t0 + timedelta(milliseconds=40)
        trades = trader.on_price_update_all(50000.0, 49999.0, 50000.0, t2, latency_ms)
        assert len(trades) == 0, "40ms 시점에는 둘 다 체결 안됨"
        
        # t=55ms: order1만 체결 (order1: 55ms >= 50ms, order2: 25ms < 50ms)
        t3 = t0 + timedelta(milliseconds=55)
        trades = trader.on_price_update_all(50100.0, 50099.0, 50100.0, t3, latency_ms)
        assert len(trades) == 1, "55ms 시점에는 order1만 체결"
        assert trades[0].price == 50100.0
        assert len(trader.pending_orders) == 1, "order2는 아직 대기 중"
        
        # t=85ms: order2도 체결 (order2: 85-30=55ms >= 50ms)
        t4 = t0 + timedelta(milliseconds=85)
        trades = trader.on_price_update_all(50200.0, 50199.0, 50200.0, t4, latency_ms)
        assert len(trades) == 1, "85ms 시점에는 order2 체결"
        assert trades[0].price == 50200.0
        assert len(trader.pending_orders) == 0, "모든 주문 체결 완료"


class TestLatencyEdgeCases:
    """
    Edge Case 테스트
    
    유저 입장:
        "이상한 상황에서도 제대로 동작해야지! 경계값, 예외 상황 다 테스트해봐!"
    """
    
    def test_exact_boundary_latency_should_execute(self):
        """
        시나리오: 정확히 50.0ms 경과 시 체결
        
        유저 입장: "50ms 딱 맞으면 체결되어야지, 안 되면 안 돼!"
        """
        trader = PaperTrader(initial_capital=10000.0)
        
        order_time = datetime(2024, 1, 1, 12, 0, 0, 0)
        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order, timestamp=order_time)
        
        # 정확히 50.000ms 후
        tick_time = order_time + timedelta(milliseconds=50)
        trade = trader.on_price_update(
            price=50000.0,
            best_bid=49999.0,
            best_ask=50000.0,
            timestamp=tick_time,
            latency_ms=50.0,
        )
        
        assert trade is not None, "정확히 50ms = 체결"
    
    def test_one_microsecond_before_boundary_should_not_execute(self):
        """
        시나리오: 49.999ms (경계 직전) → 체결 안됨
        
        유저 입장: "0.001ms라도 부족하면 안 됨!"
        """
        trader = PaperTrader(initial_capital=10000.0)
        
        order_time = datetime(2024, 1, 1, 12, 0, 0, 0)
        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order, timestamp=order_time)
        
        # 49.999ms 후 (1 마이크로초 부족)
        tick_time = order_time + timedelta(milliseconds=49, microseconds=999)
        trade = trader.on_price_update(
            price=50000.0,
            best_bid=49999.0,
            best_ask=50000.0,
            timestamp=tick_time,
            latency_ms=50.0,
        )
        
        assert trade is None, "49.999ms는 체결 안됨"
    
    def test_insufficient_balance_after_latency_should_fail(self):
        """
        시나리오: latency 지났지만 잔고 부족 → 체결 실패
        
        유저 입장: 
            "주문이 거래소에 도착했는데 잔고가 없으면 당연히 안 되지!"
        """
        trader = PaperTrader(initial_capital=100.0)  # 잔고 부족
        
        order_time = datetime(2024, 1, 1, 12, 0, 0, 0)
        # 0.1 BTC @ 50000 = $5000 필요, 잔고 $100
        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order, timestamp=order_time)
        
        # latency 경과
        tick_time = order_time + timedelta(milliseconds=100)
        trade = trader.on_price_update(
            price=50000.0,
            best_bid=49999.0,
            best_ask=50000.0,
            timestamp=tick_time,
            latency_ms=50.0,
        )
        
        assert trade is None, "잔고 부족으로 체결 실패"
        # MARKET 주문은 실패해도 대기열에서 제거됨
        assert len(trader.pending_orders) == 0, "MARKET 주문은 실패해도 제거"
    
    def test_ttl_expires_before_latency_passes(self):
        """
        시나리오: TTL 30ms, latency 50ms → latency 전에 주문 만료
        
        유저 입장:
            "주문 유효시간 30ms인데, 네트워크 지연이 50ms면 
             도착하기 전에 만료되어야지!"
        """
        trader = PaperTrader(initial_capital=10000.0)
        
        order_time = datetime(2024, 1, 1, 12, 0, 0, 0)
        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        # TTL 30ms (0.03초)
        trader.submit_order(order, timestamp=order_time, ttl_seconds=0.03)
        
        # 50ms 후 (TTL 만료 + latency 경과)
        tick_time = order_time + timedelta(milliseconds=50)
        trade = trader.on_price_update(
            price=50000.0,
            best_bid=49999.0,
            best_ask=50000.0,
            timestamp=tick_time,
            latency_ms=50.0,
        )
        
        assert trade is None, "TTL 만료로 체결 안됨"
        assert len(trader.pending_orders) == 0, "만료된 주문은 제거됨"
    
    def test_order_at_same_timestamp_as_tick(self):
        """
        시나리오: 주문 제출 시점 = 틱 시점 (t=0) → latency 있으면 체결 안됨
        
        유저 입장:
            "주문 넣자마자 틱이 왔어도, latency가 있으면 바로 체결 안 돼!"
        """
        trader = PaperTrader(initial_capital=10000.0)
        
        t0 = datetime(2024, 1, 1, 12, 0, 0, 0)
        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order, timestamp=t0)
        
        # 같은 시점에 틱 (elapsed = 0ms)
        trade = trader.on_price_update(
            price=50000.0,
            best_bid=49999.0,
            best_ask=50000.0,
            timestamp=t0,  # 주문 시점과 동일
            latency_ms=50.0,
        )
        
        assert trade is None, "elapsed=0ms < latency=50ms → 체결 안됨"
    
    def test_limit_sell_order_with_latency(self):
        """
        시나리오: LIMIT SELL @ 51000 + latency → 가격 상승 후 체결
        
        유저 입장:
            "지정가 매도 51000에 걸었는데, 주문 도착 후 가격이 51000 이상이면 체결!"
        """
        trader = PaperTrader(initial_capital=10000.0)
        trader._btc_balance = 0.1  # 매도할 BTC 보유
        
        order_time = datetime(2024, 1, 1, 12, 0, 0, 0)
        order = Order(
            side=Side.SELL,
            quantity=0.1,
            order_type=OrderType.LIMIT,
            limit_price=51000.0,
        )
        trader.submit_order(order, timestamp=order_time)
        
        # 30ms 후: 가격 51500 (조건 충족하지만 latency 미경과)
        t1 = order_time + timedelta(milliseconds=30)
        trade = trader.on_price_update(
            price=51500.0,
            best_bid=51500.0,
            best_ask=51501.0,
            timestamp=t1,
            latency_ms=50.0,
        )
        assert trade is None, "latency 미경과로 체결 안됨"
        
        # 60ms 후: 가격 51200 (latency 경과 + 조건 충족)
        t2 = order_time + timedelta(milliseconds=60)
        trade = trader.on_price_update(
            price=51200.0,
            best_bid=51200.0,
            best_ask=51201.0,
            timestamp=t2,
            latency_ms=50.0,
        )
        assert trade is not None, "latency 경과 + 조건 충족 = 체결"
        assert trade.price == 51000.0, "체결가는 limit_price"
        assert trade.side == Side.SELL
    
    def test_orders_submitted_at_same_time_execute_in_fifo_order(self):
        """
        시나리오: 같은 시점에 여러 주문 제출 → FIFO 순서로 체결
        
        유저 입장:
            "동시에 두 주문 넣었으면, 먼저 넣은 순서대로 체결되어야지!"
        """
        trader = PaperTrader(initial_capital=10000.0)
        
        t0 = datetime(2024, 1, 1, 12, 0, 0, 0)
        
        # 같은 시점에 두 주문 제출
        order1 = Order(side=Side.BUY, quantity=0.05, order_type=OrderType.MARKET)
        order2 = Order(side=Side.BUY, quantity=0.03, order_type=OrderType.MARKET)
        trader.submit_order(order1, timestamp=t0)
        trader.submit_order(order2, timestamp=t0)
        
        # latency 경과 후
        t1 = t0 + timedelta(milliseconds=50)
        trades = trader.on_price_update_all(
            price=50000.0,
            best_bid=49999.0,
            best_ask=50000.0,
            timestamp=t1,
            latency_ms=50.0,
        )
        
        # 둘 다 체결되어야 함 (FIFO 순서)
        assert len(trades) == 2, "둘 다 체결"
        assert trades[0].quantity == 0.05, "첫 번째 주문 먼저 체결"
        assert trades[1].quantity == 0.03, "두 번째 주문 다음 체결"
    
    def test_very_large_latency(self):
        """
        시나리오: 매우 큰 latency (10초) → 10초 지나야 체결
        
        유저 입장:
            "네트워크가 엄청 느려서 10초 걸리면, 10초 후에나 체결되어야지!"
        """
        trader = PaperTrader(initial_capital=10000.0)
        
        order_time = datetime(2024, 1, 1, 12, 0, 0, 0)
        order = Order(side=Side.BUY, quantity=0.1, order_type=OrderType.MARKET)
        trader.submit_order(order, timestamp=order_time)
        
        latency_ms = 10000.0  # 10초
        
        # 5초 후 - 아직 안됨
        t1 = order_time + timedelta(seconds=5)
        trade = trader.on_price_update(50000.0, 49999.0, 50000.0, t1, latency_ms)
        assert trade is None, "5초 < 10초 latency"
        
        # 10초 후 - 이제 됨
        t2 = order_time + timedelta(seconds=10)
        trade = trader.on_price_update(55000.0, 54999.0, 55000.0, t2, latency_ms)
        assert trade is not None, "10초 >= 10초 latency"
        assert trade.price == 55000.0, "10초 후 가격에 체결"

