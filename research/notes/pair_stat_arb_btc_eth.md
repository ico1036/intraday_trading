---
topic: pair_stat_arb_btc_eth
status: open
hypothesis: "The log spread log(BTC) - log(ETH) is mean-reverting on intraday horizons (1-3 days). When the rolling z-score exceeds ±2σ, take the mean-reverting position (long underperformer, short outperformer) at equal notional → dollar-neutral. Time-stop after 3 days."
data_required: "1m close for BTCUSDT and ETHUSDT"
applicability: "Pair only; BTC + ETH are the most liquid and most cointegrated pair in the basket. Should produce signals uncorrelated with directional trend-following."
date_created: 2026-05-11
last_updated: 2026-05-11
linked_alphas: []
---

## Sources

- Gatev, Goetzmann, Rouwenhorst (2006) "Pairs Trading: Performance of a Relative-Value Arbitrage Rule", Review of Financial Studies. Classic pair stat-arb formulation.
- Avellaneda, Lee (2010) "Statistical arbitrage in the U.S. equities market" — z-score thresholding and OU dynamics for spread.

## Mechanism

BTC and ETH are price-correlated but not perfectly cointegrated. Their log spread oscillates around a slow-moving mean driven by relative narrative flow. Dollar-neutral pair trade isolates the relative-value signal and removes directional crypto-market exposure → returns uncorrelated with the trend-following Donchian alphas.

## Applicability check

- Required data fields: close
- Required bar type: TIME 1m
- Universe restriction: pair (BTC + ETH); other symbols held flat
- Fee headroom: at 0.20% taker, round-trip 0.40%. Entry threshold ±2σ on a 1-day rolling window gives expected per-trade move ~1-3%, leaving fee headroom.

## Verdict

Should provide a distinct return stream uncorrelated with the trend family
(which dominates the current alpha pool). Even if Sharpe is modest, the
diversification benefit in an ensemble is significant.
