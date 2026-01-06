# Backtest Analyst

Analyze backtest results and provide structured feedback with lessons learned.

## Usage

Call after running a backtest to get analysis:
```
/backtest_analyst [paste backtest results or provide context]
```

## What It Does

1. **Diagnoses** performance issues (over-trading, fee impact, parameter sensitivity)
2. **Extracts lessons** from the results
3. **Recommends** parameter changes
4. **Provides** next steps

## Output Format

Returns structured Markdown report:
- **Summary**: Strategy, period, return, verdict
- **Metrics**: Trades, win rate, profit factor, fees
- **Diagnosis**: Primary issue, root cause, evidence
- **Lessons Learned**: Prioritized insights with actions
- **Parameter Recommendations**: Current vs suggested
- **Next Steps**: Actionable checklist

## Verdict Categories

- **PROFITABLE**: Positive return, sustainable
- **PROMISING**: Needs tuning
- **OVERTRADING**: Too many trades, fee problem
- **FEE_TRAP**: Profitable before fees
- **BROKEN**: Fundamental logic issue

Load full reasoning framework from `.claude/agents/backtest_analyst.md`.
