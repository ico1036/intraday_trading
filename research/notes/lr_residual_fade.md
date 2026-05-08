---
topic: lr_residual_fade
status: open
hypothesis: "Per-symbol residual from a rolling linear regression over the last N bars mean-reverts; fade extremes."
data_required: "close prices"
applicability: "Per-symbol; SHORT when price > regression+k·sigma, LONG when price < regression-k·sigma"
date_created: 2026-05-08
last_updated: 2026-05-08
linked_alphas: []
---

## Sources

- [academic] Pole, West, Harrison (1994), "Applied Bayesian Forecasting and Time Series Analysis"
  - Key: detrending via regression captures secular drift; residual is mean-reverting
- [practitioner] Ehlers (1992), "Mathematical Foundations of Technical Analysis"
  - Key: linear regression channels are textbook fade signals

## Mechanism

Linear regression projects the trend forward; instantaneous price minus
projection yields a stationary residual. Extremes of this residual reflect
short-term overreaction beyond trend. Fading extracts the reversion.

## Applicability check

- Required data fields: close
- Required bar type: TIME
- Universe restriction: any
- Fee headroom: tune k for trigger frequency

## Verdict

Distinct family from BB-fade (linear instead of mean) and orb_fade.
