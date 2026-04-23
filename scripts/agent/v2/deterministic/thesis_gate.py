"""Decide a thesis's verdict from its seen failure modes.

A **verdict** is a deterministic label on a thesis driven by the pattern of
failure modes across its expressions. The gate never touches the agent; the
orchestrator is expected to map verdict.status → next agent call.

Core rule:

    If ≥ ``min_evidence`` expressions share a failure_mode AND those
    expressions differ on ≥ ``min_orthogonal_axes`` distinct axes, then:

        implication == "thesis"     → REFUTED     (change thesis)
        implication == "expression" → EXHAUSTED   (change axis group)
        implication == "scope"      → SCOPE_RESTRICTED (add filter)

    Otherwise → ACTIVE.

"APPROVED" short-circuits all other logic.
"""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml


_FAILURE_MODES_PATH = (
    Path(__file__).resolve().parents[4] / "config" / "failure_modes.yaml"
)


def _load_implications() -> dict[str, str]:
    data = yaml.safe_load(_FAILURE_MODES_PATH.read_text())
    return {mode: spec["implication"] for mode, spec in data["modes"].items()}


MODE_IMPLICATION: dict[str, str] = _load_implications()


DEFAULT_MIN_EVIDENCE = 3
DEFAULT_MIN_ORTHOGONAL_AXES = 3


# ---------------------------------------------------------------------------
# Verdict struct.
# ---------------------------------------------------------------------------


@dataclass
class Verdict:
    status: str  # ACTIVE | EXHAUSTED | REFUTED | SCOPE_RESTRICTED | APPROVED
    next_action: str  # compose_expression | new_thesis | stop
    triggered_by: str | None = None
    orthogonality_axes: list[str] = field(default_factory=list)
    expressions_evaluated: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    rule: str | None = None


def _verdict_for_implication(implication: str) -> tuple[str, str, list[str]]:
    """Map an implication tag to (status, next_action, hints)."""
    if implication == "thesis":
        return "REFUTED", "new_thesis", ["thesis_flip_required"]
    if implication == "expression":
        return "EXHAUSTED", "compose_expression", ["new_axis_required"]
    if implication == "scope":
        return "SCOPE_RESTRICTED", "compose_expression", ["add_scope_filter"]
    # "unknown" or anything else → be conservative, stay ACTIVE
    return "ACTIVE", "compose_expression", []


# ---------------------------------------------------------------------------
# Orthogonality.
# ---------------------------------------------------------------------------


def _distinct_axes(specs: Sequence[Mapping[str, Any]]) -> list[str]:
    """Axes on which at least two of the given specs disagree."""
    if len(specs) < 2:
        return []
    all_keys: set[str] = set()
    for s in specs:
        all_keys.update(s.keys())
    distinct: list[str] = []
    for key in sorted(all_keys):
        values = {s.get(key) for s in specs}
        if len(values) > 1:
            distinct.append(key)
    return distinct


# ---------------------------------------------------------------------------
# Core decision.
# ---------------------------------------------------------------------------


def decide(
    seen: Sequence[Mapping[str, Any]],
    *,
    min_evidence: int = DEFAULT_MIN_EVIDENCE,
    min_orthogonal_axes: int = DEFAULT_MIN_ORTHOGONAL_AXES,
) -> Verdict:
    """Compute a :class:`Verdict` from the thesis's seen expressions."""
    if not seen:
        return Verdict(status="ACTIVE", next_action="compose_expression")

    # Short-circuit on APPROVED.
    for entry in seen:
        if entry.get("failure_mode") == "APPROVED":
            return Verdict(
                status="APPROVED",
                next_action="stop",
                expressions_evaluated=[entry["expression_id"]],
                rule="approved_short_circuit",
            )

    # Group by failure_mode.
    by_mode: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for entry in seen:
        mode = entry.get("failure_mode")
        if mode is None:
            continue
        by_mode[mode].append(entry)

    # Sort modes to make the decision deterministic across equal candidates.
    for mode in sorted(by_mode.keys()):
        entries = by_mode[mode]
        if len(entries) < min_evidence:
            continue

        specs = [e["expression_spec"] for e in entries]
        axes = _distinct_axes(specs)
        if len(axes) < min_orthogonal_axes:
            continue

        implication = MODE_IMPLICATION.get(mode, "unknown")
        status, next_action, hints = _verdict_for_implication(implication)
        if status == "ACTIVE":
            continue  # OTHER / unknown → keep looking

        return Verdict(
            status=status,
            next_action=next_action,
            triggered_by=mode,
            orthogonality_axes=axes,
            expressions_evaluated=[e["expression_id"] for e in entries],
            hints=hints,
            rule=(
                f"≥{min_evidence} orthogonal ({len(axes)}+ axes) failures "
                f"with implication={implication!r}"
            ),
        )

    return Verdict(status="ACTIVE", next_action="compose_expression")


# ---------------------------------------------------------------------------
# I/O.
# ---------------------------------------------------------------------------


def load_seen(jsonl_path: Path | str) -> list[dict[str, Any]]:
    """Read a ``seen_failure_modes.jsonl`` file into a list of dicts."""
    path = Path(jsonl_path)
    entries: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        entries.append(json.loads(line))
    return entries


# ---------------------------------------------------------------------------
# Markdown rendering.
# ---------------------------------------------------------------------------


def render_markdown(verdict: Verdict, *, thesis_id: str) -> str:
    """Render a ``verdict.md`` document from a :class:`Verdict`."""
    frontmatter_fields = [
        f"thesis_id: {thesis_id}",
        f"verdict: {verdict.status}",
        f"next_action: {verdict.next_action}",
    ]
    if verdict.triggered_by:
        frontmatter_fields.append(f"triggered_by: {verdict.triggered_by}")
    if verdict.orthogonality_axes:
        frontmatter_fields.append(
            "orthogonality_axes: [" + ", ".join(verdict.orthogonality_axes) + "]"
        )
    if verdict.expressions_evaluated:
        frontmatter_fields.append(
            "expressions_evaluated: [" + ", ".join(verdict.expressions_evaluated) + "]"
        )
    if verdict.hints:
        frontmatter_fields.append("hints: [" + ", ".join(verdict.hints) + "]")
    if verdict.rule:
        frontmatter_fields.append(f'rule: "{verdict.rule}"')

    frontmatter = "\n".join(frontmatter_fields)

    body = [f"# Verdict for {thesis_id}", ""]
    if verdict.status == "ACTIVE":
        body.append("No trigger crossed; keep exploring expressions.")
    elif verdict.status == "APPROVED":
        body.append("Thesis achieved targets — stop.")
    else:
        body.append(
            f"Triggered by `{verdict.triggered_by}` "
            f"across {len(verdict.expressions_evaluated)} expressions "
            f"differing on {len(verdict.orthogonality_axes)} axes."
        )
        body.append("")
        body.append("## Rule applied")
        body.append(verdict.rule or "")

    return f"---\n{frontmatter}\n---\n\n" + "\n".join(body) + "\n"
