"""Compile ``research_map.md`` from ``expression_log.jsonl``.

Agents are permitted to read ``research_map.md``; the raw JSONL is
off-limits. This module is the ONLY permitted transform. Output must be
deterministic given identical input (no wall-clock timestamps, sorted keys).

Layout of the generated markdown:

    # Research Map: <run_id>

    ## Overview
    - Expressions: N
    - Theses: K
    - Mode distribution: …

    ## Thesis <th_id> — <N expressions>
    - Mode distribution: …
    - Axes explored: …
    - Latest: <exp_id> <mode>
    - STAGNATION warning (if the last 3 expressions for this thesis touch
      fewer than 2 distinct axes)
"""
from __future__ import annotations

import json
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Mapping, Sequence


# ---------------------------------------------------------------------------
# Core build.
# ---------------------------------------------------------------------------


def build(log: Sequence[Mapping], *, run_id: str) -> str:
    lines: list[str] = []
    lines.append(f"# Research Map: {run_id}")
    lines.append("")

    if not log:
        lines.append("_No expressions executed yet in this run._")
        lines.append("")
        return "\n".join(lines) + "\n"

    # Overview
    mode_counter: Counter[str] = Counter(
        e.get("failure_mode", "UNKNOWN") for e in log
    )
    theses = _group_by_thesis(log)

    lines.append("## Overview")
    lines.append(f"- Expressions: {len(log)}")
    lines.append(f"- Theses: {len(theses)}")
    lines.append(
        "- Mode distribution: "
        + ", ".join(f"{m}={n}" for m, n in sorted(mode_counter.items()))
    )
    lines.append("")

    # Per-thesis sections (stable order by thesis_id).
    for thesis_id in sorted(theses.keys()):
        entries = theses[thesis_id]
        lines.append(f"## Thesis {thesis_id} — {len(entries)} expressions")

        per_mode = Counter(e.get("failure_mode", "UNKNOWN") for e in entries)
        lines.append(
            "- Mode distribution: "
            + ", ".join(f"{m}={n}" for m, n in sorted(per_mode.items()))
        )

        axes = _distinct_axes([e.get("expression_spec", {}) for e in entries])
        if axes:
            lines.append("- Axes explored (with ≥2 distinct values): " + ", ".join(axes))
        else:
            lines.append("- Axes explored: _none_")

        recent = entries[-5:]
        lines.append("- Recent (up to 5):")
        for e in recent:
            lines.append(
                f"  - {e.get('expression_id')} → {e.get('failure_mode')}"
            )

        if _is_stagnating(entries):
            lines.append(
                "- **STAGNATION**: last 3 expressions touched fewer than 2 axes. "
                "Force a new axis on the next compose_expression."
            )

        if any(e.get("failure_mode") == "APPROVED" for e in entries):
            approved = [
                e["expression_id"] for e in entries
                if e.get("failure_mode") == "APPROVED"
            ]
            lines.append(f"- **APPROVED**: {', '.join(approved)}")

        lines.append("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _group_by_thesis(log: Sequence[Mapping]) -> OrderedDict[str, list[Mapping]]:
    out: OrderedDict[str, list[Mapping]] = OrderedDict()
    for entry in log:
        tid = entry.get("thesis_id")
        if tid is None:
            continue
        out.setdefault(tid, []).append(entry)
    return out


def _distinct_axes(specs: Sequence[Mapping]) -> list[str]:
    if len(specs) < 2:
        return []
    keys: set[str] = set()
    for s in specs:
        keys.update(s.keys())
    result = []
    for key in sorted(keys):
        values = {s.get(key) for s in specs}
        if len(values) > 1:
            result.append(key)
    return result


def _is_stagnating(entries: Sequence[Mapping]) -> bool:
    if len(entries) < 3:
        return False
    last3 = entries[-3:]
    specs = [e.get("expression_spec", {}) for e in last3]
    return len(_distinct_axes(specs)) < 2


# ---------------------------------------------------------------------------
# I/O wrappers.
# ---------------------------------------------------------------------------


def _load_jsonl(path: Path | str) -> list[dict]:
    text = Path(path).read_text() if Path(path).exists() else ""
    entries: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        entries.append(json.loads(line))
    return entries


def build_from_file(log_path: Path | str, *, run_id: str) -> str:
    return build(_load_jsonl(log_path), run_id=run_id)


def write_from_file(
    log_path: Path | str,
    out_path: Path | str,
    *,
    run_id: str,
) -> Path:
    md = build_from_file(log_path, run_id=run_id)
    out = Path(out_path)
    out.write_text(md)
    return out
