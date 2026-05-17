---
topic: atr_fade_symmetric
status: open
hypothesis: "ATR-channel fade — fade extreme deviations from EMA mean measured in ATR units. Long when price < mean - k·ATR, short when price > mean + k·ATR."
data_required: "TIME 60s bars on run universe."
applicability: "Mean-reversion / fade family — designed to be uncorrelated with Donchian/TS-mom trend cluster."
date_created: 2026-05-12
linked_alphas: []
---

## Mechanism

ATR-channel fade — fade extreme deviations from EMA mean measured in ATR units. Long when price < mean - k·ATR, short when price > mean + k·ATR.

## Applicability check

- Designed specifically to be uncorrelated with the existing trend-following cluster.
- IS may underperform if 2022-2024 was strongly trending — but for composite use the
  hypothesis is that fade signals provide diversification even if standalone IS Sharpe
  is modest.

## Verdict

Open. Backtest required.
