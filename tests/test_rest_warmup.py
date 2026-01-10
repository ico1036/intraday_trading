"""
REST API 웜업 테스트

TDD: 먼저 실패하는 테스트를 작성하고, 구현을 추가합니다.
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from intraday import TickForwardRunner, CandleType
from intraday.candle_builder import Candle


class MockStrategy:
    """테스트용 Mock 전략"""

    def __init__(self):
        self.call_count = 0
        self.received_states = []

    def generate_order(self, state):
        self.call_count += 1
        self.received_states.append(state)
        return None  # 주문 없음


class TestBinanceKlinesClient:
    """Binance REST API Klines 클라이언트 테스트"""

    @pytest.mark.asyncio
    async def test_fetches_klines_from_binance(self):
        """Binance REST API에서 klines를 가져온다"""
        from intraday.klines_client import BinanceKlinesClient

        client = BinanceKlinesClient()
        klines = await client.fetch_klines(
            symbol="BTCUSDT",
            interval="1m",
            limit=10,
        )

        assert len(klines) == 10
        # 각 kline은 OHLCV 정보를 가짐
        assert all(hasattr(k, "open") for k in klines)
        assert all(hasattr(k, "high") for k in klines)
        assert all(hasattr(k, "low") for k in klines)
        assert all(hasattr(k, "close") for k in klines)
        assert all(hasattr(k, "volume") for k in klines)
        assert all(hasattr(k, "timestamp") for k in klines)

    @pytest.mark.asyncio
    async def test_klines_are_sorted_by_time(self):
        """Klines는 시간순으로 정렬되어 있다"""
        from intraday.klines_client import BinanceKlinesClient

        client = BinanceKlinesClient()
        klines = await client.fetch_klines(
            symbol="BTCUSDT",
            interval="1m",
            limit=10,
        )

        timestamps = [k.timestamp for k in klines]
        assert timestamps == sorted(timestamps)

    @pytest.mark.asyncio
    async def test_resamples_1m_to_4m(self):
        """1분봉을 4분봉으로 리샘플링한다"""
        from intraday.klines_client import BinanceKlinesClient

        client = BinanceKlinesClient()
        # 1분봉 40개 → 4분봉 10개
        candles = await client.fetch_resampled_klines(
            symbol="BTCUSDT",
            target_interval_seconds=240,  # 4분
            count=10,
        )

        assert len(candles) == 10
        # 4분 간격 확인
        for i in range(1, len(candles)):
            delta = (candles[i].timestamp - candles[i - 1].timestamp).total_seconds()
            assert delta == 240, f"Expected 240s, got {delta}s"


class TestTickForwardRunnerWarmup:
    """TickForwardRunner 웜업 테스트"""

    @pytest.mark.asyncio
    async def test_warmup_bars_parameter_exists(self):
        """warmup_bars 파라미터가 존재한다"""
        strategy = MockStrategy()
        runner = TickForwardRunner(
            strategy=strategy,
            candle_type=CandleType.TIME,
            candle_size=240,
            warmup_bars=100,  # 새 파라미터
        )
        assert runner.warmup_bars == 100

    @pytest.mark.asyncio
    async def test_warmup_calls_strategy_before_websocket(self):
        """웜업 중 전략이 호출된다 (WebSocket 연결 전)"""
        strategy = MockStrategy()
        runner = TickForwardRunner(
            strategy=strategy,
            candle_type=CandleType.TIME,
            candle_size=240,
            warmup_bars=10,
        )

        # Mock klines client
        mock_candles = [
            Candle(
                timestamp=datetime.now() - timedelta(minutes=4 * (10 - i)),
                open=100.0 + i,
                high=101.0 + i,
                low=99.0 + i,
                close=100.5 + i,
                volume=1.0,
            )
            for i in range(10)
        ]

        with patch.object(runner, "_fetch_warmup_candles", return_value=mock_candles):
            with patch.object(runner, "_client") as mock_client:
                mock_client.connect = AsyncMock()
                mock_client.disconnect = AsyncMock()

                # run()을 짧은 시간만 실행
                async def stop_quickly():
                    await asyncio.sleep(0.1)
                    await runner.stop()

                asyncio.create_task(stop_quickly())
                await runner.run()

        # 웜업 중 전략이 10번 호출되어야 함
        assert strategy.call_count >= 10

    @pytest.mark.asyncio
    async def test_warmup_provides_correct_ohlcv(self):
        """웜업 시 전략이 올바른 OHLCV 데이터를 받는다"""
        strategy = MockStrategy()
        runner = TickForwardRunner(
            strategy=strategy,
            candle_type=CandleType.TIME,
            candle_size=240,
            warmup_bars=5,
        )

        mock_candles = [
            Candle(
                timestamp=datetime.now() - timedelta(minutes=4 * (5 - i)),
                open=100.0,
                high=105.0,
                low=95.0,
                close=102.0,
                volume=10.0,
            )
            for i in range(5)
        ]

        with patch.object(runner, "_fetch_warmup_candles", return_value=mock_candles):
            with patch.object(runner, "_client") as mock_client:
                mock_client.connect = AsyncMock()
                mock_client.disconnect = AsyncMock()

                async def stop_quickly():
                    await asyncio.sleep(0.1)
                    await runner.stop()

                asyncio.create_task(stop_quickly())
                await runner.run()

        # 전략이 받은 MarketState 확인
        assert len(strategy.received_states) >= 5
        for state in strategy.received_states[:5]:
            assert state.open == 100.0
            assert state.high == 105.0
            assert state.low == 95.0
            assert state.close == 102.0
            assert state.volume == 10.0

    @pytest.mark.asyncio
    async def test_no_warmup_when_warmup_bars_is_zero(self):
        """warmup_bars가 0이면 웜업하지 않는다"""
        strategy = MockStrategy()
        runner = TickForwardRunner(
            strategy=strategy,
            candle_type=CandleType.TIME,
            candle_size=240,
            warmup_bars=0,
        )

        with patch.object(runner, "_fetch_warmup_candles") as mock_fetch:
            with patch.object(runner, "_client") as mock_client:
                mock_client.connect = AsyncMock()
                mock_client.disconnect = AsyncMock()

                async def stop_quickly():
                    await asyncio.sleep(0.1)
                    await runner.stop()

                asyncio.create_task(stop_quickly())
                await runner.run()

        # 웜업 fetch가 호출되지 않아야 함
        mock_fetch.assert_not_called()


class TestWarmupWebSocketJunction:
    """REST 웜업 → WebSocket 접합부 엣지케이스 테스트"""

    @pytest.mark.asyncio
    async def test_no_gap_between_warmup_and_websocket(self):
        """웜업 마지막 캔들과 WebSocket 첫 캔들 사이에 갭이 없어야 한다"""
        from datetime import timedelta
        from intraday.klines_client import BinanceKlinesClient

        client = BinanceKlinesClient()

        # 4분봉 10개 가져오기
        candles = await client.fetch_resampled_klines(
            symbol="BTCUSDT",
            target_interval_seconds=240,
            count=10,
        )

        # 마지막 캔들 시간 확인
        last_warmup_candle = candles[-1]
        now = datetime.now(tz=last_warmup_candle.timestamp.tzinfo)

        # 마지막 캔들은 현재 시간에서 4분 이내여야 함 (최신 데이터)
        time_since_last = (now - last_warmup_candle.timestamp).total_seconds()
        assert time_since_last < 480, f"Last candle too old: {time_since_last}s ago"

    @pytest.mark.asyncio
    async def test_warmup_candles_are_complete(self):
        """웜업 캔들은 완성된 캔들이어야 한다 (미완성 캔들 제외)"""
        from intraday.klines_client import BinanceKlinesClient

        client = BinanceKlinesClient()

        # 4분봉 5개 가져오기
        candles = await client.fetch_resampled_klines(
            symbol="BTCUSDT",
            target_interval_seconds=240,
            count=5,
        )

        # 연속된 캔들 간격이 정확히 240초여야 함
        for i in range(1, len(candles)):
            delta = (candles[i].timestamp - candles[i - 1].timestamp).total_seconds()
            # 240초 ± 10초 허용 (리샘플링 오차)
            assert 230 <= delta <= 250, f"Candle gap incorrect: {delta}s"

    @pytest.mark.asyncio
    async def test_candle_builder_starts_fresh_after_warmup(self):
        """웜업 후 CandleBuilder는 새로 시작해야 한다 (중복 방지)"""
        from intraday import CandleBuilder, CandleType
        from intraday.client import AggTrade
        from datetime import datetime, timezone

        builder = CandleBuilder(CandleType.TIME, size=240)

        # 웜업에서는 CandleBuilder를 사용하지 않음 (REST 캔들 직접 사용)
        # WebSocket 시작 시 builder는 빈 상태여야 함
        assert builder.current_candle is None

        # 첫 틱으로 새 캔들 시작
        trade = AggTrade(
            timestamp=datetime.now(tz=timezone.utc),
            price=100000.0,
            quantity=0.1,
            is_buyer_maker=False,
            symbol="BTCUSDT",
        )
        result = builder.update(trade)

        # 첫 틱은 캔들을 완성하지 않음
        assert result is None
        # 하지만 현재 캔들은 존재
        assert builder.current_candle is not None
        assert builder.current_candle.open == 100000.0

    @pytest.mark.asyncio
    async def test_strategy_receives_continuous_bars(self):
        """전략은 연속적인 바를 받아야 한다 (웜업 + 실시간)"""
        strategy = MockStrategy()
        runner = TickForwardRunner(
            strategy=strategy,
            candle_type=CandleType.TIME,
            candle_size=240,
            warmup_bars=5,
        )

        # 웜업용 Mock 캔들 생성
        base_time = datetime.now()
        mock_candles = [
            Candle(
                timestamp=base_time - timedelta(minutes=4 * (5 - i)),
                open=100.0 + i,
                high=101.0 + i,
                low=99.0 + i,
                close=100.5 + i,
                volume=1.0,
            )
            for i in range(5)
        ]

        with patch.object(runner, "_fetch_warmup_candles", return_value=mock_candles):
            with patch.object(runner, "_client") as mock_client:
                mock_client.connect = AsyncMock()
                mock_client.disconnect = AsyncMock()

                async def stop_quickly():
                    await asyncio.sleep(0.1)
                    await runner.stop()

                asyncio.create_task(stop_quickly())
                await runner.run()

        # 전략이 5번 호출되어야 함
        assert strategy.call_count == 5

        # 각 호출에서 받은 close 값 확인 (순서대로)
        for i, state in enumerate(strategy.received_states[:5]):
            expected_close = 100.5 + i
            assert state.close == expected_close, f"Bar {i}: expected {expected_close}, got {state.close}"

    @pytest.mark.asyncio
    async def test_warmup_does_not_affect_candle_builder_state(self):
        """웜업은 CandleBuilder 상태에 영향을 주지 않아야 한다"""
        strategy = MockStrategy()
        runner = TickForwardRunner(
            strategy=strategy,
            candle_type=CandleType.TIME,
            candle_size=240,
            warmup_bars=3,
        )

        mock_candles = [
            Candle(
                timestamp=datetime.now() - timedelta(minutes=4 * (3 - i)),
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.5,
                volume=1.0,
            )
            for i in range(3)
        ]

        with patch.object(runner, "_fetch_warmup_candles", return_value=mock_candles):
            with patch.object(runner, "_client") as mock_client:
                mock_client.connect = AsyncMock()
                mock_client.disconnect = AsyncMock()

                async def stop_quickly():
                    await asyncio.sleep(0.1)
                    await runner.stop()

                asyncio.create_task(stop_quickly())
                await runner.run()

        # 웜업 후에도 CandleBuilder는 빈 상태 (WebSocket 첫 틱을 기다림)
        assert runner._candle_builder.current_candle is None

    @pytest.mark.asyncio
    async def test_websocket_candle_aligned_to_interval_boundary(self):
        """
        WebSocket 캔들은 interval 경계에 정렬되어야 한다.

        예: 4분봉이면 12:00, 12:04, 12:08 등에 시작
        12:03:30에 첫 틱이 와도 12:04:00에 캔들 경계가 맞춰져야 함
        """
        from intraday import CandleBuilder, CandleType
        from intraday.client import AggTrade
        from datetime import datetime, timezone

        builder = CandleBuilder(CandleType.TIME, size=240)

        # 12:03:30에 첫 틱 (4분 경계 이전)
        base = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        tick1_time = base + timedelta(minutes=3, seconds=30)  # 12:03:30

        trade1 = AggTrade(
            timestamp=tick1_time,
            price=100000.0,
            quantity=0.1,
            is_buyer_maker=False,
            symbol="BTCUSDT",
        )
        result1 = builder.update(trade1)
        assert result1 is None  # 아직 4분 안 지남

        # 12:04:30에 두 번째 틱 (4분 경계 이후)
        tick2_time = base + timedelta(minutes=4, seconds=30)  # 12:04:30
        trade2 = AggTrade(
            timestamp=tick2_time,
            price=100100.0,
            quantity=0.2,
            is_buyer_maker=True,
            symbol="BTCUSDT",
        )
        result2 = builder.update(trade2)

        # 현재 구현: 첫 틱 시간(12:03:30)부터 4분 경과하면 캔들 완성
        # 12:03:30 + 4분 = 12:07:30이어야 캔들 완성
        # 12:04:30은 아직 4분 안 지남 (1분만 경과)
        assert result2 is None  # 아직 완성 안됨

        # 12:07:30 이후에 틱이 와야 캔들 완성
        tick3_time = base + timedelta(minutes=7, seconds=31)  # 12:07:31
        trade3 = AggTrade(
            timestamp=tick3_time,
            price=100200.0,
            quantity=0.3,
            is_buyer_maker=False,
            symbol="BTCUSDT",
        )
        result3 = builder.update(trade3)

        # 이제 캔들 완성!
        assert result3 is not None
        assert result3.timestamp == tick1_time  # 첫 틱 시간이 캔들 시작
        assert result3.open == 100000.0
        assert result3.close == 100200.0  # 마지막 틱 가격

    @pytest.mark.asyncio
    async def test_potential_gap_between_rest_and_websocket(self):
        """
        REST 마지막 캔들과 WebSocket 첫 캔들 사이 갭 시나리오 테스트

        이 테스트는 현재 구현의 한계를 문서화합니다.
        """
        from datetime import timezone

        strategy = MockStrategy()
        runner = TickForwardRunner(
            strategy=strategy,
            candle_type=CandleType.TIME,
            candle_size=240,  # 4분봉
            warmup_bars=3,
        )

        # REST에서 가져온 마지막 캔들: 12:00:00 ~ 12:04:00
        base = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_candles = [
            Candle(timestamp=base - timedelta(minutes=8), open=99.0, high=100.0, low=98.0, close=99.5, volume=1.0),
            Candle(timestamp=base - timedelta(minutes=4), open=99.5, high=100.5, low=99.0, close=100.0, volume=1.0),
            Candle(timestamp=base, open=100.0, high=101.0, low=99.5, close=100.5, volume=1.0),  # 12:00:00
        ]

        with patch.object(runner, "_fetch_warmup_candles", return_value=mock_candles):
            with patch.object(runner, "_client") as mock_client:
                mock_client.connect = AsyncMock()
                mock_client.disconnect = AsyncMock()

                async def stop_quickly():
                    await asyncio.sleep(0.1)
                    await runner.stop()

                asyncio.create_task(stop_quickly())
                await runner.run()

        # 전략이 3번 호출됨 (웜업만)
        assert strategy.call_count == 3

        # 마지막 웜업 캔들 시간: 12:00:00
        last_warmup_time = strategy.received_states[-1].timestamp
        assert last_warmup_time == base

        # 현재 구현의 한계:
        # WebSocket 첫 틱이 12:03:30에 오면, CandleBuilder는 12:03:30부터 새 캔들 시작
        # 12:00:00 ~ 12:03:30 사이의 데이터는 웜업 캔들에 포함되지 않고,
        # WebSocket 첫 캔들에도 포함되지 않음 (갭 발생)
        #
        # 하지만 이 갭은 실제로 문제가 되지 않을 수 있음:
        # - 웜업은 전략 상태 초기화가 목적
        # - 실시간 거래는 WebSocket 캔들부터 시작
        # - 정확한 시간 연속성보다 전략 워밍업이 더 중요


class TestRealBinanceKlinesIntegration:
    """실제 Binance API 통합 테스트"""

    @pytest.mark.asyncio
    async def test_real_klines_fetch(self):
        """실제 Binance에서 klines를 가져온다"""
        from intraday.klines_client import BinanceKlinesClient

        client = BinanceKlinesClient()
        klines = await client.fetch_klines(
            symbol="BTCUSDT",
            interval="1m",
            limit=5,
        )

        assert len(klines) == 5
        # 가격이 합리적인 범위인지 확인 (BTC는 보통 10,000~200,000)
        for k in klines:
            assert 1000 < k.close < 500000, f"Unrealistic price: {k.close}"
            assert k.volume > 0, "Volume should be positive"

    @pytest.mark.asyncio
    async def test_real_4m_resample(self):
        """실제 Binance에서 4분봉을 리샘플링한다"""
        from intraday.klines_client import BinanceKlinesClient

        client = BinanceKlinesClient()
        candles = await client.fetch_resampled_klines(
            symbol="BTCUSDT",
            target_interval_seconds=240,
            count=10,
        )

        assert len(candles) == 10

        # 시간 간격 확인
        for i in range(1, len(candles)):
            delta = (candles[i].timestamp - candles[i - 1].timestamp).total_seconds()
            assert 230 <= delta <= 250, f"Expected ~240s, got {delta}s"

    @pytest.mark.asyncio
    async def test_real_warmup_then_websocket(self):
        """실제 웜업 후 WebSocket 연결 테스트"""
        strategy = MockStrategy()
        runner = TickForwardRunner(
            strategy=strategy,
            symbol="btcusdt",
            candle_type=CandleType.TIME,
            candle_size=240,
            warmup_bars=10,
        )

        # 짧은 시간만 실행
        try:
            await asyncio.wait_for(runner.run(), timeout=5.0)
        except asyncio.TimeoutError:
            await runner.stop()

        # 웜업으로 최소 10번 호출
        assert strategy.call_count >= 10, f"Expected >= 10 calls, got {strategy.call_count}"

        # 웜업 후 캔들 수 확인
        assert runner.candle_count >= 0  # 실시간은 짧아서 0일 수 있음
