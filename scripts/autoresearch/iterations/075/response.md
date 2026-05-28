I'll generate a cov-FREE greedy composite using the Sharpe-rank + orthogonality-rank method (the third unexplored cov-free method from the menu), combined with the leaderboard-winning ingredients: per-year IS stability filter, drawdown discipline, correlation dedup, sign-aware combination, and explicit gross-exposure rescaling. This avoids the 1/σ underweighting trap from cov-inversion optimizers and is genuinely new (not Gram-Schmidt, not cluster-centroid, not pure 1/N).

Rationale:
- **Cov-free**: bypasses Σ⁻¹ which has been producing mean row L1 ≈ 0.05 and OS Sharpe ceilings ~0.8.
- **Sharpe-rank + orth-rank greedy** (Choueifaty-style diversification, but rank-based rather than ratio-based): picks members that are both high-quality AND orthogonal to prior picks.
- **Per-year stability + DD<22%**: regime-aware filter from the leaderboard winning pattern.
- **Equal-weight at n=7** with explicit gross rescale to L1≈0.70: avoids the dilution trap and the underweighting trap simultaneously.

```python COMPOSITE_FILE
"""Cov-free greedy composite via combined Sharpe-rank + orthogonality-rank ranking, with per-year IS stability filter, drawdown discipline, and explicit gross-exposure rescaling (Choueifaty-inspired diversification, rank-based)."""
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
    member_is_sharpe,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_075"
COMPOSITION_NOTE = "rank_sharpe_plus_orth_greedy_yearstable_dd22_n7_gross070"

RUN_ID = "run_2026_05_c"
TARGET_N = 7
DD_THRESHOLD = 0.22
DEDUP_RHO = 0.85
TARGET_GROSS = 0.70


def _max_drawdown(equity: pd.Series) -> float:
    if len(equity) == 0:
        return 1.0
    cummax = equity.cummax()
    dd = (equity - cummax) / cummax.replace(0, np.nan)
    m = dd.min()
    if not np.isfinite(m):
        return 1.0
    return float(abs(m))


def _passes_year_stability(returns: pd.Series) -> bool:
    if returns.empty:
        return False
    idx = returns.index
    if not hasattr(idx, "year"):
        try:
            idx = pd.to_datetime(idx)
        except Exception:
            return True
    try:
        years = np.asarray(idx.year)
    except AttributeError:
        return True
    unique_years = sorted(set(years.tolist()))
    if len(unique_years) < 2:
        return True
    for y in unique_years:
        mask = years == y
        sub = returns[mask]
        if len(sub) < 20:
            continue
        if sub.mean() <= 0:
            return False
    return True


def _candidate_universe() -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if len(ids) < 4:
        ids = select_all_alphas(RUN_ID)
    return list(ids)


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    candidate_ids = _candidate_universe()
    if len(candidate_ids) < 2:
        return candidate_ids[:2]

    signs = member_signs_ic(RUN_ID, candidate_ids)
    R = load_member_is_returns(RUN_ID, candidate_ids, signs=signs)
    if R.empty or len(R.columns) < 2:
        return list(R.columns)[:2] if len(R.columns) else candidate_ids[:2]

    # Per-year stability + drawdown filter, recomputing IS Sharpe on signed returns
    sharpes: dict[str, float] = {}
    survivors: list[str] = []
    for aid in R.columns:
        ret = R[aid].dropna()
        if len(ret) < 30:
            continue
        std = ret.std()
        if not np.isfinite(std) or std <= 0:
            continue
        sh = float(ret.mean() / std) * math.sqrt(252)
        if not np.isfinite(sh) or sh <= 0:
            continue
        equity = (1.0 + ret).cumprod()
        dd = _max_drawdown(equity)
        if dd > DD_THRESHOLD:
            continue
        if not _passes_year_stability(ret):
            continue
        sharpes[aid] = sh
        survivors.append(aid)

    # Fallback if filters too aggressive
    if len(survivors) < 4:
        bulk_sh = member_is_sharpe(RUN_ID, list(R.columns))
        survivors = [a for a in R.columns if float(bulk_sh.get(a, 0.0)) > 0]
        sharpes = {a: float(bulk_sh.get(a, 0.0)) for a in survivors}
    if len(survivors) < 2:
        return list(R.columns)[:max(2, min(2, len(R.columns)))]

    # Correlation dedup at rho=0.85, ranked by Sharpe
    try:
        kept = correlation_dedup(R[survivors], DEDUP_RHO, keep_metric=sharpes)
    except Exception:
        kept = survivors
    if len(kept) < 2:
        kept = survivors

    # Greedy: rank_sharpe (desc) + rank_orthogonality (asc mean |corr| vs selected)
    Rk = R[kept]
    corr = Rk.corr().abs()

    remaining = list(kept)
    seed = max(remaining, key=lambda a: sharpes.get(a, -np.inf))
    selected = [seed]
    remaining.remove(seed)

    while len(selected) < TARGET_N and remaining:
        sh_vals = np.array([sharpes.get(a, -np.inf) for a in remaining])
        order_sh = np.argsort(-sh_vals)
        rank_sh = np.empty(len(remaining), dtype=float)
        rank_sh[order_sh] = np.arange(len(remaining), dtype=float)

        mean_corr = np.array([
            float(corr.loc[a, selected].mean()) if selected else 0.0
            for a in remaining
        ])
        order_orth = np.argsort(mean_corr)
        rank_orth = np.empty(len(remaining), dtype=float)
        rank_orth[order_orth] = np.arange(len(remaining), dtype=float)

        combined = 0.5 * rank_sh + 0.5 * rank_orth
        best_idx = int(np.argmin(combined))
        selected.append(remaining.pop(best_idx))

    if len(selected) < 2:
        extras = [a for a in R.columns if a not in selected]
        selected.extend(extras[: max(0, 2 - len(selected))])

    return selected


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    loaded = [a for a in member_ids if a in R.columns]
    if not loaded:
        return {a: 1.0 / max(1, len(member_ids)) for a in member_ids}

    # Equal-weight base (cov-free, native exposure preserved)
    base = {a: 1.0 for a in loaded}
    coef = apply_signs(base, signs)

    # Estimate composite gross via per-member weight-stream volatility
    sigma_a = R[loaded].std()
    abs_c = np.array([abs(coef.get(a, 0.0)) for a in loaded])
    sig_v = np.array([float(sigma_a.get(a, 0.0)) for a in loaded])
    sig_v = np.where(np.isfinite(sig_v), sig_v, 0.0)
    est_gross = float((abs_c * sig_v).sum())

    if est_gross > 1e-9:
        scale = TARGET_GROSS / est_gross
        # Safety clamp: do not scale by more than 30x or less than 0.1x
        scale = float(np.clip(scale, 0.1, 30.0))
        coef = {a: v * scale for a, v in coef.items()}
    else:
        # Fallback: aggressive multiplier so gross is not anemic
        mult = 12.0 / max(1, len(loaded))
        coef = {a: v * mult for a, v in coef.items()}

    for a in member_ids:
        coef.setdefault(a, 0.0)
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
```
