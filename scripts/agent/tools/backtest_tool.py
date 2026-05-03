"""MCP portfolio backtest tool.

Discovers strategies from ``src/intraday/strategies/multi`` and runs them
through the portfolio backtest engine with tick input data.

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
import inspect
import json
import sys
from pathlib import Path
from typing import Any

# Add src to path for imports
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from claude_agent_sdk import tool

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
        data_type: currently only "multi"

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
    """Get available portfolio strategies with metadata."""
    result = {}

    for name, cls in _discover_strategies("multi").items():
        result[name] = {
            "class": cls,
            "data_type": "tick",
        }

    return result


async def _get_available_strategies_impl(args: dict[str, Any]) -> dict[str, Any]:
    """Return list of available strategies with their parameters (implementation)."""
    import inspect

    all_strategies = _get_all_strategies()
    strategies_info = []

    for name, info in all_strategies.items():
        cls = info["class"]

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

        strategies_info.append({"name": name, "parameters": params})

    # Format output
    lines = ["# Available Portfolio Strategies\n"]
    if not strategies_info:
        lines.append("(none found)")
    for info in strategies_info:
        lines.append(f"\n### {info['name']}")
        lines.append("Parameters:")
        for param, default in info["parameters"].items():
            lines.append(f"  - {param}: {default}")

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


def _infer_symbols_from_data_path(data_path: Path, explicit_symbols: list[str] | None) -> list[str]:
    """Discover trading symbols from data path.

    우선순위:
    1) explicit_symbols (사용자 전달)
    2) 하위 폴더 이름 (예: BTCUSDT, ETHUSDT)
    3) 파일명에서 USDT 계열 토큰 추론
    4) 마지막으로 경로명 하나만 사용
    """
    if explicit_symbols:
        result: list[str] = []
        seen = set()
        for sym in explicit_symbols:
            up = str(sym).upper().strip()
            if up and up not in seen:
                seen.add(up)
                result.append(up)
        return result

    if not data_path.exists():
        return []

    # 2) 폴더 기반 유니버스
    if data_path.is_dir():
        folder_symbols = []
        seen = set()
        for child in sorted(data_path.iterdir()):
            if not child.is_dir():
                continue
            # 폴더명 자체를 심볼 유니버스 후보로 우선 사용 (디스크 데이터 정리 시 빈 디렉터리가 먼저 보일 수 있어도
            # 사용자 의도는 폴더 단위 심볼 배치인 경우가 많음)
            sym = child.name.upper()
            if sym not in seen:
                seen.add(sym)
                folder_symbols.append(sym)
        if folder_symbols:
            return folder_symbols

    # 3) 파일명에서 추론
    import re

    candidates = set()
    if data_path.is_dir():
        files = sorted(data_path.glob("**/*.parquet"))
    else:
        files = [data_path]

    for f in files:
        token = f.stem.upper()
        matched = re.findall(r"[A-Z0-9]+USDT", token)
        if matched:
            candidates.update(matched)
        if len(candidates) >= 8:
            break

    if candidates:
        return sorted(candidates)

    # 4) 폴백: 경로명 자체
    return [data_path.name.upper()]


async def _run_backtest_impl(args: dict[str, Any]) -> dict[str, Any]:
    """
    Run a backtest with the specified strategy (implementation).

    Args:
        strategy: Strategy class name (e.g., "ATRVolumeRiskMomentumStrategy")
        data_type: must be "tick" because portfolio strategies consume tick data
        data_path: Path to tick data directory
        start_date: Start date ("YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS")
        end_date: End date ("YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS")
        bar_type: Bar type ("VOLUME", "TICK", "TIME", "DOLLAR")
        bar_size: Bar size
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
        strategy_name = args.get("strategy", "ATRVolumeRiskMomentumStrategy")
        data_type = args.get("data_type", "tick").lower()
        data_path = Path(args.get("data_path", "./data/futures_ticks"))
        # Optional universe override: explicit symbols. If omitted, infer from data_path.
        symbols = args.get("symbols")
        symbol_data_paths_raw = args.get("symbol_data_paths", {})

        # Parse symbol_data_paths - handle both dict and JSON string
        if isinstance(symbol_data_paths_raw, str):
            try:
                symbol_data_paths_raw = json.loads(symbol_data_paths_raw) if symbol_data_paths_raw else {}
            except json.JSONDecodeError:
                return {
                    "content": [{
                        "type": "text",
                        "text": f"Error: Invalid JSON in symbol_data_paths: {symbol_data_paths_raw}"
                    }],
                    "is_error": True
                }
        bar_type_str = args.get("bar_type", "VOLUME").upper()
        bar_size = float(args.get("bar_size", 10.0))
        initial_capital = float(args.get("initial_capital", 10000.0))
        leverage = int(args.get("leverage", 1))
        include_funding = args.get("include_funding", False)
        position_size_pct = float(args.get("position_size_pct", 0.1))
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
            # If end_date has no time component (00:00:00), set to end of day
            # so that "2025-03-01" includes the entire day's data
            if end_date.hour == 0 and end_date.minute == 0 and end_date.second == 0:
                end_date = end_date.replace(hour=23, minute=59, second=59)

        # Validate data_type. The strategy surface is unified under multi/;
        # "tick" here only describes the historical input data.
        if data_type != "tick":
            return {
                "content": [{
                    "type": "text",
                    "text": f"Error: Invalid data_type '{data_type}'. Must be 'tick'."
                }],
                "is_error": True
            }

        # Discover and validate strategy (exact match required)
        all_strategies = _get_all_strategies()
        if strategy_name not in all_strategies:
            available = sorted(all_strategies)
            return {
                "content": [{
                    "type": "text",
                    "text": f"Error: Unknown strategy '{strategy_name}'. Available strategies: {available}."
                }],
                "is_error": True
            }

        strategy_info = all_strategies[strategy_name]

        # Validate bar type.
        if bar_type_str not in BAR_TYPES:
            return {
                "content": [{
                    "type": "text",
                    "text": f"Error: Unknown bar_type '{bar_type_str}'. Available: {list(BAR_TYPES.keys())}"
                }],
                "is_error": True
            }

        # Validate bar_size for VOLUME bars (practical limit to prevent slow backtests)
        if bar_type_str == "VOLUME" and bar_size < 10.0:
            return {
                "content": [{
                    "type": "text",
                    "text": f"Error: bar_size={bar_size} BTC is too small. MUST be >= 10.0 BTC.\n"
                           f"(Creates millions of bars, backtest takes hours)"
                }],
                "is_error": True
            }
        
        # Validate bar_size for TIME bars (practical limit)
        if bar_type_str == "TIME" and bar_size < 60:
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

        # Normalize symbols input (used only for tick path)
        if isinstance(symbols, str):
            symbols = [s for s in symbols.replace(",", " ").split() if s]
        elif not isinstance(symbols, (list, tuple)):
            symbols = []
        symbols = _infer_symbols_from_data_path(data_path, list(symbols))

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
        sig = inspect.signature(strategy_cls.__init__)

        # Some multi-symbol strategies require explicit symbols argument.
        # Previously this was not injected consistently, causing "missing symbols" errors.
        if "symbols" in sig.parameters and "symbols" not in strategy_params:
            strategy_params = {**strategy_params, "symbols": symbols}

        if "symbols" in sig.parameters:
            symbol_count = len(strategy_params.get("symbols", []))
            if symbol_count < 1:
                return {
                    "content": [{
                        "type": "text",
                        "text": f"Error: Strategy '{strategy_name}' requires at least 1 symbol for initialization, got {symbol_count}: {strategy_params.get('symbols', [])}"
                    }],
                    "is_error": True
                }

        strategy = strategy_cls(**strategy_params)

        report, runner = _run_portfolio_like_tick_backtest(
            strategy=strategy,
            data_path=data_path,
            symbol_data_paths=symbol_data_paths_raw,
            symbols=symbols,
            bar_type=BAR_TYPES[bar_type_str],
            bar_size=bar_size,
            initial_capital=initial_capital,
            leverage=leverage,
            start_date=start_date,
            end_date=end_date,
            include_funding=include_funding,
            fee_rate=fee_rate,
            maker_fee_rate=maker_fee_rate,
            taker_fee_rate=taker_fee_rate,
            position_size_pct=position_size_pct,
        )
        result = _format_portfolio_report(report)

        # Save report to specified output directory
        output_dir_str = args.get("output_dir")
        if output_dir_str:
            output_dir = PROJECT_ROOT / output_dir_str
            try:
                report_path = runner.save_report(output_dir)
                result += f"\n\n**Report saved to**: {report_path}"
            except Exception as e:
                result += f"\n\n**Warning**: Failed to save report: {e}"

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
        "data_type": str,  # must be "tick"; strategies live under multi/
        "data_path": str,
        "symbols": list,
        "symbol_data_paths": dict,
        "start_date": str,  # "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS"
        "end_date": str,  # "YYYY-MM-DD" or "YYYY-MM-DD HH:MM:SS"
        "bar_type": str,
        "bar_size": float,
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


