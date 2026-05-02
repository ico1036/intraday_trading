# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Philosophy

This system is not a "hypothesis generator + expression helper". It is a
loop that simulates a quant researcher whose seniority accrues year over
year. Good alpha is born from the product of economic intuition (a
hypothesis) and the minimal expression that reveals it in data. As
seniority grows, both axes sharpen simultaneously. The system's job is to
reproduce that growth arc inside a single run, and to let intuition
accumulate across runs.

### Six principles (ranked)

1. Hypothesis is the primitive.
A natural-language economic thesis comes first. Factors, columns,
operators, code, and WebSearch are all expression tools in service of
testing that thesis. Good code cannot rescue a bad hypothesis; matching
operators to factors without a thesis produces noise.
*Rejects:* reducing the search space to factor × operator tuples, treating
operator diversity as an end in itself.

2. One hypothesis, many expressions.
A hypothesis unfolds into an infinite expression space through shape
questions — lag? rolling window? regime conditionality? magnitude vs.
rank? neutralization? The agent's *expressive freedom* is not the size of
its operator menu; it is **how many ways it can articulate the same
thesis**.
*Rejects:* flat "pick a factor, pick an operator" mapping; trials that
break thesis continuity without cause.

3. Simple first, sophisticated only with cause.
The first experiment for any hypothesis is the minimal expression. On
failure, separate "was the thesis wrong or was the expression
insufficient?" Thesis-wrong → refine or reject (this is when you reach
for WebSearch / papers). Expression-insufficient → refine operator /
structure, and every refinement must be tied to the **previous failure
mode**.
*Rejects:* complexity without justification, parameter-tweak festivals,
mixing operators for novelty's sake.

4. Ontology = seniority = internalized intuition.
wiki/themes, patterns/, theses.jsonl, wiki/pair_correlations.md
are not lookup tables. They are the agent's default intuition. Reading
them in ORIENT is not "information retrieval" — it is *installing this
run's agent with years of experience*. If the pages are long and
chronological, the intuition blurs. They must stay compressed beliefs.
*Rejects:* treating the ontology as a reference table, starting each run
from zero, surfacing trial-by-trial noise in place of beliefs.

5. Correlation intuition = portfolio thinking.
With seniority comes the ability to predict — before running — roughly
where a new alpha would sit in the correlation graph of existing alphas.
Good alpha is not the one with the highest sharpe; it is the one with
marginal contribution to the book. Correlation structure serves two
purposes: clone defense (post-execute filter) and orthogonality seeking
(pre-proposal intuition).
*Rejects:* greedy single-sharpe chasing, variant proliferation inside the
same cluster.

