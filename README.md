# Intraday Trading

Compact intraday alpha research repo.

## Core Paths

- `AGENTS.md`: first-read context for coding agents.
- `docs/MANUAL_BACKTEST.md`: manual strategy + backtest path.
- `docs/ALPHA_ARTIFACT_CONTRACT.md`: saved alpha artifact contract.
- `src/intraday/strategies/multi/_alpha_template.py`: strategy template.
- `src/intraday/backtest/multi_tick_runner.py`: portfolio tick backtest runner.
- `scripts/agent/run_v2.py`: single-agent research loop.
- `scripts/run_portfolio_forward_test.py`: portfolio forward test runner.

## Setup

```bash
uv sync
cp .env.example .env
```

## Manual Backtest

Read `docs/MANUAL_BACKTEST.md`.

The direct workflow is:

1. Copy `src/intraday/strategies/multi/_alpha_template.py`.
2. Implement your alpha in `src/intraday/strategies/multi/<name>.py`.
3. Run it with `PortfolioTickBacktestRunner`.

Single and multi coin are the same interface:

- `symbols=["BTCUSDT"]`: single coin
- `symbols=["BTCUSDT", "ETHUSDT"]`: multi coin

## Agent Loop

```bash
uv run python scripts/agent/run_v2.py alpha_run --prepare --no-edit
# edit archive/alpha_run/PLAN.md
uv run python scripts/agent/run_v2.py alpha_run --run --no-edit
```

The v2 loop is one staged agent: Research -> Develop -> Analyze. It should
generate reusable `weights.parquet` ledgers, not one-off backtest scripts.

## Tests

Focused smoke path:

```bash
uv run pytest \
  tests/strategies/test_alpha_template.py \
  tests/test_v2_agent_prompts.py \
  tests/test_v2_one_cycle_integration.py \
  tests/test_v2_run_v2_wiring.py \
  -q
```
