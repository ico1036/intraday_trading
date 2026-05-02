"""Tests for agent workflow helper functions in scripts/agent/run.py.

These are non-runtime orchestration utilities that are easy to regress accidentally
when prompts or workspace discovery logic changes.
"""

from __future__ import annotations

from pathlib import Path
import os
import time

import pytest

from scripts.agent import run as workflow_run


@pytest.fixture
def workspace_dir(tmp_path: Path) -> Path:
    path = tmp_path / "sample_strategy_dir"
    path.mkdir()
    return path


def test_check_and_consume_signal_roundtrip(workspace_dir: Path):
    signal_file = workspace_dir / "APPROVED.signal"

    # no file yet
    assert workflow_run.check_and_consume_signal(workspace_dir, "APPROVED.signal") is False

    # create and consume once
    signal_file.write_text("APPROVED", encoding="utf-8")
    assert workflow_run.check_and_consume_signal(workspace_dir, "APPROVED.signal") is True
    assert not signal_file.exists()

    # idempotent false after consumed
    assert workflow_run.check_and_consume_signal(workspace_dir, "APPROVED.signal") is False


def test_get_orchestrator_prompt_contains_workflow_contract(monkeypatch):
    # keep current env stable
    prompt = workflow_run.get_orchestrator_prompt()

    assert "Orchestrator Agent" in prompt
    assert "Phase 1: Research" in prompt
    assert "APPROVED" in prompt
    assert "NEED_IMPROVEMENT" in prompt
    assert "CONCEPT_INVALID" in prompt


def test_find_new_workspace_dir_single_new_directory(tmp_path: Path, monkeypatch):
    existing_old = {tmp_path / "existing_1_dir", tmp_path / "existing_2_dir"}
    for d in existing_old:
        d.mkdir()

    new_workspace = tmp_path / "new_1_dir"
    new_workspace.mkdir()

    monkeypatch.setattr(
        workflow_run,
        "get_existing_workspace_dirs",
        lambda: existing_old | {new_workspace},
    )

    found = workflow_run.find_new_workspace_dir(existing_old)
    assert found == new_workspace


def test_find_new_workspace_dir_latest_when_multiple_new(tmp_path: Path, monkeypatch):
    existing = {tmp_path / "existing_1_dir", tmp_path / "existing_2_dir"}
    for d in existing:
        d.mkdir()

    newest = tmp_path / "new_newest_dir"
    oldest = tmp_path / "new_oldest_dir"
    newest.mkdir()
    oldest.mkdir()

    # force mtime ordering
    now = time.time()
    os.utime(oldest, (now - 20, now - 20))
    os.utime(newest, (now, now))

    monkeypatch.setattr(
        workflow_run,
        "get_existing_workspace_dirs",
        lambda: existing | {newest, oldest},
    )

    found = workflow_run.find_new_workspace_dir(existing)
    assert found == newest


def test_find_new_workspace_dir_none_when_no_change(tmp_path: Path, monkeypatch):
    existing = {tmp_path / "existing_1_dir"}
    for d in existing:
        d.mkdir()

    monkeypatch.setattr(workflow_run, "get_existing_workspace_dirs", lambda: existing)

    found = workflow_run.find_new_workspace_dir(existing)
    assert found is None


def test_tick_template_is_marked_and_not_empty():
    from intraday.strategies.tick import _template as tick_t

    source = Path(tick_t.__file__).read_text(encoding="utf-8")

    # Basic integrity checks for agent-edit expectations
    assert "class MyTickStrategy" in source
    assert "StrategyBase" in source
    assert "setup(self)" in source
    assert "should_buy(self, state" in source
    assert "should_sell(self, state" in source
    assert "# <<< DO NOT MODIFY" in source
    assert "필수 규칙" in source
