"""Claude Agent SDK adapter for the v2 orchestrator.

Implements the :class:`~scripts.agent.v2.orchestrator.AgentCoordinator`
protocol by dispatching each call to a subagent (``researcher`` /
``developer`` / ``analyst``) and reading back the artefacts they wrote to
disk.

The LLM-facing part is ``_invoke`` — a single synchronous shim that we
monkeypatch in tests to avoid real SDK calls while still exercising the
file-parsing logic around it.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from scripts.agent.v2 import orchestrator as orch
from scripts.agent.v2.agents import analyst, developer, researcher
from scripts.agent.v2.deterministic import plan as plan_mod


# ---------------------------------------------------------------------------
# Invoke signature — test-swappable.
# ---------------------------------------------------------------------------


InvokeFn = Callable[[str, str], None]
"""``(subagent_name, task_prompt) -> None``; side-effects are on-disk files."""


# ---------------------------------------------------------------------------
# Coordinator.
# ---------------------------------------------------------------------------


@dataclass
class SDKCoordinator:
    run_dir: Path
    plan: plan_mod.PlanConfig
    invoke: InvokeFn
    plan_path: Path | None = None

    # ------------------------------------------------------------------ researcher

    def new_thesis(self, req: orch.NewThesisRequest) -> orch.NewThesisResponse:
        prompt = researcher.new_thesis_task(
            run_id=req.run_id,
            thesis_id=req.thesis_id,
            strategy_request=req.plan.strategy_request,
            research_map=req.research_map,
            refuted_fingerprints=req.refuted_fingerprints,
            next_expression_id="exp_001",
        )
        self.invoke("researcher", prompt)

        thesis_path = self.run_dir / "theses" / req.thesis_id / "thesis.md"
        first_exp_path = (
            self.run_dir
            / "theses"
            / req.thesis_id
            / "expressions"
            / "exp_001"
            / "algorithm_prompt.txt"
        )
        if not thesis_path.is_file():
            raise SDKCoordinatorError(
                f"researcher did not produce {thesis_path}"
            )
        if not first_exp_path.is_file():
            raise SDKCoordinatorError(
                f"researcher did not produce {first_exp_path}"
            )
        return orch.NewThesisResponse(
            thesis_md_text=thesis_path.read_text(),
            algorithm_prompt_text=first_exp_path.read_text(),
        )

    def compose_expression(
        self, req: orch.ComposeExpressionRequest
    ) -> orch.ComposeExpressionResponse:
        next_id = _next_expression_id(self.run_dir, req.thesis_id)
        prompt = researcher.compose_expression_task(
            run_id=req.run_id,
            thesis_id=req.thesis_id,
            thesis_md=req.thesis_md,
            prior_seen=req.prior_seen,
            research_map=req.research_map,
            verdict_hints=req.verdict_hints,
            addresses_hint=req.addresses_hint,
            next_expression_id=next_id,
        )
        self.invoke("researcher", prompt)

        path = (
            self.run_dir
            / "theses"
            / req.thesis_id
            / "expressions"
            / next_id
            / "algorithm_prompt.txt"
        )
        if not path.is_file():
            raise SDKCoordinatorError(
                f"researcher did not produce {path}"
            )
        return orch.ComposeExpressionResponse(algorithm_prompt_text=path.read_text())

    # ------------------------------------------------------------------ developer

    def develop(self, req: orch.DeveloperRequest) -> orch.DeveloperResponse:
        ap_path = req.workdir / "algorithm_prompt.txt"
        prompt = developer.task_prompt(
            algorithm_prompt_path=str(ap_path),
            workdir=str(req.workdir),
        )
        self.invoke("developer", prompt)
        return orch.DeveloperResponse(ok=True)

    # ------------------------------------------------------------------ analyst

    def analyze(self, req: orch.AnalystRequest) -> orch.AnalystResponse:
        plan_path = self.plan_path or (self.run_dir / "PLAN.md")
        prompt = analyst.task_prompt(
            workdir=str(req.workdir),
            plan_path=str(plan_path),
        )
        self.invoke("analyst", prompt)

        failure_path = req.workdir / "failure_mode.txt"
        metrics_path = req.workdir / "metrics.json"
        if not failure_path.is_file():
            raise SDKCoordinatorError(
                f"analyst did not produce {failure_path}"
            )
        failure_mode = failure_path.read_text().strip().splitlines()[0]

        metrics: dict[str, Any] = {}
        if metrics_path.is_file():
            metrics = json.loads(metrics_path.read_text())

        return orch.AnalystResponse(
            failure_mode=failure_mode,
            metrics=metrics,
        )


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


class SDKCoordinatorError(RuntimeError):
    """Raised when an agent fails to produce a required artefact."""


def _next_expression_id(run_dir: Path, thesis_id: str) -> str:
    exp_dir = run_dir / "theses" / thesis_id / "expressions"
    existing = sorted(exp_dir.glob("exp_*")) if exp_dir.exists() else []
    return f"exp_{len(existing) + 1:03d}"
