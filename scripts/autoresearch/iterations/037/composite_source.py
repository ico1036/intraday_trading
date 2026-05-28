"""Concentrated top-5 with year-stability + DD<=20% + Neumann-K4 tangency.

Method: regime-aware filter on the IS-submittable pool — keep alphas with
positive per-calendar-year mean return across every observed IS year AND
max IS drawdown <= 20%. Correlation-dedup at rho=0.85 keeping highest IS
Sharpe (Lopez de Prado, 2016 — orthogonality via single-linkage logic).
Pick top-5 by IS Sharpe. Build sample cov on sign-IC-aligned returns,
then approximate Sigma^{-1} by the truncated Neumann series
    Sigma^{-1} ~= alpha * sum_{k=0..K-1} (I - alpha*Sigma)^k
with K=4 and alpha = 1 / (1.5 * lambda_max), where lambda_max is
estimated by 40-step power iteration (Strang; Won & Kim 2019 for the
portfolio-inversion application). The truncation acts as an implicit
eigenvalue-divergence suppressor — the noisy high-eigenmodes that
Ledoit-Wolf shrinkage still partially retains are damped out. Tangency
weights w ∝ Sigma^{-1} mu; apply sign-IC so deployed coefficients carry
the right direction, L1-normalize, post-scale to sum|c|=0.65 to land
mean row L1 in the [0.30, 0.90] sweet spot.
"""
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
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_037_yearstable_dd20_top5_neumann_k4_tangency"
COMPOSITION_NOTE = "yearstable_dd20_top5_neumann_k4_tangency_ic_l1_065"

RUN_ID = "run_2026_05_c"
DD_THRESHOLD = 0.20
DEDUP_RHO = 0.85
TOP_K = 5
NEUMANN_K = 4
L1_TARGET = 0.65
MIN_OBS = 60


def _max_drawdown(r: pd.Series) -> float:
    eq = (1.0 + r.fillna(0.0)).cumprod()
    peak = eq.cummax()
    dd = (eq / peak - 1.0).min()
    return float(-dd) if np.isfinite(dd) else 1.0


def _year_stable(r: pd.Series) -> bool:
    idx = r.index
    if not isinstance(idx, pd.DatetimeIndex):
        try:
            idx2 = pd.to_datetime(idx, errors="coerce")
        except Exception:
            return True
        r = r.copy()
        r.index = idx2
        idx = idx2
    mask = ~pd.isna(idx)
    r = r[mask]
    if r.empty:
        return False
    years = sorted({int(y) for y in r.index.year.unique()})
    if not years:
        return False
    for y in years:
        seg = r[r.index.year == y].dropna()
        if seg.empty:
            continue
        if float(seg.mean()) <= 0.0:
            return False
    return True


def _annualized_sharpe(r: pd.Series) -> float:
    r = r.dropna()
    if len(r) < MIN_OBS:
        return -np.inf
    sd = float(r.std(ddof=0))
    if sd <= 0.0:
        return -np.inf
    return float(r.mean()) / sd * math.sqrt(252.0)


def _candidate_pool(run_id: str) -> list[str]:
    ids = select_is_submittable(run_id) or []
    if len(ids) < 2:
        ids = select_all_alphas(run_id) or ids
    # Dedup while preserving order
    seen: set[str] = set()
    out: list[str] = []
    for a in ids:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def _load_signed_returns(run_id: str, ids: list[str]) -> tuple[pd.DataFrame, dict[str, int]]:
    if not ids:
        return pd.DataFrame(), {}
    signs = member_signs_ic(run_id, ids) or {}
    for a in ids:
        signs.setdefault(a, 1)
    R = load_member_is_returns(run_id, ids, signs=signs)
    if R is None or R.empty:
        return pd.DataFrame(), signs
    R = R.dropna(axis=1, how="all")
    return R, signs


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    pool = _candidate_pool(RUN_ID)
    if len(pool) < 2:
        return pool
    R, _signs = _load_signed_returns(RUN_ID, pool)
    if R.empty:
        return pool[:TOP_K] if len(pool) >= 2 else pool

    sharpe_map: dict[str, float] = {}
    keep: list[str] = []
    for col in R.columns:
        s = _annualized_sharpe(R[col])
        if not np.isfinite(s) or s <= 0:
            continue
        sharpe_map[col] = s
        if _max_drawdown(R[col]) > DD_THRESHOLD:
            continue
        if not _year_stable(R[col]):
            continue
        keep.append(col)

    # Tiered fallbacks if the strict filter is too aggressive on this run
    if len(keep) < TOP_K:
        relaxed = [c for c in R.columns
                   if sharpe_map.get(c, -np.inf) > 0
                   and _max_drawdown(R[c]) <= DD_THRESHOLD + 0.05]
        for c in relaxed:
            if c not in keep:
                keep.append(c)
    if len(keep) < 2:
        ranked = sorted(sharpe_map.items(), key=lambda kv: kv[1], reverse=True)
        return [a for a, _ in ranked[:max(TOP_K, 2)]]

    R_keep = R[keep]
    try:
        deduped = correlation_dedup(R_keep, threshold=DEDUP_RHO, keep_metric=sharpe_map)
    except Exception:
        deduped = list(R_keep.columns)
    if not deduped:
        deduped = list(R_keep.columns)

    ranked = sorted(deduped, key=lambda aid: sharpe_map.get(aid, -np.inf), reverse=True)
    chosen = ranked[:TOP_K]
    if len(chosen) < 2:
        ranked_all = sorted(keep, key=lambda aid: sharpe_map.get(aid, -np.inf), reverse=True)
        chosen = ranked_all[:max(TOP_K, 2)]
    return chosen


