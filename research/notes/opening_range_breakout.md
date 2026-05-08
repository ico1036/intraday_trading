---
topic: opening_range_breakout
status: open
hypothesis: "Breaks of the first N minutes' range after a key handoff hour (e.g., 00 UTC) carry directional information for the rest of the session."
data_required: "OHLC on minute bars; UTC timestamps."
applicability: "Per-symbol or basket; trigger long on break above OR-high, short below OR-low; flat outside session."
date_created: 2026-05-08
last_updated: 2026-05-08
linked_alphas: []
---

## Sources

- [practitioner] Crabel (1990), "Day Trading with Short Term Price Patterns and Opening Range Breakout"
- [academic] Cooper (1999), "Filter rules based on price and volume" — RFS
  - Key: breakout filters carry persistent edge in liquid futures

## Mechanism

After a synchronizing event (UTC midnight rollover, US open), the first
N-minute range encodes overnight order imbalance. A genuine break of the
range bounds is more likely to continue than to fade because it triggers
algo stops and trend-followers. Holding from break to session end without
re-entering captures the trend without overtrading.

## Applicability check

- Required data fields: high, low, close, timestamp
- Required bar type: TIME
- Universe restriction: any (single or basket)
- Fee headroom: very few trades per day → fee-efficient if session sized right

## Verdict

Low-turnover cell. Useful complement to high-turnover reversal alphas.
