"""
MarketState OHLCV 필드 테스트

Tick 기반 전략이 캔들의 OHLCV 데이터를 받을 수 있어야 한다.
"""

import pytest
from datetime import datetime
from pathlib import Path
import tempfile

from intraday.strategy import MarketState, Side


class TestMarketStateOHLCV:
    """MarketState에 OHLCV 필드가 있어야 함"""

    def test_market_state_has_ohlcv_fields(self):
        """MarketState가 OHLCV 필드를 가져야 함"""
        state = MarketState(
            timestamp=datetime.now(),
            mid_price=100.0,
            imbalance=0.1,
            spread=0.0,
            spread_bps=0.0,
            best_bid=100.0,
            best_ask=100.0,
            best_bid_qty=1.0,
            best_ask_qty=1.0,
            # OHLCV 필드
            open=99.0,
            high=101.0,
            low=98.0,
            close=100.0,
            volume=10.0,
            vwap=99.5,
        )

        assert state.open == 99.0
        assert state.high == 101.0
        assert state.low == 98.0
        assert state.close == 100.0
        assert state.volume == 10.0
        assert state.vwap == 99.5

    def test_ohlcv_fields_are_optional(self):
        """OHLCV 필드는 옵셔널 (Orderbook Runner는 캔들 없음)"""
        state = MarketState(
            timestamp=datetime.now(),
            mid_price=100.0,
            imbalance=0.1,
            spread=1.0,
            spread_bps=10.0,
            best_bid=99.5,
            best_ask=100.5,
            best_bid_qty=1.0,
            best_ask_qty=1.0,
        )

        # 기본값 None
        assert state.open is None
        assert state.high is None
        assert state.low is None
        assert state.close is None
        assert state.volume is None
        assert state.vwap is None


class TestTickRunnerProvidesOHLCV:
    """TickBacktestRunner가 OHLCV를 전략에 전달해야 함"""

    def test_tick_runner_passes_ohlcv_to_strategy(self, tmp_path):
        """TickRunner가 MarketState에 OHLCV를 포함해야 함"""
        import pandas as pd
        from intraday.backtest import TickBacktestRunner
        from intraday.data import TickDataLoader
        from intraday import CandleType
        from intraday.strategies.base import StrategyBase, Order

        # 캡처용 전략
        captured_states = []

        class CaptureStrategy(StrategyBase):
            def setup(self):
                pass

            def should_buy(self, state: MarketState) -> bool:
                captured_states.append(state)
                return False

            def should_sell(self, state: MarketState) -> bool:
                return False

        # 테스트 데이터 생성
        data_file = tmp_path / "test.parquet"
        df = pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=100, freq="1s"),
            "price": [100.0 + i * 0.1 for i in range(100)],  # 상승 추세
            "quantity": [1.0] * 100,
            "is_buyer_maker": [i % 2 == 0 for i in range(100)],
        })
        df.to_parquet(data_file)

        # 실행
        loader = TickDataLoader(tmp_path)
        strategy = CaptureStrategy(quantity=0.01)
        runner = TickBacktestRunner(
            strategy=strategy,
            data_loader=loader,
            bar_type=CandleType.TICK,
            bar_size=10,  # 10틱마다 캔들
        )
        runner.run()

        # 검증: 전략이 받은 MarketState에 OHLCV가 있어야 함
        assert len(captured_states) > 0, "전략이 호출되어야 함"

        state = captured_states[0]
        assert state.open is not None, "open 필드가 있어야 함"
        assert state.high is not None, "high 필드가 있어야 함"
        assert state.low is not None, "low 필드가 있어야 함"
        assert state.close is not None, "close 필드가 있어야 함"
        assert state.volume is not None, "volume 필드가 있어야 함"
        assert state.vwap is not None, "vwap 필드가 있어야 함"

        # OHLCV 값 검증
        assert state.high >= state.low, "high >= low"
        assert state.high >= state.open, "high >= open"
        assert state.high >= state.close, "high >= close"
        assert state.low <= state.open, "low <= open"
        assert state.low <= state.close, "low <= close"
        assert state.volume > 0, "volume > 0"
