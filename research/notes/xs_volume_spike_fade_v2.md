# xs_volume_spike_fade_v2

## Thesis

Crypto markets contain a large amount of promotional and manipulative flow.
An abrupt jump in quote volume can represent temporary attention, wash-like
activity, or exit liquidity rather than durable demand. The alpha shorts
liquid names with abnormal prior-day volume spikes unless price action shows
healthy growth.

The strategy should not blindly short all high-volume names:

- extremely low-liquidity names are excluded because their volume spikes are
  noisy and expensive to trade;
- strong positive multi-day price confirmation is treated as healthy interest
  and excluded from the short book;
- the long leg is built from liquid names with positive price confirmation and
  non-extreme volume, preserving dollar neutrality.

## Signal

For each symbol, keep rolling daily close and quote-volume histories.

```text
volume_ratio = latest_quote_volume / median(previous_quote_volume_window)
momentum     = latest_close / close_n_days_ago - 1
```

Eligible universe:

- enough quote-volume and close history;
- median quote volume above the liquidity floor;
- latest quote volume above the one-day liquidity floor.

Short candidates:

- `volume_ratio >= min_spike_ratio`;
- `momentum < healthy_return_threshold`.

Long candidates:

- positive momentum;
- non-extreme volume ratio;
- not already in the short basket.

Weights are equal within each leg. The strategy trades the same number of long
and short names and normalizes each leg to 0.5 gross exposure, so the target is
dollar neutral.

