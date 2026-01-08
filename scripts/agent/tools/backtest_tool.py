"""
MCP Backtest Tool

Wraps TickBacktestRunner and OrderbookBacktestRunner as MCP tools for the Claude Agent SDK.
Supports dynamic strategy loading from src/intraday/strategies/.

Usage:
    from claude_agent_sdk import tool, create_sdk_mcp_server
    from scripts.agent.tools import run_backtest, get_available_strategies

    server = create_sdk_mcp_server(
        name="backtest",
        version="1.0.0",
        tools=[run_backtest, get_available_strategies]
    )
"""

import importlib
import json
import sys
from pathlib import Path
from typing import Any

# Add src to path for imports
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from claude_agent_sdk import tool

from intraday.backtest.tick_runner import TickBacktestRunner
from intraday.candle_builder import CandleType


# Bar type mapping
BAR_TYPES = {
    "VOLUME": CandleType.VOLUME,
    "TICK": CandleType.TICK,
    "TIME": CandleType.TIME,
    "DOLLAR": CandleType.DOLLAR,
}


def _discover_strategies(data_type: str) -> dict[str, type]:
    """
    Dynamically discover strategies from src/intraday/strategies/{data_type}/.

    Args:
        data_type: "tick" or "orderbook"

    Returns:
        Dict mapping strategy class names to classes
    """
    strategies = {}
    strategies_dir = PROJECT_ROOT / "src" / "intraday" / "strategies" / data_type

    if not strategies_dir.exists():
        return strategies

    for py_file in strategies_dir.glob("*.py"):
        if py_file.name.startswith("_"):
            continue  # Skip __init__.py, _template.py

        module_name = f"intraday.strategies.{data_type}.{py_file.stem}"
        try:
            # CRITICAL: Force reload of strategy module AND its dependencies
            # This ensures latest code changes are used during backtests

            # Step 1: Clear base module cache (strategies depend on this)
            base_module = "intraday.strategies.base"
            if base_module in sys.modules:
                del sys.modules[base_module]

            # Step 2: Clear the strategy module cache
            if module_name in sys.modules:
                del sys.modules[module_name]

            # Step 3: Clear __init__ cache (may hold references)
            init_module = f"intraday.strategies.{data_type}"
            if init_module in sys.modules:
                del sys.modules[init_module]

            # Step 4: Fresh import
            module = importlib.import_module(module_name)

            # Find strategy classes (classes ending with "Strategy")
            for attr_name in dir(module):
                if attr_name.endswith("Strategy") and not attr_name.startswith("_"):
                    cls = getattr(module, attr_name)
                    if isinstance(cls, type):
                        strategies[attr_name] = cls
        except Exception as e:
            # Skip modules that fail to import
            print(f"Warning: Failed to import {module_name}: {e}")
            continue

    return strategies


def _get_all_strategies() -> dict[str, dict]:
    """Get all available strategies with metadata."""
    result = {}

    for data_type in ["tick", "orderbook"]:
        strategies = _discover_strategies(data_type)
        for name, cls in strategies.items():
            result[name] = {
                "class": cls,
                "data_type": data_type,
            }

    return result


async def _get_available_strategies_impl(args: dict[str, Any]) -> dict[str, Any]:
    """Return list of available strategies with their parameters (implementation)."""
    import inspect

    all_strategies = _get_all_strategies()
    strategies_info = {"tick": [], "orderbook": []}

    for name, info in all_strategies.items():
        cls = info["class"]
        data_type = info["data_type"]

        # Get default parameters from __init__ signature
        sig = inspect.signature(cls.__init__)
        params = {}
        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue
            if param.default != inspect.Parameter.empty:
                params[param_name] = param.default
            else:
                params[param_name] = "required"

        strategies_info[data_type].append({
            "name": name,
            "parameters": params,
        })

    # Format output
    lines = ["# Available Strategies\n"]

    lines.append("## Tick Strategies")
    if strategies_info["tick"]:
        for info in strategies_info["tick"]:
            lines.append(f"\n### {info['name']}")
            lines.append("Parameters:")
            for param, default in info["parameters"].items():
                lines.append(f"  - {param}: {default}")
    else:
        lines.append("(none found)")

    lines.append("\n## Orderbook Strategies")
    if strategies_info["orderbook"]:
        for info in strategies_info["orderbook"]:
            lines.append(f"\n### {info['name']}")
            lines.append("Parameters:")
            for param, default in info["parameters"].items():
                lines.append(f"  - {param}: {default}")
    else:
        lines.append("(none found)")

    return {
        "content": [{
            "type": "text",
            "text": "\n".join(lines)
        }]
    }


