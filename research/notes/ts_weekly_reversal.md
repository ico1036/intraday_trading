---
topic: ts_weekly_reversal
status: open
hypothesis: "Per-symbol weekly mean-reversion: when a symbol's 7-day log return is large in magnitude relative to its own 4-week distribution, the next week tends to revert toward the mean."
data_required: "1m close (only end-of-window prices used)"
applicability: "Liquid majors; per-symbol decision; weekly rebalance"
date_created: 2026-05-09
last_updated: 2026-05-09
linked_alphas: []
---

## Sources

- [academic] Lehmann (1990) "Fads, martingales, and market efficiency", QJE.
  - Key: short-horizon return reversal is one of the most robust empirical facts in finance, especially for retail-dominated markets.
- [practitioner] Da, Liu, Schaumburg (2014) "A closer look at the short-term return reversal", Management Science.

## Mechanism

When a symbol drops sharply over a week relative to its own typical movement, panic selling and forced deleveraging often overshoot fundamentals; the next week's return tends to recover. The mechanism mirrors the cross-sectional reversal in xs_daily_reversal but is applied per-symbol so it does not require cross-symbol ranking. Weekly cadence keeps total trades around 170 over 90 days, well below the fee-drag threshold that defeated the daily variants.

## Applicability check

- Required data fields: close
- Required bar type: TIME 1m (10080 bars = 7 days)
- Universe restriction: per-symbol; basket_full
- Fee headroom: same as ts_weekly_momentum

## Verdict

The directional opposite of ts_weekly_momentum. Both are tested; whichever has positive Sharpe IS gives evidence about which structural force dominates at this horizon during 2024 Q3. Direction-opposite of a sibling cell is allowed because the cell vector encodes idea_family, not direction.
