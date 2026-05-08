---
topic: return_burst_revert
status: open
hypothesis: "Single-bar return burst beyond k sigmas of trailing distribution mean-reverts in the next N bars."
data_required: "close prices, bar-level returns."
applicability: "Per-symbol short-horizon reversal with z-score gating."
date_created: 2026-05-08
last_updated: 2026-05-08
linked_alphas: []
---

## Sources

- [academic] Jegadeesh (1990), "Evidence of Predictable Behavior of Security Returns" — JF
  - Key: monthly contrarian profits; intraday analogue documented in HFT literature
- [academic] Avellaneda & Lee (2010), "Statistical Arbitrage in the U.S. Equities Market"
  - Key: residual reversal extends to short horizons

## Mechanism

A bar with extreme return relative to its trailing standard deviation often
reflects liquidity-driven displacement (large taker order, stop cascade)
rather than fresh information. Inventory absorption brings price back over
the next several bars. Z-score gating filters out genuinely informational
moves whose vol context is also elevated.

## Applicability check

- Required data fields: close
- Required bar type: TIME
- Universe restriction: any
- Fee headroom: signal strong but turnover high — must hold ≥ a few bars

## Verdict

Classic short-horizon contrarian. Pair with a holding-period gate.
