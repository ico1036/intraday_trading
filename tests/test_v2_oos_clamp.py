"""Phase 2-6 — oos_clamp.py PreToolUse hook contract.

Before Write/Edit tool calls fire, any YYYY-MM-DD date string past the run's
``os_end`` is rewritten to ``os_end``. This deterministically prevents
agents from accidentally pulling data past the held-out window.
"""
from __future__ import annotations

from datetime import date

import pytest

from scripts.agent.v2.deterministic import oos_clamp


OS_END = date(2026, 1, 31)


# ---------------------------------------------------------------------------
# Pure text clamp.
# ---------------------------------------------------------------------------


def test_clamp_text_preserves_text_without_dates():
    text = "hello world, profit_factor: 1.3"
    clamped, replaced = oos_clamp.clamp_text(text, os_end=OS_END)
    assert clamped == text
    assert replaced == []


def test_clamp_text_preserves_dates_within_window():
    text = "start: 2025-03-01, end: 2025-09-30"
    clamped, replaced = oos_clamp.clamp_text(text, os_end=OS_END)
    assert clamped == text
    assert replaced == []


def test_clamp_text_preserves_boundary_date():
    text = "end: 2026-01-31"
    clamped, replaced = oos_clamp.clamp_text(text, os_end=OS_END)
    assert clamped == text
    assert replaced == []


def test_clamp_text_rewrites_date_past_os_end():
    text = "end: 2026-03-15"
    clamped, replaced = oos_clamp.clamp_text(text, os_end=OS_END)
    assert "2026-03-15" not in clamped
    assert "2026-01-31" in clamped
    assert replaced == [("2026-03-15", "2026-01-31")]


def test_clamp_text_rewrites_multiple_future_dates():
    text = "start: 2026-02-01, end: 2026-05-01"
    clamped, replaced = oos_clamp.clamp_text(text, os_end=OS_END)
    assert "2026-02-01" not in clamped
    assert "2026-05-01" not in clamped
    assert clamped.count("2026-01-31") == 2
    assert ("2026-02-01", "2026-01-31") in replaced
    assert ("2026-05-01", "2026-01-31") in replaced


def test_clamp_text_mixed_past_and_future_dates():
    text = "is_start: 2025-03-01, os_end: 2026-01-31, test: 2027-01-01"
    clamped, replaced = oos_clamp.clamp_text(text, os_end=OS_END)
    assert "2025-03-01" in clamped  # past, unchanged
    assert "2026-01-31" in clamped  # boundary + clamped
    assert "2027-01-01" not in clamped
    assert replaced == [("2027-01-01", "2026-01-31")]


def test_clamp_text_ignores_malformed_numbers_that_look_like_dates():
    # Reject 2026-13-40 as a valid date — leave untouched.
    text = "version: 2026-13-40"
    clamped, _ = oos_clamp.clamp_text(text, os_end=OS_END)
    assert clamped == text


def test_clamp_text_does_not_touch_longer_digit_runs():
    # 20260301 (no dashes) should NOT be matched by the date regex.
    text = "seed: 20260301-evt"
    clamped, _ = oos_clamp.clamp_text(text, os_end=OS_END)
    assert clamped == text


# ---------------------------------------------------------------------------
# Tool input clamp.
# ---------------------------------------------------------------------------


def test_clamp_write_input_content_field():
    payload = {
        "file_path": "/tmp/x.md",
        "content": "os_start: 2025-10-01\nos_end: 2026-06-15\n",
    }
    clamped = oos_clamp.clamp_tool_input("Write", payload, os_end=OS_END)
    assert "2026-06-15" not in clamped["content"]
    assert "2026-01-31" in clamped["content"]


def test_clamp_edit_input_both_strings():
    payload = {
        "file_path": "/tmp/x.md",
        "old_string": "end: 2026-03-15",
        "new_string": "end: 2026-04-30",
    }
    clamped = oos_clamp.clamp_tool_input("Edit", payload, os_end=OS_END)
    assert "2026-03-15" not in clamped["old_string"]
    assert "2026-04-30" not in clamped["new_string"]
    assert clamped["old_string"] == "end: 2026-01-31"
    assert clamped["new_string"] == "end: 2026-01-31"


def test_clamp_leaves_other_tools_alone():
    payload = {"command": "ls -la /data/2026-05-01/"}
    clamped = oos_clamp.clamp_tool_input("Bash", payload, os_end=OS_END)
    # Bash is not write-like → leave untouched.
    assert clamped == payload


def test_clamp_handles_missing_fields():
    # Edit without new_string is malformed but should not raise.
    payload = {"file_path": "/tmp/x"}
    result = oos_clamp.clamp_tool_input("Edit", payload, os_end=OS_END)
    assert result == payload


# ---------------------------------------------------------------------------
# Resolve os_end from run dir.
# ---------------------------------------------------------------------------


def test_os_end_from_run_dir(tmp_path):
    plan = tmp_path / "PLAN.md"
    plan.write_text(
        "# Run: x\n\n"
        "## Targets\nprofit_factor: 1.3\n\n"
        "## Universe\nsymbols: [BTCUSDT]\n\n"
        "## IS / OS periods\n"
        "is_start: 2025-03-01\n"
        "is_end: 2025-09-30\n"
        "os_start: 2025-10-01\n"
        "os_end: 2026-01-31\n"
    )
    got = oos_clamp.load_os_end(tmp_path)
    assert got == date(2026, 1, 31)


def test_os_end_from_missing_run_dir_returns_none(tmp_path):
    missing = tmp_path / "nonexistent"
    assert oos_clamp.load_os_end(missing) is None
