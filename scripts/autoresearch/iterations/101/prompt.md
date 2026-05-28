# Composite Alpha Researcher — Iteration 101

You are a quant researcher generating ONE composite-alpha attempt. Your
output is ONE Python file. The harness compiles it, runs the official
backtester, and logs the result. You are scored only by the OS Sharpe
from the actual backtest. You do not see OS data at any point — selection
and weighting must use IS-only metrics.

## Mission

Build a composite alpha that achieves **OS daily Sharpe ≥ 2.0**
on archived run `run_2026_05_c` (real fees + slippage via the canonical
backtester). You are attempt **101** of at most 200.

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
COMPOSITE_ID = "auto_101"      # exact string, do not change
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

COMPOSITE_ID = "auto_101"
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
- Median IS Sharpe across pool: **{is_sharpe_median:.3f}**
- 90th-percentile IS Sharpe: **{is_sharpe_p90:.3f}**
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
    - iter 039 `auto_039_eb_sharpe_shrink_neumann_k4_top6_yearsta` → ERRORED: backtest produced incomplete metrics. tail:     include_os=not args.no_os,
        ^^^^^^^^^^^^^^^^^^^^^^^^^^
    )
    ^
  File "/Users/taeyeong/intraday_tradi

## Strategy hint from the user

The user explicitly asked for: **"high-return / high-risk alpha-focused
combination with Neumann-series eigenvalue-divergence suppression for
MinVol"**. You may build on this but you should also propose more
sophisticated alternatives — NCO with RMT denoising + detoning, HERC,
risk-parity in the eigenbasis, etc. — when a different idea has a
better mathematical justification for hitting OS Sharpe ≥ 2.0.

## CRITICAL — regime shift between IS and OS is the dominant failure

Empirical results from prior attempts (iter 1-14):

- High-IS-Sharpe selection rules: IS 1.0-1.4 → OS 0.0-0.3 (degraded)
- "Anti-bias" selection (middle quintile, random subsets, IC-IR, CSCV
  bootstrap, cluster-median): IS 0.8-1.3 → OS **NEGATIVE** (worse!)

This rules out plain selection bias as the dominant problem. The
actual issue is **regime change between IS and OS windows**:

- IS: 2022-01 → 2024-04 (LUNA collapse, FTX collapse, 2023 chop,
  2024 ETF rally / pre-halving)
- OS: 2024-04 → 2026-05 (post-halving cycle, yen-carry crash Aug-24,
  election rally, 2025-2026 bull/correction mix)

Strategies that worked in 2022 bear → 2023 chop → 2024 rally do not
auto-generalize to 2024 post-halving + 2025 bull. "Anti-bias" rules
keep mediocre 2022-2024 alphas; concentrated top-IS picks at least
keep the genuinely robust ones along with the lucky.

**What to try next (regime-aware angles):**

- **Concentrated top selection (k=3-5)**: extreme concentration on the
  3-5 highest-IS-Sharpe alphas with low pairwise correlation. The
  best-of-best may genuinely be robust; large N just dilutes.
- **Per-year IS stability**: split IS into 2022/2023/2024 sub-periods,
  compute per-year Sharpe for each alpha, keep ONLY alphas with
  positive Sharpe in EVERY sub-period (regime-conditional robustness).
- **Drawdown-disciplined selection**: keep alphas whose max IS
  drawdown < 20% (less likely to be lucky on tail events).
- **Macro-orthogonal**: regress each alpha's returns on BTC daily
  return (the dominant market factor), keep alphas with low β AND
  positive residual mean (true alpha, not BTC beta).
- **Hold the prior winner**: tangency/MV/MinVol on the top-5 highest
  IS-Sharpe (mirror the auto_002 winning ingredients with smaller N).
- **Sign-aware combination with IC-IR alignment**: `member_signs_ic`
  flips IC<0 alphas; then within the kept set, weight by
  `IC × stability` rather than raw Sharpe.
- **Member-count sweet spot**: data shows n=6-10 outperforms n=30+
  (auto_002 n=6, auto_003 n=10 lead). Target n ∈ [4, 12].

**Coefficient magnitude:** prior attempts hovered mean row L1 ≈ 0.05-0.25
(returns muted). After normalization, scale up to mean row L1 in
[0.5, 0.9] to extract more PnL — use
`normalize_coefficients(c, "l1")` then multiply by 0.6-0.8.

## URGENT: composite underperforms individual top alphas — gross-exposure ceiling

Hard empirical evidence from current state:

- Top-10 individual alphas in this pool have **OS Sharpe in [1.0, 1.11]**.
- Our best composite to date has **OS Sharpe 0.838** with
  `mean_row_l1 = 0.049` (5% gross exposure).
- That means the composite is leaving 95% of its risk budget on the
  table — pure portfolio of cash.

**Root cause:** every tangency / min-variance / inv-cov optimizer
produces `w ∝ Σ⁻¹·μ` (or `Σ⁻¹·1`), which is naturally 1/σ-weighted.
After `_runner.py`'s row-L1 clamp to 1.0, no clamping happens because
`Σ_s|W| ≪ 1` already. The composite NEVER scales up.

**Mandatory fix every iteration:** before returning your coefficient
dict from `member_weights`, compute the would-be mean row L1 and
rescale so it hits 0.5-0.8. Sketch:

```python
# coef is your dict[str, float]
# Build the implied combined weight panel from member panels in your own
# IS-only space to estimate mean gross. Or simpler:
sigma_a = R[loaded].std()              # per-member daily vol of weight stream
est_gross = float((np.abs(np.array(list(coef.values()))) * sigma_a).sum())
# Rescale; target mean row L1 ≈ 0.6
TARGET_GROSS = 0.6
if est_gross > 0:
    scale = TARGET_GROSS / max(est_gross, 1e-6)
    coef = {k: v * scale for k, v in coef.items()}
```

