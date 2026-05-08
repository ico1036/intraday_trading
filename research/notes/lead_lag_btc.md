---
topic: lead_lag_btc
status: open
hypothesis: "BTC return innovations lead alt-coin returns at the 1-5 minute horizon; alts mechanically catch up after a BTC move."
data_required: "Synchronous 1m closes for BTCUSDT and alt symbols."
applicability: "Pair / basket alphas: trade alt direction = sign(BTC lagged return)."
date_created: 2026-05-08
last_updated: 2026-05-08
linked_alphas: []
---

## Sources

- [academic] Lo & MacKinlay (1990), "An Econometric Analysis of Nonsynchronous Trading"
  - Key: lead-lag from differential trading intensity
- [practitioner] Kaiko Research, "BTC dominance lead-lag in crypto perpetuals" (2023)
  - Key: 60-180s lag from BTC to mid-cap alts is empirically stable

## Mechanism

BTC is the de facto liquidity hub in crypto. Information shocks (macro,
funding, ETF flow) hit BTC first. Market-makers in alt perps quote relative
to BTC; informed flow pushes BTC, then alts catch up as quote-revision
delays decay. The lag is measurable and small but persistent in liquid alts.

## Applicability check

- Required data fields: close (synchronous)
- Required bar type: TIME (60s)
- Universe restriction: BTCUSDT must be present; alts as targets
- Fee headroom: signal magnitude is small per bar → must batch (rebalance every 5-15m)

## Verdict

High-frequency edge but fragile to fees. Use with rebalance ≥ 5m.
