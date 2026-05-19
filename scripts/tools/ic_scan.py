#!/usr/bin/env python3
"""Scan every alpha's IC across the archive.

Builds a daily kline panel once (across the union of all alpha
universes), then iterates each ``archive/<run>/alphas/<aid>/`` and
computes Information Coefficient from the most informative weights
parquet available (forward > is > os, since forward inherits the
unified pipeline). Output: ``/tmp/ic_distribution.csv`` plus a
percentile summary to stdout for choosing a SUBMITTABLE threshold.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = REPO_ROOT / "data" / "futures_klines_daily"
ARCHIVE = REPO_ROOT / "archive"


def _build_next_ret_panel(symbols: list[str]) -> pd.DataFrame:
    """Concatenated close panel → next-bar returns. Daily candles only."""
    closes = {}
    for sym in symbols:
        sym_dir = DATA_ROOT / sym
        if not sym_dir.is_dir():
            continue
        parts = sorted(sym_dir.glob(f"{sym}-*.parquet"))
        if not parts:
            continue
        try:
            df = pd.concat([pd.read_parquet(p, columns=["timestamp", "close"])
                            for p in parts], ignore_index=True)
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            df = (df.dropna(subset=["timestamp", "close"])
                    .drop_duplicates(subset=["timestamp"])
                    .sort_values("timestamp")
                    .set_index("timestamp"))
            closes[sym] = df["close"].astype(float)
        except Exception:
            continue
    if not closes:
        return pd.DataFrame()
    panel = pd.DataFrame(closes).sort_index()
    return panel.pct_change().shift(-1)


def _compute_ic_fast(weights_df: pd.DataFrame, next_ret: pd.DataFrame) -> dict:
    if weights_df is None or weights_df.empty or next_ret.empty:
        return {}
    if not {"timestamp", "symbol", "target_weight"}.issubset(weights_df.columns):
        return {}
    w = weights_df[["timestamp", "symbol", "target_weight"]].copy()
    w["timestamp"] = pd.to_datetime(w["timestamp"])
    w["symbol"] = w["symbol"].astype(str).str.upper()
    ic: list[float] = []
    for ts, grp in w.groupby("timestamp"):
        if ts not in next_ret.index:
            nearest = next_ret.index.asof(ts)
            if pd.isna(nearest):
                continue
            ts = nearest
        rets = next_ret.loc[ts]
        wts = grp.set_index("symbol")["target_weight"].astype(float)
        joined = pd.concat([wts.rename("w"), rets.rename("r")], axis=1).dropna()
        if len(joined) < 5:
            continue
        if joined["w"].nunique() < 2 or joined["r"].nunique() < 2:
            continue
        c = joined["w"].rank().corr(joined["r"].rank())
        if pd.notna(c):
            ic.append(float(c))
    if not ic:
        return {}
    s = pd.Series(ic)
    mean = float(s.mean())
    std = float(s.std(ddof=1)) if len(s) > 1 else 0.0
    ir = (mean / std * math.sqrt(365)) if std > 0 else None
    sign = 1 if mean >= 0 else -1
    hit = float(((s * sign) > 0).mean())
    return {
        "ic_mean": mean,
        "ic_std": std,
        "ic_ir": ir,
        "ic_hit_rate": hit,
        "ic_bars": int(len(s)),
    }


def main() -> int:
    print(f"[ic_scan] data root: {DATA_ROOT}", flush=True)
    all_symbols = sorted({p.name for p in DATA_ROOT.iterdir() if p.is_dir()})
    print(f"[ic_scan] symbols on disk: {len(all_symbols)}", flush=True)
    next_ret = _build_next_ret_panel(all_symbols)
    if next_ret.empty:
        print("[ic_scan] no kline panel — aborting", file=sys.stderr)
        return 1
    print(f"[ic_scan] kline panel built: {next_ret.shape}", flush=True)

    rows = []
    alpha_dirs: list[tuple[str, Path]] = []
    for splits_p in ARCHIVE.glob("*/splits.json"):
        run_id = splits_p.parent.name
        alphas_dir = splits_p.parent / "alphas"
        if not alphas_dir.is_dir():
            continue
        for ad in sorted(alphas_dir.iterdir()):
            if ad.is_dir():
                alpha_dirs.append((run_id, ad))
    print(f"[ic_scan] {len(alpha_dirs)} alphas to scan", flush=True)

    for i, (run_id, ad) in enumerate(alpha_dirs, 1):
        weights_path = None
        src = None
        for cand_src in ("forward", "is", "os"):
            p = ad / cand_src / "weights.parquet"
            if p.exists():
                weights_path = p
                src = cand_src
                break
        if weights_path is None:
            # flat layout (single weights.parquet at alpha_dir)
            p = ad / "weights.parquet"
            if p.exists():
                weights_path = p
                src = "flat"
        if weights_path is None:
            continue
        try:
            wdf = pd.read_parquet(weights_path)
            stats = _compute_ic_fast(wdf, next_ret)
        except Exception as exc:
            stats = {"err": str(exc)[:80]}
        rows.append({
            "run_id": run_id,
            "alpha_id": ad.name,
            "src": src,
            **stats,
        })
        if i % 25 == 0 or i == len(alpha_dirs):
            print(f"  [{i}/{len(alpha_dirs)}] last: {ad.name} src={src}", flush=True)

    df = pd.DataFrame(rows)
    out_csv = Path("/tmp/ic_distribution.csv")
    df.to_csv(out_csv, index=False)
    print(f"\n[ic_scan] saved: {out_csv}  rows={len(df)}", flush=True)

    if "ic_mean" in df.columns:
        abs_ic = df["ic_mean"].abs().dropna()
        abs_ir = df["ic_ir"].abs().dropna()
        print(f"\n=== |IC| distribution (N={len(abs_ic)}) ===")
        for p in (0.1, 0.25, 0.5, 0.7, 0.8, 0.9, 0.95, 0.99):
            print(f"  p{int(p*100):>2}: {abs_ic.quantile(p):.4f}")
        print(f"\n=== |IC_IR| distribution (N={len(abs_ir)}) ===")
        for p in (0.1, 0.25, 0.5, 0.7, 0.8, 0.9, 0.95, 0.99):
            print(f"  p{int(p*100):>2}: {abs_ir.quantile(p):.3f}")
        joint = df[(df["ic_mean"].abs() > 0.03) & (df["ic_ir"].abs() > 1.5)]
        print(f"\nalphas passing |IC|>0.03 & |IR|>1.5: {len(joint)}/{len(df)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
