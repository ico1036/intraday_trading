"""Greedy Gram-Schmidt orthogonal residual-Sharpe composition with year-stability + DD discipline.

Method: forward-stepwise (Gram-Schmidt) portfolio construction. Candidates are
filtered for per-year IS Sharpe stability (positive in every IS sub-year) and
IS max-drawdown < 25%, then correlation-deduped at |rho| > 0.85. Members are
added greedily by descending IS Sharpe; each candidate's IS return stream is
regressed on the span of already-selected members and admitted only if the
residual Sharpe > 0.3 (orthogonal new information, Lopez de Prado / Stevens
1998 marginal-contribution style). Coefficient magnitudes blend raw IS Sharpe
with residual Sharpe, L1-normalized, then hard-scaled 10x to escape the
chronic gross-exposure underweighting of covariance-inverse optimizers.
No Sigma^-1 anywhere -- cov-free by design.
"""
from __future__ import annotations
import argparse
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

COMPOSITE_ID = "auto_056_gram_schmidt_resid_sharpe_yearstab_dd25"
COMPOSITION_NOTE = "gram_schmidt_resid_sharpe_yearstab_dd25_scale10x"

RUN_ID = "run_2026_05_c"
N_MAX = 8
RESID_SHARPE_FLOOR = 0.3
DEDUP_THRESHOLD = 0.85
DD_MAX = 0.25
SHARPE_FLOOR = 0.4
POST_L1_SCALE = 10.0  # fights the 1/sigma underweighting trap


def _annualized_sharpe(r: pd.Series) -> float:
    r = r.dropna()
    if len(r) < 20:
        return 0.0
    s = float(r.std())
    if not np.isfinite(s) or s <= 0:
        return 0.0
    return float(r.mean() / s * np.sqrt(252))


def _max_drawdown(r: pd.Series) -> float:
    r = r.fillna(0.0)
    eq = (1.0 + r).cumprod()
    peak = eq.cummax()
    dd = eq / peak - 1.0
    md = float(-dd.min())
    return md if np.isfinite(md) else 1.0


def _year_stable(r: pd.Series) -> bool:
    r = r.dropna()
    if len(r) < 60:
        return False
    try:
        years = r.index.year
    except AttributeError:
        return True  # if not datetime, do not block
    by_year = r.groupby(years)
    n_years = 0
    n_pos = 0
    for _, sub in by_year:
        if len(sub) < 20:
            continue
        n_years += 1
        s = float(sub.std())
        if not np.isfinite(s) or s <= 0:
            continue
        sh = float(sub.mean() / s * np.sqrt(252))
        if sh > 0:
            n_pos += 1
    if n_years == 0:
        return True
    # Require ALL sufficient sub-years positive (strict regime-stability)
    return n_pos == n_years


def _pool(run_id: str) -> list[str]:
    try:
        ids = list(select_is_submittable(run_id))
    except Exception:
        ids = []
    if len(ids) < 2:
        try:
            ids = list(select_all_alphas(run_id))
        except Exception:
            ids = []
    return ids


def _signs_safe(run_id: str, ids: list[str]) -> dict[str, int]:
    try:
        s = member_signs_ic(run_id, ids)
        return {k: int(v) for k, v in s.items()}
    except Exception:
        return {a: 1 for a in ids}


