Looking at the recent leaderboard pattern and the user's "cov-FREE composition" guidance, I'll attempt a method **not yet tried** in the auto_001..022+ list: **Ward hierarchical clustering on the correlation-distance matrix, take the single highest-IS-Sharpe alpha as each cluster centroid, equal-weight over centroids** (Lopez de Prado 2016 HRP framework adapted to centroid-per-cluster selection, à la Raffinot's "diversification by clustering").

Mechanistic justification for hitting OS Sharpe ≥ 2.0:
- **Avoids the 1/σ trap** — every prior winner used Σ⁻¹·μ (tangency) or Σ⁻¹·1 (MinVar), both of which underweight high-vol/high-return alphas and yield mean row L1 ≈ 0.05 (95 % cash). Equal-weight over centroids preserves native member leverage.
- **Regime-robust by construction** — per-year Sharpe stability filter (positive in 2022 / 2023 / 2024) + max IS drawdown < 25 % discards alphas that were lucky in one sub-regime.
- **Concentrated (K=6)** matches the empirical sweet spot n ∈ [5, 8].
- **Sign-aligned via `member_signs_ic`** so IC<0 alphas contribute their deployable sign, not their raw historical sign.
- **Gross scaled ×3** after L1-normalization so the runner's row-L1 ≤ 1 clamp actually bites (target effective gross ≈ 0.5–0.8).

Idea family confirmed unused so far in this run (checking auto_001..022 list: neumann, NCO, HERC, BL, DRP-eigenbasis, MaxDiv, mean-CVaR, fractional Kelly, HRP-quasidiag, JS, CSCV-bootstrap, antibias, stability-IR, bootstrap-ERC, PBO, PC1-resid, regime-year, mean-semivar, hedge-EG, CCM, STARR-CVaR, Calmar — **Ward-cluster-centroid-equal-weight is not among them**).

```python COMPOSITE_FILE
"""Ward-cluster centroids equal-weight composite (Lopez de Prado 2016 HRP framework,
Raffinot 2018 cluster-rep variant): one highest-IS-Sharpe alpha per Ward cluster,
1/K weighted, gross-rescaled to escape the 1/sigma cov-inversion trap. Pre-filtered
by per-year IS Sharpe stability and max IS drawdown < 25%."""
from __future__ import annotations
import argparse
import numpy as np
import pandas as pd
import scipy.cluster.hierarchy as sch
import scipy.spatial.distance as ssd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    member_signs_ic,
    apply_signs,
    select_is_submittable,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_099"
COMPOSITION_NOTE = "ward_cluster_centroid_k6_yearstable_dd25_eqweight_gross_x3"

RUN_ID = "run_2026_05_c"
K_CLUSTERS = 6
MAX_DD_THRESH = 0.25
MIN_SHARPE_FLOOR = 0.20
SCALE_UP = 3.0

_cache: dict = {}


def _sharpe(returns: pd.Series) -> float:
    if returns is None or returns.empty:
        return 0.0
    sd = float(returns.std())
    if not np.isfinite(sd) or sd <= 0:
        return 0.0
    return float(returns.mean() / sd * np.sqrt(252.0))


def _max_dd(returns: pd.Series) -> float:
    r = returns.fillna(0.0)
    if r.empty:
        return 1.0
    eq = (1.0 + r).cumprod()
    peak = eq.cummax()
    dd = eq / peak - 1.0
    return float(-dd.min())


def _per_year_positive(returns: pd.Series) -> bool:
    if returns.empty:
        return False
    idx = pd.to_datetime(returns.index)
    years = np.asarray(idx.year)
    seen = 0
    for y in np.unique(years):
        mask = years == y
        if mask.sum() < 20:
            continue
        seen += 1
        sub = returns[mask]
        if _sharpe(sub) <= 0.0:
            return False
    return seen >= 1


def _filter_pool(ids: list[str], R: pd.DataFrame) -> list[str]:
    kept = []
    for col in R.columns:
        s = R[col].dropna()
        if len(s) < 60:
            continue
        if _sharpe(s) < MIN_SHARPE_FLOOR:
            continue
        if _max_dd(s) > MAX_DD_THRESH:
            continue
        if not _per_year_positive(s):
            continue
        kept.append(col)
    return kept


def _ward_centroids(R: pd.DataFrame, kept: list[str], k: int) -> list[str]:
    if len(kept) <= k:
        return list(kept)
    sub = R[kept].fillna(0.0)
    corr = sub.corr().values
    corr = np.nan_to_num(corr, nan=0.0, posinf=0.0, neginf=0.0)
    corr = np.clip(corr, -1.0, 1.0)
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
    np.fill_diagonal(dist, 0.0)
    dist = 0.5 * (dist + dist.T)
    condensed = ssd.squareform(dist, checks=False)
    Z = sch.linkage(condensed, method="ward")
    labels = sch.fcluster(Z, t=k, criterion="maxclust")
    sharpes = {col: _sharpe(sub[col].dropna()) for col in kept}
    centroids: list[str] = []
    for c in np.unique(labels):
        members = [kept[i] for i in range(len(kept)) if labels[i] == c]
        if not members:
            continue
        best = max(members, key=lambda m: sharpes.get(m, 0.0))
        centroids.append(best)
    return centroids


def _prepare() -> tuple[list[str], pd.DataFrame, dict[str, int]]:
    ids = select_is_submittable(RUN_ID)
    if not ids:
        return [], pd.DataFrame(), {}
    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.empty:
        return [], pd.DataFrame(), {}
    return ids, R, signs


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids, R, signs = _prepare()
    if R.empty:
        return []
    kept = _filter_pool(ids, R)
    if len(kept) < 2:
        sharpes_all = {c: _sharpe(R[c].dropna()) for c in R.columns}
        kept = sorted(sharpes_all, key=lambda k: -sharpes_all[k])[: max(K_CLUSTERS, 2)]
    centroids = _ward_centroids(R, kept, K_CLUSTERS)
    if len(centroids) < 2:
        sharpes_k = {c: _sharpe(R[c].dropna()) for c in kept}
        centroids = sorted(sharpes_k, key=lambda k: -sharpes_k[k])[: max(K_CLUSTERS, 2)]
    _cache["R"] = R
    _cache["signs"] = signs
    _cache["centroids"] = centroids
    return centroids


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    R = _cache.get("R")
    signs = _cache.get("signs") or {}
    if R is None or R.empty:
        ids = select_is_submittable(RUN_ID)
        signs = member_signs_ic(RUN_ID, ids)
        R = load_member_is_returns(RUN_ID, ids, signs=signs)

    member_ids = [m for m in member_ids if m in R.columns]
    if not member_ids:
        return {}

    raw = {m: 1.0 for m in member_ids}
    raw = normalize_coefficients(raw, "l1")

    coef = {m: float(raw[m]) * SCALE_UP for m in member_ids}

    sign_map = {m: int(signs.get(m, 1) or 1) for m in member_ids}
    coef = apply_signs(coef, sign_map)
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