@tool(
    "get_available_strategies",
    "List available trading strategies and their default parameters",
    {}
)
async def get_available_strategies(args: dict[str, Any]) -> dict[str, Any]:
    """Return list of available strategies with their parameters."""
    return await _get_available_strategies_impl(args)


async def _run_backtest_impl(args: dict[str, Any]) -> dict[str, Any]:
    """
    Run a backtest with the specified strategy (implementation).

    Args:
        strategy: Strategy class name (e.g., "VolumeImbalanceStrategy")
        data_type: "tick" or "orderbook"
        data_path: Path to data directory
        start_date: Start date ("YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS")
        end_date: End date ("YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS")
        bar_type: Bar type for tick strategies ("VOLUME", "TICK", "TIME", "DOLLAR")
        bar_size: Bar size for tick strategies
        initial_capital: Initial capital in USD
        leverage: Leverage (1=spot, >1=futures)
        include_funding: Whether to include funding rate (futures only)
        strategy_params: JSON string of strategy-specific parameters
        fee_rate: Trading fee rate (default: 0.0005 = 0.05% for futures taker)

    Returns:
        Backtest performance report
    """
    from datetime import datetime

    try:
        # Parse parameters
        strategy_name = args.get("strategy", "VolumeImbalanceStrategy")
        data_type = args.get("data_type", "tick").lower()
        data_path = Path(args.get("data_path", f"./data/{data_type}s"))
        bar_type_str = args.get("bar_type", "VOLUME").upper()
        bar_size = float(args.get("bar_size", 10.0))
        initial_capital = float(args.get("initial_capital", 10000.0))
        leverage = int(args.get("leverage", 1))
        include_funding = args.get("include_funding", False)
        # CRITICAL: Use realistic fee rates (Binance futures)
        # Reference: https://www.binance.com/en/fee/schedule (Regular user: 0.02% maker, 0.05% taker)
        # fee_rate is deprecated but kept for backward compatibility
        fee_rate = args.get("fee_rate")  # None means use maker/taker rates
        if fee_rate is not None:
            fee_rate = float(fee_rate)
        maker_fee_rate = float(args.get("maker_fee_rate", 0.0002))  # 0.02%
        taker_fee_rate = float(args.get("taker_fee_rate", 0.0005))  # 0.05%

        # Parse strategy_params - handle both dict and JSON string
        strategy_params_raw = args.get("strategy_params", {})
        if isinstance(strategy_params_raw, str):
            try:
                strategy_params = json.loads(strategy_params_raw) if strategy_params_raw else {}
            except json.JSONDecodeError:
                return {
                    "content": [{
                        "type": "text",
                        "text": f"Error: Invalid JSON in strategy_params: {strategy_params_raw}"
                    }],
                    "is_error": True
                }
        else:
            strategy_params = strategy_params_raw if strategy_params_raw else {}

        # Parse dates
        start_date = None
        end_date = None
        if args.get("start_date"):
            try:
                start_date = datetime.fromisoformat(args["start_date"])
            except ValueError:
                start_date = datetime.strptime(args["start_date"], "%Y-%m-%d")
        if args.get("end_date"):
            try:
                end_date = datetime.fromisoformat(args["end_date"])
            except ValueError:
                end_date = datetime.strptime(args["end_date"], "%Y-%m-%d")

        # Validate data_type
        if data_type not in ["tick", "orderbook"]:
            return {
                "content": [{
                    "type": "text",
                    "text": f"Error: Invalid data_type '{data_type}'. Must be 'tick' or 'orderbook'."
                }],
                "is_error": True
            }

        # Discover and validate strategy (exact match required)
        all_strategies = _get_all_strategies()
        if strategy_name not in all_strategies:
            available = [n for n, i in all_strategies.items() if i["data_type"] == data_type]
            return {
                "content": [{
                    "type": "text",
                    "text": f"Error: Unknown strategy '{strategy_name}'. Available {data_type} strategies: {available}. Strategy name must match exactly as defined in algorithm_prompt.txt (e.g., '# Strategy: VPINMomentumFilter' → 'VPINMomentumFilterStrategy')."
                }],
                "is_error": True
            }

        strategy_info = all_strategies[strategy_name]
        if strategy_info["data_type"] != data_type:
            return {
                "content": [{
                    "type": "text",
                    "text": f"Error: Strategy '{strategy_name}' is a {strategy_info['data_type']} strategy, not {data_type}."
                }],
                "is_error": True
            }

        # Validate bar type (tick only)
        if data_type == "tick" and bar_type_str not in BAR_TYPES:
            return {
                "content": [{
                    "type": "text",
                    "text": f"Error: Unknown bar_type '{bar_type_str}'. Available: {list(BAR_TYPES.keys())}"
                }],
                "is_error": True
            }

        # Validate bar_size for VOLUME bars (practical limit to prevent slow backtests)
        if data_type == "tick" and bar_type_str == "VOLUME" and bar_size < 10.0:
            return {
                "content": [{
                    "type": "text",
                    "text": f"Error: bar_size={bar_size} BTC is too small. MUST be >= 10.0 BTC.\n"
                           f"(Creates millions of bars, backtest takes hours)"
                }],
                "is_error": True
            }
        
        # Validate bar_size for TIME bars (practical limit)
        if data_type == "tick" and bar_type_str == "TIME" and bar_size < 60:
            return {
                "content": [{
                    "type": "text",
                    "text": f"Error: bar_size={bar_size} seconds is too small. MUST be >= 60 (1 minute).\n"
                           f"(Creates millions of bars, backtest takes hours)"
                }],
                "is_error": True
            }

        # CRITICAL: Validate backtest period (max 30 days)
        if start_date and end_date:
            period_days = (end_date - start_date).days
            if period_days > 30:
                return {
                    "content": [{
                        "type": "text",
                        "text": f"Error: Backtest period is {period_days} days. Maximum allowed is 30 days. Use Progressive Testing with appropriate phase durations based on signal frequency."
                    }],
                    "is_error": True
                }

        # Validate data path
        if not data_path.exists():
            return {
                "content": [{
                    "type": "text",
                    "text": f"Error: Data path not found: {data_path}"
                }],
                "is_error": True
            }

        # Create strategy instance
        strategy_cls = strategy_info["class"]
        strategy = strategy_cls(**strategy_params)

        # Run appropriate backtest
        if data_type == "tick":
            report, runner = _run_tick_backtest(
                strategy=strategy,
                data_path=data_path,
                bar_type=BAR_TYPES[bar_type_str],
                bar_size=bar_size,
                initial_capital=initial_capital,
                leverage=leverage,
                include_funding=include_funding,
                start_date=start_date,
                end_date=end_date,
                fee_rate=fee_rate,
                maker_fee_rate=maker_fee_rate,
                taker_fee_rate=taker_fee_rate,
            )
        else:
            report, runner = _run_orderbook_backtest(
                strategy=strategy,
                data_path=data_path,
                initial_capital=initial_capital,
                leverage=leverage,
                start_date=start_date,
                end_date=end_date,
                fee_rate=fee_rate,
                maker_fee_rate=maker_fee_rate,
                taker_fee_rate=taker_fee_rate,
            )

        # Format results
        result = _format_report(report, runner, data_type)

        # Save report to specified output directory
        output_dir_str = args.get("output_dir")
        if output_dir_str:
            output_dir = PROJECT_ROOT / output_dir_str
            if output_dir.exists():
                try:
                    report_path = runner.save_report(output_dir)
                    result += f"\n\n**Report saved to**: {report_path}"
                except Exception as e:
                    result += f"\n\n**Warning**: Failed to save report: {e}"
            else:
                result += f"\n\n**Warning**: output_dir '{output_dir_str}' not found, report not saved"

        return {
            "content": [{
                "type": "text",
                "text": result
            }]
        }

    except Exception as e:
        import traceback
        return {
            "content": [{
                "type": "text",
                "text": f"Error running backtest: {str(e)}\n\n{traceback.format_exc()}"
            }],
            "is_error": True
        }


