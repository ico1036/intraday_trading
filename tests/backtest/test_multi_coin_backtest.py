"""
포트폴리오 백테스트 테스트

TDD로 개발: 테스트 먼저 작성 → 구현 → 통과

테스트 범위:
    - 여러 코인 동시 로딩
    - 시간 동기화
    - 포트폴리오 포지션 관리
    - PnL 계산
"""

import pytest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
import pandas as pd
import numpy as np

from intraday.strategies.multi import PortfolioMomentum
from intraday.backtest.multi_runner import (
    PortfolioBacktestRunner,
    PortfolioPosition,
    PortfolioBacktestResult,
)


class TestPortfolioPosition:
    """포트폴리오 포지션 관리 테스트"""
    
    def test_open_long_position(self):
        """롱 포지션 오픈"""
        position = PortfolioPosition()
        
        position.open("BTCUSDT", "LONG", price=50000, quantity=0.1, timestamp=datetime.now())
        
        assert position.has_position("BTCUSDT")
        assert position.get_side("BTCUSDT") == "LONG"
        assert position.get_entry_price("BTCUSDT") == 50000
    
    def test_open_short_position(self):
        """숏 포지션 오픈"""
        position = PortfolioPosition()
        
        position.open("ETHUSDT", "SHORT", price=3000, quantity=1.0, timestamp=datetime.now())
        
        assert position.has_position("ETHUSDT")
        assert position.get_side("ETHUSDT") == "SHORT"
    
    def test_close_position(self):
        """포지션 청산"""
        position = PortfolioPosition()
        position.open("BTCUSDT", "LONG", price=50000, quantity=0.1, timestamp=datetime.now())
        
        pnl = position.close("BTCUSDT", price=52000, timestamp=datetime.now())
        
        assert not position.has_position("BTCUSDT")
        assert pnl == pytest.approx(200, rel=0.01)  # (52000 - 50000) * 0.1
    
    def test_close_short_position_pnl(self):
        """숏 포지션 PnL 계산"""
        position = PortfolioPosition()
        position.open("ETHUSDT", "SHORT", price=3000, quantity=1.0, timestamp=datetime.now())
        
        pnl = position.close("ETHUSDT", price=2800, timestamp=datetime.now())
        
        assert pnl == pytest.approx(200, rel=0.01)  # (3000 - 2800) * 1.0
    
    def test_multiple_positions(self):
        """여러 포지션 동시 관리"""
        position = PortfolioPosition()
        
        position.open("BTCUSDT", "LONG", price=50000, quantity=0.1, timestamp=datetime.now())
        position.open("ETHUSDT", "SHORT", price=3000, quantity=1.0, timestamp=datetime.now())
        position.open("SOLUSDT", "LONG", price=100, quantity=10, timestamp=datetime.now())
        
        assert len(position.get_all_positions()) == 3
        
        current = position.to_dict()
        assert current["BTCUSDT"] == "LONG"
        assert current["ETHUSDT"] == "SHORT"
        assert current["SOLUSDT"] == "LONG"


