"""NCO with Marchenko-Pastur denoising and detoning (Lopez de Prado 2019).

Nested Clustered Optimization: cluster the denoised correlation matrix,
solve tangency inside each cluster, then tangency across the resulting
cluster-portfolio cov. MP eigenvalue clipping (bulk below (1+sqrt(N/T))^2
collapsed to bulk mean) + detoning (top eigenvalue -> bulk mean) removes
RMT noise and the dominant market mode before optimization.

References:
  - Lopez de Prado, M. (2019). Machine Learning for Asset Managers, Ch.7.
  - Lopez de Prado, M. (2016). Building Diversified Portfolios that
    Outperform Out of Sample. J. Portfolio Mgmt.
  - Laloux, Cizeau, Bouchaud, Potters (1999). Noise dressing of financial
    correlation matrices.
"""
from __future__ import annotations
import argparse

import numpy as np
import pandas as pd
import scipy.linalg as sla
import scipy.cluster.hierarchy as sch
import scipy.spatial.distance as ssd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    member_signs_ic,
    select_is_submittable,
    select_all_alphas,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_002_nco_mp_denoise_detone_tangency_top80_ded"
COMPOSITION_NOTE = "nco_mp_denoise_detone_tangency_top80_dedup080"

RUN_ID = "run_2026_05_c"
TOP_N_BY_SHARPE = 80
DEDUP_RHO = 0.80
GROSS_BUDGET = 1.6
K_CLUSTERS_MAX = 12
MIN_MEMBERS = 2

_CACHE: dict = {}


def _shortlist_and_coefficients(run_id: str) -> tuple[list[str], dict[str, float]]:
    if run_id in _CACHE:
        return _CACHE[run_id]

    ids = list(select_is_submittable(run_id))
    if len(ids) < 20:
        ids = list(select_all_alphas(run_id))
    if len(ids) < MIN_MEMBERS:
        _CACHE[run_id] = (ids, {i: 1.0 / max(len(ids), 1) for i in ids})
        return _CACHE[run_id]

    signs = member_signs_ic(run_id, ids)
    R = load_member_is_returns(run_id, ids, signs=signs)
    R = R.dropna(axis=1, how="all").fillna(0.0)
    keep_cols = [c for c in R.columns if float(R[c].std()) > 1e-9]
    R = R[keep_cols]
    if R.shape[1] < MIN_MEMBERS:
        _CACHE[run_id] = (list(R.columns), {c: 1.0 for c in R.columns})
        return _CACHE[run_id]

    # IS Sharpe of sign-aligned returns
    mu_s = R.mean()
    sd_s = R.std().replace(0.0, np.nan)
    sharpe = (mu_s / sd_s).fillna(-np.inf).sort_values(ascending=False)
    top_ids = sharpe.head(TOP_N_BY_SHARPE).index.tolist()
    R_top = R[top_ids]

    # Greedy |rho|-dedup keeping higher IS Sharpe first
    C_abs = R_top.corr().abs().fillna(0.0)
    kept: list[str] = []
    for cid in top_ids:
        if all(float(C_abs.loc[cid, k]) < DEDUP_RHO for k in kept):
            kept.append(cid)
    if len(kept) < MIN_MEMBERS:
        kept = top_ids[: min(20, len(top_ids))]

    R_dedup = R_top[kept]
    coeffs = _nco_coefficients(R_dedup)
    _CACHE[run_id] = (kept, coeffs)
    return kept, coeffs


