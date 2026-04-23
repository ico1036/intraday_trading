# Run: {{run_id}}

Created: {{created}}

## Targets
# Override config/targets.yaml defaults. Delete a line to use default.
profit_factor: 1.3
max_drawdown: -0.15
total_return: 0.05
total_trades: 30
max_trials: 20
max_expressions_per_thesis: 8
max_theses_per_run: 5

## Strategy request
# Free-form: describe direction, inspiration, or constraint. The agent reads
# this at each ORIENT step as the governing intent of the run.

<write here>

## Universe
symbols: [BTCUSDT]

## IS / OS periods
is_start: 2025-03-01
is_end: 2025-09-30
os_start: 2025-10-01
os_end: 2026-01-31

## Notes
# Optional — prior art to read, constraints to respect, etc.
