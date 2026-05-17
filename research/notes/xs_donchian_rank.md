---
topic: xs_donchian_rank
status: open
hypothesis: "Cross-sectional ranking of symbols by their position within their own Donchian channel ((close − mid) / range) identifies relatively-strong vs relatively-weak coins; long top-K and short bottom-K is dollar-neutral by construction and isolates relative momentum from market beta."
data_required: "TIME 60s bars on the run universe."
applicability: "Cross-sectional alpha on multi-day horizon, basket_topk universe, signal_flip exit."
date_created: 2026-05-10
last_updated: 2026-05-10
linked_alphas: []
---

## Sources

- [academic] Asness, Moskowitz & Pedersen (2013), "Value and momentum everywhere," *Journal of Finance* 68(3).
  - Key: Cross-sectional momentum complements TS-momentum; rank-based long/short is dollar-neutral and earns spread between strong and weak names.
- [practitioner] Carr & Hogan (2006) and assorted CTA notes on channel-position normalization.
  - Key: Normalizing close to its channel range (Donchian z-equivalent) makes signals comparable across symbols of different volatilities.

## Mechanism

Each rebalance bar: for every symbol, compute channel high/low over ``channel_bars`` and signal = (close − (high+low)/2) / max(1e-9, (high−low)/2) ∈ [−1, +1]. Rank signals across the panel. Long top-K symbols, short bottom-K, equal weights. Net Σ weights ≈ 0 (dollar-neutral). Hold until next rebalance.

## Applicability check

- 7-symbol universe → K ∈ {1, 2}, since K=3 would degenerate (only 1 symbol left in middle).
- Multi-day rebal (1d, 3d, 7d) keeps fee drag manageable.

## Verdict

Open; cross-section power on 7 symbols is limited but the dollar-neutral profile should buy diversification against the existing long-only family.
