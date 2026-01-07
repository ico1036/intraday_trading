"""
Tests for MCP Backtest Tool.

Tests the backtest_tool wrapper functions used by the Analyst agent.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock

import sys
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "agent" / "tools"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

class TestDiscoverStrategies:
    """Test strategy discovery."""

    def test_discover_tick_strategies(self):
        """Should discover tick strategies."""
        from backtest_tool import _discover_strategies

        strategies = _discover_strategies("tick")

        assert len(strategies) > 0
        assert "VolumeImbalanceStrategy" in strategies or "RegimeStrategy" in strategies

    def test_discover_orderbook_strategies(self):
        """Should discover orderbook strategies."""
        from backtest_tool import _discover_strategies

        strategies = _discover_strategies("orderbook")

        # OBIStrategy should exist
        assert "OBIStrategy" in strategies

    def test_discover_nonexistent_type(self):
        """Should return empty dict for nonexistent type."""
        from backtest_tool import _discover_strategies

        strategies = _discover_strategies("nonexistent")

        assert strategies == {}

    def test_get_all_strategies(self):
        """Should get all strategies with metadata."""
        from backtest_tool import _get_all_strategies

        all_strategies = _get_all_strategies()

        assert len(all_strategies) > 0
        # Check structure
        for name, info in all_strategies.items():
            assert "class" in info
            assert "data_type" in info
            assert info["data_type"] in ["tick", "orderbook"]


class TestGetAvailableStrategies:
    """Test get_available_strategies MCP tool."""

    @pytest.mark.asyncio
    async def test_returns_formatted_list(self):
        """Should return formatted strategy list."""
        from backtest_tool import _get_available_strategies_impl

        result = await _get_available_strategies_impl({})

        assert "content" in result
        assert len(result["content"]) == 1
        assert result["content"][0]["type"] == "text"

        text = result["content"][0]["text"]
        assert "# Available Strategies" in text
        assert "## Tick Strategies" in text
        assert "## Orderbook Strategies" in text


class TestRunBacktest:
    """Test run_backtest MCP tool."""

    @pytest.mark.asyncio
    async def test_invalid_data_type(self):
        """Should return error for invalid data_type."""
        from backtest_tool import _run_backtest_impl

        result = await _run_backtest_impl({
            "strategy": "VolumeImbalanceStrategy",
            "data_type": "invalid",
            "data_path": "./data/ticks",
        })

        assert result.get("is_error") is True
        assert "Invalid data_type" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_unknown_strategy(self):
        """Should return error for unknown strategy."""
        from backtest_tool import _run_backtest_impl

        result = await _run_backtest_impl({
            "strategy": "NonExistentStrategy",
            "data_type": "tick",
            "data_path": "./data/ticks",
        })

        assert result.get("is_error") is True
        assert "Unknown strategy" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_strategy_data_type_mismatch(self):
        """Should return error when strategy doesn't match data_type."""
        from backtest_tool import _run_backtest_impl

        result = await _run_backtest_impl({
            "strategy": "OBIStrategy",
            "data_type": "tick",  # OBI is orderbook strategy
            "data_path": "./data/ticks",
        })

        assert result.get("is_error") is True
        assert "orderbook strategy" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_invalid_bar_type(self):
        """Should return error for invalid bar_type."""
        from backtest_tool import _run_backtest_impl

        result = await _run_backtest_impl({
            "strategy": "VolumeImbalanceStrategy",
            "data_type": "tick",
            "data_path": "./data/ticks",
            "bar_type": "INVALID",
        })

        assert result.get("is_error") is True
        assert "Unknown bar_type" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_missing_data_path(self):
        """Should return error when data path doesn't exist."""
        from backtest_tool import _run_backtest_impl

        result = await _run_backtest_impl({
            "strategy": "VolumeImbalanceStrategy",
            "data_type": "tick",
            "data_path": "./nonexistent/path",
        })

        assert result.get("is_error") is True
        assert "Data path not found" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_invalid_strategy_params_json(self):
        """Should return error for invalid JSON in strategy_params."""
        from backtest_tool import _run_backtest_impl

        result = await _run_backtest_impl({
            "strategy": "VolumeImbalanceStrategy",
            "data_type": "tick",
            "data_path": "./data/ticks",
            "strategy_params": "not valid json",
        })

        assert result.get("is_error") is True
        assert "Invalid JSON" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_valid_strategy_params_json(self):
        """Should parse valid JSON in strategy_params."""
        from backtest_tool import _run_backtest_impl

        # This will fail on data path, but should get past JSON parsing
        result = await _run_backtest_impl({
            "strategy": "VolumeImbalanceStrategy",
            "data_type": "tick",
            "data_path": "./nonexistent",
            "strategy_params": '{"buy_threshold": 0.5}',
        })

        # Should fail on data path, not JSON parsing
        assert result.get("is_error") is True
        assert "Data path not found" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_empty_strategy_params(self):
        """Should handle empty strategy_params."""
        from backtest_tool import _run_backtest_impl

        result = await _run_backtest_impl({
            "strategy": "VolumeImbalanceStrategy",
            "data_type": "tick",
            "data_path": "./nonexistent",
            "strategy_params": "",
        })

        # Should fail on data path, not JSON parsing
        assert result.get("is_error") is True
        assert "Data path not found" in result["content"][0]["text"]