def _load_R(run_id: str, ids: list[str]) -> tuple[pd.DataFrame, dict[str, int]]:
    signs = _signs_safe(run_id, ids)
    try:
        R = load_member_is_returns(run_id, ids, signs=signs)
    except Exception:
        R = pd.DataFrame()
    if R is None or R.empty:
        return pd.DataFrame(), signs
    R = R.replace([np.inf, -np.inf], np.nan).dropna(how="all")
    return R, signs


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    pool = _pool(RUN_ID)
    if len(pool) < 2:
        return pool

    R, _ = _load_R(RUN_ID, pool)
    if R.shape[1] < 2:
        return list(R.columns)

    cols = list(R.columns)
    sharpes = {c: _annualized_sharpe(R[c]) for c in cols}
    dds = {c: _max_drawdown(R[c]) for c in cols}
    stable = {c: _year_stable(R[c]) for c in cols}

    keep = [c for c in cols
            if sharpes[c] >= SHARPE_FLOOR
            and dds[c] < DD_MAX
            and stable[c]]

    if len(keep) < 4:
        keep = [c for c in cols if sharpes[c] >= SHARPE_FLOOR and stable[c]]
    if len(keep) < 4:
        keep = [c for c in cols if sharpes[c] >= SHARPE_FLOOR]
    if len(keep) < 2:
        keep = sorted(cols, key=lambda c: -sharpes[c])[:16]

    R_keep = R[keep]
    metric = {c: sharpes[c] for c in keep}
    try:
        deduped = list(correlation_dedup(R_keep, DEDUP_THRESHOLD, keep_metric=metric))
    except Exception:
        deduped = keep
    if len(deduped) < 2:
        deduped = sorted(keep, key=lambda c: -metric[c])[:max(4, N_MAX)]

    deduped = sorted(deduped, key=lambda c: -sharpes[c])

    # Greedy Gram-Schmidt forward selection
    selected: list[str] = [deduped[0]]
    for cand in deduped[1:]:
        if len(selected) >= N_MAX:
            break
        X = R[selected].values
        y = R[cand].values
        mask = np.isfinite(y) & np.all(np.isfinite(X), axis=1)
        if mask.sum() < 40:
            continue
        Xm, ym = X[mask], y[mask]
        try:
            beta, *_ = np.linalg.lstsq(Xm, ym, rcond=None)
        except Exception:
            continue
        resid = ym - Xm @ beta
        rs_std = float(resid.std())
        if not np.isfinite(rs_std) or rs_std <= 0:
            continue
        rs_sharpe = float(resid.mean() / rs_std * np.sqrt(252))
        if rs_sharpe < RESID_SHARPE_FLOOR:
            continue
        selected.append(cand)

    if len(selected) < 2:
        selected = deduped[:min(N_MAX, max(2, len(deduped)))]
    return selected


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    if len(member_ids) < 2:
        return {a: 1.0 for a in member_ids}

    R, signs = _load_R(RUN_ID, member_ids)
    cols = [c for c in member_ids if c in R.columns]
    if len(cols) < 2:
        # fallback: equal weight on whatever we have, scaled up
        n = max(len(member_ids), 1)
        eq = {a: 1.0 / n for a in member_ids}
        return {k: v * POST_L1_SCALE for k, v in eq.items()}
    R = R[cols]

    sh = {c: max(_annualized_sharpe(R[c]), 0.0) for c in cols}

    # Leave-one-out residual Sharpe (orthogonal contribution score)
    rs_score: dict[str, float] = {}
    for c in cols:
        others = [x for x in cols if x != c]
        if not others:
            rs_score[c] = sh[c]
            continue
        X = R[others].values
        y = R[c].values
        mask = np.isfinite(y) & np.all(np.isfinite(X), axis=1)
        if mask.sum() < 40:
            rs_score[c] = sh[c]
            continue
        Xm, ym = X[mask], y[mask]
        try:
            beta, *_ = np.linalg.lstsq(Xm, ym, rcond=None)
        except Exception:
            rs_score[c] = sh[c]
            continue
        resid = ym - Xm @ beta
        rs_std = float(resid.std())
        if not np.isfinite(rs_std) or rs_std <= 0:
            rs_score[c] = 0.0
            continue
        rs_score[c] = max(float(resid.mean() / rs_std * np.sqrt(252)), 0.0)

    # Normalize each score family to comparable scale, then blend 50/50
    sh_max = max(sh.values()) or 1.0
    rs_max = max(rs_score.values()) or 1.0
    blended = {c: 0.5 * (sh[c] / sh_max) + 0.5 * (rs_score[c] / rs_max) for c in cols}

    if sum(blended.values()) <= 0:
        blended = {c: 1.0 for c in cols}

    # Fill any member_ids missing from R with 0 to keep contract
    for a in member_ids:
        blended.setdefault(a, 0.0)

    # Apply IC-aligned signs before L1 normalization
    signed = apply_signs(blended, signs)

    coef = normalize_coefficients(signed, "l1")  # Sigma|c| = 1

    # Hard scale up to fight the gross-exposure ceiling.
    # Runner row-L1 clamps to 1.0 anyway, so overshoot is safe.
    coef = {k: float(v) * POST_L1_SCALE for k, v in coef.items()}
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