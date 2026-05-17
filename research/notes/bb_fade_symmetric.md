---
topic: bb_fade_symmetric
status: open
hypothesis: "BB-band fade symmetric — long when z-score < -τ, short when z-score > τ. Hold N bars. Z-score from rolling close window."
data_required: "TIME 60s bars on run universe."
applicability: "Mean-reversion / fade family — designed to be uncorrelated with Donchian/TS-mom trend cluster."
date_created: 2026-05-12
linked_alphas: []
---

## Mechanism

BB-band fade symmetric — long when z-score < -τ, short when z-score > τ. Hold N bars. Z-score from rolling close window.

## Applicability check

- Designed specifically to be uncorrelated with the existing trend-following cluster.
- IS may underperform if 2022-2024 was strongly trending — but for composite use the
  hypothesis is that fade signals provide diversification even if standalone IS Sharpe
  is modest.

## Verdict

Open. Backtest required.
