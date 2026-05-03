# Intraday Trading Agent Context

This file is the first-read context for future coding agents working in this
repository. Keep it short, operational, and aligned with the current design.

## Product Goal

The system exists to let AI rapidly generate intraday long/short alphas, save
their target-weight ledgers, and build stronger composite strategies by
combining saved alpha weights. Composite research should read saved
`weights.parquet` artifacts instead of rerunning every child strategy.

## Current Architecture Decisions

- Default agent workflow is markdown-driven coverage exploration. Read
  `AGENT.md` first.
- Treat alpha generation as search-space coverage, not evolutionary
  optimization. Do not refine winners during exploration.
- Use `archive/<run_id>/coverage_map.json` and `alpha_index.csv` to record
  visited cells and valid artifacts.
- The old staged v2 flow can remain as legacy support, but do not make it the
  default path for new alpha generation.
- Do not reintroduce Claude Task subagents or `AgentDefinition`-style
  multi-agent orchestration in production code.
- Generated alpha strategy code uses one portfolio template:
  `src/intraday/strategies/multi/_alpha_template.py`.
- There is no separate single-coin template. `symbols=["BTCUSDT"]` is the
  single-coin case; `symbols=[...]` with length greater than one is the
  multi-coin case.
- Generated alphas return `PortfolioOrder` with `Order(weight=...)` targets.
- Backtests and forward tests should persist the same core artifact structure.
  The primary durable alpha product is `weights.parquet`.

## Artifact Contract

Every alpha run should write these core files under its artifact directory:

- `manifest.json`
- `weights.parquet`
- `metrics.json`
- `summary.json`
- `summary.csv`
- `equity_curve.parquet`
- `trades.parquet`
- `events.parquet`

`docs/ALPHA_ARTIFACT_CONTRACT.md` is the source of truth. Strategy code should
only decide target exposure; runners/tools are responsible for writing
artifacts.

## Strategy Generation Rules

When implementing a generated alpha:

1. Pick an underexplored search cell from `docs/agent/SEARCH_SPACE.md`.
2. Write `archive/<run_id>/alphas/<alpha_id>/search_cell.json`.
3. Copy `src/intraday/strategies/multi/_alpha_template.py`.
4. Keep `symbols: list[str]` in the constructor.
5. Implement signal logic inside the copied strategy.
6. Return `PortfolioOrder | None` from `generate_order`.
7. Use target weights, not ad hoc quantity sizing, unless the runner contract
   explicitly requires otherwise.
8. Put strategy tests under `tests/strategies/`.
9. Do not edit infrastructure files such as `strategy.py`, runners, artifact
   writers, or backtest tools unless the task is explicitly infrastructure
   work.
10. Record completed artifacts with
    `uv run python scripts/agent/exploration.py record archive/<run_id> <alpha_id>`.

## Important Validation Commands

```bash
uv run pytest tests/test_agent_exploration.py -q
uv run pytest tests/strategies/test_alpha_template.py tests/test_v2_agent_prompts.py -q
uv run pytest -q
git diff --check
```

## Recently Locked Tests

- `tests/strategies/test_alpha_template.py` locks the unified template:
  single-symbol and multi-symbol operation both return `PortfolioOrder`
  target weights through the same class.
- `tests/test_agent_exploration.py` locks the markdown coverage utility:
  initialize runs, suggest underexplored cells, validate artifacts, and update
  coverage/index state.
