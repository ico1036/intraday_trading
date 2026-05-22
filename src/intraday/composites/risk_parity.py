"""risk_parity — equal risk contribution weights on IS-submittable members.

Selection: IS-SUBMITTABLE alphas.
Weights:
  * Start point: c_i ∝ 1/σ_i (inverse volatility, the "naive risk parity").
  * Refine to ERC (equal-risk-contribution) via Newton on the diag-weighted
    gradient. Each member contributes the same fraction of portfolio variance.

ERC condition:  c_i × (Σ c)_i = const  for all i.
Algorithm: iterative re-weighting
    c ← (1/(Σ c)) elementwise, normalised
converges in ~50 iterations for our pool sizes.

Look-ahead safeguards:
  * σ_i and Σ estimated from IS daily returns only.
  * Frozen in manifest before OS backtest.

Run::

    uv run python -m intraday.composites.risk_parity --run-id <run_id> --shrink 0.1
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


COMPOSITE_ID = "risk_parity"
COMPOSITION_NOTE = "erc_ic_flip_dedup"


def _erc_weights(Sigma: np.ndarray, max_iter: int = 200, tol: float = 1e-8) -> np.ndarray:
    n = Sigma.shape[0]
    sigma_i = np.sqrt(np.maximum(np.diag(Sigma), 1e-16))
    c = 1.0 / sigma_i
    c = c / c.sum()
    for _ in range(max_iter):
        marg = Sigma @ c  # marginal risk contribution proportional to (Σ c)_i
        # Target: c_i * marg_i = const → set c_i ∝ 1/marg_i then renormalise
        new_c = 1.0 / np.maximum(marg, 1e-16)
        new_c = new_c / new_c.sum()
        if np.linalg.norm(new_c - c) < tol:
            c = new_c
            break
        c = 0.5 * c + 0.5 * new_c  # damping for stability
    return c


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
        raise RuntimeError("insufficient member return series for risk parity")
    sh = member_is_sharpe(run_id, submittables)
    members = correlation_dedup(R_full, threshold=0.6, keep_metric=sh)
    if len(members) < 2:
        raise RuntimeError(f"dedup left only {len(members)} members")
    R = R_full[members]
    print(f"[risk_parity] raw={len(submittables)}  kept={len(members)}", flush=True)
    Sigma = shrink_cov(R, shrinkage=float(args.shrink))
    c = _erc_weights(Sigma)
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
