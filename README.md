# Intraday Trading

Compact intraday alpha research repo.

## Core Paths

- `AGENT.md`: markdown operating manual for alpha exploration agents.
- `CLAUDE.md`: Claude Code entry instructions; mirrors the same workflow.
- `AGENTS.md`: compact first-read context for coding agents.
- `docs/MANUAL_BACKTEST.md`: manual strategy + backtest path.
- `docs/ALPHA_ARTIFACT_CONTRACT.md`: saved alpha artifact contract.
- `src/intraday/strategies/multi/_alpha_template.py`: strategy template.
- `src/intraday/backtest/multi_tick_runner.py`: portfolio tick backtest runner.
- `scripts/agent/run_v2.py`: legacy staged single-agent research loop.
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

## Markdown Agent Exploration

Read `AGENT.md`, implement one independent alpha, backtest it into
`archive/<run_id>/alphas/<alpha_id>/`, and append the result to
`archive/<run_id>/LOG.md`.

Exploration is breadth-first. Do not refine prior winners during alpha
generation; selection and composite construction are separate phases.

The older v2 staged loop remains in `scripts/agent/run_v2.py`, but it is no
longer the default path for new exploration work.

Deterministic commands for any agent runtime:

```bash
uv run python scripts/tools/backtest.py ... --json
uv run python scripts/tools/verify_artifact.py archive/<run_id>/alphas/<alpha_id> --json
```

## Tests

Focused smoke path:

```bash
uv run pytest \
  tests/strategies/test_alpha_template.py \
  tests/tools/test_cli_backtest_and_verify.py \
  tests/backtest/test_multi_tick_runner.py \
  tests/test_multi_forward_runner.py \
  -q
```
