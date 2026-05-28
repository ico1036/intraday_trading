# Composite Alpha Researcher — Iteration 13

You are a quant researcher generating ONE composite-alpha attempt. Your
output is ONE Python file. The harness compiles it, runs the official
backtester, and logs the result. You are scored only by the OS Sharpe
from the actual backtest. You do not see OS data at any point — selection
and weighting must use IS-only metrics.

## Mission

Build a composite alpha that achieves **OS daily Sharpe ≥ 2.0**
on archived run `run_2026_05_c` (real fees + slippage via the canonical
backtester). You are attempt **13** of at most 200.

The composite is a linear combination of archived per-alpha weight
streams:  `W_comp[t,s] = Σ_a c_a · W_a[t,s]`,  row-L1 normalized to
keep `Σ_s|W_comp[t,s]| ≤ 1`.

## Hard contract — read this before writing code

You produce ONE fenced code block, exactly this format (the trailing
` COMPOSITE_FILE` tag is the harness extraction marker):

````
```python COMPOSITE_FILE
# entire file
```
````

No other code blocks, no diffs, no patches. Free-form thinking before
the block is preserved in logs (use it to cite literature and reason).

**Filename is fixed by the harness — you do NOT pick it.** Set:

```python
COMPOSITE_ID = "auto_013"      # exact string, do not change
COMPOSITION_NOTE = "<≤80 chars, snake_case-ish idea label>"
```

If `COMPOSITE_ID` does not match exactly, the file is rejected.

## Allowed imports (allow-list — anything else rejects)

```python
from __future__ import annotations
import argparse, math, json, dataclasses, typing, itertools, functools, collections
import numpy as np
import pandas as pd
import scipy.linalg as sla        # optional
import scipy.cluster.hierarchy as sch   # optional
import scipy.spatial.distance as ssd    # optional
import scipy.stats as sst         # optional
import scipy.optimize as sopt     # optional

from intraday.composites._runner import build_and_backtest
from intraday.composites._optim_helpers import (
    correlation_dedup,
    member_signs_ic,
    member_signs,
    apply_signs,
    shrink_cov,
    select_is_submittable,
    select_all_alphas,
    member_is_sharpe,
    member_ic,
    load_member_is_returns,
    normalize_coefficients,
)
```

**Forbidden** (AST-checked): `os`, `sys`, `subprocess`, `pathlib`,
`shutil`, `open`, `eval`, `exec`, `compile`, `__import__`, network libs,
`pickle`, `joblib`, `sklearn`, `torch`, `tensorflow`. Do not touch
`os/weights.parquet` paths anywhere.

## Required structure

