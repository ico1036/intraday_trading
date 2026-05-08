#!/usr/bin/env python3
"""NiceGUI dashboard for archived alpha artifacts.

Pure logic (formatters, IS_PASS gate, drawdown / net-bps / turnover compute,
downsamplers) lives in ``alpha_dashboard_lib`` so it can be unit-tested
without a NiceGUI / Plotly runtime. This module wires those primitives to
file I/O caches, builds Plotly figures, and renders NiceGUI pages.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

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
    compute_drawdown_metrics,
    compute_net_pnl_bps,
    compute_turnover,
)


DEFAULT_RUN_DIR = Path("archive")
MAX_LINE_POINTS = 2000
# Members in the composite "hairball" chart are faded grey overlays — full
# 2000-point resolution is wasted there. Drop to 250pt to cut JSON payload
# (16 MB → ~2 MB) and browser render time.
MEMBER_TRACE_POINTS = 250
METRIC_COLUMNS = [
    "run_id",
    "alpha_id",
    "status",
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
    ("status", "status", "left"),
    ("is_sharpe_fmt", "IS NetSh", "right"),
    ("is_return_fmt", "IS ret", "right"),
    ("is_max_dd_fmt", "IS DD", "right"),
    ("is_pnl_bps_fmt", "IS bps", "right"),
    ("is_trades", "IS tr", "right"),
    ("os_sharpe_fmt", "OS NetSh", "right"),
    ("os_return_fmt", "OS ret", "right"),
    ("os_max_dd_fmt", "OS DD", "right"),
    ("os_pnl_bps_fmt", "OS bps", "right"),
    ("os_trades", "OS tr", "right"),
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
            m = ad / "is" / "metrics.json"
            if m.exists():
                sig.append([r.name, ad.name, m.stat().st_mtime_ns])
    return sig


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
            is_m = read_json(alpha_d / "is" / "metrics.json")
            os_m = read_json(alpha_d / "os" / "metrics.json")

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

            # Cold-start optimisation: max_drawdown is already in metrics.json
            # (engine writes it from the same equity curve we'd reload). DD
            # duration is only used on the detail page → compute lazily there.
            # Per-trade bps requires reading trades.parquet, so only do it for
            # IS_PASS alphas (the rest will display "-" in the bps column).
            is_dd = is_m.get("max_drawdown") if is_m else None
            is_dd_dur = None
            if is_pass:
                is_bps_simple, is_bps_w, _ = net_pnl_per_trade_bps(r, alpha_d.name, "is")
            else:
                is_bps_simple = is_bps_w = None
            os_bps_simple = os_bps_w = os_dd = os_dd_dur = None

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
                }
            )
    if not rows:
        result = pd.DataFrame(
            columns=["run_id", "alpha_id", "status", "is_sharpe", "is_return", "is_trades", "os_sharpe", "os_return", "os_trades", "flags"]
        )
    else:
        result = pd.DataFrame(rows)
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
    """Downsampled (timestamp, cumret, drawdown) for chart rendering only.

    Returns ~max_points rows so 487 alphas × ~32 KB each ≈ 15 MB cap. The full
    equity_curve.parquet (~10 MB each) is read once, downsampled, and freed.
    """
    p = Path(equity_path)
    if not p.exists():
        return pd.DataFrame(columns=["timestamp", "cumret", "drawdown"])
    df = pd.read_parquet(p, columns=["timestamp", "equity"])
    if df.empty:
        return pd.DataFrame(columns=["timestamp", "cumret", "drawdown"])
    df = _lib_downsample_frame(df, max_points=max_points)
    eq = df["equity"].astype(float)
    base = float(eq.iloc[0]) if eq.iloc[0] != 0 else 1.0
    return pd.DataFrame(
        {
            "timestamp": df["timestamp"].values,
            "cumret": (eq / base - 1.0).values,
            "drawdown": (eq / eq.cummax() - 1.0).values,
        }
    )


def _x(values: pd.Series) -> list[str]:
    return pd.to_datetime(values).astype(str).tolist()


def _downsample_frame(df: pd.DataFrame, max_points: int = MAX_LINE_POINTS) -> pd.DataFrame:
    return _lib_downsample_frame(df, max_points=max_points)


def equity_figure(run_dir: Path, alpha_id: str) -> go.Figure:
    fig = go.Figure()
    for split, color in (("is", "#2563eb"), ("os", "#dc2626")):
        df = _equity_chart_series_cached(
            str(alpha_dir(run_dir, alpha_id) / split / "equity_curve.parquet")
        )
        if df.empty:
            continue
        fig.add_trace(
            go.Scatter(
                x=_x(df["timestamp"]),
                y=df["cumret"],
                mode="lines",
                name=split.upper(),
                line={"color": color, "width": 1.5},
                hovertemplate="%{x}<br>%{y:.2%}<extra>%{fullData.name}</extra>",
            )
        )
    fig.update_layout(
        height=285,
        margin=dict(l=35, r=20, t=35, b=25),
        title="Net cumulative return (after fees)",
        legend=dict(orientation="h"),
    )
    fig.update_yaxes(tickformat=".1%")
    return fig


def drawdown_figure(run_dir: Path, alpha_id: str) -> go.Figure:
    fig = go.Figure()
    for split, color in (("is", "#2563eb"), ("os", "#dc2626")):
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
    fig.update_layout(height=250, margin=dict(l=35, r=20, t=35, b=25), title="Drawdown")
    fig.update_yaxes(tickformat=".1%")
    return fig


def _weight_pivot(run_dir: Path, alpha_id: str, split: str) -> pd.DataFrame:
    df = read_parquet(alpha_dir(run_dir, alpha_id) / split / "weights.parquet")
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


def hourly_weight_stack_figure(run_dir: Path, alpha_id: str, split: str = "os") -> go.Figure:
    fig = go.Figure()
    pivot = _weight_pivot(run_dir, alpha_id, split)
    if not pivot.empty:
        equity = read_parquet(alpha_dir(run_dir, alpha_id) / split / "equity_curve.parquet")
        if not equity.empty:
            start = pd.to_datetime(equity["timestamp"]).min()
            end = pd.to_datetime(equity["timestamp"]).max()
            minute_index = pd.date_range(start=start, end=end, freq="1min")
            timeline = (
                pivot.reindex(pivot.index.union(minute_index))
                .sort_index()
                .ffill()
                .reindex(minute_index)
                .fillna(0.0)
            )
            hourly = timeline.resample("1h").mean()
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
    fig.update_layout(
        height=300,
        margin=dict(l=35, r=20, t=35, b=25),
        title=f"{split.upper()} Hourly Weight Distribution",
        legend=dict(orientation="h"),
    )
    fig.update_yaxes(tickformat=".0%")
    return fig


def weights_figure(run_dir: Path, alpha_id: str, split: str = "os") -> go.Figure:
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
    fig.update_layout(height=300, margin=dict(l=35, r=20, t=35, b=25), title=f"{split.upper()} Target Weights")
    return fig


def metric_card(label: str, value: str):
    with ui.card().classes("metric-card"):
        ui.label(label).classes("metric-label")
        ui.label(value).classes("metric-value")


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


def add_styles() -> None:
    ui.add_head_html(
        """
        <style>
        body { background: #f8fafc; color: #0f172a; }
        .page-wrap { max-width: 1500px; margin: 0 auto; padding: 14px; }
        .metric-card { min-width: 145px; padding: 10px 12px; border-radius: 6px; }
        .metric-label { color: #64748b; font-size: 12px; }
        .metric-value { font-size: 20px; font-weight: 650; color: #0f172a; }
        .section-title { font-size: 16px; font-weight: 650; color: #111827; }
        .q-table th { font-size: 11px; color: #475569; font-weight: 650; }
        .q-table td { font-size: 12px; white-space: nowrap; }
        .q-table tbody tr { cursor: pointer; }
        .q-table tbody tr:hover { background: #eef2ff; }
        .dense-panel { background: white; border: 1px solid #e2e8f0; border-radius: 6px; padding: 12px; }
        .mini-card { border-radius: 6px; padding: 10px 12px; box-shadow: none; border: 1px solid #e5e7eb; }
        .mini-value { color: #0f172a; font-size: 13px; font-weight: 650; }
        .validation-table .q-table__top,
        .validation-table .q-table__bottom { display: none; }
        .validation-table .q-table td { height: 30px; padding: 4px 8px; }
        .validation-table .q-table th { height: 28px; padding: 4px 8px; }
        .path-text { color: #64748b; font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
        .note-text { color: #475569; font-size: 12px; line-height: 1.45; }
        </style>
        """
    )


def display_rows(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows = []
    cols = [col for col in METRIC_COLUMNS if col in df.columns]
    for raw in df[cols].to_dict("records"):
        row = dict(raw)
        row["os_return_fmt"] = _fmt_pct(raw.get("os_return"))
        row["is_return_fmt"] = _fmt_pct(raw.get("is_return"))
        row["os_sharpe_fmt"] = _fmt_num(raw.get("os_sharpe"))
        row["is_sharpe_fmt"] = _fmt_num(raw.get("is_sharpe"))
        row["os_trades"] = _fmt_int(raw.get("os_trades"))
        row["is_trades"] = _fmt_int(raw.get("is_trades"))
        row["is_max_dd_fmt"] = _fmt_pct(raw.get("is_max_dd"))
        row["os_max_dd_fmt"] = _fmt_pct(raw.get("os_max_dd"))
        row["is_pnl_bps_fmt"] = _fmt_bps(raw.get("is_pnl_bps"))
        row["os_pnl_bps_fmt"] = _fmt_bps(raw.get("os_pnl_bps"))
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
COMPOSITE_BOLD_COLOR = "#1f3a8a"


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
                "selection_warning": manifest.get("selection_bias_warning"),
            }
        )
    return out


def _series_downsample(s: pd.Series, max_points: int = MAX_LINE_POINTS) -> pd.Series:
    return _lib_series_downsample(s, max_points=max_points)


@lru_cache(maxsize=512)
def _member_cumret(equity_path: str) -> pd.Series:
    p = Path(equity_path)
    if not p.exists():
        return pd.Series(dtype=float)
    df = pd.read_parquet(p)
    if df.empty:
        return pd.Series(dtype=float)
    # Downsample BEFORE pd.to_datetime: converting 453K timestamp strings is
    # the dominant cost (~35 ms per member), and the chart layer immediately
    # downsamples to MAX_LINE_POINTS anyway. Strided iloc keeps endpoints.
    n = len(df)
    if n > MAX_LINE_POINTS:
        stride = max(1, n // MAX_LINE_POINTS)
        df = df.iloc[::stride]
    s = df.set_index("timestamp")["equity"].astype(float)
    s.index = pd.to_datetime(s.index)
    if s.empty or s.iloc[0] == 0:
        return pd.Series(dtype=float)
    return s / s.iloc[0] - 1.0


@lru_cache(maxsize=64)
def _composite_cumret_cached(
    composite_dir_str: str, manifest_mtime_ns: int
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
    cache_path = Path("/tmp") / f"alpha_dashboard_cumret_{h}_{manifest_mtime_ns}.pkl"
    if cache_path.exists():
        try:
            with cache_path.open("rb") as f:
                d = pickle.load(f)
            return go.Figure(data=d.get("data", []), layout=d.get("layout", {}), skip_invalid=True)
        except Exception:
            pass  # fall through and rebuild
    fig = composite_cumret_figure(composite_dir, archive_root)
    try:
        with cache_path.open("wb") as f:
            pickle.dump(fig.to_dict(), f, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:
        pass  # opportunistic
    return fig


def composite_cumret_figure(composite_dir: Path, archive_root: Path) -> go.Figure:
    fig = go.Figure()
    members_csv = composite_dir / "members.csv"
    members = pd.read_csv(members_csv) if members_csv.exists() else pd.DataFrame()
    member_paths = [
        str(
            archive_root
            / str(m["run"])
            / "alphas"
            / str(m["alpha_id"])
            / "is"
            / "equity_curve.parquet"
        )
        for _, m in members.iterrows()
    ]
    # Parquet read releases the GIL inside pyarrow, so threads parallelise
    # the IO-bound fan-out. Each call still flows through _member_cumret's
    # lru_cache, so warm hits remain free.
    if member_paths:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=8) as pool:
            series_list = list(pool.map(_member_cumret, member_paths))
    else:
        series_list = []
    # Pack all member curves into ONE trace separated by None gaps. Plotly
    # draws them as visually distinct line segments with a single trace's
    # JSON overhead instead of 234. Note: numpy datetime64("NaT") cannot be
    # used as a separator — it serialises to its int64 epoch (1677-09-21)
    # and stretches the X axis 350+ years. Plain Python None gives the
    # correct gap behaviour.
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
    if xs:
        fig.add_trace(
            go.Scattergl(
                x=xs,
                y=ys,
                mode="lines",
                line=dict(color=COMPOSITE_MEMBER_LINE_COLOR, width=1),
                name="members",
                showlegend=False,
                hoverinfo="skip",
            )
        )
    comp_ec_path = composite_dir / "is" / "equity_curve.parquet"
    if comp_ec_path.exists():
        s = _member_cumret(str(comp_ec_path))
        if not s.empty:
            s = _series_downsample(s)
            fig.add_trace(
                go.Scatter(
                    x=s.index.astype(str),
                    y=s.values,
                    mode="lines",
                    line=dict(color=COMPOSITE_BOLD_COLOR, width=3),
                    name="Composite",
                    hovertemplate="composite<br>%{x}<br>%{y:.2%}<extra></extra>",
                )
            )
    fig.update_layout(
        title="Cumulative return — composite (bold) vs members (faded)",
        height=420,
        margin=dict(l=40, r=20, t=50, b=40),
        xaxis_title="time",
        yaxis_title="cum return",
        showlegend=False,
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
        df = load_index(run_dir)
        state = {"df": df, "search_text": build_search_text(run_dir, df)}
        add_styles()
        composites = discover_composites(run_dir)
        with ui.column().classes("page-wrap w-full gap-3"):
            ui.label("Alpha Archive Dashboard").classes("text-xl font-semibold")
            ui.label(str(run_dir)).classes("text-xs text-gray-500")

            with ui.tabs().classes("w-full") as top_tabs:
                tab_alphas = ui.tab("Alphas")
                tab_composites = ui.tab(f"Composites ({len(composites)})")
            with ui.tab_panels(top_tabs, value=tab_alphas).classes("w-full"):
                with ui.tab_panel(tab_alphas):
                    df = state["df"]
                    with ui.row().classes("w-full gap-2"):
                        metric_card("Alphas", str(len(df)))
                        metric_card("IS_PASS", str((df["status"] == "IS_PASS").sum()))

                    with ui.row().classes("w-full items-end gap-3"):
                        search_input = ui.input("Search").props("clearable dense").classes("w-96")
                        status_values = sorted(str(v) for v in df["status"].dropna().unique().tolist())
                        status_filter = ui.select(status_values, multiple=True, label="Status").classes("w-48")
                        sort_select = ui.select(
                            [
                                "is_sharpe", "is_return", "is_max_dd", "is_pnl_bps", "is_trades",
                                "os_sharpe", "os_return", "os_max_dd", "os_pnl_bps", "os_trades",
                            ],
                            value="is_sharpe",
                            label="Sort",
                        ).classes("w-48")
                        min_is_sharpe = ui.number("Min IS Sharpe", value=None, step=0.1).classes("w-40")
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
                            view = view[view["status"].isin(status_filter.value)]
                        if min_is_sharpe.value is not None:
                            is_sharpe = pd.to_numeric(view["is_sharpe"], errors="coerce")
                            view = view[is_sharpe >= float(min_is_sharpe.value)]
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
                            ).classes("w-full dense-panel")
                            table.on(
                                "rowClick",
                                lambda e: ui.navigate.to(f"/alpha/{e.args[1]['run_id']}/{e.args[1]['alpha_id']}"),
                            )
                            table_ref["table"] = table

                    for control in (search_input, status_filter, sort_select, min_is_sharpe, min_trades):
                        control.on_value_change(lambda _: render_table())

                    render_table()

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
                                    "is_sharpe_fmt": _fmt_num(c["is_sharpe"]),
                                    "is_return_fmt": _fmt_pct(c["is_return"]),
                                    "is_drawdown_fmt": _fmt_pct(c["is_drawdown"]),
                                    "is_trades_fmt": _fmt_int(c["is_trades"]),
                                    "is_win_rate_fmt": _fmt_pct(c["is_win_rate"]),
                                    "mean_row_l1_fmt": _fmt_num(c["mean_row_l1"]),
                                }
                            )
                        comp_table = ui.table(
                            columns=[
                                {"name": "composite_id", "label": "composite", "field": "composite_id", "align": "left"},
                                {"name": "method", "label": "method", "field": "method", "align": "left"},
                                {"name": "n_members", "label": "members", "field": "n_members", "align": "right"},
                                {"name": "is_sharpe_fmt", "label": "IS Sh", "field": "is_sharpe_fmt", "align": "right"},
                                {"name": "is_return_fmt", "label": "IS ret", "field": "is_return_fmt", "align": "right"},
                                {"name": "is_drawdown_fmt", "label": "IS dd", "field": "is_drawdown_fmt", "align": "right"},
                                {"name": "is_trades_fmt", "label": "IS tr", "field": "is_trades_fmt", "align": "right"},
                                {"name": "is_win_rate_fmt", "label": "IS win", "field": "is_win_rate_fmt", "align": "right"},
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

    @ui.page("/alpha/{run_id}/{alpha_id}")
    def alpha_page(run_id: str, alpha_id: str):
        add_styles()
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

            ui.label(alpha_id).classes("text-xl font-semibold")
            is_bps_simple, is_bps_w, _ = net_pnl_per_trade_bps(detail_run_dir, alpha_id, "is")
            os_bps_simple, os_bps_w, _ = net_pnl_per_trade_bps(detail_run_dir, alpha_id, "os")
            is_dd_pct, is_dd_dur, is_peak_ts, is_recov_ts = drawdown_metrics(detail_run_dir, alpha_id, "is")
            os_dd_pct, os_dd_dur, os_peak_ts, os_recov_ts = drawdown_metrics(detail_run_dir, alpha_id, "os")

            ui.label("Core 4 metrics — net of fees (1-min backtest)").classes("section-title")
            with ui.row().classes("gap-2 w-full"):
                metric_card("Status", str(selected.get("status", "-")))
                metric_card("IS Net Sharpe", _fmt_num(selected.get("is_sharpe")))
                metric_card("IS Net return", _fmt_pct(selected.get("is_return")))
                metric_card("IS Max DD", _fmt_pct(is_dd_pct))
                metric_card("IS DD duration", _fmt_duration_days(is_dd_dur))
                metric_card("IS Net bps/trade", _fmt_bps(is_bps_simple))
                metric_card("IS bps (notional-w)", _fmt_bps(is_bps_w))
                metric_card("IS Trades", _fmt_int(selected.get("is_trades", 0)))
            with ui.row().classes("gap-2 w-full"):
                metric_card("OS Net Sharpe", _fmt_num(selected.get("os_sharpe")))
                metric_card("OS Net return", _fmt_pct(selected.get("os_return")))
                metric_card("OS Max DD", _fmt_pct(os_dd_pct))
                metric_card("OS DD duration", _fmt_duration_days(os_dd_dur))
                metric_card("OS Net bps/trade", _fmt_bps(os_bps_simple))
                metric_card("OS bps (notional-w)", _fmt_bps(os_bps_w))
                metric_card("OS Trades", _fmt_int(selected.get("os_trades", 0)))
                metric_card("Turnover IS/OS", f"{_fmt_turnover(is_turnover)} / {_fmt_turnover(os_turnover)}")
            with ui.grid(columns=2).classes("w-full gap-3"):
                ui.plotly(equity_figure(detail_run_dir, alpha_id)).classes("w-full dense-panel")
                ui.plotly(drawdown_figure(detail_run_dir, alpha_id)).classes("w-full dense-panel")
                ui.plotly(hourly_weight_stack_figure(detail_run_dir, alpha_id, "is")).classes("w-full dense-panel")
                ui.plotly(weights_figure(detail_run_dir, alpha_id, "is")).classes("w-full dense-panel")
            with ui.tabs().classes("w-full") as tabs:
                tab_params = ui.tab("Params")
                tab_validation = ui.tab("Validation")
            with ui.tab_panels(tabs, value=tab_params).classes("w-full"):
                with ui.tab_panel(tab_params):
                    ui.code(json.dumps(params, indent=2), language="json").classes("w-full")
                with ui.tab_panel(tab_validation):
                    ui.code(json.dumps(validation, indent=2), language="json").classes("w-full")

    @ui.page("/composite/{composite_dir_name}")
    def composite_page(composite_dir_name: str):
        add_styles()
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

            # Compute trade-level net bps + DD duration for the composite
            comp_trades_path = composite_dir / "is" / "trades.parquet"
            comp_eq_path = composite_dir / "is" / "equity_curve.parquet"
            comp_bps_simple, comp_bps_w, _ = _net_trade_metrics_cached(str(comp_trades_path))
            comp_dd_pct, comp_dd_dur, _, _ = _drawdown_metrics_cached(str(comp_eq_path))

            ui.label("Core 4 metrics — net of fees (1-min backtest)").classes("section-title")
            with ui.row().classes("gap-2 w-full"):
                metric_card("Net Sharpe", _fmt_num(metrics.get("sharpe")))
                metric_card("Net return", _fmt_pct(metrics.get("total_return")))
                metric_card("Max DD", _fmt_pct(comp_dd_pct))
                metric_card("DD duration", _fmt_duration_days(comp_dd_dur))
                metric_card("Net bps/trade", _fmt_bps(comp_bps_simple))
                metric_card("bps (notional-w)", _fmt_bps(comp_bps_w))
                metric_card("Trades", _fmt_int(metrics.get("total_trades")))
                metric_card("Win rate", _fmt_pct(metrics.get("win_rate")))
                metric_card("Profit factor", _fmt_num(metrics.get("profit_factor")))
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
            cumret_fig = _composite_cumret_cached(str(composite_dir), mn)
            ui.plotly(cumret_fig).classes("w-full dense-panel")
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
                            "is_sharpe_fmt": _fmt_num(m.get("is_sharpe")),
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

    ui.run(host=args.host, port=args.port, title="Alpha Dashboard", reload=False)


if __name__ == "__main__":
    main()
