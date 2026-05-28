"""Michaud (1998) Resampled Efficient Frontier — bootstrap-averaged
Ledoit-Wolf-shrunk tangency on year-stable, drawdown-disciplined,
IC-sign-aligned, correlation-deduped top-N IS members. LW shrinkage
inside each bootstrap acts as the eigenvalue-divergence suppressor
(Neumann-spirit regularization without explicit truncation order)."""
from __future__ import annotations
import argparse
import math
import numpy as np
import pandas as pd
import scipy.linalg as sla

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    select_is_submittable,
    select_all_alphas,
    member_signs_ic,
    member_is_sharpe,
    apply_signs,
    correlation_dedup,
    load_member_is_returns,
    normalize_coefficients,
    shrink_cov,
)

COMPOSITE_ID = "auto_027_michaud_resampled_tangency_yearstable_dd"
COMPOSITION_NOTE = "michaud_resampled_tangency_yearstable_dd_lw_top10"

RUN_ID = "run_2026_05_c"
TARGET_N = 10
DEDUP_RHO = 0.80
DD_MAX = 0.25
MIN_PER_YEAR_OBS = 20
MIN_YEARLY_SHARPE = 0.0
N_BOOTSTRAP = 200
LW_SHRINK = 0.20
GROSS_SCALE = 0.70
RNG_SEED = 27


def _coerce_dt_index(df_or_series):
    obj = df_or_series
    if isinstance(obj.index, pd.DatetimeIndex):
        return obj
    try:
        obj.index = pd.to_datetime(obj.index)
    except Exception:
        pass
    return obj


def _yearly_stable(r: pd.Series, threshold: float, min_obs: int) -> bool:
    r = r.dropna()
    if len(r) < min_obs * 2:
        return False
    r = _coerce_dt_index(r)
    if not isinstance(r.index, pd.DatetimeIndex):
        return False
    years = sorted(set(r.index.year))
    n_valid_years = 0
    for y in years:
        ry = r[r.index.year == y]
        if len(ry) < min_obs:
            continue
        sy = float(ry.std())
        if sy <= 0:
            return False
        sh = float(ry.mean()) / sy * math.sqrt(252.0)
        if sh <= threshold:
            return False
        n_valid_years += 1
    return n_valid_years >= 2


def _max_drawdown_additive(r: pd.Series) -> float:
    s = r.dropna().cumsum()
    if len(s) == 0:
        return 0.0
    return float((s - s.cummax()).min())


def _as_dict(maybe_mapping, keys):
    if isinstance(maybe_mapping, dict):
        return maybe_mapping
    try:
        return dict(maybe_mapping)
    except Exception:
        return {k: 0.0 for k in keys}


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids_all = list(select_is_submittable(RUN_ID))
    if len(ids_all) < TARGET_N * 3:
        ids_all = list(select_all_alphas(RUN_ID))
    if not ids_all:
        return []

    sharpe_raw = member_is_sharpe(RUN_ID, ids_all)
    sharpe_dict = _as_dict(sharpe_raw, ids_all)

    signs = member_signs_ic(RUN_ID, ids_all)
    R = load_member_is_returns(RUN_ID, ids_all, signs=signs)
    if R is None or getattr(R, "empty", True):
        return ids_all[:TARGET_N]
    R = R.dropna(axis=1, how="all")
    R = _coerce_dt_index(R)
    if R.shape[1] == 0:
        return ids_all[:TARGET_N]

    keep_ys = [a for a in R.columns
               if _yearly_stable(R[a], MIN_YEARLY_SHARPE, MIN_PER_YEAR_OBS)]
    if len(keep_ys) < TARGET_N:
        keep_ys = list(R.columns)

    keep_dd = [a for a in keep_ys
               if _max_drawdown_additive(R[a]) > -DD_MAX]
    if len(keep_dd) < TARGET_N:
        keep_dd = keep_ys

    keep_metric = {a: float(sharpe_dict.get(a, 0.0)) for a in keep_dd}
    R_keep = R[keep_dd]
    try:
        deduped = correlation_dedup(R_keep, threshold=DEDUP_RHO,
                                    keep_metric=keep_metric)
    except Exception:
        deduped = keep_dd
    if not deduped or len(deduped) < 2:
        deduped = sorted(keep_dd, key=lambda a: keep_metric.get(a, 0.0),
                         reverse=True)

    deduped_sorted = sorted(deduped, key=lambda a: keep_metric.get(a, 0.0),
                            reverse=True)
    chosen = deduped_sorted[:TARGET_N]
    if len(chosen) < 2:
        fallback = sorted(ids_all, key=lambda a: float(sharpe_dict.get(a, 0.0)),
                          reverse=True)
        chosen = list(dict.fromkeys(chosen + fallback))[:TARGET_N]
    return chosen


