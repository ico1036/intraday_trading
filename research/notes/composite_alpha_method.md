---
topic: composite_alpha_method
status: open
hypothesis: "Equal-weighted (1/N) average of independent intraday alpha weight series produces a composite portfolio with risk diversification benefits — gross exposure is bounded by the per-alpha sum-of-weights constraint, and idiosyncratic noise across alphas partially cancels."
data_required: "weights.parquet event logs from previously archived alphas; same bar grid (TIME 60s) and same 7-symbol universe."
applicability: "Diagnostic / methodology — applies to any pool of archived alphas sharing the same universe and bar grid."
date_created: 2026-05-08
last_updated: 2026-05-08
linked_alphas: []
---

## Sources

- [textbook] Grinold & Kahn, *Active Portfolio Management* (2nd ed., 2000), Chapter 7 "Information Analysis" and Chapter 14 "Portfolio Construction".
  - Key: Combining independent signals raises the combined IR by ~sqrt(N) when correlations are low; equal weighting is the maximum-entropy default when no prior on signal quality is justified.
- [academic] DeMiguel, Garlappi & Uppal (2009), "Optimal Versus Naive Diversification: How Inefficient is the 1/N Portfolio Strategy?" *Review of Financial Studies* 22(5).
  - Key: 1/N often outperforms mean-variance optimisation out-of-sample because in-sample optimisation overfits noise in expected returns / covariances.

## Mechanism

Each alpha emits a signed `target_weight` per (timestamp, symbol). Forward-filling its sparse rebalance event log produces a continuous weight panel `W_a[t, s]` per alpha. The 1/N composite is `W_comp[t, s] = (1/N) * Σ_a W_a[t, s]`. By the triangle inequality, `Σ_s |W_comp[t, s]| ≤ max_a Σ_s |W_a[t, s]| ≤ 1`, so the runner's gross-exposure constraint is preserved without re-normalisation. Cross-alpha sign disagreement reduces gross turnover and fee drag relative to running each alpha on independent capital sleeves.

## Applicability check

- Required data fields: `weights.parquet` (long-format event log) per member alpha; standard bar data for re-simulation.
- Required bar type: TIME 60s (matches all 245 IS-window alphas in current archive).
- Universe restriction: 7-symbol default universe.
- Fee headroom: composite turnover ≤ max member turnover, so fee drag bounded above by single-alpha fee assumption.

## Verdict

Use as a baseline composite. The 1/N test is a sanity check for the Ex-post composite tooling — once the pipeline is verified, more sophisticated weighting (Sharpe-weighted, risk-parity, mean-variance) can plug into the same adapter by changing only the upstream weight-combination step.
