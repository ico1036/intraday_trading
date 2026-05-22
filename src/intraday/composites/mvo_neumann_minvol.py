"""mvo_neumann_minvol — min-variance weights with Neumann-truncated inverse covariance.

Same Neumann-series approximation as ``mvo_neumann_sharpe`` but the
objective is min-variance: ``c ∝ Σ⁻¹ · 1`` (and normalise to sum 1).

The Neumann truncation acts as noise filtering on the precision
matrix; min-variance with a noisy precision matrix is the classic
"concentration in least-noisy-direction" trap. Truncation widens
the support across members.

Run::

    uv run python -m intraday.composites.mvo_neumann_minvol \\
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
from intraday.composites.mvo_neumann_sharpe import _neumann_inv


COMPOSITE_ID = "mvo_neumann_minvol"
COMPOSITION_NOTE = "min_variance_neumann_ic_flip_dedup"


def main() -> None:
    parser = argparse.ArgumentParser(description=f"Build composite {COMPOSITE_ID}")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--order", type=int, default=2)
    parser.add_argument("--shrink", type=float, default=0.1)
    parser.add_argument("--max-spec-norm", type=float, default=0.9)
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
    print(f"[mvo_neumann_minvol] raw={len(submittables)}  kept={len(members)}", flush=True)
    Sigma = shrink_cov(R, shrinkage=float(args.shrink))
    inv, info = _neumann_inv(Sigma, args.order, args.max_spec_norm)
    ones = np.ones(len(members))
    c = inv @ ones
    c = c / float(ones @ c)

    print(f"[mvo_neumann_minvol] order={args.order}  ‖A‖₂={info['spectral_norm_A']:.3f}  "
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

    manifest_path = ARCHIVE_ROOT / run_id / "composites" / COMPOSITE_ID / "manifest.json"
    if manifest_path.exists():
        m = json.loads(manifest_path.read_text())
        m["neumann"] = info
        manifest_path.write_text(json.dumps(m, indent=2, default=str))


if __name__ == "__main__":
    main()
