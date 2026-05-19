# xs_amihud_illiq — Amihud illiquidity factor (cross-sectional)

Idea family: `amihud_illiq`

## Hypothesis (mechanism, not chart-reading)

Amihud (2002) introduced the illiquidity measure
`ILLIQ_t = |return_t| / dollar_volume_t`. Large ILLIQ means a small dollar
flow moved the price a lot — i.e. the book was thin. Small ILLIQ means
real money traded without moving the price — i.e. the book absorbed
flow.

In crypto:

- Top-ILLIQ + positive return = "빈집 펌프" — a thin book pumped by
  small flow. The pumper has no buyback support; first selling pressure
  collapses it.
- Bottom-ILLIQ = real participants absorbing flow at this level. Persistent
  supply/demand on a deep book.

Forward expectation: short the top-ILLIQ basket (fragile pumps revert),
long the bottom-ILLIQ basket (real bids hold).

## Signal

For each symbol at the start of day `t`:

```
ret_{t-1}      = (close_{t-1} / close_{t-2}) - 1     # yesterday's return
illiq_{t-1}    = abs(ret_{t-1}) / quote_volume_{t-1} # Amihud
score          = illiq_{t-1}                         # rank key
```

Cross-section rank by `score` (descending = most illiquid first):

- short top half (high ILLIQ — thin pumps)
- long bottom half (low ILLIQ — absorbed flow)
- `reverse=True` flips for symmetry runs

We do NOT layer the `+/-` return sign filter in this v1: the rank-only
form is a strict superset of the "MAX-illiq + positive return" version
in expectation, and the sign filter would force us to evaluate two
hypotheses at once. The sign-conditioned variant is a *different cell*
worth its own attempt later.

## Why this is a different cell

- `xs_volume_rank`: ranks by total quote_volume (attention proxy).
- `xs_max_lottery`: ranks by max single-day return (skew proxy).
- `xs_amihud_illiq`: ranks by *return-per-dollar* (book-depth proxy).

The three proxies are correlated but capture different microstructure
features — volume mass, payoff skew, and price-impact slope respectively.

## Search-space cell

- `bar`: `TIME` (daily close)
- `transform`: `rolling_rank` (Amihud over 1 day, then cross-sectional rank)
- `horizon`: `multi_day` (lookback 1d return, holding 1d)
- `universe`: `basket_full`
- `exit`: `signal_flip`
- `idea_family`: `amihud_illiq`

## Sample size / fee discipline

- IS ~845 days × `half_basket × 2` legs per day ≈ same scale as
  `xs_max_lottery` and `xs_volume_rank` — quality gates clear.
- Per-leg edge must beat the 10 bps round-trip fee floor.

## References

- Amihud, Y. (2002), "Illiquidity and stock returns: cross-section and
  time-series effects", JFM.
- User-supplied hypothesis (2026-05-18) — adapts price-impact ratio to
  daily-rebalanced crypto basket.
