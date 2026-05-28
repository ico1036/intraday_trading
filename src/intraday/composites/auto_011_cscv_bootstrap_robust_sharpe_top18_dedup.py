"""CSCV-style bootstrap-robust IS Sharpe selection (Bailey/Borwein/Lopez de Prado/Zhu 2014)
with correlation dedup and Sharpe^1.5-tilted concentrated weighting."""
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
    load_member_is_returns,
    normalize_coefficients,
)

COMPOSITE_ID = "auto_011_cscv_bootstrap_robust_sharpe_top18_dedup"
COMPOSITION_NOTE = "cscv_bootstrap_robust_sharpe_top18_dedup085_tilt15_gross60"

RUN_ID = "run_2026_05_c"

N_BOOTSTRAP = 32
SUBSAMPLE_FRAC = 0.5
ROBUST_QUANTILE = 0.25          # 25th-percentile Sharpe across bootstraps
PRE_DEDUP_TOP_K = 60
DEDUP_THRESHOLD = 0.85
FINAL_TOP_K = 18                # concentrated, per user's high-return ask
TILT_EXP = 1.5
TARGET_GROSS = 0.60             # aim mean row-L1 inside healthy [0.30, 0.90] band
RNG_SEED = 20260526
ANN = float(np.sqrt(252.0))


def _robust_sharpe_per_alpha(
    R: pd.DataFrame,
    n_boot: int,
    frac: float,
    q: float,
    seed: int,
) -> dict[str, float]:
    """Bootstrap subsamples of IS dates → q-quantile Sharpe per alpha (CSCV-flavor)."""
    T, N = R.shape
    cols = list(R.columns)
    if T < 10 or N == 0:
        mu = R.mean(axis=0).to_numpy()
        sd = R.std(axis=0, ddof=1).replace(0.0, np.nan).to_numpy()
        with np.errstate(divide="ignore", invalid="ignore"):
            s = np.where(np.isfinite(sd) & (sd > 0), mu / sd * ANN, 0.0)
        return dict(zip(cols, s.tolist()))

    rng = np.random.default_rng(seed)
    sub_size = max(5, int(round(T * frac)))
    arr = R.to_numpy(dtype=float, copy=False)
    sharpes = np.zeros((n_boot, N), dtype=float)
    for b in range(n_boot):
        idx = rng.choice(T, size=sub_size, replace=False)
        sub = arr[idx, :]
        mu = np.nanmean(sub, axis=0)
        sd = np.nanstd(sub, axis=0, ddof=1)
        with np.errstate(divide="ignore", invalid="ignore"):
            s = np.where((sd > 0) & np.isfinite(sd) & np.isfinite(mu), mu / sd * ANN, 0.0)
        sharpes[b, :] = s
    robust = np.quantile(sharpes, q, axis=0)
    robust = np.where(np.isfinite(robust), robust, 0.0)
    return dict(zip(cols, robust.tolist()))


def _build_returns(alpha_index: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int]]:
    ids = select_is_submittable(RUN_ID)
    if not ids or len(ids) < 2:
        # Defensive fallback — pull whatever the alpha_index gives us.
        ids = [str(a) for a in alpha_index["alpha_id"].tolist()] if "alpha_id" in alpha_index.columns else []
    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    return R, signs


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    R, _signs = _build_returns(alpha_index)
    if R.shape[1] < 2:
        return list(R.columns)

    robust = _robust_sharpe_per_alpha(R, N_BOOTSTRAP, SUBSAMPLE_FRAC, ROBUST_QUANTILE, RNG_SEED)

    ranked = sorted(robust.items(), key=lambda kv: kv[1], reverse=True)
    pre = [aid for aid, _ in ranked[:PRE_DEDUP_TOP_K] if aid in R.columns]
    if len(pre) < 2:
        return [aid for aid, _ in ranked[:max(2, FINAL_TOP_K)] if aid in R.columns][:FINAL_TOP_K]

    keep_metric = {aid: robust[aid] for aid in pre}
    R_pre = R[pre]
    try:
        kept = correlation_dedup(R_pre, threshold=DEDUP_THRESHOLD, keep_metric=keep_metric)
    except Exception:
        kept = pre  # fall back to pre-dedup ranking if helper hiccups

    kept = [aid for aid in kept if aid in R.columns]
    if len(kept) < 2:
        return [aid for aid, _ in ranked[:max(2, FINAL_TOP_K)] if aid in R.columns][:FINAL_TOP_K]

    kept_sorted = sorted(kept, key=lambda a: robust.get(a, 0.0), reverse=True)
    final = kept_sorted[:FINAL_TOP_K]
    if len(final) < 2:
        final = [aid for aid, _ in ranked[:max(2, FINAL_TOP_K)] if aid in R.columns][:FINAL_TOP_K]
    return final


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    R, signs = _build_returns(alpha_index)
    robust = _robust_sharpe_per_alpha(R, N_BOOTSTRAP, SUBSAMPLE_FRAC, ROBUST_QUANTILE, RNG_SEED)

    vals = np.array([float(robust.get(mid, 0.0)) for mid in member_ids], dtype=float)
    # Shift so the smallest member still gets a small positive base (no negative tilt artifacts).
    shift = max(0.0, -float(vals.min()) + 1e-3) if vals.size else 0.0
    raw = np.power(np.maximum(vals + shift, 1e-9), TILT_EXP)
    if not np.isfinite(raw).any() or raw.sum() <= 0.0:
        raw = np.ones_like(raw) if raw.size else np.array([1.0])
    base = raw / raw.sum()

    coef_dict: dict[str, float] = {mid: float(w) for mid, w in zip(member_ids, base.tolist())}

    # Normalize to Σ|c|=1, then scale to the desired aggregate gross exposure.
    coef_dict = normalize_coefficients(coef_dict, scheme="l1")
    coef_dict = {k: float(v) * TARGET_GROSS for k, v in coef_dict.items()}

    # Apply IC-derived signs so the runner combines deployable directions.
    coef_dict = apply_signs(coef_dict, signs)

    # Guarantee every requested member id is present (fill any missing with 0).
    for mid in member_ids:
        coef_dict.setdefault(mid, 0.0)

    return coef_dict


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