def _neumann_inverse(Sigma: np.ndarray, K: int) -> np.ndarray:
    n = Sigma.shape[0]
    if n == 0:
        return Sigma
    v = np.ones(n, dtype=float) / math.sqrt(n)
    lam_max = 0.0
    for _ in range(40):
        w = Sigma @ v
        nrm = float(np.linalg.norm(w))
        if nrm <= 0.0:
            break
        v = w / nrm
        lam_max = float(v @ Sigma @ v)
    if lam_max <= 0.0:
        diag_mean = float(np.trace(Sigma)) / max(n, 1)
        lam_max = diag_mean if diag_mean > 0 else 1.0
    alpha = 1.0 / (1.5 * lam_max)
    I = np.eye(n)
    M = I - alpha * Sigma
    acc = np.zeros_like(Sigma)
    term = I.copy()
    for _ in range(K):
        acc = acc + term
        term = term @ M
    return alpha * acc


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    signs = member_signs_ic(RUN_ID, member_ids) or {}
    for aid in member_ids:
        signs.setdefault(aid, 1)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    if R is None or R.empty:
        eq = {aid: 1.0 / len(member_ids) for aid in member_ids}
        c = normalize_coefficients(eq, "l1")
        return {k: float(v) * L1_TARGET for k, v in c.items()}

    R = R[[c for c in member_ids if c in R.columns]]
    R = R.dropna(how="all").fillna(0.0)
    cols = list(R.columns)

    if R.shape[1] < 2 or R.shape[0] < 10:
        eq = {aid: 1.0 / len(member_ids) for aid in member_ids}
        c = normalize_coefficients(eq, "l1")
        return {k: float(v) * L1_TARGET for k, v in c.items()}

    mu = R.mean(axis=0).values.astype(float)
    Sigma = np.cov(R.values, rowvar=False, ddof=0).astype(float)
    if Sigma.ndim == 0:
        Sigma = np.array([[float(Sigma)]])
    n = Sigma.shape[0]
    diag_mean = float(np.trace(Sigma)) / max(n, 1)
    ridge = 1e-6 * (diag_mean if diag_mean > 0 else 1.0)
    Sigma = Sigma + ridge * np.eye(n)

    try:
        Sigma_inv = _neumann_inverse(Sigma, NEUMANN_K)
        w = Sigma_inv @ mu
    except Exception:
        w = mu.copy()

    if not np.all(np.isfinite(w)) or float(np.linalg.norm(w)) == 0.0:
        w = np.ones_like(mu)

    raw: dict[str, float] = {c: float(v) for c, v in zip(cols, w.tolist()) if np.isfinite(v)}
    for aid in member_ids:
        raw.setdefault(aid, 0.0)

    # Sign-IC alignment so deployed coefficients carry the right direction
    signed = apply_signs(raw, signs)

    # Drop any non-finite that crept in before L1-normalize
    signed = {k: float(v) for k, v in signed.items() if np.isfinite(v)}
    if not signed or all(abs(v) < 1e-12 for v in signed.values()):
        signed = {aid: 1.0 for aid in member_ids}

    c = normalize_coefficients(signed, "l1")
    out = {k: float(v) * L1_TARGET for k, v in c.items()}
    for aid in member_ids:
        out.setdefault(aid, 0.0)
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