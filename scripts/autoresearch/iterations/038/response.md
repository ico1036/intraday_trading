I'll cite **Lopez de Prado (2019) MP eigenvalue clipping + classical tangency** combined with **regime-aware filters** (per-year IS Sharpe sign stability + drawdown discipline) on a concentrated top-6 survivor set. This sits in the leaderboard's winning pattern (n∈[5,8], year-stable, DD-disciplined, dedup ρ≈0.85, denoised Σ) while substituting MP eigen-clipping for the auto_017 Ledoit-Wolf path — a distinct regularizer that suppresses the noise eigenvalues at the RMT Marchenko-Pastur edge rather than uniformly shrinking toward the diagonal. Mean row L1 targeted at 0.7 via post-`normalize_coefficients` rescale.

```python COMPOSITE_FILE
"""MP-denoised tangency over year-stable, DD-disciplined, dedup-pruned top-6 (Lopez de Prado 2019, Marchenko-Pastur eigenvalue clipping)."""
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
    select_is_submittable,
    select_all_alphas,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_038"
COMPOSITION_NOTE = "mp_denoise_tangency_year3stable_dd20_dedup085_top6_l1_07"

RUN_ID = "run_2026_05_c"
TARGET_N = 6
DD_THRESHOLD = 0.20
DEDUP_RHO = 0.85
TARGET_GROSS = 0.70


def _max_drawdown(s: pd.Series) -> float:
    x = s.fillna(0.0).values
    if len(x) == 0:
        return 1.0
    eq = np.cumprod(1.0 + x)
    peak = np.maximum.accumulate(eq)
    dd = eq / np.where(peak > 0, peak, 1.0) - 1.0
    return float(-dd.min())


def _year_split_positive(R: pd.DataFrame, n_splits: int = 3) -> list[str]:
    T = len(R)
    if T < n_splits * 30:
        return list(R.columns)
    edges = np.linspace(0, T, n_splits + 1, dtype=int)
    keep: list[str] = []
    for col in R.columns:
        s = R[col].fillna(0.0).values
        ok = True
        for i in range(n_splits):
            seg = s[edges[i]:edges[i + 1]]
            if seg.sum() <= 0:
                ok = False
                break
        if ok:
            keep.append(col)
    return keep


def _mp_denoise(cov: np.ndarray, T: int, N: int) -> np.ndarray:
    d = np.sqrt(np.clip(np.diag(cov), 1e-12, None))
    corr = cov / np.outer(d, d)
    corr = (corr + corr.T) * 0.5
    vals, vecs = np.linalg.eigh(corr)
    q = max(T / max(N, 1), 1.01)
    lam_plus = (1.0 + 1.0 / math.sqrt(q)) ** 2
    keep_mask = vals > lam_plus
    if not keep_mask.any():
        keep_mask = np.zeros_like(vals, dtype=bool)
        keep_mask[-1] = True
    bulk_mean = float(vals[~keep_mask].mean()) if (~keep_mask).any() else 0.0
    new_vals = np.where(keep_mask, vals, bulk_mean)
    new_corr = vecs @ np.diag(new_vals) @ vecs.T
    np.fill_diagonal(new_corr, 1.0)
    return new_corr * np.outer(d, d)


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    try:
        ids = select_is_submittable(RUN_ID)
    except Exception:
        ids = []
    if not ids:
        try:
            ids = select_all_alphas(RUN_ID)
        except Exception:
            ids = list(alpha_index["alpha_id"]) if "alpha_id" in alpha_index.columns else []
    ids = list(ids)
    if len(ids) < 2:
        return ids

    try:
        signs = member_signs_ic(RUN_ID, ids)
    except Exception:
        signs = {a: 1 for a in ids}
    try:
        R = load_member_is_returns(RUN_ID, ids, signs=signs)
    except Exception:
        return ids[:TARGET_N]

    if R is None or R.empty or R.shape[1] < 2:
        return list(R.columns) if R is not None else ids[:TARGET_N]

    dd_keep = [c for c in R.columns if _max_drawdown(R[c]) < DD_THRESHOLD]
    if len(dd_keep) >= max(8, TARGET_N + 2):
        R = R[dd_keep]

    stable = _year_split_positive(R, n_splits=3)
    if len(stable) >= max(8, TARGET_N + 2):
        R = R[stable]

    mu = R.mean()
    sd = R.std(ddof=0).replace(0.0, np.nan).fillna(1e-9)
    sh = (mu / sd) * math.sqrt(252.0)
    keep_metric = sh.to_dict()

    try:
        kept = correlation_dedup(R, threshold=DEDUP_RHO, keep_metric=keep_metric)
    except Exception:
        kept = list(R.columns)
    if len(kept) < 2:
        kept = list(R.columns)

    kept_sorted = sorted(kept, key=lambda x: keep_metric.get(x, 0.0), reverse=True)
    selected = kept_sorted[:TARGET_N]
    if len(selected) < 2:
        selected = sorted(R.columns, key=lambda x: keep_metric.get(x, 0.0), reverse=True)[: max(TARGET_N, 2)]
    return selected


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    member_ids = list(member_ids)
    if len(member_ids) < 2:
        return {m: 1.0 for m in member_ids}

    try:
        signs = member_signs_ic(RUN_ID, member_ids)
    except Exception:
        signs = {m: 1 for m in member_ids}
    try:
        R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    except Exception:
        eq = 1.0 / len(member_ids)
        return {m: eq * TARGET_GROSS for m in member_ids}

    cols = list(R.columns) if R is not None else []
    if len(cols) < 2:
        eq = 1.0 / len(member_ids)
        return {m: eq * TARGET_GROSS for m in member_ids}

    Rv = R.fillna(0.0).values
    T, N = Rv.shape

    try:
        sample_cov = np.cov(Rv, rowvar=False, ddof=0)
        Sigma = _mp_denoise(sample_cov, T, N)
        Sigma = Sigma + 1e-6 * (np.trace(Sigma) / max(N, 1)) * np.eye(N)
        mu = Rv.mean(axis=0)
        w = sla.pinvh(Sigma) @ mu
        if not np.isfinite(w).all() or np.allclose(w, 0.0):
            w = np.ones(N)
    except Exception:
        w = np.ones(N)

    coef = dict(zip(cols, [float(x) for x in w.tolist()]))
    for m in member_ids:
        coef.setdefault(m, 0.0)

    # R was sign-aligned, so w applies to flipped streams; coefficients on
    # the ORIGINAL streams must carry the sign back out.
    coef = {m: coef[m] * float(signs.get(m, 1)) for m in coef}

    if not any(abs(v) > 1e-12 for v in coef.values()):
        coef = {m: 1.0 for m in member_ids}

    coef = normalize_coefficients(coef, "l1")
    coef = {k: float(v) * TARGET_GROSS for k, v in coef.items()}
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
