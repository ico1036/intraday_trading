I need to generate iteration 3. Iterations 1-2 used Neumann-series tangency and NCO with MP denoise+detone+tangency — both rely on (regularized) covariance inversion, both errored or underperformed. The natural fresh territory is a **hierarchical, inversion-free** method: **HERC (Hierarchical Equal Risk Contribution, Raffinot 2018)**.

**Why HERC for this mandate:**
- No matrix inversion → robust under near-singular Σ (484 alphas, many near-clones)
- Top-down recursive bisection on cluster variance (less variance → more weight) keeps allocation concentrated rather than smeared
- Within-cluster inverse-vol gives proper risk parity
- Easy to layer an IS-Sharpe **concentration tilt** on top → matches the user's high-return/high-risk mandate without abandoning diversification structure
- Distinct from Neumann (iter 1) and NCO+MP-denoise+tangency (iter 2)

**Defenses against iter-1 helper crash:** keep helper calls to the four signatures explicitly documented in the spec (`select_is_submittable`, `member_signs_ic`, `load_member_is_returns`, `member_is_sharpe`); implement dedup and sign-application inline instead of calling `correlation_dedup` / `apply_signs` whose signatures aren't in the spec.

**Gross-exposure plan:** 24 members (concentrated), `normalize_coefficients(...,"l1")` to Σ|c|=1, then scale by `TARGET_GROSS=0.60` to land mean row L1 in the requested [0.30, 0.90] window.

Note on plan mode: the harness extracts the fenced block from this text response — I'm not invoking any tools or editing files, so plan mode is honoured.

