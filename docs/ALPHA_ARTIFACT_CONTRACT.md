# Alpha Artifact Contract

Purpose: make generated alphas cheap to reuse and combine.

The durable output of an alpha is its target weight time series, not the
strategy source code. Composite strategies should read saved alpha weights,
align timestamps, combine weights, and run one portfolio execution simulation.
They should not rerun every child strategy unless explicitly regenerating an
alpha.

## Run Directory

Every backtest and forward run writes one artifact directory with the same core
files:

```text
<artifact_dir>/
  manifest.json
  weights.parquet
  metrics.json
  summary.json
  summary.csv
  equity_curve.parquet
  trades.parquet
  events.parquet
  report.png                  # optional for forward, required when rendered
```

Forward runs may also keep compatibility files such as `portfolio_nav.parquet`,
but readers must prefer the core files above.

## `weights.parquet`

This is the primary alpha product.

Required columns:

| column | type | meaning |
|---|---|---|
| `timestamp` | datetime | decision time |
| `alpha_id` | string | stable alpha/run identifier |
| `symbol` | string | instrument |
| `target_weight` | float | signed portfolio weight, long positive, short negative |
| `target_notional` | float | signed notional if known |
| `target_qty` | float | signed quantity if known |
| `price` | float | decision/reference price |
| `bar_type` | string | TIME/VOLUME/TICK/DOLLAR when known |
| `bar_size` | float | bar size when known |
| `metadata` | string | JSON object for non-core details |

Rules:

- One row means "after this timestamp, alpha wants this symbol at this target
  weight".
- Missing symbols imply target weight unchanged, not zero.
- Explicit exits are represented with `target_weight = 0`.
- Composite engines combine `target_weight`, then produce their own
  `weights.parquet` under a new `alpha_id`.

## `metrics.json`

Flat top-level metrics used for ranking/filtering:

```json
{
  "profit_factor": 1.2,
  "total_return": 0.04,
  "max_drawdown": -0.08,
  "total_trades": 120,
  "win_rate": 0.53,
  "sharpe": 0.9,
  "per_symbol": {}
}
```

`summary.json` can contain richer run metadata, but `metrics.json` stays flat
so ranking many alphas is cheap.

## Composite Workflow

1. Generate candidate alphas.
2. Backtest each alpha once and persist `weights.parquet`.
3. Filter by `metrics.json`.
4. Build composite weights from saved ledgers:
   - timestamp alignment
   - exposure caps
   - correlation/crowding caps
   - volatility targeting
   - drawdown or regime throttles
5. Run one portfolio execution simulation from composite weights.
6. Persist the composite as another alpha artifact directory.

This keeps AI iteration fast: expensive signal generation happens once per
alpha, while portfolio smoothing can be searched cheaply over saved weights.

## Strategy Template Contract

Generated alphas use one implementation surface:

- Copy `src/intraday/strategies/multi/_alpha_template.py`.
- Keep `symbols: list[str]` in the constructor.
- Treat `symbols` length 1 as the single-coin case.
- Return `PortfolioOrder` target weights from `generate_order`.
- Leave artifact writing to the runner; strategy code only decides target
  exposure.

There should be no separate single-coin template. The reusable product is the
saved target-weight ledger, not a special strategy subclass.
