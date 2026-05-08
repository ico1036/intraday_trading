# Alpha Exploration

Use this repo like a small autoresearch workspace. These instructions are plain
markdown so they work in Codex, Claude Code, or any coding agent. The detailed
loop contract is in `AUTORESEARCH.md`.

## Universe (default)

All alphas operate on the 7-symbol universe unless a run explicitly overrides:

    BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, DOGEUSDT, ADAUSDT

The contract is **picking-and-weighting**: a strategy receives the run's
symbols list and returns a `PortfolioOrder` with target weights. Per-run
overrides go in `archive/<run_id>/splits.json` under `"universe"`. The
governance check (`scripts/governance/check.py`) verifies every alpha's
`manifest.json` `symbols` matches its run's declared universe.

## Forbidden actions

These are not in the editable surface and must not be proposed or taken
during alpha generation:

- editing any file under `src/intraday/` except a single new
  `src/intraday/strategies/multi/<alpha>.py` (and never
  `_alpha_template.py` or `__init__.py`)
- editing `scripts/` (except `scripts/governance/`), `pyproject.toml`,
  `uv.lock`, `data/`
- running `scripts/download_klines.py` or any other data-fetching command
- changing fee assumptions (taker_fee_rate, maker_fee_rate), slippage,
  initial capital, leverage, or position sizing
- adding alternative bar types that require unavailable data (tick data
  is currently empty)

If the editable-surface options are exhausted for an idea, stop and report.
Do not bridge to forbidden territory.

## Goal

Generate many independent intraday long/short alpha ledgers. The durable output
is `weights.parquet`. During generation, optimize only against the fixed IS
target in `archive/<run_id>/splits.json`; do not run or inspect OS until a
strategy is frozen.

`IS_PASS` requires all of:

- `is_sharpe >= splits.json.target.threshold`
- every gate in `splits.json.quality_gates` (currently `min_trades`,
  `min_turnover`)
- artifact is valid (`scripts/tools/verify_artifact.py`)

Default thresholds for the active run: Sharpe ≥ 0.6, trades ≥ 100,
turnover ≥ 10x. The gates exist to drop flukes and passive holds.

Exploration is breadth-first. Do not refine winners during alpha generation.
Bad performance is archived, not repaired. Repair only broken code, broken
tests, or invalid artifact output.

## Editable Surface

Edit only:

- `src/intraday/strategies/multi/<alpha>.py`
- `tests/strategies/test_<alpha>.py`
- `archive/<run_id>/alphas/<alpha_id>/**`
- `archive/<run_id>/LOG.md`

Do not edit framework code unless explicitly asked.

## One Attempt

Before attempts, read `archive/<run_id>/splits.json`. Use its fixed IS period
for development. OS is reserved for one validation pass after strategy freeze.
Use the run's `universe` field for `--symbols`.

1. Read `alpha_index.csv` and recent `LOG.md` entries.
2. Choose a search-space cell that is different from recent attempts.
3. Pick the next unused `is_###` alpha id with a compact idea suffix.
4. Copy `src/intraday/strategies/multi/_alpha_template.py`.
5. Implement one strategy in `src/intraday/strategies/multi/<alpha>.py`.
6. Add focused tests in `tests/strategies/test_<alpha>.py`.
7. Run the focused tests.
8. Run IS backtest into `archive/<run_id>/alphas/<alpha_id>/is/`.
9. Verify the artifact and inspect `weights.parquet`.
10. Run `uv run python scripts/governance/check.py --json` and stop on
    any violation. Do not commit or proceed otherwise.
11. Append `alpha_index.csv` and `LOG.md`.
12. If status is `IS_PASS`, stop and ask before OS validation.
13. If status is not `IS_PASS`, move to a different search-space cell.

OS validation labels distribution shift only. Do not modify the strategy based
on OS results.

## Deterministic Commands

Run split file:

```json
{
  "is": {"start": "2025-03-01 00:00:00", "end": "2025-03-07 23:59:59"},
  "os": {"start": "2025-03-08 00:00:00", "end": "2025-03-14 23:59:59"}
}
```

Backtest:

```bash
uv run python scripts/tools/backtest.py \
  --data-type bars \
  --strategy <ClassName> \
  --symbols BTCUSDT ETHUSDT \
  --data-path data/futures_klines \
  --start "2025-03-01 00:00:00" \
  --end "2025-03-07 23:59:59" \
  --bar-type TIME \
  --bar-size 60 \
  --output-dir archive/<run_id>/alphas/<alpha_id>/is \
  --json
```

Verify:

```bash
uv run python scripts/tools/verify_artifact.py \
  archive/<run_id>/alphas/<alpha_id>/is \
  --json
```

IS/OS label:

```bash
uv run python scripts/tools/validate_is_os.py \
  --alpha-dir archive/<run_id>/alphas/<alpha_id> \
  --json
```

## Search Space

Use combinations of:

- bar: `TIME`, `VOLUME`, `DOLLAR`, `TICK`
- idea: free-form hypothesis; do not force it into a fixed family enum
- transform: `raw`, `z_score`, `percentile`, `rolling_rank`, `ewma_residual`
- horizon: `ultra_short`, `intraday`, `session`, `multi_day`
- universe: `single`, `pair`, `basket_topk`
- exit: `time_stop`, `signal_flip`, `trailing`, `vol_stop`, `neutral_zone`

Do not select the next idea from the best prior result. Select it from an
underexplored area.
