---
topic: burst_then_fade
status: open
hypothesis: "After a single-bar move > k×rolling-sigma, the next 30-60 minutes show a fade as inventory absorbs the displacement."
data_required: "close prices for return + rolling sigma."
applicability: "Per-symbol; SHORT after up burst, LONG after down burst; hold for fixed time."
date_created: 2026-05-08
last_updated: 2026-05-08
linked_alphas: []
---

## Sources

- [academic] Avellaneda & Lee (2010), residual reversal at short horizons
- [practitioner] is_023 internal — fade-extreme signal_flip pattern works

## Mechanism

Single-bar volatility burst beyond k sigma is typically liquidity-driven
(stops cascading, large taker order). Inventory absorption causes reversion.
Holding for a fixed window captures the normalization.

## Applicability check

- Required data fields: close
- Required bar type: TIME
- Universe restriction: any
- Fee headroom: tune k for trigger frequency

## Verdict

Distinct from atr_band_fade (uses sigma not ATR) and orb_fade (no anchor).