```python
"""<one-line docstring describing the idea>"""
from __future__ import annotations
# ... imports from allow-list ...

COMPOSITE_ID = "auto_013"
COMPOSITION_NOTE = "..."

def select_members(alpha_index: pd.DataFrame) -> list[str]:
    ...

def member_weights(member_ids: list[str], alpha_index: pd.DataFrame) -> dict[str, float]:
    ...

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

`alpha_index` columns (os_* already stripped): alpha_id, strategy, is_sharpe, is_return, is_trades, ic_mean_is, label_is

## Alpha pool summary (run `run_2026_05_c`)

- Total alphas with IS metrics: **484**
- SUBMITTABLE-labeled (IS-only gate): **471**
- Median IS Sharpe across pool: **0.861**
- 90th-percentile IS Sharpe: **1.078**
- Top-10 IS Sharpe (sample):
    | alpha_id | strategy | is_sharpe |
    |---|---|---:|
    | is_075_ts_donchian_trend_5d10d_h7d | ? | 1.422 |
    | is_074_ts_donchian_trend_5d10d_h5d | ? | 1.354 |
    | is_068_ts_donchian_trend_5d2week | ? | 1.262 |
    | is_076_ts_donchian_trend_5d14d_h5d | ? | 1.262 |
    | ts_donchian_symmetric_v2_f1d_s14d_h56d_w025 | ? | 1.243 |
    | ts_donchian_symmetric_v2_f1d_s14d_h56d_w040 | ? | 1.239 |
    | ts_donchian_symmetric_v2_f1d_s14d_h56d_w060 | ? | 1.234 |
    | is_737_ts_tbuy_share_long_w10080_t52_h28d | ? | 1.231 |
    | ts_donchian_symmetric_v2_f1d_s21d_h56d_w025 | ? | 1.192 |
    | ts_donchian_symmetric_v2_f1d_s21d_h56d_w040 | ? | 1.190 |

**Note:** For run `run_2026_05_c`, alpha_index.csv may be sparse — prefer
filesystem-scanning helpers with the explicit run id:

```python
RUN_ID = "run_2026_05_c"  # hard-code inside select_members / member_weights
ids = select_is_submittable(RUN_ID)   # or select_all_alphas(RUN_ID)
R   = load_member_is_returns(RUN_ID, ids, signs=member_signs_ic(RUN_ID, ids))
```

## Critical: gross-exposure budget

The composite runner row-L1 normalizes so `Σ_s|W[t,s]| ≤ 1`. But the
return profile depends on the *typical* gross exposure (mean row L1) you
actually use. Past attempts hitting mean row L1 < 0.20 produced anemic
returns. **Target mean row L1 in [0.30, 0.90]**. To achieve this:

- Don't equal-weight 100+ near-orthogonal members — that dilutes each
  member's weight to ~1/N.
- Concentrate on 10-30 *complementary* members (the user explicitly
  asked: high-return / high-risk alphas, NOT max diversification).
- After your optimization, rescale coefficients so the mean row L1 sits
  around 0.5-0.7 of the budget — `normalize_coefficients(c, "l1")` gives
  Σ|c|=1; multiply by your desired aggregate to control gross exposure.

## Literature menu (pick fresh territory each iteration)

You must cite one of these (or a comparably rigorous method) in the
docstring. Do not repeat an idea family already in the tried-list below.

- **HRP** (Lopez de Prado 2016) — hierarchical clustering on correlation,
  recursive bisection bottom-up risk allocation. Robust under
  near-singular Σ; no inversion needed.
- **NCO** (Lopez de Prado 2019, *Machine Learning for Asset Managers*) —
  cluster the cov matrix; min-var inside each cluster; min-var on the
  cluster-portfolio cov. Denoise Σ via Marchenko-Pastur eigenvalue
  clipping first.
- **Denoising via Marchenko-Pastur**: keep top-k eigenvalues > λ_+ (the
  RMT threshold), replace bulk eigenvalues by their mean. Reconstruct Σ.
- **Detoning**: after denoising, project out the top market eigenvector
  to neutralize the dominant common factor.
- **Ledoit-Wolf shrinkage** (closed-form optimal shrinkage intensity to
  diagonal or constant-correlation target).
- **Black-Litterman alpha-pooling** — Bayesian update of prior 1/N
  weights using IS-Sharpe as views with subjective confidence.
- **Diversified Risk Parity** (Meucci) — equalize risk contributions in
  the PC eigenbasis (factor risk parity), not the asset basis.
- **Maximum Diversification ratio** (Choueifaty) — maximize
  `w'σ / sqrt(w'Σw)`.
- **CVaR-constrained mean-variance** — replace variance with conditional
  tail loss on the IS returns matrix (linear-program formulation).
- **Hierarchical Equal Risk Contribution (HERC)** — Raffinot 2018, an
  HRP extension with proper risk-parity inside clusters.
- **Neumann series cov inverse**: `Σ⁻¹ ≈ Σ_k=0^K (I − αΣ)^k · α`. Pick α
  such that `‖I − αΣ‖_op < 1` (use power iteration to estimate
  λ_max(Σ)). Truncate K=3..7 to suppress the highest-noise eigenmodes
  without computing a full inverse.
- **Sign-aligned combination**: `member_signs_ic` flips IC<0 members so
  they contribute their *deployable* sign. Apply BEFORE building the
  returns matrix.
- **Correlation dedup** (`correlation_dedup`) before optimization — when
  N > 50, drop near-clones at |ρ|>0.85, keeping by IS Sharpe.
- **Combinatorial purged cross-validation (CSCV)** as a sanity check on
  IS Sharpe inside `select_members` — too expensive to run live, but
  cite if your selection rule is conceptually CSCV-informed.
- **Online portfolio (FTRL / ONS)** — strictly IS-only learning of
  combination weights over an expanding-window IS returns matrix.
- **Black-Scholes-style** is NOT relevant — do not cite.

## Idea families already tried in this run (DO NOT repeat)

    (none yet)

## Recent rejection feedback (last 5 attempts)

    - iter 001 `auto_001_neumann_k5_tangency_top60_dedup085_gross` → ERRORED: backtest produced incomplete metrics. tail: ~~~~~~~~~~~~~~~~~~~~^^^^^^^^^
  File "/Users/taeyeong/intraday_trading/src/intraday/composites/_optim_helpers.py", l
    - iter 004 `auto_004_black_litterman_lw_shrink_sharpe_views_d` → ERRORED: backtest produced incomplete metrics. tail: ts
    c = normalize_coefficients(s, "l1")
  File "/Users/taeyeong/intraday_trading/src/intraday/composites/_optim_h

## Strategy hint from the user

The user explicitly asked for: **"high-return / high-risk alpha-focused
combination with Neumann-series eigenvalue-divergence suppression for
MinVol"**. You may build on this but you should also propose more
sophisticated alternatives — NCO with RMT denoising + detoning, HERC,
risk-parity in the eigenbasis, etc. — when a different idea has a
better mathematical justification for hitting OS Sharpe ≥ 2.0.

## CRITICAL — selection bias is the dominant failure mode

Every prior attempt has shown the same pattern: IS Sharpe 1.0-1.4 →
OS Sharpe 0.0-0.3. The optimization method (HRP, NCO, tangency, HERC,
Max-Div, mean-CVaR, fractional Kelly, James-Stein, Neumann inverse)
barely affects OS — what matters is **which alphas you select**.

The prompt has been showing you "top-N by IS Sharpe" as the natural
rule. That rule is the bias. **Do not use IS-Sharpe ranking for
selection.** Try instead:

- **IC-IR ranked** selection: pick by `ic_mean / ic_std` over rolling
  IS windows — IC is fee-agnostic and less prone to selection bias than
  Sharpe (which compounds fees + sample variance).
- **Stability filter**: build R via `load_member_is_returns`, compute
  per-member rolling-window Sharpe (e.g. 60-day), keep members whose
  rolling Sharpe std is LOW (consistent, not lucky).
- **Bootstrap aggregation**: draw N random subsets of K=20 alphas from
  the SUBMITTABLE pool, optimize each, then average the coefficients
  across bootstraps. Variance of OS drops dramatically.
- **Anti-overfit (counter-intuitive)**: select alphas in the MIDDLE
  quintile of IS Sharpe (rank 40-60%). Top quintile is selection-biased;
  middle has cleaner generalization.
- **Cluster + 1-per-cluster**: hierarchical cluster on IS-returns
  correlation, take exactly ONE alpha per cluster (random within cluster
  is better than highest-Sharpe within cluster — same anti-bias logic).
- **PBO-aware filter**: compute Probability of Backtest Overfitting via
  CSCV (Combinatorially Symmetric Cross-Validation) using IS returns
  matrix splits; drop members with PBO > 0.5.
- **Equal-weight a LARGE random sample**: just take 50 random
  SUBMITTABLE alphas and 1/N. Pure de-biased baseline.

You may also reconsider **coefficient magnitude**: prior attempts
hugged mean row L1 ~0.05-0.25 (too small, returns minuscule). Aim for
mean row L1 in [0.4, 0.8]. Use `normalize_coefficients(c, "l1")` then
multiply by 0.5-0.8.

## Helper API contracts (common bugs to avoid)

These have caused repeated INVALID iterations — read carefully:

- `normalize_coefficients(c, scheme="l1")` → takes a **dict[str, float]**,
  NOT a numpy array. Returns a dict. If you have an ndarray `w`, convert
  first: `c = dict(zip(member_ids, w.tolist()))`.
- `correlation_dedup(R, threshold, keep_metric=None)` → `R` is a pandas
  DataFrame (T × N), columns = alpha_ids. `keep_metric` is a dict
  `{alpha_id: float}` used for ranking (e.g. IS Sharpe). Returns
  `list[str]` of kept alpha_ids.
- `load_member_is_returns(run_id, alpha_ids, signs=None)` returns a
  pandas DataFrame indexed by date, columns = alpha_ids (may drop
  alphas with no equity curve, so `len(R.columns) ≤ len(alpha_ids)`).
- `member_signs_ic(run_id, alpha_ids, dead_band=0.005)` returns
  `dict[str, int]` with values in {-1, +1}.
- `apply_signs(coef, signs)` returns a NEW dict, element-wise
  multiplied. Both inputs are dicts.
- `shrink_cov(R, shrinkage=0.1)` returns an ndarray (the diagonally
  shrunk sample covariance). Use this OR your own MP denoising, not both.

If your code raises ANY exception during `select_members` or
`member_weights`, the iteration is wasted (logged ERRORED, no metrics).
Wrap matrix inversions / clustering in `try/except` only if you have a
sensible fallback — otherwise let it crash early.

## Self-check before submitting

- [ ] One fenced ```` ```python COMPOSITE_FILE ```` block, nothing else.
- [ ] `COMPOSITE_ID = "auto_013"` exactly.
- [ ] All imports from the allow-list.
- [ ] No `open`, `os.*`, `subprocess.*`, `pathlib`, `pickle`, `sklearn`, etc.
- [ ] `select_members` returns ≥ 2 alpha_ids (empty fails the runner).
- [ ] `member_weights` returns a dict covering every member id.
- [ ] Docstring cites the specific method (e.g. "HRP with cluster-quasi-diag").
- [ ] Idea family NOT in the tried list.
- [ ] Numerical stability checked: any matrix you invert is regularized
      (Ledoit-Wolf or Neumann or pseudo-inverse via `sla.pinvh`).

Write your reasoning first (cite mechanism + literature), then the code
block.
