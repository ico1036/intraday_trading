#!/usr/bin/env python3
"""NiceGUI dashboard for archived alpha artifacts.

Pure logic (formatters, IS_PASS gate, drawdown / net-bps / turnover compute,
downsamplers) lives in ``alpha_dashboard_lib`` so it can be unit-tested
without a NiceGUI / Plotly runtime. This module wires those primitives to
file I/O caches, builds Plotly figures, and renders NiceGUI pages.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import subprocess
import sys
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import plotly.graph_objects as go
from nicegui import app, ui

# Allow running both as `python scripts/tools/alpha_dashboard.py` (CLI) and via
# importlib in tests; in the CLI case Python only auto-adds the script's
# directory, so the sibling lib module is reachable as `alpha_dashboard_lib`.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from alpha_dashboard_lib import (  # noqa: E402  (path injection above)
    _downsample_frame as _lib_downsample_frame,
    _duration_days,
    _fmt_bps,
    _fmt_days,
    _fmt_duration_days,
    _fmt_int,
    _fmt_num,
    _fmt_pct,
    _fmt_turnover,
    _is_pass_eligible,
    _missing,
    _series_downsample as _lib_series_downsample,
    classify_alpha,
    compute_drawdown_metrics,
    compute_net_pnl_bps,
    compute_turnover,
    cumret_segment_offsets,
    discover_splits,
    format_uptime,
    forward_status,
    is_forward_live,
    _is_flat_layout,
    read_metrics_for_split,
)


def _load_universe(run_dir: Path) -> list[str]:
    splits = read_json(run_dir / "splits.json") or {}
    syms = splits.get("universe", [])
    return [str(s) for s in syms] if isinstance(syms, list) else []


DEFAULT_RUN_DIR = Path("archive")
# metrics.json stores `sharpe` as the daily-resampled return series multiplied
# by sqrt(252). The dashboard displays raw daily Sharpe everywhere, so we divide
# the stored value by SQRT_252 at every formatting site below.
import math as _math
SQRT_252 = _math.sqrt(252)


def _fmt_sharpe_daily(value: Any) -> str:
    """Display the daily (un-annualized) Sharpe.

    Stored value is annualized = daily_mean/daily_std * sqrt(252); we divide
    back by sqrt(252) before formatting so the dashboard shows raw daily.
    """
    if value is None:
        return "-"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "-"
    if v != v:  # NaN
        return "-"
    return _fmt_num(v / SQRT_252)


def _fmt_sharpe_annual(value: Any) -> str:
    """Display the annualized Sharpe (stored value, as-is)."""
    if value is None:
        return "-"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "-"
    if v != v:  # NaN
        return "-"
    return _fmt_num(v)


def _fmt_sharpe_pair(value: Any) -> str:
    """Combined daily / yearly display: "0.057 / 0.910"."""
    return f"{_fmt_sharpe_daily(value)} / {_fmt_sharpe_annual(value)}"


MAX_LINE_POINTS = 2000
# Members in the composite "hairball" chart are faded grey overlays — full
# 2000-point resolution is wasted there. Drop to 250pt to cut JSON payload
# (16 MB → ~2 MB) and browser render time.
MEMBER_TRACE_POINTS = 250
METRIC_COLUMNS = [
    "run_id",
    "alpha_id",
    "status",
    "category",
    "bar_label",
    "bar_size_sec",
    "is_period_start",
    "is_period_end",
    "is_period_days",
    "os_period_start",
    "os_period_end",
    "os_period_days",
    "generated_at",
    "is_sharpe",
    "is_return",
    "is_max_dd",
    "is_dd_duration",
    "is_pnl_bps",
    "is_trades",
    "os_sharpe",
    "os_return",
    "os_max_dd",
    "os_pnl_bps",
    "os_trades",
    "flags",
]
TABLE_COLUMNS = [
    ("run_id", "run", "left"),
    ("alpha_id", "alpha_id", "left"),
    ("category", "Category", "left"),
    ("bar_label", "Bar", "left"),
    ("backtest_period_fmt", "Backtest Period (start~end, days)", "left"),
    ("generated_at_fmt", "Generated At", "left"),
    ("is_sharpe_fmt", "IS Sharpe (d/y)", "right"),
    ("is_return_fmt", "IS ret", "right"),
    ("is_max_dd_fmt", "IS DD", "right"),
    ("is_pnl_bps_fmt", "IS bps", "right"),
    ("is_trades", "IS tr", "right"),
    ("flags", "flags", "left"),
]
VALIDATION_RULES = {
    "RETURN_COLLAPSE": "IS return > 0, OS return < IS return * return_ratio.",
    "SHARPE_COLLAPSE": "IS Sharpe > 0, OS Sharpe < IS Sharpe * sharpe_ratio.",
    "SHARPE_SIGN_FLIP": "IS Sharpe > 0 and OS Sharpe < 0.",
    "DRAWDOWN_EXPANSION": "abs(OS drawdown) > abs(IS drawdown) * drawdown_ratio.",
    "WIN_RATE_DRIFT": "abs(OS win_rate - IS win_rate) > win_rate_gap.",
    "OS_TRADE_COUNT_TOO_LOW": "OS total_trades < min_os_trades.",
}
DEFAULT_THRESHOLDS = {
    "return_ratio": 0.30,
    "sharpe_ratio": 0.30,
    "drawdown_ratio": 2.0,
    "win_rate_gap": 0.20,
    "min_os_trades": 5,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Alpha archive dashboard")
    parser.add_argument("--run-dir", default=str(DEFAULT_RUN_DIR))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    return parser.parse_args()


@lru_cache(maxsize=1)
def _hangang_temp_cached(epoch_bucket: int) -> tuple[float | None, str]:
    """Fetch Han River water temperature (Celsius).

    Primary: Seoul OpenAPI ``WPOSInformationTime`` sample endpoint
    (수질 자동측정망 ``WATT`` field). The /sample/ route works
    without auth, but the upstream has been timing out for days.

    Fallback: scrape ``hangang.ivlis.kr`` — a Korean hobbyist Han-River
    weather page. The current ``temperature-value`` element renders the
    temp as e.g. ``18.5도``.

    Returns (temp_c, status_msg); ``temp_c`` is None on any failure.
    Cache key is a 5-minute bucket so we hit the API at most every 5 min.
    """
    del epoch_bucket
    import urllib.request

    seoul_url = "http://openapi.seoul.go.kr:8088/sample/json/WPOSInformationTime/1/5/"
    try:
        req = urllib.request.Request(seoul_url, headers={"User-Agent": "jw-capital/1.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
        payload = data.get("WPOSInformationTime") or {}
        rows = payload.get("row") or []
        result = payload.get("RESULT") or {}
        if (not result.get("CODE") or result["CODE"] == "INFO-000") and rows:
            rows.sort(key=lambda r: (r.get("YMD") or "", r.get("HR") or ""), reverse=True)
            for r in rows:
                watt = r.get("WATT")
                if watt in (None, "", "-"):
                    continue
                try:
                    return (float(watt),
                            f"seoul ({r.get('MSRSTN_NM') or 'station'} {r.get('HR') or ''})")
                except (TypeError, ValueError):
                    continue
    except Exception:
        pass  # fall through to ivlis scrape

    fallback_url = "https://hangang.ivlis.kr/"
    try:
        req = urllib.request.Request(fallback_url, headers={"User-Agent": "jw-capital/1.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        return (None, f"api error: {type(exc).__name__}")

    import re
    # Page renders the temp as e.g. "18.5도" inside a temperature-value div.
    m = re.search(r"(\d+(?:\.\d+)?)\s*도", html)
    if m:
        try:
            return (float(m.group(1)), "ivlis")
        except ValueError:
            pass
    return (None, "no temp parsed")


def hangang_temp() -> tuple[float | None, str]:
    bucket = int(datetime.now().timestamp()) // 300
    return _hangang_temp_cached(bucket)


def _current_bar_pnl(forward_dir: Path) -> tuple[float | None, float | None]:
    """(pnl_usd, return_pct) for the *current open bar*.

    Defined as ``NAV_now - NAV_at_last_rebalance``. The last rebalance
    timestamp is the open boundary of the bar the strategy is currently
    holding through, so this answers "how much has equity moved since
    we last touched the book?". Resets each time a new rebalance is
    persisted, which for a daily-candle alpha is once per kline close.

    Returns (None, None) when prior weight events or the equity curve
    don't exist yet — both are written by the runner, so a freshly
    created forward dir simply shows "-" instead of a misleading 0.
    """
    weights_path = forward_dir / "weights.parquet"
    eq_path = forward_dir / "equity_curve.parquet"
    if not weights_path.exists() or not eq_path.exists():
        return (None, None)
    try:
        weights = pd.read_parquet(weights_path, columns=["timestamp"])
        if weights.empty:
            return (None, None)
        last_rebal = pd.to_datetime(weights["timestamp"]).max()
        eq = pd.read_parquet(eq_path, columns=["timestamp", "equity"])
        if eq.empty:
            return (None, None)
        eq["timestamp"] = pd.to_datetime(eq["timestamp"])
        eq = eq.sort_values("timestamp").reset_index(drop=True)
        at_or_after = eq[eq["timestamp"] >= last_rebal]
        if at_or_after.empty:
            return (None, None)
        nav_open = float(at_or_after["equity"].iloc[0])
        nav_now = float(eq["equity"].iloc[-1])
        pnl = nav_now - nav_open
        ret = (nav_now / nav_open - 1.0) if nav_open else None
        return (pnl, ret)
    except Exception:
        return (None, None)


_LOSS_COMFORT_LINES = [
    "오늘은 주인님을 위해 따뜻한 말 한마디를 보태주세요.",
    "Today the books bled red — leave the boss a kind word.",
]


def discover_live_alphas(run_dir: Path) -> list[dict[str, Any]]:
    """Scan run_dir for alphas with a currently-running forward runner.

    Returns one entry per live alpha with its run_id, alpha_id, and the
    full forward_status() snapshot (NAV, session PnL/return, uptime, …).
    """
    found: list[dict[str, Any]] = []
    for forward_dir in run_dir.glob("*/alphas/*/forward"):
        if not is_forward_live(forward_dir):
            continue
        alpha_dir_path = forward_dir.parent
        run_id = alpha_dir_path.parent.parent.name
        alpha_id = alpha_dir_path.name
        found.append({
            "run_id": run_id,
            "alpha_id": alpha_id,
            "status": forward_status(forward_dir),
        })
    return found


def render_top_nav() -> None:
    """Sticky top navigation shown on every page."""
    with ui.header(elevated=False).classes("nav-bar"):
        with ui.row().classes("nav-inner"):
            with ui.link(target="/").classes("nav-brand").style("text-decoration: none;"):
                ui.html('<span class="nav-mark">◆</span>JW Capital', sanitize=False)
            ui.element("div").style("flex: 1")


@lru_cache(maxsize=1)
def _git_short_sha() -> str:
    """Short git SHA for the dashboard's footer build marker."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parents[2],
            stderr=subprocess.DEVNULL,
            timeout=2,
        )
        return out.decode().strip() or "unknown"
    except (subprocess.SubprocessError, OSError):
        return "unknown"


def render_footer(run_dir: Path) -> None:
    """Small footer with run_dir, live count, and git SHA."""
    live_count = 0
    try:
        # Archive layout is run_dir/<run_id>/alphas/<alpha_id>/forward
        for forward_dir in run_dir.glob("*/alphas/*/forward"):
            if is_forward_live(forward_dir):
                live_count += 1
    except Exception:
        pass
    with ui.row().classes("app-footer w-full"):
        ui.label(f"run_dir: {run_dir}")
        ui.label("·").classes("footer-dot")
        ui.label(f"live alphas: {live_count}")
        ui.label("·").classes("footer-dot")
        # Cached at process start — a git pull while the dashboard is running
        # will not refresh this.
        ui.label(f"build (at start): {_git_short_sha()}")


def _threshold_text(thresholds: dict[str, Any]) -> str:
    merged = dict(DEFAULT_THRESHOLDS)
    merged.update(thresholds or {})
    return (
        f"return_ratio={merged['return_ratio']}, "
        f"sharpe_ratio={merged['sharpe_ratio']}, "
        f"drawdown_ratio={merged['drawdown_ratio']}, "
        f"win_rate_gap={merged['win_rate_gap']}, "
        f"min_os_trades={merged['min_os_trades']}"
    )


_INDEX_CACHE: dict[str, tuple[float, pd.DataFrame]] = {}
_INDEX_CACHE_TTL_SEC = 60.0


