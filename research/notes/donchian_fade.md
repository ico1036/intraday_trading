---
topic: donchian_fade
status: open
hypothesis: "Crypto perp closes that break a multi-day Donchian channel (rolling N-bar high/low) FADE in the subsequent days, mirroring is_023's ORB-fade success at session scale."
data_required: "high, low, close on minute bars."
applicability: "Per-symbol; SHORT close > Donchian-high(N), LONG close < Donchian-low(N); hold until opposite break."
date_created: 2026-05-08
last_updated: 2026-05-08
linked_alphas: []
---

## Sources

- [practitioner] Curtis Faith (2007), "Way of the Turtle" — describes Donchian breakout system used by Turtles
  - Key: original Donchian breakout was a continuation system; modern crypto literature documents the inverse (fade) at short horizons
- [practitioner] is_023 internal (this run): orb_fade at session scale produced PF 1.24 / Sharpe 0.99 — natural extension to longer Donchian windows
  - Key: same fade mechanism likely applies at longer windows because crypto regime in this IS appears mean-reverting

## Mechanism

A Donchian breakout at multi-day scale flags an exhausted trend rather than
a fresh information signal — most multi-day extremes occur on chop-driven
overshoots (funding rotations, leverage flushes) that revert. Holding the
fade until the opposite Donchian band breaks captures the reversion span
without high turnover.

## Applicability check

- Required data fields: high, low, close
- Required bar type: TIME
- Universe restriction: any
- Fee headroom: very sparse triggers (~1 every few days per symbol) → fee-friendly

## Verdict

Direct multi-day analogue of is_023 success.
