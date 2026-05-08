---
topic: vol_filtered_meanrev
status: open
hypothesis: "Short-horizon mean reversion strengthens when realized volatility is elevated (high-vol regimes have more liquidity-driven overshoots than information-driven moves)."
data_required: "close prices for return + rv computation"
applicability: "Per-symbol reversal triggered ONLY when trailing rv > threshold; otherwise stay flat"
date_created: 2026-05-08
last_updated: 2026-05-08
linked_alphas: []
---

## Sources

- [academic] Nagel (2012), "Evaporating Liquidity" — RFS
  - Key: short-term reversal profits are concentrated in high-volatility regimes
- [academic] Avramov, Chordia, Goyal (2006), "Liquidity and Autocorrelations in Individual Stock Returns" — JF
  - Key: reversal strength scales with proxies for liquidity stress

## Mechanism

In low-vol regimes most price moves carry signal — fading them is a losing
bet. In high-vol regimes, sharp moves are more often forced/liquidity flow
than information; these revert as inventory normalizes. Conditioning the
reversal on a vol filter cuts trade count where the signal is weakest and
keeps it where the signal is strongest.

## Applicability check

- Required data fields: close
- Required bar type: TIME
- Universe restriction: any
- Fee headroom: filter cuts ~50% of trade attempts → fee-friendly

## Verdict

Combines ts_burst_revert with a regime gate. Different idea_family.
