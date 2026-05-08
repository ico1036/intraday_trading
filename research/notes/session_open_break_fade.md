---
topic: session_open_break_fade
status: open
hypothesis: "Closes that break decisively beyond the session open price (>k*ATR away) fade as the session reverts toward open."
data_required: "session open price (first close of session), high/low for ATR."
applicability: "Per-symbol; SHORT close >> open + k·ATR; LONG close << open - k·ATR. Hold until cross of open."
date_created: 2026-05-08
last_updated: 2026-05-08
linked_alphas: []
---

## Sources

- [practitioner] Larry Williams (1979) — open price as a magnetic level
- [practitioner] is_023, is_107 internal — fade-extreme template

## Mechanism

The session open is a natural anchor — many overnight orders rest near it
and intraday algos target it. Decisive break beyond open often indicates
exhaustion of overnight imbalance; price reverts as flow normalizes.

## Applicability check

- Required data fields: high, low, close
- Required bar type: TIME
- Universe restriction: any
- Fee headroom: triggers naturally sparse (1-3 per day per symbol)

## Verdict

Distinct from session_extreme (extreme = running H/L) and orb_fade
(extreme = OR boundary). New anchor (session open).