def _detailed_signature(run_dir: Path) -> list[list]:
    """Per-alpha (run, alpha, metrics.json mtime_ns). Detects any change."""
    if (run_dir / "alphas").exists():
        run_dirs = [run_dir]
    else:
        run_dirs = sorted(
            d for d in run_dir.iterdir()
            if d.is_dir() and d.name != "composites" and (d / "alphas").exists()
        )
    sig: list[list] = []
    for r in run_dirs:
        for ad in sorted((r / "alphas").iterdir()):
            if not ad.is_dir():
                continue
            # Cache key per layout: legacy uses is/metrics.json, flat
            # uses the top-level metrics.json.
            flat_m = ad / "metrics.json"
            legacy_m = ad / "is" / "metrics.json"
            if flat_m.exists() and not (ad / "is").is_dir():
                sig.append([r.name, ad.name, flat_m.stat().st_mtime_ns])
            elif legacy_m.exists():
                sig.append([r.name, ad.name, legacy_m.stat().st_mtime_ns])
    return sig


def _populate_returns(sub_df: pd.DataFrame, run_dir: Path,
                      ret_cols: dict, score: dict) -> None:
    """Fill ret_cols / score in-place from equity_curve.parquet of each
    SUBMITTABLE row. Resample to the same frequency as the bar_size
    so correlations are evaluated bar-for-bar — but downsample at
    most to daily for memory."""
    for _, row in sub_df.iterrows():
        aid = row["alpha_id"]
        run_id = row["run_id"]
        ad = run_dir / run_id / "alphas" / aid
        eq_p = None
        for cand in (
            ad / "forward" / "equity_curve.parquet",
            ad / "equity_curve.parquet",
            ad / "is" / "equity_curve.parquet",
        ):
            if cand.exists():
                eq_p = cand
                break
        if eq_p is None:
            continue
        try:
            eq = pd.read_parquet(eq_p, columns=["timestamp", "equity"])
            eq["timestamp"] = pd.to_datetime(eq["timestamp"])
            eq = eq.set_index("timestamp").sort_index()
            # Daily resample even for sub-day alphas: cap memory and
            # keep correlation comparisons on the most stable axis.
            d = (eq["equity"].resample("1D").last().dropna()
                 .pct_change().dropna())
            if len(d) < 30:
                continue
            ret_cols[aid] = d
            m = read_metrics_for_split(ad, "is") or {}
            score[aid] = abs(float(m.get("ic_ir") or 0))
        except Exception:
            continue


def _apply_corr_dedup_to_index(
    df: pd.DataFrame, run_dir: Path, tau: float = 0.7
) -> pd.DataFrame:
    """Demote SUBMITTABLE clones to NORMAL after pairwise |ρ| dedup.

    Reads each SUBMITTABLE alpha's equity_curve.parquet (forward > flat
    > is), resamples to daily returns, then greedy-dedups in order of
    descending |IC_IR|: the first alpha is kept and any later candidate
    whose max |ρ| with the already-kept set is ≥ τ gets its category
    downgraded to "NORMAL". Original rows are untouched, only the
    category column changes.
    """
    if df is None or df.empty or "category" not in df.columns:
        return df
    sub = df[df["category"] == "SUBMITTABLE"]
    if len(sub) < 2:
        return df

    # Dedup within each bar_size group separately — mixing frequencies in
    # one correlation matrix is meaningless (a 1d daily pct_change and a
    # 1m intra-day pct_change are not comparable). Output: kept alpha ids
    # across all groups; everyone else gets demoted.
    if "bar_size_sec" in sub.columns:
        kept_ids: set[str] = set()
        groups = sub.groupby(sub["bar_size_sec"].fillna(-1.0))
        out = df.copy()
        for bs, grp in groups:
            sub_grp = grp
            ret_cols: dict[str, pd.Series] = {}
            score: dict[str, float] = {}
            _populate_returns(sub_grp, run_dir, ret_cols, score)
            if len(ret_cols) < 2:
                kept_ids.update(grp["alpha_id"].tolist())
                continue
            ret_panel = pd.DataFrame(ret_cols)
            ordered = sorted(score.items(), key=lambda kv: -kv[1])
            cands = [(aid, {}) for aid, _ in ordered]
            from alpha_dashboard_lib import apply_correlation_gate as _gate
            kept = set(_gate(cands, ret_panel, tau=tau))
            kept_ids.update(kept)
            no_eq = set(grp["alpha_id"]) - set(ret_cols.keys())
            kept_ids.update(no_eq)  # alphas with no equity curve stay SUBMITTABLE
        mask = (out["category"] == "SUBMITTABLE") & ~out["alpha_id"].isin(kept_ids)
        out.loc[mask, "category"] = "NORMAL"
        return out

    # Fallback (no bar_size column): single global dedup.
    ret_cols = {}
    score = {}
    for _, row in sub.iterrows():
        aid = row["alpha_id"]
        run_id = row["run_id"]
        ad = run_dir / run_id / "alphas" / aid
        eq_p = None
        for cand in (
            ad / "forward" / "equity_curve.parquet",
            ad / "equity_curve.parquet",
            ad / "is" / "equity_curve.parquet",
        ):
            if cand.exists():
                eq_p = cand
                break
        if eq_p is None:
            continue
        try:
            eq = pd.read_parquet(eq_p, columns=["timestamp", "equity"])
            eq["timestamp"] = pd.to_datetime(eq["timestamp"])
            eq = eq.set_index("timestamp").sort_index()
            d = (eq["equity"].resample("1D").last().dropna()
                 .pct_change().dropna())
            if len(d) < 30:
                continue
            ret_cols[aid] = d
            m = read_metrics_for_split(ad, "is") or {}
            score[aid] = abs(float(m.get("ic_ir") or 0))
        except Exception:
            continue

    if len(ret_cols) < 2:
        return df

    ret_panel = pd.DataFrame(ret_cols)
    ordered = sorted(score.items(), key=lambda kv: -kv[1])
    cands = [(aid, {}) for aid, _ in ordered]
    from alpha_dashboard_lib import apply_correlation_gate as _gate
    kept = set(_gate(cands, ret_panel, tau=tau))

    # Demote everyone in sub but not in kept; leave alphas with no equity
    # curve as SUBMITTABLE because we cannot judge them.
    out = df.copy()
    mask = (out["category"] == "SUBMITTABLE") & out["alpha_id"].isin(ret_cols)
    demote = mask & ~out["alpha_id"].isin(kept)
    out.loc[demote, "category"] = "NORMAL"
    return out


def _persistent_cache_paths(run_dir: Path) -> tuple[Path, Path]:
    import hashlib
    h = hashlib.md5(str(run_dir.resolve()).encode()).hexdigest()[:8]
    base = Path("/tmp") / f"alpha_dashboard_index_{h}"
    return base.with_suffix(".parquet"), base.with_suffix(".sig.json")


def load_index(run_dir: Path) -> pd.DataFrame:
    """Build the alpha index by scanning the archive on disk.

    The per-run alpha_index.csv files were observed to drift from disk truth
    (alphas appended LOG.md/index step skipped for some attempts). Rebuilding
    in-memory from each alpha's metrics.json + splits.json gives exact counts
    and a uniform IS_PASS/IS_FAIL label across runs whether or not OS exists.

    Cached for ``_INDEX_CACHE_TTL_SEC`` seconds keyed by a directory signature
    that captures alpha-count changes, so rebuilds happen automatically when
    new alphas land but the dashboard isn't slow on every page navigation.
    """
    import time as _time
    sig = _detailed_signature(run_dir)
    key = (str(run_dir), len(sig), sig[0] if sig else None, sig[-1] if sig else None)
    cached = _INDEX_CACHE.get(str(key))
    now = _time.time()
    if cached is not None and (now - cached[0]) < _INDEX_CACHE_TTL_SEC:
        return cached[1].copy()

    # Persistent disk cache: skip the 30s+ rebuild when no alpha's metrics.json
    # has changed since the last successful build.
    cache_pq, cache_sig = _persistent_cache_paths(run_dir)
    if cache_pq.exists() and cache_sig.exists():
        try:
            saved = json.loads(cache_sig.read_text())
            if saved == sig:
                df = pd.read_parquet(cache_pq)
                _INDEX_CACHE[str(key)] = (now, df.copy())
                return df
        except Exception:
            pass
    if (run_dir / "alphas").exists():
        run_dirs = [run_dir]
    else:
        run_dirs = sorted(
            d for d in run_dir.iterdir()
            if d.is_dir() and d.name != "composites" and (d / "alphas").exists()
        )
    rows: list[dict[str, Any]] = []
    for r in run_dirs:
        splits = read_json(r / "splits.json")
        target_threshold = float((splits.get("target") or {}).get("threshold", 0.6))
        qg = splits.get("quality_gates") or {}
        min_trades = float(qg.get("min_trades", 0))
        min_turnover = float(qg.get("min_turnover", 0))
        for alpha_d in sorted((r / "alphas").iterdir()):
            if not alpha_d.is_dir():
                continue
            # Skip alphas whose IS metrics is missing — they were either
            # deleted by quality_gate enforcement or never finished. Showing
            # them as half-empty rows is misleading. Supports both legacy
            # (alpha_d/is/metrics.json) and flat (alpha_d/metrics.json with
            # "is"/"os" sub-blocks) layouts.
            is_m = read_metrics_for_split(alpha_d, "is")
            if not is_m:
                continue
            os_m = read_metrics_for_split(alpha_d, "os") or {}

            is_turnover = turnover_from_weights(r, alpha_d.name, "is")
            os_turnover = turnover_from_weights(r, alpha_d.name, "os")

            sharpe = is_m.get("sharpe") if is_m else None
            trades = is_m.get("total_trades") if is_m else None
            is_pass = _is_pass_eligible(
                sharpe,
                trades,
                is_turnover,
                sharpe_threshold=target_threshold,
                min_trades=min_trades,
                min_turnover=min_turnover,
            )

            v = read_json(alpha_d / "validation.json")
            flags = ",".join(v.get("flags", []) or []) if v else ""

            # Backtest period (start, end, days) per split, taken from splits.json
            is_split = (splits.get("is") or {}) if isinstance(splits, dict) else {}
            os_split = (splits.get("os") or {}) if isinstance(splits, dict) else {}
            is_period_start = is_split.get("start")
            is_period_end = is_split.get("end")
            os_period_start = os_split.get("start")
            os_period_end = os_split.get("end")
            is_period_days = _duration_days(is_period_start, is_period_end)
            os_period_days = _duration_days(os_period_start, os_period_end)

            # Alpha generation timestamp from manifest.json (prefer IS, fall back OS)
            is_manifest = read_json(alpha_d / "is" / "manifest.json")
            os_manifest = read_json(alpha_d / "os" / "manifest.json")
            generated_at = (
                (is_manifest or {}).get("generated_at")
                or (os_manifest or {}).get("generated_at")
            )

            # bar_size (seconds) for frequency segmentation. The dashboard
            # treats different bar_size groups as independent pools because
            # daily PnL stitching across mixed frequencies is meaningless
            # (and correlation dedup must stay within a group).
            bar_size_sec = None
            for path in (
                alpha_d / "summary.json",
                alpha_d / "is" / "summary.json",
                alpha_d / "forward" / "summary.json",
            ):
                try:
                    val = read_json(path).get("bar_size") if path.exists() else None
                except Exception:
                    val = None
                if val is not None:
                    try:
                        bar_size_sec = float(val)
                        break
                    except (TypeError, ValueError):
                        continue
            if bar_size_sec is not None:
                if bar_size_sec >= 86400 * 0.9:
                    bar_label = "1d"
                elif bar_size_sec >= 3600 * 0.9:
                    bar_label = f"{int(round(bar_size_sec/3600))}h"
                elif bar_size_sec >= 60 * 0.9:
                    bar_label = f"{int(round(bar_size_sec/60))}m"
                else:
                    bar_label = f"{int(bar_size_sec)}s"
            else:
                bar_label = "?"

            # All trade-level stats are persisted into metrics.json at backtest
            # write time (see scripts/tools/backtest.py:_persist_display_metrics)
            # so the dashboard is purely read-only.
            is_dd = is_m.get("max_drawdown") if is_m else None
            is_dd_dur = None
            is_bps_simple = is_m.get("pnl_bps_simple") if is_m else None
            is_bps_w = is_m.get("pnl_bps_notional_weighted") if is_m else None
            os_bps_simple = os_m.get("pnl_bps_simple") if os_m else None
            os_bps_w = os_m.get("pnl_bps_notional_weighted") if os_m else None
            os_dd = os_m.get("max_drawdown") if os_m else None
            os_dd_dur = None

            # Extended trade-level metrics (Tier 1+2). Same field for IS and OS.
            def _g(m, k):
                return m.get(k) if m else None
            extra = {
                "is_t_stat": _g(is_m, "t_stat"),
                "is_per_trade_sharpe": _g(is_m, "per_trade_sharpe"),
                "is_calmar": _g(is_m, "calmar"),
                "is_win_rate_trades": _g(is_m, "trade_win_rate"),
                "is_avg_win_bps": _g(is_m, "avg_win_bps"),
                "is_avg_loss_bps": _g(is_m, "avg_loss_bps"),
                "is_win_loss_ratio": _g(is_m, "win_loss_ratio"),
                "is_profit_factor_trades": _g(is_m, "profit_factor_trades"),
                "is_largest_win_bps": _g(is_m, "largest_win_bps"),
                "is_largest_loss_bps": _g(is_m, "largest_loss_bps"),
                "is_round_trips": _g(is_m, "round_trips"),
                "os_t_stat": _g(os_m, "t_stat"),
                "os_per_trade_sharpe": _g(os_m, "per_trade_sharpe"),
                "os_calmar": _g(os_m, "calmar"),
                "os_win_rate_trades": _g(os_m, "trade_win_rate"),
                "os_avg_win_bps": _g(os_m, "avg_win_bps"),
                "os_avg_loss_bps": _g(os_m, "avg_loss_bps"),
                "os_win_loss_ratio": _g(os_m, "win_loss_ratio"),
                "os_profit_factor_trades": _g(os_m, "profit_factor_trades"),
                "os_largest_win_bps": _g(os_m, "largest_win_bps"),
                "os_largest_loss_bps": _g(os_m, "largest_loss_bps"),
                "os_round_trips": _g(os_m, "round_trips"),
            }

            rows.append(
                {
                    "run_id": r.name,
                    "_run_dir": str(r),
                    "alpha_id": alpha_d.name,
                    "status": "IS_PASS" if is_pass else "IS_FAIL",
                    "is_sharpe": sharpe,
                    "is_return": is_m.get("total_return") if is_m else None,
                    "is_trades": trades,
                    "is_turnover": is_turnover,
                    "is_max_dd": is_dd,
                    "is_dd_duration": is_dd_dur,
                    "is_pnl_bps": is_bps_simple,
                    "is_pnl_bps_w": is_bps_w,
                    "os_sharpe": os_m.get("sharpe") if os_m else None,
                    "os_return": os_m.get("total_return") if os_m else None,
                    "os_trades": os_m.get("total_trades") if os_m else None,
                    "os_turnover": os_turnover,
                    "os_max_dd": os_dd,
                    "os_dd_duration": os_dd_dur,
                    "os_pnl_bps": os_bps_simple,
                    "os_pnl_bps_w": os_bps_w,
                    "has_os": bool(os_m),
                    "flags": flags,
                    "th_sharpe": target_threshold,
                    "th_trades": min_trades,
                    "th_turnover": min_turnover,
                    "is_period_start": is_period_start,
                    "is_period_end": is_period_end,
                    "is_period_days": is_period_days,
                    "os_period_start": os_period_start,
                    "os_period_end": os_period_end,
                    "os_period_days": os_period_days,
                    "generated_at": generated_at,
                    # Prefer forward/metrics.json for classification because it
                    # carries the IC fields populated by the unified
                    # backtest+slice pipeline. Fall back to IS metrics for
                    # alphas that don't have a forward run yet.
                    "bar_size_sec": bar_size_sec,
                    "bar_label": bar_label,
                    "category": classify_alpha(
                        (read_metrics_for_split(alpha_d, "forward") or is_m),
                        os_m,
                    )[0],
                    **extra,
                }
            )
    if not rows:
        result = pd.DataFrame(
            columns=["run_id", "alpha_id", "status", "is_sharpe", "is_return", "is_trades", "os_sharpe", "os_return", "os_trades", "flags"]
        )
    else:
        result = pd.DataFrame(rows)

    # Population-level correlation gate: keep an alpha as SUBMITTABLE only
    # if its daily equity returns correlate < τ with everything already
    # in the pool. τ = 0.7 collapses near-duplicate strategies that share
    # the same factor and only differ in concentration or direction.
    result = _apply_corr_dedup_to_index(result, run_dir, tau=0.7)

    _INDEX_CACHE[str(key)] = (now, result.copy())
    try:
        result.to_parquet(cache_pq, index=False)
        cache_sig.write_text(json.dumps(sig))
    except Exception:
        pass  # cache is opportunistic, skip on write failure
    return result


