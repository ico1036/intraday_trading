# Composite Member Cutoff — Signal vs Noise Analysis

**Date**: 2026-05-12
**Author**: Claude (overnight L/S batch follow-up)
**Status**: draft — awaiting user feedback before locking the gate

## TL;DR

Our existing submittable gate (S1–S7) was designed for **standalone alpha publication**: every threshold answers "is this alpha tradeable by itself?". When we apply it to the 385 alphas with both IS and OS results, **zero pass**. The bottleneck is **S1 (OS t-stat > 2.5)**: not one alpha meets it.

But the population-level statistics show our signals are not random — we see **2.5× excess passers vs the noise null** at moderate t-stat thresholds. The right move for *composite member selection* is not to relax S1 alone, but to pivot to a **signal-vs-noise gate**: keep IS-side strict, accept moderate-but-real OS edges, require sign preservation. With G2 = 0.8 (OS t-stat ≥ 0.8) the candidate pool is **192 alphas with near 1:1 long-only / L/S balance** — usable for a dollar-balanced composite.

The current report justifies that choice; the recommendation is **G2 = 1.0** (pool 140, slightly stricter, still defensible) as the primary, with **G2 = 0.8 (192) as a stretch pool** if more L/S members are required for dollar-balance.

---

## 1. The framing problem

`alpha_dashboard_lib.classify_alpha` enforces 11 gates, summarised:

| Group | Gate | Threshold | Measures |
|---|---|---|---|
| Reject | R1 | bps > 0 (IS & OS) | basic profitability |
| Reject | R2 | OS t-stat ≥ 1.5 | edge ≠ noise (85% conf) |
| Reject | R3 | sharpe degr ≥ 0.4 | OS preserves Sharpe partially |
| Reject | R4 | IS trades ≥ 100 | sample size sanity |
| Submit | S1 | OS t-stat > 2.5 | strong stat significance |
| Submit | S2 | OS bps > 2.0 | meaningful edge size |
| Submit | S3 | sharpe degr > 0.7 | robust over time |
| Submit | S4 | bps degr > 0.6 | bps robust over time |
| Submit | S5 | \|OS DD\| < 0.12 | risk control |
| Submit | S6 | OS profit factor > 1.3 | win/loss balance |
| Submit | S7 | IS trades > 500 | statistical power |

Every one of these asks "is this *standalone* alpha tradeable?". None ask "does this alpha **contribute to a portfolio**?". For the composite workflow, that distinction matters:

- A noisy individual alpha can be a strong portfolio member if its noise is uncorrelated with peers.
- A pristine individual alpha may be redundant if it duplicates an existing member.

This report addresses the question **"which alphas have real signals (not noise), regardless of standalone performance magnitude?"**, motivated by the user's request that single-gate criteria be relaxed for composite use.

## 2. Per-gate pass rates — diagnosing the bottleneck

![Per-gate pass rates](figures/07_gate_efficiency.png)

Out of **385 alphas with both IS and OS metrics**:

| Gate | Pass count | % | Notes |
|---|---:|---:|---|
| R4: IS trades ≥ 100 | 385 | 100% | always satisfied |
| G4: IS bps > 0 | 385 | 100% | every alpha is IS-profitable |
| S7: IS trades > 500 | 359 | 93% | well-supplied |
| G1: IS per-trade t ≥ 1.96 | 337 | 88% | IS edge is statistically real |
| R1: bps > 0 (IS&OS) | 317 | 82% | most stay profitable in OS |
| G3: OS bps > 0 | 317 | 82% | sign preservation strong |
| S2: OS bps > 2.0 | 307 | 80% | meaningful OS edge size |
| G5: Sharpe sign agree | 321 | 83% | IS↔OS direction holds |
| S5: \|OS DD\| < 0.12 | 248 | 64% | OS drawdown contained |
| R3: sharpe degr ≥ 0.4 | 235 | 61% | partial robustness |
| **G2: OS t ≥ 0.8** | **192** | **50%** | half clear weak stat-sig |
| **G2: OS t ≥ 1.0** | **152** | **39%** | one-sided p=0.16 |
| S3: sharpe degr > 0.7 | 57 | 15% | strict robustness |
| **R2: OS t ≥ 1.5** | **23** | **6%** | the killer |
| **S1: OS t > 2.5** | **0** | **0%** | nobody clears |

