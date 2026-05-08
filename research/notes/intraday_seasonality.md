---
topic: intraday_seasonality
status: open
hypothesis: "Crypto perps show repeatable hour-of-day return and vol patterns driven by US/Asia handoff and funding-settlement clock; conditioning entries on time-of-day improves edge."
data_required: "Bar timestamps; close prices for return computation."
applicability: "Restrict trades to specific UTC hour windows; combine with momentum or reversal signal."
date_created: 2026-05-08
last_updated: 2026-05-08
linked_alphas: []
---

## Sources

- [academic] Heston, Korajczyk, Sadka (2010), "Intraday Patterns in the Cross-Section of Stock Returns" — JF
  - Key: hour-of-day effects survive in panel
- [practitioner] Coinbase research, "Hour of day effects in BTC perpetuals" (2024)
  - Key: vol clusters near US open and 8h funding cycles

## Mechanism

Funding settlement at 00/08/16 UTC creates predictable rebalance flows.
US equity open (~13:30 UTC) imports macro vol. Late Asia (~03 UTC) is
typically quiet and mean-reverting. A signal restricted to high-information
hours reduces sample but raises Sharpe-per-trade.

## Applicability check

- Required data fields: timestamp, close
- Required bar type: TIME
- Universe restriction: any
- Fee headroom: trades cluster by design — use selective windows to keep PF up

## Verdict

Layer time-of-day on top of any directional signal. Risk: overfit to
specific UTC hours; mitigate with broad window blocks (3h chunks).
