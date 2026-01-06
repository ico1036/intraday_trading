# Infrastructure Doctor

Diagnose infrastructure issues in the trading system.

## Usage

When called, first run the automated diagnostic:
```bash
uv run python scripts/diagnose_infra.py --verbose
```

Then load the full reasoning framework from `.claude/agents/infra_doctor.md`.

## Quick Reference

**Binary Search for Failure:**
```
trades=0, orders>0  → Problem in PaperTrader (check conditionals)
trades=0, orders=0  → Problem in Strategy (check thresholds)
orders=0, bars>0    → Strategy logic issue
orders=0, bars=0    → CandleBuilder or Loader issue
```

**Most Common Issues:**
1. Enum duplication (different classes don't compare equal)
2. Threshold mismatch (parameters tuned for wrong data type)
3. Missing integration tests (unit tests pass, system fails)
