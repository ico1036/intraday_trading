---
topic: bb_band_fade
status: open
hypothesis: "Closes outside Bollinger Bands (mean ± k·sigma) FADE — return to mean within hours. Holding until opposite band hit captures full reversion."
data_required: "close prices for rolling mean and rolling sigma."
applicability: "Per-symbol; SHORT on close > upper band, LONG on close < lower band; exit on opposite band touch (signal_flip)."
date_created: 2026-05-08
last_updated: 2026-05-08
linked_alphas: []
---

## Sources

- [practitioner] John Bollinger (1980s), original BB methodology
  - Key: BB widely used as overbought/oversold indicator
- [academic] Lento, Gradojevic (2007), "The Profitability of Technical Trading Rules" — JBF
  - Key: BB rules show economically meaningful returns with appropriate exit

## Mechanism

A close outside ±k sigma of a rolling mean indicates a deviation that, in
the absence of regime change, mean-reverts as the rolling mean catches up.
The fade direction is the reversion side. Signal_flip exit (close on
opposite band) lets the full mean-reversion span complete.

## Applicability check

- Required data fields: close
- Required bar type: TIME
- Universe restriction: any
- Fee headroom: trigger frequency depends on k; k=2 produces ~5% trigger rate per bar — keep rebalance ≥ hourly to avoid double entries

## Verdict

Same family of "fade extreme; hold until opposite extreme" as is_023 but with
a continuous signal (BB) instead of a session-anchored OR.
