---
topic: xs_daily_momentum
status: open
hypothesis: "On a daily rebalance cadence, ranking liquid USDT-M futures by their trailing 24h log return and going long the top while shorting the bottom yields a positive risk-adjusted return after fees on a 7-symbol panel."
data_required: "1m close (only end-of-window prices used)"
applicability: "Liquid majors; long/short cross-section; daily rebalance"
date_created: 2026-05-09
last_updated: 2026-05-09
linked_alphas: []
---

## Sources

- [academic] Asness, Moskowitz, Pedersen (2013) "Value and Momentum Everywhere", J. Finance.
  - Key: cross-sectional momentum is robust at monthly horizon in equities and commodities; analogous effect appears on shorter horizons in crypto due to faster narrative turnover.
- [practitioner] Bianchi, Dimpfl, Yarovaya (2021) "On the persistence of cryptocurrency returns".
  - Key: short-horizon momentum continuation persists in liquid majors after costs.

## Mechanism

Crypto return drivers — narrative flow, leveraged positioning, and reflexive stop cascades — operate on hour-to-day scales. The strongest 24h gainer tends to attract continued retail and momentum-fund flow for at least another day, while the worst loser sees forced deleveraging continue. Daily rebalance is rare enough that round-trip fees stay below the signal magnitude.

## Applicability check

- Required data fields: close
- Required bar type: TIME 1m (1440 bars = 24h)
- Universe restriction: 5+ symbols for stable cross-section
- Fee headroom: at 0.05% taker per side, daily rebalance with ~2 leg turns per day produces ~5–10x turnover over 3 months — well below typical signal magnitude

## Verdict

The cleanest test of the cross-sectional momentum effect at 1m bars without overtrading. Distinct from the intraday variant (is_001) which failed via fee drag at 5-bar rebalance. Worth attempting under default fee assumptions.
