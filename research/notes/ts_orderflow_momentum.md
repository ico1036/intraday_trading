---
topic: ts_orderflow_momentum
status: open
hypothesis: "On a per-symbol basis, persistent taker-buy aggression (positive cumulative signed volume over the past several hours) predicts continuation of the underlying price drift on the next short horizon."
data_required: "1m candles with taker_buy_volume to derive signed volume per bar"
applicability: "Liquid USDT-M futures; time-series signal applied independently per symbol"
date_created: 2026-05-09
last_updated: 2026-05-09
linked_alphas: []
---

## Sources

- [academic] Easley, López de Prado, O'Hara (2012) "The Volume Clock: Insights into the High Frequency Paradigm".
  - Key: Order-flow imbalance accumulates information faster than price; price typically follows aggregated taker-buy intensity with a short lag.
- [practitioner] Hasbrouck (2007) "Empirical Market Microstructure", chapter on price impact of signed flow.
  - Key: persistent signed flow induces lasting price moves through inventory and information channels.

## Mechanism

Aggressive market-buy flow consumes resting asks; market-sell flow consumes resting bids. When this imbalance persists over several hours rather than seconds, it signals informed positioning rather than noise. Inventory-bearing market makers must rehedge, which propagates the move. The signal is intrinsically per-symbol (time-series) — different from the cross-sectional CVD ranking already implemented in is_002 which compares symbols against each other.

## Applicability check

- Required data fields: close, volume, volume_imbalance (or buy_volume + sell_volume)
- Required bar type: TIME 1m
- Universe restriction: works per-symbol; basket_full simply applies independently
- Fee headroom: rebalancing every ~30 bars at full position keeps round-trip fees below typical signal magnitude

## Verdict

Different signal generation than the cross-section CVD alpha because each symbol is judged against its own history; correlation with XS-CVD should be moderate but not collinear. Worth attempting at 0.20% taker fee.
