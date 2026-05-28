"""Cov-free Sharpe-rank + orthogonality-rank greedy composite (Choueifaty spirit).

Method:
- Sign-align members via IC dead-band (member_signs_ic) before any return math.
- Regime-stability filters: per-year IS Sharpe > 0 across each sub-year
  AND max IS drawdown < 25%. Empirical leaderboard ingredients.
- Greedy 8-member selection with rank-blend score (Choueifaty 2008
  diversification-ratio spirit, but rank-based to avoid Σ⁻¹ noise):
      score(c) = 0.5 * rank_IS_Sharpe_desc(c)
               + 0.5 * rank_mean_abs_corr_with_prior_picks_asc(c)
  Seed with the highest-IS-Sharpe alpha; iterate greedily.
- Equal weight, sign-align, then POST-SCALE coefficients so estimated gross
  (Σ|cᵢ|·σᵢ) ≈ 0.65. This breaks the "mean row L1 ≈ 0.05" failure mode of
  cov-based optimizers (Σ⁻¹·μ has 1/σ bias → underweight by 10×).

Cov inversion is deliberately avoided per the harness diagnostic: every
tangency / min-var attempt to date has left ≥90 % of the risk budget unused.
"""
from __future__ import annotations
import argparse
import numpy as np
import pandas as pd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    member_signs_ic,
    apply_signs,
    select_is_submittable,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_104_sharpe_orth_rank_greedy_n8_yearstable_dd"
COMPOSITION_NOTE = "sharpe_orth_rank_greedy_n8_yearstable_dd25_grossp65"
RUN_ID = "run_2026_05_c"
TARGET_GROSS = 0.65
N_PICK = 8
DD_LIMIT = 0.25
SCALE_FLOOR = 3.0
SCALE_CAP = 15.0


def _max_dd(equity: np.ndarray) -> float:
    if equity.size == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    safe_peak = np.where(peak == 0.0, 1.0, peak)
    dd = (equity - peak) / safe_peak
    return float(np.min(dd))


def _sharpe(s: pd.Series) -> float:
    s = s.dropna()
    if len(s) < 30:
        return -9.0
    sd = float(s.std())
    if not np.isfinite(sd) or sd <= 0.0:
        return -9.0
    return float(s.mean() / sd * np.sqrt(252.0))


def _year_stable(returns: pd.Series, min_sh: float = 0.0) -> bool:
    if returns.empty or len(returns) < 60:
        return False
    try:
        idx = pd.to_datetime(returns.index)
    except Exception:
        return True
    years = np.asarray(idx.year)
    uniq = np.unique(years)
    if len(uniq) < 2:
        return True
    vals = returns.values
    for y in uniq:
        mask = years == y
        sub = vals[mask]
        if sub.size < 20:
            continue
        sd = float(np.std(sub, ddof=1))
        if not np.isfinite(sd) or sd <= 0.0:
            return False
        sh = float(np.mean(sub)) / sd * np.sqrt(252.0)
        if sh <= min_sh:
            return False
    return True


def _filter_regime(R: pd.DataFrame) -> list[str]:
    kept: list[str] = []
    for a in R.columns:
        s = R[a].dropna()
        if len(s) < 60:
            continue
        eq = (1.0 + s.values).cumprod()
        if _max_dd(eq) < -DD_LIMIT:
            continue
        if not _year_stable(s):
            continue
        kept.append(a)
    return kept


def _filter_dd_only(R: pd.DataFrame) -> list[str]:
    kept: list[str] = []
    for a in R.columns:
        s = R[a].dropna()
        if len(s) < 60:
            continue
        eq = (1.0 + s.values).cumprod()
        if _max_dd(eq) >= -DD_LIMIT:
            kept.append(a)
    return kept


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = list(select_is_submittable(RUN_ID))
    if len(ids) < N_PICK * 2 and "alpha_id" in alpha_index.columns:
        extra = [str(x) for x in alpha_index["alpha_id"].astype(str).tolist()]
        ids = list(dict.fromkeys(ids + extra))
    if not ids:
        return []
    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.empty or R.shape[1] < 2:
        cols = [] if (R is None or R.empty) else list(R.columns)
        return cols[: max(2, len(cols))] if cols else []
    R = R.dropna(axis=1, thresh=int(0.5 * len(R)))
    if R.shape[1] < 2:
        return list(R.columns)
    sharpe_full = {c: _sharpe(R[c]) for c in R.columns}
    if R.shape[1] < N_PICK:
        ranked = sorted(R.columns, key=lambda c: -sharpe_full.get(c, -9.0))
        return ranked[: max(2, len(ranked))]
    kept = _filter_regime(R)
    if len(kept) < N_PICK:
        kept = _filter_dd_only(R)
    if len(kept) < N_PICK:
        kept = list(R.columns)
    Rk = R[kept].fillna(0.0)
    sharpe_map = {c: sharpe_full.get(c, _sharpe(R[c])) for c in kept}
    sorted_by_sh = sorted(kept, key=lambda c: -sharpe_map.get(c, -9.0))
    rank_sharpe = {c: i + 1 for i, c in enumerate(sorted_by_sh)}
    try:
        corr = Rk.corr().fillna(0.0)
    except Exception:
        corr = pd.DataFrame(np.eye(len(kept)), index=kept, columns=kept)
    picks: list[str] = [sorted_by_sh[0]]
    remaining = [c for c in kept if c not in picks]
    while len(picks) < N_PICK and remaining:
        mean_abs_corr: dict[str, float] = {}
        for c in remaining:
            vals: list[float] = []
            for p in picks:
                try:
                    vals.append(abs(float(corr.loc[c, p])))
                except Exception:
                    vals.append(0.0)
            mean_abs_corr[c] = float(np.mean(vals)) if vals else 0.0
        sorted_by_corr = sorted(remaining, key=lambda c: mean_abs_corr.get(c, 0.0))
        rank_corr = {c: i + 1 for i, c in enumerate(sorted_by_corr)}
        scores = {
            c: 0.5 * rank_sharpe.get(c, len(kept) + 1)
            + 0.5 * rank_corr.get(c, len(kept) + 1)
            for c in remaining
        }
        best = min(scores, key=lambda c: scores[c])
        picks.append(best)
        remaining.remove(best)
    if len(picks) < 2:
        picks = sorted_by_sh[: min(2, len(sorted_by_sh))]
    return picks


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    signs = member_signs_ic(RUN_ID, member_ids)
    base = {a: 1.0 for a in member_ids}
    coef = normalize_coefficients(base, "l1")
    coef = apply_signs(coef, signs)
    try:
        R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    except Exception:
        R = pd.DataFrame()
    if R is None or R.empty:
        return {k: v * SCALE_FLOOR for k, v in coef.items()}
    loaded = [c for c in R.columns if c in coef]
    if not loaded:
        return {k: v * SCALE_FLOOR for k, v in coef.items()}
    sigma_a = R[loaded].std()
    c_arr = np.array([coef[a] for a in loaded], dtype=float)
    s_arr = sigma_a.reindex(loaded).fillna(0.0).values.astype(float)
    est_gross = float(np.sum(np.abs(c_arr) * s_arr))
    if est_gross > 1e-9 and np.isfinite(est_gross):
        scale = TARGET_GROSS / est_gross
        if not np.isfinite(scale):
            scale = SCALE_FLOOR
        scale = float(np.clip(scale, SCALE_FLOOR, SCALE_CAP))
    else:
        scale = SCALE_FLOOR
    return {k: v * scale for k, v in coef.items()}


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