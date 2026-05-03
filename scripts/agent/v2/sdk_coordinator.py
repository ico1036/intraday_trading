"""Claude Agent SDK adapter for the v2 orchestrator.

Implements the :class:`~scripts.agent.v2.orchestrator.AgentCoordinator`
protocol by dispatching each phase prompt to one SDK agent and reading back
the artefacts it wrote to disk.

The LLM-facing part is ``_invoke`` — a single synchronous shim that we
monkeypatch in tests to avoid real SDK calls while still exercising the
file-parsing logic around it.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from scripts.agent.v2 import orchestrator as orch
from scripts.agent.v2.agents import analyst, developer, researcher
from scripts.agent.v2.deterministic import plan as plan_mod


# ---------------------------------------------------------------------------
# Invoke signature — test-swappable.
# ---------------------------------------------------------------------------


InvokeFn = Callable[[str, str], None]
"""``(phase_name, task_prompt) -> None``; side-effects are on-disk files."""


# ---------------------------------------------------------------------------
# Coordinator.
# ---------------------------------------------------------------------------


@dataclass
class SDKCoordinator:
    run_dir: Path
    plan: plan_mod.PlanConfig
    invoke: InvokeFn
    plan_path: Path | None = None
    strategy_root: Path = field(
        default_factory=lambda: Path(__file__).resolve().parents[3]
        / "src"
        / "intraday"
        / "strategies"
        / "multi"
    )

    # ------------------------------------------------------------------ research phase

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

    # ------------------------------------------------------------------ development phase

    def develop(self, req: orch.DeveloperRequest) -> orch.DeveloperResponse:
        ap_path = req.workdir / "algorithm_prompt.txt"
        prompt = developer.task_prompt(
            algorithm_prompt_path=str(ap_path),
            workdir=str(req.workdir),
        )
        self.invoke("developer", prompt)
        expected = _expected_strategy_path(req.algorithm_prompt, self.strategy_root)
        if not expected.is_file():
            raise SDKCoordinatorError(
                f"developer did not produce strategy file {expected}"
            )
        class_name = _strategy_class_name(req.algorithm_prompt)
        if class_name not in expected.read_text():
            raise SDKCoordinatorError(
                f"developer strategy file {expected} does not define {class_name}"
            )
        return orch.DeveloperResponse(ok=True)

    # ------------------------------------------------------------------ analysis phase

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


_STRATEGY_RE = re.compile(r"^#\s*Strategy:\s*([A-Za-z_][A-Za-z0-9_]*)\s*$", re.M)


def _strategy_class_name(prompt: Any) -> str:
    match = _STRATEGY_RE.search(prompt.body)
    if not match:
        raise SDKCoordinatorError("algorithm_prompt body missing '# Strategy: <ClassName>'")
    return match.group(1)


def _class_to_snake(name: str) -> str:
    out = []
    for idx, char in enumerate(name):
        if char.isupper() and idx > 0 and (not name[idx - 1].isupper()):
            out.append("_")
        out.append(char.lower())
    return "".join(out)


def _expected_strategy_path(prompt: Any, strategy_root: Path) -> Path:
    return Path(strategy_root) / f"{_class_to_snake(_strategy_class_name(prompt))}.py"
