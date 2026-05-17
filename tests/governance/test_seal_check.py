"""Tests for the OS-seal PreToolUse hook."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "governance" / "seal_check.py"


def _run(payload: dict, *, seal_open: bool = False) -> tuple[int, str]:
    env = os.environ.copy()
    env.pop("SEAL_OPEN", None)
    if seal_open:
        env["SEAL_OPEN"] = "1"
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )
    return proc.returncode, proc.stderr


def test_read_os_path_blocked():
    rc, _ = _run(
        {
            "tool_name": "Read",
            "tool_input": {"file_path": "archive/run_2026_05_c/alphas/foo/os/metrics.json"},
        }
    )
    assert rc == 2


def test_read_is_path_allowed():
    rc, _ = _run(
        {
            "tool_name": "Read",
            "tool_input": {"file_path": "archive/run_2026_05_c/alphas/foo/is/metrics.json"},
        }
    )
    assert rc == 0


def test_bash_with_os_path_blocked():
    rc, _ = _run(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "cat archive/run_X/alphas/foo/os/metrics.json"},
        }
    )
    assert rc == 2


def test_bash_without_os_path_allowed():
    rc, _ = _run(
        {
            "tool_name": "Bash",
            "tool_input": {"command": 'python -c "import os; print(os.getcwd())"'},
        }
    )
    assert rc == 0


def test_glob_into_os_blocked():
    rc, _ = _run(
        {
            "tool_name": "Glob",
            "tool_input": {"pattern": "archive/run_X/alphas/foo/os/*.parquet"},
        }
    )
    assert rc == 2


def test_grep_in_os_path_blocked():
    rc, _ = _run(
        {
            "tool_name": "Grep",
            "tool_input": {"path": "archive/run_X/alphas/foo/os/"},
        }
    )
    assert rc == 2


def test_seal_open_bypasses_os_block():
    rc, _ = _run(
        {
            "tool_name": "Read",
            "tool_input": {"file_path": "archive/run_X/alphas/foo/os/metrics.json"},
        },
        seal_open=True,
    )
    assert rc == 0


def test_oscar_filename_not_blocked():
    rc, _ = _run(
        {
            "tool_name": "Read",
            "tool_input": {"file_path": "archive/run_X/alphas/foo/oscar.py"},
        }
    )
    assert rc == 0


def test_absolute_path_blocked():
    rc, _ = _run(
        {
            "tool_name": "Read",
            "tool_input": {
                "file_path": "/Users/me/intraday_trading/archive/run_X/alphas/aid/os/file"
            },
        }
    )
    assert rc == 2


def test_empty_input_allowed():
    rc, _ = _run({"tool_name": "Read", "tool_input": {}})
    assert rc == 0


def test_block_message_in_stderr():
    _, stderr = _run(
        {
            "tool_name": "Read",
            "tool_input": {"file_path": "archive/run_X/alphas/foo/os/x"},
        }
    )
    assert "OS sealed" in stderr


def test_write_to_os_blocked():
    rc, _ = _run(
        {
            "tool_name": "Write",
            "tool_input": {"file_path": "archive/run_X/alphas/foo/os/tamper.json"},
        }
    )
    assert rc == 2
