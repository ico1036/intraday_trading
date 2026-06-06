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
DATA_DAILY = REPO_ROOT / "data" / "futures_klines_daily"
DATA_MINUTE = REPO_ROOT / "data" / "futures_klines"
ARCHIVE = REPO_ROOT / "archive"


def _build_next_ret_panel(symbols: list[str], data_root: Path,
                          file_glob: str = "{sym}-*.parquet") -> pd.DataFrame:
    """Concatenated close panel → next-bar returns. ``data_root`` selects
    the candle frequency (daily kline dir vs 1m kline dir). Tries the
    direct glob first, falls back to a recursive search for layouts
    that bucket files into year subdirectories."""
    closes = {}
    for sym in symbols:
        sym_dir = data_root / sym
        if not sym_dir.is_dir():
            continue
        parts = sorted(sym_dir.glob(file_glob.format(sym=sym)))
        if not parts:
            parts = sorted(sym_dir.rglob(file_glob.format(sym=sym)))
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


def _compute_ic_fast(weights_df: pd.DataFrame, next_ret: pd.DataFrame,
                     is_end: str | None = None) -> dict:
    if weights_df is None or weights_df.empty or next_ret.empty:
        return {}
    if not {"timestamp", "symbol", "target_weight"}.issubset(weights_df.columns):
        return {}
    w = weights_df[["timestamp", "symbol", "target_weight"]].copy()
    w["timestamp"] = pd.to_datetime(w["timestamp"])
    w["symbol"] = w["symbol"].astype(str).str.upper()
    records: list[tuple[pd.Timestamp, float]] = []
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
            records.append((ts, float(c)))
    if not records:
        return {}
    s = pd.Series([v for _, v in records],
                  index=pd.to_datetime([t for t, _ in records]))
    mean = float(s.mean())
    std = float(s.std(ddof=1)) if len(s) > 1 else 0.0
    ir = (mean / std * math.sqrt(365)) if std > 0 else None
    sign = 1 if mean >= 0 else -1
    hit = float(((s * sign) > 0).mean())
    out = {
        "ic_mean": mean,
        "ic_std": std,
        "ic_ir": ir,
        "ic_hit_rate": hit,
        "ic_bars": int(len(s)),
        "ic_z": None,
    }
    if is_end:
        cutoff = pd.Timestamp(is_end)
        is_ic = s[s.index <= cutoff]
        os_ic = s[s.index > cutoff]
        if len(is_ic) >= 2 and len(os_ic) >= 2:
            mu_is, mu_os = float(is_ic.mean()), float(os_ic.mean())
            var_is, var_os = float(is_ic.var(ddof=1)), float(os_ic.var(ddof=1))
            denom = math.sqrt(var_is / len(is_ic) + var_os / len(os_ic))
            out["ic_z"] = (mu_is - mu_os) / denom if denom > 0 else None
    return out


def _load_bar_size(splits_path: Path, alpha_dir: Path) -> float | None:
    """Read bar_size_sec from metrics.json, with legacy summary fallback."""
    metrics_path = alpha_dir / "metrics.json"
    if metrics_path.exists():
        try:
            import json as _json
            v = _json.loads(metrics_path.read_text()).get("bar_size")
            if v is not None:
                return float(v)
        except Exception:
            pass
    for path in (
        alpha_dir / "summary.json",
        alpha_dir / "is" / "summary.json",
        alpha_dir / "forward" / "summary.json",
    ):
        if not path.exists():
            continue
        try:
            import json as _json
            v = _json.loads(path.read_text()).get("bar_size")
            if v is not None:
                return float(v)
        except Exception:
            continue
    return None