@tool(
    "run_backtest",
    "Run a backtest with specified strategy and parameters. Returns performance metrics.",
    {
        "strategy": str,
        "data_type": str,  # "tick" or "orderbook"
        "data_path": str,
        "start_date": str,  # "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS"
        "end_date": str,  # "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS"
        "bar_type": str,  # For tick strategies only
        "bar_size": float,  # For tick strategies only
        "initial_capital": float,
        "leverage": int,
        "include_funding": bool,  # For futures only
        "strategy_params": str,  # JSON string of strategy parameters
        "output_dir": str,  # Directory to save report (e.g., "vpin_momentum_filter_dir")
        "fee_rate": float,  # (deprecated) Single fee rate for all orders. Use maker/taker_fee_rate instead.
        "maker_fee_rate": float,  # Limit Order fee rate (default: 0.0002 = 0.02%)
        "taker_fee_rate": float,  # Market Order fee rate (default: 0.0005 = 0.05%)
    }
)
async def run_backtest(args: dict[str, Any]) -> dict[str, Any]:
    """Run a backtest with the specified strategy."""
    return await _run_backtest_impl(args)


def _run_tick_backtest(
    strategy,
    data_path: Path,
    bar_type: CandleType,
    bar_size: float,
    initial_capital: float,
    leverage: int,
    include_funding: bool,
    start_date=None,
    end_date=None,
    fee_rate: float | None = None,
    maker_fee_rate: float = 0.0002,
    taker_fee_rate: float = 0.0005,
):
    """Run tick backtest with TickBacktestRunner."""
    from intraday.data.loader import TickDataLoader

    loader = TickDataLoader(data_path)

    # Optionally load funding data
    funding_loader = None
    if include_funding and leverage > 1:
        funding_path = data_path.parent / "funding"
        if funding_path.exists():
            try:
                from intraday.data.funding_downloader import FundingDataLoader
                funding_loader = FundingDataLoader(funding_path)
            except ImportError:
                pass  # Funding loader not available

    runner = TickBacktestRunner(
        strategy=strategy,
        data_loader=loader,
        bar_type=bar_type,
        bar_size=bar_size,
        initial_capital=initial_capital,
        fee_rate=fee_rate,
        maker_fee_rate=maker_fee_rate,
        taker_fee_rate=taker_fee_rate,
        leverage=leverage,
        funding_loader=funding_loader,
    )

    report = runner.run(start_time=start_date, end_time=end_date)
    return report, runner


