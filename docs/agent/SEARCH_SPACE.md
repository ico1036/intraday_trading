# Alpha Search Space

The alpha generator samples this space for coverage. Do not rank cells by prior
performance during exploration. Prefer cells with low visit counts.

Each alpha writes its chosen cell to `search_cell.json`.

## Required Axes

| axis | values |
|---|---|
| `bar_domain` | `TIME`, `VOLUME`, `DOLLAR`, `TICK` |
| `signal_family` | `momentum`, `reversal`, `volatility`, `volume_pressure`, `dispersion`, `correlation_break`, `lead_lag`, `funding`, `regime_transition` |
| `feature_set` | `return`, `vwap_gap`, `volume_imbalance`, `range_expansion`, `realized_vol`, `cross_rank`, `pair_spread`, `trend_state` |
| `normalization` | `raw`, `z_score`, `percentile`, `rolling_rank`, `ewma_residual` |
| `horizon` | `ultra_short`, `intraday`, `session`, `multi_day` |
| `entry_logic` | `threshold`, `rank_top_bottom`, `breakout`, `mean_reversion`, `state_transition` |
| `exit_logic` | `time_stop`, `signal_flip`, `trailing`, `vol_stop`, `neutral_zone` |
| `sizing` | `fixed`, `equal_weight`, `inverse_vol`, `confidence_scaled` |
| `universe` | `single`, `pair`, `basket_topk` |

## Example

```json
{
  "bar_domain": "VOLUME",
  "signal_family": "lead_lag",
  "feature_set": "cross_rank",
  "normalization": "rolling_rank",
  "horizon": "intraday",
  "entry_logic": "rank_top_bottom",
  "exit_logic": "signal_flip",
  "sizing": "equal_weight",
  "universe": "basket_topk"
}
```

## Exploration Rules

- A new alpha should differ from recent alphas on at least three axes.
- If a cell is already visited, prefer an unvisited cell.
- If every direct cell is visited, choose the lowest-count combination by
  `(signal_family, feature_set, normalization, horizon, universe)`.
- Use metrics only after exploration, during selection or composite
  construction.
