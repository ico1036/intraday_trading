# Live paper-trading deployment

This directory is the portable bundle for the currently-running paper
forward tick. It is **not** an exchange order pipeline — every run is a
deterministic re-backtest of `[IS_start .. as_of]`, with results written
to `archive/<run_id>/alphas/<alpha_id>/forward/` and served by the
dashboard.

## What is running

- Alpha: `xs_volume_rank` (`reverse=true`)
- Run: `run_2026_05_xs500`
- Cadence: daily 09:05 local (macOS launchd)
- Entry script: `scripts/run_forward_tick.py`
- Composite: `hierarchical_amihud_quality_corr095_gross5_weight_composite_v1`
- Child alphas:
  `xs_factor_amihud60d_fwd_c10`,
  `xs_factor_amihud60d_fwd_c20`,
  `xs_factor_amihud60d_fwd_c30`,
  `xs_factor_amihud60d_fwd_c40`,
  `xs_factor_amihud60d_fwd_c50`
- Composite run: `run_2026_05_full531_rerun_backtests`
- Composite cadence: daily 09:20 local (macOS launchd)
- Composite entry script: `scripts/run_live_composite_amihud_gross5_tick.py`

## Files

- `com.intraday.forward_tick.plist` — launchd job that drives the daily
  re-backtest. **Absolute paths inside are PC-specific** (see below).
- `com.intraday.composite_amihud_gross5_forward_tick.plist` — launchd job
  that refreshes the five AMIHUD child alphas and then the gross-5 composite.
  **Absolute paths inside are PC-specific**.
- `splits/run_2026_05_xs500.splits.json` — frozen universe + IS/OS
  windows. Required to seed data and reproduce the run on another PC.
- `splits/run_2026_05_full531.splits.json` — frozen universe + IS/OS
  windows for the AMIHUD composite live tick.

## One-time setup on a new PC

```bash
# 1. Clone + install deps
git clone https://github.com/ico1036/intraday_trading.git
cd intraday_trading
uv sync

# 2. Seed daily klines for the live universe (idempotent, ~ a few minutes)
uv run python scripts/tools/download_daily_klines.py \
    --from-splits live/splits/run_2026_05_xs500.splits.json

# 3. Patch absolute paths in the plist for this PC
cp live/com.intraday.forward_tick.plist ~/Library/LaunchAgents/
cp live/com.intraday.composite_amihud_gross5_forward_tick.plist ~/Library/LaunchAgents/
#    edit ~/Library/LaunchAgents/com.intraday.forward_tick.plist:
#      - WorkingDirectory       → absolute path to this repo
#      - ProgramArguments cd    → same absolute path
#      - /opt/homebrew/bin/uv   → `which uv` on this PC
#    repeat the same path edits for:
#      ~/Library/LaunchAgents/com.intraday.composite_amihud_gross5_forward_tick.plist

# 4. Register and start
launchctl unload ~/Library/LaunchAgents/com.intraday.forward_tick.plist 2>/dev/null
launchctl load   ~/Library/LaunchAgents/com.intraday.forward_tick.plist
launchctl unload ~/Library/LaunchAgents/com.intraday.composite_amihud_gross5_forward_tick.plist 2>/dev/null
launchctl load   ~/Library/LaunchAgents/com.intraday.composite_amihud_gross5_forward_tick.plist

# 5. Smoke test (one immediate run instead of waiting for 09:05)
SEAL_OPEN=1 uv run python scripts/run_forward_tick.py \
    --run-id run_2026_05_xs500 \
    --alpha-id xs_volume_rank \
    --strategy XsVolumeRankStrategy \
    --strategy-params '{"reverse": true}' \
    --as-of $(date -u +%Y-%m-%d) --sync-data

SEAL_OPEN=1 uv run python scripts/run_live_composite_amihud_gross5_tick.py \
    --as-of $(date -u +%Y-%m-%d) --sync-data
```

## Verification

- Log: `/tmp/forward_cron.log`, `/tmp/forward_launchd.{out,err}`,
  `/tmp/composite_amihud_gross5_forward_cron.log`,
  `/tmp/composite_amihud_gross5_forward_launchd.{out,err}`
- Result dir: `archive/run_2026_05_xs500/alphas/xs_volume_rank/forward/`
  (look at `metrics.json` mtime → should match the last 09:05 fire)
- Composite result dir:
  `archive/run_2026_05_full531_rerun_backtests/composites/hierarchical_amihud_quality_corr095_gross5_weight_composite_v1/forward/`
  (look at `metrics.json` mtime → should match the last 09:20 fire)
- Dashboard: serves the same `forward/` directory automatically.

## Linux / non-launchd hosts

The plist is macOS-only. Replace with cron:

```cron
5 9 * * *  cd /abs/path/to/intraday_trading && SEAL_OPEN=1 \
    /abs/path/to/uv run python scripts/run_forward_tick.py \
    --run-id run_2026_05_xs500 --alpha-id xs_volume_rank \
    --strategy XsVolumeRankStrategy \
    --strategy-params '{"reverse": true}' \
    --as-of $(date -u +\%Y-\%m-\%d) --sync-data \
    >> /tmp/forward_cron.log 2>&1
```

## What is NOT here

- No exchange API keys, no order placement code. This pipeline is
  paper-only — `src/intraday/paper_trader.py` is a simulator.
- No `archive/` results — those are local artifacts (95 GB) and stay
  out of git. The pipeline regenerates them.