Or more robustly: just multiply ALL coefficients by 5-15× at the end
when you used a min-var/tangency style optimizer. Empirically these
optimizers underweight by 10×.

## Cov-FREE composition methods to try (NEW — never attempted)

Every prior attempt used cov-based optimization. The user has flagged
this as the blocker. Try these — they preserve native member leverage:

**DO NOT pick Gram-Schmidt** — empirically failed 9/9 prior attempts
(IS overfits the residual-Sharpe ranking, OS collapses negative). Try
ONE of the OTHER three methods below first.

- **Greedy Gram-Schmidt orthogonalization** (SKIP — failed 9/9):
  1. Order candidates by IS Sharpe desc.
  2. Take strongest as `r1`. Add to portfolio with weight 1.
  3. For each next candidate, regress its IS returns on `{r1,...,r_{k-1}}`
     and keep the **residual returns** `r_perp`.
  4. Score by `Sharpe(r_perp)` — high residual Sharpe = orthogonal new info.
  5. Add the top one with weight equal to its residual Sharpe (or 1).
  6. Stop when residual Sharpe drops below 0.3 (no more orthogonal info).
  Final weights: `1/n` over the kept set, then rescale gross to 0.6.

- **Cluster centroid then equal-weight** (user-suggested):
  1. `R = load_member_is_returns(...)` then `corr = R.corr()`.
  2. `dist = sqrt(0.5 * (1 - corr))` → Ward hierarchical clustering.
  3. Cut at K clusters (try K=4, 6, 8).
  4. Within each cluster, pick the single highest-IS-Sharpe alpha
     (centroid representative).
  5. Equal-weight: `coef = {centroid_i: 1/K for i in range(K)}`.
  6. Rescale gross to 0.6-0.8.

- **Correlation-rank + Sharpe-rank composite score**:
  1. For each candidate, compute `rank_sharpe = rank by IS Sharpe desc`
     and `rank_orthogonal = rank by mean |corr| with prior picks asc`.
  2. Combined score = `0.5 * rank_sharpe + 0.5 * rank_orthogonal`.
  3. Greedy add top-scoring next candidate until n=8.

- **Pure 1/N over top-K with native exposure**:
  `coef = {a: 1.0 for a in top_K_by_IS_Sharpe}`, then
  `normalize_coefficients(coef, "l1")` → each gets `1/K`. Skip
  cov inversion entirely.

These methods bypass the 1/σ-weighting trap. Use them this iteration.

## Current leaderboard pattern (exploit-near-winners hint)

Live leaderboard shows top OS Sharpes in [0.30, 0.41]. The pattern that
consistently lands top-5 has these ingredients:

- **n_members ∈ [5, 8]** (concentrated)
- **per-year IS Sharpe stability filter** (positive Sh in every IS sub-year)
- **drawdown discipline** (max IS DD < 20-25%)
- **Neumann series cov inverse OR MP-denoised cov + tangency / min-var**
- **correlation dedup at ρ ∈ [0.80, 0.90]**

Things that consistently UNDER-PERFORM (don't repeat):
- n_members > 20 (dilution)
- "anti-bias" middle-quintile / random subsets (OS turns negative)
- Calmar / Omega / Sortino-only criteria (too sample-fragile)
- Michaud resampling without year-stability filter (OS regresses)

**Permission to exploit near winners:** Try variations on top-3 ideas:
- Different N-of-top-K cutoffs (k=3, k=4, k=6)
- Different DD thresholds (15%, 20%, 30%)
- Different ρ thresholds (0.75, 0.85, 0.92)
- Different cov regularizers (Ledoit-Wolf shrinkage vs Tikhonov vs MP)
- Sign-aware (`member_signs_ic`) on/off variations
- Coefficient post-scale (try aiming mean row L1 = 0.5 vs 0.7 vs 0.9)

But also try ONE genuinely different angle per iteration — not pure
hill-climb. Reserve ~30% iterations for unexplored territory:
- Spectral clustering on cov, then 1-per-cluster top-IS
- Risk parity in the eigenbasis (Meucci DRP) — careful: prior attempt
  with that name went OS-negative
- Online FTRL/ONS over expanding-window IS returns
- Bayesian alpha pooling with empirical Bayes prior

## Helper API contracts (common bugs to avoid)

These have caused repeated INVALID iterations — read carefully:

- `normalize_coefficients(c, scheme="l1")` → takes a **dict[str, float]**,
  NOT a numpy array. Returns a dict. If you have an ndarray `w`, convert
  first: `c = dict(zip(member_ids, w.tolist()))`.
- `correlation_dedup(R, threshold, keep_metric=None)` → `R` is a pandas
  DataFrame (T × N), columns = alpha_ids. `keep_metric` is a dict
  `{{alpha_id: float}}` used for ranking (e.g. IS Sharpe). Returns
  `list[str]` of kept alpha_ids.
- `load_member_is_returns(run_id, alpha_ids, signs=None)` returns a
  pandas DataFrame indexed by date, columns = alpha_ids (may drop
  alphas with no equity curve, so `len(R.columns) ≤ len(alpha_ids)`).
- `member_signs_ic(run_id, alpha_ids, dead_band=0.005)` returns
  `dict[str, int]` with values in {{-1, +1}}.
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
- [ ] `COMPOSITE_ID = "auto_101"` exactly.
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
