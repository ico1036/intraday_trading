"""Borda-rank greedy composite (cov-free): fuse IS-Sharpe rank with
orthogonality rank to pick k=6 sign-aligned members; equal-magnitude
weights with gross post-scaling. Cites DeMiguel, Garlappi & Uppal (2009),
"Optimal Versus Naive Diversification" (RFS 22:5) and Borda (1781)
rank aggregation."""
from __future__ import annotations
import argparse
import math
import numpy as np
import pandas as pd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    correlation_dedup,
    member_signs_ic,
    apply_signs,
    select_is_submittable,
    select_all_alphas,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_115_borda_rank_sharpe_x_orthogonality_k6_yea"
COMPOSITION_NOTE = "borda_rank_sharpe_x_orthogonality_k6_yearstable_dd22_dedup085"

RUN_ID = "run_2026_05_c"
TARGET_K = 6
MAX_DD_THRESHOLD = -0.22
DEDUP_RHO = 0.85
GROSS_SCALE = 5.0
MIN_YEAR_OBS = 30


def _years(index: pd.Index) -> np.ndarray:
    if hasattr(index, "year"):
        return np.asarray(index.year)
    return np.asarray(pd.to_datetime(index).year)


def _per_year_sharpe_positive(returns: pd.Series) -> bool:
    r = returns.dropna()
    if r.empty:
        return False
    df = pd.DataFrame({"r": r.values, "y": _years(r.index)})
    saw_any = False
    for _y, grp in df.groupby("y"):
        if len(grp) < MIN_YEAR_OBS:
            continue
        saw_any = True
        mu = float(grp["r"].mean())
        sd = float(grp["r"].std())
        if sd <= 0.0 or mu / sd <= 0.0:
            return False
    return saw_any


def _max_drawdown(returns: pd.Series) -> float:
    r = returns.fillna(0.0)
    if r.empty:
        return 0.0
    eq = (1.0 + r).cumprod()
    peak = eq.cummax()
    dd = (eq / peak) - 1.0
    return float(dd.min())


def _sharpe_map(R: pd.DataFrame) -> dict[str, float]:
    out: dict[str, float] = {}
    ann = math.sqrt(365.0)
    for a in R.columns:
        sd = float(R[a].std())
        out[a] = float(R[a].mean() / sd * ann) if sd > 0 else -math.inf
    return out


def _borda_greedy(R: pd.DataFrame, sharpe: dict[str, float], k: int) -> list[str]:
    cols = list(R.columns)
    if not cols:
        return []
    ordered = sorted(cols, key=lambda a: -sharpe.get(a, -math.inf))
    picked: list[str] = [ordered[0]]
    pool: list[str] = [a for a in ordered if a != picked[0]]
    corr = R.corr().abs()
    while len(picked) < k and pool:
        sharpe_sorted = sorted(pool, key=lambda x: -sharpe.get(x, -math.inf))
        s_rank = {a: i for i, a in enumerate(sharpe_sorted)}
        ortho_score = {a: float(corr.loc[a, picked].mean()) for a in pool}
        ortho_sorted = sorted(pool, key=lambda x: ortho_score[x])
        o_rank = {a: i for i, a in enumerate(ortho_sorted)}
        combined = {a: 0.5 * s_rank[a] + 0.5 * o_rank[a] for a in pool}
        nxt = min(pool, key=lambda a: combined[a])
        picked.append(nxt)
        pool = [a for a in pool if a != nxt]
    return picked


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if len(ids) < TARGET_K + 2:
        ids = select_all_alphas(RUN_ID)
    if len(ids) < TARGET_K + 2 and "alpha_id" in alpha_index.columns:
        ids = list(alpha_index["alpha_id"].astype(str).unique())
    if len(ids) < 2:
        return ids

    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)

    if R.empty or R.shape[1] < 2:
        if "is_sharpe" in alpha_index.columns:
            srt = alpha_index.sort_values("is_sharpe", ascending=False)
            return list(srt["alpha_id"].astype(str).head(TARGET_K))
        return ids[:TARGET_K]

    # Year-stability: positive Sharpe in every sufficiently-populated IS year
    stable = [a for a in R.columns if _per_year_sharpe_positive(R[a])]
    if len(stable) >= TARGET_K + 1:
        R = R[stable]

    # Drawdown discipline: keep max IS DD shallower than threshold
    dd_ok = [a for a in R.columns if _max_drawdown(R[a]) > MAX_DD_THRESHOLD]
    if len(dd_ok) >= TARGET_K + 1:
        R = R[dd_ok]
    else:
        # Relax: keep the K*4 shallowest-drawdown survivors instead of collapsing
        ranked_dd = sorted(R.columns, key=lambda a: _max_drawdown(R[a]), reverse=True)
        R = R[ranked_dd[: max(TARGET_K * 4, 16)]]

    sharpe = _sharpe_map(R)

    # Correlation dedup at ρ=0.85, keyed by IS Sharpe (post sign-flip)
    try:
        kept = correlation_dedup(R, threshold=DEDUP_RHO, keep_metric=sharpe)
    except Exception:
        kept = list(R.columns)
    if len(kept) >= 2:
        R = R[kept]
        sharpe = _sharpe_map(R)

    # If dedup over-pruned, top-up with the best remaining by Sharpe
    if R.shape[1] < TARGET_K:
        all_signed = load_member_is_returns(RUN_ID, ids, signs=signs)
        avail = [a for a in all_signed.columns if a not in R.columns]
        avail.sort(key=lambda a: -(all_signed[a].mean() / all_signed[a].std())
                   if all_signed[a].std() > 0 else math.inf)
        need = TARGET_K - R.shape[1]
        extras = avail[:need]
        if extras:
            R = pd.concat([R, all_signed[extras]], axis=1).dropna(how="all")
            sharpe = _sharpe_map(R)

    picked = _borda_greedy(R, sharpe, TARGET_K)
    if len(picked) < 2:
        # Last-ditch fallback: raw top-K by IS Sharpe from the pool
        picked = sorted(R.columns, key=lambda a: -sharpe.get(a, -math.inf))[:TARGET_K]
    return picked


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    signs = member_signs_ic(RUN_ID, member_ids)
    base: dict[str, float] = {a: 1.0 for a in member_ids}
    base = apply_signs(base, signs)
    c = normalize_coefficients(base, "l1")
    c = {k: float(v) * GROSS_SCALE for k, v in c.items()}
    return c


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