---
topic: xs_daily_reversal
status: open
hypothesis: "On a daily rebalance cadence in liquid USDT-M futures, the worst trailing-24h performer outperforms the best over the next day on average — overshoot mean-reversion dominates short-horizon continuation when realized volatility is elevated."
data_required: "1m close (only end-of-window prices used)"
applicability: "Liquid majors; long/short cross-section; daily rebalance"
date_created: 2026-05-09
last_updated: 2026-05-09
linked_alphas: []
---

## Sources

- [academic] Da, Liu, Schaumburg (2014) "A closer look at the short-term return reversal", Management Science.
  - Key: short-horizon return reversal is strongest for high-volatility, retail-dominated assets — characteristics shared by crypto majors.
- [academic] Conrad, Kaul (1998) "An anatomy of trading strategies".
  - Key: reversal at 1-day to 1-week horizon delivers significant alpha in cross-section, distinct from longer-horizon momentum.

## Mechanism

Crypto retail flow chases yesterday's winner and dumps yesterday's loser, producing systematic overshoot. When liquidity provision is supplied by market makers and quant funds, they earn the spread by leaning against the herd: buy the panicked loser, sell the chased winner. On a basket of 7 highly correlated majors, this cross-section reversal is more reliable than naive XS momentum at this horizon.

## Applicability check

- Required data fields: close
- Required bar type: TIME 1m (1440 bars = 24h)
- Universe restriction: 5+ symbols for stable cross-section
- Fee headroom: same low-turnover daily rebalance as the momentum variant; round-trip fee drag remains small versus typical 1-day return dispersion across the basket

## Verdict

Companion test to xs_daily_momentum. The two are *direction-opposite* signals on the same data, separated by their idea_family. Whichever has positive Sharpe in IS implies the prevailing micro-structure regime; both being near zero would indicate cross-section uninformative at this horizon.
