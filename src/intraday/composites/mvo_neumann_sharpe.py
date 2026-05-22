"""mvo_neumann_sharpe — max-Sharpe weights with Neumann-truncated inverse covariance.

Background:
  Classical Markowitz max-Sharpe weights ``c ∝ Σ⁻¹ μ`` suffer from
  estimation error in ``Σ⁻¹``: tiny eigenvalues of Σ get amplified after
  inversion, and the noise spills into ``c``. Ledoit-Wolf shrinkage
  toward the diagonal is one fix; this builder is a different kind —
  Neumann-series truncation of the *correlation* inverse:

      Σ = D^{1/2} C D^{1/2}
      C = I + A          (A = off-diagonal block of correlation matrix)
      C⁻¹ = I − A + A² − A³ + …    (Neumann series, converges when ‖A‖<1)
      C⁻¹_approx (order=k)  =  Σ_{j=0..k} (−A)^j
      Σ⁻¹_approx = D^{−1/2} · C⁻¹_approx · D^{−1/2}

  Truncating high-order terms drops *spurious long-range correlations*
  between distant alphas — the part most contaminated by sampling
  noise. The result is a regularised precision matrix that behaves
  like a banded operator.

Safety:
  Convergence of the Neumann series needs ‖A‖₂ < 1. If the spectral
  norm of the off-diagonal block exceeds ``--max-spec-norm`` (default
  0.9) the builder falls back to plain Ledoit-Wolf max-Sharpe and
  records the fallback in the manifest.

Run::

    uv run python -m intraday.composites.mvo_neumann_sharpe \\
        --run-id <run_id> --order 2 --shrink 0.1
"""
from __future__ import annotations

import argparse
import json

import numpy as np
import pandas as pd

from intraday.composites._runner import build_and_backtest, ARCHIVE_ROOT
from intraday.composites._optim_helpers import (
    select_is_submittable,
    load_member_is_returns,
    shrink_cov,
    member_signs_ic,
    member_is_sharpe,
    apply_signs,
    correlation_dedup,
)


COMPOSITE_ID = "mvo_neumann_sharpe"
COMPOSITION_NOTE = "max_sharpe_neumann_ic_flip_dedup"


def _neumann_inv(Sigma: np.ndarray, order: int, max_spec_norm: float) -> tuple[np.ndarray, dict]:
    """Approximate Σ⁻¹ via truncated Neumann series on the correlation matrix.

    Returns (Σ⁻¹_approx, info) where ``info`` records ‖A‖₂ and whether
    a fallback was triggered.
    """
    d = np.sqrt(np.maximum(np.diag(Sigma), 1e-16))
    Dinv = 1.0 / d
    # Correlation matrix
    C = Sigma * np.outer(Dinv, Dinv)
    np.fill_diagonal(C, 1.0)
    A = C - np.eye(C.shape[0])
    spec = float(np.linalg.norm(A, ord=2))
    info = {"spectral_norm_A": spec, "order": int(order)}
    if spec >= max_spec_norm:
        # Fall back to Ledoit-Wolf style: just use pinv on the shrunk Σ.
        info["fallback"] = "spectral_norm_exceeded"
        return np.linalg.pinv(Sigma), info
    # Σ_{j=0..k} (-A)^j
    n = C.shape[0]
    Cinv = np.eye(n)
    term = np.eye(n)
    for _ in range(int(order)):
        term = -term @ A
        Cinv = Cinv + term
    Sigma_inv = (Dinv[:, None] * Cinv) * Dinv[None, :]
    info["fallback"] = None
    return Sigma_inv, info


def main() -> None:
    parser = argparse.ArgumentParser(description=f"Build composite {COMPOSITE_ID}")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--order", type=int, default=2,
                        help="Neumann truncation order (k=1,2,3 typical).")
    parser.add_argument("--shrink", type=float, default=0.1,
                        help="Ledoit-Wolf-style linear shrinkage on Σ before Neumann.")
    parser.add_argument("--max-spec-norm", type=float, default=0.9,
                        help="If ‖A‖₂ exceeds this, fall back to pinv(Σ).")
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
    members = correlation_dedup(R_full, threshold=0.6, keep_metric=sh)
    if len(members) < 2:
        raise RuntimeError(f"dedup left only {len(members)} members")
    R = R_full[members]
    print(f"[mvo_neumann_sharpe] raw={len(submittables)}  kept={len(members)}", flush=True)
    Sigma = shrink_cov(R, shrinkage=float(args.shrink))
    mu = R.mean(axis=0).values
    inv, info = _neumann_inv(Sigma, args.order, args.max_spec_norm)
    ones = np.ones(len(members))
    c = inv @ mu
    denom = float(ones @ c)
    if abs(denom) < 1e-12:
        c = inv @ ones
        denom = float(ones @ c) or 1.0
    c = c / denom

    print(f"[mvo_neumann_sharpe] order={args.order}  ‖A‖₂={info['spectral_norm_A']:.3f}  "
          f"fallback={info['fallback']}", flush=True)

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

    # Append optimiser info to manifest after runner wrote it.
    manifest_path = ARCHIVE_ROOT / run_id / "composites" / COMPOSITE_ID / "manifest.json"
    if manifest_path.exists():
        m = json.loads(manifest_path.read_text())
        m["neumann"] = info
        manifest_path.write_text(json.dumps(m, indent=2, default=str))


if __name__ == "__main__":
    main()
