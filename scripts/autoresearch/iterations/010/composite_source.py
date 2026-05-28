"""High-return tangency composite with James-Stein mean shrinkage and Neumann-series Σ⁻¹ approximation on a Ledoit-Wolf shrunk covariance — Stein 1956 + Ledoit-Wolf 2004 + truncated Neumann inverse; sign-aligned via IC and Sharpe-tilted."""
from __future__ import annotations
import argparse
import numpy as np
import pandas as pd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    correlation_dedup,
    member_signs_ic,
    apply_signs,
    shrink_cov,
    select_is_submittable,
    select_all_alphas,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_010_james_stein_tangency_neumann_k6_lw020_to"
COMPOSITION_NOTE = "james_stein_tangency_neumann_k6_lw020_top30_dedup080_gross060"

RUN_ID = "run_2026_05_c"
PRE_TOP_N = 80
DEDUP_RHO = 0.80
FINAL_N = 30
NEUMANN_K = 6
LW_SHRINK = 0.20
GROSS_TARGET = 0.60


def _is_sharpe_map(alpha_index: pd.DataFrame, ids: list[str]) -> dict[str, float]:
    if alpha_index is None or len(alpha_index) == 0 or "is_sharpe" not in alpha_index.columns:
        return {a: 0.0 for a in ids}
    df = alpha_index[["alpha_id", "is_sharpe"]].dropna()
    m = dict(zip(df["alpha_id"].astype(str), df["is_sharpe"].astype(float)))
    return {a: float(m.get(a, 0.0)) for a in ids}


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if len(ids) < 2:
        ids = select_all_alphas(RUN_ID)
    if len(ids) < 2:
        return list(ids)

    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R.shape[1] < 2:
        return list(R.columns)

    cols = list(R.columns)
    sharpe_map = _is_sharpe_map(alpha_index, cols)
    if max(sharpe_map.values(), default=0.0) <= 0.0:
        mu = R.mean()
        sd = R.std().replace(0.0, np.nan)
        s = (mu / sd).fillna(0.0)
        sharpe_map = {a: float(s.get(a, 0.0)) for a in cols}

    ordered = sorted(cols, key=lambda a: sharpe_map.get(a, 0.0), reverse=True)
    top_ids = ordered[:PRE_TOP_N]
    R_top = R[top_ids]

    keep_metric = {a: float(sharpe_map.get(a, 0.0)) for a in top_ids}
    kept = correlation_dedup(R_top, threshold=DEDUP_RHO, keep_metric=keep_metric)
    kept = [a for a in kept if a in top_ids]
    if len(kept) < 2:
        kept = top_ids[: max(2, FINAL_N)]
    kept = sorted(kept, key=lambda a: keep_metric.get(a, 0.0), reverse=True)[:FINAL_N]
    return kept


def _neumann_inverse(S: np.ndarray, k: int) -> np.ndarray:
    n = S.shape[0]
    rng = np.random.RandomState(7)
    v = rng.randn(n)
    nv = float(np.linalg.norm(v))
    v = (v / nv) if nv > 1e-12 else np.ones(n) / np.sqrt(n)
    lam_max = 1e-6
    for _ in range(40):
        u = S @ v
        nu = float(np.linalg.norm(u))
        if nu < 1e-12:
            break
        v = u / nu
        lam_max = float(v @ (S @ v))
    if not np.isfinite(lam_max) or lam_max <= 1e-12:
        return np.eye(n)
    alpha = 1.0 / (1.10 * lam_max)
    M = np.eye(n) - alpha * S
    acc = np.eye(n)
    term = np.eye(n)
    for _ in range(k):
        term = term @ M
        acc = acc + term
    return alpha * acc


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    cols = list(R.columns)
    if len(cols) < 2:
        out = {a: 1.0 / max(1, len(member_ids)) for a in member_ids}
        return apply_signs(out, signs)

    R = R.fillna(0.0)
    X = R.values
    T, N = X.shape

    # Ledoit-Wolf style diagonal shrinkage on sample cov
    Sigma = np.asarray(shrink_cov(R, shrinkage=LW_SHRINK))
    if Sigma.shape != (N, N) or not np.all(np.isfinite(Sigma)):
        S_raw = np.cov(X, rowvar=False)
        if S_raw.ndim == 0:
            S_raw = np.array([[float(S_raw)]])
        Sigma = 0.8 * S_raw + 0.2 * np.diag(np.diag(S_raw))

    # James-Stein shrinkage of sample mean toward grand mean
    mu = X.mean(axis=0)
    mu_bar = float(np.mean(mu))
    diff = mu - mu_bar
    avg_var = float(np.mean(np.diag(Sigma)))
    denom = float(diff @ diff) * max(T, 1)
    if N > 2 and denom > 1e-12 and avg_var > 0.0:
        shrink = 1.0 - (N - 2) * avg_var / denom
        shrink = float(np.clip(shrink, 0.0, 1.0))
    else:
        shrink = 0.0
    mu_js = mu_bar + shrink * diff

    # Neumann-series Σ⁻¹ ≈ α Σ_{i=0..K} (I − αΣ)^i
    Sigma_inv = _neumann_inverse(Sigma, NEUMANN_K)

    # Tangency direction with shrunk mean
    w_raw = Sigma_inv @ mu_js
    if (not np.all(np.isfinite(w_raw))) or float(np.linalg.norm(w_raw)) < 1e-12:
        w_raw = mu.copy()

    # Floor at zero — signs are baked into R via member_signs_ic, so the
    # "deployable" direction is +; if tangency picks a member negatively
    # given its post-sign returns, drop it rather than flip-flopping.
    w_pos = np.where(w_raw > 0, w_raw, 0.0)
    if float(w_pos.sum()) < 1e-12:
        w_pos = np.abs(w_raw)
    if float(w_pos.sum()) < 1e-12:
        w_pos = np.ones(N)

    # Sharpe tilt: concentrate on high-Sharpe / high-return members
    sd = X.std(axis=0)
    sd = np.where(sd > 0, sd, 1.0)
    sharpe = mu / sd
    tilt = np.clip(sharpe, 0.0, None)
    tmax = float(tilt.max()) if tilt.size else 0.0
    if tmax > 0.0:
        tilt = tilt / tmax
    w_pos = w_pos * (0.4 + 0.6 * tilt)
    if float(w_pos.sum()) < 1e-12:
        w_pos = np.ones(N)

    coef = {cols[i]: float(w_pos[i]) for i in range(N)}
    coef = normalize_coefficients(coef, scheme="l1")
    coef = {a: GROSS_TARGET * float(v) for a, v in coef.items()}
    coef = apply_signs(coef, signs)

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