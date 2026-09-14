"""Composite-alpha builder + backtest runner.

A composite alpha is a linear combination of archived per-alpha target-weight
series. The runner is a small library invoked by composite modules (see
``_composite_template.py``); it does five things end-to-end:

1. Load ``alpha_index.csv`` with ``os_*`` columns stripped (look-ahead guard).
2. Make sure every selected member's archive is current: same engine, same
   strategy source, same data path, window, universe and cost model as the
   run. A stale member is rerun from its archived ``run_config`` first
   (``rerun_members="auto"``), so member weight files are never something to
   manage by hand.
3. Load each member's ``weights.parquet``, split at the run's IS end, pivot
   and forward-fill onto a shared timestamp grid.
4. Compute ``W_comp[t,s] = Σ_a c_a · W_a[t,s]``, scale each row's gross (clip
   to 1, or scale to ``target_gross``), and emit one row per (timestamp,
   symbol) where the combined target changed or a member rebalanced, so the
   composite turns over when its members do.
5. Freeze the selection in ``manifest.json``, then replay the combined
   weights through ``scripts/tools/backtest.py`` with
   ``PrecomputedWeightsStrategy`` on the run's data path: the same engine,
   fees, slippage, funding and delisting handling as the members.

Look-ahead safeguards:

* ``load_alpha_index_is_only`` strips ``os_*`` columns before exposing the
  index to user-supplied selection / weighting code. Touching ``os_sharpe``
  etc. raises ``KeyError`` immediately.
* The ``(member_ids, coefficients)`` decision is computed once from IS data
  and frozen in ``manifest.json`` before the replay. Both IS and OS replay
  the same combined ``weights.parquet``; selection is never recomputed.
* Time alignment is forward-fill only. A member whose first event lands
  after time ``t`` contributes zero to ``W_comp[t]`` (causal).
* Per-member ``is_gross_mean`` recorded in ``members.csv`` is derived from
  the member's IS rows only.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from intraday.backtest.provenance import (
    COST_DEFAULTS,
    SIZING_FIELDS,
    class_to_module_name,
    engine_fingerprint,
    file_sha256,
    run_config_to_cli,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
ARCHIVE_ROOT = REPO_ROOT / "archive"
BACKTEST_SCRIPT = REPO_ROOT / "scripts" / "tools" / "backtest.py"
STRATEGY_DIR = REPO_ROOT / "src" / "intraday" / "strategies" / "multi"

OS_PREFIX = "os_"
DEFAULT_DATA_PATH = "data/futures_klines_daily"
RERUN_MODES = ("auto", "always", "never")
_GROSS_EPS = 1e-12
_EVENT_COLUMNS = ["timestamp", "symbol", "target_weight"]
_DEFAULT_SIZING: dict[str, Any] = {
    "initial_capital": 10000.0,
    "position_size_pct": 1.0,
    "leverage": 1,
    "maker_fee_rate": 0.0002,
    "taker_fee_rate": 0.0005,
    "fixed_aum_sizing": False,
}


def load_alpha_index_is_only(run_id: str) -> pd.DataFrame:
    """Load ``alpha_index.csv`` with all ``os_*`` columns dropped."""
    path = ARCHIVE_ROOT / run_id / "alpha_index.csv"
    if not path.exists():
        raise FileNotFoundError(f"alpha_index not found: {path}")
    df = pd.read_csv(path)
    keep = [c for c in df.columns if not c.startswith(OS_PREFIX)]
    return df[keep].copy()


# --------------------------------------------------------------------------
# run context
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RunContext:
    """What ``splits.json`` says about a run: where its data lives, which
    symbols have data, and the IS/OS window."""

    run_id: str
    run_dir: Path
    data_path: str
    universe: list[str]
    unavailable: list[str]
    is_window: dict[str, str]
    os_window: dict[str, str] | None
    include_os: bool

    @property
    def start(self) -> str:
        return self.is_window["start"]

    @property
    def is_end(self) -> str:
        return self.is_window["end"]

    @property
    def end(self) -> str:
        """End of the run's full window; members are always archived to here."""
        return (self.os_window or self.is_window)["end"]

    @property
    def replay_end(self) -> str:
        return self.end if self.include_os and self.os_window else self.is_end


