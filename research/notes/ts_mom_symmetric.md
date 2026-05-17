---
topic: ts_mom_symmetric
status: open
hypothesis: "Per-symbol time-series momentum with both directions: long if past-N-day return > +threshold, short if < −threshold. Each symbol independent; the universe is held only when its own signal fires. Different from Donchian breakouts (which use channel highs/lows); this uses raw return magnitude."
data_required: "TIME 60s bars on the run universe."
applicability: "Time-series momentum, multi-day horizon, basket_full universe, signal_flip exit."
date_created: 2026-05-10
last_updated: 2026-05-10
linked_alphas: []
---

## Sources

- [academic] Moskowitz, Ooi & Pedersen (2012), "Time series momentum," *JFE* 104(2).
  - Key: TS-mom is canonically symmetric — sign of past return predicts sign of future return. Long-only truncation halves Sharpe.
- [practitioner] CTA literature on threshold-based directional filters.

## Mechanism

Each rebalance bar: for every symbol, compute past-``lookback_bars`` log return. If r > +threshold → target LONG. If r < −threshold → target SHORT. Else flat. Per-symbol max-weight bounds gross. Re-evaluated every rebalance; effectively signal_flip exit.

## Applicability check

- Distinct from Donchian breakouts (continuous return-magnitude signal vs discrete channel-cross).
- Threshold > 0 prevents oscillation around r ≈ 0 (whipsaw guard).

## Verdict

Open; symmetric TS-mom is the cleanest L/S baseline and the natural counterpart of the long_persist family.
