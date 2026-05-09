# Research Principles

Project-wide research philosophy. These are **task-agnostic** principles that
apply to individual alpha generation, composite alpha construction, regime
analysis, factor decomposition, and any other research work in this repo.

Operational contracts live elsewhere:
- `AGENT.md` — individual alpha generation procedure & forbidden actions
- `CLAUDE.md` — Claude Code workflow

This file is the *why* and *how to think*. The other files are the *what to do*.

---

## Master principles

<!-- Fill in: top-level commandments. The "if you remember nothing else" rules. -->

-

## Statistical discipline

### Sample size & power

<!-- minimum trades for a meaningful Sharpe; rule-of-thumb on standard error -->

-

### Multiple testing & data snooping

<!-- N strategies tested ⇒ expected best Sharpe under null; deflated Sharpe;
     why "I tried 50 variants and one passed" is not evidence -->

-

### Overfitting

<!-- in-sample optimism; degrees of freedom in transforms/thresholds;
     why cell-saturation and breadth-first exist -->

-

### Look-ahead & leakage

<!-- bar-close timing, fill assumptions, future-info contamination -->

-

## Signal & edge

### Where edge actually comes from

<!-- liquidity provision, information asymmetry, behavioral, structural;
     not "the chart looks predictive" -->

-

### Fee-aware thinking

<!-- 0.20% taker means edge per trade must clear 40bps round-trip;
     turnover-Sharpe tradeoff; why high-frequency mean-reversion is hard -->

-

### Regime awareness

<!-- 2023 chop vs 2024 trend; signals are conditional, not universal;
     how to tell regime-dependence from genuine alpha decay -->

-

## Research process

### Breadth over depth

<!-- coverage > exploitation; why tuning a near-winner is the worst
     failure mode in this loop -->

-

### Pre-registration & frozen IS

<!-- decide hypothesis BEFORE looking at OS; OS labels distribution shift
     only — never feeds back into the strategy -->

-

### Failure archival

<!-- failed alphas are data, not waste; LOG.md and alpha_index.csv as
     the institutional memory -->

-

### Hypothesis quality

<!-- a good research note states a *mechanism* — why does this signal
     carry information? "It backtests well" is not a hypothesis -->

-

## Portfolio construction

### Composite & combination

<!-- 1/N as default; correlation-aware weighting; when ensembling
     hurts vs helps; gross-exposure invariants -->

-

### Diversification across cells

<!-- the six-tuple ALPHA_CELL exists to force orthogonality;
     low-correlation members > high-Sharpe singletons -->

-

## Anti-patterns

<!-- A short list of things to actively avoid. Each item: name + one-line
     diagnosis + what to do instead. -->

- **Tune-and-resubmit** — refining a failed alpha until it passes IS. → Move to a different cell.
-

## Glossary & references

<!-- Pointers to canonical sources: López de Prado, Grinold & Kahn,
     Harvey & Liu, etc. Keep short — full citations live in research/notes/. -->

-
