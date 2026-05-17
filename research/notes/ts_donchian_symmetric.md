---
topic: ts_donchian_symmetric
status: open
hypothesis: "Symmetric Donchian persist captures both directional regimes — entering long on upper-channel breakout AND short on lower-channel breakdown — should reduce the long-only beta exposure of the long_persist family while preserving its time-series momentum signal."
data_required: "TIME 60s bars on the run universe."
applicability: "Multi-day TS-momentum on basket_full universe with time-stop exit."
date_created: 2026-05-10
last_updated: 2026-05-10
linked_alphas: []
---

## Sources

- [academic] Moskowitz, Ooi & Pedersen (2012), "Time series momentum," *Journal of Financial Economics* 104(2).
  - Key: TS-mom is canonically symmetric — long if past return > 0, short if past return < 0. Truncating to long-only erases half the signal and adds market beta.
- [book] Faber, *The Ivy Portfolio* (2009).
  - Key: Channel breakout (Donchian) is a robust trend-following filter; symmetric application gives a market-neutral overlay candidate when net positions average to zero across regimes.

## Mechanism

Each rebalance bar, for every symbol: compute fast-channel high/low (over ``fast_bars``) and slow-channel high/low (``slow_bars``). Regime = +1 if close ≥ slow_high, −1 if close ≤ slow_low. Within a positive regime, enter LONG when fast-channel upper is broken (or persist re-entry while in regime). Within a negative regime, enter SHORT on fast lower breakdown. Time-stop exit after ``hold_bars`` regardless of regime. Sum-of-weights cap = 1.0; per-symbol max-weight bounds gross exposure.

## Applicability check

- Bars: TIME 60s.
- Universe: 7-symbol default.
- Fees: ~5 bps taker per round-trip; signal-to-noise dominates fee drag at multi-day horizons.

## Verdict

Open; first IS pass will determine whether the short leg adds Sharpe or just drags it (bull-cycle IS likely punishes shorts, but cross-cycle composite benefits from symmetry). Submittable threshold same as run-wide quality_gates.