def load_run_context(run_id: str, include_os: bool = True) -> RunContext:
    run_dir = ARCHIVE_ROOT / run_id
    splits = json.loads((run_dir / "splits.json").read_text())
    data_path = str(splits.get("data_path") or DEFAULT_DATA_PATH)
    requested = [s.upper() for s in splits["universe"]]
    root = REPO_ROOT / data_path
    universe = [s for s in requested if (root / s).exists()] if root.is_dir() else requested
    available = set(universe)
    return RunContext(
        run_id=run_id,
        run_dir=run_dir,
        data_path=data_path,
        universe=universe,
        unavailable=[s for s in requested if s not in available],
        is_window=splits["is"],
        os_window=splits.get("os"),
        include_os=include_os,
    )


# --------------------------------------------------------------------------
# member archives
# --------------------------------------------------------------------------


def _member_dir(run_id: str, alpha_id: str) -> Path:
    return ARCHIVE_ROOT / run_id / "alphas" / alpha_id


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _read_events(path: Path) -> pd.DataFrame:
    df = pd.read_parquet(path, columns=_EVENT_COLUMNS).copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["symbol"] = df["symbol"].astype(str).str.upper()
    return df


def _load_member_events(run_id: str, alpha_id: str, split: str, is_end: str) -> pd.DataFrame:
    """One split of a member's weight events.

    Current archives hold one ``weights.parquet`` for the whole run, split
    here at the IS end; older archives hold ``is/`` and ``os/`` files.
    """
    member = _member_dir(run_id, alpha_id)
    legacy = member / split / "weights.parquet"
    empty = pd.DataFrame(columns=_EVENT_COLUMNS)
    if legacy.exists():
        df = _read_events(legacy)
    elif (member / "weights.parquet").exists():
        df = _read_events(member / "weights.parquet")
        cutoff = pd.Timestamp(is_end)
        df = df[df["timestamp"] <= cutoff] if split == "is" else df[df["timestamp"] > cutoff]
    else:
        return empty
    if df.empty:
        return empty
    # Snap events to the next daily-bar boundary so composite weights align
    # with PrecomputedWeightsStrategy's exact-timestamp lookup. Events at
    # midnight UTC stay put; intraday events move forward to the next 00:00
    # (causal, never earlier).
    ts = df["timestamp"]
    snap = ts.dt.normalize() + pd.Timedelta(days=1)
    df = df.assign(timestamp=ts.where(ts == ts.dt.normalize(), snap))
    return (
        df.sort_values("timestamp")
          .groupby(["timestamp", "symbol"], as_index=False, sort=False)
          .agg(target_weight=("target_weight", "last"))
    )


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


def _is_metrics_fallback(run_id: str, alpha_id: str) -> dict:
    """IS metrics straight from the member's archive when ``alpha_index.csv``
    is stale. Look-ahead clean: only the IS block is read."""
    member = _member_dir(run_id, alpha_id)
    metrics = _read_json(member / "metrics.json")
    block = metrics.get("is") if isinstance(metrics.get("is"), dict) else _read_json(member / "is" / "metrics.json")
    if not block:
        return {}
    return {
        "is_sharpe_daily": block.get("sharpe_daily"),
        "is_sharpe": block.get("sharpe"),
        "is_return": block.get("total_return"),
        "is_trades": block.get("total_trades"),
        "strategy": metrics.get("strategy_class") or block.get("strategy_name"),
    }


# --------------------------------------------------------------------------
# member freshness
# --------------------------------------------------------------------------


@dataclass
class MemberStatus:
    """Whether a member's archive was produced under the run's current
    engine, source, data, window and cost model, and if not, why."""

    alpha_id: str
    reasons: list[str]
    rerunnable: bool
    run_config: dict[str, Any]
    generated_at: str | None = None
    strategy_sha: str | None = None
    engine_fingerprint: str | None = None
    rerun: bool = False

    @property
    def fresh(self) -> bool:
        return not self.reasons

    def provenance(self) -> dict[str, Any]:
        return {
            "alpha_id": self.alpha_id,
            "generated_at": self.generated_at,
            "strategy_sha": self.strategy_sha,
            "engine_fingerprint": self.engine_fingerprint,
            "rerun": self.rerun,
            "stale_reasons": list(self.reasons),
        }


def _same_time(a: Any, b: Any) -> bool:
    try:
        return pd.Timestamp(a) == pd.Timestamp(b)
    except (TypeError, ValueError):
        return False


