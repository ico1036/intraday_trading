"""Exponentiated Gradient FTRL (Helmbold-Schapire-Singer-Warmuth 1998) online portfolio
on year-stable, drawdown-disciplined, IC-sign-aligned concentrated top-k members."""
from __future__ import annotations
import argparse, math
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

COMPOSITE_ID = "auto_035_eg_ftrl_online_yearstable_dd25_top8_corr"
COMPOSITION_NOTE = "eg_ftrl_online_yearstable_dd25_top8_corr080_gross070"

RUN_ID = "run_2026_05_c"
TARGET_K = 8
CORR_THR = 0.80
DD_CAP = 0.25
GROSS_TARGET = 0.70
EG_ETA = 0.08
DAILY_CLIP = 0.5


def _ensure_dt(r: pd.Series) -> pd.Series:
    if isinstance(r.index, pd.DatetimeIndex):
        return r
    try:
        r = r.copy()
        r.index = pd.to_datetime(r.index)
        return r
    except Exception:
        return r


def _per_year_sharpe_ok(r: pd.Series) -> bool:
    r = r.dropna()
    if r.empty:
        return False
    r = _ensure_dt(r)
    if not isinstance(r.index, pd.DatetimeIndex):
        return False
    grp = r.groupby(r.index.year)
    if grp.ngroups < 2:
        return False
    for _, rr in grp:
        if len(rr) < 20:
            continue
        sd = rr.std()
        if sd is None or not np.isfinite(sd) or sd <= 0:
            return False
        if rr.mean() <= 0:
            return False
        if (rr.mean() / sd) * math.sqrt(252) <= 0.0:
            return False
    return True


def _max_drawdown(r: pd.Series) -> float:
    r = r.dropna()
    if r.empty:
        return 1.0
    eq = (1.0 + r).cumprod()
    peak = eq.cummax()
    dd = (eq / peak) - 1.0
    mn = dd.min()
    if not np.isfinite(mn):
        return 1.0
    return float(-mn)


def _sharpe(r: pd.Series) -> float:
    r = r.dropna()
    if r.empty:
        return 0.0
    sd = r.std()
    if sd is None or not np.isfinite(sd) or sd <= 0:
        return 0.0
    return float(r.mean() / sd * math.sqrt(252))


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if len(ids) < TARGET_K * 2:
        ids = select_all_alphas(RUN_ID)
    if not ids:
        return []

    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.empty:
        return []
    R = R.dropna(axis=1, how="all")

    keep: list[str] = []
    sharpes: dict[str, float] = {}
    for a in R.columns:
        s = R[a].dropna()
        if len(s) < 60:
            continue
        sh = _sharpe(s)
        if sh <= 0:
            continue
        if _max_drawdown(s) > DD_CAP:
            continue
        if not _per_year_sharpe_ok(s):
            continue
        keep.append(a)
        sharpes[a] = sh

    if len(keep) < 2:
        keep = []
        sharpes = {}
        for a in R.columns:
            s = R[a].dropna()
            if len(s) < 30:
                continue
            sh = _sharpe(s)
            if sh <= 0:
                continue
            if _max_drawdown(s) > 0.40:
                continue
            keep.append(a)
            sharpes[a] = sh

    if len(keep) < 2:
        all_sh = {a: _sharpe(R[a]) for a in R.columns}
        keep = [a for a, v in all_sh.items() if v > 0]
        sharpes = {a: all_sh[a] for a in keep}

    if len(keep) < 2:
        return []

    R_keep = R[keep]
    try:
        deduped = correlation_dedup(R_keep, threshold=CORR_THR, keep_metric=sharpes)
    except Exception:
        deduped = list(keep)

    deduped = [a for a in deduped if a in sharpes]
    deduped.sort(key=lambda x: sharpes.get(x, 0.0), reverse=True)
    selected = deduped[:TARGET_K]

    if len(selected) < 2:
        ranked = sorted(sharpes, key=lambda x: sharpes[x], reverse=True)
        selected = ranked[: max(2, TARGET_K)]

    return selected


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if not member_ids:
        return {}

    signs = member_signs_ic(RUN_ID, member_ids)
    for a in member_ids:
        signs.setdefault(a, 1)

    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    if R is None or R.empty:
        c = {a: 1.0 / len(member_ids) for a in member_ids}
        c = apply_signs(c, signs)
        c = normalize_coefficients(c, "l1")
        return {a: GROSS_TARGET * v for a, v in c.items()}

    R = R.dropna(how="all").fillna(0.0)
    cols = [a for a in member_ids if a in R.columns]
    if len(cols) < 2:
        c = {a: 1.0 / len(member_ids) for a in member_ids}
        c = apply_signs(c, signs)
        c = normalize_coefficients(c, "l1")
        return {a: GROSS_TARGET * v for a, v in c.items()}

    arr = R[cols].to_numpy(dtype=float)
    arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
    arr = np.clip(arr, -DAILY_CLIP, DAILY_CLIP)

    n = len(cols)
    w = np.ones(n, dtype=float) / n
    for t in range(arr.shape[0]):
        grad = arr[t]
        w = w * np.exp(EG_ETA * grad)
        s = w.sum()
        if not np.isfinite(s) or s <= 0:
            w = np.ones(n, dtype=float) / n
        else:
            w = w / s

    # Sharpe tilt on EG weights to break ties toward genuinely robust members
    sharpe_arr = np.zeros(n, dtype=float)
    for i, a in enumerate(cols):
        sh = _sharpe(R[a])
        sharpe_arr[i] = max(sh, 0.0)
    if sharpe_arr.sum() > 0:
        tilt = sharpe_arr / sharpe_arr.sum()
        w = 0.7 * w + 0.3 * tilt
        w = w / w.sum()

    c: dict[str, float] = {a: float(w[i]) for i, a in enumerate(cols)}
    for a in member_ids:
        c.setdefault(a, 0.0)

    c = apply_signs(c, signs)
    c = normalize_coefficients(c, "l1")
    c = {a: GROSS_TARGET * v for a, v in c.items()}
    return c


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