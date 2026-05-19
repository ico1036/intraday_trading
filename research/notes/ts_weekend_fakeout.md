# ts_weekend_fakeout — Monday-open mean reversion of weekend pump

Idea family: `weekend_fakeout`

## Hypothesis (mechanism)

Crypto trades 24/7, but institutional liquidity (market makers, basis
funds, ETF authorized participants) is a Mon–Fri business. Friday's
US close marks the start of a low-quality liquidity window where the
remaining flow is mostly retail.

Over the weekend:

- Retail FOMOs into headline-day winners.
- Thin order books amplify the impact of any directional flow.
- No institutional fade is present to absorb it.

On Monday's UTC bar (= KST 09:00) the institutional algos come back
online. Pumps that lacked real bid support get sold; oversold names
get bid back to neutral. The expected weekend → Monday-open mean
reversion is the trade.

## Signal

Each new daily candle:

1. If `timestamp.weekday() != 0` (not Monday), do nothing (let the
   weekend candles accumulate without firing).
2. On the Monday candle:
   - `weekend_ret = close_{Sun} / close_{Thu} - 1` — three-day window
     spanning the full Fri/Sat/Sun candle group.
   - Rank symbols by `weekend_ret`:
     - **short** top half (most pumped over the weekend)
     - **long** bottom half (most beaten down)
   - `reverse=True` flips for symmetry runs.

We hold the basket through the week and only revisit on the next Monday.
Mid-week noise is intentionally ignored: the hypothesis is specifically
about the weekend-vs-Monday flow boundary, not daily mean reversion.

## Why this is a different cell

- Rebalance horizon is **weekly**, not daily. Distinct cell from
  every prior xs_* alpha in `run_2026_05_c`, which all rebalance daily.
- The `idea_family` ``weekend_fakeout`` encodes a calendar-conditional
  signal rather than a continuous rank — closer to a regime trigger
  than a steady-state factor.

## Search-space cell

- `bar`: `TIME`
- `transform`: `rolling_rank`
- `horizon`: `session` (weekly)
- `universe`: `basket_full`
- `exit`: `signal_flip`
- `idea_family`: `weekend_fakeout`

## Sample size / fee discipline

- IS spans ~123 weeks → about `2 × half_basket × 123` legs.
  For the 7-coin universe ≈ ~740 closed legs over IS. Above the 100-
  trade gate.
- Turnover: full basket swap each week → roughly weekly gross 2×.
  Over 123 weeks → ~246× — above the 10× gate.
- Per-leg edge must clear 10 bps round-trip; weekly trades carry less
  fee drag than daily strategies.

## Anti-patterns avoided

- *Tuning the day filter to "Sun close → Mon open"* — the cell here is
  Mon-open candle, which on daily bars is well-defined and aligns with
  the canonical institutional return point.
- *Conditioning on US calendar holidays* — too few events on IS to fit
  without overfitting; the pure day-of-week filter is the pre-registered
  form.

## References

- General market-microstructure literature on Monday-effect /
  weekend-effect (French 1980, Lakonishok & Smidt 1988); the latest
  is well-documented in equities but unverified in crypto.
- User-supplied crypto-adapted hypothesis (2026-05-18) noting CME-aligned
  institutional return on Mondays as the structural reason.
