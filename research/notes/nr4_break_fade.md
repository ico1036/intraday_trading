---
topic: nr4_break_fade
status: open
hypothesis: "When a bar's range is the narrowest of the past 4 bars (NR4), a subsequent break of that bar's high/low fades."
data_required: "high, low for last N bars."
applicability: "Per-symbol; SHORT on close > NR4-high after NR4 forms; LONG on close < NR4-low."
date_created: 2026-05-08
last_updated: 2026-05-08
linked_alphas: []
---

## Sources

- [practitioner] Toby Crabel (1990), "Day Trading with Short Term Price Patterns"
  - Key: NR4 / NR7 are textbook consolidation-then-break patterns; Crabel documents the fade direction
- [practitioner] is_023, is_028 internal — same fade-extreme template

## Mechanism

A narrowest-range bar signals consolidation. The first break of that bar
typically liquidates one side of the consolidation but reverts as the other
side absorbs. Sparse trigger by construction.

## Applicability check

- Required data fields: high, low, close
- Required bar type: TIME
- Universe restriction: any
- Fee headroom: triggers are sparse (NR4 occurs ~25% of bars)

## Verdict

Distinct family. Sparse trigger + signal_flip exit fits the winning template.
