# Intraday Trading

Compact intraday alpha research repo.

## Core Paths

- `AGENT.md`: markdown operating manual for alpha exploration agents.
- `AGENTS.md`: compact first-read context for coding agents.
- `docs/agent/SEARCH_SPACE.md`: coverage axes for alpha generation.
- `scripts/agent/exploration.py`: deterministic coverage/index utility.
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

```bash
uv run python scripts/agent/exploration.py init archive/alpha_run
uv run python scripts/agent/exploration.py next-cells archive/alpha_run --limit 10
```

Then read `AGENT.md` and implement one independent alpha for an underexplored
cell. After backtesting into `archive/alpha_run/alphas/<alpha_id>/`, record it:

```bash
uv run python scripts/agent/exploration.py record archive/alpha_run <alpha_id>
```

Exploration is coverage-driven. Do not refine prior winners during alpha
generation; selection and composite construction are separate phases.

The older v2 staged loop remains in `scripts/agent/run_v2.py`, but it is no
longer the default path for new exploration work.

## Tests

Focused smoke path:

```bash
uv run pytest \
  tests/test_agent_exploration.py \
  tests/strategies/test_alpha_template.py \
  tests/backtest/test_multi_tick_runner.py \
  tests/test_multi_forward_runner.py \
  -q
```
