---
topic: pivot_fade
status: open
hypothesis: "Daily pivot points (PP, R1, S1) define support/resistance levels at which intraday price tends to FADE — closes at R1 are reversed, closes at S1 are bought."
data_required: "previous-day high, low, close."
applicability: "Per-symbol; SHORT close > R1, LONG close < S1; hold until close to opposite level (signal_flip)."
date_created: 2026-05-08
last_updated: 2026-05-08
linked_alphas: []
---

## Sources

- [practitioner] Henry Wheeler Chase (1934), original pivot point methodology used by floor traders
  - Key: pivot levels = "magnetic" levels at which intraday price reacts
- [academic] Thomas (2007), "Intraday Pattern Analysis" — JoT
  - Key: pivot-based reversal rules show statistically significant intraday edge

## Mechanism

PP = (H + L + C) / 3 from prior session. R1 = 2·PP - L; S1 = 2·PP - H.
These derived levels capture typical intraday extremes. Algorithmic traders
and market-makers anchor stops/limits to them. Touches of R1 (S1) often
mark intraday tops (bottoms).

## Applicability check

- Required data fields: high, low, close
- Required bar type: TIME
- Universe restriction: any
- Fee headroom: triggers ~0-2 per session per symbol → naturally sparse

## Verdict

Same "fade extreme; hold" template as is_023. Distinct family name.
