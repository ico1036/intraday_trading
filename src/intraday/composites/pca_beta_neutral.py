"""pca_beta_neutral — equal-weight on PC1-orthogonal projection of IS-submittable members.

Selection: IS-SUBMITTABLE alphas (same gate as ``is_submittable_eqw``).
Weights:
  1. R = T × N IS daily returns matrix.
  2. PC1 = first right singular vector of (R - mean) — the "market"
     direction in member space.
  3. Project equal-weight 1/N onto subspace orthogonal to PC1:
       c = (I - v v^T) · (1/N · 1)
  4. Return c (signed scalars per member). Composite runner does the
     row-wise gross normalisation downstream.

Look-ahead safeguards:
  * Member selection and PC1 estimation use IS equity curves only
    (``is/equity_curve.parquet``).
  * Coefficients are frozen in ``manifest.json`` before any OS backtest.

Run::

    uv run python -m intraday.composites.pca_beta_neutral --run-id <run_id>
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    select_is_submittable,
    load_member_is_returns,
    member_signs_ic,
    member_is_sharpe,
    apply_signs,
    correlation_dedup,
)


COMPOSITE_ID = "pca_beta_neutral"
COMPOSITION_NOTE = "pc1_orthogonal_ic_flip_dedup"


def main() -> None:
    parser = argparse.ArgumentParser(description=f"Build composite {COMPOSITE_ID}")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--no-os", action="store_true")
    args = parser.parse_args()
    run_id = args.run_id

    submittables = select_is_submittable(run_id)
    if not submittables:
        raise RuntimeError(f"No IS-submittable alphas found under {run_id}")
    signs = member_signs_ic(run_id, submittables)
    R_full = load_member_is_returns(run_id, submittables, signs=signs)
    if R_full.empty or R_full.shape[1] < 2:
        raise RuntimeError("insufficient member return series for PCA")

    sh = member_is_sharpe(run_id, submittables)
    members = correlation_dedup(R_full, threshold=0.6, keep_metric=sh)
    if len(members) < 2:
        raise RuntimeError(f"dedup left only {len(members)} members")
    R = R_full[members]
    print(f"[pca_beta_neutral] raw={len(submittables)}  kept={len(members)}", flush=True)
    X = R.values - R.values.mean(axis=0, keepdims=True)
    # SVD on centred returns — V[:, 0] = PC1 direction in member space.
    U, S, Vt = np.linalg.svd(X, full_matrices=False)
    v1 = Vt[0]
    v1 = v1 / (np.linalg.norm(v1) or 1.0)

    n = len(members)
    eq = np.full(n, 1.0 / n)
    coef = eq - v1 * float(eq @ v1)  # subtract projection on PC1
    coef_dict = apply_signs({m: float(coef[i]) for i, m in enumerate(members)}, signs)

    def select(_idx: pd.DataFrame) -> list[str]:
        return members

    def weights(ids: list[str], _idx: pd.DataFrame) -> dict[str, float]:
        # Defensive: re-emit coefficients in the order the runner asks.
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