def _working_tree_source(metrics: dict, cfg: dict) -> Path | None:
    """The strategy file the archive was snapshotted from, if it still exists."""
    candidates: list[Path] = []
    if metrics.get("source_original_path"):
        candidates.append(Path(str(metrics["source_original_path"])))
    class_name = cfg.get("strategy") or metrics.get("strategy_class")
    if class_name:
        candidates.append(STRATEGY_DIR / f"{class_to_module_name(str(class_name))}.py")
    for path in candidates:
        if path.exists():
            return path
    return None


def member_status(run_id: str, alpha_id: str, ctx: RunContext, current_fingerprint: str) -> MemberStatus:
    member = _member_dir(run_id, alpha_id)
    metrics = _read_json(member / "metrics.json")
    cfg = metrics.get("run_config") if isinstance(metrics.get("run_config"), dict) else {}
    reasons: list[str] = []
    if not metrics:
        reasons.append("no metrics.json")
    elif not cfg:
        reasons.append("no run_config (archived before provenance was recorded)")

    fingerprint = metrics.get("engine_fingerprint")
    if fingerprint != current_fingerprint:
        reasons.append(f"engine {fingerprint or 'unknown'} != {current_fingerprint}")

    snapshot = member / "strategy_source.py"
    source = _working_tree_source(metrics, cfg)
    snapshot_sha = file_sha256(snapshot) if snapshot.exists() else None
    source_sha = file_sha256(source) if source is not None else None
    if snapshot_sha is None:
        reasons.append("no strategy_source.py snapshot")
    elif source_sha is None:
        reasons.append("strategy source missing from the working tree")
    elif snapshot_sha != source_sha:
        reasons.append("strategy source changed since the archive")

    if cfg:
        if cfg.get("data_path") != ctx.data_path:
            reasons.append(f"data_path {cfg.get('data_path')} != {ctx.data_path}")
        if not (
            _same_time(cfg.get("start"), ctx.start)
            and _same_time(cfg.get("end"), ctx.end)
            and _same_time(cfg.get("is_end"), ctx.is_end)
        ):
            reasons.append("window differs from splits.json")
        for key, default in COST_DEFAULTS.items():
            if cfg.get(key) != default:
                reasons.append(f"{key} {cfg.get(key)!r} != {default!r}")

    symbols = metrics.get("symbols")
    if isinstance(symbols, list) and {str(s).upper() for s in symbols} != set(ctx.universe):
        reasons.append("universe differs from the run's")

    return MemberStatus(
        alpha_id=alpha_id,
        reasons=reasons,
        rerunnable=bool(cfg) and source_sha is not None,
        run_config=cfg,
        generated_at=metrics.get("generated_at"),
        strategy_sha=snapshot_sha,
        engine_fingerprint=fingerprint,
    )


def _rerun_member(status: MemberStatus, ctx: RunContext) -> None:
    """Re-archive one member under the run's data path, window, universe and
    the current cost defaults, keeping its own strategy and sizing."""
    out_dir = _member_dir(ctx.run_id, status.alpha_id)
    overrides = {
        "data_path": ctx.data_path,
        "start": ctx.start,
        "end": ctx.end,
        "is_end": ctx.is_end,
        **COST_DEFAULTS,
    }
    cmd = [
        "uv", "run", "python", str(BACKTEST_SCRIPT),
        *run_config_to_cli(status.run_config, output_dir=out_dir, symbols=ctx.universe, overrides=overrides),
        "--no-enforce-quality",
        "--no-enforce-governance",
        "--json",
    ]
    # The truncation check guards a changed strategy; an unchanged one is a
    # replay and skips it.
    if not any(r.startswith("strategy source changed") for r in status.reasons):
        cmd.append("--no-prefix-check")
    print(f"[composite] rerun {status.alpha_id}: {'; '.join(status.reasons) or 'requested'}", file=sys.stderr)
    result = subprocess.run(cmd, check=False, cwd=REPO_ROOT, stdout=subprocess.DEVNULL)
    if result.returncode not in (0, 2) or not (out_dir / "metrics.json").exists():
        raise RuntimeError(f"member rerun failed for {status.alpha_id} (rc={result.returncode})")