def load_splits(run_dir: Path) -> dict[str, Any]:
    return read_json(run_dir / "splits.json")


def alpha_dir(run_dir: Path, alpha_id: str) -> Path:
    return run_dir / "alphas" / alpha_id


def row_run_dir(row: dict[str, Any], default_run_dir: Path) -> Path:
    return Path(str(row.get("_run_dir") or default_run_dir))


@lru_cache(maxsize=2048)
def read_json_cached(path_text: str) -> dict[str, Any]:
    path = Path(path_text)
    return json.loads(path.read_text()) if path.exists() else {}


def read_json(path: Path) -> dict[str, Any]:
    return read_json_cached(str(path))


# Cap the raw-parquet cache to 32 entries — large equity_curve.parquet files
# (~10 MB each, 453K rows) blow this cache up to multi-GB if uncapped. Charts
# now use derived caches (downsampled cumret/drawdown) so we don't need the
# full df cached past the next render.
@lru_cache(maxsize=32)
def read_parquet_cached(path_text: str) -> pd.DataFrame:
    path = Path(path_text)
    return pd.read_parquet(path) if path.exists() else pd.DataFrame()


def read_parquet(path: Path) -> pd.DataFrame:
    return read_parquet_cached(str(path))


@lru_cache(maxsize=4096)
def _equity_chart_series_cached(
    equity_path: str, max_points: int = MAX_LINE_POINTS
) -> pd.DataFrame:
    """Downsampled ``(timestamp, cumret, cumret_simple, drawdown)`` for chart rendering.

    ``cumret`` is the compound form ``C_t/C_0 - 1``; ``cumret_simple`` is the
    additive form ``Σ_t r_t`` with ``r_t = ΔC/C``. The simple version is
    approximately ``ln(C_t/C_0)`` for small per-bar returns and lets the user
    flip between the two on charts without re-reading equity_curve.parquet.
    Returns ~max_points rows so 487 alphas × ~32 KB each ≈ 15 MB cap.
    """
    p = Path(equity_path)
    if not p.exists():
        return pd.DataFrame(columns=["timestamp", "cumret", "cumret_simple", "drawdown"])
    df = pd.read_parquet(p, columns=["timestamp", "equity"])
    if df.empty:
        return pd.DataFrame(columns=["timestamp", "cumret", "cumret_simple", "drawdown"])
    df = _lib_downsample_frame(df, max_points=max_points)
    eq = df["equity"].astype(float)
    base = float(eq.iloc[0]) if eq.iloc[0] != 0 else 1.0
    return pd.DataFrame(
        {
            "timestamp": df["timestamp"].values,
            "cumret": (eq / base - 1.0).values,
            "cumret_simple": eq.pct_change().fillna(0.0).cumsum().values,
            "drawdown": (eq / eq.cummax() - 1.0).values,
        }
    )


def _x(values: pd.Series) -> list[str]:
    return pd.to_datetime(values).astype(str).tolist()


def _downsample_frame(df: pd.DataFrame, max_points: int = MAX_LINE_POINTS) -> pd.DataFrame:
    return _lib_downsample_frame(df, max_points=max_points)


def equity_figure(run_dir: Path, alpha_id: str, mode: str = "compound") -> go.Figure:
    """Per-alpha cumret chart with IS/OS/Forward stitched into one
    continuous NAV curve (each segment offset by the prior segment's
    final cumret)."""
    column = "cumret_simple" if mode == "simple" else "cumret"
    label = "Simple (additive)" if mode == "simple" else "Compound"
    fig = go.Figure()
    segments: dict[str, pd.DataFrame] = {}
    for split in ("is", "os", "forward"):
        df = _equity_chart_series_cached(
            str(alpha_dir(run_dir, alpha_id) / split / "equity_curve.parquet")
        )
        if not df.empty and column in df.columns:
            segments[split] = df
    is_final = float(segments["is"][column].iloc[-1]) if "is" in segments else None
    os_final = float(segments["os"][column].iloc[-1]) if "os" in segments else None
    offsets = cumret_segment_offsets(is_final, os_final)

    palette = {"is": "#2563eb", "os": "#dc2626", "forward": "#16a34a"}
    boundaries: list = []
    for split, df in segments.items():
        y = df[column] + offsets[split]
        fig.add_trace(
            go.Scatter(
                x=_x(df["timestamp"]),
                y=y,
                mode="lines",
                name=split.upper(),
                line={"color": palette[split], "width": 1.5},
                hovertemplate="%{x}<br>%{y:.2%}<extra>%{fullData.name}</extra>",
            )
        )
        if split in ("os", "forward"):
            boundaries.append((str(df["timestamp"].iloc[0]), palette[split]))
    for ts, color in boundaries:
        fig.add_vline(x=ts, line_width=0.8, line_dash="dot",
                      line_color=color, opacity=0.4)
    fig.update_layout(
        height=340,
        autosize=True,
        # Bottom-anchored legend keeps it off the title row above.
        margin=dict(l=40, r=15, t=40, b=60),
        title=f"Net cumulative return (after fees) — {label} (stitched)",
        legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5),
    )
    fig.update_yaxes(tickformat=".1%")
    return fig


def forward_session_figure(run_dir: Path, alpha_id: str) -> go.Figure:
    """Forward (live) cumret only — starts at 0% on the first forward bar.

    Distinct from ``equity_figure`` which stitches IS+OS+forward into one
    continuous curve. Used inside the Live Session panel so the user can
    judge live performance independently of backtest history.
    """
    df = _equity_chart_series_cached(
        str(alpha_dir(run_dir, alpha_id) / "forward" / "equity_curve.parquet")
    )
    fig = go.Figure()
    if not df.empty and "cumret" in df.columns:
        # Rebase so the first forward bar shows 0% rather than wherever the
        # forward runner inherited the prior NAV from.
        cumret = df["cumret"] - df["cumret"].iloc[0]
        fig.add_trace(
            go.Scatter(
                x=_x(df["timestamp"]),
                y=cumret,
                mode="lines",
                line={"color": "#16a34a", "width": 1.8},
                name="Live session",
                hovertemplate="%{x}<br>%{y:.2%}<extra></extra>",
            )
        )
    fig.update_layout(
        height=240,
        autosize=True,
        margin=dict(l=40, r=15, t=40, b=30),
        title="Live session PnL (post-OS only)",
        showlegend=False,
    )
    fig.update_yaxes(tickformat=".2%")
    fig.add_hline(y=0, line_dash="dash", line_width=1, line_color="#94a3b8")
    return fig


def drawdown_figure(run_dir: Path, alpha_id: str) -> go.Figure:
    fig = go.Figure()
    for split, color in (("is", "#2563eb"), ("os", "#dc2626"), ("forward", "#16a34a")):
        df = _equity_chart_series_cached(
            str(alpha_dir(run_dir, alpha_id) / split / "equity_curve.parquet")
        )
        if df.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=_x(df["timestamp"]),
                y=df["drawdown"],
                mode="lines",
                name=split.upper(),
                line={"color": color, "width": 1.5},
            )
        )
    fig.update_layout(
        height=300,
        autosize=True,
        margin=dict(l=40, r=15, t=40, b=60),
        title="Drawdown",
        legend=dict(orientation="h", yanchor="top", y=-0.20, xanchor="center", x=0.5),
    )
    fig.update_yaxes(tickformat=".1%")
    return fig


@lru_cache(maxsize=256)
def _weight_pivot_cached(weights_path: str) -> pd.DataFrame:
    p = Path(weights_path)
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    if df.empty:
        return pd.DataFrame()
    pivot = (
        df.sort_values("timestamp")
        .pivot_table(
            index="timestamp",
            columns="symbol",
            values="target_weight",
            aggfunc="last",
        )
        .sort_index()
    )
    return pivot.ffill().fillna(0.0)


def _weight_pivot(run_dir: Path, alpha_id: str, split: str) -> pd.DataFrame:
    return _weight_pivot_cached(str(alpha_dir(run_dir, alpha_id) / split / "weights.parquet"))


def turnover_from_weights(run_dir: Path, alpha_id: str, split: str) -> float | None:
    return compute_turnover(_weight_pivot(run_dir, alpha_id, split))


@lru_cache(maxsize=2048)
def _net_trade_metrics_cached(trades_path: str) -> tuple[float | None, float | None, int]:
    p = Path(trades_path)
    if not p.exists():
        return (None, None, 0)
    return compute_net_pnl_bps(pd.read_parquet(p))


def net_pnl_per_trade_bps(run_dir: Path, alpha_id: str, split: str) -> tuple[float | None, float | None, int]:
    return _net_trade_metrics_cached(str(alpha_dir(run_dir, alpha_id) / split / "trades.parquet"))


@lru_cache(maxsize=2048)
def _drawdown_metrics_cached(equity_path: str) -> tuple[float | None, float | None, str | None, str | None]:
    p = Path(equity_path)
    if not p.exists():
        return (None, None, None, None)
    df = pd.read_parquet(p)
    if df.empty:
        return (None, None, None, None)
    eq = df.set_index(pd.to_datetime(df["timestamp"]))["equity"].astype(float)
    eq = eq[~eq.index.duplicated(keep="last")].sort_index()
    return compute_drawdown_metrics(eq)


