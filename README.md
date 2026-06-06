# Intraday Trading

Compact intraday alpha research repo.

## Core Paths

- `AGENT.md`: markdown operating manual for alpha exploration agents.
- `AUTORESEARCH.md`: loop contract used by automated agents.
- `CLAUDE.md`: Claude Code entry instructions; mirrors the same workflow.
- `AGENTS.md`: compact first-read context for coding agents.
- `scripts/governance/check.py`: workflow guard (editable surface + universe).
- `docs/MANUAL_BACKTEST.md`: manual strategy + backtest path.
- `docs/ALPHA_ARTIFACT_CONTRACT.md`: saved alpha artifact contract.
- `src/intraday/strategies/multi/_alpha_template.py`: strategy template.
- `src/intraday/backtest/multi_tick_runner.py`: portfolio tick backtest runner.
- `scripts/tools/backtest.py`: deterministic backtest CLI.
- `scripts/tools/verify_artifact.py`: deterministic artifact validator.
- `scripts/tools/research_wiki.py`: research wiki and loop harness metadata.
- `scripts/run_portfolio_forward_test.py`: portfolio forward test runner.

## Setup

```bash
uv sync
cp .env.example .env
git config core.hooksPath .githooks
```

The last command activates the repo-local pre-commit hook
(`.githooks/pre-commit`), which runs `scripts/governance/check.py` on every
commit and aborts on editable-surface or universe-consistency violations.

## Universe

The default trading universe is the 7-symbol list declared in each run's
`archive/<run_id>/splits.json` under `"universe"`:

    BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, DOGEUSDT, ADAUSDT

All alphas use a picking-and-weighting contract: receive the run's
`symbols`, return target weights via `PortfolioOrder`. The governance
check ensures every alpha's `metrics.json` `symbols` matches the run's
`universe`.

## Governance

Run the workflow check at any time:

```bash
uv run python scripts/governance/check.py --json
uv run python scripts/governance/check.py --staged   # for the pre-commit case
```

Two checks run:

- `editable_surface`: only allow-listed paths may change vs the baseline
  (default `HEAD`). The whitelist lives in `scripts/governance/check.py`.
- `universe`: every alpha manifest's `symbols` must equal its run's
  declared universe.

`AGENT.md` lists forbidden actions explicitly. The hook + governance
script enforce them at the repository level.

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

Deterministic commands for any agent runtime:

```bash
uv run python scripts/tools/backtest.py ... --json
uv run python scripts/tools/verify_artifact.py archive/<run_id>/alphas/<alpha_id> --json
uv run python scripts/tools/validate_is_os.py --alpha-dir archive/<run_id>/alphas/<alpha_id> --json
```

Store exploration runs as one artifact directory:
`archive/<run_id>/alphas/<alpha_id>/`. Do not split new artifacts into `is/`
and `os/` directories. Keep fixed periods in `archive/<run_id>/splits.json`;
IS/OS metric blocks and validation flags live in `metrics.json`. Do not revise
a strategy from OS results.

Before starting a goal-driven loop, initialize the research wiki and harness
version:

```bash
uv run python scripts/tools/research_wiki.py init-run \
  --run-id <run_id> \
  --goal "<user goal>" \
  --harness-id loop_v1_post_analysis_wiki \
  --attempt-budget <N>
```

After each backtest, write `research/wiki/post_analysis/<run_id>/<alpha_id>.md`
and upsert `research/wiki/alpha_memory.jsonl`. The wiki is intentionally a
small retrieval index plus post-analysis links; it should not become a
best-parameter recommender.

Every normal `scripts/tools/backtest.py` run performs a prefix-invariance
check: a shorter same-start backtest must emit identical past weights. This is
the hard look-ahead guard for generated alpha ledgers.

The default backtest data path is 1m futures bars:

```bash
uv run python scripts/tools/backtest.py --data-type bars --data-path data/futures_klines ...
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
