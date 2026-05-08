---
topic: ts_burst_revert
status: open
hypothesis: "Per-symbol return burst beyond k sigmas of trailing distribution mean-reverts in the next M bars; reversal is strongest at multi-hour horizons (4–8h)."
data_required: "close prices, bar-level returns"
applicability: "Per-symbol time-series reversal applied across the basket"
date_created: 2026-05-08
last_updated: 2026-05-08
linked_alphas: []
---

## Sources

- [academic] Jegadeesh (1990), "Evidence of Predictable Behavior of Security Returns" — JF
  - Key: short-horizon reversal is a robust empirical pattern
- [academic] Avellaneda & Lee (2010), "Statistical Arbitrage in the U.S. Equities Market"
  - Key: residual reversal works at multi-hour to multi-day horizons

## Mechanism

A bar with extreme return relative to its trailing standard deviation often
reflects liquidity-driven displacement (large taker order, stop cascade)
rather than fresh information. Inventory absorption brings price back over
the next several hours. The 4-8h window captures the typical inventory-cycle
timescale in crypto perps without competing with fees.

## Applicability check

- Required data fields: close
- Required bar type: TIME
- Universe restriction: any
- Fee headroom: hold ≥ 4h to keep turnover bounded

## Verdict

A natural cell to test at multi-hour horizon. Distinct from is_006/is_007's
hourly per-symbol z-reversal because of the longer holding window.
