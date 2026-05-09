---
topic: ts_weekly_orderflow_momentum
status: open
hypothesis: "Per-symbol weekly orderflow momentum: when accumulated taker-buy aggression over the past 7 days is large in z-score versus the trailing 4-week distribution, the next-week price drift continues in the same direction."
data_required: "1m candles with volume_imbalance and volume"
applicability: "Liquid majors; per-symbol; weekly rebalance"
date_created: 2026-05-09
last_updated: 2026-05-09
linked_alphas: []
---

## Sources

- [academic] Easley, López de Prado, O'Hara (2012) "The Volume Clock: Insights into the High Frequency Paradigm".
  - Key: order-flow imbalance carries information that propagates into price with a lag.
- [practitioner] Cont, Kukanov, Stoikov (2014) "The price impact of order book events".

## Mechanism

is_005 confirmed that *price-based* weekly TS momentum carries an edge. Whether *flow-based* weekly TS momentum captures distinct or correlated information is an empirical question. If price already incorporates flow, the two signals will be highly correlated; if there is residual information in cumulative taker-buy intensity that price has not yet absorbed, this provides a differentiated alpha. Weekly cadence reuses the proven low-fee structure of is_005.

## Applicability check

- Required data fields: volume, volume_imbalance
- Required bar type: TIME 1m (10080 bars = 7 days)
- Universe restriction: per-symbol; basket_full
- Fee headroom: matches is_005's ~260 trades

## Verdict

Distinct from is_005 (signal source: signed flow vs price return). Worth running to surface flow-residual alpha if any exists.
