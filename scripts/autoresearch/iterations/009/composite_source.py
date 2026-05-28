"""HRP composite (Lopez de Prado, 'Building Diversified Portfolios that Outperform Out-of-Sample', JPM 2016):
correlation-distance single-linkage clustering with quasi-diagonalization and recursive bisection,
followed by an IS-Sharpe power tilt to concentrate on high-return members per the user mandate."""
from __future__ import annotations

import argparse
import numpy as np
import pandas as pd
import scipy.cluster.hierarchy as sch
import scipy.spatial.distance as ssd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    correlation_dedup,
    member_signs_ic,
    apply_signs,
    select_is_submittable,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_009_hrp_lopezdeprado_quasidiag_sharpe_tilt_t"
COMPOSITION_NOTE = "hrp_lopezdeprado_quasidiag_sharpe_tilt_top25_gross060"

RUN_ID = "run_2026_05_c"
TOP_N = 25
DEDUP_THRESHOLD = 0.85
GROSS_TARGET = 0.60
SHARPE_TILT_POWER = 0.5
COV_SHRINK = 0.10


def _is_sharpe_map(alpha_index: pd.DataFrame) -> dict[str, float]:
    if "alpha_id" in alpha_index.columns and "is_sharpe" in alpha_index.columns:
        return {
            str(a): float(s) if pd.notna(s) else 0.0
            for a, s in zip(alpha_index["alpha_id"], alpha_index["is_sharpe"])
        }
    return {}


def _sharpe_from_returns(R: pd.DataFrame) -> dict[str, float]:
    mu = R.mean(axis=0)
    sd = R.std(axis=0).replace(0.0, np.nan)
    s = (mu / sd) * np.sqrt(252.0)
    return s.fillna(0.0).to_dict()


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if not ids or len(ids) < 2:
        if "alpha_id" in alpha_index.columns:
            ids = [str(a) for a in alpha_index["alpha_id"].tolist()]
    if not ids or len(ids) < 2:
        return ids or []

    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R.shape[1] < 2:
        return list(R.columns)

    sharpe_map = _is_sharpe_map(alpha_index)
    if not sharpe_map:
        sharpe_map = _sharpe_from_returns(R)
    # ensure every column present in the metric dict
    for a in R.columns:
        sharpe_map.setdefault(str(a), 0.0)

    try:
        kept = correlation_dedup(R, threshold=DEDUP_THRESHOLD, keep_metric=sharpe_map)
    except Exception:
        kept = list(R.columns)

    kept = [a for a in kept if a in R.columns]
    if len(kept) > TOP_N:
        kept = sorted(kept, key=lambda a: -float(sharpe_map.get(a, 0.0)))[:TOP_N]

    if len(kept) < 2:
        kept = list(R.columns[: max(2, min(TOP_N, R.shape[1]))])
    return kept


def _quasi_diag(link: np.ndarray) -> list[int]:
    link = link.astype(int)
    n_items = int(link[-1, 3])
    sort_ix = [int(link[-1, 0]), int(link[-1, 1])]
    while max(sort_ix) >= n_items:
        new_sort: list[int] = []
        for i in sort_ix:
            if i < n_items:
                new_sort.append(i)
            else:
                j = i - n_items
                new_sort.append(int(link[j, 0]))
                new_sort.append(int(link[j, 1]))
        sort_ix = new_sort
    return sort_ix


def _cluster_inv_var(cov: np.ndarray, items: list[int]) -> float:
    sub = cov[np.ix_(items, items)]
    diag = np.diag(sub).astype(float).copy()
    diag[~np.isfinite(diag)] = 1e-12
    diag[diag <= 0.0] = 1e-12
    iv = 1.0 / diag
    w = iv / iv.sum()
    return float(w @ sub @ w)


