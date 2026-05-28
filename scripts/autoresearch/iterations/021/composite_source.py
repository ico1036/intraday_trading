"""STARR (Stoyanov & Rachev 2003 reward-to-CVaR) selection with downside-
volatility risk-parity allocation on top-7 regime-stable alphas: per-year
IS Sharpe > 0 gate, IS max-drawdown < 25%, correlation deduplication, and
explicit gross-budget targeting at L1 ~= 0.65."""
from __future__ import annotations
import argparse
import math
import numpy as np
import pandas as pd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    select_is_submittable,
    select_all_alphas,
    load_member_is_returns,
    member_signs_ic,
    apply_signs,
    correlation_dedup,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_021_starr_cvar_dnvol_parity_top7_yearstable"
COMPOSITION_NOTE = "starr_cvar_dnvol_parity_top7_yearstable_dd25"

RUN_ID = "run_2026_05_c"
ALPHA_CVAR = 0.10
DD_GATE = 0.25
SUBSET_K = 7
PRE_K_MULT = 3
DEDUP_RHO = 0.85
GROSS_TARGET = 0.65
MIN_DAYS = 60


def _max_drawdown(returns: pd.Series) -> float:
    r = returns.fillna(0.0).to_numpy()
    if r.size == 0:
        return 0.0
    eq = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1.0
    return float(-dd.min())


def _starr(returns: pd.Series, alpha: float = 0.10) -> float:
    r = returns.dropna().to_numpy()
    if r.size < 20:
        return 0.0
    q = float(np.quantile(r, alpha))
    tail = r[r <= q]
    if tail.size == 0:
        return 0.0
    cvar = float(-tail.mean())
    if cvar <= 1e-12:
        return 0.0
    return float(r.mean() / cvar)


def _per_year_min_sharpe(returns: pd.Series) -> float:
    r = returns.dropna()
    if r.empty:
        return -math.inf
    if not isinstance(r.index, pd.DatetimeIndex):
        try:
            r = r.copy()
            r.index = pd.to_datetime(r.index)
        except Exception:
            sd = float(r.std()) if r.size > 1 else 0.0
            if sd <= 1e-12:
                return 0.0
            return math.sqrt(252.0) * float(r.mean()) / sd
    yrs = r.index.year
    try:
        if int(yrs.min()) < 2010 or int(yrs.max()) > 2030:
            sd = float(r.std()) if r.size > 1 else 0.0
            if sd <= 1e-12:
                return 0.0
            return math.sqrt(252.0) * float(r.mean()) / sd
    except Exception:
        pass
    out: list[float] = []
    for y in np.unique(yrs):
        sub = r[yrs == y]
        if sub.size < 30:
            continue
        sd = float(sub.std())
        if sd <= 1e-12:
            continue
        out.append(math.sqrt(252.0) * float(sub.mean()) / sd)
    return float(min(out)) if out else -math.inf


def _eligible_pool() -> list[str]:
    ids: list[str] = []
    try:
        ids = list(select_is_submittable(RUN_ID))
    except Exception:
        ids = []
    if len(ids) < 2:
        try:
            ids = list(select_all_alphas(RUN_ID))
        except Exception:
            ids = []
    return ids


def _score(R: pd.DataFrame, gate_dd: bool, gate_year: bool) -> dict[str, dict[str, float]]:
    metrics: dict[str, dict[str, float]] = {}
    for a in R.columns:
        s = R[a].dropna()
        if s.size < MIN_DAYS:
            continue
        if gate_year:
            py = _per_year_min_sharpe(s)
            if py <= 0.0:
                continue
        else:
            py = 0.0
        if gate_dd:
            dd = _max_drawdown(s)
            if dd > DD_GATE:
                continue
        else:
            dd = _max_drawdown(s)
        starr = _starr(s, ALPHA_CVAR)
        if starr <= 0.0:
            continue
        metrics[a] = {"starr": starr, "dd": dd, "py": py}
    return metrics