**Conclusion**: the bottleneck is the **OS t-statistic**, not OS profitability, not DD, not Sharpe degradation. Profitability (G3, S2) is preserved by 80%+ of alphas; sign agreement (G5) by 83%. The only thing missing is enough statistical power to clear `t > 2.5` (S1) or even `t > 1.5` (R2).

## 3. Why OS t-stat is structurally low

The trade-level t-statistic is

$$
t = \frac{\bar{x}_{\text{bps}}}{s_{\text{bps}} / \sqrt{N}} = \text{per\_trade\_sharpe} \cdot \sqrt{N}
$$

`per_trade_sharpe` is the trade-level Sharpe (mean/std of round-trip bps). `N` is the round-trip count.

![Per-trade Sharpe IS vs OS](figures/05_per_trade_sharpe.png)

| Metric | IS (median) | OS (median) | Degradation |
|---|---:|---:|---:|
| per-trade Sharpe | 0.088 | 0.035 | **0.40** ⚠ |
| trade count N | 797 | 643 | 0.81 |
| t-stat = ps · √N | 2.48 | 0.89 | 0.36 |

**OS edge per trade is 40% of IS edge** — the trade quality drops, not the trade count. For comparison, an "IC of 0.05" is typically called respectable in equity quant. Our IS per-trade Sharpe at 0.088 is healthy; our OS per-trade Sharpe at 0.035 is weak but non-zero.

Across the universe this is a real-environment effect: **IS** (2022-01 → 2024-04) contained LUNA/FTX shocks → recovery → ETF rally — large persistent trends that Donchian-family alphas exploit. **OS** (2024-04 → 2026-05) is the post-halving cycle, with shorter, less persistent trends. Same signal logic, lower per-trade payoff.

![OS t-stat distribution](figures/01_os_tstat_distribution.png)

The distribution shows where each gate would slice: at S1=2.5 the slice is empty; at R2=1.5 it captures only the tail; at G2=0.8–1.0 it captures the meat of the distribution.

## 4. Population-level evidence: signals are real

The single-alpha t-stat argument considers each alpha in isolation. But we have 385 alphas — a population. Under the null **H₀: "every alpha is pure noise"**, the per-trade t-stats should be roughly standard normal. The number of passers at each threshold follows Binomial(N=385, p = 1 − Φ(τ)).

![Observed vs null](figures/04_observed_vs_null.png)

| τ (threshold) | E[count] under H₀ | Observed | Ratio | P(≥ obs \| H₀) |
|---:|---:|---:|---:|---:|
| 0.0 | 192.5 | 317 | 1.65× | 0 |
| 0.5 | 118.8 | 263 | 2.21× | 0 |
| 0.8 | 81.6 | 208 | 2.55× | 0 |
| 1.0 | 61.1 | 152 | 2.49× | 0 |
| 1.28 | 38.6 | 82 | 2.12× | 5e-11 |
| 1.645 | 19.2 | 2 | 0.10× | 1.0 |
| 1.96 | 9.6 | 1 | 0.10× | 1.0 |
| 2.5 | 2.4 | 0 | 0× | 1.0 |

Two findings:

1. **At moderate thresholds (τ ≤ 1.28)** we see 2.1–2.6× excess passers vs the noise null — overwhelmingly significant (p ≈ 0 for all). **Strong evidence that real signals exist in the population**.
2. **At high thresholds (τ ≥ 1.5)** we see *deficit* vs the noise null. This is not because signals are absent — it's because OS edges are *moderately* positive (median 0.035 per-trade Sharpe) and the t-statistic mass concentrates near t = 1, not at the noise tail near t = 2.

