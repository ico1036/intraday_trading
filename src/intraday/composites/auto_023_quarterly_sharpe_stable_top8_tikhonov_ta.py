"""Quarterly-Sharpe-stable concentrated top-8 with Tikhonov-regularized
tangency. Cites Tikhonov (1963) ill-conditioned regularization for the
small-N covariance inverse, plus a Bailey & Lopez de Prado (2014)
deflated-Sharpe-spirit per-quarter regime stability filter (finer than
per-year). High-return-tilt concentration (n=8), IC-aligned signs,
soft long-only in deployable space, mean row-L1 targeted to 0.70."""
from __future__ import annotations
import argparse, math
import numpy as np
import pandas as pd
import scipy.linalg as sla

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

COMPOSITE_ID = "auto_023_quarterly_sharpe_stable_top8_tikhonov_ta"
COMPOSITION_NOTE = "quarterly_sharpe_stable_top8_tikhonov_tangency_g070"

RUN_ID = "run_2026_05_c"
TARGET_N = 8
DEDUP_THRESHOLD = 0.85
GROSS_TARGET = 0.70
QUARTER_MIN_FRAC = 0.70


def _quarterly_pos_sharpe_frac(R: pd.DataFrame) -> pd.Series:
    """Fraction of quarters with positive Sharpe per alpha column."""
    Rd = R.copy()
    try:
        Rd.index = pd.to_datetime(Rd.index)
    except Exception:
        return pd.Series({c: 1.0 for c in Rd.columns})
    out = {}
    grouped = list(Rd.groupby(pd.Grouper(freq="Q")))
    for col in Rd.columns:
        ok = []
        for _, g in grouped:
            s = g[col].dropna()
            if len(s) < 5:
                continue
            sd = float(s.std(ddof=1))
            if not np.isfinite(sd) or sd <= 0:
                continue
            ok.append(1.0 if float(s.mean()) / sd > 0 else 0.0)
        out[col] = (sum(ok) / len(ok)) if ok else 0.0
    return pd.Series(out)


def _sharpe_lookup(alpha_index: pd.DataFrame, R: pd.DataFrame) -> dict[str, float]:
    lk: dict[str, float] = {}
    if isinstance(alpha_index, pd.DataFrame) and {"alpha_id", "is_sharpe"} <= set(alpha_index.columns):
        for _, row in alpha_index.iterrows():
            try:
                lk[str(row["alpha_id"])] = float(row["is_sharpe"])
            except Exception:
                continue
    for col in R.columns:
        if col in lk and np.isfinite(lk[col]):
            continue
        s = R[col].dropna()
        sd = float(s.std(ddof=1)) if len(s) > 1 else 0.0
        lk[col] = (float(s.mean()) / sd * math.sqrt(365.0)) if sd > 0 else 0.0
    return lk


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if len(ids) < 5:
        ids = select_all_alphas(RUN_ID)
    if len(ids) < 3:
        return ids
    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.empty or R.shape[1] < 3:
        return list(R.columns)[:TARGET_N] if R is not None else ids[:TARGET_N]

    sharpe = _sharpe_lookup(alpha_index, R)
    qfrac = _quarterly_pos_sharpe_frac(R)

    stable = [c for c in R.columns if qfrac.get(c, 0.0) >= QUARTER_MIN_FRAC]
    if len(stable) < max(TARGET_N * 2, 20):
        # Relax to top-quartile of quarterly stability, ensuring pool size
        ranked_q = qfrac.sort_values(ascending=False)
        stable = ranked_q.head(max(TARGET_N * 4, 30)).index.tolist()

    R_stable = R[[c for c in stable if c in R.columns]]
    if R_stable.shape[1] < 3:
        ranked = sorted(R.columns, key=lambda a: sharpe.get(a, 0.0), reverse=True)
        return ranked[:TARGET_N]

    try:
        kept = correlation_dedup(R_stable, threshold=DEDUP_THRESHOLD, keep_metric=sharpe)
    except Exception:
        kept = list(R_stable.columns)

    kept_sorted = sorted(kept, key=lambda a: sharpe.get(a, 0.0), reverse=True)
    final = kept_sorted[:TARGET_N]
    if len(final) < 3:
        ranked = sorted(R.columns, key=lambda a: sharpe.get(a, 0.0), reverse=True)
        final = ranked[:TARGET_N]
    return final


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    signs = member_signs_ic(RUN_ID, member_ids)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)
    cols = [c for c in member_ids if c in (R.columns if R is not None else [])]

    def _finalize(coef_dict: dict[str, float]) -> dict[str, float]:
        # Drop non-finite / zero-only safety
        coef_dict = {a: float(v) for a, v in coef_dict.items() if np.isfinite(v)}
        if not coef_dict or sum(abs(v) for v in coef_dict.values()) <= 1e-12:
            coef_dict = {a: 1.0 for a in member_ids}
        coef_dict = normalize_coefficients(coef_dict, "l1")
        coef_dict = {a: v * GROSS_TARGET for a, v in coef_dict.items()}
        coef_dict = apply_signs(coef_dict, signs)
        for a in member_ids:
            coef_dict.setdefault(a, 0.0)
        return coef_dict

    if len(cols) < 2:
        return _finalize({a: 1.0 / max(len(member_ids), 1) for a in member_ids})

    Rc = R[cols].dropna(how="any")
    if Rc.shape[0] < 20:
        # Not enough history for cov estimation — inv-vol fallback in signed space
        vol = R[cols].std(ddof=1)
        invv = {c: (1.0 / float(vol[c])) if (np.isfinite(vol[c]) and vol[c] > 0) else 1.0 for c in cols}
        return _finalize(invv)

    mu = Rc.mean().values.astype(float)
    Sigma = np.cov(Rc.values, rowvar=False, ddof=1)
    n = Sigma.shape[0]

    # Tikhonov regularization: lambda = 0.5 * mean(diag(Sigma))
    diag_mean = float(np.trace(Sigma)) / max(n, 1)
    lam = 0.5 * diag_mean if diag_mean > 0 else 1e-6
    reg = Sigma + lam * np.eye(n)

    try:
        w_raw = sla.solve(reg, mu, assume_a="pos")
    except Exception:
        try:
            w_raw = sla.pinvh(reg) @ mu
        except Exception:
            w_raw = mu  # last resort: weight by mean return

    if not np.all(np.isfinite(w_raw)):
        w_raw = np.where(np.isfinite(w_raw), w_raw, 0.0)

    # Soft long-only in deployable-sign space (signs already applied to R,
    # so positive w_raw means deployable-positive). Clip negatives.
    w_pos = np.clip(w_raw, 0.0, None)
    if float(w_pos.sum()) <= 1e-9:
        # All-negative: fall back to inverse-variance on positive-mu subset
        diag = np.diag(Sigma)
        good = (mu > 0) & (diag > 0)
        if good.any():
            w_pos = np.where(good, 1.0 / np.where(diag > 0, diag, 1.0), 0.0)
        else:
            w_pos = np.where(np.diag(Sigma) > 0, 1.0 / np.diag(Sigma), 1.0)

    coef = dict(zip(cols, w_pos.tolist()))
    return _finalize(coef)


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