# Framework limitations

This document is loaded by the v2 researcher agent. It lists what the v2
harness **cannot do** so proposals that need these features can be refused
or adapted up-front, not discovered mid-backtest.

The researcher should cite this document when declining a user's request
or when reshaping a proposal to fit.

## Execution model

- **Tick data only.** No L2 orderbook replay. `MarketState.spread` and
  `spread_bps` are always 0. Strategies that need true bid/ask dynamics
  are not supported.
- **Fees are binary (maker / taker).** Values come from the backtest
  config; there is no fee schedule per volume tier or maker rebate
  adjustments per exchange.
- **Slippage is not modelled.** Market orders execute at the last trade
  price. Strategies that depend on slippage sensitivity testing must be
  refused.
- **Funding rates settle on 8h boundaries.** No custom funding calendar.

## Market scope

- **Binance USDT-M perpetual futures.** Other venues (Bybit, Deribit,
  spot-only exchanges) are out of scope.
- **Static symbol list.** The universe is the set of symbols the run's
  data directory contains. Agents cannot add symbols mid-run.
- **No cross-exchange arb.** Even if `basis` is in the feature vocab, it's
  computed against a pre-ingested spot feed — there is no live spot leg.

## Strategy surface

- **Single-leg strategies.** `PortfolioOrder` lets you take multiple
  symbols in one tick, but the orchestrator treats the strategy as one
  unit. True multi-leg hedged execution (delta-neutral, triangular
  arb) is unsupported.
- **No partial fills.** Every order fills entirely or not at all.
- **No order book interaction.** No iceberg orders, no passive quoting,
  no queue position modelling.
- **No position sizing beyond the ``sizing`` axis enum.** Kelly,
  vol-targeted, and fixed are supported; everything else is refused.

## Data scope

- **Historical data horizon** is defined by the ``os_end`` field in
  PLAN.md. The ``oos_clamp`` PreToolUse hook rewrites any dates past
  ``os_end`` to ``os_end`` — agents cannot peek beyond.
- **Feature vocabulary is bounded** (`config/feature_vocab.yaml`).
  Proposing a feature outside the vocab is a framework-limited request
  that must either be refused or reduced to an in-vocab proxy.
- **No alternative data.** No news sentiment, no Twitter signals, no
  on-chain metrics unless already pre-ingested as a feature.

## Temporal scope

- **Intraday only.** Holding periods longer than a few days are
  unsupported; the backtester is designed for minute-to-day horizons.
- **No multi-timeframe joins across exchanges.** All bars come from one
  symbol's tick stream.

## What the agent should refuse

If a user request implies any of the following, the agent must push back
explicitly rather than silently reshape:

- Orderbook-sensitive strategies (market-making, queue-position games).
- Strategies that depend on realistic slippage numbers.
- Strategies with variable fee tiers / volume rebates.
- Cross-exchange or cross-asset strategies.
- Strategies needing alternative data not in `feature_vocab.yaml`.
- Strategies whose holding period is multi-day to multi-week.

## How to refuse

Append to the generated thesis or algorithm_prompt body:

```markdown
## Framework Limitation Refused
| Asked for | Reason it cannot be supported | Reshape (if any) |
|---|---|---|
| <feature> | <bullet from this doc> | <in-scope alternative or none> |
```

If the reshape is acceptable, proceed. If not, emit ``CONCEPT_INVALID``
signal and stop.
