---
topic: ts_4week_momentum
status: open
hypothesis: "Per-symbol monthly time-series momentum: 4-week log-return z-score vs 6-month history."
data_required: "1m close"
applicability: "Liquid majors; per-symbol; biweekly rebalance"
date_created: 2026-05-09
last_updated: 2026-05-09
linked_alphas: []
---

## Mechanism

Slower than the weekly variant (is_005). 4-week lookback smooths over short-cycle noise; biweekly rebalance halves trade count further. Tests whether monthly-horizon TS momentum is regime-robust where weekly was not.

## Verdict

Monthly trend signals dominated AQR's century-of-evidence dataset. If TS momentum carries any cross-cycle edge in crypto majors, the 4-week version should expose it more reliably than is_005's 7-day version.