```python COMPOSITE_FILE
"""HERC (Hierarchical Equal Risk Contribution, Raffinot 2018, JPM) on IC-aligned IS
returns, with greedy correlation dedup (|rho|>0.85) and IS-Sharpe concentration tilt.
Avoids covariance inversion entirely — top-down bisection on Ward-clustered correlation
distance, inverse-vol allocation inside leaves, Sharpe-power tilt to honour the
high-return/high-risk mandate, scaled to mean gross ~0.6."""
from __future__ import annotations
import argparse
import math
import numpy as np
import pandas as pd
import scipy.cluster.hierarchy as sch
import scipy.spatial.distance as ssd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    member_signs_ic,
    select_is_submittable,
    member_is_sharpe,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_003"
COMPOSITION_NOTE = "herc_raffinot_dedup085_sharpe_tilt_top24_gross060"
RUN_ID = "run_2026_05_c"

TOP_N = 24
POOL_CAP = 120
DEDUP_RHO = 0.85
TARGET_GROSS = 0.60
TILT_POWER = 1.25


# ---------- safe helpers ----------------------------------------------------

def _as_float(v, default: float) -> float:
    try:
        x = float(v)
    except Exception:
        return default
    return x if math.isfinite(x) else default


def _ic_signs(ids: list[str]) -> dict[str, float]:
    try:
        raw = member_signs_ic(RUN_ID, ids) or {}
    except Exception:
        raw = {}
    out: dict[str, float] = {}
    for a in ids:
        try:
            s = raw.get(a, 1.0) if hasattr(raw, "get") else 1.0
        except Exception:
            s = 1.0
        s = _as_float(s, 1.0)
        if s == 0.0:
            s = 1.0
        out[a] = 1.0 if s > 0 else -1.0
    return out


def _is_sharpe_map(ids: list[str]) -> dict[str, float]:
    try:
        raw = member_is_sharpe(RUN_ID, ids) or {}
    except Exception:
        raw = {}
    out: dict[str, float] = {}
    for a in ids:
        try:
            v = raw.get(a, 0.0) if hasattr(raw, "get") else 0.0
        except Exception:
            v = 0.0
        out[a] = _as_float(v, 0.0)
    return out


def _load_returns(ids: list[str], signs: dict[str, float]) -> pd.DataFrame | None:
    if not ids:
        return None
    try:
        R = load_member_is_returns(RUN_ID, ids, signs=signs)
    except TypeError:
        try:
            R = load_member_is_returns(RUN_ID, ids)
            if R is not None:
                for a in list(R.columns):
                    R[a] = R[a].astype(float) * float(signs.get(a, 1.0))
        except Exception:
            return None
    except Exception:
        return None
    if R is None or len(R) == 0:
        return None
    R = R.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    keep = [c for c in R.columns if R[c].std(ddof=0) > 1e-12]
    R = R.loc[:, keep]
    return R if R.shape[1] >= 2 else None


def _norm_l1(d: dict[str, float]) -> dict[str, float]:
    try:
        return normalize_coefficients(d, "l1")
    except TypeError:
        try:
            return normalize_coefficients(d, mode="l1")
        except Exception:
            pass
    except Exception:
        pass
    tot = sum(abs(v) for v in d.values()) or 1.0
    return {k: v / tot for k, v in d.items()}


def _greedy_dedup(R: pd.DataFrame, ranks: dict[str, float], rho: float) -> list[str]:
    cols = list(R.columns)
    order = sorted(cols, key=lambda a: -ranks.get(a, 0.0))
    C = R.corr().fillna(0.0).abs()
    kept: list[str] = []
    for a in order:
        ok = True
        for k in kept:
            try:
                if float(C.at[a, k]) > rho:
                    ok = False
                    break
            except Exception:
                continue
        if ok:
            kept.append(a)
    return kept


# ---------- HERC core -------------------------------------------------------

def _herc_risk_weights(corr: np.ndarray, vol: np.ndarray) -> np.ndarray:
    n = corr.shape[0]
    if n == 1:
        return np.array([1.0])
    d = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
    np.fill_diagonal(d, 0.0)
    cond = ssd.squareform(d, checks=False)
    try:
        Z = sch.linkage(cond, method="ward")
        leaves = sch.leaves_list(Z)
    except Exception:
        leaves = np.arange(n)
    w = np.ones(n, dtype=float)

    def cluster_var(sub: np.ndarray) -> float:
        if len(sub) == 1:
            return float(vol[sub[0]] ** 2)
        sub_corr = corr[np.ix_(sub, sub)]
        sub_vol = vol[sub]
        sub_cov = sub_corr * np.outer(sub_vol, sub_vol)
        iv = 1.0 / np.maximum(sub_vol, 1e-12)
        s = iv.sum()
        if s <= 0:
            iv = np.ones_like(iv) / len(iv)
        else:
            iv = iv / s
        return float(iv @ sub_cov @ iv)

    def recurse(idx: np.ndarray) -> None:
        if len(idx) <= 1:
            return
        half = len(idx) // 2
        left, right = idx[:half], idx[half:]
        cv_l = cluster_var(left)
        cv_r = cluster_var(right)
        denom = cv_l + cv_r
        if denom <= 0 or not math.isfinite(denom):
            alpha = 0.5
        else:
            alpha = 1.0 - cv_l / denom  # lower variance side gets larger weight
        alpha = float(np.clip(alpha, 0.05, 0.95))
        w[left] *= alpha
        w[right] *= (1.0 - alpha)
        recurse(left)
        recurse(right)

    recurse(np.asarray(leaves, dtype=int))
    if not np.isfinite(w).all() or w.sum() <= 0:
        w = np.ones(n) / n
    return w / w.sum()


# ---------- harness contract -----------------------------------------------

def select_members(alpha_index: pd.DataFrame) -> list[str]:
    try:
        ids = list(select_is_submittable(RUN_ID))
    except Exception:
        ids = []
    ids = [a for a in ids if isinstance(a, str) and a]
    if len(ids) < 3 and isinstance(alpha_index, pd.DataFrame) and "alpha_id" in alpha_index.columns:
        ids = [a for a in alpha_index["alpha_id"].astype(str).tolist() if a]
    if len(ids) < 2:
        return ids

    sharpe = _is_sharpe_map(ids)
    ranked = sorted(ids, key=lambda a: -sharpe.get(a, 0.0))
    pool = ranked[: min(POOL_CAP, len(ranked))]

    signs = _ic_signs(pool)
    R = _load_returns(pool, signs)
    if R is None or R.shape[1] < 3:
        return ranked[: min(TOP_N, len(ranked))]

    kept = _greedy_dedup(R, {a: sharpe.get(a, 0.0) for a in pool}, DEDUP_RHO)
    if len(kept) < 3:
        return ranked[: min(TOP_N, len(ranked))]

    kept_sorted = sorted(kept, key=lambda a: -sharpe.get(a, 0.0))
    return kept_sorted[: min(TOP_N, len(kept_sorted))]


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    ids = [a for a in member_ids if isinstance(a, str) and a]
    if not ids:
        return {}

    signs = _ic_signs(ids)
    sharpe = _is_sharpe_map(ids)
    R = _load_returns(ids, signs)

    if R is None or R.shape[1] < 2:
        raw = {a: max(0.05, sharpe.get(a, 0.5)) * signs.get(a, 1.0) for a in ids}
        c = _norm_l1(raw)
        return {a: TARGET_GROSS * c.get(a, 0.0) for a in ids}

    cols = list(R.columns)
    Rm = R.values.astype(float)
    vol = Rm.std(axis=0, ddof=0)
    vol = np.where(vol < 1e-12, 1e-12, vol)
    Cdf = R.corr().fillna(0.0)
    corr = Cdf.loc[cols, cols].values.astype(float)
    np.fill_diagonal(corr, 1.0)
    corr = np.clip(corr, -0.999, 0.999)

    w_risk = _herc_risk_weights(corr, vol)   # risk budgets summing to 1
    w_cap = w_risk / vol                     # convert to capital weights
    if not np.isfinite(w_cap).all() or w_cap.sum() <= 0:
        w_cap = np.ones(len(cols)) / len(cols)
    else:
        w_cap = w_cap / w_cap.sum()

    s_vec = np.array([max(0.05, sharpe.get(a, 0.5)) for a in cols], dtype=float)
    tilt = np.power(s_vec, TILT_POWER)
    if not np.isfinite(tilt).all() or tilt.sum() <= 0:
        tilt = np.ones(len(cols))
    tilt = tilt / tilt.sum()

    w = w_cap * tilt
    if not np.isfinite(w).all() or w.sum() <= 0:
        w = np.ones(len(cols)) / len(cols)
    else:
        w = w / w.sum()

    signed = {cols[i]: float(w[i]) * float(signs.get(cols[i], 1.0)) for i in range(len(cols))}
    c_norm = _norm_l1(signed)
    out = {a: TARGET_GROSS * _as_float(c_norm.get(a, 0.0), 0.0) for a in cols}
    for a in ids:
        out.setdefault(a, 0.0)
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
```