def ensure_members_fresh(member_ids: list[str], ctx: RunContext, mode: str = "auto") -> list[MemberStatus]:
    """Return one status per member, rerunning members as ``mode`` says:
    ``auto`` reruns stale members, ``always`` reruns all, ``never`` combines
    the archives as they are and only reports staleness."""
    if mode not in RERUN_MODES:
        raise ValueError(f"rerun_members must be one of {RERUN_MODES}, got {mode!r}")
    current = engine_fingerprint()
    statuses: list[MemberStatus] = []
    for alpha_id in member_ids:
        status = member_status(ctx.run_id, alpha_id, ctx, current)
        wants_rerun = mode == "always" or (mode == "auto" and not status.fresh)
        if wants_rerun:
            if not status.rerunnable:
                raise RuntimeError(
                    f"{alpha_id} is stale ({'; '.join(status.reasons)}) and cannot be rerun "
                    "from its archive; rerun it through the alpha workflow, or pass "
                    "rerun_members='never' to combine it as archived"
                )
            _rerun_member(status, ctx)
            status = member_status(ctx.run_id, alpha_id, ctx, current)
            if not status.fresh:
                raise RuntimeError(f"{alpha_id} is still stale after rerun: {'; '.join(status.reasons)}")
            status.rerun = True
        elif not status.fresh:
            print(f"[composite] using stale member {alpha_id}: {'; '.join(status.reasons)}", file=sys.stderr)
        statuses.append(status)
    return statuses


def _shared_sizing(statuses: list[MemberStatus]) -> dict[str, Any]:
    """The replay sizes positions the way its members did; members must agree."""
    configs = [s.run_config for s in statuses if s.run_config]
    if not configs:
        return dict(_DEFAULT_SIZING)
    sizing = {k: configs[0].get(k, _DEFAULT_SIZING[k]) for k in SIZING_FIELDS}
    for cfg in configs[1:]:
        other = {k: cfg.get(k, _DEFAULT_SIZING[k]) for k in SIZING_FIELDS}
        if other != sizing:
            raise ValueError(f"members disagree on sizing: {sizing} vs {other}")
    return sizing


# --------------------------------------------------------------------------
# combination
# --------------------------------------------------------------------------


def combine_weights(
    member_panels: dict[str, pd.DataFrame],
    coefficients: dict[str, float],
    universe: list[str],
    target_gross: float | None = None,
) -> tuple[pd.DataFrame, dict]:
    """Linear-combine member panels and emit rebalance events.

    Returns ``(events_long_df, stats)``. A row is emitted for (timestamp,
    symbol) when the combined target changed, or when any member emitted a
    target for that symbol at that timestamp: a member rebalance is a
    composite rebalance, so turnover matches the members. A zero target with
    no position on either side is not emitted.

    ``target_gross=None`` scales down rows whose gross exceeds 1; a number
    scales every non-flat row to exactly that gross.
    """
    stats = {
        "raw_max_row_l1": 0.0, "raw_mean_row_l1": 0.0,
        "max_row_l1": 0.0, "mean_row_l1": 0.0,
        "n_change_events": 0, "n_rows_clipped": 0,
        "target_gross": target_gross,
    }
    panels = {a: p for a, p in member_panels.items() if not p.empty}
    if not panels:
        return pd.DataFrame(columns=_EVENT_COLUMNS), stats

    idx = pd.DatetimeIndex(sorted(set().union(*[p.index for p in panels.values()])))
    combined = pd.DataFrame(0.0, index=idx, columns=universe)
    emitted = pd.DataFrame(False, index=idx, columns=universe)
    for alpha_id, panel in panels.items():
        aligned = panel.reindex(index=idx, columns=universe)
        emitted |= aligned.notna()
        combined += aligned.ffill().fillna(0.0) * float(coefficients[alpha_id])

    raw_l1 = combined.abs().sum(axis=1)
    if target_gross is None:
        n_clipped = int((raw_l1 > 1.0 + _GROSS_EPS).sum())
        scale = pd.Series(1.0, index=idx).where(raw_l1 <= 1.0, 1.0 / raw_l1.replace(0.0, 1.0))
    else:
        n_clipped = int((raw_l1 > float(target_gross) + _GROSS_EPS).sum())
        scale = (float(target_gross) / raw_l1.where(raw_l1 > _GROSS_EPS)).fillna(1.0)
    combined = combined.mul(scale, axis=0)

    prev = combined.shift()
    changed = (combined != prev) & ~(prev.isna() & (combined.abs() < _GROSS_EPS))
    held = (prev.fillna(0.0).abs() > _GROSS_EPS) | (combined.abs() > _GROSS_EPS)
    emit = changed | (emitted & held)
    rows, cols = np.nonzero(emit.to_numpy())
    long_df = (
        pd.DataFrame({
            "timestamp": idx[rows],
            "symbol": np.asarray(universe, dtype=object)[cols],
            "target_weight": combined.to_numpy()[rows, cols].astype(float),
        })
        .sort_values(["timestamp", "symbol"])
        .reset_index(drop=True)
    )

    final_l1 = combined.abs().sum(axis=1)
    stats.update({
        "raw_max_row_l1": float(raw_l1.max()),
        "raw_mean_row_l1": float(raw_l1.mean()),
        "max_row_l1": float(final_l1.max()),
        "mean_row_l1": float(final_l1.mean()),
        "n_change_events": int(len(long_df)),
        "n_rows_clipped": n_clipped,
    })
    return long_df, stats


