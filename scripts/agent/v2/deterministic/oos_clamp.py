"""PreToolUse hook that clamps out-of-sample dates before Write/Edit fires.

Agents sometimes invent dates past the held-out window when composing
algorithm_prompt.txt or backtest configs. This hook intercepts Write/Edit
tool calls and rewrites any ``YYYY-MM-DD`` date past the run's
``os_end`` to ``os_end`` itself, deterministically.

The hook is registered in ``.claude/settings.json`` under ``PreToolUse`` in
Phase 3. For now we expose the pure functions it depends on so that
thesis_gate / exit_check do not need to wait on hook plumbing.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from scripts.agent.v2.deterministic import plan as plan_mod


_DATE_RE = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")


# ---------------------------------------------------------------------------
# Pure functions.
# ---------------------------------------------------------------------------


def clamp_text(text: str, *, os_end: date) -> tuple[str, list[tuple[str, str]]]:
    """Replace every parseable date > ``os_end`` with ``os_end``.

    Returns the clamped text plus a list of ``(original, replacement)`` pairs
    for logging.
    """
    replacements: list[tuple[str, str]] = []

    def _sub(m: re.Match) -> str:
        s = m.group(1)
        try:
            d = date.fromisoformat(s)
        except ValueError:
            return s  # not actually a valid date (e.g. 2026-13-40)
        if d <= os_end:
            return s
        new = os_end.isoformat()
        replacements.append((s, new))
        return new

    return _DATE_RE.sub(_sub, text), replacements


_WRITE_LIKE_TOOLS = {"Write", "Edit"}
_FIELDS_BY_TOOL = {
    "Write": ("content",),
    "Edit": ("old_string", "new_string"),
}


def clamp_tool_input(
    tool_name: str,
    tool_input: Mapping[str, Any],
    *,
    os_end: date,
) -> dict[str, Any]:
    """Return a clamped copy of ``tool_input``; non-write tools pass through."""
    if tool_name not in _WRITE_LIKE_TOOLS:
        return dict(tool_input)
    fields = _FIELDS_BY_TOOL[tool_name]
    out = dict(tool_input)
    for f in fields:
        if f in out and isinstance(out[f], str):
            out[f], _ = clamp_text(out[f], os_end=os_end)
    return out


# ---------------------------------------------------------------------------
# os_end resolution.
# ---------------------------------------------------------------------------


def load_os_end(run_dir: Path | str) -> date | None:
    """Read ``os_end`` from ``<run_dir>/PLAN.md`` or return ``None``."""
    plan_path = Path(run_dir) / "PLAN.md"
    if not plan_path.exists():
        return None
    cfg = plan_mod.parse_file(plan_path)
    return cfg.os_end


# ---------------------------------------------------------------------------
# SDK hook factory. Wired in .claude/settings.json during Phase 3.
# ---------------------------------------------------------------------------


def build_hook(os_end: date):
    """Return an async hook callable matching Claude Agent SDK's PreToolUse."""

    async def _hook(input_data, tool_use_id, _context):  # noqa: ARG001
        tool_name = input_data.get("tool_name")
        if tool_name not in _WRITE_LIKE_TOOLS:
            return {}
        tool_input = input_data.get("tool_input", {}) or {}
        clamped = clamp_tool_input(tool_name, tool_input, os_end=os_end)
        if clamped == tool_input:
            return {}
        # SDK convention: return ``{"tool_input": ...}`` to override.
        return {"tool_input": clamped}

    return _hook
