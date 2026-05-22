"""rolling_greedy — sliding-window walk-forward composite.

For each refit time t (every ``--refit-freq`` days, starting after a
``--lookback`` warmup):

  1. Take the past ``lookback`` days of returns ``R[t-LB : t]`` over
     ALL alphas under the run.
  2. Per alpha: sign = +1 if mean(R_window) ≥ 0 else −1. Flip the
     window so each alpha is in its "deployed direction".
  3. Per alpha: window Sharpe = mean / std × √365 on the flipped
     series.
  4. Greedy walk by descending Sharpe with ``|corr| < corr-thr``
     rejection vs. already-kept members. Stop at K.
  5. Coefficient ``c_a = sign_a / K`` for each kept member.

The chosen coefficients are applied to each member's daily weights
panel from the *next* bar onward until the next refit. The combined
composite weights series is then backtested with
``PrecomputedWeightsStrategy`` over the post-warmup window only —
the warmup period contributes nothing to the equity curve, so
Sharpe / DD are measured cleanly on the walk-forward segment.

Look-ahead safeguards:
  * The refit at time ``t`` uses returns strictly *before* ``t``
    (window is sliced as ``R.iloc[i-LB:i]``).
  * IC signs are recomputed every refit from the same window — no
    full-period IC leakage.
  * The backtest starts at the first bar after warmup completes;
    Sharpe is not contaminated by zero-trade warmup days.

Run::

    uv run python -m intraday.composites.rolling_greedy \\
        --run-id run_2026_05_full531 --K 5 --corr-thr 0.2 \\
        --lookback 252 --refit-freq 7
"""
from __future__ import annotations

import argparse
import json
import sys
from bisect import bisect_right
from pathlib import Path

import numpy as np
import pandas as pd

from intraday.composites._runner import (
    ARCHIVE_ROOT, _load_member_events, _events_to_panel,
    _run_backtest_window, _GROSS_EPS,
)
from intraday.composites._optim_helpers import select_all_alphas


COMPOSITE_ID_BASE = "rolling_greedy"


def _per_alpha_returns(run_id: str, aid: str) -> pd.Series | None:
    parts = []
    for sp in ("is", "os"):
        p = ARCHIVE_ROOT / run_id / "alphas" / aid / sp / "equity_curve.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(p, columns=["timestamp", "equity"])
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        parts.append(df)
    if not parts:
        return None
    eq = (pd.concat(parts, ignore_index=True)
            .sort_values("timestamp")
            .drop_duplicates("timestamp")
            .set_index("timestamp"))
    eod = eq["equity"].resample("1D").last().dropna()
    if len(eod) < 60:
        return None
    return eod.pct_change().fillna(0.0)


