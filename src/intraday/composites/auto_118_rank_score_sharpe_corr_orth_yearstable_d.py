"""Rank-based greedy composite (Sharpe-rank + corr-orthogonality rank) with
year-stability + drawdown discipline pre-filter; equal-weight on n=6, then
sigma-rescaled to target gross row L1 ~ 0.6.

Method: cov-FREE greedy selection. At each step pick argmin of
(0.5 * rank_IS_Sharpe_desc + 0.5 * rank_mean_abs_corr_asc) over the remaining
pool. Inspired by Choueifaty (2008) diversification ratio principle, but in
rank space to avoid cov inversion and the 1/sigma weighting trap that has
collapsed prior tangency/min-var attempts to mean gross ~ 0.05. Regime
robustness via per-calendar-year positive Sharpe filter and IS max-DD < 0.20.
"""
from __future__ import annotations

import argparse
import math
import numpy as np
import pandas as pd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    select_is_submittable,
    member_signs_ic,
    apply_signs,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_118_rank_score_sharpe_corr_orth_yearstable_d"
COMPOSITION_NOTE = "rank_score_sharpe_corr_orth_yearstable_dd20_top6_eqw_gross06"

RUN_ID = "run_2026_05_c"
TARGET_N = 6
TARGET_GROSS = 0.6
DD_MAX = 0.20
MIN_OBS = 60

_CACHE: dict = {}


def _max_drawdown(returns: pd.Series) -> float:
    r = returns.fillna(0.0).astype(float)
    cum = (1.0 + r).cumprod()
    peak = cum.cummax()
    dd = (cum / peak) - 1.0
    val = dd.min()
    if not np.isfinite(val):
        return 1.0
    return float(-val)


def _year_stable(returns: pd.Series) -> bool:
    s = returns.dropna()
    if s.empty:
        return False
    idx = s.index
    if not isinstance(idx, pd.DatetimeIndex):
        try:
            s = s.copy()
            s.index = pd.to_datetime(s.index)
        except Exception:
            return False
    years = s.groupby(s.index.year)
    seen = 0
    for _, grp in years:
        if len(grp) < 20:
            continue
        sd = grp.std()
        if sd == 0 or not np.isfinite(sd):
            return False
        sharpe = grp.mean() / sd * math.sqrt(252.0)
        if sharpe <= 0:
            return False
        seen += 1
    return seen >= 2


def _sharpe(returns: pd.Series) -> float:
    s = returns.dropna()
    if len(s) < MIN_OBS:
        return float("-inf")
    sd = s.std()
    if sd == 0 or not np.isfinite(sd):
        return float("-inf")
    return float(s.mean() / sd * math.sqrt(252.0))


def _greedy_rank_select(R: pd.DataFrame, is_sharpe: dict, n: int) -> list[str]:
    cols = list(R.columns)
    if not cols:
        return []
    seed = max(cols, key=lambda a: is_sharpe.get(a, float("-inf")))
    picked = [seed]
    remaining = [c for c in cols if c != seed]
    if not remaining:
        return picked
    corr_abs = R.corr().abs()
    while remaining and len(picked) < n:
        sharpe_series = pd.Series({a: is_sharpe.get(a, 0.0) for a in remaining})
        sharpe_rank = sharpe_series.rank(ascending=False, method="average")
        mean_corr = corr_abs.loc[remaining, picked].mean(axis=1)
        orth_rank = mean_corr.rank(ascending=True, method="average")
        score = 0.5 * sharpe_rank + 0.5 * orth_rank
        nxt = score.idxmin()
        picked.append(nxt)
        remaining.remove(nxt)
    return picked


def _prepare():
    if "members" in _CACHE:
        return _CACHE
    pool = select_is_submittable(RUN_ID) or []
    if len(pool) < 2:
        _CACHE.update(members=[], signs={}, R=pd.DataFrame(), is_sharpe={})
        return _CACHE
    signs = member_signs_ic(RUN_ID, pool)
    R_full = load_member_is_returns(RUN_ID, pool, signs=signs)
    if R_full is None or R_full.empty:
        _CACHE.update(members=[], signs=signs, R=pd.DataFrame(), is_sharpe={})
        return _CACHE
    keep = []
    sharpe_map: dict[str, float] = {}
    for c in R_full.columns:
        s = R_full[c]
        sh = _sharpe(s)
        if not np.isfinite(sh) or sh <= 0:
            continue
        dd = _max_drawdown(s)
        if dd > DD_MAX:
            continue
        if not _year_stable(s):
            continue
        sharpe_map[c] = sh
        keep.append(c)
    if len(keep) < 2:
        # Relax filters progressively.
        keep = []
        sharpe_map = {}
        for c in R_full.columns:
            sh = _sharpe(R_full[c])
            if not np.isfinite(sh) or sh <= 0:
                continue
            dd = _max_drawdown(R_full[c])
            if dd > 0.35:
                continue
            sharpe_map[c] = sh
            keep.append(c)
    if len(keep) < 2:
        keep = []
        sharpe_map = {}
        for c in R_full.columns:
            sh = _sharpe(R_full[c])
            if not np.isfinite(sh):
                continue
            sharpe_map[c] = sh
            keep.append(c)
        keep = sorted(keep, key=lambda a: -sharpe_map[a])[: max(TARGET_N * 4, 12)]
    R_keep = R_full[keep] if keep else R_full.iloc[:, :0]
    members = _greedy_rank_select(R_keep, sharpe_map, TARGET_N)
    _CACHE.update(members=members, signs=signs, R=R_full, is_sharpe=sharpe_map)
    return _CACHE


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    st = _prepare()
    members = list(st.get("members") or [])
    if len(members) >= 2:
        return members
    # Last-resort fallback: top-N by IS Sharpe over the whole submittable pool.
    pool = select_is_submittable(RUN_ID) or []
    if len(pool) < 2:
        return pool
    signs = member_signs_ic(RUN_ID, pool)
    R = load_member_is_returns(RUN_ID, pool, signs=signs)
    sharpes = {}
    for c in R.columns:
        sh = _sharpe(R[c])
        if np.isfinite(sh):
            sharpes[c] = sh
    top = [a for a, _ in sorted(sharpes.items(), key=lambda kv: -kv[1])[:TARGET_N]]
    _CACHE["members"] = top
    _CACHE["signs"] = signs
    _CACHE["R"] = R
    _CACHE["is_sharpe"] = sharpes
    return top


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    st = _prepare()
    signs = st.get("signs") or {}
    R = st.get("R")
    if R is None or R.empty:
        signs = member_signs_ic(RUN_ID, member_ids)
        R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    raw = {a: 1.0 for a in member_ids}
    raw = normalize_coefficients(raw, "l1")
    raw = apply_signs(raw, signs)
    sigma = {}
    for a in member_ids:
        if a in R.columns:
            sd = R[a].std()
            sigma[a] = float(sd) if (np.isfinite(sd) and sd > 0) else 0.01
        else:
            sigma[a] = 0.01
    est_gross = sum(abs(raw[a]) * sigma[a] for a in member_ids)
    if est_gross <= 1e-9:
        scale = 10.0
    else:
        scale = TARGET_GROSS / est_gross
    scale = float(min(max(scale, 1.0), 60.0))
    return {a: raw[a] * scale for a in member_ids}


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