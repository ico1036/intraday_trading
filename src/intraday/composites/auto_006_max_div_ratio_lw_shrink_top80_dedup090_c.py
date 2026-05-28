"""Maximum Diversification Ratio portfolio (Choueifaty & Coignard 2008) on
Ledoit-Wolf shrunk covariance, with IC-aligned sign flip, mild |rho|>0.90 dedup,
and top-Sharpe concentration of ~20 complementary high-return members."""
from __future__ import annotations
import argparse
import math
import numpy as np
import pandas as pd
import scipy.linalg as sla

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    correlation_dedup,
    member_signs_ic,
    apply_signs,
    shrink_cov,
    select_is_submittable,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_006_max_div_ratio_lw_shrink_top80_dedup090_c"
COMPOSITION_NOTE = "max_div_ratio_lw_shrink_top80_dedup090_cap30_gross070"

RUN_ID = "run_2026_05_c"
TOP_N_PRESELECT = 80
DEDUP_THRESHOLD = 0.90
TARGET_GROSS = 0.70
MIN_MEMBERS = 12
MAX_MEMBERS = 30
SHRINKAGE = 0.15


def _is_sharpe_lookup(alpha_index: pd.DataFrame) -> dict[str, float]:
    if (
        alpha_index is not None
        and not alpha_index.empty
        and "alpha_id" in alpha_index.columns
        and "is_sharpe" in alpha_index.columns
    ):
        out: dict[str, float] = {}
        for aid, s in zip(alpha_index["alpha_id"], alpha_index["is_sharpe"]):
            try:
                out[str(aid)] = float(s)
            except (TypeError, ValueError):
                continue
        return out
    return {}


def _empirical_sharpe(R: pd.DataFrame) -> dict[str, float]:
    out: dict[str, float] = {}
    for col in R.columns:
        r = R[col].dropna()
        if len(r) < 5:
            out[col] = 0.0
            continue
        sd = float(r.std())
        out[col] = float(r.mean() / sd * math.sqrt(252)) if sd > 0 else 0.0
    return out


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if not ids:
        return []

    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.shape[1] < MIN_MEMBERS:
        return list(R.columns) if R is not None else []

    sharpe_map = _is_sharpe_lookup(alpha_index)
    emp = _empirical_sharpe(R)
    keep_metric: dict[str, float] = {
        c: float(sharpe_map.get(c, emp.get(c, 0.0))) for c in R.columns
    }

    ranked = sorted(R.columns, key=lambda a: keep_metric.get(a, 0.0), reverse=True)
    pre = ranked[: max(TOP_N_PRESELECT, MIN_MEMBERS)]
    R_pre = R[pre]

    try:
        kept = correlation_dedup(R_pre, threshold=DEDUP_THRESHOLD, keep_metric=keep_metric)
    except Exception:
        kept = list(pre)

    kept = sorted(kept, key=lambda a: keep_metric.get(a, 0.0), reverse=True)
    if len(kept) > MAX_MEMBERS:
        kept = kept[:MAX_MEMBERS]
    if len(kept) < MIN_MEMBERS:
        kept = ranked[: max(MIN_MEMBERS, min(len(ranked), MAX_MEMBERS))]
    return list(kept)


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}

    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    cols = [m for m in member_ids if m in R.columns]
    if len(cols) < 2:
        # Degenerate fallback: equal weight on whatever survived.
        n = max(len(cols), 1)
        coef = {c: TARGET_GROSS / n for c in cols}
        return apply_signs(coef, signs)

    R = R[cols].fillna(0.0)

    Sigma = np.asarray(shrink_cov(R, shrinkage=SHRINKAGE), dtype=float)
    n = Sigma.shape[0]
    # Diagonal jitter for conditioning before the linear solve.
    Sigma = Sigma + np.eye(n) * 1e-10 * max(1.0, float(np.trace(Sigma)) / max(n, 1))
    sigma_vec = np.sqrt(np.clip(np.diag(Sigma), 1e-12, None))

    # Max-diversification closed form: w ∝ Σ^{-1} σ.
    try:
        w = sla.solve(Sigma, sigma_vec, assume_a="pos")
    except (sla.LinAlgError, ValueError):
        try:
            w = sla.pinvh(Sigma) @ sigma_vec
        except Exception:
            w = 1.0 / np.maximum(np.diag(Sigma), 1e-12)

    w = np.asarray(w, dtype=float).flatten()
    if not np.isfinite(w).all():
        w = 1.0 / np.maximum(np.diag(Sigma), 1e-12)

    # Members are IC-aligned to be positive-expectation; clip residual negatives
    # arising from finite-sample noise so we stay on the deployable side.
    w = np.clip(w, 0.0, None)
    if w.sum() <= 0:
        w = 1.0 / np.maximum(np.diag(Sigma), 1e-12)

    coef: dict[str, float] = {c: float(v) for c, v in zip(cols, w.tolist())}
    coef = normalize_coefficients(coef, scheme="l1")            # dict in, dict out
    coef = {k: float(v) * TARGET_GROSS for k, v in coef.items()}  # scale gross
    coef = apply_signs(coef, signs)                              # back to archived orientation
    return coef


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--no-os", action="store_true")
    args = parser.parse_args()
    build_and_backtest(
        composite_id=COMPOSITE_ID,
        run_id=args.run_id,
        select_members=select_members,
        member_weights=member_weights,
        composition_note=COMPOSITION_NOTE,
        include_os=not args.no_os,
    )


if __name__ == "__main__":
    main()