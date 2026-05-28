Looking at the recent rejections and the user's regime-shift guidance, I want to try something genuinely fresh that hasn't appeared in the tried list. The strongest signal so far is the warning that high-IS Sharpe selection alone fails to generalize OS because of regime change, while anti-bias selection collapses worse — both suggest that the *root cause* is luck-driven alphas surviving selection.

**Idea: Probabilistic Sharpe Ratio (PSR) gating** — Bailey & López de Prado (2012, *The Sharpe Ratio Efficient Frontier*) construct a closed-form estimator of P(true SR > benchmark SR*) that explicitly penalises returns with bad higher moments (negative skew, fat tails). This is *not* the same as CSCV (which is already in the tried list); CSCV does combinatorial purged backtest splits, PSR is a moment-aware confidence bound on the observed Sharpe itself.

Pipeline:
1. Get SUBMITTABLE pool, sign-flip via IC.
2. Compute PSR(SR* = 0) for each surviving alpha — this rejects high-Sharpe alphas whose distribution looks too lottery-shaped to be trustworthy.
3. Correlation-dedup at 0.75 using PSR as the keep-metric (higher confidence wins).
4. Take top-6 by daily Sharpe — small N per the n=6-10 sweet-spot data.
5. Weight by PSR × Sharpe (confidence × magnitude), apply IC signs, L1-normalize, scale to gross 0.70 to hit the target row-L1 band.

No matrix inversion, so no Tikhonov / shrinkage stability concern that bit iter 001 / iter 004. Higher-moment gating is the differentiator vs. all 27 prior attempts.

```python COMPOSITE_FILE
"""PSR-gated (Bailey & Lopez de Prado 2012) concentrated IC-signed composite.

The Probabilistic Sharpe Ratio estimates P(true SR > SR*) using a closed-form
expression that accounts for skewness and kurtosis of the daily return series.
PSR > 0.90 filters out alphas whose IS Sharpe is plausibly a sample-luck or
fat-tail artifact -- the dominant failure mode flagged by prior iterations
(IS Sharpe 1.0-1.4 -> OS Sharpe 0.0-0.3). After PSR gating we correlation-dedup
(keep-by-PSR), take the top-K by daily Sharpe (small-N concentration responds
to empirical evidence that n=6-10 outperforms n>=30 under IS->OS regime shift),
then weight by PSR x Sharpe and apply IC-aligned signs.

Ref: Bailey & Lopez de Prado (2012), "The Sharpe Ratio Efficient Frontier",
Journal of Risk 15(2). Distinct from CSCV / PBO (different family): PSR is a
moment-aware confidence bound on the observed SR, not a combinatorial backtest
overfit estimator.
"""
from __future__ import annotations

import argparse
import math

import numpy as np
import pandas as pd
import scipy.stats as sst

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    correlation_dedup,
    member_signs_ic,
    apply_signs,
    select_is_submittable,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_028"
COMPOSITION_NOTE = "psr_baileylopez_gated_top6_icsigned_gross070"

RUN_ID = "run_2026_05_c"
PSR_THRESHOLD = 0.90
DEDUP_THRESHOLD = 0.75
TARGET_K = 6
TARGET_GROSS = 0.70


def _psr(daily_returns: np.ndarray, sr_benchmark: float = 0.0) -> float:
    """Probabilistic Sharpe Ratio: P(true SR > sr_benchmark)."""
    r = np.asarray(daily_returns, dtype=float)
    r = r[np.isfinite(r)]
    n = int(r.size)
    if n < 30:
        return 0.0
    sd = float(r.std(ddof=1))
    if sd <= 1e-12:
        return 0.0
    sr = float(r.mean() / sd)
    try:
        g3 = float(sst.skew(r, bias=False))
        g4 = float(sst.kurtosis(r, bias=False, fisher=False))
    except Exception:
        g3, g4 = 0.0, 3.0
    if not math.isfinite(g3):
        g3 = 0.0
    if not math.isfinite(g4):
        g4 = 3.0
    denom = 1.0 - g3 * sr + ((g4 - 1.0) / 4.0) * (sr * sr)
    if not math.isfinite(denom) or denom <= 1e-9:
        denom = 1e-9
    z = (sr - sr_benchmark) * math.sqrt(max(n - 1, 1)) / math.sqrt(denom)
    if not math.isfinite(z):
        return 0.0
    return float(sst.norm.cdf(z))


def _daily_sharpe(daily_returns: np.ndarray) -> float:
    r = np.asarray(daily_returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 2:
        return 0.0
    sd = float(r.std(ddof=1))
    if sd <= 1e-12:
        return 0.0
    return float(r.mean() / sd)


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if not ids or len(ids) < 4:
        return list(ids)

    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.shape[1] == 0 or R.shape[0] < 30:
        return list(ids)[: max(TARGET_K, 4)]

    available = [c for c in R.columns.tolist() if isinstance(c, str)]
    if len(available) < 4:
        return available

    psr_dict: dict[str, float] = {}
    sharpe_dict: dict[str, float] = {}
    for col in available:
        series = R[col].to_numpy()
        psr_dict[col] = _psr(series, sr_benchmark=0.0)
        sharpe_dict[col] = _daily_sharpe(series)

    survivors = [
        a for a in available
        if psr_dict.get(a, 0.0) >= PSR_THRESHOLD and sharpe_dict.get(a, 0.0) > 0.0
    ]
    if len(survivors) < TARGET_K + 2:
        ranked = sorted(
            available,
            key=lambda a: (psr_dict.get(a, 0.0), sharpe_dict.get(a, 0.0)),
            reverse=True,
        )
        survivors = ranked[: max(TARGET_K * 4, 24)]

    R_sub = R[survivors]
    try:
        kept = correlation_dedup(R_sub, threshold=DEDUP_THRESHOLD, keep_metric=psr_dict)
    except Exception:
        kept = list(survivors)
    if len(kept) < 2:
        kept = list(survivors)

    final = sorted(
        kept,
        key=lambda a: (sharpe_dict.get(a, 0.0), psr_dict.get(a, 0.0)),
        reverse=True,
    )[:TARGET_K]

    if len(final) < 2:
        final = sorted(
            available,
            key=lambda a: sharpe_dict.get(a, 0.0),
            reverse=True,
        )[: max(TARGET_K, 4)]
    return final


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    n = len(member_ids)
    if n == 0:
        return {}
    if n == 1:
        return {member_ids[0]: TARGET_GROSS}

    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)

    available_cols: list[str] = []
    if R is not None and R.shape[1] > 0:
        available_cols = [c for c in R.columns.tolist() if isinstance(c, str)]

    raw: dict[str, float] = {}
    for m in member_ids:
        if m in available_cols:
            series = R[m].to_numpy()
            psr = _psr(series, sr_benchmark=0.0)
            sr = _daily_sharpe(series)
            raw[m] = max(psr, 0.0) * max(sr, 0.0)
        else:
            raw[m] = 0.0

    if sum(raw.values()) <= 1e-12:
        raw = {m: 1.0 for m in member_ids}

    coef_signed = apply_signs(raw, signs)
    coef_l1 = normalize_coefficients(coef_signed, "l1")
    coef = {k: float(v) * TARGET_GROSS for k, v in coef_l1.items()}

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
```