def member_weights(member_ids: list[str],
                   alpha_index: pd.DataFrame) -> dict[str, float]:
    n_in = len(member_ids)
    if n_in == 0:
        return {}
    if n_in == 1:
        return {member_ids[0]: GROSS_SCALE}

    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    if R is None or getattr(R, "empty", True):
        eq = GROSS_SCALE / n_in
        return {a: eq for a in member_ids}

    R = R.dropna(axis=1, how="all").dropna(axis=0, how="any")
    cols = list(R.columns)
    n = len(cols)
    if n < 2 or len(R) < 30:
        eq = GROSS_SCALE / max(n_in, 1)
        return {a: (eq if a in cols else 0.0) for a in member_ids} \
            if cols else {a: eq for a in member_ids}

    T = len(R)
    rng = np.random.default_rng(RNG_SEED)
    w_acc = np.zeros(n, dtype=float)
    n_ok = 0

    for _ in range(N_BOOTSTRAP):
        idx = rng.integers(0, T, size=T)
        Rb = R.iloc[idx].reset_index(drop=True)
        mu = Rb.mean().values.astype(float)
        if not np.all(np.isfinite(mu)):
            continue
        try:
            Sigma = shrink_cov(Rb, shrinkage=LW_SHRINK)
            Sigma = np.asarray(Sigma, dtype=float)
            if Sigma.shape != (n, n) or not np.all(np.isfinite(Sigma)):
                continue
            Sigma = Sigma + 1e-8 * np.eye(n)
            try:
                wb = sla.solve(Sigma, mu, assume_a="pos")
            except Exception:
                wb = sla.pinvh(Sigma) @ mu
        except Exception:
            continue
        if not np.all(np.isfinite(wb)):
            continue
        wb = np.clip(wb, -5.0, 5.0)
        s = float(np.abs(wb).sum())
        if s <= 1e-12:
            continue
        w_acc += wb / s
        n_ok += 1

    if n_ok == 0:
        eq = 1.0 / n
        coef_signed = {c: eq for c in cols}
    else:
        w_avg = (w_acc / n_ok).tolist()
        coef_signed = {c: float(w) for c, w in zip(cols, w_avg)}

    sign_subset = {k: int(signs.get(k, 1)) for k in cols}
    try:
        coef = apply_signs(coef_signed, sign_subset)
    except Exception:
        coef = {k: coef_signed[k] * sign_subset.get(k, 1) for k in coef_signed}

    if not isinstance(coef, dict):
        coef = dict(coef)
    total = sum(abs(float(v)) for v in coef.values())
    if total <= 1e-12:
        eq = 1.0 / n
        coef = {c: eq for c in cols}

    try:
        coef = normalize_coefficients(coef, "l1")
        if not isinstance(coef, dict):
            coef = dict(coef)
    except Exception:
        tot = sum(abs(float(v)) for v in coef.values()) or 1.0
        coef = {k: float(v) / tot for k, v in coef.items()}

    coef = {k: float(v) * GROSS_SCALE for k, v in coef.items()}

    out = {a: 0.0 for a in member_ids}
    for k, v in coef.items():
        if k in out:
            out[k] = float(v)
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