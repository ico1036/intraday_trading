---
topic: atr_fast_fade
status: open
hypothesis: "Per-bar return exceeding k×ATR (over a fast 2h window) fades, captured by signal-flip until opposite burst."
data_required: "high, low, close minute bars."
applicability: "Per-symbol, basket or single asset."
date_created: 2026-05-08
last_updated: 2026-05-08
linked_alphas: []
---

## Sources

- [practitioner] Wilder (1978), original ATR
  - Key: short-window ATR responds faster to regime changes
- [practitioner] is_023 internal — fade-extreme + signal_flip is the working template here

## Mechanism

A fast ATR (2h) tracks current vol regime, not slow-moving averages. Bursts
beyond k×ATR are typically liquidity events that revert. Compared with the
slow 24h ATR variant, this captures fresh regime shifts.

## Applicability check

- Required data fields: high, low, close
- Required bar type: TIME
- Universe restriction: any
- Fee headroom: triggers more frequent than slow ATR; tune k for balance

## Verdict

New family distinct from atr_band_fade due to faster window characteristic.
