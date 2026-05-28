I'm operating under the operator-level "composite generator" prompt which directs me to output exactly one fenced ```python COMPOSITE_FILE``` block with rationale allowed before it — so I will produce that output rather than run the plan-mode workflow.

**Rationale.** The tried list already covers Neumann tangency, NCO+RMT, HERC, Black-Litterman, DRP eigenbasis, and Max-Diversification. Fresh territory: **Mean-CVaR LP (Rockafellar & Uryasev 2000, *Journal of Risk* 2(3))**, which directly trades off conditional tail loss against mean return — a natural fit for the user's "high-return / high-risk" mandate because it doesn't penalize symmetric variance (so high-Sharpe-but-volatile members aren't shrunk away), only left-tail loss.

**Mechanism.**
1. Pool = `select_is_submittable("run_2026_05_c")`; flip each member to its deployable sign via `member_signs_ic` so the LP can stay long-only.
2. Pre-rank by ex-post-sign IS Sharpe; take top-80; correlation-dedup at |ρ|>0.85 (`correlation_dedup`); cap at top-30 by Sharpe. This avoids the 100+-member dilution trap that produced anemic gross exposure in iter 1/4.
3. Solve Rockafellar-Uryasev LP via `scipy.optimize.linprog(method="highs")` over variables `(w∈ℝ_+^N, α∈ℝ, z∈ℝ_+^T)`:
   - min  α + (1/(η·T)) Σ z_t
   - s.t. z_t ≥ −r_t·w − α,  μ·w ≥ median(μ),  Σw=1
   with η=0.10 → minimize CVaR_{90%}.
4. Map positive LP weights back through `apply_signs` and `normalize_coefficients(scheme="l1")`; scale by `GROSS_TARGET=0.65` so the mean row-L1 of the composite lands in [0.30, 0.90].

**Bug guards from iter 1/4 rejections.** `normalize_coefficients` is fed a *dict* (keyword `scheme="l1"`), every input `member_id` gets a key in the returned dict (zero for any dropped by `load_member_is_returns`), and the LP path is wrapped in `try/except` with a Sharpe-tilt fallback.

```python COMPOSITE_FILE
"""Mean-CVaR linear program (Rockafellar & Uryasev 2000, J. Risk 2(3)):
minimize CVaR_{1-eta} subject to a mean-return floor, on sign-aligned and
correlation-deduplicated top-Sharpe SUBMITTABLE members from run_2026_05_c.
Tail-asymmetric risk control keeps high-Sharpe / high-vol alphas alive while
suppressing left-tail exposure -- a fresh objective vs. variance-based attempts."""
from __future__ import annotations
import argparse
import numpy as np
import pandas as pd
import scipy.optimize as sopt

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    correlation_dedup,
    member_signs_ic,
    apply_signs,
    select_is_submittable,
    select_all_alphas,
    load_member_is_returns,
    normalize_coefficients,
    member_is_sharpe,
)

COMPOSITE_ID = "auto_007"
COMPOSITION_NOTE = "mean_cvar_rockafellar_uryasev_eta010_dedup085_top30"

RUN_ID = "run_2026_05_c"
ETA = 0.10            # CVaR tail probability (worst 10%)
DEDUP_THR = 0.85
PRE_TOP = 80
TOP_N = 30
GROSS_TARGET = 0.65   # final L1 sum of coefficients -> mean row-L1 of composite


# --------------------------------------------------------------------------- #
# Pool construction
# --------------------------------------------------------------------------- #
def _pool_ids() -> list[str]:
    ids = select_is_submittable(RUN_ID)
    if not ids:
        ids = select_all_alphas(RUN_ID) or []
    return list(ids)


def _shrink_pool(ids: list[str], signs: dict[str, int]) -> pd.DataFrame:
    R = load_member_is_returns(RUN_ID, ids, signs=signs)
    if R is None or R.shape[1] < 2:
        return R if R is not None else pd.DataFrame()

    sd = R.std(ddof=0).replace(0.0, np.nan)
    sh = (R.mean() / sd).fillna(-1e9)

    # Pre-shrink to top-PRE_TOP by sign-aligned IS Sharpe before dedup
    pre_keep = sh.sort_values(ascending=False).head(min(PRE_TOP, len(sh))).index.tolist()
    R = R[pre_keep]
    metric = {a: float(sh[a]) for a in pre_keep}

    kept = correlation_dedup(R, DEDUP_THR, keep_metric=metric)
    if not kept or len(kept) < 2:
        kept = pre_keep[: min(TOP_N, len(pre_keep))]
    R = R[kept]

    if R.shape[1] > TOP_N:
        sh2 = (R.mean() / R.std(ddof=0).replace(0.0, np.nan)).fillna(-1e9)
        final = sh2.sort_values(ascending=False).head(TOP_N).index.tolist()
        R = R[final]
    return R


def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ids = _pool_ids()
    if len(ids) < 2:
        return ids
    signs = member_signs_ic(RUN_ID, ids, dead_band=0.005)
    R = _shrink_pool(ids, signs)
    if R is None or R.shape[1] < 2:
        # Last-ditch fallback: top-10 by IS Sharpe lookup
        sh = member_is_sharpe(RUN_ID, ids) or {}
        ranked = sorted(sh.items(), key=lambda kv: -float(kv[1]))[:10]
        return [k for k, _ in ranked] or ids[:10]
    return list(R.columns)


# --------------------------------------------------------------------------- #
# Mean-CVaR linear program  (Rockafellar & Uryasev 2000)
# --------------------------------------------------------------------------- #
def _mean_cvar_lp(R_np: np.ndarray) -> np.ndarray:
    T, N = R_np.shape
    mu = R_np.mean(axis=0)

    # Mean-return floor: median of member means (keeps top half of carriers)
    mu_target = float(np.quantile(mu, 0.50))
    inv_eta_T = 1.0 / (ETA * T)

    # Decision vars: [ w (N) | alpha (1) | z (T) ]
    n_vars = N + 1 + T

    c = np.zeros(n_vars, dtype=float)
    c[N] = 1.0
    c[N + 1:] = inv_eta_T

    # z_t >= -r_t . w - alpha          -->   -R w - alpha - z <= 0
    A_cvar = np.zeros((T, n_vars), dtype=float)
    A_cvar[:, :N] = -R_np
    A_cvar[:, N] = -1.0
    A_cvar[np.arange(T), N + 1 + np.arange(T)] = -1.0
    b_cvar = np.zeros(T, dtype=float)

    # mu . w >= mu_target              -->   -mu w <= -mu_target
    A_mu = np.zeros((1, n_vars), dtype=float)
    A_mu[0, :N] = -mu
    b_mu = np.array([-mu_target], dtype=float)

    A_ub = np.vstack([A_cvar, A_mu])
    b_ub = np.concatenate([b_cvar, b_mu])

    # sum(w) = 1
    A_eq = np.zeros((1, n_vars), dtype=float)
    A_eq[0, :N] = 1.0
    b_eq = np.array([1.0], dtype=float)

    bounds = [(0.0, 1.0)] * N + [(None, None)] + [(0.0, None)] * T

    res = sopt.linprog(
        c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
        bounds=bounds, method="highs",
    )
    if not res.success or res.x is None:
        raise RuntimeError(f"linprog failed: {res.message}")

    w = np.clip(np.asarray(res.x[:N], dtype=float), 0.0, None)
    s = float(w.sum())
    if not np.isfinite(s) or s <= 1e-12:
        raise RuntimeError("degenerate LP solution")
    return w / s


def _sharpe_tilt_fallback(R_np: np.ndarray) -> np.ndarray:
    mu = R_np.mean(axis=0)
    sd = R_np.std(axis=0, ddof=0)
    sd = np.where(sd <= 1e-12, 1.0, sd)
    sh = np.clip(mu / sd, 0.0, None)
    s = sh.sum()
    if s <= 1e-12:
        return np.ones(R_np.shape[1]) / R_np.shape[1]
    return sh / s


# --------------------------------------------------------------------------- #
# Weight emission
# --------------------------------------------------------------------------- #
def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    out = {m: 0.0 for m in member_ids}
    if not member_ids:
        return out

    signs = member_signs_ic(RUN_ID, member_ids, dead_band=0.005)
    R = load_member_is_returns(RUN_ID, member_ids, signs=signs)

    if R is None or R.shape[1] < 2:
        # Sign-only equal-weight fallback
        coef = {m: float(signs.get(m, 1)) for m in member_ids}
        coef = normalize_coefficients(coef, scheme="l1")
        for k, v in coef.items():
            out[k] = float(v) * GROSS_TARGET
        return out

    ids_used = list(R.columns)
    R_np = R.to_numpy(dtype=float, copy=False)

    # Drop NaN rows if we can, else zero-fill
    finite = np.isfinite(R_np).all(axis=1)
    if int(finite.sum()) >= max(20, R_np.shape[1] + 2):
        R_np = R_np[finite]
    else:
        R_np = np.nan_to_num(R_np, nan=0.0, posinf=0.0, neginf=0.0)

    try:
        w = _mean_cvar_lp(R_np)
    except Exception:
        w = _sharpe_tilt_fallback(R_np)

    pos_coef = {a: float(v) for a, v in zip(ids_used, w.tolist())}
    used_signs = {m: int(signs.get(m, 1)) for m in ids_used}
    signed = apply_signs(pos_coef, used_signs)
    norm = normalize_coefficients(signed, scheme="l1")

    for k, v in norm.items():
        out[k] = float(v) * GROSS_TARGET
    return out


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
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
