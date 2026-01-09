"""
TickForwardRunner 테스트

클라이언트 관점에서 기대 동작을 검증합니다.
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from intraday import TickForwardRunner, CandleType, Side, Order, OrderType
from intraday.client import AggTrade
from intraday.candle_builder import Candle
from intraday.strategies.tick.bb_squeeze import BBSqueezeStrategy


# === Fixtures ===


class MockStrategy:
    """테스트용 Mock 전략"""

    def __init__(self, quantity: float = 0.01):
        self.quantity = quantity
        self.call_count = 0
        self.last_state = None
        self._next_order = None

    def generate_order(self, state):
        self.call_count += 1
        self.last_state = state
        order = self._next_order
        self._next_order = None  # 한 번 사용 후 초기화
        return order

    def set_next_order(self, order):
        """다음 호출에서 반환할 주문 설정"""
        self._next_order = order


def make_trade(price: float, quantity: float = 0.1, timestamp: datetime = None, is_buyer_maker: bool = False) -> AggTrade:
    """테스트용 AggTrade 생성"""
    return AggTrade(
        timestamp=timestamp or datetime.now(),
        symbol="BTCUSDT",
        price=price,
        quantity=quantity,
        is_buyer_maker=is_buyer_maker,
    )


# === 초기화 테스트 ===


class TestTickForwardRunnerInit:
    """초기화 테스트"""

    def test_creates_with_default_parameters(self):
        """기본 파라미터로 생성할 수 있다"""
        strategy = MockStrategy()
        runner = TickForwardRunner(strategy=strategy)

        assert runner.symbol == "btcusdt"
        assert runner.candle_type == CandleType.TIME
        assert runner.candle_size == 240.0
        assert runner.initial_capital == 10000.0
        assert runner.leverage == 1

    def test_creates_with_custom_parameters(self):
        """커스텀 파라미터로 생성할 수 있다"""
        strategy = MockStrategy()
        runner = TickForwardRunner(
            strategy=strategy,
            symbol="ethusdt",
            candle_type=CandleType.VOLUME,
            candle_size=100.0,
            initial_capital=50000.0,
            leverage=10,
            fee_rate=0.0005,
        )

        assert runner.symbol == "ethusdt"
        assert runner.candle_type == CandleType.VOLUME
        assert runner.candle_size == 100.0
        assert runner.initial_capital == 50000.0
        assert runner.leverage == 10
        assert runner.fee_rate == 0.0005

    def test_initial_state_is_not_running(self):
        """초기 상태는 실행 중이 아니다"""
        strategy = MockStrategy()
        runner = TickForwardRunner(strategy=strategy)

        assert runner.is_running is False
        assert runner.tick_count == 0
        assert runner.candle_count == 0


# === 틱 처리 테스트 ===


class TestTickProcessing:
    """틱 처리 테스트"""

    def test_counts_ticks(self):
        """틱을 카운트한다"""
        strategy = MockStrategy()
        runner = TickForwardRunner(strategy=strategy)

        # 틱 직접 처리 (내부 메서드 호출)
        trade = make_trade(price=50000.0)
        runner._on_trade(trade)

        assert runner.tick_count == 1
        assert runner.last_trade_price == 50000.0

    def test_multiple_ticks_increment_count(self):
        """여러 틱이 카운트에 누적된다"""
        strategy = MockStrategy()
        runner = TickForwardRunner(strategy=strategy)

        for i in range(10):
            trade = make_trade(price=50000.0 + i)
            runner._on_trade(trade)

        assert runner.tick_count == 10
        assert runner.last_trade_price == 50009.0


# === 캔들 빌드 테스트 ===


class TestCandleBuilding:
    """캔들 빌드 테스트"""

    def test_builds_time_candle_after_interval(self):
        """시간 간격 후 TIME 캔들이 생성된다"""
        strategy = MockStrategy()
        runner = TickForwardRunner(
            strategy=strategy,
            candle_type=CandleType.TIME,
            candle_size=10.0,  # 10초
        )

        # 첫 틱
        t0 = datetime(2024, 1, 1, 12, 0, 0)
        runner._on_trade(make_trade(price=50000.0, timestamp=t0))
        assert runner.candle_count == 0

        # 10초 후 틱 -> 캔들 완성
        t1 = t0 + timedelta(seconds=11)
        runner._on_trade(make_trade(price=50100.0, timestamp=t1))
        assert runner.candle_count == 1

    def test_builds_volume_candle_after_volume(self):
        """볼륨 충족 후 VOLUME 캔들이 생성된다"""
        strategy = MockStrategy()
        runner = TickForwardRunner(
            strategy=strategy,
            candle_type=CandleType.VOLUME,
            candle_size=1.0,  # 1 BTC
        )

        # 0.5 BTC 틱
        runner._on_trade(make_trade(price=50000.0, quantity=0.5))
        assert runner.candle_count == 0

        # 0.5 BTC 추가 -> 1 BTC 완성
        runner._on_trade(make_trade(price=50100.0, quantity=0.5))
        assert runner.candle_count == 1

    def test_builds_tick_candle_after_count(self):
        """틱 수 충족 후 TICK 캔들이 생성된다"""
        strategy = MockStrategy()
        runner = TickForwardRunner(
            strategy=strategy,
            candle_type=CandleType.TICK,
            candle_size=5,  # 5틱
        )

        # 4틱
        for i in range(4):
            runner._on_trade(make_trade(price=50000.0 + i))
        assert runner.candle_count == 0

        # 5번째 틱 -> 캔들 완성
        runner._on_trade(make_trade(price=50005.0))
        assert runner.candle_count == 1


# === 전략 실행 테스트 ===


class TestStrategyExecution:
    """전략 실행 테스트"""

    def test_executes_strategy_on_candle_completion(self):
        """캔들 완성 시 전략을 실행한다"""
        strategy = MockStrategy()
        runner = TickForwardRunner(
            strategy=strategy,
            candle_type=CandleType.TICK,
            candle_size=2,  # 2틱마다 캔들
        )

        # 1틱 - 전략 미실행
        runner._on_trade(make_trade(price=50000.0))
        assert strategy.call_count == 0

        # 2틱 - 캔들 완성, 전략 실행
        runner._on_trade(make_trade(price=50100.0))
        assert strategy.call_count == 1

    def test_passes_ohlcv_to_strategy(self):
        """전략에 OHLCV 데이터를 전달한다"""
        strategy = MockStrategy()
        runner = TickForwardRunner(
            strategy=strategy,
            candle_type=CandleType.TICK,
            candle_size=3,
        )

        # 3틱으로 캔들 생성: open=100, high=120, low=100, close=110
        runner._on_trade(make_trade(price=100.0))
        runner._on_trade(make_trade(price=120.0))
        runner._on_trade(make_trade(price=110.0))

        state = strategy.last_state
        assert state is not None
        assert state.open == 100.0
        assert state.high == 120.0
        assert state.low == 100.0
        assert state.close == 110.0

    def test_passes_position_info_to_strategy(self):
        """전략에 포지션 정보를 전달한다"""
        strategy = MockStrategy()
        runner = TickForwardRunner(
            strategy=strategy,
            candle_type=CandleType.TICK,
            candle_size=2,
        )

        # 초기 상태: 포지션 없음
        runner._on_trade(make_trade(price=50000.0))
        runner._on_trade(make_trade(price=50100.0))

        state = strategy.last_state
        assert state.position_side is None
        assert state.position_qty == 0.0


# === 주문 제출 테스트 ===


class TestOrderSubmission:
    """주문 제출 테스트"""

    def test_submits_order_from_strategy(self):
        """전략에서 반환한 주문을 제출한다"""
        strategy = MockStrategy(quantity=0.01)
        runner = TickForwardRunner(
            strategy=strategy,
            candle_type=CandleType.TICK,
            candle_size=2,
        )

        # 주문 설정
        order = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        strategy.set_next_order(order)

        # 캔들 완성 시 주문 제출
        runner._on_trade(make_trade(price=50000.0))
        runner._on_trade(make_trade(price=50100.0))

        assert len(runner.trader.pending_orders) == 1

    def test_does_not_submit_duplicate_orders(self):
        """같은 방향의 중복 주문은 제출하지 않는다"""
        strategy = MockStrategy(quantity=0.01)
        runner = TickForwardRunner(
            strategy=strategy,
            candle_type=CandleType.TICK,
            candle_size=2,
        )

        # 첫 번째 BUY 주문
        order1 = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        strategy.set_next_order(order1)
        runner._on_trade(make_trade(price=50000.0))
        runner._on_trade(make_trade(price=50100.0))

        # 두 번째 BUY 주문 시도 (중복)
        order2 = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        strategy.set_next_order(order2)
        runner._on_trade(make_trade(price=50200.0))
        runner._on_trade(make_trade(price=50300.0))

        # 중복 주문은 무시됨
        assert len(runner.trader.pending_orders) == 1

    def test_increments_order_count(self):
        """주문 카운트가 증가한다"""
        strategy = MockStrategy(quantity=0.01)
        runner = TickForwardRunner(
            strategy=strategy,
            candle_type=CandleType.TICK,
            candle_size=2,
        )

        order = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        strategy.set_next_order(order)

        runner._on_trade(make_trade(price=50000.0))
        runner._on_trade(make_trade(price=50100.0))

        # order_count는 내부 변수 _order_count로 확인
        assert runner._order_count == 1


# === 체결 테스트 ===


class TestTradeExecution:
    """체결 테스트"""

    def test_executes_market_order_on_tick(self):
        """MARKET 주문은 다음 틱에서 체결된다"""
        strategy = MockStrategy(quantity=0.01)
        runner = TickForwardRunner(
            strategy=strategy,
            candle_type=CandleType.TICK,
            candle_size=2,
        )

        # BUY 주문 제출
        order = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        strategy.set_next_order(order)
        runner._on_trade(make_trade(price=50000.0))
        runner._on_trade(make_trade(price=50100.0))

        # 다음 틱에서 체결
        runner._on_trade(make_trade(price=50200.0))

        assert len(runner.trader.trades) == 1
        assert runner.trader.trades[0].side == Side.BUY

    def test_updates_unrealized_pnl(self):
        """미실현 손익이 업데이트된다"""
        strategy = MockStrategy(quantity=0.01)
        runner = TickForwardRunner(
            strategy=strategy,
            candle_type=CandleType.TICK,
            candle_size=2,
            leverage=1,
        )

        # BUY 주문 제출 및 체결
        order = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        strategy.set_next_order(order)
        runner._on_trade(make_trade(price=50000.0))
        runner._on_trade(make_trade(price=50000.0))
        runner._on_trade(make_trade(price=50000.0))  # 체결

        # 가격 상승 -> 미실현 이익
        runner._on_trade(make_trade(price=51000.0))

        # 미실현 손익 확인 (약 +$10)
        assert runner.trader.position.unrealized_pnl > 0


# === 성과 리포트 테스트 ===


class TestPerformanceReport:
    """성과 리포트 테스트"""

    def test_generates_report_with_no_trades(self):
        """거래 없이도 리포트를 생성한다"""
        strategy = MockStrategy()
        runner = TickForwardRunner(strategy=strategy)

        report = runner.get_performance_report()

        assert report is not None
        assert report.total_trades == 0
        assert report.initial_capital == 10000.0

    def test_generates_report_with_trades(self):
        """거래가 있으면 리포트에 반영된다"""
        strategy = MockStrategy(quantity=0.01)
        runner = TickForwardRunner(
            strategy=strategy,
            candle_type=CandleType.TICK,
            candle_size=2,
        )

        # BUY -> SELL 사이클
        buy_order = Order(side=Side.BUY, quantity=0.01, order_type=OrderType.MARKET)
        strategy.set_next_order(buy_order)
        runner._on_trade(make_trade(price=50000.0))
        runner._on_trade(make_trade(price=50000.0))
        runner._on_trade(make_trade(price=50000.0))  # BUY 체결

        sell_order = Order(side=Side.SELL, quantity=0.01, order_type=OrderType.MARKET)
        strategy.set_next_order(sell_order)
        runner._on_trade(make_trade(price=50500.0))
        runner._on_trade(make_trade(price=50500.0))
        runner._on_trade(make_trade(price=50500.0))  # SELL 체결

        report = runner.get_performance_report()

        assert report.total_trades == 2  # BUY + SELL


# === 레버리지 테스트 ===


class TestLeverage:
    """레버리지 테스트"""

    def test_spot_mode_with_leverage_1(self):
        """leverage=1은 현물 모드"""
        strategy = MockStrategy()
        runner = TickForwardRunner(strategy=strategy, leverage=1)

        assert runner.leverage == 1
        assert runner.trader.leverage == 1

    def test_futures_mode_with_leverage_10(self):
        """leverage=10은 선물 모드"""
        strategy = MockStrategy()
        runner = TickForwardRunner(strategy=strategy, leverage=10)

        assert runner.leverage == 10
        assert runner.trader.leverage == 10


# === 에러 처리 테스트 ===


class TestErrorHandling:
    """에러 처리 테스트"""

    def test_handles_error_gracefully(self, capsys):
        """에러를 우아하게 처리한다"""
        strategy = MockStrategy()
        runner = TickForwardRunner(strategy=strategy)

        # 에러 시뮬레이션
        runner._on_error(Exception("Test error"))

        captured = capsys.readouterr()
        assert "Error" in captured.out
        assert "Test error" in captured.out


# === 실제 데이터 통합 테스트 ===


@pytest.mark.integration
class TestRealDataIntegration:
    """
    실제 Binance WebSocket 데이터를 사용한 통합 테스트

    pytest -m integration 으로 실행
    네트워크 연결 필요
    """

    @pytest.mark.asyncio
    async def test_connects_to_binance_and_receives_ticks(self):
        """실제 바이낸스에 연결하여 틱 데이터를 수신한다"""
        strategy = MockStrategy()
        runner = TickForwardRunner(
            strategy=strategy,
            symbol="btcusdt",
            candle_type=CandleType.TICK,
            candle_size=10,  # 10틱마다 캔들
        )

        # 5초간 실행
        await runner.run(duration_seconds=5)

        # 틱을 수신했어야 함
        assert runner.tick_count > 0, "바이낸스에서 틱 데이터를 수신하지 못함"
        assert runner.last_trade_price > 0, "가격 데이터가 없음"

    @pytest.mark.asyncio
    async def test_builds_candles_from_real_data(self):
        """실제 데이터로 캔들을 빌드한다"""
        strategy = MockStrategy()
        runner = TickForwardRunner(
            strategy=strategy,
            symbol="btcusdt",
            candle_type=CandleType.TICK,
            candle_size=5,  # 5틱마다 캔들 (빠른 테스트)
        )

        # 10초간 실행
        await runner.run(duration_seconds=10)

        # 캔들이 생성되었어야 함
        assert runner.candle_count > 0, "캔들이 생성되지 않음"
        # 전략이 호출되었어야 함
        assert strategy.call_count > 0, "전략이 호출되지 않음"

    @pytest.mark.asyncio
    async def test_strategy_receives_valid_ohlcv(self):
        """전략이 유효한 OHLCV 데이터를 받는다"""
        strategy = MockStrategy()
        runner = TickForwardRunner(
            strategy=strategy,
            symbol="btcusdt",
            candle_type=CandleType.TICK,
            candle_size=5,
        )

        await runner.run(duration_seconds=10)

        # 마지막 상태 검증
        state = strategy.last_state
        if state is not None:
            # OHLCV가 유효해야 함
            assert state.open > 0, "open 가격이 0"
            assert state.high >= state.low, "high < low (비정상)"
            assert state.close > 0, "close 가격이 0"
            # high >= open, close >= low
            assert state.high >= state.open, "high < open"
            assert state.high >= state.close, "high < close"
            assert state.low <= state.open, "low > open"
            assert state.low <= state.close, "low > close"

    @pytest.mark.asyncio
    async def test_bb_squeeze_strategy_with_real_data(self):
        """BB Squeeze 전략이 실제 데이터로 동작한다"""
        strategy = BBSqueezeStrategy(
            quantity=0.01,
            bb_period=5,  # 빠른 테스트용 짧은 기간
            warmup_bars=10,
        )
        runner = TickForwardRunner(
            strategy=strategy,
            symbol="btcusdt",
            candle_type=CandleType.TICK,
            candle_size=3,  # 3틱마다 캔들
            leverage=10,
        )

        await runner.run(duration_seconds=15)

        # 캔들이 생성되고 전략이 처리됨
        assert runner.candle_count > 0, "캔들이 생성되지 않음"
        # BB Squeeze는 warmup 후에 동작하므로 거래가 없을 수 있음
        # 하지만 에러 없이 완료되어야 함

    @pytest.mark.asyncio
    async def test_generates_report_after_real_run(self):
        """실제 실행 후 리포트가 생성된다"""
        strategy = MockStrategy()
        runner = TickForwardRunner(
            strategy=strategy,
            symbol="btcusdt",
            candle_type=CandleType.TICK,
            candle_size=5,
        )

        await runner.run(duration_seconds=8)

        report = runner.get_performance_report()

        # 리포트 필수 필드 검증
        assert report.strategy_name == "MockStrategy"
        assert report.symbol == "BTCUSDT"
        assert report.initial_capital == 10000.0
        assert report.start_time is not None
        assert report.end_time is not None
        assert report.end_time > report.start_time

    @pytest.mark.asyncio
    async def test_time_candle_builds_correctly(self):
        """TIME 캔들이 정확한 시간 간격으로 생성된다"""
        strategy = MockStrategy()
        runner = TickForwardRunner(
            strategy=strategy,
            symbol="btcusdt",
            candle_type=CandleType.TIME,
            candle_size=3,  # 3초마다 캔들
        )

        await runner.run(duration_seconds=10)

        # 약 3개 캔들 생성 기대 (10초 / 3초 = 3.3)
        assert runner.candle_count >= 2, f"TIME 캔들 생성 부족: {runner.candle_count}개"
        assert runner.candle_count <= 5, f"TIME 캔들 과다 생성: {runner.candle_count}개"