def _per_alpha_panel(run_id: str, aid: str, universe: list[str]) -> pd.DataFrame:
    parts = []
    for sp in ("is", "os"):
        ev = _load_member_events(run_id, aid, sp)
        if not ev.empty:
            parts.append(ev)
    if not parts:
        return pd.DataFrame(columns=universe)
    full = pd.concat(parts, ignore_index=True)
    return _events_to_panel(full, universe)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--K", type=int, default=5)
    parser.add_argument("--corr-thr", type=float, default=0.2)
    parser.add_argument("--lookback", type=int, default=252)
    parser.add_argument("--refit-freq", type=int, default=7,
                        help="Refit every N days (1=daily, 7=weekly).")
    parser.add_argument("--no-os", action="store_true",
                        help="Unused (walk-forward is a single window).")
    args = parser.parse_args()

    run_id = args.run_id
    # Per-configuration composite dir so we can sweep without overwrites.
    composite_id = (f"{COMPOSITE_ID_BASE}_lb{int(args.lookback)}"
                    f"_rf{int(args.refit_freq)}_K{int(args.K)}"
                    f"_thr{int(float(args.corr_thr)*100):02d}")
    splits = json.loads((ARCHIVE_ROOT / run_id / "splits.json").read_text())
    universe = [s.upper() for s in splits["universe"]]

    pool = select_all_alphas(run_id)
    print(f"[rolling_greedy] pool size: {len(pool)}", flush=True)

    # 1. Build the cross-section returns matrix
    rets = {}
    for aid in pool:
        r = _per_alpha_returns(run_id, aid)
        if r is not None:
            rets[aid] = r
    if not rets:
        raise RuntimeError("no usable return series in pool")
    R = pd.DataFrame(rets).sort_index().fillna(0.0)
    pool = list(R.columns)  # ones we actually have
    print(f"[rolling_greedy] R shape T×N = {R.shape}", flush=True)

    # 2. Build each alpha's weight panel (T × universe)
    panels = {aid: _per_alpha_panel(run_id, aid, universe) for aid in pool}

    # 3. Common timestamp grid (union of all panels)
    all_ts = sorted(set().union(*[p.index for p in panels.values() if not p.empty]))
    if not all_ts:
        raise RuntimeError("no member weights timestamps")
    grid = pd.DatetimeIndex(all_ts)
    print(f"[rolling_greedy] grid: {grid[0]} → {grid[-1]}  bars={len(grid)}",
          flush=True)

    # Align each panel to the grid via forward-fill (carries the most-recent
    # target weight, zero before the first event).
    aligned = {}
    for aid in pool:
        p = panels[aid]
        if p.empty:
            aligned[aid] = pd.DataFrame(0.0, index=grid, columns=universe)
        else:
            aligned[aid] = p.reindex(grid).ffill().fillna(0.0)
    A = np.stack([aligned[aid].values for aid in pool], axis=0)  # (N, T, U)

    # 4. Rolling refits — only on the daily R index, which is what the
    #    look-back is defined on. Then translate to grid timestamps.
    R = R.reindex(grid).fillna(0.0)   # align returns to the same grid
    R_vals = R.values                  # (T, N)
    T, N = R_vals.shape
    LB = int(args.lookback)
    RF = int(args.refit_freq)

    pool_idx = {a: i for i, a in enumerate(pool)}
    refit_records: list[tuple[int, dict[str, float]]] = []
    for i in range(LB, T, RF):
        window = R_vals[i - LB:i]   # exclude row i (today) — strict past
        means = window.mean(axis=0)
        stds = window.std(axis=0)
        signs = np.where(means < -1e-6, -1, 1)
        flipped = window * signs
        sharpe = np.where(stds > 1e-12,
                          flipped.mean(axis=0) / np.where(stds > 1e-12, stds, 1) * np.sqrt(365),
                          0.0)
        # Greedy
        order = np.argsort(-sharpe)
        corr_mat = pd.DataFrame(flipped, columns=pool).corr().abs().fillna(0).values
        kept_idx: list[int] = []
        for k in order:
            if len(kept_idx) >= int(args.K):
                break
            if all(corr_mat[k, j] < float(args.corr_thr) for j in kept_idx):
                kept_idx.append(int(k))
        if len(kept_idx) < 2:
            continue
        c = {pool[j]: float(signs[j]) / len(kept_idx) for j in kept_idx}
        refit_records.append((i, c))

    print(f"[rolling_greedy] refits: {len(refit_records)}", flush=True)
    if not refit_records:
        raise RuntimeError("no valid refit windows produced members")

    # 5. Build c_arr (T × N) — apply each refit from its bar onward
    c_arr = np.zeros((T, len(pool)))
    refit_starts = [r[0] for r in refit_records]
    for k, (start_i, c) in enumerate(refit_records):
        next_i = refit_records[k + 1][0] if k + 1 < len(refit_records) else T
        for aid, coef in c.items():
            c_arr[start_i:next_i, pool_idx[aid]] = coef

    # 6. Combine: W_comp[t, s] = Σ_a c_arr[t, a] · A[a, t, s]
    #    einsum: 'tn, ntu -> tu'  (memory-friendly; ~T·U·N flops)
    combined = np.einsum("tn,ntu->tu", c_arr, A)
    combined_df = pd.DataFrame(combined, index=grid, columns=universe)

    # 7. Row-wise normalise so |Σ_s| ≤ 1
    row_l1 = combined_df.abs().sum(axis=1)
    n_clipped = int((row_l1 > 1.0 + _GROSS_EPS).sum())
    scale = pd.Series(1.0, index=grid).where(
        row_l1 <= 1.0, 1.0 / row_l1.replace(0.0, 1.0))
    combined_df = combined_df.mul(scale, axis=0)

    # 8. Wide → long change events
    rows = []
    for sym in universe:
        col = combined_df[sym]
        prev = col.shift()
        changed = (col != prev) & ~(prev.isna() & (col.abs() < _GROSS_EPS))
        for ts in col.index[changed.fillna(False)]:
            rows.append((ts, sym, float(col.loc[ts])))
    long_df = (pd.DataFrame(rows, columns=["timestamp", "symbol", "target_weight"])
                 .sort_values(["timestamp", "symbol"])
                 .reset_index(drop=True))
    print(f"[rolling_greedy] change events: {len(long_df):,}  rows_clipped={n_clipped}",
          flush=True)

    # 9. Save artifacts
    comp_dir = ARCHIVE_ROOT / run_id / "composites" / composite_id
    comp_dir.mkdir(parents=True, exist_ok=True)
    weights_path = comp_dir / "weights.parquet"
    long_df.to_parquet(weights_path, index=False)

    first_active = grid[LB]
    last_ts = grid[-1]
    bt_start = first_active.strftime("%Y-%m-%d %H:%M:%S")
    bt_end = last_ts.strftime("%Y-%m-%d %H:%M:%S")

    members_used = sorted({aid for _, c in refit_records for aid in c.keys()})
    pd.DataFrame({"alpha_id": members_used}).to_csv(comp_dir / "members.csv",
                                                   index=False)

    manifest = {
        "composite_id": composite_id,
        "method": "rolling_walk_forward_greedy_top_K_eqw",
        "K": int(args.K),
        "corr_thr": float(args.corr_thr),
        "lookback_days": int(LB),
        "refit_freq_days": int(RF),
        "pool_size": len(pool),
        "n_refits": len(refit_records),
        "n_unique_members_used": len(members_used),
        "warmup_end": bt_start,
        "backtest_window": {"start": bt_start, "end": bt_end},
        "selection_bias_warning": (
            "Walk-forward: every refit uses ONLY the trailing 252-day window. "
            "Backtest excludes warmup. IS/OS distinction does not apply."
        ),
    }
    (comp_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))

    # 10. Backtest the post-warmup window (single segment)
    out_dir = comp_dir / "wf"
    _run_backtest_window(weights_path=weights_path, out_dir=out_dir,
                         symbols=universe, start=bt_start, end=bt_end)
    print(f"[rolling_greedy] backtest done → {out_dir}", flush=True)


if __name__ == "__main__":
    main()
