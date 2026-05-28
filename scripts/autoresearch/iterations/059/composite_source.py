"""Greedy Gram-Schmidt residual-Sharpe composition (cov-free).

Cites: classical Gram-Schmidt + stepwise forward selection by residual
Sharpe — the QR-based "orthogonal information" formulation analogous to
factor selection in Cochrane (2005, Asset Pricing, ch. 13). Sequentially
projects already-picked alphas out of the IS returns matrix and admits
the next candidate whose orthogonal residual carries the highest annual
Sharpe. Bypasses Σ inversion entirely, so the 1/σ under-leverage trap
of tangency/min-var solvers does not apply. Selection layered on
per-year IS Sharpe stability + IS max-drawdown < 25% (regime-robust
filter from the leaderboard pattern). Final coefficients are L1-
normalized then multiplied by 10× so the runner's row-L1 clamp
saturates and mean gross exposure sits in the productive band.
"""
from __future__ import annotations

import argparse
import math
import numpy as np
import pandas as pd

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    select_is_submittable,
    select_all_alphas,
    member_signs_ic,
    apply_signs,
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_059_gramschmidt_resid_sharpe_yearstable_dd25"
COMPOSITION_NOTE = "gramschmidt_resid_sharpe_yearstable_dd25_top7_gross10x"

RUN_ID = "run_2026_05_c"
MAX_N = 7
MIN_RESID_SHARPE = 0.30
DD_THRESHOLD = 0.25
POST_SCALE = 10.0

_CACHE: dict | None = None


def _ann_sharpe(r: np.ndarray) -> float:
    r = np.asarray(r, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 5:
        return 0.0
    s = r.std()
    if not np.isfinite(s) or s <= 1e-12:
        return 0.0
    return float(r.mean() / s * math.sqrt(252.0))


def _max_drawdown(r: pd.Series) -> float:
    x = r.fillna(0.0)
    eq = (1.0 + x).cumprod()
    peak = eq.cummax()
    dd = (eq / peak - 1.0).min()
    return float(-dd) if np.isfinite(dd) else 1.0


def _year_stable(r: pd.Series) -> bool:
    idx = r.index
    if not isinstance(idx, pd.DatetimeIndex):
        try:
            idx = pd.to_datetime(idx)
            r = pd.Series(r.values, index=idx)
        except Exception:
            return True
    years = sorted({d.year for d in r.index})
    if len(years) < 2:
        return True
    for y in years:
        sub = r[r.index.year == y].values
        if sub.size < 10:
            continue
        if _ann_sharpe(sub) < 0.0:
            return False
    return True


def _filter_pool(R: pd.DataFrame) -> list[str]:
    keep = []
    for aid in R.columns:
        s = R[aid].dropna()
        if s.size < 30:
            continue
        if _ann_sharpe(s.values) <= 0.0:
            continue
        if _max_drawdown(s) >= DD_THRESHOLD:
            continue
        if not _year_stable(s):
            continue
        keep.append(aid)
    return keep


def _greedy_gram_schmidt(R: pd.DataFrame) -> tuple[list[str], dict[str, float]]:
    cols = list(R.columns)
    if not cols:
        return [], {}
    sharpes = {c: _ann_sharpe(R[c].dropna().values) for c in cols}
    anchor = max(cols, key=lambda c: sharpes[c])
    picked = [anchor]
    scores = {anchor: max(sharpes[anchor], 0.10)}

    M = R.fillna(0.0).values.astype(float)
    name_to_idx = {c: i for i, c in enumerate(cols)}
    residuals = M.copy()

    v = residuals[:, name_to_idx[anchor]]
    nv = float(np.linalg.norm(v))
    if nv > 1e-12:
        u = v / nv
        residuals = residuals - np.outer(u, u @ residuals)

    remaining = [c for c in cols if c != anchor]
    while remaining and len(picked) < MAX_N:
        best_id, best_sh, best_vec = None, -np.inf, None
        for c in remaining:
            vec = residuals[:, name_to_idx[c]]
            sh = _ann_sharpe(vec)
            if sh > best_sh:
                best_sh = sh
                best_id = c
                best_vec = vec
        if best_id is None or best_sh < MIN_RESID_SHARPE:
            break
        picked.append(best_id)
        scores[best_id] = float(best_sh)
        nv = float(np.linalg.norm(best_vec))
        if nv > 1e-12:
            u = best_vec / nv
            residuals = residuals - np.outer(u, u @ residuals)
        remaining.remove(best_id)
    return picked, scores


def _build(run_id: str):
    global _CACHE
    if _CACHE is not None and _CACHE.get("run_id") == run_id:
        return _CACHE["picked"], _CACHE["scores"], _CACHE["signs"]

    ids = select_is_submittable(run_id)
    if not ids or len(ids) < 5:
        ids = select_all_alphas(run_id)
    signs = member_signs_ic(run_id, ids)
    R = load_member_is_returns(run_id, ids, signs=signs)
    R = R.dropna(axis=1, how="all")

    keep = _filter_pool(R)
    if len(keep) < 3:
        ranked = sorted(
            R.columns,
            key=lambda c: _ann_sharpe(R[c].dropna().values),
            reverse=True,
        )
        keep = ranked[:25]

    picked, scores = _greedy_gram_schmidt(R[keep])

    if len(picked) < 2:
        ranked = sorted(
            R.columns,
            key=lambda c: _ann_sharpe(R[c].dropna().values),
            reverse=True,
        )
        picked = ranked[:5]
        scores = {c: max(_ann_sharpe(R[c].dropna().values), 0.10) for c in picked}

    _CACHE = {
        "run_id": run_id,
        "picked": picked,
        "scores": scores,
        "signs": signs,
    }
    return picked, scores, signs


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    picked, _, _ = _build(RUN_ID)
    return list(picked)


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    picked, scores, signs = _build(RUN_ID)
    chosen = [m for m in member_ids if m in scores]
    if len(chosen) < 2:
        chosen = list(picked)
    raw = {m: max(scores.get(m, 0.10), 0.05) for m in chosen}
    raw = apply_signs(raw, signs)
    coef = normalize_coefficients(raw, "l1")
    return {m: float(coef[m]) * POST_SCALE for m in coef}


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