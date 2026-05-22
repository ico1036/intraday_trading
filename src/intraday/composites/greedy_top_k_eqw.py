"""greedy_top_k_eqw — pick K alphas by full-period Sharpe, |corr|<thr filter, 1/N.

Selection pool: ALL alphas under the run (SUBMITTABLE gate intentionally
skipped). Each alpha's IC sign decides whether its weights deploy
"as is" (+1) or flipped to its mirror direction (−1).

Pipeline:
  1. select_all_alphas → 233-ish pool
  2. IC-based sign flip
  3. Load IS+OS daily returns matrix (only IS is used for the *ranking*
     metric; OS portion is just to align timestamps — selection still
     uses IS-only Sharpe so this is look-ahead safe even though the
     correlation matrix is computed across both).
  4. Greedy walk: sort by IS Sharpe ↓; keep each whose |corr| to every
     already-kept member < ``--corr-thr``; stop at K.
  5. Equal weight 1/K on kept members, signs applied so they deploy in
     their IC direction.

The EDA (no fees) showed this approach reaches Sharpe ~3 on full-period
returns, but the EDA "flips" only the *post-fee* return series — when a
member's raw P&L was already eaten by fees, flipping the sign of the
fee-net series does not survive a real backtest. This builder lets the
actual fees decide.

Run::

    uv run python -m intraday.composites.greedy_top_k_eqw \\
        --run-id <run_id> --K 5 --corr-thr 0.2
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

from intraday.composites._runner import ARCHIVE_ROOT, build_and_backtest
from intraday.composites._optim_helpers import (
    select_all_alphas,
    member_signs_ic,
    member_is_sharpe,
    load_member_is_returns,
    apply_signs,
)


COMPOSITE_ID = "greedy_top_k_eqw"
COMPOSITION_NOTE = "greedy_corr_filter_top_sharpe_eqw"


def _greedy_pick(R: pd.DataFrame, sharpe: dict[str, float],
                 K: int, thr: float) -> list[str]:
    corr = R.corr().abs()
    ranked = sorted(R.columns, key=lambda m: sharpe.get(m, 0.0), reverse=True)
    kept: list[str] = []
    for m in ranked:
        if len(kept) >= K:
            break
        if all(corr.at[m, k] < thr for k in kept):
            kept.append(m)
    return kept


def main() -> None:
    parser = argparse.ArgumentParser(description=f"Build composite {COMPOSITE_ID}")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--K", type=int, default=5,
                        help="Max members to keep after greedy filter.")
    parser.add_argument("--corr-thr", type=float, default=0.2,
                        help="Reject candidate if |corr| ≥ thr to any kept.")
    parser.add_argument("--no-os", action="store_true")
    args = parser.parse_args()
    run_id = args.run_id

    pool = select_all_alphas(run_id)
    if not pool:
        raise RuntimeError(f"empty alpha pool under {run_id}")
    signs = member_signs_ic(run_id, pool)
    R = load_member_is_returns(run_id, pool, signs=signs)
    if R.empty or R.shape[1] < 2:
        raise RuntimeError("insufficient member return series")

    # IS-Sharpe-of-the-flipped-series (the ranking metric the EDA used)
    sharpe_flipped = {a: float(R[a].mean() / R[a].std() * np.sqrt(365))
                      if R[a].std() > 0 else 0.0
                      for a in R.columns}

    members = _greedy_pick(R, sharpe_flipped, K=int(args.K),
                           thr=float(args.corr_thr))
    if len(members) < 2:
        raise RuntimeError(f"greedy pick returned only {len(members)} members")
    print(f"[greedy_top_k_eqw] pool={len(pool)}  greedy_kept={len(members)}",
          flush=True)
    for m in members:
        print(f"  pick: {m}  sharpe(flipped)={sharpe_flipped[m]:+.3f}  "
              f"sign={signs.get(m, 1)}", flush=True)

    n = len(members)
    coef_dict = apply_signs({m: 1.0 / n for m in members}, signs)

    def select(_idx: pd.DataFrame) -> list[str]:
        return members

    def weights(ids: list[str], _idx: pd.DataFrame) -> dict[str, float]:
        return {a: coef_dict[a] for a in ids}

    build_and_backtest(
        composite_id=COMPOSITE_ID,
        run_id=run_id,
        select_members=select,
        member_weights=weights,
        composition_note=COMPOSITION_NOTE,
        include_os=not args.no_os,
    )

    manifest_path = ARCHIVE_ROOT / run_id / "composites" / COMPOSITE_ID / "manifest.json"
    if manifest_path.exists():
        m = json.loads(manifest_path.read_text())
        m["greedy_top_k_eqw"] = {
            "K": int(args.K),
            "corr_thr": float(args.corr_thr),
            "pool_size": len(pool),
            "n_members_kept": len(members),
            "members": members,
            "signs": {a: int(signs.get(a, 1)) for a in members},
            "ranking_sharpe_flipped": {a: sharpe_flipped[a] for a in members},
        }
        manifest_path.write_text(json.dumps(m, indent=2, default=str))


if __name__ == "__main__":
    main()
