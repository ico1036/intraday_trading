"""Correlation-rank + Sharpe-rank greedy fusion: cov-free, year-stable, DD-disciplined (Eckles & Sun 2024 rank-aggregation; Fortin & Hlouskova 2011 diversity-relevance)."""
from __future__ import annotations
import argparse
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

COMPOSITE_ID = "auto_066_corr_rank_sharpe_rank_greedy_yearstable"
COMPOSITION_NOTE = "corr_rank_sharpe_rank_greedy_yearstable_ddlt22_top7_gross065"

RUN_ID = "run_2026_05_c"
TARGET_N = 7
TARGET_GROSS = 0.65
MAX_DD_THRESHOLD = 0.22
MIN_PER_YEAR_SHARPE = 0.0
SCALE_CAP = 30.0


def _per_year_sharpe(returns: pd.Series) -> dict[int, float]:
    out: dict[int, float] = {}
    if returns.empty:
        return out
    for year, r in returns.groupby(returns.index.year):
        sd = float(r.std())
        if sd <= 1e-12 or len(r) < 20:
            continue
        out[int(year)] = float(r.mean() / sd * np.sqrt(365.0))
    return out


def _max_drawdown(returns: pd.Series) -> float:
    if returns.empty:
        return 1.0
    eq = (1.0 + returns.fillna(0.0)).cumprod()
    peak = eq.cummax()
    dd = (eq / peak - 1.0).min()
    return float(abs(dd))


def _full_sharpe(returns: pd.Series) -> float:
    r = returns.dropna()
    sd = float(r.std())
    if sd <= 1e-12:
        return 0.0
    return float(r.mean() / sd * np.sqrt(365.0))


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    candidates = select_is_submittable(RUN_ID)
    if not candidates:
        candidates = list(alpha_index.get("alpha_id", pd.Series(dtype=str)))
    if not candidates:
        return []

    signs = member_signs_ic(RUN_ID, candidates)
    R = load_member_is_returns(RUN_ID, candidates, signs=signs)
    if R is None or R.shape[1] < 2:
        return []

    # Filter on year-stability + DD discipline + positive full-window Sharpe.
    keep: list[str] = []
    sharpe_map: dict[str, float] = {}
    for aid in R.columns:
        ser = R[aid].dropna()
        if len(ser) < 60:
            continue
        py = _per_year_sharpe(ser)
        if len(py) < 2:
            continue
        if min(py.values()) < MIN_PER_YEAR_SHARPE:
            continue
        if _max_drawdown(ser) > MAX_DD_THRESHOLD:
            continue
        s = _full_sharpe(ser)
        if s <= 0.0:
            continue
        sharpe_map[aid] = s
        keep.append(aid)

    # Relax year-stability if too few survive.
    if len(keep) < TARGET_N:
        keep = []
        sharpe_map = {}
        for aid in R.columns:
            ser = R[aid].dropna()
            if len(ser) < 60:
                continue
            if _max_drawdown(ser) > MAX_DD_THRESHOLD:
                continue
            s = _full_sharpe(ser)
            if s <= 0.0:
                continue
            sharpe_map[aid] = s
            keep.append(aid)

    # Final fallback: top-N by raw IS Sharpe across all loaded columns.
    if len(keep) < 2:
        sharpe_map = {c: _full_sharpe(R[c]) for c in R.columns}
        keep = [a for a in sorted(sharpe_map, key=lambda x: sharpe_map[x], reverse=True)
                if sharpe_map[a] > 0.0]
        if len(keep) < 2:
            keep = sorted(sharpe_map, key=lambda x: sharpe_map[x], reverse=True)
        return keep[: max(2, min(TARGET_N, len(keep)))]

    Rk = R[keep].fillna(0.0)
    corr = Rk.corr().fillna(0.0)
    sharpe_rank = pd.Series(sharpe_map).rank(ascending=False)  # 1 == best Sharpe

    # Greedy rank-fusion: seed with top-Sharpe, then add the candidate with
    # lowest 0.5*sharpe_rank + 0.5*orthogonality_rank (mean |corr| asc).
    picks: list[str] = [str(sharpe_rank.idxmin())]
    remaining = [a for a in keep if a != picks[0]]

    while len(picks) < TARGET_N and remaining:
        mean_abs = {a: float(corr.loc[a, picks].abs().mean()) for a in remaining}
        orth_rank = pd.Series(mean_abs).rank(ascending=True)  # 1 == most orthogonal
        score = 0.5 * sharpe_rank.loc[remaining] + 0.5 * orth_rank
        nxt = str(score.idxmin())
        picks.append(nxt)
        remaining.remove(nxt)

    return picks


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    loaded = [m for m in member_ids if (R is not None and m in R.columns)]
    if not loaded:
        # Last-ditch equal weight with no sign info.
        equal = {m: 1.0 for m in member_ids}
        c0 = normalize_coefficients(equal, "l1")
        return {m: float(c0[m]) * TARGET_GROSS * float(len(member_ids)) for m in member_ids}

    # Cov-FREE: equal weight, sign-aligned, then L1-normalized.
    raw = {m: 1.0 for m in loaded}
    raw_signed = apply_signs(raw, signs)
    c = normalize_coefficients(raw_signed, "l1")  # Σ|c| = 1

    # Heuristic gross rescale: proxy gross-exposure with Σ|c| · σ_return.
    sigma = R[loaded].std()
    est_gross = float(sum(abs(c[m]) * float(sigma.get(m, 0.0)) for m in loaded))
    if est_gross > 1e-9:
        scale = TARGET_GROSS / est_gross
    else:
        scale = TARGET_GROSS * float(len(loaded))
    scale = float(min(max(scale, 1.0), SCALE_CAP))

    return {m: float(c[m]) * scale for m in loaded}


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