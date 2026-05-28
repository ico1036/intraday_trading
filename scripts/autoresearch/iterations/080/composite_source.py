"""HERC-inspired Ward cluster-centroid composite with per-year IS stability and DD discipline (Raffinot 2018; Lopez de Prado 2016 HRP)."""
from __future__ import annotations
import argparse
import math
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
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_080_herc_ward_centroid_yearstable_dd25_k6_eq"
COMPOSITION_NOTE = "herc_ward_centroid_yearstable_dd25_k6_eqw_gross075"

RUN_ID = "run_2026_05_c"
N_CLUSTERS = 6
DD_THRESHOLD = 0.25
DEDUP_RHO = 0.85
TARGET_L1_AFTER_NORM = 0.75
MIN_DAYS = 60
MIN_YEAR_DAYS = 20


def _max_drawdown(r: pd.Series) -> float:
    s = r.fillna(0.0)
    cum = (1.0 + s).cumprod()
    peak = cum.cummax()
    dd = (cum / peak) - 1.0
    val = dd.min()
    if not np.isfinite(val):
        return float("inf")
    return float(-val)


def _ann_sharpe(r: pd.Series) -> float:
    if r is None or len(r) < 2:
        return 0.0
    sd = r.std()
    if sd is None or not np.isfinite(sd) or sd <= 0:
        return 0.0
    mu = r.mean()
    if not np.isfinite(mu):
        return 0.0
    return float(mu / sd * math.sqrt(365.0))


def _year_stable(r: pd.Series, min_sh: float = 0.0) -> bool:
    if r.empty:
        return False
    try:
        idx = pd.to_datetime(r.index, errors="coerce")
    except Exception:
        return True
    if idx.isna().all():
        return True
    s = pd.Series(r.values, index=idx).dropna()
    if s.empty:
        return False
    for _, sub in s.groupby(s.index.year):
        if len(sub) < MIN_YEAR_DAYS:
            continue
        sh = _ann_sharpe(sub)
        if sh <= min_sh:
            return False
    return True


def _filter_pool(R: pd.DataFrame, strict: bool) -> tuple[list[str], dict[str, float]]:
    kept: list[str] = []
    sharpe_map: dict[str, float] = {}
    dd_cap = DD_THRESHOLD if strict else DD_THRESHOLD * 1.5
    for col in R.columns:
        r = R[col].dropna()
        if len(r) < MIN_DAYS:
            continue
        sh = _ann_sharpe(r)
        if sh <= 0:
            continue
        if strict and not _year_stable(r, 0.0):
            continue
        if _max_drawdown(r) > dd_cap:
            continue
        kept.append(col)
        sharpe_map[col] = sh
    return kept, sharpe_map


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    try:
        candidates = select_is_submittable(RUN_ID)
    except Exception:
        candidates = []
    if not candidates:
        try:
            candidates = select_all_alphas(RUN_ID)
        except Exception:
            candidates = []
    if not candidates:
        return []

    try:
        signs = member_signs_ic(RUN_ID, candidates)
    except Exception:
        signs = {a: 1 for a in candidates}
    signs = {a: int(signs.get(a, 1)) for a in candidates}

    try:
        R = load_member_is_returns(RUN_ID, candidates, signs=signs)
    except Exception:
        R = None
    if R is None or R.empty or R.shape[1] < 2:
        return list(candidates[: min(len(candidates), 6)])

    kept, sharpe_map = _filter_pool(R, strict=True)
    if len(kept) < N_CLUSTERS:
        kept, sharpe_map = _filter_pool(R, strict=False)
    if len(kept) < 2:
        all_sh = {c: _ann_sharpe(R[c].dropna()) for c in R.columns}
        ranked = sorted(all_sh.items(), key=lambda x: x[1], reverse=True)
        chosen = [c for c, sh in ranked[:6] if sh > 0]
        if len(chosen) >= 2:
            return chosen
        return list(R.columns[: min(2, R.shape[1])])

    R_k = R[kept]
    try:
        deduped = correlation_dedup(R_k, threshold=DEDUP_RHO, keep_metric=sharpe_map)
    except Exception:
        deduped = list(kept)
    if not deduped or len(deduped) < 2:
        deduped = list(kept)

    if len(deduped) <= N_CLUSTERS:
        return list(deduped)

    R_d = R_k[deduped].fillna(0.0)
    try:
        corr = R_d.corr().values
        corr = np.nan_to_num(corr, nan=0.0, posinf=0.0, neginf=0.0)
        corr = np.clip(corr, -1.0, 1.0)
        dist = np.sqrt(np.maximum(0.0, 0.5 * (1.0 - corr)))
        np.fill_diagonal(dist, 0.0)
        dist = 0.5 * (dist + dist.T)
        condensed = ssd.squareform(dist, checks=False)
        Z = sch.linkage(condensed, method="ward")
        labels = sch.fcluster(Z, t=N_CLUSTERS, criterion="maxclust")
    except Exception:
        return list(deduped[:N_CLUSTERS])

    by_cluster: dict[int, tuple[str, float]] = {}
    for aid, lab in zip(deduped, labels):
        sh = sharpe_map.get(aid, 0.0)
        lab_i = int(lab)
        cur = by_cluster.get(lab_i)
        if cur is None or sh > cur[1]:
            by_cluster[lab_i] = (aid, sh)
    centroids = [v[0] for v in by_cluster.values()]
    if len(centroids) < 2:
        return list(deduped[:N_CLUSTERS])
    return centroids


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}
    try:
        signs = member_signs_ic(RUN_ID, member_ids)
    except Exception:
        signs = {a: 1 for a in member_ids}
    signs = {a: int(signs.get(a, 1)) for a in member_ids}

    n = len(member_ids)
    base = {a: 1.0 / n for a in member_ids}
    try:
        signed = apply_signs(base, signs)
    except Exception:
        signed = {a: base[a] * (1 if signs.get(a, 1) >= 0 else -1) for a in member_ids}

    try:
        normed = normalize_coefficients(signed, "l1")
    except Exception:
        total = sum(abs(v) for v in signed.values())
        if total <= 0:
            normed = {a: 1.0 / n for a in member_ids}
        else:
            normed = {k: v / total for k, v in signed.items()}

    scaled = {k: float(v) * TARGET_L1_AFTER_NORM for k, v in normed.items()}
    # ensure every input id is present
    for a in member_ids:
        scaled.setdefault(a, 0.0)
    return scaled


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