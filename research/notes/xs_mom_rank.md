---
topic: xs_mom_rank
status: open
hypothesis: "Past-N-day return cross-sectional ranking with long top-K / short bottom-K extracts relative strength while netting out market beta. Multi-day rebalance keeps fee drag manageable, distinct from earlier 5-min xs_return_momentum_1h variants that whipsawed."
data_required: "TIME 60s bars on the run universe."
applicability: "Cross-sectional momentum, multi-day horizon, basket_topk."
date_created: 2026-05-10
last_updated: 2026-05-10
linked_alphas: []
---

## Sources

- [academic] Jegadeesh & Titman (1993), "Returns to buying winners and selling losers," *Journal of Finance* 48(1).
  - Key: Cross-sectional 3-12 month momentum (winners minus losers) earns a robust premium across markets.
- [crypto-specific] Liu & Tsyvinski (2021), "Risks and Returns of Cryptocurrency," *Review of Financial Studies* 34(6).
  - Key: Crypto exhibits a momentum factor at weekly horizons.

## Mechanism

Each rebalance: compute past-``lookback_bars`` log return per symbol. Rank descending. Long top-K, short bottom-K, equal weight ≤ ``max_weight`` per leg. Hold until next rebalance.

## Applicability check

- Lessons from prior failures (is_001 xs_return_momentum_1h: −100%, is_002 xs_daily_momentum: −98%):
  - Avoid sub-hour rebalance (whipsaw + fee drag).
  - Use higher entry threshold or rank-based (no z-score noise).
- Multi-day lookback + 1-7d rebalance avoids the failure modes.

## Verdict

Open; past failures were on intraday; multi-day xs-mom on crypto has academic support and is worth a clean test.
