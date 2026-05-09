---
topic: ts_weekly_long_only
status: open
hypothesis: "Restricting the proven weekly TS-momentum signal to long-only trades and exiting via fixed time-stop (1 week) carries a strictly positive risk-adjusted return on the 7-symbol panel under default fees."
data_required: "1m close"
applicability: "Liquid majors; per-symbol decision; weekly entry, time-stop exit"
date_created: 2026-05-09
last_updated: 2026-05-09
linked_alphas: ["is_005_ts_weekly_momentum"]
---

## Sources

- [academic] Asness, Frazzini, Pedersen (2014) "Quality minus junk", AQR.
  - Key: long-only momentum implementations capture most of the alpha while avoiding the path-dependence costs of shorting.
- [practitioner] Hurst, Ooi, Pedersen (2017) "A century of evidence on trend-following investing", AQR.

## Mechanism

is_005 (long-short TS weekly momentum) passed at sharpe 1.52 with 260 trades. A long-only restriction trades only the upward-trending leg, halving the trade count and removing the carry cost of short positions during recoveries. Crypto's structural upward drift over multi-quarter windows (despite Q3 2024's drawdown phase) further favors the long side. Time-stop exit instead of signal-flip enforces a deterministic 1-week hold per entry, which removes the "flip-back-and-forth" portion of trades that contribute fee drag with little PnL.

## Applicability check

- Required data fields: close
- Required bar type: TIME 1m (10080 bars = 7 days)
- Universe restriction: per-symbol; basket_full
- Fee headroom: roughly half of is_005's 260 trades → ~130 trades, well above min_trades=100

## Verdict

Direct structural variant of is_005 (different exit type and direction restriction) — distinct cell. Tests whether the long-side captures the bulk of the working signal.
