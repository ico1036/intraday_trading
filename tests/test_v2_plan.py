"""Phase 2-7 — PLAN.md parser contract.

Reads the user-authored PLAN.md into a typed struct used by thesis_gate,
exit_check, and oos_clamp. Merges user-supplied targets onto the defaults
from config/targets.yaml.
"""
from __future__ import annotations

from datetime import date

import pytest

from scripts.agent.v2.deterministic import plan as plan_mod


SAMPLE_PLAN = """# Run: test_run

Created: 2026-04-23T00:00:00+00:00

## Targets
profit_factor: 1.4
max_drawdown: -0.10
total_return: 0.08
total_trades: 40
max_trials: 15
max_expressions_per_thesis: 6
max_theses_per_run: 4

## Strategy request
Probe VPIN-based reversal on BTC perp. Prefer adaptive thresholds.

## Universe
symbols: [BTCUSDT, ETHUSDT]

## IS / OS periods
is_start: 2025-04-01
is_end: 2025-09-30
os_start: 2025-10-01
os_end: 2026-01-31

## Notes
None.
"""


def test_parse_plan_returns_targets():
    cfg = plan_mod.parse(SAMPLE_PLAN)
    assert cfg.targets["primary"]["profit_factor"]["value"] == 1.4
    assert cfg.targets["primary"]["max_drawdown"]["value"] == -0.10
    assert cfg.targets["primary"]["total_return"]["value"] == 0.08
    assert cfg.targets["primary"]["total_trades"]["value"] == 40


def test_parse_plan_returns_budgets():
    cfg = plan_mod.parse(SAMPLE_PLAN)
    b = cfg.targets["budget"]
    assert b["max_trials"] == 15
    assert b["max_expressions_per_thesis"] == 6
    assert b["max_theses_per_run"] == 4


def test_parse_plan_returns_universe():
    cfg = plan_mod.parse(SAMPLE_PLAN)
    assert cfg.symbols == ["BTCUSDT", "ETHUSDT"]


def test_parse_plan_returns_periods():
    cfg = plan_mod.parse(SAMPLE_PLAN)
    assert cfg.is_start == date(2025, 4, 1)
    assert cfg.is_end == date(2025, 9, 30)
    assert cfg.os_start == date(2025, 10, 1)
    assert cfg.os_end == date(2026, 1, 31)


def test_parse_plan_preserves_strategy_request():
    cfg = plan_mod.parse(SAMPLE_PLAN)
    assert "VPIN" in cfg.strategy_request
    assert "adaptive thresholds" in cfg.strategy_request


def test_parse_plan_merges_with_default_targets():
    """User omits a key → default from targets.yaml should be used."""
    plan_text = """# Run: minimal

## Targets
profit_factor: 1.5

## Universe
symbols: [BTCUSDT]

## IS / OS periods
is_start: 2025-03-01
is_end: 2025-09-30
os_start: 2025-10-01
os_end: 2026-01-31
"""
    cfg = plan_mod.parse(plan_text)
    assert cfg.targets["primary"]["profit_factor"]["value"] == 1.5
    # not supplied — should fall back to config/targets.yaml default (1.3)
    assert cfg.targets["primary"]["max_drawdown"]["value"] == -0.15
    # secondary / auto_reject intact from defaults
    assert cfg.targets["auto_reject"]["win_rate"]["value"] == 0.10


def test_parse_plan_single_symbol_accepted():
    plan_text = """# Run: x

## Targets
profit_factor: 1.3

## Universe
symbols: [BTCUSDT]

## IS / OS periods
is_start: 2025-03-01
is_end: 2025-09-30
os_start: 2025-10-01
os_end: 2026-01-31
"""
    cfg = plan_mod.parse(plan_text)
    assert cfg.symbols == ["BTCUSDT"]


def test_parse_plan_ignores_commented_lines():
    plan_text = """# Run: x

## Targets
# this is a comment
profit_factor: 1.3
# max_drawdown: -0.99  <- commented out, should use default

## Universe
symbols: [BTCUSDT]

## IS / OS periods
is_start: 2025-03-01
is_end: 2025-09-30
os_start: 2025-10-01
os_end: 2026-01-31
"""
    cfg = plan_mod.parse(plan_text)
    assert cfg.targets["primary"]["max_drawdown"]["value"] == -0.15  # default


def test_parse_plan_rejects_invalid_os_is_ordering():
    plan_text = """# Run: x

## Targets
profit_factor: 1.3

## Universe
symbols: [BTCUSDT]

## IS / OS periods
is_start: 2025-10-01
is_end: 2026-01-31
os_start: 2025-03-01
os_end: 2025-09-30
"""
    with pytest.raises(plan_mod.PlanError):
        plan_mod.parse(plan_text)  # OS precedes IS — data leakage risk


def test_parse_plan_rejects_overlapping_is_os():
    plan_text = """# Run: x

## Targets
profit_factor: 1.3

## Universe
symbols: [BTCUSDT]

## IS / OS periods
is_start: 2025-03-01
is_end: 2025-11-30
os_start: 2025-10-01
os_end: 2026-01-31
"""
    with pytest.raises(plan_mod.PlanError):
        plan_mod.parse(plan_text)


def test_parse_plan_rejects_missing_section():
    plan_text = """# Run: x

## Universe
symbols: [BTCUSDT]

## IS / OS periods
is_start: 2025-03-01
is_end: 2025-09-30
os_start: 2025-10-01
os_end: 2026-01-31
"""
    with pytest.raises(plan_mod.PlanError) as exc:
        plan_mod.parse(plan_text)
    assert "Targets" in str(exc.value) or "targets" in str(exc.value).lower()


def test_parse_plan_from_file(tmp_path):
    plan_path = tmp_path / "PLAN.md"
    plan_path.write_text(SAMPLE_PLAN)
    cfg = plan_mod.parse_file(plan_path)
    assert cfg.symbols == ["BTCUSDT", "ETHUSDT"]
