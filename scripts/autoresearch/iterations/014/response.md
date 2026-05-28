**Rationale (Iteration 14)**

The persistent failure pattern — IS Sharpe 1.0–1.4 collapsing to OS Sharpe 0.0–0.3 — and the two ERRORED attempts (auto_001, auto_004) point at *selection bias on Sharpe* as the dominant root cause and *helper API misuse* (passing ndarrays into `normalize_coefficients` which expects a `dict`) as a secondary trap. None of attempts 001–013 has combined (a) **fee-agnostic IC-magnitude pre-ranking** with (b) **rolling-Sharpe stability culling** and (c) **bagging**, which is the cleanest de-biasing chain available.

**Method.** *Bootstrap-Aggregated Equal Risk Contribution* (Maillard, Roncalli, Teiletche 2010 + Breiman 1996). ERC equalises risk contributions `w_i·(Σw)_i` across members, a robust diversification target that — unlike tangency, min-var, max-div — needs no covariance inversion and is well-behaved on noisy Σ̂. We bag the ERC fit over `N_BOOTSTRAP=80` random subsets of K≈2N/3 members and average the per-member coefficients (Bühlmann/Yu "subagging" — variance of OS Sharpe drops dramatically when each fit only sees a random subset of the noisy candidate set). Selection is anti-Sharpe-biased:
1. **IC magnitude** ranks alphas first (`|ic_mean|`), which is fee-agnostic and immune to Sharpe's compounded-fee/sample-variance distortion;
2. Among the top 120, keep those in the **lower half of rolling-Sharpe stability** (low std-of-rolling-Sharpe = consistent, not lucky);
3. Correlation-dedup at |ρ|=0.85, IS-Sharpe used only as a *tie-breaker* on the already-debiased pool;
4. Take ≤24 members.

**Numerics.** Σ̂ is diagonally shrunk (Ledoit-Wolf-style 0.85·Σ̂ + 0.15·avg_var·I) inside each bootstrap fit; ERC is solved by 200-step damped fixed-point iteration with `adj` clipped to [0.25, 4] for stability. No matrix inversion. `apply_signs` re-applies the IC-derived sign to the long-only ERC weights so the resulting coefficient set is properly oriented on the *raw* (unsigned) alpha weight stream. Final L1-normalised dict is scaled by `TARGET_GROSS=0.65` to land mean row-L1 in the prompt's [0.30, 0.90] sweet spot.

**Helper-API guard rails.** Every `normalize_coefficients` / `apply_signs` call receives a `dict`, never an ndarray. `correlation_dedup` receives a DataFrame plus a dict `keep_metric`. All metric-lookup calls use `.get(a, default)` so a missing alpha never raises.

