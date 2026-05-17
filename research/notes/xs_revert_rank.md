---
topic: xs_revert_rank
status: open
hypothesis: "Cross-sectional reversal — long bottom-K (recent losers), short top-K (recent winners) — at multi-day horizons captures mean-reversion across crypto majors. Dollar-neutral by construction; orthogonal direction to xs_mom_rank."
data_required: "TIME 60s bars on the run universe."
applicability: "Cross-sectional reversal, multi-day horizon, basket_topk."
date_created: 2026-05-10
last_updated: 2026-05-10
linked_alphas: []
---

## Sources

- [academic] DeBondt & Thaler (1985), "Does the stock market overreact?" *Journal of Finance* 40(3).
  - Key: Long-horizon reversals after extreme returns; the inverse signal of momentum at the right horizon.
- [crypto] Multiple weekly-reversal studies on liquid crypto pairs (e.g., Caporale et al. 2018).
  - Key: Short-term reversals in crypto majors are documented at 1-3 week horizons.

## Mechanism

Each rebalance: compute past-``lookback_bars`` log return per symbol. Rank ascending. Long bottom-K, short top-K, equal weight ≤ ``max_weight`` per leg. Hold until next rebalance.

## Applicability check

- Same lookback range as xs_mom_rank but inverted direction.
- Distinct cell signature (idea_family ≠ xs_mom_rank), so governance saturation OK.

## Verdict

Open; complement to xs_mom_rank — only one of the two should win at any given horizon, but composite of both with sign-discriminating gate is interesting later.