def _run_portfolio_like_tick_backtest(
    strategy,
    data_path: Path,
    symbol_data_paths,
    symbols: list[str],
    bar_type: CandleType,
    bar_size: float,
    initial_capital: float,
    leverage: int,
    start_date=None,
    end_date=None,
    include_funding: bool = False,
    fee_rate: float | None = None,
    maker_fee_rate: float = 0.0002,
    taker_fee_rate: float = 0.0005,
    position_size_pct: float = 0.1,
):
    """Run tick backtest with PortfolioTickBacktestRunner.

    - 유니버스 크기와 무관하게 동일 포트폴리오 엔진 사용
    - symbol_data_paths를 통한 개별 경로 주입 지원
    """
    from intraday.data.loader import TickDataLoader
    from intraday.backtest.multi_tick_runner import PortfolioTickBacktestRunner

    if not symbols:
        symbols = ["BTCUSDT"]

    loaders = {}
    for sym in symbols:
        path = data_path
        if symbol_data_paths and sym in symbol_data_paths:
            path = Path(symbol_data_paths[sym])
        else:
            candidate = data_path / sym
            if candidate.exists():
                path = candidate

        if not path.exists():
            raise FileNotFoundError(f"Data path not found for {sym}: {path}")

        loaders[sym] = TickDataLoader(path, symbol=sym)

    # 기본 position_size_pct=0.1이지만 전략의 weight 기반 결정이나 runner 파라미터로 오버라이드 가능
    runner = PortfolioTickBacktestRunner(
        strategy=strategy,
        data_loaders=loaders,
        bar_type=bar_type,
        bar_size=bar_size,
        initial_capital=initial_capital,
        position_size_pct=position_size_pct,
        maker_fee_rate=maker_fee_rate,
        taker_fee_rate=taker_fee_rate,
        leverage=leverage,
    )

    report = runner.run(start_time=start_date, end_time=end_date)
    return report, runner





