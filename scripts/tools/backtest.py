#!/usr/bin/env python3
"""Run a portfolio alpha backtest from CLI and emit JSON."""
from __future__ import annotations

import argparse
import importlib
import inspect
import json
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from intraday.backtest.multi_tick_runner import PortfolioTickBacktestRunner
from intraday.candle_builder import CandleType
from intraday.data.bar_loader import BarDataLoader
from intraday.data.loader import TickDataLoader

from scripts.tools.verify_artifact import verify_artifact


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.strptime(value, "%Y-%m-%d")


def _class_to_module_name(class_name: str) -> str:
    out = []
    for idx, char in enumerate(class_name):
        if char.isupper() and idx > 0 and not class_name[idx - 1].isupper():
            out.append("_")
        out.append(char.lower())
    return "".join(out)


def load_strategy_class(class_name: str) -> type:
    candidates = [
        f"intraday.strategies.multi.{_class_to_module_name(class_name)}",
        "intraday.strategies.multi._alpha_template",
        "intraday.strategies.multi",
    ]
    errors = []
    for module_name in candidates:
        try:
            if module_name in sys.modules:
                del sys.modules[module_name]
            module = importlib.import_module(module_name)
            cls = getattr(module, class_name, None)
            if isinstance(cls, type):
                return cls
        except Exception as exc:
            errors.append(f"{module_name}: {exc}")
    raise ValueError(f"strategy class not found: {class_name}; tried {errors}")


def build_loaders(
    *,
    symbols: list[str],
    data_path: Path,
    symbol_data_paths: dict[str, str],
    data_type: str,
) -> dict[str, TickDataLoader]:
    loaders = {}
    loader_cls = BarDataLoader if data_type == "bars" else TickDataLoader
    for symbol in symbols:
        path = Path(symbol_data_paths[symbol]) if symbol in symbol_data_paths else data_path
        candidate = data_path / symbol
        if symbol not in symbol_data_paths and candidate.exists():
            path = candidate
        if not path.exists():
            raise FileNotFoundError(f"data path not found for {symbol}: {path}")
        loaders[symbol] = loader_cls(path, symbol=symbol)
    return loaders


def run_backtest(args: argparse.Namespace) -> dict[str, Any]:
    symbols = [s.upper() for s in args.symbols]
    strategy_params = json.loads(args.strategy_params) if args.strategy_params else {}
    symbol_data_paths = json.loads(args.symbol_data_paths) if args.symbol_data_paths else {}

    strategy_cls = load_strategy_class(args.strategy)
    sig = inspect.signature(strategy_cls.__init__)
    if "symbols" in sig.parameters and "symbols" not in strategy_params:
        strategy_params["symbols"] = symbols
    strategy = strategy_cls(**strategy_params)

    data_path = Path(args.data_path)
    loaders = build_loaders(
        symbols=symbols,
        data_path=data_path,
        symbol_data_paths=symbol_data_paths,
        data_type=args.data_type,
    )
    output_dir = Path(args.output_dir)

    runner = PortfolioTickBacktestRunner(
        strategy=strategy,
        data_loaders=loaders,
        bar_type=CandleType[args.bar_type],
        bar_size=args.bar_size,
        initial_capital=args.initial_capital,
        position_size_pct=args.position_size_pct,
        maker_fee_rate=args.maker_fee_rate,
        taker_fee_rate=args.taker_fee_rate,
        leverage=args.leverage,
    )
    result = runner.run(start_time=parse_dt(args.start), end_time=parse_dt(args.end))
    runner.save_report(output_dir)
    verification = verify_artifact(output_dir)

    metrics = {
        "profit_factor": result.profit_factor,
        "total_return": result.total_return,
        "max_drawdown": -abs(result.max_drawdown),
        "total_trades": result.total_trades,
        "win_rate": result.win_rate,
        "sharpe": result.sharpe_ratio,
        "per_symbol": result.get_symbol_breakdown(),
    }
    return {
        "ok": verification["ok"],
        "artifact_dir": str(output_dir),
        "strategy": args.strategy,
        "symbols": symbols,
        "metrics": metrics,
        "verification": verification,
        "summary": {
            "initial_capital": result.initial_capital,
            "final_capital": result.final_capital,
            "tick_counts": result.tick_counts,
            "bar_counts": result.bar_counts,
            "data_type": args.data_type,
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run deterministic alpha backtest")
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--data-type", choices=["ticks", "bars"], default="bars")
    parser.add_argument("--data-path", default="data/futures_klines")
    parser.add_argument("--symbol-data-paths", default="")
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--bar-type", choices=["TIME", "VOLUME", "TICK", "DOLLAR"], default="TIME")
    parser.add_argument("--bar-size", type=float, default=60.0)
    parser.add_argument("--initial-capital", type=float, default=10000.0)
    parser.add_argument("--position-size-pct", type=float, default=1.0)
    parser.add_argument("--leverage", type=int, default=1)
    parser.add_argument("--maker-fee-rate", type=float, default=0.0002)
    parser.add_argument("--taker-fee-rate", type=float, default=0.0005)
    parser.add_argument("--strategy-params", default="")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--json", action="store_true", help="emit JSON only")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = run_backtest(args)
    except Exception as exc:
        result = {
            "ok": False,
            "error": str(exc),
            "traceback": traceback.format_exc(),
            "artifact_dir": args.output_dir,
        }
        print(json.dumps(result, indent=2, default=_json_default))
        return 2

    print(json.dumps(result, indent=2, default=_json_default))
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