def drawdown_metrics(run_dir: Path, alpha_id: str, split: str) -> tuple[float | None, float | None, str | None, str | None]:
    return _drawdown_metrics_cached(str(alpha_dir(run_dir, alpha_id) / split / "equity_curve.parquet"))


@lru_cache(maxsize=64)
def _hourly_weight_stack_figure_cached(run_dir_s: str, alpha_id: str, split: str) -> go.Figure:
    return _hourly_weight_stack_figure_build(Path(run_dir_s), alpha_id, split)


def hourly_weight_stack_figure(run_dir: Path, alpha_id: str, split: str = "os") -> go.Figure:
    return _hourly_weight_stack_figure_cached(str(run_dir), alpha_id, split)


def _hourly_weight_stack_figure_build(run_dir: Path, alpha_id: str, split: str = "os") -> go.Figure:
    fig = go.Figure()
    pivot = _weight_pivot(run_dir, alpha_id, split)
    if not pivot.empty:
        equity = read_parquet(alpha_dir(run_dir, alpha_id) / split / "equity_curve.parquet")
        if not equity.empty:
            start = pd.to_datetime(equity["timestamp"]).min()
            end = pd.to_datetime(equity["timestamp"]).max()
            # Direct hourly reindex with ffill — earlier impl expanded to a
            # 1-minute grid first (525k rows × 260 cols for a 1y IS span) then
            # resampled back down. For daily-candle weights that's wasted work;
            # ffill onto an hourly grid is visually identical and ~60x cheaper.
            hourly_index = pd.date_range(start=start, end=end, freq="1h")
            hourly = pivot.reindex(hourly_index, method="ffill").fillna(0.0)
        else:
            hourly = pivot.resample("1h").mean().ffill().fillna(0.0)
        abs_hourly = hourly.abs()
        for symbol in abs_hourly.columns:
            fig.add_trace(
                go.Scatter(
                    x=_x(pd.Series(abs_hourly.index)),
                    y=abs_hourly[symbol],
                    mode="lines",
                    name=symbol,
                    stackgroup="weights",
                    hovertemplate=(
                        "%{x}<br>abs weight=%{y:.1%}<extra>" + symbol + "</extra>"
                    ),
                )
            )
    # With hundreds of symbols an inline legend is useless and crowds the
    # plot — keep the traces (still hoverable for individual lookup) but
    # hide the legend.
    fig.update_layout(
        height=320,
        autosize=True,
        margin=dict(l=40, r=15, t=40, b=30),
        title=f"{split.upper()} Hourly Weight Distribution",
        showlegend=False,
    )
    fig.update_yaxes(tickformat=".0%")
    return fig


@lru_cache(maxsize=64)
def _weights_figure_cached(run_dir_s: str, alpha_id: str, split: str) -> go.Figure:
    return _weights_figure_build(Path(run_dir_s), alpha_id, split)


def weights_figure(run_dir: Path, alpha_id: str, split: str = "os") -> go.Figure:
    return _weights_figure_cached(str(run_dir), alpha_id, split)


def _weights_figure_build(run_dir: Path, alpha_id: str, split: str = "os") -> go.Figure:
    df = read_parquet(alpha_dir(run_dir, alpha_id) / split / "weights.parquet")
    fig = go.Figure()
    if not df.empty:
        pivot = (
            df.pivot_table(
                index="symbol",
                columns="timestamp",
                values="target_weight",
                aggfunc="last",
            )
            .sort_index()
            .fillna(0.0)
        )
        fig.add_trace(
            go.Heatmap(
                x=[str(value) for value in pivot.columns],
                y=list(pivot.index),
                z=pivot.values,
                colorscale="RdBu",
                zmid=0,
                colorbar=dict(title="weight"),
            )
        )
    fig.update_layout(
        height=420,
        autosize=True,
        margin=dict(l=80, r=15, t=40, b=30),
        title=f"{split.upper()} Target Weights",
    )
    return fig


