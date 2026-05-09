---
topic: xs_return_momentum_1h
status: open
hypothesis: "Within a small basket of liquid USDT-M futures, the symbol with the strongest 1h return tends to continue outperforming the weakest over the next short horizon, after costs."
data_required: "1m close prices, 7-symbol panel"
applicability: "Liquid majors only; 1m bars; long/short cross-section"
date_created: 2026-05-09
last_updated: 2026-05-09
linked_alphas: []
---

## Sources

- [academic] Asness, Moskowitz, Pedersen (2013) "Value and Momentum Everywhere", J. Finance.
  - Key: cross-sectional momentum is a robust effect across asset classes including currencies and commodities; intraday extension is plausible for liquid crypto futures.
- [practitioner] Hudson & Thames blog post: "Crypto cross-sectional momentum" (general literature).
  - Key: in crypto, XS momentum has historically shown faster decay than equities, so shorter rebalancing horizons (15m–1h) outperform daily rebalancing.

## Mechanism

Liquid crypto futures move in waves driven by leveraged-trader positioning, correlated narrative flow, and stop-cascade reflexivity. When one symbol moves strongly higher relative to the others over the past hour, marginal flow tends to chase the leader for at least the next several minutes — a slow-moving herd effect. Conversely the laggard is sold by latecomers. Rebalancing every few bars captures the residual continuation while avoiding holding through noise.

## Applicability check

- Required data fields: close (volume optional)
- Required bar type: TIME 1m
- Universe restriction: basket of 5+ symbols for stable cross-section
- Fee headroom: rebalance every ~5 bars at ~10bps round-trip yields manageable cost if signal magnitude exceeds ~15bps

## Verdict

Plausible at 0.20% taker on 7-symbol 1m universe if rebalancing is throttled (>=5 bars between rebalances) and only top/bottom cross-section legs are held. Single-symbol overfit is unlikely because the signal is pure relative ranking.
