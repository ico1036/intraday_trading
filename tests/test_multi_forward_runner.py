"""
포트폴리오 Forward Test 러너 테스트

TDD: 여러 코인 실시간 데이터로 포트폴리오 전략 Forward Test
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch

import pandas as pd
import pytest

from intraday.candle_builder import Candle, CandleType
from intraday.klines_client import Kline
from intraday.strategies.multi import PortfolioMomentum, PairTradingStrategy
from intraday.multi_forward_runner import (
    PortfolioForwardRunner,
    SymbolState,
)
from intraday.strategy import Order, OrderType, PortfolioOrder, Side
from scripts.run_portfolio_forward_test import build_strategy
from types import SimpleNamespace


class FixedLongOnceForwardStrategy:
    """첫 패널 수신 시 지정 수량 LONG을 한 번 낸다."""

    def __init__(self, symbol: str, quantity: float):
        self.symbol = symbol
        self.quantity = quantity
        self.done = False

    def generate_order(self, state):
        if self.done or state.panel is None:
            return None
        self.done = True
        return PortfolioOrder(
            orders={
                self.symbol: Order(
                    side=Side.BUY,
                    quantity=self.quantity,
                    order_type=OrderType.MARKET,
                )
            }
        )


def _kline(ts: datetime, close: float, **kwargs) -> Kline:
    """Test helper: build a closed kline at ``ts`` with constant OHLC=close."""
    return Kline(
        timestamp=ts, open=kwargs.get("open", close),
        high=kwargs.get("high", close), low=kwargs.get("low", close), close=close,
        volume=kwargs.get("volume", 10.0),
        quote_volume=kwargs.get("quote_volume", close * 10.0),
        trade_count=kwargs.get("trade_count", 100),
        taker_buy_volume=kwargs.get("taker_buy_volume", 5.0),
        taker_buy_quote_volume=kwargs.get("taker_buy_quote_volume", close * 5.0),
        is_closed=True,
    )


class TestSymbolState:
    """심볼별 상태 관리 테스트"""

    def test_init(self):
        state = SymbolState(symbol="BTCUSDT")
        assert state.symbol == "BTCUSDT"
        assert state.last_price == 0.0
        assert state.candle_count == 0
        assert state.last_candle is None

    def test_on_kline_close_updates_price_and_history(self):
        state = SymbolState(symbol="BTCUSDT")
        for i, close in enumerate([50000, 50100, 50200, 49900, 50050]):
            ts = datetime(2026, 1, 1) + timedelta(minutes=i)
            state.on_kline_close(Candle(
                timestamp=ts, open=close, high=close, low=close, close=close,
                volume=10.0, quote_volume=close * 10.0,
                trade_count=100, buy_volume=5.0, sell_volume=5.0,
            ))

        assert state.last_price == 50050
        assert state.candle_count == 5
        history = state.get_price_history()
        assert len(history) == 5
        assert history.iloc[-1] == 50050


class TestPortfolioForwardRunner:
    """포트폴리오 Forward Runner 테스트"""

    def test_init_with_momentum(self):
        """Momentum 전략으로 초기화"""
        strategy = PortfolioMomentum(
            symbols=["BTCUSDT", "ETHUSDT"],
            lookback_minutes=60,
            top_n=1,
            bottom_n=1,
        )

        runner = PortfolioForwardRunner(
            strategy=strategy,
            symbols=["BTCUSDT", "ETHUSDT"],
            candle_type=CandleType.TIME,
            candle_size=300,
            initial_capital=10000,
        )

        assert len(runner.symbol_states) == 2
        assert "BTCUSDT" in runner.symbol_states
        assert "ETHUSDT" in runner.symbol_states

    def test_init_with_pair(self):
        """Pair Trading 전략으로 초기화"""
        strategy = PairTradingStrategy(
            coin_a="BTCUSDT",
            coin_b="ETHUSDT",
            zscore_entry=2.0,
            zscore_exit=0.5,
            lookback=60,
        )

        runner = PortfolioForwardRunner(
            strategy=strategy,
            symbols=["BTCUSDT", "ETHUSDT"],
            candle_type=CandleType.TIME,
            candle_size=300,
            initial_capital=10000,
        )

        assert len(runner.symbol_states) == 2

    def test_process_trade(self):
        """거래 데이터 처리"""
        strategy = PortfolioMomentum(
            symbols=["BTCUSDT", "ETHUSDT"],
            lookback_minutes=60,
            top_n=1,
            bottom_n=0,
        )

        runner = PortfolioForwardRunner(
            strategy=strategy,
            symbols=["BTCUSDT", "ETHUSDT"],
            candle_type=CandleType.TIME,
            candle_size=300,
            initial_capital=10000,
        )

        runner.on_kline_close("BTCUSDT", _kline(datetime.now(), 50000))
        assert runner.symbol_states["BTCUSDT"].last_price == 50000

    def test_rebalance_check(self):
        """리밸런싱 시점 확인"""
        strategy = PortfolioMomentum(
            symbols=["BTCUSDT", "ETHUSDT"],
            lookback_minutes=5,
            top_n=1,
            bottom_n=0,
        )

        runner = PortfolioForwardRunner(
            strategy=strategy,
            symbols=["BTCUSDT", "ETHUSDT"],
            candle_type=CandleType.TIME,
            candle_size=300,
            initial_capital=10000,
            rebalance_minutes=10,
        )

        # 시작 시점
        assert runner.should_rebalance(datetime.now()) is False

        # 10분 후
        runner._last_rebalance_time = datetime.now() - timedelta(minutes=11)
        assert runner.should_rebalance(datetime.now()) is True

    def test_get_current_prices(self):
        """현재 가격 조회"""
        strategy = PortfolioMomentum(
            symbols=["BTCUSDT", "ETHUSDT"],
            lookback_minutes=5,
            top_n=1,
            bottom_n=0,
        )

        runner = PortfolioForwardRunner(
            strategy=strategy,
            symbols=["BTCUSDT", "ETHUSDT"],
            candle_type=CandleType.TIME,
            candle_size=300,
            initial_capital=10000,
        )

        runner.on_kline_close("BTCUSDT", _kline(datetime.now(), 50000))
        runner.on_kline_close("ETHUSDT", _kline(datetime.now(), 3000))

        prices = runner.get_current_prices()
        assert prices["BTCUSDT"] == 50000
        assert prices["ETHUSDT"] == 3000

    def test_status_report(self):
        """상태 리포트"""
        strategy = PortfolioMomentum(
            symbols=["BTCUSDT", "ETHUSDT"],
            lookback_minutes=5,
            top_n=1,
            bottom_n=0,
        )

        runner = PortfolioForwardRunner(
            strategy=strategy,
            symbols=["BTCUSDT", "ETHUSDT"],
            candle_type=CandleType.TIME,
            candle_size=300,
            initial_capital=10000,
        )

        report = runner.get_status()

        assert "capital" in report
        assert "positions" in report
        assert "symbols" in report

    def test_runner_rejects_unsupported_candle_size(self):
        """candle_size must map to a Binance kline interval."""
        strategy = PortfolioMomentum(symbols=["BTCUSDT"], lookback_minutes=5, top_n=1, bottom_n=0)
        with pytest.raises(ValueError, match="unsupported candle size"):
            PortfolioForwardRunner(
                strategy=strategy,
                symbols=["BTCUSDT"],
                candle_type=CandleType.TIME,
                candle_size=137,  # not a Binance interval
            )

    def test_on_kline_close_drives_rebalance(self):
        """Feeding closed klines via on_kline_close triggers the rebalance path."""
        strategy = PortfolioMomentum(
            symbols=["BTCUSDT", "ETHUSDT"],
            lookback_minutes=1,
            top_n=1,
            bottom_n=0,
        )
        runner = PortfolioForwardRunner(
            strategy=strategy,
            symbols=["BTCUSDT", "ETHUSDT"],
            candle_type=CandleType.TIME,
            candle_size=60,
            rebalance_minutes=1,
        )
        runner._start_time = datetime(2026, 5, 17, 0, 0, 0)
        runner._last_rebalance_time = runner._start_time - timedelta(minutes=2)

        # Replay two closed klines (one per symbol) — symbol_states should
        # receive the candle and candle_count should increment.
        ts = datetime(2026, 5, 17, 0, 1, 0)
        for sym, close in [("BTCUSDT", 80_000.0), ("ETHUSDT", 2_500.0)]:
            kline = Kline(
                timestamp=ts, open=close, high=close, low=close, close=close,
                volume=10.0, quote_volume=close * 10.0, trade_count=100,
                taker_buy_volume=5.0, taker_buy_quote_volume=close * 5.0,
            )
            runner.on_kline_close(sym, kline)

        assert runner.symbol_states["BTCUSDT"].candle_count == 1
        assert runner.symbol_states["ETHUSDT"].candle_count == 1
        assert runner.symbol_states["BTCUSDT"].last_candle is not None
        assert runner.symbol_states["BTCUSDT"].last_candle.quote_volume == 800_000.0

    def test_auto_save_loop_persists_to_disk(self, tmp_path):
        """auto_save_output_dir set → _auto_save_loop writes save_report to disk."""
        strategy = PortfolioMomentum(
            symbols=["BTCUSDT", "ETHUSDT"],
            lookback_minutes=60,
            top_n=1,
            bottom_n=1,
        )
        runner = PortfolioForwardRunner(
            strategy=strategy,
            symbols=["BTCUSDT", "ETHUSDT"],
            candle_type=CandleType.TIME,
            candle_size=300,
            initial_capital=10000,
            rebalance_minutes=10,
            run_id="autosave_test",
            auto_save_interval_seconds=0.05,
            auto_save_output_dir=str(tmp_path),
        )

        client = AsyncMock()
        client.connect = AsyncMock()
        client.stop = AsyncMock()

        with patch("intraday.multi_forward_runner.BinanceKlineStreamClient", return_value=client):
            asyncio.run(runner.run(duration_seconds=0.25))

        run_dir = tmp_path / "autosave_test"
        assert run_dir.exists(), "save_report should have created the run directory mid-run"
        assert (run_dir / "summary.json").exists()
        assert (run_dir / "portfolio_nav.parquet").exists()

    def test_run_stops_on_duration(self):
        """duration으로 종료 시 정상 stop 보장"""
        strategy = PortfolioMomentum(
            symbols=["BTCUSDT", "ETHUSDT"],
            lookback_minutes=60,
            top_n=1,
            bottom_n=1,
        )

        runner = PortfolioForwardRunner(
            strategy=strategy,
            symbols=["BTCUSDT", "ETHUSDT"],
            candle_type=CandleType.TIME,
            candle_size=300,
            initial_capital=10000,
            rebalance_minutes=10,
        )

        client = AsyncMock()
        client.connect = AsyncMock()
        client.stop = AsyncMock()

        with patch("intraday.multi_forward_runner.BinanceKlineStreamClient", return_value=client):
            asyncio.run(runner.run(duration_seconds=0.2))

        assert not runner._running
        assert runner._start_time is not None

    def test_run_stops_on_zero_duration(self):
        """duration=0도 무한 실행이 아니라 즉시 종료로 처리"""
        strategy = PortfolioMomentum(
            symbols=["BTCUSDT", "ETHUSDT"],
            lookback_minutes=60,
            top_n=1,
            bottom_n=1,
        )

        runner = PortfolioForwardRunner(
            strategy=strategy,
            symbols=["BTCUSDT", "ETHUSDT"],
            candle_type=CandleType.TIME,
            candle_size=300,
            initial_capital=10000,
            rebalance_minutes=10,
        )

        client = AsyncMock()
        client.connect = AsyncMock()
        client.stop = AsyncMock()

        with patch("intraday.multi_forward_runner.BinanceKlineStreamClient", return_value=client):
            asyncio.run(runner.run(duration_seconds=0))

        assert not runner._running
        # Kline runner uses a single combined-stream client; one stop call.
        assert client.stop.await_count == 1

    def test_rebalance_updates_last_time_for_momentum(self):
        """momentum 파이프라인에서도 리밸런스 타임스탬프가 갱신되는지 확인"""
        strategy = PortfolioMomentum(
            symbols=["BTCUSDT", "ETHUSDT"],
            lookback_minutes=5,
            top_n=1,
            bottom_n=1,
        )

        runner = PortfolioForwardRunner(
            strategy=strategy,
            symbols=["BTCUSDT", "ETHUSDT"],
            candle_type=CandleType.TIME,
            candle_size=300,
            initial_capital=10000,
            rebalance_minutes=10,
        )

        # 가격 히스토리 확보
        runner.symbol_states["BTCUSDT"].last_price = 50000
        runner.symbol_states["ETHUSDT"].last_price = 3000
        now = datetime.now()
        runner.symbol_states["BTCUSDT"]._price_history.extend([49900, 50000])
        runner.symbol_states["BTCUSDT"]._price_timestamps.extend([now, now + timedelta(seconds=1)])
        runner.symbol_states["ETHUSDT"]._price_history.extend([29900, 30000])
        runner.symbol_states["ETHUSDT"]._price_timestamps.extend([now, now + timedelta(seconds=1)])

        ts = datetime.now()
        cb = Candle(
            timestamp=ts,
            open=50000,
            high=50000,
            low=50000,
            close=50000,
            volume=1.0,
            quote_volume=1.0,
            trade_count=1,
            buy_volume=1.0,
            sell_volume=0.0,
        )
        runner._last_rebalance_time = ts - timedelta(minutes=11)

        runner._execute_rebalance("BTCUSDT", cb, ts)
        assert runner._last_rebalance_time == ts

    def test_execute_signal_close_and_long_short(self):
        """CLOSE_AND_* 시그널이 실제 방향 전환으로 동작"""
        strategy = PortfolioMomentum(
            symbols=["BTCUSDT", "ETHUSDT"],
            lookback_minutes=5,
            top_n=1,
            bottom_n=1,
        )

        runner = PortfolioForwardRunner(
            strategy=strategy,
            symbols=["BTCUSDT", "ETHUSDT"],
            candle_type=CandleType.TIME,
            candle_size=300,
            initial_capital=10000,
        )

        # 기존 숏 보유
        runner.position.open("BTCUSDT", "SHORT", price=50000, quantity=0.002, timestamp=datetime.now())
        runner.capital += 0.0

        runner._execute_signal("BTCUSDT", "CLOSE_AND_LONG", price=51000, timestamp=datetime.now())

        assert runner.position.get_side("BTCUSDT") == "LONG"
        assert runner.capital > 0

    def test_save_report_generates_parquet_csv(self, tmp_path):
        """상태저장: parquet/csv 파일이 생성되는지 확인"""
        strategy = PortfolioMomentum(
            symbols=["BTCUSDT", "ETHUSDT"],
            lookback_minutes=5,
            top_n=1,
            bottom_n=0,
        )

        runner = PortfolioForwardRunner(
            strategy=strategy,
            symbols=["BTCUSDT", "ETHUSDT"],
            candle_type=CandleType.TIME,
            candle_size=300,
            initial_capital=10000,
        )

        now = datetime.now()
        runner.rebalance_events = [
            {
                "run_id": runner.run_id,
                "timestamp": now,
                "event_type": "model_target",
                "symbol": "BTCUSDT",
                "target_side": "BUY",
                "target_weight": 0.5,
            }
        ]
        runner.execution_events = []
        runner.weight_events = [
            {
                "timestamp": now,
                "alpha_id": strategy.__class__.__name__,
                "symbol": "BTCUSDT",
                "target_weight": 0.5,
                "target_notional": 5000.0,
                "target_qty": 0.1,
                "price": 50000.0,
                "bar_type": "TIME",
                "bar_size": 300.0,
                "metadata": "{}",
            }
        ]
        runner.nav_events = [
            {
                "run_id": runner.run_id,
                "timestamp": now,
                "capital": 10000,
                "unrealized": 0,
                "equity": 10000,
                "positions": "{}",
                "active_symbols": 0,
                "trades": 0,
                "runtime_sec": 0,
            }
        ]

        saved = runner.save_report(tmp_path)

        assert {
            "state",
            "summary",
            "manifest",
            "metrics",
            "events",
            "trades",
            "weights",
            "equity_curve",
            "portfolio",
            "summary_csv",
        }.issubset(saved.keys())
        for key in [
            "state",
            "summary",
            "manifest",
            "metrics",
            "events",
            "trades",
            "weights",
            "equity_curve",
            "portfolio",
            "summary_csv",
        ]:
            assert saved[key].exists(), f"missing {key}"
            assert saved[key].stat().st_size > 0

        events_df = pd.read_parquet(saved["events"])
        weights_df = pd.read_parquet(saved["weights"])
        nav_df = pd.read_parquet(saved["portfolio"])

        assert not events_df.empty
        assert not weights_df.empty
        assert not nav_df.empty
        assert {
            "timestamp",
            "alpha_id",
            "symbol",
            "target_weight",
            "target_notional",
            "target_qty",
            "price",
            "bar_type",
            "bar_size",
            "metadata",
        }.issubset(weights_df.columns)

        summary_text = saved["summary_csv"].read_text()
        assert "run_id" in summary_text

    def test_forward_simple_long_has_exact_realized_pnl_and_artifacts(self, tmp_path):
        """고정 가격 경로에서 포워드 진입/청산/저장값을 정확히 검증."""
        strategy = FixedLongOnceForwardStrategy("BTCUSDT", quantity=2.0)
        runner = PortfolioForwardRunner(
            strategy=strategy,
            symbols=["BTCUSDT"],
            candle_type=CandleType.TIME,
            candle_size=60,
            initial_capital=10000.0,
            position_size_pct=1.0,
            fee_rate=0.0,
            rebalance_minutes=1,
            run_id="forward_exact",
        )

        base = datetime(2025, 3, 1, 9, 0, 0)
        runner._start_time = base
        runner._last_rebalance_time = base - timedelta(minutes=2)

        open_ts = base + timedelta(seconds=60)
        runner.on_kline_close("BTCUSDT", _kline(open_ts, 100.0))

        opened = [t for t in runner.trade_log if t["action"] == "OPEN_LONG"]
        assert opened == [
            {
                "timestamp": open_ts,
                "symbol": "BTCUSDT",
                "action": "OPEN_LONG",
                "price": 100.0,
                "quantity": 2.0,
                "fee": 0.0,
            }
        ]

        close_ts = base + timedelta(seconds=120)
        runner.on_kline_close("BTCUSDT", _kline(close_ts, 120.0))
        runner.close_all_positions(timestamp=close_ts)
        runner._record_nav(close_ts)
        saved = runner.save_report(tmp_path)

        closed = [t for t in runner.trade_log if t["action"] == "CLOSE"]
        assert len(closed) == 1
        assert closed[0]["timestamp"] == close_ts
        assert closed[0]["symbol"] == "BTCUSDT"
        assert closed[0]["price"] == 120.0
        assert closed[0]["quantity"] == 0.0
        assert closed[0]["pnl"] == pytest.approx((120.0 - 100.0) * 2.0)
        assert runner.capital == pytest.approx(10040.0)

        weights = pd.read_parquet(saved["weights"])
        metrics = pd.read_json(saved["metrics"], typ="series")

        assert len(weights) == 1
        assert weights.iloc[0]["timestamp"] == pd.Timestamp(open_ts)
        assert weights.iloc[0]["symbol"] == "BTCUSDT"
        assert weights.iloc[0]["target_qty"] == pytest.approx(2.0)
        assert weights.iloc[0]["target_notional"] == pytest.approx(200.0)
        assert weights.iloc[0]["target_weight"] == pytest.approx(0.02)
        assert metrics["total_return"] == pytest.approx(0.004)
        assert metrics["total_trades"] == 1