def _tone_from_number(value: Any) -> str | None:
    """Map a numeric value to a tone class ('positive'/'negative')."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN
        return None
    if v > 0:
        return "positive"
    if v < 0:
        return "negative"
    return None


def metric_card(label: str, value: str, *, tone: str | None = None):
    """Render a metric card. ``tone`` colors the value:
    'positive' → green, 'negative' → red, 'muted' → gray."""
    with ui.card().classes("metric-card"):
        ui.label(label).classes("metric-label")
        value_cls = "metric-value"
        if tone in ("positive", "negative", "muted"):
            value_cls += f" metric-value-{tone}"
        ui.label(value).classes(value_cls)


def artifact_path(run_dir: Path, alpha_id: str) -> str:
    return str(alpha_dir(run_dir, alpha_id))


def validation_rules_card(thresholds: dict[str, Any] | None = None) -> None:
    with ui.card().classes("dense-panel grow"):
        ui.label("Validation warning rules").classes("section-title")
        with ui.row().classes("w-full gap-2"):
            ui.badge("PASS = no rule fired", color="green")
            ui.badge("WARNING = one or more rules fired", color="orange")
            ui.badge("not a profitability label", color="grey")
        ui.label(_threshold_text(thresholds or {})).classes("path-text")
        rows = [{"flag": flag, "rule": rule} for flag, rule in VALIDATION_RULES.items()]
        ui.table(
            columns=[
                {"name": "flag", "label": "flag", "field": "flag", "align": "left"},
                {"name": "rule", "label": "trigger", "field": "rule", "align": "left"},
            ],
            rows=rows,
            row_key="flag",
            pagination=0,
        ).classes("w-full validation-table")


def split_cards(splits: dict[str, Any]) -> None:
    if not splits:
        return
    for name in ("warmup", "is", "os"):
        split = splits.get(name, {})
        start = split.get("start", "?")
        end = split.get("end", "?")
        days = _duration_days(start, end)
        metric_card(f"{name.upper()} period", f"{_fmt_days(days)}")
    is_days = _duration_days(splits.get("is", {}).get("start"), splits.get("is", {}).get("end")) or 0
    os_days = _duration_days(splits.get("os", {}).get("start"), splits.get("os", {}).get("end")) or 0
    label = "SCOUT" if is_days < 30 or os_days < 7 else "RESEARCH"
    metric_card("Run type", label)


def field_contract_card() -> None:
    with ui.card().classes("dense-panel grow"):
        ui.label("Field contract").classes("section-title")
        with ui.grid(columns=2).classes("w-full gap-2"):
            with ui.card().classes("mini-card"):
                ui.label("status").classes("metric-label")
                ui.label(
                    "IS_PASS = meets run's IS gates "
                    "(Sharpe ≥ threshold, min_trades, min_turnover from splits.json)"
                ).classes("mini-value")
            with ui.card().classes("mini-card"):
                ui.label("return").classes("metric-label")
                ui.label("split total return, not CAGR").classes("mini-value")
            with ui.card().classes("mini-card"):
                ui.label("flags").classes("metric-label")
                ui.label(
                    "OS-vs-IS validation flags from validation.json (only set on runs with OS data)"
                ).classes("mini-value")
            with ui.card().classes("mini-card"):
                ui.label("source").classes("metric-label")
                ui.label(
                    "rebuilt live from each alpha's metrics.json — alpha_index.csv ignored"
                ).classes("mini-value")


_CSS_PATH = Path(__file__).resolve().parent / "alpha_dashboard.css"


@lru_cache(maxsize=1)
def _stylesheet() -> str:
    return _CSS_PATH.read_text(encoding="utf-8")


def add_styles() -> None:
    """Inject viewport meta + stylesheet into the page head.

    The stylesheet lives in ``alpha_dashboard.css`` alongside this module.
    Tokens originate from the open-design "coinbase" system.
    """
    ui.add_head_html(
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        f"<style>{_stylesheet()}</style>"
    )


def _fmt_period_days(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{int(value)}"
    except (TypeError, ValueError):
        return "-"


def _fmt_period_range(start: Any, end: Any, days: Any) -> str:
    """Format a backtest split as 'YYYY-MM-DD ~ YYYY-MM-DD (Nd)'."""
    if start is None or end is None:
        return "-"
    s = str(start)[:10]
    e = str(end)[:10]
    try:
        d_int = int(days) if days is not None else None
    except (TypeError, ValueError):
        d_int = None
    suffix = f" ({d_int}d)" if d_int is not None else ""
    return f"{s} ~ {e}{suffix}"


def _fmt_generated_at(value: Any) -> str:
    """Render manifest.generated_at as a short YYYY-MM-DD HH:MM."""
    if value is None or value == "":
        return "-"
    try:
        dt = datetime.fromisoformat(str(value))
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(value)[:16]


def display_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    cols = [col for col in METRIC_COLUMNS if col in df.columns]
    for raw in df[cols].to_dict("records"):
        row = dict(raw)
        row["os_return_fmt"] = _fmt_pct(raw.get("os_return"))
        row["is_return_fmt"] = _fmt_pct(raw.get("is_return"))
        row["os_sharpe_fmt"] = _fmt_sharpe_pair(raw.get("os_sharpe"))
        row["is_sharpe_fmt"] = _fmt_sharpe_pair(raw.get("is_sharpe"))
        row["os_trades"] = _fmt_int(raw.get("os_trades"))
        row["is_trades"] = _fmt_int(raw.get("is_trades"))
        row["is_max_dd_fmt"] = _fmt_pct(raw.get("is_max_dd"))
        row["os_max_dd_fmt"] = _fmt_pct(raw.get("os_max_dd"))
        row["is_pnl_bps_fmt"] = _fmt_bps(raw.get("is_pnl_bps"))
        row["os_pnl_bps_fmt"] = _fmt_bps(raw.get("os_pnl_bps"))
        row["is_period_days_fmt"] = _fmt_period_days(raw.get("is_period_days"))
        row["os_period_days_fmt"] = _fmt_period_days(raw.get("os_period_days"))
        # Combined backtest period spans IS_start through OS_end (or IS_end if no OS)
        bt_start = raw.get("is_period_start")
        bt_end = raw.get("os_period_end") or raw.get("is_period_end")
        bt_days_is = raw.get("is_period_days") or 0
        bt_days_os = raw.get("os_period_days") or 0
        bt_days_total = (bt_days_is + bt_days_os) if (bt_days_is or bt_days_os) else None
        row["backtest_period_fmt"] = _fmt_period_range(bt_start, bt_end, bt_days_total)
        row["generated_at_fmt"] = _fmt_generated_at(raw.get("generated_at"))
        rows.append(row)
    return rows


def load_alpha_params(run_dir: Path, alpha_id: str) -> dict[str, Any]:
    queue = read_json(run_dir / "queue.json")
    for variant in queue.get("variants", []):
        if variant.get("alpha_id") == alpha_id:
            return variant.get("params", {})
    return {}


def build_search_text(run_dir: Path, df: pd.DataFrame) -> pd.Series:
    values = []
    for row in df.to_dict("records"):
        alpha_id = str(row.get("alpha_id", ""))
        row_dir = row_run_dir(row, run_dir)
        params = load_alpha_params(row_dir, alpha_id)
        values.append(
            " ".join(
                [
                    str(row.get("run_id", "")),
                    alpha_id,
                    str(row.get("status", "")),
                    str(row.get("flags", "")),
                    json.dumps(params, sort_keys=True),
                ]
            ).lower()
        )
    return pd.Series(values, index=df.index)


COMPOSITE_MEMBER_LINE_COLOR = "rgba(120, 120, 120, 0.18)"
COMPOSITE_MEMBER_OS_LINE_COLOR = "rgba(220, 38, 38, 0.18)"
COMPOSITE_BOLD_COLOR = "#1f3a8a"
COMPOSITE_OS_BOLD_COLOR = "#dc2626"


def discover_composites(archive_root: Path) -> list[dict[str, Any]]:
    composites_root = archive_root / "composites"
    out: list[dict[str, Any]] = []
    if not composites_root.exists():
        return out
    for d in sorted(composites_root.iterdir()):
        if not d.is_dir():
            continue
        manifest_path = d / "manifest.json"
        if not manifest_path.exists():
            continue
        manifest = read_json(manifest_path)
        is_metrics = read_json(d / "is" / "metrics.json")
        os_metrics = read_json(d / "os" / "metrics.json") if (d / "os" / "metrics.json").exists() else {}
        out.append(
            {
                "composite_id": manifest.get("composite_id", d.name),
                "dir_name": d.name,
                "dir": str(d),
                "method": manifest.get("method", ""),
                "n_members": manifest.get("n_members", 0),
                "n_change_events": manifest.get("n_change_events", 0),
                "max_row_l1": manifest.get("max_row_l1"),
                "mean_row_l1": manifest.get("mean_row_l1"),
                "is_window": manifest.get("is_window", {}),
                "is_sharpe": is_metrics.get("sharpe"),
                "is_return": is_metrics.get("total_return"),
                "is_drawdown": is_metrics.get("max_drawdown"),
                "is_trades": is_metrics.get("total_trades"),
                "is_win_rate": is_metrics.get("win_rate"),
                "os_sharpe": os_metrics.get("sharpe"),
                "os_return": os_metrics.get("total_return"),
                "os_drawdown": os_metrics.get("max_drawdown"),
                "os_trades": os_metrics.get("total_trades"),
                "selection_warning": manifest.get("selection_bias_warning"),
            }
        )
    return out


def _series_downsample(s: pd.Series, max_points: int = MAX_LINE_POINTS) -> pd.Series:
    return _lib_series_downsample(s, max_points=max_points)


def _active_trim_equity(equity_series: pd.Series) -> pd.Series:
    """Slice equity from the first bar where it diverged from initial capital.

    Composite warmup periods (no positions yet) sit at flat 10000.00 → return
    0%, which dilutes the cumret chart and Sharpe. Trimming starts the chart
    and recomputed metrics from the first realised PnL bar.
    """
    if equity_series.empty:
        return equity_series
    initial = equity_series.iloc[0]
    diverged = equity_series.ne(initial)
    if not diverged.any():
        return equity_series
    first_active = diverged.idxmax()
    return equity_series.loc[first_active:]


def _load_active_equity(equity_path: str) -> pd.Series:
    """Read equity_curve.parquet, downsample, and trim to active period."""
    p = Path(equity_path)
    if not p.exists():
        return pd.Series(dtype=float)
    df = pd.read_parquet(p)
    if df.empty:
        return pd.Series(dtype=float)
    n = len(df)
    if n > MAX_LINE_POINTS:
        stride = max(1, n // MAX_LINE_POINTS)
        df = df.iloc[::stride]
    s = df.set_index("timestamp")["equity"].astype(float)
    s.index = pd.to_datetime(s.index)
    return _active_trim_equity(s)


@lru_cache(maxsize=512)
def _member_cumret(equity_path: str) -> pd.Series:
    """Compound cumulative return: ``C_t / C_0 - 1``."""
    s = _load_active_equity(equity_path)
    if s.empty or s.iloc[0] == 0:
        return pd.Series(dtype=float)
    return s / s.iloc[0] - 1.0


@lru_cache(maxsize=512)
def _member_cumret_simple(equity_path: str) -> pd.Series:
    """Simple (additive) cumulative return: ``Σ_t r_t`` where ``r_t = ΔC/C``.

    Approximates ``ln(C_t / C_0)`` for small per-bar returns; removes the
    compounding effect so what's plotted is the linear sum of period returns.
    """
    s = _load_active_equity(equity_path)
    if s.empty or s.iloc[0] == 0:
        return pd.Series(dtype=float)
    return s.pct_change().fillna(0.0).cumsum()


@lru_cache(maxsize=2048)
def _active_period_metrics(equity_path: str) -> dict:
    """Sharpe / total return / max DD / DD duration / window — active period only.

    Mirrors the engine's ``sharpe_daily_annualized`` (daily resample → mean/std
    × √252) so the displayed Sharpe is comparable with metrics.json. Returns
    an empty dict if the file is missing or never traded.
    """
    from intraday.backtest.metrics import sharpe_daily_annualized
    p = Path(equity_path)
    if not p.exists():
        return {}
    df = pd.read_parquet(p)
    if df.empty:
        return {}
    s = df.set_index("timestamp")["equity"].astype(float)
    s.index = pd.to_datetime(s.index)
    s = _active_trim_equity(s)
    if s.empty or s.iloc[0] == 0:
        return {}
    initial = float(s.iloc[0])
    final = float(s.iloc[-1])
    daily = s.resample("D").last().dropna()
    if daily.empty:
        return {}
    peak = daily.cummax()
    dd_series = (daily - peak) / peak
    max_dd = float(dd_series.min())
    in_dd = dd_series < 0
    if in_dd.any():
        dd_blocks = (in_dd != in_dd.shift()).cumsum()[in_dd]
        block_lens = dd_blocks.value_counts().sort_index()
        dd_duration_days = float(block_lens.max()) if not block_lens.empty else 0.0
    else:
        dd_duration_days = 0.0
    return {
        "active_start": str(s.index[0]),
        "active_end": str(s.index[-1]),
        "active_total_return": final / initial - 1.0,
        "active_sharpe_daily": sharpe_daily_annualized(list(s.values), s.index),
        "active_max_dd": max_dd,
        "active_dd_duration_days": dd_duration_days,
    }


def _resolve_member_equity_path(archive_root: Path, run: str, alpha_id: str, split: str) -> Path:
    """Tolerant resolver for both archive layouts.

    Layout A (current single-run): ``archive_root`` IS the run dir, members
    live at ``archive_root / alphas / <id>``.
    Layout B (multi-run): ``archive_root`` is the bare ``archive/``, members
    live at ``archive_root / <run> / alphas / <id>``.
    """
    direct = archive_root / "alphas" / alpha_id / split / "equity_curve.parquet"
    if direct.exists():
        return direct
    return archive_root / run / "alphas" / alpha_id / split / "equity_curve.parquet"


@lru_cache(maxsize=64)
def _composite_cumret_cached(
    composite_dir_str: str, manifest_mtime_ns: int, mode: str = "compound"
) -> go.Figure:
    composite_dir = Path(composite_dir_str)
    archive_root = composite_dir.parent.parent
    # Persistent /tmp cache: a 234-member composite needs ~2 s of parquet
    # reads to rebuild. We pickle ``fig.to_dict()`` (not the Figure object) —
    # unpickling a Figure runs Plotly's full validator tree per trace and
    # itself costs ~2 s; loading a plain dict is ~10 ms.
    import hashlib
    import pickle

    h = hashlib.md5(composite_dir_str.encode()).hexdigest()[:10]
    cache_path = Path("/tmp") / f"alpha_dashboard_cumret_{h}_{mode}_{manifest_mtime_ns}.pkl"
    if cache_path.exists():
        try:
            with cache_path.open("rb") as f:
                d = pickle.load(f)
            return go.Figure(data=d.get("data", []), layout=d.get("layout", {}), skip_invalid=True)
        except Exception:
            pass  # fall through and rebuild
    fig = composite_cumret_figure(composite_dir, archive_root, mode=mode)
    try:
        with cache_path.open("wb") as f:
            pickle.dump(fig.to_dict(), f, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        pass  # opportunistic
    return fig


def composite_member_summary_figure(composite_dir: Path, top_n: int = 20) -> go.Figure:
    """Horizontal bar of the top contributors by total integrated gross.

    Per-member lifetime contribution = ``Σ_t c_a · Σ_s |W_a[t,s]|`` (sum of
    member_gross_daily). For 1/N composites all coefficients are equal, so
    the ranking reflects each member's *activity intensity* — alphas that
    held larger gross positions for longer rank higher.
    """
    fig = go.Figure()
    p = composite_dir / "member_gross_daily.parquet"
    if not p.exists():
        return fig
    df = pd.read_parquet(p)
    if df.empty:
        return fig
    totals = (
        df.groupby("alpha_id")["gross_contribution"].sum().sort_values(ascending=False)
    )
    top = totals.head(top_n)
    rest_sum = float(totals.iloc[top_n:].sum()) if len(totals) > top_n else 0.0
    rest_n = max(0, len(totals) - top_n)
    labels = list(top.index[::-1])
    values = list(top.values[::-1])
    if rest_n > 0:
        labels.insert(0, f"… {rest_n} others")
        values.insert(0, rest_sum)
    fig.add_trace(
        go.Bar(
            y=labels,
            x=values,
            orientation="h",
            marker=dict(color=COMPOSITE_BOLD_COLOR),
            hovertemplate="%{y}<br>cum gross: %{x:.3f}<extra></extra>",
            showlegend=False,
        )
    )
    fig.update_layout(
        title=f"Top {top_n} contributors — integrated gross over IS (of {len(totals)} members)",
        height=500,
        margin=dict(l=240, r=20, t=50, b=40),
        xaxis_title="cumulative gross (member-days)",
    )
    fig.update_yaxes(automargin=True)
    return fig


def _stacked_member_lines(
    member_paths: list[str],
    cumret_fn: Callable[[str], pd.Series] = _member_cumret,
) -> tuple[list[Any], list[Any]]:
    """Load member equity curves in parallel and pack into a single
    (xs, ys) pair separated by ``None`` gaps. Plotly draws the result as
    visually distinct line segments with one trace's JSON overhead instead
    of N. ``None`` (not numpy NaT) is the only valid separator.
    """
    if not member_paths:
        return [], []
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as pool:
        series_list = list(pool.map(cumret_fn, member_paths))
    xs: list[Any] = []
    ys: list[Any] = []
    for s in series_list:
        if s.empty:
            continue
        s = _series_downsample(s, max_points=MEMBER_TRACE_POINTS)
        xs.extend(s.index.strftime("%Y-%m-%d %H:%M:%S").tolist())
        xs.append(None)
        ys.extend(s.values.astype(float).tolist())
        ys.append(None)
    return xs, ys


def composite_cumret_figure(
    composite_dir: Path,
    archive_root: Path,
    mode: str = "compound",
) -> go.Figure:
    """Build the composite cumret chart in either ``compound`` or ``simple`` mode."""
    cumret_fn = _member_cumret_simple if mode == "simple" else _member_cumret
    label = "Simple (additive)" if mode == "simple" else "Compound"
    fig = go.Figure()
    members_csv = composite_dir / "members.csv"
    members = pd.read_csv(members_csv) if members_csv.exists() else pd.DataFrame()
    has_flip = "flipped" in members.columns

    def _add_member_lines(split: str, color: str, legend_name: str):
        """Plot one faded line per member. When `flipped`=1 the cumret
        series is negated so the rendered line matches what the member
        actually contributes to the composite (sign-flipped at deploy)."""
        if members.empty:
            return
        is_first = True
        for _, m in members.iterrows():
            try:
                p = _resolve_member_equity_path(
                    archive_root, str(m["run"]), str(m["alpha_id"]), split)
            except Exception:
                continue
            if not Path(p).exists():
                continue
            s = cumret_fn(str(p))
            if s.empty:
                continue
            if has_flip and bool(m["flipped"]):
                s = -s
            s = _series_downsample(s)
            fig.add_trace(
                go.Scattergl(
                    x=s.index.astype(str), y=s.values, mode="lines",
                    line=dict(color=color, width=1),
                    name=legend_name if is_first else legend_name,
                    showlegend=is_first, hoverinfo="skip",
                )
            )
            is_first = False

    _add_member_lines("is", COMPOSITE_MEMBER_LINE_COLOR, "members IS")
    _add_member_lines("os", COMPOSITE_MEMBER_OS_LINE_COLOR, "members OS")

    # Composite IS line (bold dark blue)
    comp_is_path = composite_dir / "is" / "equity_curve.parquet"
    if comp_is_path.exists():
        s = cumret_fn(str(comp_is_path))
        if not s.empty:
            s = _series_downsample(s)
            fig.add_trace(
                go.Scatter(
                    x=s.index.astype(str), y=s.values, mode="lines",
                    line=dict(color=COMPOSITE_BOLD_COLOR, width=3),
                    name="Composite IS",
                    hovertemplate="composite IS<br>%{x}<br>%{y:.2%}<extra></extra>",
                )
            )
    # Composite OS line (bold red — matches individual-alpha OS #dc2626)
    comp_os_path = composite_dir / "os" / "equity_curve.parquet"
    if comp_os_path.exists():
        s = cumret_fn(str(comp_os_path))
        if not s.empty:
            s = _series_downsample(s)
            fig.add_trace(
                go.Scatter(
                    x=s.index.astype(str), y=s.values, mode="lines",
                    line=dict(color=COMPOSITE_OS_BOLD_COLOR, width=3),
                    name="Composite OS",
                    hovertemplate="composite OS<br>%{x}<br>%{y:.2%}<extra></extra>",
                )
            )

    fig.update_layout(
        title=f"Cumulative return — {label}: composite (bold) vs members (faded), IS / OS",
        height=440,
        margin=dict(l=40, r=20, t=50, b=70),
        xaxis_title="time",
        yaxis_title="cum return",
        showlegend=True,
        legend=dict(orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5),
        hovermode="x unified",
    )
    fig.update_yaxes(tickformat=".1%")
    fig.add_hline(y=0, line_dash="dash", line_width=1, line_color="#94a3b8")
    return fig


def main() -> None:
    args = parse_args()
    run_dir = Path(args.run_dir)
    app.storage.general["run_dir"] = str(run_dir)

    @ui.page("/")
    def page():
        add_styles()
        render_top_nav()
        df = load_index(run_dir)
        state = {"df": df, "search_text": build_search_text(run_dir, df)}
        composites = discover_composites(run_dir)
        live_alphas = discover_live_alphas(run_dir)
        with ui.column().classes("page-wrap w-full gap-3"):
            with ui.column().classes("page-header"):
                ui.label("Alpha Archive").classes("page-title")
                ui.label(f"{run_dir}").classes("geek-aside")

            with ui.tabs().classes("w-full") as top_tabs:
                tab_alphas = ui.tab("Alphas")
                tab_live = ui.tab(f"Live ({len(live_alphas)})")
                tab_composites = ui.tab(f"Composites ({len(composites)})")
            with ui.tab_panels(top_tabs, value=tab_alphas).classes("w-full"):
                with ui.tab_panel(tab_alphas):
                    df = state["df"]
                    sub_n = int((df["category"] == "SUBMITTABLE").sum()) if "category" in df.columns else 0
                    norm_n = int((df["category"] == "NORMAL").sum()) if "category" in df.columns else 0
                    with ui.row().classes("w-full gap-2"):
                        with ui.card().classes("metric-card metric-card-accent"):
                            ui.label("Alphas").classes("metric-label")
                            ui.label(str(len(df))).classes("metric-value")
                        live_tone_class = "metric-card-positive" if len(live_alphas) else "metric-card-muted"
                        with ui.card().classes(f"metric-card {live_tone_class}").on(
                            "click", lambda: top_tabs.set_value(tab_live)
                        ).style("cursor: pointer;"):
                            ui.label("Live").classes("metric-label")
                            ui.label(str(len(live_alphas))).classes("metric-value")
                        with ui.card().classes("metric-card metric-card-positive"):
                            ui.label("Submittable").classes("metric-label")
                            ui.label(str(sub_n)).classes("metric-value")
                        with ui.card().classes("metric-card metric-card-muted"):
                            ui.label("Normal").classes("metric-label")
                            ui.label(str(norm_n)).classes("metric-value")

                    with ui.row().classes("w-full items-end gap-3"):
                        search_input = ui.input("Search").props("clearable dense").classes("w-96")
                        category_values = sorted(str(v) for v in df["category"].dropna().unique().tolist()) if "category" in df.columns else []
                        status_filter = ui.select(category_values, multiple=True, label="Category").classes("w-48")
                        bar_values = sorted(
                            str(v) for v in df["bar_label"].dropna().unique().tolist()
                        ) if "bar_label" in df.columns else []
                        bar_filter = ui.select(bar_values, multiple=True, label="Bar size").classes("w-40")
                        sort_select = ui.select(
                            [
                                "is_sharpe", "is_return", "is_max_dd", "is_pnl_bps", "is_trades",
                                "os_sharpe", "os_return", "os_max_dd", "os_pnl_bps", "os_trades",
                            ],
                            value="is_sharpe",
                            label="Sort",
                        ).classes("w-48")
                        min_is_sharpe = ui.number("Min IS Sharpe(daily)", value=None, step=0.01).classes("w-40")
                        min_trades = ui.number("Min trades", value=0, min=0, step=1).classes("w-40")

                    rows_container = ui.column().classes("w-full")

                    table_ref = {"table": None}

                    def filtered_rows() -> list[dict[str, Any]]:
                        view = state["df"].copy()
                        query = str(search_input.value or "").strip().lower()
                        if query:
                            mask = state["search_text"].str.contains(query, regex=False, na=False)
                            view = view[mask]
                        if status_filter.value:
                            view = view[view["category"].isin(status_filter.value)]
                        if bar_filter.value:
                            view = view[view["bar_label"].isin(bar_filter.value)]
                        if min_is_sharpe.value is not None:
                            is_sharpe = pd.to_numeric(view["is_sharpe"], errors="coerce")
                            # Filter input is in daily Sharpe; stored is_sharpe is
                            # annualized (×sqrt(252)). Compare on annualized value
                            # so the user-entered daily threshold matches display.
                            view = view[is_sharpe >= float(min_is_sharpe.value) * SQRT_252]
                        if min_trades.value:
                            is_trades = pd.to_numeric(view["is_trades"], errors="coerce").fillna(0)
                            os_trades = pd.to_numeric(view["os_trades"], errors="coerce").fillna(0)
                            view = view[(is_trades >= int(min_trades.value)) | (os_trades >= int(min_trades.value))]
                        view = view.sort_values(sort_select.value, ascending=False, na_position="last")
                        return display_rows(view)

                    def render_table():
                        rows_container.clear()
                        rows = filtered_rows()
                        with rows_container:
                            with ui.row().classes("w-full items-center justify-between"):
                                ui.label(f"Alpha Table ({len(rows)})").classes("section-title")
                                ui.label("Click a row to inspect artifacts, IS/OS equity, weights, params, and validation flags.").classes("text-xs text-gray-500")
                            table = ui.table(
                                columns=[
                                    {
                                        "name": name,
                                        "label": label,
                                        "field": name,
                                        "sortable": True,
                                        "align": align,
                                    }
                                    for name, label, align in TABLE_COLUMNS
                                ],
                                rows=rows,
                                row_key="alpha_id",
                                pagination=25,
                            ).classes("w-full alpha-table").props("flat bordered")
                            table.on(
                                "rowClick",
                                lambda e: ui.navigate.to(f"/alpha/{e.args[1]['run_id']}/{e.args[1]['alpha_id']}"),
                            )
                            # Phone-only card list — CSS media query hides the
                            # wide table above and reveals this on viewports
                            # <= 640px. Same dataset, kinder to thumbs.
                            with ui.element("div").classes("alpha-card-list w-full"):
                                for row in rows[:50]:  # cap to avoid massive phone scroll
                                    sharpe_v = row.get("is_sharpe")
                                    ret_v = row.get("is_return")
                                    pos_neg = ""
                                    if isinstance(ret_v, (int, float)) and ret_v == ret_v:
                                        pos_neg = "pos" if ret_v > 0 else ("neg" if ret_v < 0 else "")
                                    sharpe_pair = html.escape(_fmt_sharpe_pair(sharpe_v))
                                    ret_fmt = html.escape(_fmt_pct(ret_v))
                                    tr_fmt = html.escape(_fmt_int(row.get("is_trades")))
                                    cat = html.escape(str(row.get("category") or "-"))
                                    aid = html.escape(str(row.get("alpha_id") or "-"))
                                    rid = html.escape(str(row.get("run_id") or "-"))
                                    # URL parts go through a separate escape pass — the
                                    # JS string literal needs quote-safety too.
                                    aid_url = aid.replace("'", "%27")
                                    rid_url = rid.replace("'", "%27")
                                    ui.html(
                                        f'''
                                        <div class="alpha-row" onclick="window.location.href='/alpha/{rid_url}/{aid_url}'">
                                          <div class="row-head">
                                            <div class="row-title">{aid}</div>
                                            <div class="row-cat">{cat}</div>
                                          </div>
                                          <div class="row-stats">
                                            <div><span class="stat-label">IS Sh (d/y)</span><span class="stat-value">{sharpe_pair}</span></div>
                                            <div><span class="stat-label">IS Ret</span><span class="stat-value {pos_neg}">{ret_fmt}</span></div>
                                            <div><span class="stat-label">IS Tr</span><span class="stat-value">{tr_fmt}</span></div>
                                          </div>
                                        </div>
                                        ''',
                                        sanitize=False,
                                    )
                                if len(rows) > 50:
                                    ui.label(f"… and {len(rows)-50} more. Use sort/filter to narrow.").classes("note-text mt-1")
                            table_ref["table"] = table

                    for control in (search_input, status_filter, bar_filter, sort_select, min_is_sharpe, min_trades):
                        control.on_value_change(lambda _: render_table())

                    render_table()

                with ui.tab_panel(tab_live):
                    if not live_alphas:
                        ui.label(
                            "No alphas currently live. Start a paper forward "
                            "from any alpha's detail page to see it here."
                        ).classes("note-text")
                    else:
                        with ui.column().classes("w-full gap-2"):
                            for entry in live_alphas:
                                st = entry["status"]
                                target_url = f"/alpha/{entry['run_id']}/{entry['alpha_id']}"
                                card = ui.card().classes("metric-card-accent w-full p-3").style(
                                    "cursor: pointer;"
                                )
                                card.on("click", lambda _, url=target_url: ui.navigate.to(url))
                                with card:
                                    with ui.row().classes("items-center justify-between w-full"):
                                        ui.label(entry["alpha_id"]).classes("text-base font-bold").style(
                                            "color: var(--text);"
                                        )
                                        ui.html('<span class="badge-live">LIVE</span>', sanitize=False)
                                    ui.label(entry["run_id"]).classes("path-text")
                                    with ui.row().classes("gap-2 w-full mt-2"):
                                        nav_cur = st.get("nav_current")
                                        s_pnl = st.get("session_pnl")
                                        s_ret = st.get("session_return")
                                        metric_card(
                                            "NAV",
                                            f"${nav_cur:,.2f}" if nav_cur else "-",
                                        )
                                        metric_card(
                                            "Session PnL",
                                            f"${s_pnl:+.2f}" if s_pnl is not None else "-",
                                            tone=_tone_from_number(s_pnl),
                                        )
                                        metric_card(
                                            "Session Return",
                                            _fmt_pct(s_ret),
                                            tone=_tone_from_number(s_ret),
                                        )
                                        metric_card(
                                            "Uptime",
                                            format_uptime(st.get("uptime_seconds")),
                                        )

                with ui.tab_panel(tab_composites):
                    if not composites:
                        ui.label("No composites found under archive/composites/.").classes("note-text")
                    else:
                        ui.label("Composite alphas — click a row to drill into members and weights.").classes("text-xs text-gray-500")
                        comp_rows = []
                        for c in composites:
                            comp_rows.append(
                                {
                                    "composite_id": c["composite_id"],
                                    "dir_name": c["dir_name"],
                                    "method": c["method"],
                                    "n_members": c["n_members"],
                                    "is_sharpe_fmt": _fmt_sharpe_pair(c["is_sharpe"]),
                                    "is_return_fmt": _fmt_pct(c["is_return"]),
                                    "is_drawdown_fmt": _fmt_pct(c["is_drawdown"]),
                                    "is_trades_fmt": _fmt_int(c["is_trades"]),
                                    "os_sharpe_fmt": _fmt_sharpe_pair(c.get("os_sharpe")),
                                    "os_return_fmt": _fmt_pct(c.get("os_return")),
                                    "os_drawdown_fmt": _fmt_pct(c.get("os_drawdown")),
                                    "os_trades_fmt": _fmt_int(c.get("os_trades")),
                                    "mean_row_l1_fmt": _fmt_num(c["mean_row_l1"]),
                                }
                            )
                        comp_table = ui.table(
                            columns=[
                                {"name": "composite_id", "label": "composite", "field": "composite_id", "align": "left"},
                                {"name": "method", "label": "method", "field": "method", "align": "left"},
                                {"name": "n_members", "label": "members", "field": "n_members", "align": "right"},
                                {"name": "is_sharpe_fmt", "label": "IS Sh (d/y)", "field": "is_sharpe_fmt", "align": "right"},
                                {"name": "is_return_fmt", "label": "IS ret", "field": "is_return_fmt", "align": "right"},
                                {"name": "is_drawdown_fmt", "label": "IS dd", "field": "is_drawdown_fmt", "align": "right"},
                                {"name": "is_trades_fmt", "label": "IS tr", "field": "is_trades_fmt", "align": "right"},
                                {"name": "os_sharpe_fmt", "label": "OS Sh (d/y)", "field": "os_sharpe_fmt", "align": "right"},
                                {"name": "os_return_fmt", "label": "OS ret", "field": "os_return_fmt", "align": "right"},
                                {"name": "os_drawdown_fmt", "label": "OS dd", "field": "os_drawdown_fmt", "align": "right"},
                                {"name": "os_trades_fmt", "label": "OS tr", "field": "os_trades_fmt", "align": "right"},
                                {"name": "mean_row_l1_fmt", "label": "mean gross", "field": "mean_row_l1_fmt", "align": "right"},
                            ],
                            rows=comp_rows,
                            row_key="dir_name",
                            pagination=25,
                        ).classes("w-full dense-panel")
                        comp_table.on(
                            "rowClick",
                            lambda e: ui.navigate.to(f"/composite/{e.args[1]['dir_name']}"),
                        )
            render_footer(run_dir)

    @ui.page("/alpha/{run_id}/{alpha_id}")
    def alpha_page(run_id: str, alpha_id: str):
        add_styles()
        render_top_nav()
        df = load_index(run_dir)
        selected_rows = df[(df["run_id"] == run_id) & (df["alpha_id"] == alpha_id)]
        with ui.column().classes("page-wrap w-full gap-3"):
            with ui.row().classes("w-full items-center justify-between"):
                ui.button("Back", icon="arrow_back", on_click=lambda: ui.navigate.to("/"))
                detail_run_dir = Path(run_id) if (Path(run_id) / "alpha_index.csv").exists() else run_dir / run_id
                ui.label(artifact_path(detail_run_dir, alpha_id)).classes("path-text")
            if selected_rows.empty:
                ui.label(f"Unknown alpha_id: {alpha_id}").classes("text-lg font-semibold")
                return

            selected = selected_rows.iloc[0].to_dict()
            detail_run_dir = row_run_dir(selected, detail_run_dir)
            validation = read_json(alpha_dir(detail_run_dir, alpha_id) / "validation.json")
            params = load_alpha_params(detail_run_dir, alpha_id)
            is_turnover = turnover_from_weights(detail_run_dir, alpha_id, "is")
            os_turnover = turnover_from_weights(detail_run_dir, alpha_id, "os")

            # Heading row: alpha name + LIVE badge if a recent forward exists.
            # Forward is now driven by cron + scripts/run_forward_tick.py; the
            # in-page "Start" button is gone. Liveness = "forward/ exists and
            # the most recent emit was within ~1.5× the candle period".
            with ui.row().classes("items-center gap-3"):
                ui.label(alpha_id).classes("page-title")
                forward_dir = alpha_dir(detail_run_dir, alpha_id) / "forward"
                already_live = is_forward_live(forward_dir)
                if already_live:
                    ui.html('<span class="badge-live">LIVE</span>', sanitize=False)

            # ---------- Section: LIVE STATUS (if forward exists) ----------
            fwd_dir = alpha_dir(detail_run_dir, alpha_id) / "forward"
            if fwd_dir.exists():
                status = forward_status(fwd_dir)
                # --- Vibe block: current-bar gain/loss banner ---
                # PnL since the last rebalance (= last kline close that the
                # strategy acted on). Resets each new bar. Daily strategy →
                # "today's PnL"; an hourly strategy auto-adapts.
                bar_pnl_usd, bar_ret = _current_bar_pnl(fwd_dir)
                if bar_pnl_usd is not None:
                    is_loss = bar_pnl_usd < 0
                    tone_cls = "loss" if is_loss else "gain"
                    pct_part = f" ({bar_ret * 100:+.2f}%)" if bar_ret is not None else ""
                    roast = (
                        "오늘은 주인님을 위해 따뜻한 말 한마디를 보태주세요. "
                        "Take it easy, boss — the market owes us nothing."
                        if is_loss else
                        "오늘의 식대는 강세장이 책임집니다. "
                        "Green candle, green tea — savor it."
                    )
                    with ui.element("div").classes(f"daily-banner {tone_cls} w-full"):
                        ui.html(
                            f'<div class="daily-label">Current bar PnL (since last close)</div>'
                            f'<div class="daily-amount">{bar_pnl_usd:+,.2f} USD{pct_part}</div>'
                            f'<div class="daily-roast">{roast}</div>',
                            sanitize=False,
                        )
                with ui.column().classes("section-panel w-full gap-2"):
                    with ui.row().classes("w-full items-center justify-between"):
                        ui.label("Live Status").classes("section-title")
                        temp_c, temp_status = hangang_temp()
                        if temp_c is not None:
                            ui.html(
                                f'<div class="hangang-chip">'
                                f'<span>🌊 한강 수온</span>'
                                f'<span class="hangang-temp">{temp_c:.1f}°C</span>'
                                f'</div>',
                                sanitize=False,
                            )
                        else:
                            ui.html(
                                f'<div class="hangang-chip" title="{html.escape(temp_status)}">'
                                f'<span>🌊 한강 수온</span>'
                                f'<span class="hangang-aside">측정 불가</span>'
                                f'</div>',
                                sanitize=False,
                            )
                    with ui.row().classes("gap-2 w-full"):
                        metric_card(
                            "Status",
                            "● LIVE" if status["live"] else "○ Stopped",
                            tone="positive" if status["live"] else "muted",
                        )
                        metric_card(
                            "PID",
                            str(status["pid"]) if status["pid"] else "-",
                        )
                        metric_card(
                            "Uptime",
                            format_uptime(status["uptime_seconds"]),
                        )
                        nav_curr = status["nav_current"]
                        nav_start = status["nav_start"]
                        nav_pct = (
                            (nav_curr / nav_start - 1.0) if nav_curr and nav_start
                            else None
                        )
                        metric_card(
                            "Live NAV",
                            f"${nav_curr:,.2f}" if nav_curr else "-",
                        )
                        metric_card(
                            "Live Return",
                            _fmt_pct(nav_pct),
                            tone=_tone_from_number(nav_pct),
                        )
                        pnl = status["today_pnl"]
                        metric_card(
                            "Last bar PnL",
                            f"${pnl:+.2f}" if pnl is not None else "-",
                            tone=_tone_from_number(pnl),
                        )
                        metric_card(
                            "Last decision",
                            status["last_decision"].strftime("%Y-%m-%d %H:%M")
                            if status["last_decision"] is not None else "-",
                        )
                # Live-only: post-OS session PnL (segment after OS ends)
                if status["live"]:
                    with ui.column().classes("section-panel w-full gap-2"):
                        ui.label("Live Session (post-OS)").classes("section-title")
                        with ui.row().classes("gap-2 w-full"):
                            s_pnl = status["session_pnl"]
                            s_ret = status["session_return"]
                            s_start = status["session_start"]
                            s_eq0 = status["session_equity_start"]
                            metric_card(
                                "Session start",
                                s_start.strftime("%Y-%m-%d %H:%M")
                                if s_start is not None else "-",
                            )
                            metric_card(
                                "Session start NAV",
                                f"${s_eq0:,.2f}" if s_eq0 is not None else "-",
                            )
                            metric_card(
                                "Session PnL",
                                f"${s_pnl:+.2f}" if s_pnl is not None else "-",
                                tone=_tone_from_number(s_pnl),
                            )
                            metric_card(
                                "Session Return",
                                _fmt_pct(s_ret),
                                tone=_tone_from_number(s_ret),
                            )
                        # Forward-only PnL curve — separate from the stitched
                        # IS+OS+forward chart below, so the user can read live
                        # performance without backtest history bleeding in.
                        ui.plotly(
                            forward_session_figure(detail_run_dir, alpha_id)
                        ).classes("w-full chart-host mt-2")
            is_bps_simple, is_bps_w, _ = net_pnl_per_trade_bps(detail_run_dir, alpha_id, "is")
            os_bps_simple, os_bps_w, _ = net_pnl_per_trade_bps(detail_run_dir, alpha_id, "os")
            is_dd_pct, is_dd_dur, is_peak_ts, is_recov_ts = drawdown_metrics(detail_run_dir, alpha_id, "is")
            os_dd_pct, os_dd_dur, os_peak_ts, os_recov_ts = drawdown_metrics(detail_run_dir, alpha_id, "os")

            # ---------- Section: Status header ----------
            with ui.column().classes("section-panel w-full gap-2"):
                ui.label("Overview").classes("section-title")
                with ui.row().classes("gap-2 w-full"):
                    metric_card("Category", str(selected.get("category", "-")))
                    metric_card("IS Trades", _fmt_int(selected.get("is_trades", 0)))
                    metric_card("OS Trades", _fmt_int(selected.get("os_trades", 0)))
                    metric_card("Turnover IS/OS", f"{_fmt_turnover(is_turnover)} / {_fmt_turnover(os_turnover)}")

            # ---------- Section: Returns ----------
            with ui.column().classes("section-panel w-full gap-2"):
                ui.label("Returns").classes("section-title")
                with ui.row().classes("gap-2 w-full"):
                    metric_card("IS Net return", _fmt_pct(selected.get("is_return")),
                                tone=_tone_from_number(selected.get("is_return")))
                    metric_card("IS bps/trade",        _fmt_bps(is_bps_simple),
                                tone=_tone_from_number(is_bps_simple))
                    metric_card("IS bps (notional-w)", _fmt_bps(is_bps_w),
                                tone=_tone_from_number(is_bps_w))
                    metric_card("OS Net return", _fmt_pct(selected.get("os_return")),
                                tone=_tone_from_number(selected.get("os_return")))
                    metric_card("OS bps/trade",        _fmt_bps(os_bps_simple),
                                tone=_tone_from_number(os_bps_simple))
                    metric_card("OS bps (notional-w)", _fmt_bps(os_bps_w),
                                tone=_tone_from_number(os_bps_w))

            # ---------- Section: Risk-Adjusted ----------
            with ui.column().classes("section-panel w-full gap-2"):
                ui.label("Risk-Adjusted").classes("section-title")
                with ui.row().classes("gap-2 w-full"):
                    metric_card("IS Sharpe(daily)", _fmt_sharpe_daily(selected.get("is_sharpe")),
                                tone=_tone_from_number(selected.get("is_sharpe")))
                    metric_card("IS Sharpe(yearly)", _fmt_sharpe_annual(selected.get("is_sharpe")),
                                tone=_tone_from_number(selected.get("is_sharpe")))
                    metric_card("IS per-trade Sharpe", _fmt_num(selected.get("is_per_trade_sharpe")),
                                tone=_tone_from_number(selected.get("is_per_trade_sharpe")))
                    metric_card("IS Calmar", _fmt_num(selected.get("is_calmar")),
                                tone=_tone_from_number(selected.get("is_calmar")))
                with ui.row().classes("gap-2 w-full"):
                    metric_card("OS Sharpe(daily)", _fmt_sharpe_daily(selected.get("os_sharpe")),
                                tone=_tone_from_number(selected.get("os_sharpe")))
                    metric_card("OS Sharpe(yearly)", _fmt_sharpe_annual(selected.get("os_sharpe")),
                                tone=_tone_from_number(selected.get("os_sharpe")))
                    metric_card("OS per-trade Sharpe", _fmt_num(selected.get("os_per_trade_sharpe")),
                                tone=_tone_from_number(selected.get("os_per_trade_sharpe")))
                    metric_card("OS Calmar", _fmt_num(selected.get("os_calmar")),
                                tone=_tone_from_number(selected.get("os_calmar")))

            # ---------- Section: Drawdown ----------
            with ui.column().classes("section-panel w-full gap-2"):
                ui.label("Drawdown").classes("section-title")
                with ui.row().classes("gap-2 w-full"):
                    metric_card("IS Max DD", _fmt_pct(is_dd_pct), tone="negative" if is_dd_pct else None)
                    metric_card("IS DD duration", _fmt_duration_days(is_dd_dur))
                    metric_card("OS Max DD", _fmt_pct(os_dd_pct), tone="negative" if os_dd_pct else None)
                    metric_card("OS DD duration", _fmt_duration_days(os_dd_dur))
                # God-loves-you banner — surfaces when any split's drawdown
                # passes 20%. The Comic Sans is the joke; don't lecture it.
                worst_mdd = max(
                    (abs(x) for x in (is_dd_pct, os_dd_pct) if x is not None),
                    default=0.0,
                )
                if worst_mdd >= 0.20:
                    ui.html(
                        f'<div class="god-banner">'
                        f'  <div class="god-line">하나님은 당신을 사랑합니다.</div>'
                        f'  <div class="god-line-en">God loves you.</div>'
                        f'  <div class="god-foot">// MDD {worst_mdd*100:.1f}% — hang in there, boss</div>'
                        f'</div>',
                        sanitize=False,
                    )

            # ---------- Section: Backtest details (collapsed) ----------
            # These three sections (Statistical Confidence / Distribution /
            # Overfit Check) are mostly informational for the backtest
            # researcher. For live monitoring most fields are "-" so they
            # add clutter — hide behind a click. No lazy load needed; the
            # values are already attached to ``selected``.
            def _ratio(os_v, is_v):
                try:
                    if os_v is None or is_v is None or float(is_v) == 0:
                        return None
                    return float(os_v) / float(is_v)
                except Exception:
                    return None

            sharpe_degr = _ratio(selected.get("os_sharpe"), selected.get("is_sharpe"))
            bps_degr = _ratio(os_bps_simple, is_bps_simple)
            pf_degr = _ratio(
                selected.get("os_profit_factor_trades"),
                selected.get("is_profit_factor_trades"),
            )
            ts_degr = _ratio(selected.get("os_t_stat"), selected.get("is_t_stat"))

            with ui.expansion(
                "Backtest details — Statistical Confidence · Distribution · Overfit Check",
                icon="science",
            ).classes("w-full dense-panel"):
                with ui.column().classes("section-panel w-full gap-2 mt-2"):
                    ui.label("Statistical Confidence").classes("section-title")
                    with ui.row().classes("gap-2 w-full"):
                        metric_card("IS t-stat", _fmt_num(selected.get("is_t_stat")),
                                    tone=_tone_from_number(selected.get("is_t_stat")))
                        metric_card("IS Profit Factor", _fmt_num(selected.get("is_profit_factor_trades")))
                        metric_card("IS Round trips", _fmt_int(selected.get("is_round_trips")))
                        metric_card("OS t-stat", _fmt_num(selected.get("os_t_stat")),
                                    tone=_tone_from_number(selected.get("os_t_stat")))
                        metric_card("OS Profit Factor", _fmt_num(selected.get("os_profit_factor_trades")))
                        metric_card("OS Round trips", _fmt_int(selected.get("os_round_trips")))

                with ui.column().classes("section-panel w-full gap-2 mt-2"):
                    ui.label("Distribution").classes("section-title")
                    with ui.row().classes("gap-2 w-full"):
                        metric_card("IS Win rate (trades)", _fmt_pct(selected.get("is_win_rate_trades")))
                        metric_card("IS Avg win", _fmt_bps(selected.get("is_avg_win_bps")), tone="positive")
                        metric_card("IS Avg loss", _fmt_bps(selected.get("is_avg_loss_bps")), tone="negative")
                        metric_card("IS W/L ratio", _fmt_num(selected.get("is_win_loss_ratio")))
                        metric_card("IS Largest win",  _fmt_bps(selected.get("is_largest_win_bps")), tone="positive")
                        metric_card("IS Largest loss", _fmt_bps(selected.get("is_largest_loss_bps")), tone="negative")
                    with ui.row().classes("gap-2 w-full"):
                        metric_card("OS Win rate (trades)", _fmt_pct(selected.get("os_win_rate_trades")))
                        metric_card("OS Avg win", _fmt_bps(selected.get("os_avg_win_bps")), tone="positive")
                        metric_card("OS Avg loss", _fmt_bps(selected.get("os_avg_loss_bps")), tone="negative")
                        metric_card("OS W/L ratio", _fmt_num(selected.get("os_win_loss_ratio")))
                        metric_card("OS Largest win",  _fmt_bps(selected.get("os_largest_win_bps")), tone="positive")
                        metric_card("OS Largest loss", _fmt_bps(selected.get("os_largest_loss_bps")), tone="negative")

                with ui.column().classes("section-panel w-full gap-2 mt-2"):
                    ui.label("Overfit Check (OS / IS)").classes("section-title")
                    with ui.row().classes("gap-2 w-full"):
                        metric_card("Sharpe degr", _fmt_num(sharpe_degr))
                        metric_card("bps degr",    _fmt_num(bps_degr))
                        metric_card("PF degr",     _fmt_num(pf_degr))
                        metric_card("t-stat degr", _fmt_num(ts_degr))
            with ui.grid(columns=2).classes("w-full gap-3 chart-grid"):
                with ui.column().classes("w-full gap-1"):
                    with ui.row().classes("w-full justify-end"):
                        alpha_mode_toggle = ui.toggle(
                            {"compound": "Compound", "simple": "Simple"},
                            value="compound",
                        ).props("dense")
                    alpha_eq_compound = ui.plotly(
                        equity_figure(detail_run_dir, alpha_id, mode="compound")
                    ).classes("w-full dense-panel chart-host")
                    alpha_eq_simple = ui.plotly(
                        equity_figure(detail_run_dir, alpha_id, mode="simple")
                    ).classes("w-full dense-panel chart-host")
                    alpha_eq_simple.set_visibility(False)
                    alpha_mode_toggle.on_value_change(
                        lambda e: (
                            alpha_eq_compound.set_visibility(e.value == "compound"),
                            alpha_eq_simple.set_visibility(e.value != "compound"),
                        )
                    )
                ui.plotly(drawdown_figure(detail_run_dir, alpha_id)).classes("w-full dense-panel chart-host")
                ui.plotly(weights_figure(detail_run_dir, alpha_id, "is")).classes("w-full dense-panel chart-host")
            # Hourly weight chart is by far the heaviest plot (~2s for 109
            # symbol stacked-area traces). Hide it behind a collapsed
            # expansion and build the Figure only on first expand, so the
            # cold-cache page entry isn't held up by a plot most viewers
            # may not look at.
            with ui.expansion(
                "IS Hourly Weight Distribution (click to load)",
                icon="show_chart",
            ).classes("w-full dense-panel") as hw_exp:
                hw_state = {"loaded": False}

                def _load_hw(e, exp=hw_exp, state=hw_state,
                             rd=detail_run_dir, aid_=alpha_id):
                    if e.value and not state["loaded"]:
                        state["loaded"] = True
                        with exp:
                            ui.plotly(
                                hourly_weight_stack_figure(rd, aid_, "is")
                            ).classes("w-full chart-host")

                hw_exp.on_value_change(_load_hw)
            with ui.tabs().classes("w-full") as tabs:
                tab_params = ui.tab("Params")
                tab_validation = ui.tab("Validation")
            with ui.tab_panels(tabs, value=tab_params).classes("w-full"):
                with ui.tab_panel(tab_params):
                    ui.code(json.dumps(params, indent=2), language="json").classes("w-full")
                with ui.tab_panel(tab_validation):
                    ui.code(json.dumps(validation, indent=2), language="json").classes("w-full")
            render_footer(run_dir)

    @ui.page("/composite/{composite_dir_name}")
    def composite_page(composite_dir_name: str):
        add_styles()
        render_top_nav()
        composite_dir = run_dir / "composites" / composite_dir_name
        manifest_path = composite_dir / "manifest.json"
        is_metrics_path = composite_dir / "is" / "metrics.json"
        with ui.column().classes("page-wrap w-full gap-3"):
            with ui.row().classes("w-full items-center justify-between"):
                ui.button("Back", icon="arrow_back", on_click=lambda: ui.navigate.to("/"))
                ui.label(str(composite_dir)).classes("path-text")

            if not manifest_path.exists():
                ui.label(f"composite not found: {composite_dir_name}").classes("text-lg font-semibold")
                return

            manifest = read_json(manifest_path)
            metrics = read_json(is_metrics_path) if is_metrics_path.exists() else {}

            ui.label(manifest.get("composite_id", composite_dir_name)).classes("text-xl font-semibold")
            ui.label(
                f"method: {manifest.get('method', '?')}  |  "
                f"members: {manifest.get('n_members', 0)}  |  "
                f"window: {manifest.get('is_window', {}).get('start', '?')} → "
                f"{manifest.get('is_window', {}).get('end', '?')}"
            ).classes("text-xs text-gray-500")
            if manifest.get("selection_bias_warning"):
                with ui.card().classes("dense-panel"):
                    ui.label("⚠ Selection bias notice").classes("section-title")
                    ui.label(manifest["selection_bias_warning"]).classes("note-text")

            # Composite-level metrics: Sharpe / return / DD recomputed over the
            # active period (first realised PnL bar onward) so warmup zeros do
            # not dilute. Trade-derived metrics (count, win rate, PF, bps) are
            # already active-period since trades only fire after entry.
            comp_trades_path = composite_dir / "is" / "trades.parquet"
            comp_eq_path = composite_dir / "is" / "equity_curve.parquet"
            comp_bps_simple, comp_bps_w, _ = _net_trade_metrics_cached(str(comp_trades_path))
            is_active = _active_period_metrics(str(comp_eq_path))

            os_metrics_path = composite_dir / "os" / "metrics.json"
            os_trades_path = composite_dir / "os" / "trades.parquet"
            os_eq_path = composite_dir / "os" / "equity_curve.parquet"
            os_metrics = read_json(os_metrics_path) if os_metrics_path.exists() else {}
            os_bps_simple, os_bps_w, _ = _net_trade_metrics_cached(str(os_trades_path))
            os_active = _active_period_metrics(str(os_eq_path))

            ui.label("IS metrics — active period only (warmup excluded)").classes("section-title")
            if is_active:
                ui.label(
                    f"active window: {is_active['active_start']} → {is_active['active_end']}"
                ).classes("text-xs text-gray-500")
            with ui.row().classes("gap-2 w-full"):
                metric_card("Sharpe(daily)", _fmt_sharpe_daily(is_active.get("active_sharpe_daily")))
                metric_card("Net return", _fmt_pct(is_active.get("active_total_return")))
                metric_card("Max DD", _fmt_pct(is_active.get("active_max_dd")))
                metric_card("DD duration", _fmt_duration_days(is_active.get("active_dd_duration_days")))
                metric_card("Net bps/trade", _fmt_bps(comp_bps_simple))
                metric_card("bps (notional-w)", _fmt_bps(comp_bps_w))
                metric_card("Trades", _fmt_int(metrics.get("total_trades")))
                metric_card("Win rate", _fmt_pct(metrics.get("win_rate")))
                metric_card("Profit factor", _fmt_num(metrics.get("profit_factor")))

            if os_metrics or os_eq_path.exists():
                ui.label("OS metrics — active period only").classes("section-title")
                if os_active:
                    ui.label(
                        f"active window: {os_active['active_start']} → {os_active['active_end']}"
                    ).classes("text-xs text-gray-500")
                with ui.row().classes("gap-2 w-full"):
                    metric_card("Sharpe(daily)", _fmt_sharpe_daily(os_active.get("active_sharpe_daily")))
                    metric_card("Net return", _fmt_pct(os_active.get("active_total_return")))
                    metric_card("Max DD", _fmt_pct(os_active.get("active_max_dd")))
                    metric_card("DD duration", _fmt_duration_days(os_active.get("active_dd_duration_days")))
                    metric_card("Net bps/trade", _fmt_bps(os_bps_simple))
                    metric_card("bps (notional-w)", _fmt_bps(os_bps_w))
                    metric_card("Trades", _fmt_int(os_metrics.get("total_trades")))
                    metric_card("Win rate", _fmt_pct(os_metrics.get("win_rate")))
                    metric_card("Profit factor", _fmt_num(os_metrics.get("profit_factor")))

            with ui.row().classes("gap-2"):
                metric_card("Members", str(manifest.get("n_members", 0)))
                metric_card("Mean gross", _fmt_num(manifest.get("mean_row_l1")))
                metric_card("Max gross", _fmt_num(manifest.get("max_row_l1")))
                if manifest.get("n_rows_clipped"):
                    metric_card(
                        "Rows clipped",
                        f"{int(manifest['n_rows_clipped']):,}",
                    )

            archive_root = run_dir
            mn = manifest_path.stat().st_mtime_ns if manifest_path.exists() else 0
            method = (manifest.get("method") or "").lower()
            with ui.row().classes("w-full justify-end"):
                mode_toggle = ui.toggle(
                    {"compound": "Compound", "simple": "Simple"},
                    value="compound",
                ).props("dense")
            cumret_compound = ui.plotly(
                _composite_cumret_cached(str(composite_dir), mn, "compound")
            ).classes("w-full dense-panel")
            cumret_simple = ui.plotly(
                _composite_cumret_cached(str(composite_dir), mn, "simple")
            ).classes("w-full dense-panel")
            cumret_simple.set_visibility(False)

            def _on_mode_change(e):
                is_compound = (e.value == "compound")
                cumret_compound.set_visibility(is_compound)
                cumret_simple.set_visibility(not is_compound)

            mode_toggle.on_value_change(_on_mode_change)

            if (composite_dir / "member_gross_daily.parquet").exists():
                ui.plotly(composite_member_summary_figure(composite_dir)).classes("w-full dense-panel")

            if method.startswith("equal_weight"):
                n = int(manifest.get("n_members", 0)) or 1
                with ui.card().classes("dense-panel"):
                    ui.label(
                        f"Equal-weight composite — each of {n} members holds "
                        f"{1.0/n:.4f} share (1/N), constant over time."
                    ).classes("note-text")

            members_csv = composite_dir / "members.csv"
            if members_csv.exists():
                members_df = pd.read_csv(members_csv).sort_values("is_sharpe", ascending=False, na_position="last")
                rows = []
                for _, m in members_df.iterrows():
                    rows.append(
                        {
                            "alpha_id": str(m["alpha_id"]),
                            "run": str(m["run"]),
                            "is_sharpe_fmt": _fmt_sharpe_daily(m.get("is_sharpe")),
                            "is_total_return_fmt": _fmt_pct(m.get("is_total_return")),
                            "is_total_trades_fmt": _fmt_int(m.get("is_total_trades")),
                            "is_gross_mean_fmt": _fmt_num(m.get("is_gross_mean")),
                        }
                    )
                ui.label(f"Members ({len(rows)})").classes("section-title")
                t = ui.table(
                    columns=[
                        {"name": "alpha_id", "label": "alpha_id", "field": "alpha_id", "align": "left"},
                        {"name": "run", "label": "run", "field": "run", "align": "left"},
                        {"name": "is_sharpe_fmt", "label": "IS Sh", "field": "is_sharpe_fmt", "align": "right"},
                        {"name": "is_total_return_fmt", "label": "IS ret", "field": "is_total_return_fmt", "align": "right"},
                        {"name": "is_total_trades_fmt", "label": "IS tr", "field": "is_total_trades_fmt", "align": "right"},
                        {"name": "is_gross_mean_fmt", "label": "mean gross", "field": "is_gross_mean_fmt", "align": "right"},
                    ],
                    rows=rows,
                    row_key="alpha_id",
                    pagination=25,
                ).classes("w-full dense-panel")
                t.on(
                    "rowClick",
                    lambda e: ui.navigate.to(f"/alpha/{e.args[1]['run']}/{e.args[1]['alpha_id']}"),
                )
            render_footer(run_dir)

    ui.run(
        host=args.host,
        port=args.port,
        title="JW Capital",
        reload=False,
    )


if __name__ == "__main__":
    main()
