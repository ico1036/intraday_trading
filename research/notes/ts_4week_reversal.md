---
topic: ts_4week_reversal
status: open
hypothesis: "Per-symbol monthly mean reversion: extreme 4-week moves revert at the next biweekly checkpoint."
data_required: "1m close"
applicability: "Liquid majors; per-symbol; biweekly rebalance"
date_created: 2026-05-09
last_updated: 2026-05-09
linked_alphas: []
---

## Mechanism

Direction-opposite of ts_4week_momentum. If monthly returns overshoot driven by reflexive trend chasing, the next 2 weeks tend to revert. Same low-turnover cadence keeps fee drag minimal.

## Verdict

Companion test. Whichever direction has positive Sharpe identifies the dominant force at this horizon during 2022-2024 cycle.
