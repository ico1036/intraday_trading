---
topic: ts_weekly_momentum
status: open
hypothesis: "On weekly rebalance, per-symbol time-series momentum at the 7-day horizon: a symbol with a strongly positive 7-day log return (high z-score vs trailing 4 weeks) tends to continue trending in that direction over the next week."
data_required: "1m close (only end-of-window prices used)"
applicability: "Liquid majors; per-symbol decision; weekly rebalance — 7x lower turnover than daily variants"
date_created: 2026-05-09
last_updated: 2026-05-09
linked_alphas: []
---

## Sources

- [academic] Moskowitz, Ooi, Pedersen (2012) "Time series momentum", J. Financial Economics.
  - Key: TS momentum is robust at multiple horizons; weekly is a natural inter-mediate frequency between intraday noise and monthly persistence.
- [practitioner] Hurst, Ooi, Pedersen (2017) "A century of evidence on trend-following investing", AQR.

## Mechanism

The same continuation/dispersion economics as the daily variant, but on a slower clock. Holding for a full week dilutes per-trade fee impact dramatically: a daily-rebalanced 7-symbol portfolio incurs ~7x more round-trip fees than a weekly-rebalanced one for the same position sizes. This run's daily TS/XS momentum and reversal alphas all failed despite reasonable win-rates because fee drag absorbed the per-trade edge — moving to weekly cadence directly tests whether the underlying signal carries any post-cost edge at all.

## Applicability check

- Required data fields: close
- Required bar type: TIME 1m (10080 bars = 7 days)
- Universe restriction: applied independently per symbol; basket_full
- Fee headroom: ~12 rebalance events × 7 symbols × ~2 trades-per-event ~= 170 trades over 90 days; round-trip fee drag ~3% of capital — leaves plenty of room

## Verdict

If the underlying time-series momentum carries any positive expected return after fees on this 7-symbol panel, the weekly cadence should expose it. If this also fails, the conclusion is the directional momentum signal itself is non-informative on Q3 2024.
