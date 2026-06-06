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
  weights.parquet
  equity_curve.parquet
  trades.parquet
  metrics.json
  strategy_source.py
  report.png                  # optional rendered report
```

Forward runs may also keep compatibility files such as `portfolio_nav.parquet`,
but readers must prefer the core files above.

For alpha exploration, store one file set under one alpha directory:

```text
archive/<run_id>/alphas/<alpha_id>/
  weights.parquet
  equity_curve.parquet
  trades.parquet
  metrics.json
  strategy_source.py
```

The fixed split file lives at:

```text
archive/<run_id>/splits.json
```

Example:

```json
{
  "is": {"start": "2025-03-01 00:00:00", "end": "2025-03-07 23:59:59"},
  "os": {"start": "2025-03-08 00:00:00", "end": "2025-03-14 23:59:59"}
}
```

The agent may inspect IS during development. OS is run after strategy code is
frozen and is used only to write warning labels in `metrics.json`; it must not
drive strategy repair. Do not create separate `is/` and `os/` artifact
directories for new runs. When a single run covers both windows, write IS/OS
sub-metrics under `metrics.json` keys `is` and `os`, with `is_end` recording
the split boundary.

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

## `trades.parquet`

The realised trade ledger used for execution-level checks and cost analysis.
It is required because aggregate metrics alone are not enough to inspect
turnover, win/loss distribution, fees, or suspicious one-off fills.

## `equity_curve.parquet`

The cached NAV/PnL curve used by dashboards and quick comparisons. It avoids
rerunning portfolio simulation just to inspect an alpha.

## `strategy_source.py`

The strategy module snapshot used for the run. Source metadata such as
`strategy_class`, original source path, and git commit should live in
`metrics.json`, not in a separate `strategy_source.meta.json`.

## `metrics.json`

Top-level metrics and run metadata used for ranking/filtering:

```json
{
  "artifact_version": 2,
  "run_type": "backtest",
  "alpha_id": "xs_volume_rank",
  "strategy_class": "XsVolumeRankStrategy",
  "strategy_source": "strategy_source.py",
  "source_original_path": "src/intraday/strategies/multi/xs_volume_rank_strategy.py",
  "git_head": "abc123",
  "symbols": ["BTCUSDT", "ETHUSDT"],
  "bar_type": "TIME",
  "bar_size": 86400,
  "started_at": "2025-03-01T00:00:00",
  "ended_at": "2025-03-14T23:59:59",
  "profit_factor": 1.2,
  "total_return": 0.04,
  "max_drawdown": -0.08,
  "total_trades": 120,
  "win_rate": 0.53,
  "sharpe": 0.9,
  "per_symbol": {},
  "is_end": "2025-03-07T23:59:59",
  "is": {"total_return": 0.03, "sharpe": 0.8},
  "os": {"total_return": 0.01, "sharpe": 0.6},
  "validation_flags": []
}
```

Do not add separate `manifest.json`, `summary.json`, `summary.csv`,
`validation.json`, or `strategy_source.meta.json` for new artifacts. Fold that
metadata into `metrics.json`.

## IS/OS validation

`scripts/tools/validate_is_os.py` compares the `is` and `os` metric blocks
inside `metrics.json` and writes `validation_flags` plus a `validation` block
back into `metrics.json`. Legacy `is/metrics.json` and `os/metrics.json`
archives may still be read, but they are not the standard for new runs.

Warnings are labels, not failures. Initial flags:

- `RETURN_COLLAPSE`
- `SHARPE_COLLAPSE`
- `SHARPE_SIGN_FLIP`
- `DRAWDOWN_EXPANSION`
- `WIN_RATE_DRIFT`
- `OS_TRADE_COUNT_TOO_LOW`

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
