---
topic: two_bar_reversal_fade
status: open
hypothesis: "After two consecutive same-direction bars, the third bar's same-direction continuation is faded — short-term exhaustion."
data_required: "close prices."
applicability: "Per-symbol; SHORT after 2 up bars when the third confirms; LONG after 2 down + confirm. Hold until opposite pattern."
date_created: 2026-05-08
last_invariant: 2026-05-08
linked_alphas: []
---

## Sources

- [practitioner] Larry Williams (1988), "The Right Stock at the Right Time"
  - Key: 2-down or 2-up consecutive close pattern is a textbook exhaustion signal
- [practitioner] is_023, is_028 internal — same fade-extreme pattern works at session OR / BB extreme

## Mechanism

Two consecutive same-direction bars indicate momentum but also typically
mark a short-term overreaction. The third bar that confirms the direction
is often the exhaustion peak. Fading captures the snap-back.

## Applicability check

- Required data fields: close
- Required bar type: TIME
- Universe restriction: any
- Fee headroom: very common pattern → may need stricter filters

## Verdict

Distinct family. Sparse trigger if combined with magnitude filter.
