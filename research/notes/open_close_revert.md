---
topic: open_close_revert
status: open
hypothesis: "Per-symbol close vs N-bar open (return over N bars) extreme values fade — short-horizon overreaction reverts."
data_required: "close prices."
applicability: "Per-symbol; SHORT large up moves, LONG large down moves; signal_flip exit."
date_created: 2026-05-08
last_updated: 2026-05-08
linked_alphas: []
---

## Sources

- [academic] Jegadeesh & Titman (1993), short-horizon contrarian effects
- [practitioner] is_023 internal — fade-extreme + signal_flip pattern works

## Mechanism

Cumulative close-to-open return over N bars captures medium-frequency
momentum. Extremes mark exhausted move; reversion captures the snap-back.

## Applicability check

- Required data fields: close
- Required bar type: TIME
- Universe restriction: any
- Fee headroom: depends on N and threshold

## Verdict

Distinct from BB-fade (no rolling sigma, just direct return).