def _format_portfolio_report(result) -> str:
    """포트폴리오 백테스트 결과를 마크다운으로 포맷"""
    lines = [
        "# Portfolio Backtest Results",
        "",
        "## Summary",
        "| Item | Value |",
        "|------|-------|",
        f"| Initial Capital | ${result.initial_capital:,.2f} |",
        f"| Final Capital | ${result.final_capital:,.2f} |",
        f"| **Total Return** | **{result.total_return * 100:+.2f}%** |",
        f"| Sharpe Ratio | {result.sharpe_ratio:.2f} |",
        f"| Max Drawdown | {result.max_drawdown * 100:.2f}% |",
        f"| Total Trades | {result.total_trades} |",
        f"| Win Rate | {result.win_rate * 100:.1f}% |",
        f"| Profit Factor | {result.profit_factor:.2f} |",
    ]

    breakdown = result.get_symbol_breakdown()
    if breakdown:
        lines.extend([
            "",
            "## Symbol Breakdown",
            "| Symbol | PnL | Trades | Wins | Losses |",
            "|--------|-----|--------|------|--------|",
        ])
        for sym, info in sorted(breakdown.items()):
            lines.append(
                f"| {sym} | ${info['total_pnl']:+.2f} | "
                f"{info['trades']} | {info['wins']} | {info['losses']} |"
            )

    if result.tick_counts:
        lines.extend([
            "",
            "## Execution Stats",
            "| Symbol | Ticks | Bars |",
            "|--------|-------|------|",
        ])
        for sym in sorted(result.tick_counts.keys()):
            ticks = result.tick_counts.get(sym, 0)
            bars = result.bar_counts.get(sym, 0)
            lines.append(f"| {sym} | {ticks:,} | {bars:,} |")

    return "\n".join(lines)


async def _run_portfolio_backtest_impl(args: dict) -> dict:
    """Portfolio backtest entry (same engine as run_backtest)."""
    try:
        symbols = list(args.get("symbols", []))
        data_paths_raw = args.get("data_paths", {})

        if not symbols and data_paths_raw:
            symbols = list(data_paths_raw.keys())

        base_path = str(args.get("data_path", str(PROJECT_ROOT / "data" / "futures_ticks")))
        forward_args = {k: v for k, v in args.items() if k not in {"symbol_data_paths", "data_paths", "symbols"}}

        strategy_params = args.get("strategy_params", {})
        if isinstance(strategy_params, dict) and symbols and "symbols" not in strategy_params:
            strategy_params = {**strategy_params, "symbols": symbols}
            forward_args["strategy_params"] = strategy_params

        if not symbols:
            return await _run_backtest_impl({
                **forward_args,
                "strategy": args.get("strategy", "PortfolioMomentum"),
                "data_type": "tick",
                "data_path": base_path,
                "symbols": symbols,
            })

        if not data_paths_raw:
            data_paths_raw = {sym: str(Path(base_path) / sym) for sym in symbols}

        return await _run_backtest_impl({
            **forward_args,
            "data_type": "tick",
            "symbols": symbols,
            "symbol_data_paths": data_paths_raw,
            "strategy": args.get("strategy", "PortfolioMomentum"),
            "data_path": base_path,
        })

    except Exception as e:
        import traceback
        return {
            "content": [{
                "type": "text",
                "text": f"Error running portfolio backtest: {str(e)}\n\n{traceback.format_exc()}",
            }],
            "is_error": True,
        }





@tool(
    "run_portfolio_backtest",
    "Run portfolio backtest for one or more symbols.",
    {
        "strategy": str,
        "symbols": list,
        "data_paths": dict,
        "start_date": str,
        "end_date": str,
        "bar_type": str,
        "bar_size": float,
        "initial_capital": float,
        "leverage": int,
        "position_size_pct": float,
        "strategy_params": str,
        "maker_fee_rate": float,
        "taker_fee_rate": float,
    },
)
async def run_portfolio_backtest(args: dict) -> dict:
    """Canonical wrapper for portfolio backtest."""
    return await _run_portfolio_backtest_impl(args)
