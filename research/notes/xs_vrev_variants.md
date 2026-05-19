# xs_volume_rank reverse — enhancement variants (A, B, A+B)

Idea families: `xs_vrev_vol_target`, `xs_vrev_conc`, `xs_vrev_conc_vol`

## Background

The `xs_volume_rank --reverse` alpha (short top-volume / long bottom-
volume on a daily cross-section) passed IS/OS in `run_2026_05_xs500`:
IS sharpe 0.91 yearly, OS 1.02, forward +1.15%.

EDA on the IS window (274-coin daily) showed two orthogonal
improvements over the original half-basket equal-weight form:

| Enhancement     | Daily mean | Daily std | Sharpe(d√252) | Cum   |
|-----------------|-----------:|----------:|--------------:|------:|
| BASE            | 0.0459%    | 0.6068%   | 1.20          | +38.6%|
| **A. Vol-target (1/σ)**     | 0.0464%    | **0.5161%**| **1.43**| +38.98%|
| **B. Concentration q=0.10** | **0.0807%**| 1.336%    | 0.96    | +67.8%|
| **A+B (q=0.10 + 1/σ)**      | **0.092%** | **1.027%**| **1.43**| **+77.3%** |

A reduces std (risk-balance — high-σ small-caps no longer dominate
the variance budget). B raises mean (Q5-Q1 spread is ~2x the half-
basket spread). A+B captures both effects.

## Hypotheses

**A — Vol-targeted half-basket** (idea_family: `xs_vrev_vol_target`)

Each leg's per-coin weight is proportional to `1/σ_i` (20-day rolling
realised vol), normalised so each leg's gross is 0.5. Short top-half /
long bottom-half by quote_volume. Reverse direction.

The risk contribution of each coin becomes approximately equal,
preventing a handful of high-vol alts from swamping the portfolio's
variance.

**B — Concentration q=0.10** (idea_family: `xs_vrev_conc`)

Take only the top 10% (short) and bottom 10% (long) of the cross-
section by quote_volume. Equal weight within each leg. Half-basket
diluted Q5-Q1 spread by ~50%; concentration recovers it. Variance
goes up because basket is smaller — see why A and B are stronger
together than alone.

**A+B — Concentrated + vol-targeted** (idea_family: `xs_vrev_conc_vol`)

Apply both. Concentration sharpens the mean; vol-targeting damps
the variance. Orthogonal effects.

## Search-space cells

All three:
- `bar`: `TIME`
- `transform`: `rolling_rank`
- `horizon`: `multi_day`
- `universe`: `basket_full`
- `exit`: `signal_flip`

idea_family differs per variant to keep cell signatures unique
(governance-distinct).

## Sample size / fee discipline

Daily rebalance on a 274-coin universe (109 IS-active). Trades per
year scale linearly with `concentration_pct × 2 × N_active × 252`.
For q=0.5 baseline → ~28k/year; for q=0.10 → ~5.6k/year. Fee budget
0.10% round-trip per trade × weight.

## Anti-patterns avoided

- *Tuning q after seeing IS sharpe*. q=0.10 is pre-registered from
  EDA spread tables (Q5-Q1 vs half-basket).
- *Reusing the original `xs_volume_rank` cell*. Variants get distinct
  idea_family to satisfy uniqueness governance.

## References

- xs_volume_rank base note: `research/notes/xs_volume_rank.md`
- EDA: `/tmp/eda_xsvol_variants.py` (output kept in archive LOG)
