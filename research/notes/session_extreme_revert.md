---
topic: session_extreme_revert
status: open
hypothesis: "Closes at the session high or session low fade, with the session low being a buy and the session high being a sell."
data_required: "running session high/low and current close"
applicability: "Per-symbol; SHORT when close == session_high so far; LONG when close == session_low. Hold until opposite."
date_created: 2026-05-08
last_updated: 2026-05-08
linked_alphas: []
---

## Sources

- [practitioner] Larry Williams (1979), "How I Made One Million Dollars Trading Commodities"
  - Key: high-low extremes within a session are reliable contrarian markers
- [practitioner] is_023 internal — same fade-extreme template at session OR works

## Mechanism

Each new session high/low typically marks short-term exhaustion. The
running-extreme tracking is a more responsive variant of OR break — it
catches mid-session exhaustion that an opening-range structure would miss.

## Applicability check

- Required data fields: high, low, close
- Required bar type: TIME
- Universe restriction: any
- Fee headroom: triggers naturally sparse (one new high/low per move)

## Verdict

Distinct from orb_fade (extreme is the running session H/L, not the OR boundary).