@pytest.mark.slow
class TestRunBacktestIntegration:
    """Integration tests with real data (if available).

    These tests are slow (use real backtest) and marked with @pytest.mark.slow.
    Run with: pytest -m slow
    Skip with: pytest -m "not slow"
    """

    @pytest.fixture
    def data_path(self):
        """Get tick data path if exists."""
        path = PROJECT_ROOT / "data" / "ticks"
        if not path.exists():
            pytest.skip("Tick data not available")
        return path

    @pytest.mark.asyncio
    async def test_run_short_backtest(self, data_path):
        """Should run a short backtest successfully."""
        from backtest_tool import _run_backtest_impl

        result = await _run_backtest_impl({
            "strategy": "VolumeImbalanceStrategy",
            "data_type": "tick",
            "data_path": str(data_path),
            "start_date": "2024-01-15",
            "end_date": "2024-01-16",
            "bar_type": "VOLUME",
            "bar_size": 1.0,
            "initial_capital": 10000.0,
            "leverage": 1,
        })

        assert result.get("is_error") is not True
        text = result["content"][0]["text"]

        # Check report structure
        assert "# Backtest Results" in text
        assert "## Summary" in text
        assert "## Trading Statistics" in text
        assert "## Risk Metrics" in text
        assert "Total Return" in text
        assert "Win Rate" in text
        assert "Sharpe Ratio" in text

    @pytest.mark.asyncio
    async def test_run_backtest_with_strategy_params(self, data_path):
        """Should pass strategy params correctly."""
        from backtest_tool import _run_backtest_impl

        result = await _run_backtest_impl({
            "strategy": "VolumeImbalanceStrategy",
            "data_type": "tick",
            "data_path": str(data_path),
            "start_date": "2024-01-15",
            "end_date": "2024-01-16",
            "bar_type": "VOLUME",
            "bar_size": 1.0,
            "strategy_params": json.dumps({
                "buy_threshold": 0.6,
                "sell_threshold": -0.6,
            }),
        })

        assert result.get("is_error") is not True

    @pytest.mark.asyncio
    async def test_run_futures_backtest(self, data_path):
        """Should run futures backtest with leverage."""
        from backtest_tool import _run_backtest_impl

        result = await _run_backtest_impl({
            "strategy": "VolumeImbalanceStrategy",
            "data_type": "tick",
            "data_path": str(data_path),
            "start_date": "2024-01-15",
            "end_date": "2024-01-16",
            "bar_type": "VOLUME",
            "bar_size": 1.0,
            "leverage": 5,
            "include_funding": False,
        })

        assert result.get("is_error") is not True
        text = result["content"][0]["text"]
        assert "5x" in text  # Leverage should be shown


class TestFormatReport:
    """Test report formatting."""

    def test_format_report_structure(self):
        """Should format report with all sections."""
        from backtest_tool import _format_report

        # Create mock report with spec to avoid hasattr issues
        class MockReport:
            strategy_name = "TestStrategy"
            symbol = "BTCUSDT"
            start_time = "2024-01-15"
            end_time = "2024-01-16"
            initial_capital = 10000.0
            final_capital = 10500.0
            total_return = 5.0
            total_trades = 50
            win_rate = 55.0
            winning_trades = 28
            losing_trades = 22
            profit_factor = 1.5
            avg_win = 100.0
            avg_loss = 50.0
            max_drawdown = -3.5
            sharpe_ratio = 1.2
            total_fees = 25.0

        class MockRunner:
            leverage = 1

        result = _format_report(MockReport(), MockRunner(), "tick")

        assert "# Backtest Results" in result
        assert "TestStrategy" in result
        assert "BTCUSDT" in result
        assert "+5.00%" in result  # Total return
        assert "55.0%" in result  # Win rate
        assert "1.50" in result  # Profit factor
