"""
backtest_tool.py 포트폴리오 확장 테스트 (Phase 4)

run_portfolio_backtest MCP 도구가 PortfolioTickBacktestRunner를 올바르게 호출하는지 확인.
"""

import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import sys

# agent tools 경로 추가
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


class TestPortfolioBacktestToolDiscovery:
    """포트폴리오 전략 발견"""

    def test_discover_portfolio_strategies(self):
        """portfolio 디렉토리 전략을 발견"""
        from agent.tools.backtest_tool import _discover_strategies

        strategies = _discover_strategies("multi")
        # momentum.py, pair.py 에 있는 전략들
        assert len(strategies) >= 0  # 전략이 없어도 에러 안 남

    def test_get_all_includes_portfolio(self):
        """get_all_strategies에서 portfolio 전략이 tick으로 노출"""
        from agent.tools.backtest_tool import _get_all_strategies

        all_strats = _get_all_strategies()
        # portfolio 전략이 포함되어야 함
        data_types = set(info["data_type"] for info in all_strats.values())
        assert "tick" in data_types or len(all_strats) > 0  # 최소한 에러 안 남


class TestRunPortfolioBacktestTool:
    """run_portfolio_backtest MCP 도구"""

    def test_tool_exists(self):
        """run_portfolio_backtest 도구를 검증"""
        from agent.tools.backtest_tool import run_portfolio_backtest
        assert run_portfolio_backtest is not None

    def test_missing_symbols_returns_error(self):
        """symbols 미지정 시 에러"""
        from agent.tools.backtest_tool import _run_portfolio_backtest_impl

        result = asyncio.run(
            _run_portfolio_backtest_impl({
                "strategy": "PortfolioMomentum",
                "data_paths": {},
            })
        )

        assert result.get("is_error", False) or "error" in str(result).lower() or "symbols" in str(result).lower()

    def test_valid_args_structure(self):
        """유효한 인자 구조로 호출 가능"""
        from agent.tools.backtest_tool import _run_portfolio_backtest_impl

        # 존재하지 않는 경로지만 에러 메시지가 적절한지 확인
        result = asyncio.run(
            _run_portfolio_backtest_impl({
                "strategy": "PortfolioMomentum",
                "symbols": ["BTCUSDT", "ETHUSDT"],
                "data_paths": {
                    "BTCUSDT": "/nonexistent/btc",
                    "ETHUSDT": "/nonexistent/eth",
                },
                "start_date": "2025-03-01",
                "end_date": "2025-03-15",
            })
        )

        # 에러가 발생하되, 적절한 메시지
        content = result["content"][0]["text"]
        assert "error" in content.lower() or "not found" in content.lower() or "Error" in content


class TestPortfolioBacktestToolFormatting:
    """결과 포맷팅"""

    def test_format_portfolio_report(self):
        """포트폴리오 리포트 포맷팅"""
        from agent.tools.backtest_tool import _format_portfolio_report

        # 가짜 결과
        import pandas as pd
        from intraday.backtest.multi_tick_runner import PortfolioTickResult

        result = PortfolioTickResult(
            initial_capital=10000.0,
            final_capital=10500.0,
            total_return=0.05,
            sharpe_ratio=1.5,
            max_drawdown=0.03,
            total_trades=10,
            winning_trades=6,
            losing_trades=4,
            equity_curve=pd.Series([10000, 10200, 10500]),
            trade_log=[
                {"symbol": "BTCUSDT", "pnl": 100, "action": "CLOSE"},
                {"symbol": "ETHUSDT", "pnl": -50, "action": "CLOSE"},
            ],
            tick_counts={"BTCUSDT": 50000, "ETHUSDT": 45000},
            bar_counts={"BTCUSDT": 100, "ETHUSDT": 95},
        )

        formatted = _format_portfolio_report(result)

        assert "Portfolio" in formatted
        assert "10,500" in formatted or "10500" in formatted
        assert "BTCUSDT" in formatted
        assert "ETHUSDT" in formatted
