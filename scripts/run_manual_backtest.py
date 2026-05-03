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
import json
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
from intraday.strategies.multi.atr_volume_risk_momentum import (
    ATRVolumeRiskMomentumStrategy,
)


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


def build_strategy(symbols: list[str]) -> ATRVolumeRiskMomentumStrategy:
    """Replace this function when testing a new strategy."""
    return ATRVolumeRiskMomentumStrategy(
        symbols=symbols,
        lookback_minutes=60,
        top_n=min(1, len(symbols)),
        bottom_n=0 if len(symbols) <= 1 else 1,
        rebalance_interval_minutes=60,
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
        "profit_factor": result.profit_factor,
        "total_return": result.total_return,
        "max_drawdown": -abs(result.max_drawdown),
        "total_trades": result.total_trades,
        "win_rate": result.win_rate,
        "sharpe": result.sharpe_ratio,
        "per_symbol": result.get_symbol_breakdown(),
    }
    (output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    (output_dir / "summary.json").write_text(
        json.dumps(
            {
                "symbols": symbols,
                "bar_type": args.bar_type,
                "bar_size": args.bar_size,
                "initial_capital": args.initial_capital,
                "final_capital": result.final_capital,
                "metrics": metrics,
            },
            indent=2,
        )
    )
    pd.DataFrame([metrics | {"per_symbol": json.dumps(metrics["per_symbol"])}]).to_csv(
        output_dir / "summary.csv",
        index=False,
    )

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
    pd.DataFrame(columns=["timestamp", "event", "metadata"]).to_parquet(
        output_dir / "events.parquet",
        index=False,
    )
    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "kind": "manual_backtest",
                "strategy": build_strategy.__name__,
                "artifacts": {
                    "weights": "weights.parquet",
                    "metrics": "metrics.json",
                    "equity_curve": "equity_curve.parquet",
                    "trades": "trades.parquet",
                    "events": "events.parquet",
                },
            },
            indent=2,
        )
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