# --------------------------------------------------------------------------
# replay + pipeline
# --------------------------------------------------------------------------


def _row_for_member(idx_lookup: pd.DataFrame, alpha_id: str) -> dict:
    if alpha_id not in idx_lookup.index:
        return {}
    row = idx_lookup.loc[alpha_id]
    return row.iloc[0].to_dict() if isinstance(row, pd.DataFrame) else row.to_dict()


def _run_backtest_window(
    *,
    weights_path: Path,
    out_dir: Path,
    ctx: RunContext,
    sizing: dict[str, Any],
    target_gross: float | None,
    alpha_id: str,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    # The per-alpha quality gate and governance check delete the artifact
    # dir on failure, which for a composite would take manifest.json and
    # members.csv with it; composite-level validation happens at the
    # composite level. The truncation check is a guard for a changed
    # strategy and means nothing for a replay of a fixed schedule.
    cmd = [
        "uv", "run", "python", str(BACKTEST_SCRIPT),
        "--strategy", "PrecomputedWeightsStrategy",
        "--symbols", *ctx.universe,
        "--data-type", "bars",
        "--data-path", ctx.data_path,
        "--bar-type", "TIME",
        "--bar-size", "86400",
        "--start", ctx.start,
        "--end", ctx.replay_end,
        "--initial-capital", str(sizing["initial_capital"]),
        "--position-size-pct", str(sizing["position_size_pct"]),
        "--leverage", str(sizing["leverage"]),
        "--maker-fee-rate", str(sizing["maker_fee_rate"]),
        "--taker-fee-rate", str(sizing["taker_fee_rate"]),
        "--max-portfolio-weight", str(float(target_gross) if target_gross is not None else 1.0),
        "--strategy-params", json.dumps({"weights_path": str(weights_path), "alpha_id": alpha_id}),
        "--output-dir", str(out_dir),
        "--no-prefix-check",
        "--no-enforce-quality",
        "--no-enforce-governance",
    ]
    if sizing.get("fixed_aum_sizing"):
        cmd.append("--fixed-aum-sizing")
    if ctx.include_os and ctx.os_window:
        cmd.extend(["--is-end", ctx.is_end])
    print(f"[composite] replay {alpha_id} on {ctx.data_path} ({len(ctx.universe)} symbols)", file=sys.stderr)
    # backtest.py exits 2 whenever quality thresholds are missed, even with
    # --no-enforce-quality; for a composite the artifacts are the point.
    result = subprocess.run(cmd, check=False, cwd=REPO_ROOT)
    if not (out_dir / "metrics.json").exists():
        raise RuntimeError(
            f"backtest.py exited {result.returncode} and produced no metrics.json under {out_dir}"
        )


def build_and_backtest(
    composite_id: str,
    run_id: str,
    select_members: Callable[[pd.DataFrame], list[str]],
    member_weights: Callable[[list[str], pd.DataFrame], dict[str, float]],
    composition_note: str = "user_defined",
    include_os: bool = True,
    target_gross: float | None = None,
    rerun_members: str = "auto",
) -> Path:
    """End-to-end: select → weight → refresh members → combine → freeze →
    replay. Returns the composite directory path."""
    ctx = load_run_context(run_id, include_os)
    if ctx.unavailable:
        print(
            f"[composite] {len(ctx.unavailable)} universe symbol(s) have no data under "
            f"{ctx.data_path}: {' '.join(ctx.unavailable[:8])}{' ...' if len(ctx.unavailable) > 8 else ''}",
            file=sys.stderr,
        )

    idx = load_alpha_index_is_only(run_id)
    selected = list(select_members(idx))
    if not selected:
        raise ValueError("select_members returned an empty list")
    coef = dict(member_weights(selected, idx))
    missing = [a for a in selected if a not in coef]
    if missing:
        raise ValueError(f"member_weights missing entries for: {missing}")

    statuses = ensure_members_fresh(selected, ctx, rerun_members)
    sizing = _shared_sizing(statuses)

    is_gross_mean: dict[str, float | None] = {}
    full_panels: dict[str, pd.DataFrame] = {}
    for alpha_id in selected:
        is_events = _load_member_events(run_id, alpha_id, "is", ctx.is_end)
        is_gross_mean[alpha_id] = _gross_mean_from_panel(_events_to_panel(is_events, ctx.universe))
        events = is_events
        if include_os:
            events = pd.concat([is_events, _load_member_events(run_id, alpha_id, "os", ctx.is_end)], ignore_index=True)
        full_panels[alpha_id] = _events_to_panel(events, ctx.universe)
    long_df, stats = combine_weights(full_panels, coef, ctx.universe, target_gross)

    comp_dir = ctx.run_dir / "composites" / composite_id
    comp_dir.mkdir(parents=True, exist_ok=True)
    weights_path = comp_dir / "weights.parquet"
    long_df.to_parquet(weights_path, index=False)

    # Per-member daily gross contribution c_a · Σ_s |W_a[t,s]| for the
    # dashboard's stacked area; summed over members it is the daily gross.
    rows = []
    for alpha_id, panel in full_panels.items():
        if panel.empty:
            continue
        gross = panel.ffill().fillna(0.0).abs().sum(axis=1) * float(coef[alpha_id])
        for ts, v in gross.resample("1D").mean().dropna().items():
            rows.append({"date": ts.normalize(), "alpha_id": alpha_id, "gross_contribution": float(v)})
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
        "run_id": run_id,
        "method": composition_note,
        "n_members": len(selected),
        "members": selected,
        "coefficients": {a: float(coef[a]) for a in selected},
        **stats,
        "is_window": ctx.is_window,
        "os_window": ctx.os_window if include_os else None,
        "data_path": ctx.data_path,
        "n_symbols": len(ctx.universe),
        "unavailable_symbols": ctx.unavailable,
        "sizing": sizing,
        "engine_fingerprint": engine_fingerprint(),
        "members_provenance": [s.provenance() for s in statuses],
        "selection_bias_warning": (
            "Selection used IS metrics. The OS backtest is a single-shot "
            "evaluation of this frozen composite; member alphas were drawn "
            "from a search-space pool, so OS Sharpe is a noisy point estimate."
        ),
        "created": datetime.now(timezone.utc).isoformat(),
    }
    # Frozen before the replay: the OS result can never feed back into it.
    (comp_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))

    _run_backtest_window(
        weights_path=weights_path,
        out_dir=comp_dir,
        ctx=ctx,
        sizing=sizing,
        target_gross=target_gross,
        alpha_id=composite_id,
    )
    metrics_path = comp_dir / "metrics.json"
    metrics = _read_json(metrics_path)
    metrics.update(manifest)
    metrics_path.write_text(json.dumps(metrics, indent=2, default=str))
    return comp_dir


def cli(
    composite_id: str,
    select_members: Callable[[pd.DataFrame], list[str]],
    member_weights: Callable[[list[str], pd.DataFrame], dict[str, float]],
    composition_note: str,
    target_gross: float | None = None,
    argv: list[str] | None = None,
) -> Path:
    """The command line shared by every composite module."""
    parser = argparse.ArgumentParser(description=f"Build composite {composite_id}")
    parser.add_argument("--run-id", required=True, help="archive subdir, e.g. run_2026_08_pit641")
    parser.add_argument("--no-os", action="store_true", help="skip the OS part of the replay")
    parser.add_argument(
        "--rerun-members", choices=RERUN_MODES, default="auto",
        help="auto: rerun a member whose archive is stale (default); always: rerun every member; "
             "never: combine the archives as they are",
    )
    args = parser.parse_args(argv)
    return build_and_backtest(
        composite_id=composite_id,
        run_id=args.run_id,
        select_members=select_members,
        member_weights=member_weights,
        composition_note=composition_note,
        include_os=not args.no_os,
        target_gross=target_gross,
        rerun_members=args.rerun_members,
    )
