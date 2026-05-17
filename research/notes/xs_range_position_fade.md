---
topic: xs_range_position_fade
status: open
hypothesis: "Cross-section range position fade — rank symbols by (close - mid_range) / half_range. Long bottom-K (oversold relative to peers), short top-K (overbought relative to peers)."
data_required: "TIME 60s bars on run universe."
applicability: "Mean-reversion / fade family — designed to be uncorrelated with Donchian/TS-mom trend cluster."
date_created: 2026-05-12
linked_alphas: []
---

## Mechanism

Cross-section range position fade — rank symbols by (close - mid_range) / half_range. Long bottom-K (oversold relative to peers), short top-K (overbought relative to peers).

## Applicability check

- Designed specifically to be uncorrelated with the existing trend-following cluster.
- IS may underperform if 2022-2024 was strongly trending — but for composite use the
  hypothesis is that fade signals provide diversification even if standalone IS Sharpe
  is modest.

## Verdict

Open. Backtest required.
