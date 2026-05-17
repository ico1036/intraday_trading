# xs_volume_rank — daily volume-rank cross-section

## Thesis

At daily frequency on a broad USDT-M perp universe (~430 coins), use the
previous-day **quote volume** (= USDT-denominated dollar volume) as a
liquidity / attention proxy. Take a dollar-neutral L/S basket:

- **Long** the top 50% (high prior-day volume)
- **Short** the bottom 50% (low prior-day volume)
- Equal weight within each leg, daily rebalance

The premise is that volume rank carries information about the next bar's
realised flow. Two competing readings, both worth a single backtest:

1. **Continuation** — names attracting the most flow today continue to
   attract flow tomorrow (the implemented direction).
2. **Mean reversion** — extreme prior-day flow exhausts and the low-flow
   names catch up. The strategy with sign-flipped weights tests this.

The actual sign of the realised edge is an empirical question; this note
just declares the experiment.

## Signal

For each daily bar:

    score(s, t) = volume(s, t) × vwap(s, t)     # = quote_volume

Cross-sectional rank → halves → top 50% LONG, bottom 50% SHORT.
``per_leg_weight = min(max_weight, 0.5 / half_size)`` keeps gross ≈ 1.0
regardless of universe size.

## Why it matters for this project

The current run universe is 7 majors. This is the first run that exercises
the pipeline at **basket_full × ~500 coins × daily** — a stress test of
the framework and a candidate component for the broader ensemble. As a
breadth probe rather than a refined alpha, individual-alpha metrics are
secondary to:

- whether the framework can backtest at this scale
- whether the resulting signal is correlated with the existing 7-coin
  alpha pool (independent → useful as ensemble member; not independent →
  evidence the basket is just majors-momentum repackaged)

## References

- *Liquidity and the Cross-Section of Returns* (Pastor & Stambaugh, 2003) —
  classic liquidity-as-priced-factor result on equities; crypto analogue
  remains an open empirical question.
- Internal: contrast with `ts_donchian_*` family (time-series momentum,
  same horizon, 7-coin) for independence check via IC correlation.
