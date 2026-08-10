# Intraday Trading

Intraday long/short alpha research, forward monitoring, and guarded live
execution workspace. The durable product of every alpha is a target-weight
ledger (`weights.parquet`); composites reuse those ledgers instead of rerunning
their child strategies.

## What Is Included

- One target-weight strategy interface for both single- and multi-symbol alphas.
- Deterministic backtest, artifact verification, and forward-test CLIs.
- An alpha dashboard for research results, composites, and live streams.
- A fail-closed Binance USDⓈ-M execution path for `xs_volume_rank`.

Research artifacts and live state are local runtime data. They are intentionally
excluded from Git, so a fresh clone contains the code but not private account
state or the local dashboard history.

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
- `scripts/live_xs_volume_rank.py`: fail-closed Binance USDⓈ-M executor for
  `xs_volume_rank` (`dry-run` by default). See
  `docs/XS_VOLUME_RANK_LIVE_RUNBOOK.md` before connecting an account.

## Setup

```bash
uv sync
git config core.hooksPath .githooks
```

The last command activates the repo-local pre-commit hook
(`.githooks/pre-commit`), which runs `scripts/governance/check.py` on every
commit and aborts on editable-surface or universe-consistency violations.

## Alpha Dashboard

Start the dashboard against the local archive root:

```bash
MPLCONFIGDIR=/tmp/matplotlib-cache \
  uv run python scripts/tools/alpha_dashboard.py \
  --run-dir archive \
  --host 127.0.0.1 \
  --port 8081
```

Open <http://127.0.0.1:8081>. The dashboard discovers artifacts under
`archive/` and provides:

- alpha and composite drill-down pages;
- IS, OS, and forward/live performance views;
- a live board for selecting and comparing multiple strategies;
- `All live`, `30D`, and `7D` windows;
- an optional rebased BTC comparison on live charts;
- navigation back to the originating dashboard tab.

An empty dashboard on a fresh clone is expected because `archive/*` is ignored.
Populate or mount the artifact archive before starting it. To expose the local
server temporarily, run `cloudflared tunnel --url http://127.0.0.1:8081`; the
generated public URL is ephemeral and should not be treated as deployment.

## Live Execution Safety

`scripts/live_xs_volume_rank.py` is dry-run by default and requires explicit
execution flags for real orders. Read `docs/XS_VOLUME_RANK_LIVE_RUNBOOK.md`
before connecting an account.

Keep credentials only in local environment variables. Never put API keys in
JSON configuration, source files, command history, screenshots, or committed
`.env` files. The following local paths are ignored by Git:

- `.env` and `*.env`;
- `live/state/` and `live/KILL_SWITCH`;
- `archive/*`, which contains weights, trades, metrics, and forward state;
- local caches, databases, and NiceGUI state.

Use a dedicated exchange sub-account, disable withdrawals on its API key, and
validate on testnet and dry-run before enabling live execution.

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
