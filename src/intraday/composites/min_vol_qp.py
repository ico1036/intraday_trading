"""min_vol_qp — Markowitz minimum-variance weights on IS-submittable members.

Selection: IS-SUBMITTABLE alphas.
Weights: solve  min_c  c^T Σ c  s.t.  1^T c = 1.
Closed form: c = (Σ⁻¹ 1) / (1^T Σ⁻¹ 1).

We apply linear shrinkage (`--shrink`, default 0.1) toward the diagonal to
stabilise the inverse when N approaches T or members are collinear. The
coefficients can be negative (composite framework allows long-short).

Look-ahead safeguards:
  * Σ estimated from IS daily returns only.
  * Frozen in manifest before OS backtest.

Run::

    uv run python -m intraday.composites.min_vol_qp --run-id <run_id> --shrink 0.1
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


COMPOSITE_ID = "min_vol_qp"
COMPOSITION_NOTE = "min_variance_ic_flip_dedup"


def main() -> None:
    parser = argparse.ArgumentParser(description=f"Build composite {COMPOSITE_ID}")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--shrink", type=float, default=0.1)
    parser.add_argument("--no-os", action="store_true")
    args = parser.parse_args()
    run_id = args.run_id

    submittables = select_is_submittable(run_id)
    if not submittables:
        raise RuntimeError(f"No IS-submittable alphas found under {run_id}")
    signs = member_signs_ic(run_id, submittables)
    R_full = load_member_is_returns(run_id, submittables, signs=signs)
    if R_full.empty or R_full.shape[1] < 2:
        raise RuntimeError("insufficient member return series for covariance")
    sh = member_is_sharpe(run_id, submittables)
    members = correlation_dedup(R_full, threshold=0.6, keep_metric=sh)
    if len(members) < 2:
        raise RuntimeError(f"dedup left only {len(members)} members")
    R = R_full[members]
    print(f"[min_vol_qp] raw={len(submittables)}  kept={len(members)}", flush=True)
    n = len(members)
    Sigma = shrink_cov(R, shrinkage=float(args.shrink))
    inv = np.linalg.pinv(Sigma)
    ones = np.ones(n)
    c = inv @ ones
    c = c / float(ones @ c)  # sum(c) = 1
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
