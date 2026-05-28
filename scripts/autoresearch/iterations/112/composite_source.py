"""Greedy corr-rank + Sharpe-rank composite (cov-free, regime-aware).

Method (Lohre/Opfer/Orszag 2014 style diversification ranking, blended with
Sharpe ranking a la Lopez de Prado AFML ch.7): order members by IS Sharpe,
then greedily add the candidate that minimizes a 50/50 blend of
(Sharpe-rank desc) and (mean |corr| with already-picked, asc). Bypasses any
covariance inversion -> avoids the 1/sigma underweighting trap.

Regime guards on the universe: max IS drawdown < 25% AND per-year IS
Sharpe > 0 in every IS sub-year (regime-conditional robustness). Final
sizing: equal coefficients, L1-normalized then scaled by 2x so the runner's
row-L1 clamp lands the realized mean gross in [0.5, 0.85].
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

COMPOSITE_ID = "auto_112_corr_rank_sharpe_rank_greedy_n8_yearstab"
COMPOSITION_NOTE = "corr_rank_sharpe_rank_greedy_n8_yearstable_dd25_gross_x2"
RUN_ID = "run_2026_05_c"
N_TARGET = 8
DD_MAX = 0.25
GROSS_MULT = 2.0  # post L1-normalize; runner clamps row-L1 <= 1


def _max_drawdown(r: pd.Series) -> float:
    r2 = r.fillna(0.0)
    cum = (1.0 + r2).cumprod()
    peak = cum.cummax()
    dd = (cum / peak) - 1.0
    val = dd.min()
    if not np.isfinite(val):
        return 0.0
    return float(-val)


def _annualized_sharpe(r: pd.Series) -> float:
    s = r.dropna()
    if s.empty:
        return -np.inf
    sd = float(s.std(ddof=0))
    if not np.isfinite(sd) or sd <= 0:
        return -np.inf
    return float(s.mean()) / sd * np.sqrt(252.0)


def _year_stable(r: pd.Series) -> bool:
    s = r.dropna()
    if s.empty:
        return False
    idx = s.index
    if not isinstance(idx, pd.DatetimeIndex):
        try:
            idx = pd.DatetimeIndex(pd.to_datetime(idx))
            s = pd.Series(s.values, index=idx)
        except Exception:
            return False
    years = idx.year
    uniq = np.unique(years)
    if len(uniq) < 2:
        return True  # not enough sub-years to test
    for y in uniq:
        sub = s[years == y]
        if len(sub) < 20:
            continue  # too short to judge
        sd = float(sub.std(ddof=0))
        if not np.isfinite(sd) or sd <= 0:
            return False
        sh = float(sub.mean()) / sd * np.sqrt(252.0)
        if not np.isfinite(sh) or sh <= 0.0:
            return False
    return True


def _build_pool() -> tuple[list[str], pd.DataFrame, dict[str, float]]:
    try:
        ids = list(select_is_submittable(RUN_ID))
    except Exception:
        ids = []
    if len(ids) < 10:
        try:
            ids = list(select_all_alphas(RUN_ID))
        except Exception:
            pass
    ids = [a for a in dict.fromkeys(ids)]  # dedup, preserve order
    if not ids:
        return [], pd.DataFrame(), {}

    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    R = R.dropna(axis=1, how="all")
    if R.empty:
        return [], pd.DataFrame(), {}

    cols = list(R.columns)
    kept: list[str] = []
    sharpes: dict[str, float] = {}
    for c in cols:
        col = R[c]
        sh = _annualized_sharpe(col)
        if not np.isfinite(sh) or sh <= 0.0:
            continue
        if _max_drawdown(col) > DD_MAX:
            continue
        if not _year_stable(col):
            continue
        kept.append(c)
        sharpes[c] = sh

    # Fallback: relax year-stability if too aggressive
    if len(kept) < N_TARGET:
        kept2: list[str] = []
        sharpes2: dict[str, float] = {}
        for c in cols:
            col = R[c]
            sh = _annualized_sharpe(col)
            if not np.isfinite(sh) or sh <= 0.0:
                continue
            if _max_drawdown(col) > DD_MAX:
                continue
            kept2.append(c)
            sharpes2[c] = sh
        if len(kept2) > len(kept):
            kept, sharpes = kept2, sharpes2

    # Last-resort fallback: positive Sharpe only
    if len(kept) < 2:
        kept = []
        sharpes = {}
        for c in cols:
            sh = _annualized_sharpe(R[c])
            if not np.isfinite(sh) or sh <= 0.0:
                continue
            kept.append(c)
            sharpes[c] = sh

    if not kept:
        return [], pd.DataFrame(), {}
    return kept, R[kept], sharpes


def _greedy_corr_sharpe(
    kept: list[str], R: pd.DataFrame, sharpes: dict[str, float]
) -> list[str]:
    if not kept:
        return []
    sorted_by_sh = sorted(kept, key=lambda x: -sharpes.get(x, -np.inf))
    picked: list[str] = [sorted_by_sh[0]]
    candidates: list[str] = list(sorted_by_sh[1:])
    if not candidates:
        return picked

    try:
        corr = R.corr().fillna(0.0)
    except Exception:
        # Degenerate corr -> just return top-N by Sharpe
        return sorted_by_sh[: min(N_TARGET, len(sorted_by_sh))]

    n = min(N_TARGET, len(kept))
    while len(picked) < n and candidates:
        sh_sorted = sorted(candidates, key=lambda x: -sharpes.get(x, -np.inf))
        sh_rank = {c: i for i, c in enumerate(sh_sorted)}
        mean_abs_corr: dict[str, float] = {}
        for c in candidates:
            try:
                vals = corr.loc[c, picked].abs()
                m = float(vals.mean()) if len(vals) else 0.0
            except Exception:
                m = 1.0
            if not np.isfinite(m):
                m = 1.0
            mean_abs_corr[c] = m
        orth_sorted = sorted(candidates, key=lambda x: mean_abs_corr[x])
        orth_rank = {c: i for i, c in enumerate(orth_sorted)}
        score = {c: 0.5 * sh_rank[c] + 0.5 * orth_rank[c] for c in candidates}
        nxt = min(candidates, key=lambda c: score[c])
        picked.append(nxt)
        candidates.remove(nxt)
    return picked


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    kept, R, sharpes = _build_pool()
    picks = _greedy_corr_sharpe(kept, R, sharpes)
    if len(picks) < 2 and kept:
        picks = kept[: min(N_TARGET, len(kept))]
        if len(picks) < 2:
            picks = kept[:2]
    return picks


def member_weights(
    member_ids: list[str], alpha_index: pd.DataFrame
) -> dict[str, float]:
    ids = list(member_ids)
    if not ids:
        return {}
    signs = member_signs_ic(RUN_ID, ids)
    base: dict[str, float] = {m: 1.0 for m in ids}
    base = apply_signs(base, signs)
    base = normalize_coefficients(base, "l1")  # Sum |c| = 1
    out: dict[str, float] = {m: float(v) * GROSS_MULT for m, v in base.items()}
    return out


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