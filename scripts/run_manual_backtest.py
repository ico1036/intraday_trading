#!/usr/bin/env python3
"""Manual portfolio backtest example.

This file is intentionally small. It shows the whole path without the agent:

1. choose symbols and data paths
2. instantiate a strategy
3. run PortfolioTickBacktestRunner
4. print metrics
5. persist simple artifact files

To test your own alpha, copy `_alpha_template.py` into
`src/intraday/strategies/multi/<name>.py`, import it below, and replace
`build_strategy`.
"""
from __future__ import annotations

import argparse
import inspect
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from intraday.backtest.multi_tick_runner import PortfolioTickBacktestRunner
from intraday.candle_builder import CandleType
from intraday.data import TickDataLoader
from intraday.strategies.multi._alpha_template import AlphaTemplateStrategy


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Manual portfolio backtest")
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    parser.add_argument("--data-root", default="data/futures_ticks")
    parser.add_argument("--year", default="2025")
    parser.add_argument("--start", default="2025-03-01")
    parser.add_argument("--end", default="2025-03-31 23:59:59")
    parser.add_argument(
        "--bar-type",
        default="VOLUME",
        choices=["VOLUME", "TIME", "TICK", "DOLLAR"],
    )
    parser.add_argument("--bar-size", type=float, default=20.0)
    parser.add_argument("--initial-capital", type=float, default=100_000.0)
    parser.add_argument("--position-size-pct", type=float, default=1.0)
    parser.add_argument("--leverage", type=int, default=1)
    parser.add_argument("--output-dir", default="archive/manual_backtest")
    return parser.parse_args()


def parse_dt(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return datetime.strptime(value, "%Y-%m-%d")


def build_loaders(
    symbols: list[str],
    data_root: Path,
    year: str,
) -> dict[str, TickDataLoader]:
    loaders: dict[str, TickDataLoader] = {}
    for symbol in symbols:
        path = data_root / symbol / year
        if not path.exists():
            raise FileNotFoundError(f"missing data for {symbol}: {path}")
        loaders[symbol] = TickDataLoader(path, symbol=symbol)
    return loaders


def build_strategy(symbols: list[str]) -> AlphaTemplateStrategy:
    """Replace this function when testing a new strategy."""
    return AlphaTemplateStrategy(
        symbols=symbols,
        lookback_bars=24,
        rebalance_bars=1,
        entry_threshold=0.003,
        exit_threshold=0.001,
        max_weight=min(1.0, 1.0 / max(1, len(symbols))),
    )


def save_artifacts(
    output_dir: Path,
    result,
    symbols: list[str],
    args: argparse.Namespace,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamps = getattr(result, "equity_curve", pd.Series(dtype=float)).index
    equity_df = pd.DataFrame(
        {
            "step": range(len(result.equity_curve)),
            "equity": list(result.equity_curve),
        }
    )
    if len(timestamps) == len(equity_df):
        equity_df["timestamp"] = timestamps
    equity_df.to_parquet(output_dir / "equity_curve.parquet", index=False)

    trades_df = pd.DataFrame(result.trade_log)
    trades_df.to_parquet(output_dir / "trades.parquet", index=False)

    metrics = {
        "artifact_version": 2,
        "run_type": "manual_backtest",
        "strategy_class": build_strategy.__name__,
        "strategy_source": "strategy_source.py",
        "symbols": symbols,
        "bar_type": args.bar_type,
        "bar_size": args.bar_size,
        "initial_capital": args.initial_capital,
        "final_capital": result.final_capital,
        "profit_factor": result.profit_factor,
        "total_return": result.total_return,
        "max_drawdown": -abs(result.max_drawdown),
        "total_trades": result.total_trades,
        "win_rate": result.win_rate,
        "sharpe": result.sharpe_ratio,
        "per_symbol": result.get_symbol_breakdown(),
        "validation_flags": [],
    }
    (output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))

    # This runner does not expose target weight history yet. Keep an explicit
    # placeholder so readers know where the alpha ledger belongs.
    pd.DataFrame(
        columns=[
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
        ]
    ).to_parquet(output_dir / "weights.parquet", index=False)
    try:
        src = Path(inspect.getfile(build_strategy))
        shutil.copy2(src, output_dir / "strategy_source.py")
        metrics["source_original_path"] = str(src)
        (output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    except Exception:
        (output_dir / "strategy_source.py").write_text(
            f"# source unavailable for {build_strategy.__name__}\n"
        )


def main() -> int:
    args = parse_args()
    symbols = [s.upper() for s in args.symbols]
    data_root = PROJECT_ROOT / args.data_root

    loaders = build_loaders(symbols, data_root, args.year)
    strategy = build_strategy(symbols)

    runner = PortfolioTickBacktestRunner(
        strategy=strategy,
        data_loaders=loaders,
        bar_type=CandleType[args.bar_type],
        bar_size=args.bar_size,
        initial_capital=args.initial_capital,
        position_size_pct=args.position_size_pct,
        leverage=args.leverage,
    )
    result = runner.run(start_time=parse_dt(args.start), end_time=parse_dt(args.end))

    print(result.summary())
    print("Per-symbol:")
    for symbol, stats in result.get_symbol_breakdown().items():
        print(f"  {symbol}: pnl={stats['total_pnl']:.2f}, trades={stats['trades']}")

    output_dir = PROJECT_ROOT / args.output_dir
    save_artifacts(output_dir, result, symbols, args)
    print(f"Artifacts: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
