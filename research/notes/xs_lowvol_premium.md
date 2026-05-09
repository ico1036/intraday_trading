---
topic: xs_lowvol_premium
status: open
hypothesis: "Cross-section low-vol anomaly: long the basket's lowest-realized-vol symbols, short the highest. Weekly rebalance."
data_required: "1m close"
applicability: "Liquid majors; long/short cross-section"
date_created: 2026-05-09
last_updated: 2026-05-09
linked_alphas: []
---

## Mechanism

Documented across asset classes: low-vol assets earn higher risk-adjusted returns than predicted by CAPM (Frazzini & Pedersen 2014, "Betting against beta"). In crypto majors, short the noisy gainer / long the calm low-vol asset is a market-neutral bet. Distinct cell: transform=ewma_residual? Actually rolling_rank fits — rank by realized vol.
