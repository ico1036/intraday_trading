"""Decide whether a run should terminate.

Called at the end of each orchestrator iteration with the run's
``expression_log.jsonl`` and the budget block from the PLAN's merged targets.
On ``should_exit``, the orchestrator writes a ``DONE`` sentinel in
``archive/<run_id>/``.

Priority order:

    1. TARGETS_MET     — any entry with failure_mode=APPROVED
    2. MAX_TRIALS      — len(log) >= budget.max_trials
    3. THESES_EXHAUSTED — distinct theses >= max_theses_per_run AND every
       thesis has a REFUTED terminal verdict (EXHAUSTED/SCOPE_RESTRICTED do
       not count — they route back to compose_expression)
    4. CONTINUE
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence


class ExitCheckError(RuntimeError):
    """Raised when a caller asks for the DONE sentinel without an exit decision."""


@dataclass
class ExitDecision:
    should_exit: bool
    reason: str | None = None
    winning_expression: str | None = None
    meta: dict | None = None


# Verdicts that mean "this thesis is done for this run — cannot come back".
_TERMINAL_THESIS_VERDICTS = {"REFUTED"}


# ---------------------------------------------------------------------------
# Decision.
# ---------------------------------------------------------------------------


def decide(
    log: Sequence[Mapping],
    *,
    budget: Mapping,
) -> ExitDecision:
    # Priority 1 — APPROVED wins over everything, even budget exhaustion.
    for entry in log:
        if entry.get("failure_mode") == "APPROVED":
            return ExitDecision(
                should_exit=True,
                reason="TARGETS_MET",
                winning_expression=entry.get("expression_id"),
            )

    max_trials = int(budget.get("max_trials", 0))
    if max_trials > 0 and len(log) >= max_trials:
        return ExitDecision(
            should_exit=True,
            reason="MAX_TRIALS",
            meta={"trials": len(log), "limit": max_trials},
        )

    max_theses = int(budget.get("max_theses_per_run", 0))
    if max_theses > 0:
        per_thesis_last_verdict: dict[str, str | None] = {}
        for entry in log:
            tid = entry.get("thesis_id")
            if tid is None:
                continue
            per_thesis_last_verdict[tid] = entry.get("verdict_after")
        if len(per_thesis_last_verdict) >= max_theses and all(
            v in _TERMINAL_THESIS_VERDICTS
            for v in per_thesis_last_verdict.values()
        ):
            return ExitDecision(
                should_exit=True,
                reason="THESES_EXHAUSTED",
                meta={
                    "theses": list(per_thesis_last_verdict.keys()),
                    "limit": max_theses,
                },
            )

    return ExitDecision(should_exit=False)


# ---------------------------------------------------------------------------
# I/O.
# ---------------------------------------------------------------------------


def load_log(path: Path | str) -> list[dict]:
    entries: list[dict] = []
    text = Path(path).read_text() if Path(path).exists() else ""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        entries.append(json.loads(line))
    return entries


def write_done(run_dir: Path | str, decision: ExitDecision) -> Path:
    if not decision.should_exit:
        raise ExitCheckError("cannot write DONE when decision.should_exit is False")

    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    content_lines = [
        f"reason: {decision.reason or 'UNKNOWN'}",
        f"written_at: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
    ]
    if decision.winning_expression:
        content_lines.append(f"winning_expression: {decision.winning_expression}")
    if decision.meta:
        for k, v in decision.meta.items():
            content_lines.append(f"{k}: {v}")

    path = run_dir / "DONE"
    path.write_text("\n".join(content_lines) + "\n")
    return path