class TestPortfolioBacktestRunner:
    """포트폴리오 백테스트 러너 테스트"""
    
    def test_runner_init(self):
        """러너 초기화"""
        strategy = PortfolioMomentum(
            symbols=["BTCUSDT", "ETHUSDT"],
            lookback_minutes=60,
            top_n=1,
            bottom_n=1,
        )
        
        runner = PortfolioBacktestRunner(
            strategy=strategy,
            initial_capital=10000,
            position_size_pct=0.1,  # 10% per position
        )
        
        assert runner.initial_capital == 10000
        assert runner.position_size_pct == 0.1
    
    def test_load_multi_coin_data(self):
        """여러 코인 데이터 로딩"""
        strategy = PortfolioMomentum(
            symbols=["BTCUSDT", "ETHUSDT"],
            lookback_minutes=60,
            top_n=1,
            bottom_n=1,
        )
        
        runner = PortfolioBacktestRunner(strategy=strategy, initial_capital=10000)
        
        # Mock 데이터 로더
        mock_data = {
            "BTCUSDT": pd.DataFrame({
                "timestamp": pd.date_range("2025-01-01", periods=100, freq="1min"),
                "price": np.linspace(50000, 51000, 100),
            }),
            "ETHUSDT": pd.DataFrame({
                "timestamp": pd.date_range("2025-01-01", periods=100, freq="1min"),
                "price": np.linspace(3000, 3100, 100),
            }),
        }
        
        runner.load_data(mock_data)
        
        assert "BTCUSDT" in runner.data
        assert "ETHUSDT" in runner.data
    
    def test_time_sync(self):
        """시간 동기화 - 모든 코인이 같은 타임스탬프에서 평가"""
        strategy = PortfolioMomentum(
            symbols=["BTCUSDT", "ETHUSDT"],
            lookback_minutes=5,
            top_n=1,
            bottom_n=1,
        )
        
        runner = PortfolioBacktestRunner(strategy=strategy, initial_capital=10000)
        
        # 시간대가 약간 다른 데이터
        btc_times = pd.date_range("2025-01-01 00:00:00", periods=10, freq="1min")
        eth_times = pd.date_range("2025-01-01 00:00:30", periods=10, freq="1min")  # 30초 offset
        
        mock_data = {
            "BTCUSDT": pd.DataFrame({
                "timestamp": btc_times,
                "price": [50000 + i * 100 for i in range(10)],
            }),
            "ETHUSDT": pd.DataFrame({
                "timestamp": eth_times,
                "price": [3000 + i * 50 for i in range(10)],
            }),
        }
        
        runner.load_data(mock_data)
        synced_times = runner.get_synced_timestamps()
        
        # 공통 시간대만 포함
        assert len(synced_times) > 0
    
    def test_run_backtest(self):
        """백테스트 실행"""
        strategy = PortfolioMomentum(
            symbols=["BTCUSDT", "ETHUSDT"],
            lookback_minutes=5,
            top_n=1,
            bottom_n=1,
        )
        
        runner = PortfolioBacktestRunner(
            strategy=strategy,
            initial_capital=10000,
            position_size_pct=0.5,
            rebalance_minutes=10,
        )
        
        # ETH가 더 강하게 상승, BTC는 약하게 상승
        times = pd.date_range("2025-01-01", periods=30, freq="1min")
        mock_data = {
            "BTCUSDT": pd.DataFrame({
                "timestamp": times,
                "price": [50000 + i * 10 for i in range(30)],  # +0.6%
            }),
            "ETHUSDT": pd.DataFrame({
                "timestamp": times,
                "price": [3000 + i * 20 for i in range(30)],  # +18%
            }),
        }
        
        runner.load_data(mock_data)
        result = runner.run()
        
        assert isinstance(result, PortfolioBacktestResult)
        assert result.total_trades > 0
    
    def test_result_metrics(self):
        """결과 메트릭"""
        strategy = PortfolioMomentum(
            symbols=["BTCUSDT", "ETHUSDT"],
            lookback_minutes=5,
            top_n=1,
            bottom_n=1,
        )
        
        runner = PortfolioBacktestRunner(
            strategy=strategy,
            initial_capital=10000,
            position_size_pct=0.5,
            rebalance_minutes=10,
        )
        
        times = pd.date_range("2025-01-01", periods=60, freq="1min")
        mock_data = {
            "BTCUSDT": pd.DataFrame({
                "timestamp": times,
                "price": [50000 + i * 50 for i in range(60)],
            }),
            "ETHUSDT": pd.DataFrame({
                "timestamp": times,
                "price": [3000 - i * 10 for i in range(60)],  # 하락
            }),
        }
        
        runner.load_data(mock_data)
        result = runner.run()
        
        # 기본 메트릭 확인
        assert hasattr(result, "total_return")
        assert hasattr(result, "sharpe_ratio")
        assert hasattr(result, "max_drawdown")
        assert hasattr(result, "total_trades")
        assert hasattr(result, "win_rate")

    def test_save_report_uses_existing_run_without_rerun(self, tmp_path):
        """save_report는 이미 실행된 백테스트 상태를 다시 실행하지 않고 저장"""
        strategy = PortfolioMomentum(
            symbols=["BTCUSDT", "ETHUSDT"],
            lookback_minutes=5,
            top_n=1,
            bottom_n=1,
        )

        runner = PortfolioBacktestRunner(
            strategy=strategy,
            initial_capital=10000,
            position_size_pct=0.5,
            rebalance_minutes=10,
        )

        times = pd.date_range("2025-01-01", periods=60, freq="1min")
        runner.load_data({
            "BTCUSDT": pd.DataFrame({
                "timestamp": times,
                "price": [50000 + i * 50 for i in range(60)],
            }),
            "ETHUSDT": pd.DataFrame({
                "timestamp": times,
                "price": [3000 - i * 10 for i in range(60)],
            }),
        })

        result = runner.run()
        trade_count = len(runner.trade_log)
        equity_count = len(runner.equity_curve)
        final_capital = runner.capital

        report_dir = runner.save_report(tmp_path)
        summary = pd.read_parquet(Path(report_dir) / "summary.parquet").iloc[0]

        assert len(runner.trade_log) == trade_count
        assert len(runner.equity_curve) == equity_count
        assert runner.capital == final_capital
        assert summary["final_capital"] == pytest.approx(result.final_capital)
        assert summary["total_return"] == pytest.approx(result.total_return)
        assert summary["total_trades"] == result.total_trades


class TestPortfolioBacktestResult:
    """백테스트 결과 테스트"""
    
    def test_result_summary(self):
        """결과 요약"""
        result = PortfolioBacktestResult(
            initial_capital=10000,
            final_capital=12000,
            total_return=0.20,
            sharpe_ratio=1.5,
            max_drawdown=-0.05,
            total_trades=10,
            winning_trades=7,
            losing_trades=3,
            equity_curve=pd.Series([10000, 10500, 11000, 11500, 12000]),
            trade_log=[
                {"symbol": "BTCUSDT", "pnl": 500},
                {"symbol": "BTCUSDT", "pnl": 300},
                {"symbol": "ETHUSDT", "pnl": -100},
            ],
        )
        
        assert result.win_rate == pytest.approx(0.7, rel=0.01)
        assert result.profit_factor > 0  # 800 / 100 = 8.0
    
    def test_per_symbol_breakdown(self):
        """심볼별 성과 분석"""
        result = PortfolioBacktestResult(
            initial_capital=10000,
            final_capital=12000,
            total_return=0.20,
            sharpe_ratio=1.5,
            max_drawdown=-0.05,
            total_trades=10,
            winning_trades=7,
            losing_trades=3,
            equity_curve=pd.Series([10000, 10500, 11000, 11500, 12000]),
            trade_log=[
                {"symbol": "BTCUSDT", "pnl": 500},
                {"symbol": "BTCUSDT", "pnl": -100},
                {"symbol": "ETHUSDT", "pnl": 300},
                {"symbol": "ETHUSDT", "pnl": 200},
            ],
        )
        
        breakdown = result.get_symbol_breakdown()
        
        assert "BTCUSDT" in breakdown
        assert "ETHUSDT" in breakdown
        assert breakdown["BTCUSDT"]["total_pnl"] == 400
        assert breakdown["ETHUSDT"]["total_pnl"] == 500
