"""Greedy Gram-Schmidt residual-Sharpe composite with drawdown discipline.

Iteratively admits alphas whose IS-return stream has high Sharpe AFTER
projecting out the linear span of already-selected members (L2 orthogonalization
on the IS-returns inner product). This isolates genuinely orthogonal alpha
contribution rather than rewarding correlated near-clones - cf. Trippi (1986)
on factor decomposition and Harvey-Liu (2019) "A Census of the Factor Zoo"
for orthogonalization-based multi-test factor admission. A max IS drawdown
filter (<20%) acts as a tail-risk discipline in the spirit of Bailey-Lopez
de Prado (2014) PBO/CSCV. No covariance inversion is used, so the 1/sigma
underweighting trap that suppressed gross exposure in prior tangency/min-var
attempts cannot occur; coefficients are scaled post-L1 to push composite
mean row L1 into the [0.5, 0.9] productive band.
"""
from __future__ import annotations
import argparse
import numpy as np
import pandas as pd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    select_is_submittable,
    select_all_alphas,
    member_signs_ic,
    apply_signs,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_060_gram_schmidt_resid_sharpe_dd20_n6_gross"
COMPOSITION_NOTE = "gram_schmidt_resid_sharpe_dd20_n6_gross_x18"

RUN_ID = "run_2026_05_c"
TARGET_N = 6
DD_MAX = 0.20
MIN_RESID_SHARPE = 0.30
POST_L1_SCALE = 1.8
ANN = float(np.sqrt(252.0))


def _annual_sharpe(arr: np.ndarray) -> float:
    a = arr[np.isfinite(arr)]
    if a.size < 30:
        return 0.0
    sd = float(a.std(ddof=0))
    if sd <= 0.0:
        return 0.0
    return float(a.mean() / sd) * ANN


def _max_drawdown(returns: pd.Series) -> float:
    r = returns.fillna(0.0)
    if len(r) == 0:
        return 1.0
    eq = (1.0 + r).cumprod()
    peak = eq.cummax()
    dd = (eq / peak) - 1.0
    mn = dd.min()
    if not np.isfinite(mn):
        return 1.0
    return float(-mn)


def _load_pool(run_id: str):
    ids = select_is_submittable(run_id)
    if ids is None or len(ids) < 8:
        ids = select_all_alphas(run_id)
    ids = list(ids)
    signs = member_signs_ic(run_id, ids)
    R = load_member_is_returns(run_id, ids, signs=signs)
    return R, signs


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    R, _signs = _load_pool(RUN_ID)
    ids = list(R.columns)
    if len(ids) < 2:
        return ids

    # Drawdown discipline: keep alphas with max IS DD <= DD_MAX
    dd_map = {a: _max_drawdown(R[a]) for a in ids}
    kept = [a for a in ids if dd_map[a] <= DD_MAX]
    if len(kept) < 4:
        # Relax: take the 30 most drawdown-disciplined alphas
        kept = sorted(ids, key=lambda x: dd_map[x])[:30]

    Rk = R[kept]
    sharpe_map = {a: _annual_sharpe(Rk[a].dropna().values) for a in kept}
    ordered = [a for a in sorted(kept, key=lambda x: sharpe_map[x], reverse=True)
               if sharpe_map[a] > 0.0]
    if len(ordered) < 2:
        # nothing positive after filter; fall back to top-N by raw Sharpe
        ordered = sorted(kept, key=lambda x: sharpe_map[x], reverse=True)

    # Greedy Gram-Schmidt: add a candidate only if its residual Sharpe is high
    selected: list[str] = [ordered[0]]
    used: list[np.ndarray] = [Rk[ordered[0]].fillna(0.0).values.astype(float)]

    for cand in ordered[1:]:
        if len(selected) >= TARGET_N:
            break
        y = Rk[cand].fillna(0.0).values.astype(float)
        if y.size != used[0].size:
            continue
        X = np.column_stack(used)
        try:
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
            resid = y - X @ beta
        except np.linalg.LinAlgError:
            continue
        res_sh = _annual_sharpe(resid)
        if res_sh < MIN_RESID_SHARPE:
            continue
        selected.append(cand)
        used.append(resid)

    if len(selected) < 2:
        # safety: ensure runner gets at least 2 ids
        pad = [a for a in ordered if a not in selected]
        selected = (selected + pad)[: max(2, min(TARGET_N, len(ordered)))]
    return selected


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    avail = [m for m in member_ids if m in R.columns]

    if len(avail) < 2:
        base = member_ids[: max(2, len(member_ids))]
        coef = {m: 1.0 for m in base}
        coef = normalize_coefficients(coef, "l1")
        coef = {k: float(v) * POST_L1_SCALE for k, v in coef.items()}
        for m in member_ids:
            coef.setdefault(m, 0.0)
        return coef

    # Sharpe-weighted (residual orthogonality already enforced in selection)
    sharpe = {a: max(_annual_sharpe(R[a].dropna().values), 0.0) for a in avail}
    if sum(sharpe.values()) <= 0.0:
        sharpe = {a: 1.0 for a in avail}

    # IC-aligned signs so each member contributes its deployable direction
    coef = apply_signs(sharpe, signs)

    # L1 normalize (Sigma|c|=1), then scale up to lift composite gross exposure
    # into the productive [0.5, 0.9] band (runner row-L1 clip is the safety).
    coef = normalize_coefficients(coef, "l1")
    coef = {k: float(v) * POST_L1_SCALE for k, v in coef.items()}

    for m in member_ids:
        coef.setdefault(m, 0.0)
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