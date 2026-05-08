---
topic: rsi_extreme_fade
status: open
hypothesis: "RSI > 70 (overbought) and RSI < 30 (oversold) extremes mean-revert in crypto perp at the intraday-to-multi-hour horizon."
data_required: "close prices for return-based RSI computation."
applicability: "Per-symbol; SHORT on RSI > 70, LONG on RSI < 30; hold until opposite extreme."
date_created: 2026-05-08
last_updated: 2026-05-08
linked_alphas: []
---

## Sources

- [practitioner] J. Welles Wilder Jr. (1978), original RSI
  - Key: 14-period RSI with 30/70 thresholds is a textbook overbought/oversold gauge
- [academic] Brock, Lakonishok, LeBaron (1992), "Simple Technical Trading Rules and the Stochastic Properties of Stock Returns" — JF
  - Key: oscillator-based contrarian rules generated abnormal returns historically

## Mechanism

RSI compresses recent gain/loss into a bounded oscillator. Extremes signal
exhausted directional flow that often reverts as inventory absorbs the move.
Combined with signal-flip exit (RSI returns to opposite extreme), the
strategy captures the full reversion span without micro-managing entries.

## Applicability check

- Required data fields: close
- Required bar type: TIME
- Universe restriction: any
- Fee headroom: extremes occur < 5% of bars → naturally sparse triggers

## Verdict

Standard contrarian oscillator, fits the "sparse extreme + signal-flip"
template that worked for is_023.