```python COMPOSITE_FILE
"""Bootstrap-aggregated Equal Risk Contribution (Maillard, Roncalli, Teiletche 2010) with IC-magnitude pre-rank and rolling-Sharpe stability filter; subagging per Breiman/Bühlmann to suppress selection bias."""
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
    member_ic,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_014"
COMPOSITION_NOTE = "bootstrap_erc_icmag_stability_dedup085_top24_gross065"

RUN_ID = "run_2026_05_c"
TARGET_GROSS = 0.65
TARGET_MEMBERS = 24
DEDUP_THRESHOLD = 0.85
N_BOOTSTRAP = 80
SEED = 20260526


def _safe_dict(fn, *args, **kwargs) -> dict:
    try:
        out = fn(*args, **kwargs)
    except Exception:
        return {}
    if isinstance(out, dict):
        return out
    try:
        return dict(out)
    except Exception:
        return {}


def _stability_score(R: pd.DataFrame, window: int = 60) -> pd.Series:
    """Std of a rolling-window annualized Sharpe; lower => more stable."""
    T = len(R)
    if T < window + 5:
        window = max(15, T // 4)
    if window < 8 or T < window + 2:
        return pd.Series({c: float("inf") for c in R.columns})
    mu = R.rolling(window).mean()
    sd = R.rolling(window).std().replace(0.0, np.nan)
    rs = (mu / sd) * math.sqrt(252.0)
    s = rs.std()
    return s.replace([np.inf, -np.inf], np.nan)


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if not ids or len(ids) < 30:
        ids = select_all_alphas(RUN_ID)
    if not ids:
        return []

    signs = _safe_dict(member_signs_ic, RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    cols = [c for c in R.columns if R[c].notna().sum() > 30]
    if len(cols) < 4:
        return list(R.columns)[: max(2, len(R.columns))]
    R = R[cols].fillna(0.0)

    ic_map = _safe_dict(member_ic, RUN_ID, cols)
    sharpe_map = _safe_dict(member_is_sharpe, RUN_ID, cols)

    # (1) IC-magnitude rank — fee-agnostic, anti-Sharpe-bias.
    pool = sorted(cols, key=lambda a: abs(float(ic_map.get(a, 0.0))), reverse=True)
    top_ic = pool[: min(len(pool), 120)]
    if len(top_ic) < 6:
        top_ic = pool

    # (2) Rolling-Sharpe stability filter — keep lower half (more consistent).
    stab = _stability_score(R[top_ic]).dropna()
    if len(stab) >= 16:
        med = float(stab.median())
        stable = [a for a in top_ic if a in stab.index and float(stab.loc[a]) <= med]
    else:
        stable = top_ic
    if len(stable) < 8:
        stable = top_ic

    # (3) Correlation dedup at 0.85, IS Sharpe only as tie-breaker.
    R_sub = R[stable]
    keep_metric = {a: float(sharpe_map.get(a, 0.0)) for a in stable}
    try:
        kept = correlation_dedup(R_sub, threshold=DEDUP_THRESHOLD, keep_metric=keep_metric)
    except Exception:
        kept = stable

    if not kept or len(kept) < 4:
        kept = stable

    return list(kept)[: min(TARGET_MEMBERS, len(kept))]


def _erc_weights(R_sub: pd.DataFrame, max_iter: int = 200, tol: float = 1e-7) -> np.ndarray:
    """Maillard (2010) Equal Risk Contribution via damped fixed-point iteration.
    Diagonally shrunk Σ̂ (LW-style); no inversion, no eigendecomp."""
    n = R_sub.shape[1]
    Sigma = np.asarray(R_sub.cov().values, dtype=float)
    if not np.all(np.isfinite(Sigma)):
        Sigma = np.nan_to_num(Sigma, nan=0.0, posinf=0.0, neginf=0.0)
    avg_var = float(np.mean(np.diag(Sigma))) if n else 0.0
    if avg_var <= 0.0:
        avg_var = 1e-8
    Sigma = 0.85 * Sigma + 0.15 * avg_var * np.eye(n)
    w = np.ones(n) / n
    for _ in range(max_iter):
        Sw = Sigma @ w
        port_var = float(w @ Sw)
        if port_var <= 1e-14:
            break
        rc = w * Sw
        target = port_var / n
        adj = np.sqrt(np.clip(target / np.maximum(rc, 1e-14), 0.25, 4.0))
        w_new = np.clip(w * adj, 1e-10, None)
        w_new = w_new / w_new.sum()
        if float(np.max(np.abs(w_new - w))) < tol:
            w = w_new
            break
        w = w_new
    return w


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    ids = list(member_ids)
    if len(ids) == 0:
        return {}
    if len(ids) == 1:
        c = normalize_coefficients({ids[0]: 1.0}, "l1")
        return {a: TARGET_GROSS * float(v) for a, v in c.items()}

    signs = _safe_dict(member_signs_ic, RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    cols = [c for c in R.columns if R[c].notna().sum() > 20]
    if len(cols) < 2:
        coef = {a: 1.0 for a in ids}
        c = normalize_coefficients(coef, "l1")
        return {a: TARGET_GROSS * float(v) for a, v in c.items()}
    R = R[cols].fillna(0.0)
    n = len(cols)

    rng = np.random.default_rng(SEED)
    K = max(6, min(n, (2 * n) // 3))
    agg = {a: 0.0 for a in cols}
    counts = {a: 0 for a in cols}

    n_boot = N_BOOTSTRAP if K < n else 1
    for _ in range(n_boot):
        if K >= n:
            sub = list(cols)
        else:
            idx = rng.choice(n, size=K, replace=False)
            sub = [cols[i] for i in idx]
        R_sub = R[sub]
        if R_sub.shape[0] < 20 or R_sub.shape[1] < 2:
            continue
        try:
            w = _erc_weights(R_sub)
        except Exception:
            continue
        if not np.all(np.isfinite(w)) or float(np.sum(w)) <= 0.0:
            continue
        for a, val in zip(sub, w):
            agg[a] += float(val)
            counts[a] += 1

    avg = {a: (agg[a] / counts[a]) if counts[a] > 0 else 0.0 for a in cols}
    if sum(avg.values()) <= 0.0:
        avg = {a: 1.0 / n for a in cols}

    # signs were applied to R, so ERC weights are long-only on the
    # sign-aligned series; re-apply signs to recover directional
    # coefficients on the raw alpha weight stream.
    signs_sub = {a: int(signs.get(a, 1)) for a in avg.keys()}
    signed = apply_signs(avg, signs_sub)

    full = {a: float(signed.get(a, 0.0)) for a in ids}
    if sum(abs(v) for v in full.values()) <= 0.0:
        full = {a: 1.0 / len(ids) for a in ids}

    c = normalize_coefficients(full, "l1")
    return {a: TARGET_GROSS * float(v) for a, v in c.items()}


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
