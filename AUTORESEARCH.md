# Autoresearch Loop

This repo uses a markdown-only loop for intraday crypto alpha search. The loop
is compatible with Codex and Claude Code because the agent only needs plain
instructions plus deterministic backtest and verification commands.

## Universe and forbidden actions

The default universe is the 7-symbol list declared in
`archive/<run_id>/splits.json` under `"universe"`:

    BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, DOGEUSDT, ADAUSDT

Forbidden actions during the loop (see `AGENT.md` for the full list):

- editing framework code under `src/intraday/` (other than one new alpha file)
- editing `scripts/`, `pyproject.toml`, `uv.lock`, `data/`
- running data-fetching commands
- changing fees, slippage, capital, or leverage assumptions

`scripts/governance/check.py` enforces both the editable surface and the
universe consistency. Run it after every attempt; the pre-commit hook in
`.githooks/pre-commit` runs it on every commit.

## Objective

Explore independent long/short portfolio alphas until the fixed in-sample
target plus all declared quality gates are satisfied. The active run sets
its own threshold and gates in `archive/<run_id>/splits.json`. The current
default for new runs is:

```text
IS Sharpe >= 0.6
total_trades >= 100
turnover >= 10x
```

`turnover = sum(|price * quantity|) / initial_capital` from the trades
ledger. The gates filter out single-trade flukes and effectively-passive
strategies (buy-and-hold has ~14 trades and ~1x turnover at this sizing).

During generation, do not run, inspect, or optimize against OS. OS is reserved
for one frozen-strategy validation pass after an alpha is selected.

## Editable Surface

The agent may edit only:

- `src/intraday/strategies/multi/<alpha>.py`
- `tests/strategies/test_<alpha>.py`
- `archive/<run_id>/alphas/<alpha_id>/**`
- `archive/<run_id>/LOG.md`
- `archive/<run_id>/alpha_index.csv`

Framework code, data loaders, execution simulation, metrics, and dashboard code
are not part of the search loop.

## One Attempt

When the user says `루프 돌려`, `start loop`, or `run loop`, continue attempts
without asking for another prompt until the IS target is reached or the user
interrupts.

1. Read `archive/<run_id>/splits.json` (including `universe`),
   `archive/<run_id>/alpha_index.csv`, recent entries in
   `archive/<run_id>/LOG.md`, and `research/index.csv`.
2. Pick the next `alpha_id`. Use the next `is_###` prefix not already present
   in `alpha_index.csv`, then add a compact idea suffix.
3. Pick a cell vector `(bar, transform, horizon, universe, exit,
   idea_family)` not already attempted in this run. The cell-saturation
   guard rejects duplicates.
4. Invoke the `/research` skill for the chosen `idea_family` if no
   `research/notes/<topic>.md` covers it. Reuse existing notes otherwise.
5. Copy `src/intraday/strategies/multi/_alpha_template.py` and populate
   `ALPHA_CELL` and `SOURCE_NOTES` at module top.
6. Add focused tests for order direction, finite weights, and single/multi
   symbol behavior.
7. Run focused tests.
8. Run an IS-only backtest into `archive/<run_id>/alphas/<alpha_id>/is/`,
   passing the run's `universe` to `--symbols`. The CLI pre-flight refuses
   on missing/invalid metadata or saturated cells.
9. Run artifact verification and inspect `weights.parquet`.
10. Run `uv run python scripts/governance/check.py --json`. Any
   non-zero exit aborts the attempt; revert disallowed changes before
   continuing.
11. Append one row to `archive/<run_id>/alpha_index.csv` and one short
    block to `archive/<run_id>/LOG.md` (include cell vector + cited note).
12. If status is `IS_PASS`, stop generation and ask before OS validation.
13. If status is not `IS_PASS`, start the next attempt from a different
   search-space cell. Never tune the failing alpha and resubmit.

## Deterministic Commands

Run an IS backtest:

```bash
uv run python scripts/tools/backtest.py \
  --data-type bars \
  --strategy <ClassName> \
  --symbols BTCUSDT ETHUSDT SOLUSDT BNBUSDT XRPUSDT DOGEUSDT ADAUSDT \
  --data-path data/futures_klines \
  --start "<IS_START>" \
  --end "<IS_END>" \
  --bar-type TIME \
  --bar-size 60 \
  --strategy-params '<strategy params json>' \
  --output-dir archive/<run_id>/alphas/<alpha_id>/is \
  --json
```

Verify artifact:

```bash
uv run python scripts/tools/verify_artifact.py \
  archive/<run_id>/alphas/<alpha_id>/is \
  --json
```

## Alpha Index

`archive/<run_id>/alpha_index.csv` is append-only during search. Use these
columns:

```text
alpha_id,status,strategy,idea,is_return,is_sharpe,is_trades,is_max_drawdown,is_win_rate,turnover,long_weight_rows,short_weight_rows,weights_finite,artifact_dir,notes
```

Status values:

```text
IS_PASS   IS Sharpe >= target.threshold AND all quality_gates AND artifact is valid
IS_FAIL   artifact is valid but Sharpe or any quality_gate is not satisfied
INVALID   code, test, artifact, or weight contract failed
```

Quality gates live in `archive/<run_id>/splits.json` under
`"quality_gates"`. The governance check (`scripts/governance/check.py
--only quality`) computes them from `trades.parquet`,
`equity_curve.parquet`, and `metrics.json`.

## Policy

- Archive every attempt.
- Bad PnL is information, not a bug.
- Fix broken code, invalid artifacts, non-finite weights, and contract
  violations only.
- Use `weights.parquet` as the durable alpha output.
- Select the next idea for breadth, not similarity to a winner.
