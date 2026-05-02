"""
포트폴리오 Forward Test 러너 테스트

TDD: 여러 코인 실시간 데이터로 포트폴리오 전략 Forward Test
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch

import pandas as pd
import pytest

from intraday.client import AggTrade
from intraday.candle_builder import CandleBuilder, Candle, CandleType
from intraday.strategies.multi import PortfolioMomentum, PairTradingStrategy
from intraday.multi_forward_runner import (
    PortfolioForwardRunner,
    SymbolState,
)
from scripts.run_portfolio_forward_test import build_strategy
from types import SimpleNamespace


class TestSymbolState:
    """심볼별 상태 관리 테스트"""

    def test_init(self):
        """초기화"""
        state = SymbolState(
            symbol="BTCUSDT",
            candle_type=CandleType.TIME,
            candle_size=300,  # 5분봉
        )

        assert state.symbol == "BTCUSDT"
        assert state.last_price == 0.0
        assert state.candle_count == 0
        assert state.candle_builder is not None

    def test_update_price(self):
        """가격 업데이트"""
        state = SymbolState(
            symbol="BTCUSDT",
            candle_type=CandleType.TIME,
            candle_size=300,
        )

        trade = AggTrade(
            timestamp=datetime.now(),
            symbol="BTCUSDT",
            price=50000,
            quantity=0.1,
            is_buyer_maker=False,
        )

        state.on_trade(trade)

        assert state.last_price == 50000
        assert state.tick_count == 1

    def test_price_history(self):
        """가격 히스토리 추적"""
        state = SymbolState(
            symbol="BTCUSDT",
            candle_type=CandleType.TIME,
            candle_size=300,
        )

        now = datetime.now()
        prices = [50000, 50100, 50200, 49900, 50050]

        for i, price in enumerate(prices):
            trade = AggTrade(
                timestamp=now + timedelta(seconds=i),
                symbol="BTCUSDT",
                price=price,
                quantity=0.1,
                is_buyer_maker=False,
            )
            state.on_trade(trade)

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

        trade = AggTrade(
            timestamp=datetime.now(),
            symbol="BTCUSDT",
            price=50000,
            quantity=0.1,
            is_buyer_maker=False,
        )

        runner.on_trade("BTCUSDT", trade)

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

        # BTC 가격 설정
        trade_btc = AggTrade(
            timestamp=datetime.now(),
            symbol="BTCUSDT",
            price=50000,
            quantity=0.1,
            is_buyer_maker=False,
        )
        runner.on_trade("BTCUSDT", trade_btc)

        # ETH 가격 설정
        trade_eth = AggTrade(
            timestamp=datetime.now(),
            symbol="ETHUSDT",
            price=3000,
            quantity=1.0,
            is_buyer_maker=False,
        )
        runner.on_trade("ETHUSDT", trade_eth)

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
        client.disconnect = AsyncMock()

        with patch("intraday.multi_forward_runner.BinanceAggTradeClient", return_value=client):
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
        client.disconnect = AsyncMock()

        with patch("intraday.multi_forward_runner.BinanceAggTradeClient", return_value=client):
            asyncio.run(runner.run(duration_seconds=0))

        assert not runner._running
        assert client.disconnect.await_count == 2

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
                "run_id": runner.run_id,
                "date": now.date().isoformat(),
                "timestamp": now,
                "symbol": "BTCUSDT",
                "weight": 0.5,
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

        assert {"state", "events", "weights", "portfolio", "summary_csv"}.issubset(saved.keys())
        for key in ["state", "events", "weights", "portfolio", "summary_csv"]:
            assert saved[key].exists(), f"missing {key}"
            assert saved[key].stat().st_size > 0

        events_df = pd.read_parquet(saved["events"])
        weights_df = pd.read_parquet(saved["weights"])
        nav_df = pd.read_parquet(saved["portfolio"])

        assert not events_df.empty
        assert not weights_df.empty
        assert not nav_df.empty

        summary_text = saved["summary_csv"].read_text()
        assert "run_id" in summary_text
