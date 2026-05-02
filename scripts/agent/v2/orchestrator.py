"""Pure-Python orchestrator core.

No Claude SDK dependency. Tests inject a ``ScriptedCoordinator`` that
implements the :class:`AgentCoordinator` protocol. Real wiring in
``run_v2.py`` swaps in an SDK-backed coordinator.

Data flow per iteration:

    1. Pick active thesis (or mint a new one if all prior are terminal).
    2. Run the research phase (``new_thesis`` on first-of-thesis, else
       ``compose_expression``).
    3. Persist ``algorithm_prompt.txt`` under the expression directory.
    4. Run the development phase → strategy code.
    5. Run the analysis phase → returns ``(metrics, failure_mode)``.
    6. Build seen list, run thesis_gate → verdict.
    7. Write verdict.md.
    8. Append to expression_log.jsonl (and seen_failure_modes.jsonl).
    9. Regenerate research_map.md.
    10. Run exit_check → maybe write DONE and return.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol

from scripts.agent.v2 import algorithm_prompt as ap
from scripts.agent.v2 import expression_log as elog
from scripts.agent.v2.deterministic import (
    exit_check,
    plan as plan_mod,
    thesis_gate,
    within_run_digest,
)


# ---------------------------------------------------------------------------
# Agent request / response dataclasses.
# ---------------------------------------------------------------------------


@dataclass
class NewThesisRequest:
    run_id: str
    thesis_id: str
    plan: plan_mod.PlanConfig
    research_map: str
    refuted_fingerprints: list[str] = field(default_factory=list)


@dataclass
class NewThesisResponse:
    thesis_md_text: str
    algorithm_prompt_text: str


@dataclass
class ComposeExpressionRequest:
    run_id: str
    thesis_id: str
    thesis_md: str
    prior_seen: list[dict]
    research_map: str
    verdict_hints: list[str]
    addresses_hint: str | None


@dataclass
class ComposeExpressionResponse:
    algorithm_prompt_text: str


@dataclass
class DeveloperRequest:
    algorithm_prompt: ap.AlgorithmPrompt
    workdir: Path


@dataclass
class DeveloperResponse:
    ok: bool


@dataclass
class AnalystRequest:
    algorithm_prompt: ap.AlgorithmPrompt
    workdir: Path
    plan: plan_mod.PlanConfig


@dataclass
class AnalystResponse:
    failure_mode: str
    metrics: Mapping[str, Any]


class AgentCoordinator(Protocol):
    def new_thesis(self, req: NewThesisRequest) -> NewThesisResponse: ...
    def compose_expression(
        self, req: ComposeExpressionRequest
    ) -> ComposeExpressionResponse: ...
    def develop(self, req: DeveloperRequest) -> DeveloperResponse: ...
    def analyze(self, req: AnalystRequest) -> AnalystResponse: ...


# ---------------------------------------------------------------------------
# Result type.
# ---------------------------------------------------------------------------


@dataclass
class RunResult:
    decision: exit_check.ExitDecision
    iterations: int


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


_TERMINAL_STATUSES = frozenset({"REFUTED", "APPROVED"})


def _next_thesis_id(run_dir: Path) -> str:
    existing = sorted((run_dir / "theses").glob("th_*"))
    return f"th_{len(existing):03d}"


def _load_research_map(run_dir: Path) -> str:
    path = run_dir / "research_map.md"
    return path.read_text() if path.exists() else ""


def _load_refuted_fingerprints(run_dir: Path) -> list[str]:
    """List fingerprints of theses refuted in this run (from their frontmatter)."""
    out: list[str] = []
    for thesis_dir in sorted((run_dir / "theses").glob("th_*")):
        verdict_path = thesis_dir / "verdict.md"
        if not verdict_path.exists():
            continue
        verdict_txt = verdict_path.read_text()
        if "verdict: REFUTED" not in verdict_txt:
            continue
        thesis_path = thesis_dir / "thesis.md"
        if not thesis_path.exists():
            continue
        for line in thesis_path.read_text().splitlines():
            line = line.strip()
            if line.startswith("fingerprint:"):
                out.append(line.split(":", 1)[1].strip())
                break
    return out


def _load_seen_for_thesis(run_dir: Path, thesis_id: str) -> list[dict]:
    path = run_dir / "theses" / thesis_id / "seen_failure_modes.jsonl"
    if not path.exists():
        return []
    return thesis_gate.load_seen(path)


def _load_verdict_status(run_dir: Path, thesis_id: str) -> str | None:
    path = run_dir / "theses" / thesis_id / "verdict.md"
    if not path.exists():
        return None
    for line in path.read_text().splitlines():
        line = line.strip()
        if line.startswith("verdict:"):
            return line.split(":", 1)[1].strip()
    return None


def _load_verdict_hints(run_dir: Path, thesis_id: str) -> list[str]:
    path = run_dir / "theses" / thesis_id / "verdict.md"
    if not path.exists():
        return []
    for line in path.read_text().splitlines():
        s = line.strip()
        if s.startswith("hints:"):
            raw = s.split(":", 1)[1].strip().strip("[]")
            return [x.strip() for x in raw.split(",") if x.strip()]
    return []


def _pick_active_thesis(
    run_dir: Path,
    plan: plan_mod.PlanConfig,
) -> str | None:
    """Return the ``thesis_id`` of a thesis still eligible for more expressions.

    Eligible = verdict status is not terminal AND expression count hasn't
    hit ``max_expressions_per_thesis``.
    """
    cap = int(plan.targets["budget"]["max_expressions_per_thesis"])
    for thesis_dir in sorted((run_dir / "theses").glob("th_*")):
        thesis_id = thesis_dir.name
        status = _load_verdict_status(run_dir, thesis_id) or "ACTIVE"
        if status in _TERMINAL_STATUSES:
            continue
        n_expr = len(list((thesis_dir / "expressions").glob("exp_*")))
        if n_expr >= cap:
            continue
        return thesis_id
    return None


def _write_thesis(run_dir: Path, thesis_id: str, text: str) -> Path:
    thesis_dir = run_dir / "theses" / thesis_id
    thesis_dir.mkdir(parents=True, exist_ok=True)
    (thesis_dir / "expressions").mkdir(exist_ok=True)
    path = thesis_dir / "thesis.md"
    path.write_text(text)
    return path


def _load_thesis_md(run_dir: Path, thesis_id: str) -> str:
    path = run_dir / "theses" / thesis_id / "thesis.md"
    return path.read_text() if path.exists() else ""


def _latest_failure_mode(seen: list[dict]) -> str | None:
    return seen[-1]["failure_mode"] if seen else None


# ---------------------------------------------------------------------------
# Main loop.
# ---------------------------------------------------------------------------


def run(
    *,
    run_dir: Path,
    plan: plan_mod.PlanConfig,
    coord: AgentCoordinator,
    max_iterations: int = 1000,
) -> RunResult:
    run_id = run_dir.name

    for iter_idx in range(max_iterations):
        iter_start = time.perf_counter()
        active_thesis = _pick_active_thesis(run_dir, plan)

        # ----- 1. Research phase: new_thesis or compose_expression ----------
        if active_thesis is None:
            # Check budget: can we even mint another thesis?
            n_theses = len(list((run_dir / "theses").glob("th_*")))
            if n_theses >= int(plan.targets["budget"]["max_theses_per_run"]):
                # Fall through — exit_check below will report THESES_EXHAUSTED.
                log = exit_check.load_log(run_dir / "expression_log.jsonl")
                decision = exit_check.decide(log, budget=plan.targets["budget"])
                if decision.should_exit:
                    exit_check.write_done(run_dir, decision)
                    return RunResult(decision=decision, iterations=iter_idx)
                # If exit_check still says continue (no terminal verdict for
                # every thesis), we cannot make progress — bail out.
                decision = exit_check.ExitDecision(
                    should_exit=True, reason="STUCK_NO_ACTIVE_THESIS"
                )
                exit_check.write_done(run_dir, decision)
                return RunResult(decision=decision, iterations=iter_idx)

            thesis_id = _next_thesis_id(run_dir)
            req_new = NewThesisRequest(
                run_id=run_id,
                thesis_id=thesis_id,
                plan=plan,
                research_map=_load_research_map(run_dir),
                refuted_fingerprints=_load_refuted_fingerprints(run_dir),
            )
            resp_new = coord.new_thesis(req_new)
            _write_thesis(run_dir, thesis_id, resp_new.thesis_md_text)
            active_thesis = thesis_id
            expr_text = resp_new.algorithm_prompt_text
        else:
            thesis_id = active_thesis
            seen = _load_seen_for_thesis(run_dir, thesis_id)
            addresses_hint = None
            if seen:
                prev_exp = seen[-1]["expression_id"]
                prev_mode = seen[-1]["failure_mode"]
                addresses_hint = f"{prev_exp}:{prev_mode}"
            req_comp = ComposeExpressionRequest(
                run_id=run_id,
                thesis_id=thesis_id,
                thesis_md=_load_thesis_md(run_dir, thesis_id),
                prior_seen=seen,
                research_map=_load_research_map(run_dir),
                verdict_hints=_load_verdict_hints(run_dir, thesis_id),
                addresses_hint=addresses_hint,
            )
            resp_comp = coord.compose_expression(req_comp)
            expr_text = resp_comp.algorithm_prompt_text

        # ----- 2. Persist algorithm_prompt ----------------------------------
        parsed = ap.parse(expr_text)
        exp_dir = (
            run_dir / "theses" / thesis_id / "expressions" / parsed.expression_id
        )
        exp_dir.mkdir(parents=True, exist_ok=True)
        (exp_dir / "algorithm_prompt.txt").write_text(expr_text)

        # ----- 3. Development phase ----------------------------------------
        coord.develop(DeveloperRequest(algorithm_prompt=parsed, workdir=exp_dir))

        # ----- 4. Analysis phase -------------------------------------------
        analyst_resp = coord.analyze(
            AnalystRequest(algorithm_prompt=parsed, workdir=exp_dir, plan=plan)
        )

        # ----- 5. Gate ------------------------------------------------------
        seen = _load_seen_for_thesis(run_dir, thesis_id)
        seen.append(
            {
                "expression_id": parsed.expression_id,
                "failure_mode": analyst_resp.failure_mode,
                "expression_spec": parsed.expression_spec,
            }
        )
        verdict = thesis_gate.decide(seen)
        (run_dir / "theses" / thesis_id / "verdict.md").write_text(
            thesis_gate.render_markdown(verdict, thesis_id=thesis_id)
        )

        # ----- 6. Append to run log -----------------------------------------
        iter_duration_s = round(time.perf_counter() - iter_start, 3)
        entry = elog.ExpressionLogEntry(
            run_id=run_id,
            thesis_id=thesis_id,
            expression_id=parsed.expression_id,
            expression_spec=parsed.expression_spec,
            features_used=parsed.features_used,
            failure_mode=analyst_resp.failure_mode,
            verdict_after=verdict.status,
            artifact_path=str(exp_dir.relative_to(run_dir.parent.parent)),
            result=dict(analyst_resp.metrics),
            addresses=parsed.addresses,
            iter_duration_s=iter_duration_s,
        )
        elog.append(run_dir, entry)

        # ----- 7. Research map refresh --------------------------------------
        within_run_digest.write_from_file(
            run_dir / "expression_log.jsonl",
            run_dir / "research_map.md",
            run_id=run_id,
        )

        # ----- 8. Exit check ------------------------------------------------
        log = exit_check.load_log(run_dir / "expression_log.jsonl")
        decision = exit_check.decide(log, budget=plan.targets["budget"])
        if decision.should_exit:
            exit_check.write_done(run_dir, decision)
            return RunResult(decision=decision, iterations=iter_idx + 1)

    decision = exit_check.ExitDecision(
        should_exit=True, reason="MAX_ITERATIONS_HIT"
    )
    exit_check.write_done(run_dir, decision)
    return RunResult(decision=decision, iterations=max_iterations)
