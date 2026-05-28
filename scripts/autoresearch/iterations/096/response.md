Picking the **correlation-rank × Sharpe-rank greedy** composition method — a cov-FREE selector explicitly listed in the spec as never-attempted. It pairs ordinal aggregation of IS Sharpe with ordinal aggregation of mean |corr| against the already-picked set, so we avoid the 1/σ-weighting trap of every prior cov-based optimizer (which has been bottlenecking gross exposure at ~5% of budget). Concentrated n=6 to match the leaderboard sweet-spot (n∈[5,8]), pre-filtered by per-year IS Sharpe positivity (regime-conditional CSCV proxy, Bailey & López de Prado 2014/2017) and max DD < 25%. Equal-weighted post-selection (no Σ inversion), sign-aligned via IC, then explicitly rescaled to sum_|c|=3 so mean row L1 lands in the [0.5,0.8] target band. None of the auto_001..auto_022 idea families used pure rank-aggregation; this is fresh territory.

```python COMPOSITE_FILE
"""Correlation-rank × IS-Sharpe-rank greedy composite (cov-free), n=6, year-stable, DD<25%.

Method: cov-FREE greedy member selection by an ordinal composite score that
mixes 50% IS-Sharpe rank with 50% mean-|corr|-with-prior-picks rank
(Lopez de Prado-style rank aggregation; no Σ inversion, no 1/σ dilution).
Pre-filtered by per-year IS Sharpe positivity (regime-conditional CSCV
proxy, Bailey & Lopez de Prado 2014) and max IS drawdown < 25%.
Members are equal-weighted after IC-sign alignment, then explicitly
rescaled (sum|c|=3) to land composite mean row L1 in [0.5, 0.8] — the
band where individual top-alpha OS Sharpes (1.0+) translate into
composite OS rather than being clamped down to 0.05 gross.
"""
from __future__ import annotations
import argparse
import math
import pandas as pd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    member_signs_ic,
    apply_signs,
    select_is_submittable,
    select_all_alphas,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_096"
COMPOSITION_NOTE = "corr_rank_sharpe_rank_greedy_n6_yearstable_dd25_gross3"
RUN_ID = "run_2026_05_c"
TARGET_N = 6
MAX_DD_THRESHOLD = -0.25
RELAXED_DD_THRESHOLD = -0.40
TARGET_GROSS_SUM = 3.0  # sum_|c| ; post L1-normalize multiplier


def _per_year_sharpe_positive(s: pd.Series, min_obs: int = 20) -> bool:
    s = s.dropna()
    if s.empty:
        return False
    idx = pd.to_datetime(s.index)
    years = sorted(set(idx.year))
    if len(years) < 2:
        return float(s.mean()) > 0
    for y in years:
        yr = s[idx.year == y]
        if len(yr) < min_obs:
            continue
        sd = float(yr.std())
        if sd <= 0 or math.isnan(sd):
            return False
        if float(yr.mean()) <= 0:
            return False
    return True


def _max_drawdown(s: pd.Series) -> float:
    s = s.fillna(0.0)
    if s.empty:
        return 0.0
    cum = (1.0 + s).cumprod()
    peak = cum.cummax()
    return float((cum / peak - 1.0).min())


def _sharpe(s: pd.Series) -> float:
    s = s.dropna()
    if len(s) < 2:
        return 0.0
    sd = float(s.std())
    if sd <= 0 or math.isnan(sd):
        return 0.0
    val = float(s.mean()) / sd * math.sqrt(252.0)
    if math.isnan(val) or math.isinf(val):
        return 0.0
    return val


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    try:
        ids = select_is_submittable(RUN_ID)
    except Exception:
        ids = []
    if not ids or len(ids) < TARGET_N:
        try:
            ids = select_all_alphas(RUN_ID)
        except Exception:
            ids = []

    if not ids:
        if "alpha_id" in alpha_index.columns and "is_sharpe" in alpha_index.columns:
            return list(
                alpha_index.sort_values("is_sharpe", ascending=False)
                .head(TARGET_N)["alpha_id"].tolist()
            )
        return []

    signs = member_signs_ic(RUN_ID, ids)
    signs = {mid: int(signs.get(mid, 1)) for mid in ids}

    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.empty or R.shape[1] < 2:
        if "alpha_id" in alpha_index.columns and "is_sharpe" in alpha_index.columns:
            return list(
                alpha_index.sort_values("is_sharpe", ascending=False)
                .head(TARGET_N)["alpha_id"].tolist()
            )
        return ids[: max(TARGET_N, 2)]

    R.index = pd.to_datetime(R.index)

    # Stage 1: per-year Sharpe positivity + max DD < 25%
    stable: list[str] = []
    for c in R.columns:
        s = R[c].dropna()
        if len(s) < 50:
            continue
        if not _per_year_sharpe_positive(s):
            continue
        if _max_drawdown(s) < MAX_DD_THRESHOLD:
            continue
        stable.append(c)

    # Relax DD filter if too restrictive
    if len(stable) < TARGET_N * 2:
        relaxed: list[str] = []
        for c in R.columns:
            s = R[c].dropna()
            if len(s) < 50:
                continue
            if _max_drawdown(s) < RELAXED_DD_THRESHOLD:
                continue
            relaxed.append(c)
        if len(relaxed) >= TARGET_N:
            stable = relaxed

    if len(stable) < TARGET_N:
        stable = [c for c in R.columns if len(R[c].dropna()) >= 30]

    # Score by IS Sharpe; keep strictly positive
    sharpe_map: dict[str, float] = {c: _sharpe(R[c]) for c in stable}
    positive = [c for c in stable if sharpe_map[c] > 0.0]
    if len(positive) >= 2:
        stable = positive

    if len(stable) < 2:
        if "alpha_id" in alpha_index.columns and "is_sharpe" in alpha_index.columns:
            return list(
                alpha_index.sort_values("is_sharpe", ascending=False)
                .head(TARGET_N)["alpha_id"].tolist()
            )
        return list(R.columns)[: max(TARGET_N, 2)]

    # Pre-compute absolute correlation matrix on stable subset
    corr_abs = R[stable].corr().abs().fillna(1.0)

    # Greedy: first pick = highest IS Sharpe; subsequent = lowest combined rank
    first = max(stable, key=lambda c: sharpe_map[c])
    selected: list[str] = [first]
    pool: list[str] = [c for c in stable if c != first]

    while len(selected) < TARGET_N and pool:
        sh_sorted = sorted(pool, key=lambda c: -sharpe_map[c])
        rank_sh = {c: i for i, c in enumerate(sh_sorted)}
        mean_corr = {c: float(corr_abs.loc[c, selected].mean()) for c in pool}
        oc_sorted = sorted(pool, key=lambda c: mean_corr[c])
        rank_oc = {c: i for i, c in enumerate(oc_sorted)}
        score = {c: 0.5 * rank_sh[c] + 0.5 * rank_oc[c] for c in pool}
        best = min(pool, key=lambda c: score[c])
        selected.append(best)
        pool.remove(best)

    if len(selected) < 2:
        # absolute fallback so the runner never sees an empty list
        if "alpha_id" in alpha_index.columns and "is_sharpe" in alpha_index.columns:
            return list(
                alpha_index.sort_values("is_sharpe", ascending=False)
                .head(TARGET_N)["alpha_id"].tolist()
            )
        return list(R.columns)[: max(TARGET_N, 2)]

    return selected


def member_weights(
    member_ids: list[str], alpha_index: pd.DataFrame
) -> dict[str, float]:
    if not member_ids:
        return {}
    signs = member_signs_ic(RUN_ID, member_ids)
    signs = {mid: int(signs.get(mid, 1)) for mid in member_ids}
    # Equal-weighted (cov-free) baseline — sidesteps the 1/σ dilution trap.
    coef_raw = {mid: 1.0 for mid in member_ids}
    coef = apply_signs(coef_raw, signs)
    coef = normalize_coefficients(coef, "l1")  # sum_|c| = 1
    # Push mean row L1 into [0.5, 0.8] band — empirically required so the
    # composite is not 95% cash like every prior cov-based attempt.
    coef = {k: float(v) * TARGET_GROSS_SUM for k, v in coef.items()}
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
