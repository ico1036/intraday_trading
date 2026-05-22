"""sharpe_opt — max-Sharpe (mean-variance) weights on IS-submittable members.

Selection: IS-SUBMITTABLE alphas.
Weights: solve  max_c  (c^T μ) / sqrt(c^T Σ c)  s.t.  1^T c = 1.
Closed-form (ignoring rf): c = (Σ⁻¹ μ) / (1^T Σ⁻¹ μ).

The mean-variance optimal weights amplify any member with high IS mean
return relative to risk — this is the most overfit-prone of the three
composites. Pair with Ledoit-Wolf shrinkage and watch OS degradation
closely.

Look-ahead safeguards:
  * μ and Σ estimated from IS daily returns only.
  * Frozen in manifest before OS backtest.

Run::

    uv run python -m intraday.composites.sharpe_opt --run-id <run_id> --shrink 0.2
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    select_is_submittable,
    load_member_is_returns,
    shrink_cov,
    member_signs_ic,
    member_is_sharpe,
    apply_signs,
    correlation_dedup,
)


COMPOSITE_ID = "sharpe_opt"
COMPOSITION_NOTE = "max_sharpe_ic_flip_dedup"


def main() -> None:
    parser = argparse.ArgumentParser(description=f"Build composite {COMPOSITE_ID}")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--shrink", type=float, default=0.2)
    parser.add_argument("--no-os", action="store_true")
    args = parser.parse_args()
    run_id = args.run_id

    submittables = select_is_submittable(run_id)
    if not submittables:
        raise RuntimeError(f"No IS-submittable alphas found under {run_id}")
    signs = member_signs_ic(run_id, submittables)
    R_full = load_member_is_returns(run_id, submittables, signs=signs)
    if R_full.empty or R_full.shape[1] < 2:
        raise RuntimeError("insufficient member return series for mean-variance")
    sh = member_is_sharpe(run_id, submittables)
    members = correlation_dedup(R_full, threshold=0.6, keep_metric=sh)
    if len(members) < 2:
        raise RuntimeError(f"dedup left only {len(members)} members")
    R = R_full[members]
    print(f"[sharpe_opt] raw={len(submittables)}  kept={len(members)}", flush=True)
    Sigma = shrink_cov(R, shrinkage=float(args.shrink))
    mu = R.mean(axis=0).values
    inv = np.linalg.pinv(Sigma)
    ones = np.ones(len(members))
    c = inv @ mu
    denom = float(ones @ c)
    if abs(denom) < 1e-12:
        # Degenerate: μ orthogonal to Σ⁻¹ 1; fall back to inverse-vol-weighted.
        c = inv @ ones
        denom = float(ones @ c) or 1.0
    c = c / denom
    coef_dict = apply_signs({m: float(c[i]) for i, m in enumerate(members)}, signs)

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


if __name__ == "__main__":
    main()