def _recursive_bisection(cov: np.ndarray, sort_ix: list[int]) -> np.ndarray:
    n = cov.shape[0]
    w = np.ones(n, dtype=float)
    clusters: list[list[int]] = [list(sort_ix)]
    while clusters:
        nxt: list[list[int]] = []
        for c in clusters:
            if len(c) <= 1:
                continue
            half = len(c) // 2
            left, right = c[:half], c[half:]
            vl = _cluster_inv_var(cov, left)
            vr = _cluster_inv_var(cov, right)
            denom = vl + vr
            alpha = 0.5 if denom <= 0 or not np.isfinite(denom) else 1.0 - vl / denom
            alpha = float(np.clip(alpha, 0.0, 1.0))
            for i in left:
                w[i] *= alpha
            for i in right:
                w[i] *= 1.0 - alpha
            nxt.append(left)
            nxt.append(right)
        clusters = nxt
    return w


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)

    if R.shape[1] < 2:
        if R.shape[1] == 1:
            only = str(R.columns[0])
            coef = {only: GROSS_TARGET}
        else:
            eq = GROSS_TARGET / max(1, len(member_ids))
            coef = {a: eq for a in member_ids}
        return apply_signs(coef, signs)

    ids = [str(c) for c in R.columns]
    X = R.to_numpy(dtype=float)
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    # Correlation -> distance d_ij = sqrt(0.5 * (1 - rho_ij))
    Cdf = pd.DataFrame(X, columns=ids).corr()
    C = Cdf.to_numpy()
    C = np.nan_to_num(C, nan=0.0, posinf=0.0, neginf=0.0)
    np.fill_diagonal(C, 1.0)
    C = np.clip(C, -1.0, 1.0)
    D = np.sqrt(np.clip(0.5 * (1.0 - C), 0.0, 1.0))
    D = (D + D.T) * 0.5
    np.fill_diagonal(D, 0.0)

    try:
        condensed = ssd.squareform(D, checks=False)
        link = sch.linkage(condensed, method="single")
        sort_ix = _quasi_diag(link)
    except Exception:
        sort_ix = list(range(len(ids)))

    # Sample covariance with mild diagonal shrinkage (no inversion needed for HRP)
    cov = np.cov(X, rowvar=False)
    cov = np.nan_to_num(cov, nan=0.0, posinf=0.0, neginf=0.0)
    if cov.ndim == 0:
        cov = np.array([[float(cov)]])
    diag_mean = float(np.mean(np.diag(cov))) if cov.size else 1.0
    if not np.isfinite(diag_mean) or diag_mean <= 0:
        diag_mean = 1.0
    cov = (1.0 - COV_SHRINK) * cov + COV_SHRINK * diag_mean * np.eye(cov.shape[0])

    w_hrp = _recursive_bisection(cov, sort_ix)
    if not np.all(np.isfinite(w_hrp)) or w_hrp.sum() <= 0:
        w_hrp = np.ones_like(w_hrp)
    w_hrp = w_hrp / w_hrp.sum()

    # IS-Sharpe power tilt: concentrate on high-return members (user mandate)
    sharpe_map = _is_sharpe_map(alpha_index)
    if not sharpe_map:
        sharpe_map = _sharpe_from_returns(R)
    raw = np.array([max(float(sharpe_map.get(a, 0.0)), 0.0) for a in ids], dtype=float)
    if raw.sum() <= 0 or not np.isfinite(raw.sum()):
        tilt = np.ones_like(raw)
    else:
        tilt = np.power(raw + 1e-6, SHARPE_TILT_POWER)
    w = w_hrp * tilt
    if not np.all(np.isfinite(w)) or w.sum() <= 0:
        w = np.ones_like(w)
    w = w / w.sum()

    # Build dict (non-negative magnitudes); ensure every member_id is keyed
    coef: dict[str, float] = {a: float(v) for a, v in zip(ids, w.tolist())}
    for a in member_ids:
        coef.setdefault(str(a), 0.0)

    # L1-normalize via helper then scale to the gross-exposure target
    coef = normalize_coefficients(coef, "l1")
    coef = {a: GROSS_TARGET * float(v) for a, v in coef.items()}

    # Apply deployable IC signs
    coef = apply_signs(coef, signs)
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