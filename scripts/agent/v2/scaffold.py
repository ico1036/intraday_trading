"""Scaffolding for v2 harness runs.

Creates ``archive/<run_id>/`` skeleton and materialises ``PLAN.md`` from the
template. No agent invocation; no behaviour change for existing v1 flows.

Contract:
    - ``scaffold_run(run_id)`` is safe to call for both new and resumed runs.
    - Existing ``PLAN.md`` is NEVER overwritten unless ``force=True``.
    - Existing ``DONE`` sentinel blocks resume — caller must delete it first.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ARCHIVE_ROOT = PROJECT_ROOT / "archive"
TEMPLATE_PATH = Path(__file__).parent / "plan_template.md"
RUN_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_\-]{0,63}$")


class RunScaffoldError(Exception):
    """Raised when scaffolding cannot proceed safely."""


@dataclass
class ScaffoldResult:
    run_id: str
    path: Path
    created: bool  # True for fresh run, False for resume
    plan_path: Path


def validate_run_id(run_id: str) -> None:
    if not RUN_ID_PATTERN.match(run_id):
        raise RunScaffoldError(
            f"run_id {run_id!r} must match {RUN_ID_PATTERN.pattern}"
        )


def run_path(run_id: str) -> Path:
    return ARCHIVE_ROOT / run_id


def is_done(run_id: str) -> bool:
    return (run_path(run_id) / "DONE").exists()


def render_plan_template(run_id: str) -> str:
    template = TEMPLATE_PATH.read_text()
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return (
        template.replace("{{run_id}}", run_id).replace("{{created}}", created)
    )


def scaffold_run(run_id: str, *, force: bool = False) -> ScaffoldResult:
    """Create or resume a run directory.

    Parameters
    ----------
    run_id:
        Identifier matching :data:`RUN_ID_PATTERN`.
    force:
        If ``True``, overwrite ``PLAN.md`` and clear ``DONE`` sentinel.

    Returns
    -------
    ScaffoldResult
        Describes what was done.
    """
    validate_run_id(run_id)
    path = run_path(run_id)
    existed = path.exists()

    if existed and is_done(run_id) and not force:
        raise RunScaffoldError(
            f"run {run_id!r} is DONE; rm {path/'DONE'} to resume or use force=True"
        )

    path.mkdir(parents=True, exist_ok=True)
    (path / "theses").mkdir(exist_ok=True)
    (path / "expression_log.jsonl").touch()
    (path / "research_map.md").touch()

    plan_path = path / "PLAN.md"
    wrote_plan = False
    if not plan_path.exists() or force:
        plan_path.write_text(render_plan_template(run_id))
        wrote_plan = True

    if force and is_done(run_id):
        (path / "DONE").unlink()

    return ScaffoldResult(
        run_id=run_id,
        path=path,
        created=not existed or wrote_plan,
        plan_path=plan_path,
    )