**Interpretation**: our alphas produce a distribution that has been **shifted to the positive side** but with limited magnitude — concentrated mass at moderate t, thin upper tail. This is exactly the population profile of *useful composite members*: each contributes a small real edge.

## 5. Sign-preservation evidence

A signal that survives the IS → OS transition with the **same sign** is by definition not noise (zero-mean noise flips sign 50% of the time).

![IS vs OS Sharpe](figures/02_is_os_sharpe_scatter.png)

- Upper-right quadrant (both Sharpe > 0) = **G5 pass** = sign preserved.
- 321 / 385 = **83.4%** sit in this quadrant.
- Under H₀ (independent random Sharpe each split), only 25% would land here.

The dashed diagonal marks "no degradation". Most points sit *below* the diagonal — OS Sharpe is less than IS — but predominantly above zero. **The signals are dampening, not disappearing.**

![Sharpe degradation](figures/06_sharpe_degradation.png)

The degradation distribution (OS Sharpe / IS Sharpe) is centred near 0.5–0.7 with most mass between 0 and 1.5. R3 (degr ≥ 0.4) catches the right tail at 61%; S3 (degr > 0.7) catches only 15%. Degradation does happen, but most alphas keep a meaningful fraction.

## 6. Threshold sweep — pool size and family balance

The composite-suitable pool size depends on the G2 (OS t-stat) cutoff. Base gates: G1 ∧ G3 ∧ G4 ∧ G5 ∧ G6 (IS-side strong, OS-side sign + non-negative bps, both Sharpe positive, minimum sample size).

![Pool vs threshold](figures/03_pool_vs_threshold.png)

| G2 threshold | One-sided p | Pool | long_only | L/S | Balance |
|---:|---:|---:|---:|---:|---|
| 0.0 (no gate) | 0.50 | 291 | 104 | 187 | L/S heavy |
| 0.5 | 0.31 | 243 | 104 | 139 | L/S leaning |
| **0.8** | **0.21** | **192** | **92** | **100** | **near 1:1** |
| 1.0 | 0.16 | 140 | 74 | 66 | balanced |
| 1.28 | 0.10 | 84 | 53 | 31 | long-leaning |
| 1.645 | 0.05 | 30 | 24 | 6 | long-heavy |
| 2.5 (original S1) | 0.006 | 0 | 0 | 0 | empty |

Key inflection: between **G2 = 0.8 and 1.0** the L/S count nearly halves (100 → 66), and at G2 = 1.28 the L/S leg collapses to 31. Long-only count is more stable because the long-persist family has higher per-trade Sharpe than the symmetric L/S families on this IS/OS pair.

## 7. Recommendation

### Primary: **G2 = 1.0** (pool = 140)

- **Statistical defense**: one-sided p ≈ 0.16. Each individual alpha has ~84% probability of having a true positive edge (vs the noise null), assessed independently. This is weak for standalone but acceptable for composite members.
- **Robustness**: median sharpe_degr 0.67 means 2/3 of IS Sharpe survives in OS.
- **Balance**: 74 long_only + 66 L/S ≈ 53/47 split. Good for dollar-balanced composite construction.
- **Pool size**: 140 is large enough to apply downstream correlation/marginal-Sharpe selection to ~30 final members.

### Stretch: **G2 = 0.8** (pool = 192) — if L/S coverage is the priority

- Same defense weaker (one-sided p ≈ 0.21).
- Better long-only / L/S balance (~48 / 52). Useful when the downstream selector wants more L/S diversity.
- Recommended as a *backup pool* if the G2 = 1.0 selection underproduces L/S members after correlation filtering.

### Reject: **G2 < 0.5** (pool > 240)

