#!/usr/bin/env python3
"""Compute cross-sectional daily IC for one alpha split.

For ``<artifact_dir>`` = ``archive/<run>/alphas/<aid>/<split>``:
    1. Read weights.parquet (event log of target_weight changes).
    2. Forward-fill to a daily (date × symbol) position grid using each
       event's last value before end-of-day.
    3. Load daily close prices for the run's universe (from
       ``data/futures_klines_daily/<SYM>/`` if available, else resample
       1m from ``data/futures_klines/<SYM>/``).
    4. Compute forward 1-day returns r[t+1] = close[t+1]/close[t] - 1.
    5. For each date t with ≥ 2 valid positions: IC[t] = Spearman rank
       correlation between position vector and forward-return vector
       across symbols.
    6. Write ``ic.json`` with ic_mean, ic_std, ic_ir, ic_t, ic_obs_days.

Does not modify ``metrics.json``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_daily_close(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.Series:
    """Return daily close indexed by date.

    Prefer ``data/futures_klines_daily/<SYM>/`` (already daily). Fall back
    to resampling 1m bars from ``data/futures_klines/<SYM>/``.
    """
    daily_dir = PROJECT_ROOT / "data" / "futures_klines_daily" / symbol
    if daily_dir.exists():
        files = sorted(daily_dir.glob("*.parquet"))
        if files:
            df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df = df[(df["timestamp"] >= start) & (df["timestamp"] <= end)]
            if df.empty:
                return pd.Series(dtype=float)
            s = df.set_index("timestamp")["close"].astype(float).sort_index()
            s.index = s.index.normalize()
            return s[~s.index.duplicated(keep="last")]

    minute_dir = PROJECT_ROOT / "data" / "futures_klines" / symbol
    if not minute_dir.exists():
        return pd.Series(dtype=float)
    files = sorted(minute_dir.rglob("*.parquet"))
    if not files:
        return pd.Series(dtype=float)
    parts = []
    for f in files:
        df = pd.read_parquet(f, columns=["timestamp", "close"])
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        parts.append(df)
    df = pd.concat(parts, ignore_index=True).sort_values("timestamp")
    df = df[(df["timestamp"] >= start) & (df["timestamp"] <= end)]
    if df.empty:
        return pd.Series(dtype=float)
    df["date"] = df["timestamp"].dt.normalize()
    return df.groupby("date")["close"].last().astype(float)


def _daily_positions(weights: pd.DataFrame, dates: pd.DatetimeIndex, symbols: list[str]) -> pd.DataFrame:
    """Forward-fill weight events to a (date × symbol) position grid.

    For each (date, symbol): take the last target_weight whose timestamp is
    ≤ end of that date. Symbols with no event before the date get 0.
    """
    w = weights.copy()
    w["timestamp"] = pd.to_datetime(w["timestamp"])
    w["date"] = w["timestamp"].dt.normalize()
    # Keep last event per (date, symbol)
    last_per_day = (
        w.sort_values("timestamp")
         .groupby(["symbol", "date"], as_index=False)["target_weight"]
         .last()
    )
    pos = last_per_day.pivot(index="date", columns="symbol", values="target_weight")
    pos = pos.reindex(dates).ffill().fillna(0.0)
    for s in symbols:
        if s not in pos.columns:
            pos[s] = 0.0
    return pos[symbols]


def compute_ic(artifact_dir: Path) -> dict:
    artifact_dir = Path(artifact_dir).resolve()
    metrics_path = artifact_dir / "metrics.json"
    manifest_path = artifact_dir / "manifest.json"
    if metrics_path.exists():
        meta = json.loads(metrics_path.read_text())
    else:
        meta = json.loads(manifest_path.read_text())
    universe = meta["symbols"]
    weights = pd.read_parquet(artifact_dir / "weights.parquet")
    if weights.empty:
        return {"ok": False, "reason": "weights.parquet empty"}

    weights["timestamp"] = pd.to_datetime(weights["timestamp"])
    start = weights["timestamp"].min().normalize()
    end = weights["timestamp"].max().normalize() + pd.Timedelta(days=2)

    closes = {s: _load_daily_close(s, start, end) for s in universe}
    closes = {s: c for s, c in closes.items() if not c.empty}
    if not closes:
        return {"ok": False, "reason": "no daily price data for universe"}

    all_dates = sorted(set().union(*[c.index for c in closes.values()]))
    dates = pd.DatetimeIndex(all_dates)
    close_df = pd.DataFrame({s: c.reindex(dates) for s, c in closes.items()})
    ret_fwd = close_df.pct_change(1).shift(-1)

    universe_with_prices = [s for s in universe if s in close_df.columns]
    pos = _daily_positions(weights, dates, universe_with_prices)

    ics: list[float] = []
    n_obs_pairs: list[int] = []
    for d in dates:
        sig = pos.loc[d].values.astype(float)
        ret = ret_fwd.loc[d].values.astype(float)
        mask = ~(np.isnan(sig) | np.isnan(ret))
        if mask.sum() < 2:
            continue
        s = sig[mask]
        r = ret[mask]
        if np.all(s == s[0]):  # constant signal — Spearman undefined
            continue
        rho, _ = spearmanr(s, r)
        if not np.isnan(rho):
            ics.append(float(rho))
            n_obs_pairs.append(int(mask.sum()))

    if not ics:
        return {"ok": False, "reason": "no IC observations"}

    arr = np.array(ics)
    ic_mean = float(arr.mean())
    ic_std = float(arr.std(ddof=1)) if len(arr) > 1 else 0.0
    ic_ir = ic_mean / ic_std if ic_std > 0 else 0.0
    ic_t = ic_mean / (ic_std / np.sqrt(len(arr))) if ic_std > 0 else 0.0
    return {
        "ok": True,
        "ic_mean": ic_mean,
        "ic_std": ic_std,
        "ic_ir": ic_ir,
        "ic_t": ic_t,
        "ic_obs_days": len(arr),
        "median_breadth": float(np.median(n_obs_pairs)),
        "min_breadth": int(min(n_obs_pairs)),
        "max_breadth": int(max(n_obs_pairs)),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("artifact_dir", help="archive/<run>/alphas/<aid>/<split>")
    ap.add_argument("--write", action="store_true", help="write ic.json into artifact_dir")
    args = ap.parse_args(argv)

    result = compute_ic(Path(args.artifact_dir))
    print(json.dumps(result, indent=2))
    if args.write and result.get("ok"):
        out = Path(args.artifact_dir) / "ic.json"
        out.write_text(json.dumps(result, indent=2) + "\n")
        print(f"wrote: {out}", file=sys.stderr)
    return 0 if result.get("ok") else 2


if __name__ == "__main__":
    sys.exit(main())
