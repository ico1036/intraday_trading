"""PC1-residualized alpha selection: regress out the dominant common factor of
the IS returns matrix, then concentrate on residual-Sharpe leaders weighted by
inverse residual volatility. Targets regime-robustness because IS->OS regime
shifts predominantly act through the top common factor (cf. APT, Ross 1976;
Residual Momentum, Blitz / Huij / Martens 2011, JFE)."""
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

COMPOSITE_ID = "auto_016_pc1_residualized_resid_sharpe_top8_invvo"
COMPOSITION_NOTE = "pc1_residualized_resid_sharpe_top8_invvol_gross070"
RUN_ID = "run_2026_05_c"
TARGET_GROSS = 0.70
N_TARGET = 8
N_BROAD = 40
DEDUP_RHO = 0.80


def _pool():
    ids = select_is_submittable(RUN_ID)
    if len(ids) < 30:
        ids = select_all_alphas(RUN_ID)
    signs = member_signs_ic(RUN_ID, ids)
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    R = R.dropna(axis=1, how="all").fillna(0.0)
    keep = [c for c in R.columns if float(np.abs(R[c].values).sum()) > 1e-9]
    R = R[keep]
    return R, signs


def _residualize_on_pc1(R: pd.DataFrame):
    X = R.values - R.values.mean(axis=0, keepdims=True)
    sd = X.std(axis=0) + 1e-12
    Xs = X / sd
    n_eff = max(len(Xs) - 1, 1)
    C = (Xs.T @ Xs) / n_eff
    _, eigvecs = np.linalg.eigh(C)
    pc1 = eigvecs[:, -1]
    f = Xs @ pc1
    fstd = float(f.std()) + 1e-12
    f = f / fstd
    beta = (X.T @ f) / n_eff
    resid = X - np.outer(f, beta)
    return (
        pd.DataFrame(resid, index=R.index, columns=R.columns),
        pd.Series(beta, index=R.columns),
    )


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    R, _signs = _pool()
    if R.shape[1] < 4:
        return list(R.columns)
    resid, beta = _residualize_on_pc1(R)
    mu = resid.mean()
    sd = resid.std().replace(0.0, np.nan)
    rsharpe = (mu / sd * np.sqrt(252)).fillna(0.0)
    score = (rsharpe - 0.5 * beta.abs()).where(mu > 0, other=-1e9)
    ranked = score.sort_values(ascending=False)
    top = ranked.head(min(N_BROAD, len(ranked))).index.tolist()
    if len(top) < 2:
        return ranked.head(max(2, min(N_TARGET, len(ranked)))).index.tolist()
    keep_metric = {a: float(ranked[a]) for a in top}
    deduped = correlation_dedup(resid[top], DEDUP_RHO, keep_metric=keep_metric)
    if not deduped:
        deduped = top[:N_TARGET]
    final = deduped[:N_TARGET]
    if len(final) < 2:
        final = ranked.head(min(N_TARGET, len(ranked))).index.tolist()
    return final


def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    R_all, signs = _pool()
    use = [m for m in member_ids if m in R_all.columns]
    if not use:
        n = max(len(member_ids), 1)
        return {m: TARGET_GROSS / n for m in member_ids}
    resid_full, _ = _residualize_on_pc1(R_all)
    resid = resid_full[use]
    sd = resid.std().replace(0.0, np.nan)
    inv_vol = (1.0 / sd).fillna(0.0)
    coef = {m: float(inv_vol[m]) for m in use}
    coef = apply_signs(coef, {m: int(signs.get(m, 1)) for m in coef})
    coef = normalize_coefficients(coef, "l1")
    coef = {k: float(v) * TARGET_GROSS for k, v in coef.items()}
    return {m: coef.get(m, 0.0) for m in member_ids}


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