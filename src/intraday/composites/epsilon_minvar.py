"""epsilon_minvar — minimum-variance portfolio in the PC1-residual space, β-neutral.

The earlier ``epsilon_residual`` used inverse-volatility on the diagonal of
Σ_ε. That ignores residual covariance — two members with low individual
σ_eps can still co-move strongly, so 1/σ does not actually minimise
portfolio variance.

This builder solves the constrained quadratic:

    minimise   c' Σ_ε c
    subject to β' c = 0       (zero net exposure to the PC1 score f_t)
               1' c = 1       (unit gross — runner rescales row-wise)

Closed form (two-constraint mean-variance Lagrangian):

    c* = Σ_ε⁻¹ ( λ · 1  +  μ · β )

    a = 1' Σ_ε⁻¹ 1
    b = 1' Σ_ε⁻¹ β
    d = β' Σ_ε⁻¹ β
    λ =  d / (a d − b²)
    μ = −b / (a d − b²)

The result is the lowest-variance long/short combination of residual
return series whose PC1 exposure is exactly zero. By directly shrinking
σ_portfolio, the Sharpe ratio rises even when raw return is modest —
which is what the user wants in order to deploy with leverage.

Look-ahead safeguards:
  * PC1, β, ε, Σ_ε all estimated on IS only.
  * Frozen in manifest before OS backtest.

Run::

    uv run python -m intraday.composites.epsilon_minvar --run-id <run_id>
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

from intraday.composites._runner import ARCHIVE_ROOT, build_and_backtest
from intraday.composites._optim_helpers import (
    select_is_submittable,
    load_member_is_returns,
    member_signs_ic,
    member_is_sharpe,
    apply_signs,
    correlation_dedup,
)


COMPOSITE_ID = "epsilon_minvar"
COMPOSITION_NOTE = "pc1_residual_minvariance_beta_neutral"


def _shrink_cov(eps: np.ndarray, alpha: float) -> np.ndarray:
    """Linear shrinkage of the residual covariance toward its diagonal."""
    S = np.cov(eps, rowvar=False, ddof=1)
    D = np.diag(np.diag(S))
    return (1.0 - alpha) * S + alpha * D


def main() -> None:
    parser = argparse.ArgumentParser(description=f"Build composite {COMPOSITE_ID}")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--dedup-threshold", type=float, default=0.7)
    parser.add_argument("--shrink", type=float, default=0.15,
                        help="Linear shrinkage on Σ_ε toward its diagonal.")
    parser.add_argument("--no-os", action="store_true")
    args = parser.parse_args()
    run_id = args.run_id

    submittables = select_is_submittable(run_id)
    if not submittables:
        raise RuntimeError(f"No IS-submittable alphas found under {run_id}")
    signs = member_signs_ic(run_id, submittables)
    R_full = load_member_is_returns(run_id, submittables, signs=signs)
    if R_full.empty or R_full.shape[1] < 2:
        raise RuntimeError("insufficient member return series")

    sh = member_is_sharpe(run_id, submittables)
    members = correlation_dedup(R_full, threshold=args.dedup_threshold, keep_metric=sh)
    if len(members) < 3:
        raise RuntimeError(f"dedup left only {len(members)} members; need ≥3 for "
                           "two-constraint min-variance")
    R = R_full[members]
    print(f"[epsilon_minvar] raw={len(submittables)}  kept={len(members)}", flush=True)

    # PC1 score and per-member β
    X = R.values - R.values.mean(axis=0, keepdims=True)
    U, S, _Vt = np.linalg.svd(X, full_matrices=False)
    f = (U[:, 0] * S[0])
    var_f = float(np.var(f, ddof=1)) or 1e-12
    beta = np.array([
        float(np.cov(R[m].values, f, ddof=1)[0, 1]) / var_f
        for m in members
    ])
    eps = R.values - np.outer(f, beta)

    # Σ_ε with diagonal shrinkage
    Sigma = _shrink_cov(eps, alpha=float(args.shrink))
    Sigma_inv = np.linalg.pinv(Sigma)

    ones = np.ones(len(members))
    a = float(ones @ Sigma_inv @ ones)
    b = float(ones @ Sigma_inv @ beta)
    d = float(beta @ Sigma_inv @ beta)
    denom = a * d - b * b
    if abs(denom) < 1e-12:
        # Pathological: β colinear with 1. Fall back to vanilla min-var (no
        # β-neutrality), which still excludes PC1 by construction (ε
        # already orthogonal to f, so c'·ε is PC1-free anyway).
        c = Sigma_inv @ ones
        c = c / (ones @ c)
        bn = float(beta @ c)
        print(f"[epsilon_minvar] β-neutral system singular; vanilla min-var; "
              f"β·c={bn:.2e}", flush=True)
    else:
        lam = d / denom
        mu = -b / denom
        c = Sigma_inv @ (lam * ones + mu * beta)
        bn = float(beta @ c)
        sm = float(ones @ c)
        print(f"[epsilon_minvar] β·c={bn:.2e}  Σc={sm:.4f}  "
              f"a={a:.2e} b={b:.2e} d={d:.2e}", flush=True)

    # Diagnostic: predicted residual portfolio σ
    pred_var = float(c @ Sigma @ c)
    pred_sigma = float(np.sqrt(max(pred_var, 0.0)))
    indiv_sigmas = eps.std(axis=0, ddof=1)
    naive_sigma_eqw = float(np.sqrt(np.mean(indiv_sigmas ** 2) / len(members)))
    print(f"[epsilon_minvar] IS predicted σ_p = {pred_sigma:.6f}  "
          f"naive_1/N σ ≈ {naive_sigma_eqw:.6f}", flush=True)

    coef_dict = apply_signs({m: float(c[i]) for i, m in enumerate(members)},
                            signs)

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
        m["epsilon_minvar"] = {
            "dedup_threshold": float(args.dedup_threshold),
            "shrinkage": float(args.shrink),
            "n_members_raw": len(submittables),
            "n_members_kept": len(members),
            "IS_predicted_sigma_portfolio": pred_sigma,
            "IS_naive_eqw_sigma": naive_sigma_eqw,
            "residual_beta_exposure": float(beta @ c),
        }
        manifest_path.write_text(json.dumps(m, indent=2, default=str))


if __name__ == "__main__":
    main()