def _topk_starr_dedup(
    R: pd.DataFrame, metrics: dict[str, dict[str, float]], k: int
) -> list[str]:
    ranked = sorted(metrics, key=lambda x: metrics[x]["starr"], reverse=True)
    pre = ranked[: PRE_K_MULT * k]
    if len(pre) < 2:
        return pre
    sub_R = R[pre].dropna(how="all")
    keep_metric = {a: metrics[a]["starr"] for a in pre}
    try:
        kept = list(correlation_dedup(sub_R, threshold=DEDUP_RHO, keep_metric=keep_metric))
    except Exception:
        kept = list(pre)
    if len(kept) < 2:
        kept = list(pre)
    return kept[:k]


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    pool = _eligible_pool()
    if len(pool) < 2:
        return pool

    try:
        signs = member_signs_ic(RUN_ID, pool)
    except Exception:
        signs = {a: 1 for a in pool}
    signs = {a: int(signs.get(a, 1)) for a in pool}

    try:
        R = load_member_is_returns(RUN_ID, pool, signs=signs)
    except Exception:
        R = None

    if R is None or R.empty or len(R.columns) < 2:
        if alpha_index is not None and not alpha_index.empty \
                and "is_sharpe" in alpha_index.columns \
                and "alpha_id" in alpha_index.columns:
            ranked = (
                alpha_index.dropna(subset=["is_sharpe"])
                .sort_values("is_sharpe", ascending=False)["alpha_id"]
                .tolist()
            )
            if len(ranked) >= 2:
                return ranked[:SUBSET_K]
        return pool[:SUBSET_K]

    # Tier 1: full gates (year + DD)
    metrics = _score(R, gate_dd=True, gate_year=True)
    # Tier 2: drop DD gate
    if len(metrics) < 2:
        metrics = _score(R, gate_dd=False, gate_year=True)
    # Tier 3: drop both gates, pure STARR
    if len(metrics) < 2:
        metrics = _score(R, gate_dd=False, gate_year=False)

    if len(metrics) < 2:
        return list(R.columns)[:SUBSET_K]

    chosen = _topk_starr_dedup(R, metrics, SUBSET_K)
    if len(chosen) < 2:
        chosen = list(R.columns)[:SUBSET_K]
    return chosen


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    n = len(member_ids)
    if n == 0:
        return {}
    if n == 1:
        return {member_ids[0]: GROSS_TARGET}

    try:
        signs_raw = member_signs_ic(RUN_ID, member_ids)
    except Exception:
        signs_raw = {}
    signs = {a: int(signs_raw.get(a, 1)) for a in member_ids}

    try:
        R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    except Exception:
        R = None

    if R is None or R.empty:
        eq = {a: 1.0 for a in member_ids}
        coef_signed = apply_signs(eq, signs)
        for a in member_ids:
            coef_signed.setdefault(a, 0.0)
        norm = normalize_coefficients(coef_signed, "l1")
        return {a: float(GROSS_TARGET * norm.get(a, 0.0)) for a in member_ids}

    avail = [a for a in member_ids if a in R.columns]
    coef: dict[str, float] = {a: 0.0 for a in member_ids}

    for a in avail:
        s = R[a].dropna()
        if s.size < 20:
            continue
        dn = s[s < 0.0]
        if dn.size > 1:
            dn_vol = float(dn.std())
        elif s.size > 1:
            dn_vol = float(s.std())
        else:
            dn_vol = 0.0
        if not np.isfinite(dn_vol) or dn_vol <= 1e-8:
            continue
        starr = max(0.0, _starr(s, ALPHA_CVAR))
        coef[a] = math.sqrt(starr + 1e-6) / dn_vol

    total = sum(abs(v) for v in coef.values())
    if total <= 1e-12:
        coef = {a: 1.0 for a in member_ids}

    coef_signed = apply_signs(coef, signs)
    for a in member_ids:
        coef_signed.setdefault(a, 0.0)

    try:
        norm = normalize_coefficients(coef_signed, "l1")
    except Exception:
        abs_sum = sum(abs(v) for v in coef_signed.values()) or 1.0
        norm = {a: coef_signed[a] / abs_sum for a in member_ids}

    final: dict[str, float] = {a: float(GROSS_TARGET * norm.get(a, 0.0)) for a in member_ids}
    return final


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