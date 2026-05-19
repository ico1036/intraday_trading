# xs_max_lottery — Lottery-ticket / MAX factor (cross-sectional)

Idea family: `lottery_max`

## Hypothesis (mechanism, not chart-reading)

Bali, Cakici & Whitelaw (2011) showed equities with the highest single-day
return over the past month ("lottery-like" stocks) earn *lower* future
returns than otherwise-similar names. The mechanism is behavioural: retail
investors overpay for positive-skew payoffs (lottery-ticket preference),
which inflates the current price and depresses forward expected return.

In crypto:

- Retail concentration is even higher than in equities.
- Daily-bar payoff distributions are heavier-tailed; "어제 100% 빔" coins
  are visible to everyone, immediately attracting FOMO flow.
- That flow is forced to lift the offer (no underwriter capacity), so the
  premium gets paid on top of an already-extended price.

Forward expectation: the cross-sectional spread between *highest single-day
return* names and *flattest* names is short the former, long the latter.

## Signal

For each symbol at the start of day `t`:

```
MAX_t(N) = max(daily_return_{t-N..t-1})
```

with `N = 14` daily bars (matches Bali et al. 2011 month-window in a
faster-rotating market).

Cross-sectional rank: short top half by `MAX`, long bottom half.
Reverse switch left for symmetry runs.

## Why this is a different cell

`xs_volume_rank` (already in archive) ranks by total quote-volume —
attention proxy. `xs_max_lottery` ranks by *highest single-day return* —
skew proxy. The two are correlated but not identical: a coin can have
high volume without a "lottery day" and vice versa. The orthogonal
information is the *peak* of the daily-return distribution, not the
volume mass.

## Search-space cell

- `bar`: `TIME` (daily close)
- `transform`: `rolling_rank` (MAX over N days, then cross-sectional rank)
- `horizon`: `multi_day` (lookback 14d, holding 1d)
- `universe`: `basket_full` (whole run universe)
- `exit`: `signal_flip` (next-day rebalance)
- `idea_family`: `lottery_max`

## Sample size / fee discipline

- Run-universe with daily rebalance → roughly `2 × half_basket × N_days`
  closed legs.
- For the run_2026_05_c universe (7 symbols) IS ≈ 845 days → ~5,900 legs.
  Comfortably above the 100-trade quality gate.
- Daily turnover ≈ 2× gross (open + close) → above the 10x gate over IS.
- Per-leg edge must clear 2× taker (0.05% per side) ≈ 10 bps to be real.

## Known anti-patterns to avoid

- *Tuning the lookback after seeing IS*. N=14 is pre-registered here.
- *Mixing in 1h bars* — that's a different cell, not a refinement.
- *Equal-weight by name vs cap-weight*: this run uses equal-weight by
  signal half — keep it that way, the framework expects target weights.

## References

- Bali, Cakici, Whitelaw (2011), "Maxing Out: Stocks as Lotteries and
  the Cross-Section of Expected Returns", JFE.
- User-provided crypto-adapted hypothesis (2026-05-18) — adds retail-skew
  channel and FOMO-on-headline mechanism to the original framework.
