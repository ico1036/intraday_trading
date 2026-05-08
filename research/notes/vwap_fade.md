---
topic: vwap_fade
status: open
hypothesis: "Closes far above session VWAP fade short-term as price reverts to volume-weighted equilibrium; symmetric for closes below VWAP."
data_required: "close prices, volume per bar."
applicability: "Per-symbol; SHORT close > VWAP×(1+threshold); LONG close < VWAP×(1-threshold). Hold until cross."
date_created: 2026-05-08
last_updated: 2026-05-08
linked_alphas: []
---

## Sources

- [practitioner] Berkowitz, Logue, Noser (1988), "The Total Cost of Transactions on the NYSE" — JF
  - Key: VWAP is institutional execution benchmark; closes deviating from VWAP carry information about over/underexecution
- [practitioner] Konishi (2002), "Optimal slice of a VWAP trade" — JFM
  - Key: VWAP-anchored deviations mean-revert as institutional rebalances complete

## Mechanism

Within a session, accumulation/distribution of volume defines a fair-value
proxy (VWAP). Large deviations from VWAP trigger institutional rebalance flow
(VWAP-target algos), pulling price back. The fade direction matches this
institutional flow.

## Applicability check

- Required data fields: close, volume
- Required bar type: TIME
- Universe restriction: any
- Fee headroom: deviations occur ~few times/session per symbol → reasonable trade count

## Verdict

Distinct family from orb_fade. Different anchor (volume-weighted vs OR).