At G2 = 0 or 0.5 the pool gains 50+ alphas, but those marginal additions are statistically indistinguishable from noise (p ≥ 0.31). Including them dilutes the average member quality and only helps if downstream selection is very aggressive at filtering.

### Reject: **G2 ≥ 1.28** (pool ≤ 84)

The L/S leg collapses below 31 members. Cannot build a dollar-balanced composite without padding the long-only side and getting back the original long-bias problem.

## 8. Full proposed gate stack

```python
def select_for_composite(df):  # df has both IS and OS metrics
    return df[
        (df.is_t_stat   >= 1.96)   # G1: IS edge is statistically real
        & (df.os_bps    >  0   )   # G3: OS sign preserved
        & (df.is_bps    >  0   )   # G4
        & (df.is_sharpe >  0   )   # G5a
        & (df.os_sharpe >  0   )   # G5b
        & (df.is_trades >= 100 )   # G6: sample size
        & (df.os_t_stat >= 1.0 )   # G2: OS edge non-trivial (recommended)
    ]
```

Compared to the standalone submittable gate this drops S1 (OS t > 2.5), S2 (OS bps > 2.0 — implied by G3 ∧ G1), S3 (sharpe_degr > 0.7 — too strict), S5 (\|OS DD\| < 0.12 — already controlled at portfolio level), S6 (OS PF > 1.3 — magnitude), S7 (IS trades > 500 — covered by G6).

## 9. Caveats and open questions

1. **Family imbalance**: the long-only legacy family dominates the high-t-stat zone because it was developed on cycle-aware breakouts that worked well in the IS bull cycle. The L/S families were added late and have less per-trade edge. A more diverse composite would benefit from new L/S families (e.g., volatility-target, cross-section with longer rebalance) before final selection.

2. **Multiple-testing inflation**: we generated 435 candidates. Even pure noise would produce some high-t alphas. The population-level binomial test (Section 4) explicitly accounts for this, but downstream correlation-aware selection should also penalize members that look like noise outliers from large families.

3. **OS evaluation contamination**: alphas were not selected with OS data, but the *threshold itself* (G2) is being chosen with OS data. To stay clean, the final composite should be locked before any further OS use; a true second OS validation would require a held-out third split or paper-trading.

4. **The 0.8 ↔ 1.0 ↔ 1.28 decision is sensitive to OS edge degradation**. If the next quarter of data shows OS edges recover (per-trade Sharpe rises), the same threshold passes far more alphas. The pool-size curve should be re-evaluated every 1–2 quarters.

## 10. Next steps

1. **User decision**: confirm G2 = 1.0 (recommended) or G2 = 0.8 (stretch).
2. Implement `select_for_composite` in `src/intraday/composites/_runner.py` as a reusable selector.
3. Build a 1/N dollar-balanced composite over the selected pool.
4. Score correlation-aware downstream selection (greedy Sharpe lift, max-correlation cap 0.6) to reduce 140 → ~30 final members.
5. Tag the resulting composite in the dashboard with its selection metadata for traceability.

---

### Appendix A — figure index

- `figures/01_os_tstat_distribution.png` — OS t-stat histogram with gate cuts
- `figures/02_is_os_sharpe_scatter.png` — IS vs OS Sharpe scatter, sign quadrants
- `figures/03_pool_vs_threshold.png` — pool size as function of G2
- `figures/04_observed_vs_null.png` — observed vs noise-null pass count
- `figures/05_per_trade_sharpe.png` — per-trade Sharpe IS vs OS overlay
- `figures/06_sharpe_degradation.png` — degradation distribution with R3/S3 marks
- `figures/07_gate_efficiency.png` — standalone pass rate per gate

### Appendix B — sources

- Code: `scripts/tools/alpha_dashboard_lib.py:classify_alpha`
- Data: `archive/run_2026_05_c/alphas/<id>/{is,os}/metrics.json` for 385 alphas
- Reference for IC interpretation: Grinold & Kahn, *Active Portfolio Management* (2nd ed., 2000), ch. 6