6. Clean separation of deterministic rules vs. agent judgment.
Thresholds, retry budgets, chain orchestration, schema validation are
scripts. Hypothesis generation, code writing, narrative, and intuition
are agent. When the boundary is violated — determinism encroaching on
judgment (rule-list bloat) or judgment absorbing determinism (counters
carried in the agent's head) — the system degrades toward either rigid
exploration or unreliable execution.
*Rejects:* passing flags as prose, agents parsing JSON to branch on
conditions, runaway hard-rule lists.

### One-line summary

> **Hypothesis is king. Operators are servants. Ontology is the experience
> the king leans on. Correlation structure is the map the king reads.
> Scripts are the king's executors — they never usurp the throne.**

### What this means for contributors
- When adding to scripts/, ask: does this belong on the deterministic
  side (threshold, orchestration, schema)? If it requires semantic
  judgment, it belongs in an agent skill instead.
- When editing a skill (`.claude/skills/*/SKILL.md`), ask: does this
  constrain judgment in a way that serves hypothesis sharpening, or does
  it force mechanical behavior that will produce noise?
- When compiling wiki pages, keep compressed beliefs, not logs. A
  wiki page that the next agent can internalize in one read is worth ten
  exhaustive ones.
- New gates should target the thesis layer (exploration, refinement
  depth, orthogonality) rather than the expression layer (operator
  coverage, mechanical diversity).

## Project

Vectorized factor-based backtester for US equities. Pulls Compustat data from ClickHouse (`db_compustat_mirror`) and evaluates signal functions as pure pandas/numpy matrix operations — no event loop.

## Environment

- conda activate helix (Python ≥ 3.10)
- CLICKHOUSE_GOLD_COMPUSTAT_URL must be set in .env — every run connects to ClickHouse on load.
- Dependencies declared in pyproject.toml; lock file is uv.lock (project can be installed via uv sync or `pip install -e .`).
- After cloning, install the package in editable mode: pip install -e .

## Running strategies

Strategy scripts live in strategies/. Run directly:

python strategies/roe.py               # long-only ROE, top 500
python strategies/profit_composite.py  # composite ROE+GP+OP
python strategies/sp500.py             # cap-weighted SP500 proxy
*_neutral.py variants are dollar-neutral long/short versions (rank-demeaned signal, weight_scheme="signal"`). Real pytest tests go in `tests/.

Artifacts land in backtest_output/<signal_name>_<timestamp>/ (summary CSV, parquet matrices, plot PNG). Raw data is cached as parquet in cache/ keyed by date range + universe size + table/column (see _cache_key in `vectest/vectorized.py`); delete the file to force a refetch.

## Architecture

The vectest package contains all core modules. Import via from vectest import VectorizedBacktester.

### vectest/vectorized.py — VectorizedBacktester + BacktestResult

Pipeline inside bt.run(signal_fn, rebal, top_n, weight_scheme, long_bottom, ...):

1. Universe resolution — _resolve_universe picks one issue per gvkey (largest market cap) via tb_sec_idhist + tb_security + tb_company. _resolve_dynamic_universe snapshots it at each rebalance date so survivorship bias is avoided.
2. Data load — load_prices() and load_fundamentals(table, columns) pivot raw rows into DataFrame[date × sec_id] matrices stored in bt.funda[col]. Fundamentals are forward-filled to the daily trading calendar.
3. Signal evaluation — user's signal_fn(bt) returns a full DataFrame[date × sec_id]; higher = selected unless long_bottom=True. NaN → excluded.
4. Selection & weighting — at each rebal date, mask to active universe, rank, take top-N, then either equal-weight or signal-proportional weight. Weights forward-fill daily between rebalances.
5. PnL — daily returns = (weights_t * pct_change_t).sum(axis=1). BacktestResult exposes cagr, sharpe, max_drawdown, calmar, volatility, avg_turnover, avg_holdings, plus summary(), yearly_summary(), plot(), save().

Key invariant: signal functions receive the full matrix, not row-by-row — write everything with pandas vector ops (`.shift(N)` for lags in trading days, .rank(axis=1, pct=True) for cross-sectional ranks, .where(cond) to mask).

### vectest/benchmark.py — BenchmarkAnalysis

Loads S&P 500 series either from a Korean-format .xls (`from_xls`, which scans for the first row where col 0 parses as a date and col 1 as a float) or from db_finance_mirror.tb_bm_idx_data (`from_db`). bm.compare(result) returns a report with CAPM α/β, tracking error, information ratio, up/down capture.

## Data reference
- tb_sec_dprc — daily prices (`prccd`, prcod, prchd, prcld, cshtrd, `cshoc`)
- tb_co_ifndq — quarterly fundamentals (`ibq`, ceqq, saleq, cogsq, atq, oiadpq, …)
- tb_co_afnd1 / tb_co_afnd2 — annual fundamentals
- tb_sec_idhist — point-in-time ticker ↔ gvkey/iid mapping

Column dictionaries for each fundamental table are in table_desc/desc_*.csv (3,192 columns total) — consult via Grep, never full Read. The project-local compustat-fundamental skill (`.claude/skills/`) already points at table_desc/ and provides the table-asymmetry reference (which CF/EBIT items are annual-only, etc.).

## Signal authoring reference

### bt.load_prices(columns=[...]) — allowed column names
open, high, low, close, volume, market_cap, adj_close. Anything else will KeyError. Stored into bt.funda[col] alongside fundamentals.

### bt.load_fundamentals(table, columns, pub_delay_months=4)
- table: one of tb_co_ifndq (quarterly), tb_co_afnd1`/`tb_co_afnd2 (annual A–L / M–Z split), tb_co_ifndsa (semi-annual), tb_co_ifndytd (YTD).
- pub_delay_months=4 shifts datadate forward by 4 months before aligning to the trading calendar — this is the look-ahead guard for fundamental publication lag; don't disable unless you know what you're doing.
- For column existence, grep table_desc/desc_<table>.csv — never assume.

### Constructor
bt = VectorizedBacktester("2018-09-15", "2026-04-01", univ_n=3000)- univ_n = candidate universe size (PIT top-N by market cap). Portfolio
  size is determined by signal_fn itself (see below).

### bt.run(...) parameter surface
| Param | Values | Notes |
|---|---|---|
| signal_fn | (bt) -> DataFrame[date × sec_id] | Required. NaN = excluded, non-NaN = position. |
| rebal | "M", "W", "Q" | Monthly / weekly / quarterly rebalance. |
| weight_scheme | "equal", "signal" | "signal" = weights proportional to the signal value (use this for L/S where sign matters). |
| signal_name | str | Label used in save() folder name. |
| initial_capital | float | Default 1e8; additive PnL, no compounding. |
| start, end | str (optional) | Override the constructor's date range for this run only (used by IntegrityTest). |

### Position selection is inside signal_fn (current API)

There is no top_n or long_bottom argument on run(). The signal function
is fully responsible for:
1. Masking to the eligible universe (`bt.universe_mask`).
2. Picking top-N (or bottom-N) via .rank(...) + .where(...).
3. Setting the sign (positive = long, negative = short) when using
   weight_scheme="signal".

Canonical long-only top-N pattern:
signal = <your raw score>
mask = bt.universe_mask.reindex(signal.index, method="ffill") \
                        .reindex(columns=signal.columns, fill_value=False)
signal = signal.where(mask)
return signal.where(signal.rank(axis=1, ascending=False) <= 100)  # top 100
"Low-is-good" factors (old `long_bottom=True`): invert the score in
signal_fn itself — either negate (`-signal`) or take reciprocal (`1/signal`).
No flag exists anymore.

L/S neutral: return signed values (rank-demeaned), set
weight_scheme="signal".

### Conventions
- Fundamental lag: .shift(63) ≈ 1 trading quarter, .shift(252) ≈ 1 trading year. Use for "lagged denominator" patterns like ibq / ceqq.shift(63).
- Divisor safety: wrap denominators as x.where(x > 0) to NaN-out non-positive values rather than generate inf.
- Composite signals: convert each leg with .rank(axis=1, pct=True) before summing so units are comparable.
- Neutral (L/S) variants: rank to [0, 1] then subtract 0.5 (or cross-sectional mean); run with weight_scheme="signal".
- Quarterly-only columns: CF items (`capx`, oancf, fincf, ivncf`) and `ebit`/`ebitda do not exist in tb_co_ifndq. Either use annual tables with .shift(252) or compute quarterly EBIT as saleq - cogsq - xsgaq (see compustat-fundamental skill for the full asymmetry table).
- YTD → quarterly CF: tb_co_ifndytd stores oancfy, capxy, etc. as year-to-date cumulative. Naive .diff() breaks at fiscal-year boundaries (4Q-end → 1Q drops by ~full-year value). Correct pattern:

  ytd = bt.funda["oancfy"]
  fq  = bt.funda["fqtr"]           # fiscal quarter number 1..4
  oancfq = ytd.where(fq == 1, ytd - ytd.shift(63))  # Q1 stays as-is, else diff
    Load fqtr alongside the YTD column. Annual (`afnd2.oancf`) is simpler if yearly cadence is acceptable.

## Framework limitations

Push back on requests that need any of these — they require new code, not a new signal:

- Intraday / bar-level execution — only rebal="M"/"W"/"Q" supported; positions held between period ends.
- Stop-loss, trailing stop, drawdown triggers — no position-level exit logic; weights forward-fill to the next rebalance unconditionally.
- Transaction costs, slippage, borrow fees — portfolio_returns is gross. Turnover is reported but never deducted. Agent must not compare gross Sharpes as if they were net.
- Asset classes outside US equity — universe is hardcoded to tb_sec_dprc with excntry='USA', tpci='0'. No options, futures, bonds, or non-US.
- Walk-forward / OOS split — bt.run() evaluates on the full date range. For agentic sweeps, wrap an explicit train/val/test split externally and gate final metrics on untouched OOS data.
- Delisting returns — no explicit liquidation price; a stock that stops trading silently contributes 0 to PnL thereafter (see the universe/PIT discussion). Low-price or distress-oriented strategies will be biased upward.

### Agent / sweep loops

- Use result.save(lite=True) in loops — skips adj_close.parquet and stock_returns.parquet (duplicates of cache/ data, ~130 MB per run). Cuts per-folder footprint from 158 MB → 27 MB.
- bt can be reused across strategies only if (start, end, univ_n) stay fixed. Changing any of those requires a fresh VectorizedBacktester(...) to avoid stale _daily_adj_close / funda.
- Between iterations: del bt, result; plt.close('all'); gc.collect() to release the ~GB-scale matrices.
- Metric crash guard: short backtests or empty portfolios can yield NaN/inf Sharpe — wrap metric extraction in a finite-check before ranking trials.

### Integrity test (from `vectest/integrity.py`)

When building a new signal, wrap it with IntegrityTest to detect
look-ahead bias and path dependency automatically. The test runs three
backtests over overlapping windows and compares positions on shared dates.
See strategies/sp500.py or strategies/gp.py for usage. Any non-zero post-warmup
divergence indicates a bug — fix before trusting the numbers.

## Autonomous strategy search loop

The repo ships a Ralph-style agent loop for automated factor discovery:

./auto_loop.sh            # run until targets met or max_trials reached
./auto_loop.sh --reset    # wipe state and restart
./auto_loop.sh --max 5    # cap outer shell iterations
- Entry point for the agent's procedure: .claude/AGENT.md (read every iteration).
- User-editable goal + numeric targets: auto_state/PLAN.md.
- Deterministic logic lives in scripts/ (execute_trial, classify, plateau, similarity, log_append, synthesize, exit_check, oos_clamp).
- Long-term memory: auto_state/research_map.md (auto-regenerated from trial_log.jsonl each iteration — theme histogram, stagnation warning, unexplored gaps).
- Agent-generated trials land in auto_strategies/trial_NNN.py based on _template.py.
- Guardrail: a PreToolUse hook (`scripts/oos_clamp.py`, registered in .claude/settings.json`) rewrites any date past `2026-04-01 (end of available history) in files under auto_strategies/ back to 2026-04-01 before the Write/Edit tool fires. OOS is future forward-test — the user validates top-K strategies on new data as it arrives after 2026-04-01. The loop itself uses the full 2018-09-15 ~ 2026-04-01 history as IS.

See README_AUTO_LOOP.md for the full design and file map.

### Loop control — design decisions

#### 2026-04-21: iter-resilience deliberation

Problem (observed on 15-run backfill: v3–v5 + 12 aqr_*): only 2
terminated normally (DONE + manifest). 7 died mid-iter or mid-sequence
and left residue on disk; 6 never dispatched because `run_aqr_N.sh`'s
set -e propagated the abort. Three structural causes in the loop:

1. auto_loop.sh:173-174 exit $rc — a single non-zero from Claude
   (including transient token issues) aborts the whole run. No retry.
2. AGENT.md ORIENT step does NOT check for residue before starting
   the next iter: last_iteration.json, current_hypothesis.md, or an
   orphan source/trial_(N+1).py from a prior dead iter are invisible
   to the agent, so the next iter silently overwrites or skips them.
3. The 6-step pipeline (ORIENT → PROPOSE → IMPLEMENT → EXECUTE →
   REFLECT → COMMIT) is not transactional. reflection.json write and
   commit_iteration.py invocation are two separate agent actions —
   a stop between them loses the executed trial from trial_log.jsonl.

3 approaches considered:

| # | Idea | Status |
|---|---|---|
| 1 | Fix auto_loop.sh retry + ORIENT residue-check + atomic commit wrapper | chosen — preserves filesystem-as-SoT and 4-shard parallel design, ~1-day impl |
| 2 | Ralph-style Stop hook (one long session, hook re-invokes Claude until DONE) | rejected — naturally handles #1 and #2 via in-memory context, but for runs with max_trials > ~100 the session's context fills and compact becomes lossy, breaking the stagnation-detection invariants |
| 3 | claude-agent-sdk + done pattern (programmatic session and compact) | rejected — rewrites auto_loop.sh in Python, compact is still lossy, and the 4-shard parallel model becomes awkward under a single SDK driver |

Re-evaluation triggers:
- If max_trials routinely exceeds ~200 and fresh-ORIENT overhead
  becomes the dominant token cost → revisit Option 2 with selective
  compact (e.g., compact wiki/research_map summary only, keep
  trial_log tail raw).
- If cross-run session continuity becomes necessary (e.g., sharing
  thesis registry live between runs) → revisit Option 3 with shared
  session threads.

Scope note: none of the three options solves daily token budget
exhaustion. That is a user planning problem. Option 1 makes transient
rc != 0 recoverable but a truly drained account still fails all
retries, and run_aqr_N.sh set -e then cascades.
