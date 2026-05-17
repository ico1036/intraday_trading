#!/usr/bin/env python3
"""PreToolUse hook: block agent access to sealed OS-window artifacts.

Each alpha's out-of-sample artifacts live under
``archive/<run>/alphas/<alpha_id>/os/``. During research / reflect /
planning phases the agent must not see them — peeking at OS metrics and
then iterating on the strategy is a form of look-ahead leakage that
invalidates the OOS validation.

This hook reads a PreToolUse payload from stdin and blocks any tool call
whose path-like argument matches the sealed OS pattern. Set
``SEAL_OPEN=1`` in the environment to bypass (evaluation phase only).

Exit codes:
    0 - allow
    2 - block (stderr shown to model)
"""
from __future__ import annotations

import json
import os
import re
import sys

SEAL_RE = re.compile(r"\barchive/[^/\s\"']+/alphas/[^/\s\"']+/os\b")

PATH_KEYS = (
    "file_path",
    "path",
    "pattern",
    "command",
    "notebook_path",
    "glob",
)

BLOCK_MSG = (
    "OS sealed: this path is under archive/<run>/alphas/<aid>/os/. "
    "Out-of-sample artifacts are hidden during research/reflect to prevent "
    "leakage into strategy decisions. Re-run with SEAL_OPEN=1 in env for "
    "the evaluation phase only."
)


def main() -> int:
    if os.environ.get("SEAL_OPEN") == "1":
        return 0
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    tool_input = payload.get("tool_input") or {}
    for key in PATH_KEYS:
        val = tool_input.get(key)
        if isinstance(val, str) and SEAL_RE.search(val):
            print(BLOCK_MSG, file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
