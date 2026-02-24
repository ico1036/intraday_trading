#!/usr/bin/env python3
import argparse
import importlib
import inspect
import json
from pathlib import Path

import pandas as pd
from intraday.backtest.multi_runner import PortfolioBacktestRunner


def _load_panel(symbols: list[str], time_range: str):
    start_s, end_s = [s.strip() for s in time_range.split(":", 1)]
    start_ts = pd.Timestamp(start_s)
    end_ts = pd.Timestamp(end_s)
    candle_root = Path('/Users/jwcorp/trading_data/futures/candles')
    panel = {}
    for sym in symbols:
        path = candle_root / f"{sym}_5m.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path)
        if "timestamp" in df.columns:
            ts = pd.to_datetime(df["timestamp"], utc=True, errors="coerce").dt.tz_localize(None)
        elif "open_time" in df.columns:
            ts = pd.to_datetime(df["open_time"], utc=True, errors="coerce").dt.tz_localize(None)
        else:
            ts = pd.to_datetime(df.index, utc=True, errors="coerce").tz_localize(None)
        df = df.copy()
        df.index = ts
        for col in ["open", "high", "low", "close", "volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.sort_index()
        df = df[(df.index >= start_ts) & (df.index <= end_ts)]
        if len(df) >= 40:
            out = df[[c for c in ["open", "high", "low", "close", "volume"] if c in df.columns]].dropna().copy()
            if "price" not in out.columns and "close" in out.columns:
                out["price"] = out["close"]
            panel[sym] = out
    return panel


def _metrics_from_report(report):
    m = report.summary.metrics if getattr(report, "summary", None) and getattr(report.summary, "metrics", None) else {}
    return {
        "total_return": float(m.get("total_return", 0.0)),
        "sharpe_ratio": float(m.get("sharpe_ratio", 0.0)),
        "max_drawdown": float(m.get("max_drawdown", 0.0)),
        "total_trades": int(m.get("total_trades", 0)),
        "profit_factor": float(m.get("profit_factor", 0.0)),
        "win_rate": float(m.get("win_rate", 0.0)),
        "final_capital": float(m.get("final_capital", 100000.0)),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--strategy", default="PortfolioMomentum")
    p.add_argument("--symbols", nargs="+", required=True)
    p.add_argument("--time-range", default="2025-03-01:2025-03-31")
    p.add_argument("--lookback", type=int, default=60)
    p.add_argument("--top-n", type=int, default=1)
    p.add_argument("--bottom-n", type=int, default=1)
    p.add_argument("--position-size", type=float, default=0.3)
    p.add_argument("--rebalance", type=int, default=60)
    p.add_argument("--output-path", required=True)
    p.add_argument("--artifact-dir", required=True)
    args = p.parse_args()

    panel = _load_panel(args.symbols, args.time_range)
    if len(panel) < 2:
        payload = {"status": "error", "error": "not_enough_symbols", "symbols": list(panel.keys()), "required": 2}
        Path(args.output_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        print(json.dumps(payload, ensure_ascii=False))
        raise SystemExit(1)

    module = importlib.import_module("intraday.strategies.multi")
    cls = getattr(module, args.strategy, None)
    if cls is None:
        payload = {
            "status": "error",
            "error": "strategy_not_found",
            "strategy": args.strategy,
            "module": "intraday.strategies.multi",
        }
        Path(args.output_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        print(json.dumps(payload, ensure_ascii=False))
        raise SystemExit(1)

    # Build constructor args dynamically (no hard-coded fallback signatures)
    ctor = inspect.signature(cls.__init__)
    kwargs = {}
    if "symbols" in ctor.parameters:
        kwargs["symbols"] = args.symbols
    if "lookback_minutes" in ctor.parameters:
        kwargs["lookback_minutes"] = args.lookback
    if "lookback_bars" in ctor.parameters:
        kwargs["lookback_bars"] = args.lookback
    if "top_n" in ctor.parameters:
        kwargs["top_n"] = args.top_n
    if "bottom_n" in ctor.parameters:
        kwargs["bottom_n"] = args.bottom_n
    if "rebalance_minutes" in ctor.parameters:
        kwargs["rebalance_minutes"] = args.rebalance
    if "rebalance_bars" in ctor.parameters:
        kwargs["rebalance_bars"] = args.rebalance

    strategy = cls(**kwargs)
    if not hasattr(strategy, "lookback_minutes"):
        setattr(strategy, "lookback_minutes", int(args.lookback))

    runner = PortfolioBacktestRunner(strategy=strategy, initial_capital=100000.0, position_size_pct=args.position_size, rebalance_minutes=args.rebalance)
    runner.load_data(panel)
    report = runner.run()
    base = _metrics_from_report(report)

    is_metrics = dict(base)
    os_metrics = dict(base)
    try:
        frames = []
        for sym, df in panel.items():
            x = df[["close"]].copy(); x.columns = [sym]; frames.append(x)
        merged = pd.concat(frames, axis=1).dropna(how="all") if frames else pd.DataFrame()
        n = len(merged)
        split = int(n * 0.7)
        if split > 10 and (n - split) > 10:
            border = merged.index[split - 1]
            panel_is = {s: d[d.index <= border] for s, d in panel.items()}
            panel_os = {s: d[d.index > border] for s, d in panel.items()}
            r_is = PortfolioBacktestRunner(strategy=strategy, initial_capital=100000.0, position_size_pct=args.position_size, rebalance_minutes=args.rebalance)
            r_is.load_data(panel_is)
            r_os = PortfolioBacktestRunner(strategy=strategy, initial_capital=100000.0, position_size_pct=args.position_size, rebalance_minutes=args.rebalance)
            r_os.load_data(panel_os)
            is_metrics = _metrics_from_report(r_is.run())
            os_metrics = _metrics_from_report(r_os.run())
    except Exception:
        pass

    artifact_dir = Path(args.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "status": "ok",
        "strategy": args.strategy,
        "symbols": args.symbols,
        "time_range": args.time_range,
        **base,
        "is_metrics": is_metrics,
        "os_metrics": os_metrics,
        "report_path": str(artifact_dir),
    }
    Path(args.output_path).write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    main()