def _run_orderbook_backtest(
    strategy,
    data_path: Path,
    initial_capital: float,
    leverage: int,
    start_date=None,
    end_date=None,
    fee_rate: float | None = None,
    maker_fee_rate: float = 0.0002,
    taker_fee_rate: float = 0.0005,
):
    """Run orderbook backtest with OrderbookBacktestRunner."""
    try:
        from intraday.backtest.orderbook_runner import OrderbookBacktestRunner
        from intraday.data.orderbook_loader import OrderbookDataLoader
    except ImportError:
        raise ImportError("OrderbookBacktestRunner not available. Check imports.")

    loader = OrderbookDataLoader(data_path)

    runner = OrderbookBacktestRunner(
        strategy=strategy,
        data_loader=loader,
        initial_capital=initial_capital,
        fee_rate=fee_rate,
        maker_fee_rate=maker_fee_rate,
        taker_fee_rate=taker_fee_rate,
    )

    report = runner.run(start_time=start_date, end_time=end_date)
    return report, runner


def _format_report(report, runner, data_type: str) -> str:
    """Format backtest report as structured text."""
    # Get fee rates from runner's trader
    maker_fee_rate = 0.0002  # default (Binance futures maker)
    taker_fee_rate = 0.0005  # default (Binance futures taker)
    if hasattr(runner, '_trader'):
        if hasattr(runner._trader, 'maker_fee_rate'):
            maker_fee_rate = runner._trader.maker_fee_rate
        if hasattr(runner._trader, 'taker_fee_rate'):
            taker_fee_rate = runner._trader.taker_fee_rate
    elif hasattr(runner, 'maker_fee_rate') and hasattr(runner, 'taker_fee_rate'):
        maker_fee_rate = runner.maker_fee_rate
        taker_fee_rate = runner.taker_fee_rate

    # Basic metrics available in all reports
    lines = [
        "# Backtest Results",
        "",
        "## Configuration",
        "| Item | Value |",
        "|------|-------|",
        f"| Data Type | {data_type.upper()} |",
        f"| Leverage | {runner.leverage if hasattr(runner, 'leverage') else 1}x |",
        f"| Maker Fee | {maker_fee_rate * 100:.3f}% (Limit) |",
        f"| Taker Fee | {taker_fee_rate * 100:.3f}% (Market) |",
        "",
        "## Summary",
        "| Item | Value |",
        "|------|-------|",
        f"| Strategy | {report.strategy_name} |",
        f"| Symbol | {report.symbol} |",
        f"| Period | {report.start_time} ~ {report.end_time} |",
        f"| Initial Capital | ${report.initial_capital:,.2f} |",
        f"| Final Capital | ${report.final_capital:,.2f} |",
        f"| **Total Return** | **{report.total_return:+.2f}%** |",
        "",
        "## Trading Statistics",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total Trades | {report.total_trades} |",
        f"| Win Rate | {report.win_rate:.1f}% |",
        f"| Winning Trades | {report.winning_trades} |",
        f"| Losing Trades | {report.losing_trades} |",
        f"| Profit Factor | {report.profit_factor:.2f} |",
        f"| Avg Win | ${report.avg_win:.2f} |",
        f"| Avg Loss | ${report.avg_loss:.2f} |",
        "",
        "## Risk Metrics",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Max Drawdown | {report.max_drawdown:.2f}% |",
        f"| Sharpe Ratio | {report.sharpe_ratio:.2f} |",
        "",
        "## Costs",
        "| Item | Value |",
        "|------|-------|",
        f"| Total Fees | ${report.total_fees:.2f} |",
    ]

    # Add funding info if available
    if hasattr(report, 'total_funding_paid'):
        lines.append(f"| Funding Paid | ${report.total_funding_paid:+.2f} |")

    # Add execution stats
    lines.extend([
        "",
        "## Execution Stats",
        "| Item | Value |",
        "|------|-------|",
    ])

    if data_type == "tick":
        if hasattr(runner, 'tick_count'):
            lines.append(f"| Ticks Processed | {runner.tick_count:,} |")
        if hasattr(runner, 'bar_count'):
            lines.append(f"| Bars Generated | {runner.bar_count:,} |")
    else:
        if hasattr(runner, 'snapshot_count'):
            lines.append(f"| Snapshots Processed | {runner.snapshot_count:,} |")

    return "\n".join(lines)
