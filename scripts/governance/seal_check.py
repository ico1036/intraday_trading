#!/usr/bin/env python3
"""PreToolUse hook: block agent access to sealed OS-window artifacts.

Two layouts are protected:

1. **Legacy two-dir layout**: ``archive/<run>/alphas/<aid>/os/...`` — any
   path under the per-alpha ``os/`` subfolder is blocked. The ``is/``
   subfolder is freely readable.

2. **Flat loader-gateway layout**: ``archive/<run>/alphas/<aid>/<file>``
   where backtest runs once across IS+OS and writes a single set of
   artifacts. ``metrics.json`` carries the OS sub-block, the raw parquet
   carries every OS timestamp, and ``backtest_report.md`` contains the
   full-period summary. Direct reads leak OS data, so the hook blocks
   the canonical filenames and the agent must use
   ``scripts/tools/load_alpha.py`` (default split=is) to read anything.

Set ``SEAL_OPEN=1`` in the environment to bypass either pattern during
the evaluation phase only.

Exit codes:
    0 - allow
    2 - block (stderr shown to model)
"""
from __future__ import annotations

import json
import os
import re
import sys

SEAL_LEGACY_RE = re.compile(r"\barchive/[^/\s\"']+/alphas/[^/\s\"']+/os\b")
SEAL_FLAT_RE = re.compile(
    r"\barchive/[^/\s\"']+/alphas/[^/\s\"']+/"
    r"(metrics|equity_curve|trades|weights|backtest_report|summary)"
    r"\.(json|parquet|csv|md)\b"
)
SEAL_PATTERNS = (SEAL_LEGACY_RE, SEAL_FLAT_RE)

PATH_KEYS = (
    "file_path",
    "path",
    "pattern",
    "command",
    "notebook_path",
    "glob",
)

BLOCK_MSG = (
    "OS sealed: this path under archive/<run>/alphas/<aid>/ exposes "
    "OS-window data (either the os/ subfolder or the flat-layout artifact "
    "that bundles IS+OS in one file). Use scripts/tools/load_alpha.py "
    "with --split is to read sanctioned IS-only views. Set SEAL_OPEN=1 "
    "in env to bypass for the evaluation phase only."
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
        if not isinstance(val, str):
            continue
        for pattern in SEAL_PATTERNS:
            if pattern.search(val):
                print(BLOCK_MSG, file=sys.stderr)
                return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