def main() -> int:
    print(f"[ic_scan] daily dir: {DATA_DAILY}", flush=True)
    print(f"[ic_scan] minute dir: {DATA_MINUTE}", flush=True)
    daily_syms = sorted({p.name for p in DATA_DAILY.iterdir() if p.is_dir()}) \
        if DATA_DAILY.exists() else []
    minute_syms = sorted({p.name for p in DATA_MINUTE.iterdir() if p.is_dir()}) \
        if DATA_MINUTE.exists() else []
    print(f"[ic_scan] daily symbols: {len(daily_syms)}  "
          f"minute symbols: {len(minute_syms)}", flush=True)

    # Minute kline panel is huge (274 sym × ~2.3M bars). To keep memory
    # bounded, restrict the 1m panel to the symbols any minute alpha
    # actually trades — those come from the legacy 7-coin alphas. If the
    # universe ever grows, this filter scales naturally with whatever
    # weights.parquet files contain.
    minute_universe: set[str] = set()
    for splits_p in ARCHIVE.glob("*/splits.json"):
        alphas_dir = splits_p.parent / "alphas"
        if not alphas_dir.is_dir():
            continue
        for ad in alphas_dir.iterdir():
            if not ad.is_dir():
                continue
            bar = _load_bar_size(None, ad)
            if bar is None or bar >= 86400 * 0.9:
                continue
            for sub_src in ("is", "os", "forward", ""):
                wp = ad / (sub_src + "/weights.parquet" if sub_src else "weights.parquet")
                if not wp.exists():
                    continue
                try:
                    syms = pd.read_parquet(wp, columns=["symbol"])["symbol"].astype(str).str.upper().unique()
                    minute_universe.update(syms.tolist())
                except Exception:
                    pass
                break
    if minute_universe:
        minute_syms = [s for s in minute_syms if s in minute_universe]
        print(f"[ic_scan] minute panel limited to {len(minute_syms)} symbols "
              f"(min alpha universe)", flush=True)

    panels: dict[str, pd.DataFrame] = {}
    if daily_syms:
        panels["1d"] = _build_next_ret_panel(daily_syms, DATA_DAILY)
        print(f"[ic_scan] daily panel: {panels['1d'].shape}", flush=True)
    if minute_syms:
        panels["1m"] = _build_next_ret_panel(minute_syms, DATA_MINUTE)
        print(f"[ic_scan] minute panel: {panels['1m'].shape}", flush=True)
    if not panels:
        print("[ic_scan] no panel built — aborting", file=sys.stderr)
        return 1

    def _panel_for(bar_sec: float | None) -> pd.DataFrame:
        if bar_sec is None:
            return panels.get("1d", panels.get("1m", pd.DataFrame()))
        if bar_sec >= 86400 * 0.9:
            return panels.get("1d", pd.DataFrame())
        return panels.get("1m", pd.DataFrame())

    # Below this comment the per-alpha loop runs against the right panel.
    next_ret = panels.get("1d", pd.DataFrame())  # legacy var for fallback

    rows = []
    alpha_dirs: list[tuple[str, Path, str | None]] = []
    for splits_p in ARCHIVE.glob("*/splits.json"):
        run_id = splits_p.parent.name
        alphas_dir = splits_p.parent / "alphas"
        if not alphas_dir.is_dir():
            continue
        try:
            is_end = (
                pd.io.json.read_json(str(splits_p), typ="series")["is"]["end"]
                if False else None
            )
        except Exception:
            is_end = None
        try:
            import json as _json
            is_end = (_json.loads(splits_p.read_text()).get("is") or {}).get("end")
        except Exception:
            is_end = None
        for ad in sorted(alphas_dir.iterdir()):
            if ad.is_dir():
                alpha_dirs.append((run_id, ad, is_end))
    print(f"[ic_scan] {len(alpha_dirs)} alphas to scan", flush=True)

    # IC is meaningful only on a long enough emit history. Always concat
    # every available weights parquet (is + os + forward, or the flat
    # full-period parquet) so the per-bar IC series spans the longest
    # window the alpha actually has, not just the slice the dashboard
    # happens to render.
    for i, (run_id, ad, is_end) in enumerate(alpha_dirs, 1):
        sources: list[Path] = []
        for cand_src in ("is", "os", "forward"):
            p = ad / cand_src / "weights.parquet"
            if p.exists():
                sources.append(p)
        if not sources and (ad / "weights.parquet").exists():
            sources.append(ad / "weights.parquet")
        src = "+".join(p.parent.name for p in sources) if sources else None
        if not sources:
            continue
        bar_sec = _load_bar_size(None, ad)
        panel = _panel_for(bar_sec)
        if panel.empty:
            continue
        try:
            wdf = pd.concat([pd.read_parquet(p) for p in sources], ignore_index=True)
            stats = _compute_ic_fast(wdf, panel, is_end=is_end)
            stats["bar_size_sec"] = bar_sec
        except Exception as exc:
            stats = {"err": str(exc)[:80], "bar_size_sec": bar_sec}
        rows.append({
            "run_id": run_id,
            "alpha_id": ad.name,
            "src": src,
            "trades_approx": None,
            **stats,
        })
        if i % 50 == 0 or i == len(alpha_dirs):
            print(f"  [{i}/{len(alpha_dirs)}] last: {ad.name} src={src}", flush=True)

    df = pd.DataFrame(rows)
    out_csv = Path("/tmp/ic_distribution.csv")
    df.to_csv(out_csv, index=False)
    print(f"\n[ic_scan] saved: {out_csv}  rows={len(df)}", flush=True)

    if "ic_mean" in df.columns:
        abs_ic = df["ic_mean"].abs().dropna()
        abs_ir = df["ic_ir"].abs().dropna()
        abs_z = df["ic_z"].abs().dropna() if "ic_z" in df.columns else pd.Series([], dtype=float)
        print(f"\n=== |IC| distribution (N={len(abs_ic)}) ===")
        for p in (0.1, 0.25, 0.5, 0.7, 0.8, 0.9, 0.95, 0.99):
            print(f"  p{int(p*100):>2}: {abs_ic.quantile(p):.4f}")
        print(f"\n=== |IC_IR| distribution (N={len(abs_ir)}) ===")
        for p in (0.1, 0.25, 0.5, 0.7, 0.8, 0.9, 0.95, 0.99):
            print(f"  p{int(p*100):>2}: {abs_ir.quantile(p):.3f}")
        if len(abs_z) > 0:
            print(f"\n=== |IC_z| distribution (N={len(abs_z)}) ===")
            for p in (0.1, 0.25, 0.5, 0.7, 0.8, 0.9, 0.95, 0.99):
                print(f"  p{int(p*100):>2}: {abs_z.quantile(p):.3f}")
            # Survival counts at common Welch z thresholds.
            for z_th in (1.0, 1.5, 2.0, 2.5, 3.0):
                print(f"  |z| < {z_th}: {(abs_z < z_th).sum()}/{len(abs_z)}"
                      f"  ({(abs_z < z_th).mean()*100:.1f}%)")

        # Survival of the full 4-gate (no |z| requirement counts as pass
        # for legacy rows where z is missing).
        ic_pass = df["ic_mean"].abs() > 0.03
        ir_pass = df["ic_ir"].abs() > 1.5
        z_pass = df["ic_z"].abs() < 2.0 if "ic_z" in df.columns else True
        z_pass = z_pass.where(df["ic_z"].notna(), True) if "ic_z" in df.columns else z_pass
        if isinstance(z_pass, pd.Series):
            survive = df[ic_pass & ir_pass & z_pass]
        else:
            survive = df[ic_pass & ir_pass]
        print(f"\nalphas passing |IC|>0.03 & |IR|>1.5 & |z|<2.0: "
              f"{len(survive)}/{len(df)}")
        # Stricter alternatives.
        for ic_th, ir_th, z_th in ((0.05, 2.0, 2.0), (0.07, 3.0, 2.0),
                                   (0.03, 1.5, 1.5)):
            ic_p = df["ic_mean"].abs() > ic_th
            ir_p = df["ic_ir"].abs() > ir_th
            zp = (df["ic_z"].abs() < z_th).where(df["ic_z"].notna(), True) \
                 if "ic_z" in df.columns else True
            n = (ic_p & ir_p & zp).sum()
            print(f"  |IC|>{ic_th} & |IR|>{ir_th} & |z|<{z_th}: {n}/{len(df)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
