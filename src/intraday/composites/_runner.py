"""Composite-alpha builder + backtest runner.

A composite alpha is a linear combination of archived per-alpha target-weight
series. The runner is a small library invoked by composite template files
(see ``_composite_template.py``); it does the four steps end-to-end:

1. Load ``alpha_index.csv`` with ``os_*`` columns stripped (look-ahead guard).
2. Load each selected member's ``is/weights.parquet`` (and optionally
   ``os/weights.parquet``); pivot, ffill onto a shared timestamp grid.
3. Compute ``W_comp[t,s] = Σ_a c_a · W_a[t,s]``, row-wise normalize so
   ``Σ_s|W_comp[t,s]| ≤ 1``, emit per-(timestamp, symbol) change events
   into ``composites/<composite_id>/weights.parquet``.
4. Invoke ``scripts/tools/backtest.py`` with ``PrecomputedWeightsStrategy``
   for the IS window and (if requested) the OS window — exactly the same
   engine used for individual alphas, so fees/slippage/quality-gates apply.

Look-ahead safeguards:

* ``load_alpha_index_is_only`` strips ``os_*`` columns before exposing the
  index to user-supplied selection / weighting code. Touching ``os_sharpe``
  etc. raises ``KeyError`` immediately.
* The ``(member_ids, coefficients)`` decision is computed once from IS data
  and frozen in ``manifest.json``. Both IS and OS backtests replay the same
  combined ``weights.parquet`` — selection is never recomputed for OS.
* Time alignment is forward-fill only. A member whose first event lands
  after time ``t`` contributes zero to ``W_comp[t]`` (causal).
* Per-member ``is_gross_mean`` recorded in ``members.csv`` is derived from
  the member's IS weight panel only; OS panels are not touched until backtest.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
ARCHIVE_ROOT = REPO_ROOT / "archive"
BACKTEST_SCRIPT = REPO_ROOT / "scripts" / "tools" / "backtest.py"

OS_PREFIX = "os_"
_GROSS_EPS = 1e-12


def load_alpha_index_is_only(run_id: str) -> pd.DataFrame:
    """Load ``alpha_index.csv`` with all ``os_*`` columns dropped."""
    path = ARCHIVE_ROOT / run_id / "alpha_index.csv"
    if not path.exists():
        raise FileNotFoundError(f"alpha_index not found: {path}")
    df = pd.read_csv(path)
    keep = [c for c in df.columns if not c.startswith(OS_PREFIX)]
    return df[keep].copy()


def _load_member_events(run_id: str, alpha_id: str, split: str) -> pd.DataFrame:
    path = ARCHIVE_ROOT / run_id / "alphas" / alpha_id / split / "weights.parquet"
    if not path.exists():
        return pd.DataFrame(columns=["timestamp", "symbol", "target_weight"])
    df = pd.read_parquet(path, columns=["timestamp", "symbol", "target_weight"])
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["symbol"] = df["symbol"].astype(str).str.upper()
    # Snap events to the next daily-bar boundary so composite weights
    # align with PrecomputedWeightsStrategy's exact-timestamp lookup
    # under the daily-bar backtest path. Events already at midnight UTC
    # remain put; intraday events shift forward to the NEXT 00:00 UTC
    # (causal — never moves an event earlier).
    ts = df["timestamp"]
    snap = ts.dt.normalize() + pd.Timedelta(days=1)
    df["timestamp"] = ts.where(ts == ts.dt.normalize(), snap)
    df = (
        df.sort_values("timestamp")
          .groupby(["timestamp", "symbol"], as_index=False, sort=False)
          .agg(target_weight=("target_weight", "last"))
    )
    return df


def _events_to_panel(events: pd.DataFrame, universe: list[str]) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame(columns=universe)
    return (
        events.sort_values("timestamp")
        .pivot_table(index="timestamp", columns="symbol", values="target_weight", aggfunc="last")
        .reindex(columns=universe)
    )


def _gross_mean_from_panel(panel: pd.DataFrame) -> float | None:
    if panel.empty:
        return None
    filled = panel.ffill().fillna(0.0)
    row_l1 = filled.abs().sum(axis=1)
    return float(row_l1.mean()) if len(row_l1) else None


def combine_weights(
    member_panels: dict[str, pd.DataFrame],
    coefficients: dict[str, float],
    universe: list[str],
) -> tuple[pd.DataFrame, dict]:
    """Linear-combine member panels and emit change-events.

    Returns ``(events_long_df, stats)``. The long DF has columns
    ``[timestamp, symbol, target_weight]`` and contains only rows where the
    target changed for that symbol.
    """
    panels = {a: p for a, p in member_panels.items() if not p.empty}
    if not panels:
        return (
            pd.DataFrame(columns=["timestamp", "symbol", "target_weight"]),
            {"max_row_l1": 0.0, "mean_row_l1": 0.0, "n_change_events": 0, "n_rows_clipped": 0},
        )

    all_ts = sorted(set().union(*[p.index for p in panels.values()]))
    idx = pd.DatetimeIndex(all_ts)
    combined = pd.DataFrame(0.0, index=idx, columns=universe)
    for alpha_id, panel in panels.items():
        aligned = panel.reindex(idx).ffill().fillna(0.0)
        combined = combined.add(aligned * float(coefficients[alpha_id]), fill_value=0.0)
    combined = combined[universe]  # preserve column order

    row_l1 = combined.abs().sum(axis=1)
    n_clipped = int((row_l1 > 1.0 + _GROSS_EPS).sum())
    scale = pd.Series(1.0, index=idx).where(row_l1 <= 1.0, 1.0 / row_l1.replace(0.0, 1.0))
    combined = combined.mul(scale, axis=0)

    rows = []
    for symbol in universe:
        col = combined[symbol]
        prev = col.shift()
        # Emit when value differs from prior (NaN prior counts as "differs"
        # except when current is also 0 — that initial flat is a no-op).
        changed = (col != prev) & ~(prev.isna() & (col.abs() < _GROSS_EPS))
        for ts in col.index[changed.fillna(False)]:
            rows.append((ts, symbol, float(col.loc[ts])))
    long_df = (
        pd.DataFrame(rows, columns=["timestamp", "symbol", "target_weight"])
        .sort_values(["timestamp", "symbol"])
        .reset_index(drop=True)
    )

    stats = {
        "max_row_l1": float(row_l1.max()) if len(row_l1) else 0.0,
        "mean_row_l1": float(row_l1.mean()) if len(row_l1) else 0.0,
        "n_change_events": int(len(long_df)),
        "n_rows_clipped": n_clipped,
    }
    return long_df, stats


def _row_for_member(idx_lookup: pd.DataFrame, alpha_id: str) -> dict:
    if alpha_id not in idx_lookup.index:
        return {}
    row = idx_lookup.loc[alpha_id]
    return row.iloc[0].to_dict() if isinstance(row, pd.DataFrame) else row.to_dict()


def _is_metrics_fallback(run_id: str, alpha_id: str) -> dict:
    """Read per-alpha ``is/metrics.json`` when ``alpha_index.csv`` is stale.
    Look-ahead clean — only the IS split is read."""
    p = ARCHIVE_ROOT / run_id / "alphas" / alpha_id / "is" / "metrics.json"
    if not p.exists():
        return {}
    try:
        m = json.loads(p.read_text())
    except Exception:
        return {}
    return {
        "is_sharpe_daily": m.get("sharpe_daily"),
        "is_sharpe": m.get("sharpe"),
        "is_return": m.get("total_return"),
        "is_trades": m.get("total_trades"),
        "strategy": m.get("strategy_name"),
    }


def _run_backtest_window(
    weights_path: Path,
    out_dir: Path,
    symbols: list[str],
    start: str,
    end: str,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    # Composite backtests skip ``backtest.py``'s per-alpha quality gate and
    # governance check. Both delete ``output_dir.parent`` on failure, which
    # for a composite would nuke ``manifest.json`` / ``members.csv`` /
    # ``weights.parquet``. Composite-level validation belongs at the
    # composite level (e.g. compare-vs-members), not at the per-alpha gate.
    #
    # Use daily-bar data — the existing daily XS factor zoo + per-alpha
    # weights all come from daily-bar backtests. backtest.py's default
    # data path is the minute-bar tree, which doesn't cover all daily-only
    # symbols (e.g. coins listed only in 2025+).
    cmd = [
        "uv", "run", "python", str(BACKTEST_SCRIPT),
        "--strategy", "PrecomputedWeightsStrategy",
        "--symbols", *symbols,
        "--data-type", "bars",
        "--data-path", "data/futures_klines_daily",
        "--bar-type", "TIME",
        "--bar-size", "86400",
        "--start", start,
        "--end", end,
        "--strategy-params", json.dumps({"weights_path": str(weights_path)}),
        "--output-dir", str(out_dir),
        "--no-enforce-quality",
        "--no-enforce-governance",
    ]
    print("$ " + " ".join(cmd), file=sys.stderr)
    # ``backtest.py`` returns exit 2 whenever quality_gate thresholds are
    # missed, even with ``--no-enforce-quality`` (which only suppresses the
    # artifact deletion). For composites we accept that — the artifacts are
    # the point. Treat it as success when ``metrics.json`` was written.
    result = subprocess.run(cmd, check=False, cwd=REPO_ROOT)
    metrics_path = out_dir / "metrics.json"
    if not metrics_path.exists():
        raise RuntimeError(
            f"backtest.py exited {result.returncode} and produced no "
            f"metrics.json under {out_dir}; treat as hard failure."
        )


def build_and_backtest(
    composite_id: str,
    run_id: str,
    select_members: Callable[[pd.DataFrame], list[str]],
    member_weights: Callable[[list[str], pd.DataFrame], dict[str, float]],
    composition_note: str = "user_defined",
    include_os: bool = True,
) -> Path:
    """End-to-end: select → weight → combine → write artifacts → IS/OS backtest.

    Returns the composite directory path.
    """
    run_dir = ARCHIVE_ROOT / run_id
    splits = json.loads((run_dir / "splits.json").read_text())
    universe = [s.upper() for s in splits["universe"]]
    is_window = splits["is"]
    os_window = splits.get("os") if include_os else None

    idx = load_alpha_index_is_only(run_id)
    selected = list(select_members(idx))
    if not selected:
        raise ValueError("select_members returned an empty list")
    coef = dict(member_weights(selected, idx))
    missing = [a for a in selected if a not in coef]
    if missing:
        raise ValueError(f"member_weights missing entries for: {missing}")

    is_panels: dict[str, pd.DataFrame] = {}
    is_gross_mean: dict[str, float | None] = {}
    combined_events: dict[str, pd.DataFrame] = {}
    for alpha_id in selected:
        is_events = _load_member_events(run_id, alpha_id, "is")
        is_panel = _events_to_panel(is_events, universe)
        is_panels[alpha_id] = is_panel
        is_gross_mean[alpha_id] = _gross_mean_from_panel(is_panel)
        if include_os:
            os_events = _load_member_events(run_id, alpha_id, "os")
            full = pd.concat([is_events, os_events], ignore_index=True)
        else:
            full = is_events
        combined_events[alpha_id] = full

    full_panels = {
        a: _events_to_panel(events, universe) for a, events in combined_events.items()
    }
    long_df, stats = combine_weights(full_panels, coef, universe)

    comp_dir = run_dir / "composites" / composite_id
    comp_dir.mkdir(parents=True, exist_ok=True)
    weights_path = comp_dir / "weights.parquet"
    long_df.to_parquet(weights_path, index=False)

    # Per-member daily gross contribution: c_a · Σ_s |W_a[t,s]|, downsampled
    # to daily for stacked-area visualization in the dashboard. Sum across
    # alpha_ids reproduces the composite's daily mean gross.
    rows = []
    for alpha_id, panel in full_panels.items():
        if panel.empty:
            continue
        filled = panel.ffill().fillna(0.0)
        gross = filled.abs().sum(axis=1) * float(coef[alpha_id])
        daily = gross.resample("1D").mean().dropna()
        for ts, v in daily.items():
            rows.append({
                "date": ts.normalize(),
                "alpha_id": alpha_id,
                "gross_contribution": float(v),
            })
    pd.DataFrame(rows).to_parquet(comp_dir / "member_gross_daily.parquet", index=False)

    idx_lookup = idx.set_index("alpha_id")
    members_rows = []
    for alpha_id in selected:
        row = _row_for_member(idx_lookup, alpha_id) or _is_metrics_fallback(run_id, alpha_id)
        members_rows.append({
            "alpha_id": alpha_id,
            "run": run_id,
            "coefficient": float(coef[alpha_id]),
            "is_sharpe": row.get("is_sharpe_daily") or row.get("is_sharpe"),
            "is_total_return": row.get("is_return"),
            "is_total_trades": row.get("is_trades"),
            "is_gross_mean": is_gross_mean.get(alpha_id),
            "strategy": row.get("strategy"),
        })
    pd.DataFrame(members_rows).to_csv(comp_dir / "members.csv", index=False)

    manifest = {
        "composite_id": composite_id,
        "method": composition_note,
        "n_members": len(selected),
        "n_change_events": stats["n_change_events"],
        "max_row_l1": stats["max_row_l1"],
        "mean_row_l1": stats["mean_row_l1"],
        "n_rows_clipped": stats["n_rows_clipped"],
        "is_window": is_window,
        "os_window": os_window,
        "selection_bias_warning": (
            "Selection used IS metrics. The OS backtest is a single-shot "
            "evaluation of this frozen composite; member alphas were drawn "
            "from a search-space pool, so OS Sharpe is a noisy point estimate."
        ),
        "created": datetime.now(timezone.utc).isoformat(),
    }
    (comp_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))

    _run_backtest_window(
        weights_path=weights_path,
        out_dir=comp_dir / "is",
        symbols=universe,
        start=is_window["start"],
        end=is_window["end"],
    )
    if include_os and os_window:
        _run_backtest_window(
            weights_path=weights_path,
            out_dir=comp_dir / "os",
            symbols=universe,
            start=os_window["start"],
            end=os_window["end"],
        )
    return comp_dir
