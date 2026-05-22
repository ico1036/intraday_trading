"""epsilon_residual — residual-return portfolio after regressing out PC1.

Fama-French / Grinold-Kahn style decomposition:
  * Members share a strong common factor (PC1) — our correlation matrix
    has ‖A‖₂ in the tens, so most variance is explained by one direction.
  * Naïve composite (1/N, MVO, etc.) ends up taking a large bet on that
    common factor, killing diversification.
  * Solution: regress each member's IS returns on the PC1 time-series
    score, keep only the residual ``ε_i = r_i − β_i·f``, then build the
    portfolio from those residuals.

Pipeline:
  1. Select IS-SUBMITTABLE alphas, IC-sign-flip negative-IC members.
  2. Build R[T×N] returns matrix on the flipped series.
  3. Correlation dedup at threshold 0.7 to drop the most redundant copies
     (keeps PC1 well-conditioned).
  4. SVD(R−mean) → first column gives PC1 score f_t = U[:,0]·S[0].
  5. For each member: β_i = cov(r_i, f) / var(f),  ε_i = r_i − β_i·f.
  6. Inverse-vol weighting on residuals:  c_i ∝ 1/σ(ε_i),  Σ|c| = 1.
  7. β-neutrality projection:  c ← c − β·(β·c / β·β)  ⇒  Σ c_i β_i = 0.
     Renormalise.
  8. Apply IC signs back so deployed direction matches each member's
     intended signal.

Look-ahead safeguards:
  * All statistics (PC1, β, ε, σ) estimated on the IS window only.
  * Frozen in manifest before OS backtest.

Run::

    uv run python -m intraday.composites.epsilon_residual --run-id <run_id>
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


COMPOSITE_ID = "epsilon_residual"
COMPOSITION_NOTE = "pc1_residual_inverse_vol_beta_neutral"


def main() -> None:
    parser = argparse.ArgumentParser(description=f"Build composite {COMPOSITE_ID}")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--dedup-threshold", type=float, default=0.7,
                        help="Drop members with |corr| ≥ this to a kept one.")
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
    if len(members) < 2:
        raise RuntimeError(f"dedup left only {len(members)} members")
    R = R_full[members]
    print(f"[epsilon_residual] raw={len(submittables)}  kept={len(members)}", flush=True)

    # 4. PC1 time-series score
    X = R.values - R.values.mean(axis=0, keepdims=True)  # centred (T × N)
    U, S, _Vt = np.linalg.svd(X, full_matrices=False)
    f = (U[:, 0] * S[0])  # PC1 score, length T
    var_f = float(np.var(f, ddof=1)) or 1e-12

    # 5. Per-member β and residual ε
    beta = np.array([
        float(np.cov(R[m].values, f, ddof=1)[0, 1]) / var_f
        for m in members
    ])
    eps = R.values - np.outer(f, beta)  # T × N
    sigma_eps = eps.std(axis=0, ddof=1)
    sigma_eps = np.where(sigma_eps > 1e-12, sigma_eps, 1e-12)

    pc1_var_share = float(np.sum(np.outer(f, beta) ** 2)) / max(
        float(np.sum(X ** 2)), 1e-12)
    print(f"[epsilon_residual] PC1 share of total variance ≈ "
          f"{pc1_var_share:.2%}", flush=True)

    # 6. Inverse-vol on residuals
    c = 1.0 / sigma_eps
    c = c / np.sum(np.abs(c))  # |c|_1 = 1

    # 7. β-neutrality: subtract β-direction component from c
    beta_norm2 = float(beta @ beta) or 1e-12
    c = c - beta * (float(beta @ c) / beta_norm2)
    c = c / max(float(np.sum(np.abs(c))), 1e-12)
    residual_beta = float(beta @ c)
    print(f"[epsilon_residual] residual β-exposure of c = {residual_beta:.2e}",
          flush=True)

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

    # Record diagnostics in manifest
    manifest_path = ARCHIVE_ROOT / run_id / "composites" / COMPOSITE_ID / "manifest.json"
    if manifest_path.exists():
        m = json.loads(manifest_path.read_text())
        m["epsilon_residual"] = {
            "dedup_threshold": float(args.dedup_threshold),
            "n_members_raw": len(submittables),
            "n_members_kept": len(members),
            "pc1_variance_share": pc1_var_share,
            "residual_beta_exposure": residual_beta,
            "betas": {members[i]: float(beta[i]) for i in range(len(members))},
            "sigma_eps": {members[i]: float(sigma_eps[i]) for i in range(len(members))},
        }
        manifest_path.write_text(json.dumps(m, indent=2, default=str))


if __name__ == "__main__":
    main()
