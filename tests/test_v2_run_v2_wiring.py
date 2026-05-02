"""Phase 3-3 — run_v2 SDK wiring sanity checks.

We cannot easily run a real agent session in unit tests, but we can:
    - Import the module.
    - Build the SDK invoke callable with a given ``os_end``.
    - Confirm the clamp hook is reachable and does what we expect.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

# Import the module under test (triggers imports inside).
run_v2 = pytest.importorskip("scripts.agent.run_v2")


def test_build_sdk_invoke_returns_callable():
    invoke = run_v2._build_sdk_invoke(os_end=date(2026, 1, 31))
    assert callable(invoke)


def test_clamp_hook_factory_works_for_configured_os_end():
    # Mirror what run_v2 does internally — same build_hook, same effect.
    from scripts.agent.v2.deterministic import oos_clamp

    os_end = date(2026, 1, 31)
    hook = oos_clamp.build_hook(os_end=os_end)
    assert callable(hook)

    # Sanity: invoking the hook clamps a payload with a future date.
    import asyncio

    input_data = {
        "tool_name": "Write",
        "tool_input": {"file_path": "/tmp/x", "content": "end: 2026-05-15"},
    }
    result = asyncio.run(hook(input_data, "tool_use_id_x", None))
    assert "tool_input" in result
    assert "2026-05-15" not in result["tool_input"]["content"]
    assert "2026-01-31" in result["tool_input"]["content"]


def test_run_v2_prepare_path_does_not_invoke_sdk(tmp_path, monkeypatch, capsys):
    from scripts.agent.v2 import scaffold

    monkeypatch.setattr(scaffold, "ARCHIVE_ROOT", tmp_path)

    # --prepare --no-edit: should scaffold and return without calling SDK.
    rc = run_v2.main(["cli_smoke", "--prepare", "--no-edit"])
    assert rc == 0
    assert (tmp_path / "cli_smoke" / "PLAN.md").is_file()


def test_run_v2_rejects_invalid_plan_on_run(tmp_path, monkeypatch):
    from scripts.agent.v2 import scaffold

    monkeypatch.setattr(scaffold, "ARCHIVE_ROOT", tmp_path)

    # Scaffold, then corrupt the PLAN (missing Targets section).
    rc = run_v2.main(["run_smoke", "--prepare", "--no-edit"])
    assert rc == 0
    (tmp_path / "run_smoke" / "PLAN.md").write_text("# Empty plan\n")

    # --run should fail fast on invalid PLAN.
    rc = run_v2.main(["run_smoke", "--run", "--no-edit"])
    assert rc == 3  # PLAN.md invalid exit code


def test_run_v2_refuses_run_with_placeholder_strategy_request(tmp_path, monkeypatch):
    from scripts.agent.v2 import scaffold

    monkeypatch.setattr(scaffold, "ARCHIVE_ROOT", tmp_path)

    # Scaffold with default PLAN.md — contains the <write here> placeholder.
    rc = run_v2.main(["placeholder_smoke", "--prepare", "--no-edit"])
    assert rc == 0

    # --run with --no-edit: placeholder check should fire and bail out.
    rc = run_v2.main(["placeholder_smoke", "--run", "--no-edit"])
    assert rc == 4


def test_run_v2_import_is_top_level_safe():
    """Module import must not require SDK; SDK loads lazily inside helper."""
    # Simulate a second import — should succeed without side effects.
    import importlib

    importlib.reload(run_v2)