def _nco_coefficients(R: pd.DataFrame) -> dict[str, float]:
    ids = list(R.columns)
    N = len(ids)
    T = max(int(len(R)), 1)
    if N == 0:
        return {}
    if N == 1:
        return {ids[0]: float(GROSS_BUDGET)}

    mu = R.mean().values.astype(float)
    sd = R.std().values.astype(float)
    sd = np.where(sd < 1e-9, 1e-9, sd)
    C = R.corr().values.astype(float)
    C = np.nan_to_num(C, nan=0.0, posinf=0.0, neginf=0.0)
    np.fill_diagonal(C, 1.0)
    # Symmetrize for safety
    C = 0.5 * (C + C.T)

    # --- Marchenko-Pastur denoise ---
    try:
        eigvals, eigvecs = sla.eigh(C)
    except sla.LinAlgError:
        eigvals, eigvecs = np.linalg.eigh(C)

    q = float(N) / float(T)
    lam_plus = (1.0 + np.sqrt(q)) ** 2
    bulk_mask = eigvals < lam_plus
    eigvals_clean = eigvals.copy()
    if bulk_mask.sum() >= 1:
        bulk_mean = float(eigvals[bulk_mask].mean())
        eigvals_clean[bulk_mask] = bulk_mean
        # --- Detoning: replace dominant (largest) eigenvalue with bulk mean ---
        eigvals_clean[-1] = bulk_mean
    eigvals_clean = np.clip(eigvals_clean, 1e-6, None)

    C_clean = eigvecs @ np.diag(eigvals_clean) @ eigvecs.T
    d = np.sqrt(np.clip(np.diag(C_clean), 1e-12, None))
    C_clean = C_clean / np.outer(d, d)
    np.fill_diagonal(C_clean, 1.0)
    C_clean = 0.5 * (C_clean + C_clean.T)
    Sigma = (sd[:, None] * sd[None, :]) * C_clean

    # --- Hierarchical clustering on correlation distance ---
    dist = np.sqrt(np.clip(0.5 * (1.0 - C_clean), 0.0, 1.0))
    np.fill_diagonal(dist, 0.0)
    cond = ssd.squareform(dist, checks=False)
    Z = sch.linkage(cond, method="average")
    k = max(2, min(int(round(np.sqrt(N))), K_CLUSTERS_MAX, N - 1))
    labels = sch.fcluster(Z, t=k, criterion="maxclust")
    cluster_ids = sorted(set(labels.tolist()))

    # --- Intra-cluster tangency ---
    w_intra = np.zeros(N)
    cluster_ports = []
    for c in cluster_ids:
        idx = np.where(labels == c)[0]
        if idx.size == 1:
            w_intra[idx[0]] = 1.0
            cluster_ports.append(R.iloc[:, idx[0]].values)
            continue
        S = Sigma[np.ix_(idx, idx)]
        m = mu[idx]
        tr = float(np.trace(S))
        reg = max(1e-6, 1e-4 * tr / float(idx.size))
        S_reg = S + reg * np.eye(idx.size)
        try:
            w_c = sla.solve(S_reg, m, assume_a="pos")
        except Exception:
            w_c = sla.pinvh(S_reg) @ m
        w_c = np.clip(w_c, 0.0, None)
        s_w = float(w_c.sum())
        if s_w <= 1e-12:
            w_c = np.ones(idx.size) / float(idx.size)
        else:
            w_c = w_c / s_w
        w_intra[idx] = w_c
        cluster_ports.append(R.iloc[:, idx].values @ w_c)

    # --- Inter-cluster tangency on cluster portfolios ---
    Rc = np.column_stack(cluster_ports)
    mu_c = Rc.mean(axis=0)
    if Rc.shape[1] == 1:
        w_inter = np.array([1.0])
    else:
        Sc = np.cov(Rc.T)
        Sc = np.atleast_2d(Sc)
        Sc = 0.5 * (Sc + Sc.T)
        tr_c = float(np.trace(Sc))
        reg_c = max(1e-6, 1e-4 * tr_c / float(Sc.shape[0]))
        Sc_reg = Sc + reg_c * np.eye(Sc.shape[0])
        try:
            w_inter = sla.solve(Sc_reg, mu_c, assume_a="pos")
        except Exception:
            w_inter = sla.pinvh(Sc_reg) @ mu_c
        w_inter = np.clip(w_inter, 0.0, None)
        s_i = float(w_inter.sum())
        if s_i <= 1e-12:
            w_inter = np.ones(Rc.shape[1]) / float(Rc.shape[1])
        else:
            w_inter = w_inter / s_i

    # --- Compose ---
    w_final = np.zeros(N)
    for i, c in enumerate(cluster_ids):
        idx = np.where(labels == c)[0]
        w_final[idx] = w_intra[idx] * float(w_inter[i])

    l1 = float(np.abs(w_final).sum())
    if l1 <= 1e-12:
        w_final = np.ones(N) / float(N)
    else:
        try:
            w_final = np.asarray(normalize_coefficients(w_final, "l1"), dtype=float)
        except Exception:
            w_final = w_final / l1

    w_final = w_final * float(GROSS_BUDGET)
    return {ids[i]: float(w_final[i]) for i in range(N)}


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids, _ = _shortlist_and_coefficients(RUN_ID)
    return ids


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    _, coeffs = _shortlist_and_coefficients(RUN_ID)
    return {mid: float(coeffs.get(mid, 0.0)) for mid in member_ids}


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