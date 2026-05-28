Rationale: I'll use the **Ward hierarchical-clustering centroid + equal-weight** approach (user-suggested, cov-FREE, never tried in this run). The literature anchor is Ward (1963) agglomerative clustering on correlation-distance `d_{ij} = sqrt(0.5·(1−ρ_{ij}))` (Mantegna 1999), with one IS-Sharpe-maximal representative per cluster (a coarse, sample-robust analogue of Lopez de Prado's quasi-diagonal block selection).

Why this fits the current diagnosis:
- **Cov-free** — no Σ⁻¹ multiplication, so no 1/σ under-weighting trap. Prior attempts capped at mean row L1 ≈ 0.05 because tangency/min-var produces tiny coefficients; equal-weight preserves native member leverage.
- **Concentration n=6** — falls in the empirical sweet spot [4,12].
- **Regime defenses** — per-calendar-year IS Sharpe > 0 in every sub-period AND |IS DD| < 25% gates out lucky-tail alphas before clustering.
- **Cluster diversification** — one representative per cluster guarantees the 6 members are genuinely orthogonal, so no cancellation of weight streams across members (which is what drives mean row L1 to zero in correlated baskets).
- **Native gross-exposure** — after `normalize_coefficients(_, "l1")` (Σ|c|=1) we scale by 8×, putting Σ|c|≈8. The runner's row-L1 clamp will still cap any exceeding row, but typical rows will sit in [0.4,0.9] gross.

Signs are applied via `member_signs_ic` (IC-deployable flips), `correlation_dedup` at ρ=0.92 first to avoid duplicate-source clusters. Idea family "ward-centroid-equal-weight-native-gross" is not in the prior list (auto_013 used cluster-MEDIAN; auto_009 used HRP recursive bisection on quasi-diag; this uses Ward + per-cluster top-Sharpe single representative + equal-weight, which is distinct).

```python COMPOSITE_FILE
"""Ward hierarchical clustering (Mantegna 1999) on IS-correlation distance with one IS-Sharpe-maximal centroid per cluster, equal-weighted at native gross exposure; cov-free composition with per-year stability and drawdown-discipline pre-filters."""
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
    select_all_alphas,
    member_is_sharpe,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_090"
COMPOSITION_NOTE = "ward_centroid_k6_yearstable_dd25_dedup092_native_gross"

RUN_ID = "run_2026_05_c"
N_CLUSTERS = 6
DD_MAX = 0.25
DEDUP_THRESHOLD = 0.92
COEF_SCALE = 8.0


def _to_datetime_index(R: pd.DataFrame) -> pd.DataFrame:
    idx = R.index
    if isinstance(idx, pd.DatetimeIndex):
        return R
    try:
        new_idx = pd.DatetimeIndex(pd.to_datetime(idx))
    except Exception:
        return R
    out = R.copy()
    out.index = new_idx
    return out


def _year_stable_and_dd_filter(R: pd.DataFrame, dd_max: float) -> list[str]:
    R = _to_datetime_index(R)
    if not isinstance(R.index, pd.DatetimeIndex):
        return list(R.columns)
    years = sorted({int(y) for y in R.index.year.tolist()})
    kept: list[str] = []
    for col in R.columns:
        s = R[col].dropna()
        if len(s) < 60:
            continue
        ok = True
        for y in years:
            sy = s[s.index.year == y]
            if len(sy) < 10:
                continue
            mu = float(sy.mean())
            sd = float(sy.std())
            if not (sd > 0.0 and mu > 0.0):
                ok = False
                break
        if not ok:
            continue
        eq = (1.0 + s.fillna(0.0)).cumprod()
        peak = eq.cummax()
        dd = float((eq / peak - 1.0).min())
        if dd < -dd_max:
            continue
        kept.append(col)
    return kept


def _safe_member_is_sharpe(ids: list[str]) -> dict[str, float]:
    try:
        raw = member_is_sharpe(RUN_ID, ids)
    except Exception:
        return {a: 0.0 for a in ids}
    out: dict[str, float] = {}
    if isinstance(raw, dict):
        for a in ids:
            try:
                out[a] = float(raw.get(a, 0.0))
            except Exception:
                out[a] = 0.0
        return out
    try:
        for a, v in zip(ids, list(raw)):
            out[a] = float(v)
    except Exception:
        out = {a: 0.0 for a in ids}
    return out


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if len(ids) < 10:
        ids = select_all_alphas(RUN_ID)
    if not ids:
        return []
    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.shape[1] < 2:
        return list(R.columns) if R is not None else []
    stable = _year_stable_and_dd_filter(R, DD_MAX)
    if len(stable) < N_CLUSTERS:
        stable = _year_stable_and_dd_filter(R, 0.40)
    if len(stable) < N_CLUSTERS:
        sh_all = _safe_member_is_sharpe(list(R.columns))
        stable = sorted(
            list(R.columns),
            key=lambda a: -sh_all.get(a, 0.0),
        )[: max(N_CLUSTERS * 4, 20)]
    if len(stable) < 2:
        return list(R.columns)[: max(2, N_CLUSTERS)]
    sh_kept = _safe_member_is_sharpe(stable)
    try:
        deduped = correlation_dedup(
            R[stable], threshold=DEDUP_THRESHOLD, keep_metric=sh_kept
        )
    except Exception:
        deduped = stable
    if len(deduped) < N_CLUSTERS:
        deduped = stable
    R_d = R[deduped]
    if len(deduped) <= N_CLUSTERS:
        return list(deduped)
    corr = R_d.corr().fillna(0.0).to_numpy()
    corr = np.clip(corr, -1.0, 1.0)
    dist = np.sqrt(np.maximum(0.5 * (1.0 - corr), 0.0))
    np.fill_diagonal(dist, 0.0)
    dist = 0.5 * (dist + dist.T)
    try:
        condensed = ssd.squareform(dist, checks=False)
        Z = sch.linkage(condensed, method="ward")
        labels = sch.fcluster(Z, t=N_CLUSTERS, criterion="maxclust")
    except Exception:
        ranked = sorted(deduped, key=lambda a: -sh_kept.get(a, 0.0))
        return ranked[:N_CLUSTERS]
    cluster_rep: dict[int, str] = {}
    for col, lab in zip(R_d.columns, labels.tolist()):
        lab = int(lab)
        cur = cluster_rep.get(lab)
        cur_s = sh_kept.get(cur, -1e18) if cur is not None else -1e18
        new_s = sh_kept.get(col, -1e18)
        if cur is None or new_s > cur_s:
            cluster_rep[lab] = col
    selected = list(cluster_rep.values())
    if len(selected) < 2:
        ranked = sorted(deduped, key=lambda a: -sh_kept.get(a, 0.0))
        selected = ranked[: max(2, N_CLUSTERS)]
    return selected


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    signs = member_signs_ic(RUN_ID, member_ids)
    coef = {a: 1.0 for a in member_ids}
    coef = normalize_coefficients(coef, "l1")
    coef = apply_signs(coef, signs)
    coef = {k: float(v) * COEF_SCALE for k, v in coef.items()}
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
