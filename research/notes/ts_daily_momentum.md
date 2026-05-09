---
topic: ts_daily_momentum
status: open
hypothesis: "Per-symbol time-series momentum at the daily horizon: when a symbol's trailing 24h log return is large in magnitude relative to its own recent volatility, the next day's return tends to continue the same sign on average, after fees, in liquid USDT-M futures."
data_required: "1m close (only end-of-window prices used)"
applicability: "Liquid majors; per-symbol decision; daily rebalance"
date_created: 2026-05-09
last_updated: 2026-05-09
linked_alphas: []
---

## Sources

- [academic] Moskowitz, Ooi, Pedersen (2012) "Time series momentum", J. Financial Economics.
  - Key: time-series momentum (each asset judged against its own past) generalizes across asset classes and horizons; documented even in highly liquid markets.
- [practitioner] Hurst, Ooi, Pedersen (2017) "A century of evidence on trend-following investing", AQR.
  - Key: TS-momentum survives across regimes when normalized by realized volatility.

## Mechanism

The XS daily momentum and reversal cells both failed for this run, suggesting the *cross-section* ranking was not the right structure for Q3 2024. The TS variant assesses each symbol independently against its own recent volatility, so a symbol with elevated absolute drift gets the position regardless of its rank in the basket. This decouples per-symbol carry from XS herd effects.

## Applicability check

- Required data fields: close
- Required bar type: TIME 1m (1440 bars = 24h, 10080 bars = 1 week)
- Universe restriction: applied independently per symbol; basket_full
- Fee headroom: same daily-rebalance frequency as is_002/is_003 (round-trip fees similar), but symbol direction is independent so fewer simultaneous flips expected

## Verdict

Direction-independent counterpart to the XS-daily attempts. Worth testing under same fee assumptions to see whether TS structure rescues the daily horizon.
