"""Phase 1-2 — orchestrator core contract.

The orchestrator is pure Python. It takes an injected ``AgentCoordinator``
(protocol) so tests can script agent responses without the Claude SDK. The
SDK wiring happens in ``run_v2.py`` in Phase 1-5.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.agent.v2 import (
    algorithm_prompt as ap,
    orchestrator as orch,
    scaffold,
)
from scripts.agent.v2.deterministic import plan as plan_mod


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


PLAN_TEXT = """# Run: smoke

## Targets
profit_factor: 1.3
max_drawdown: -0.15
total_return: 0.05
total_trades: 30
max_trials: 6
max_expressions_per_thesis: 3
max_theses_per_run: 2

## Strategy request
Smoke test.

## Universe
symbols: [BTCUSDT]

## IS / OS periods
is_start: 2025-03-01
is_end: 2025-09-30
os_start: 2025-10-01
os_end: 2026-01-31
"""


def _spec(**overrides):
    base = dict(
        bar_domain="VOLUME",
        bar_granularity="medium",
        signal_form="raw",
        threshold_type="absolute",
        aggregation="instantaneous",
        regime_filter="none",
        exit_rule="time_stop",
        sizing="fixed",
        universe="single_symbol",
    )
    base.update(overrides)
    return base


def _algorithm_prompt_text(thesis_id, expression_id, spec, features, addresses=None):
    return ap.build(
        thesis_id=thesis_id,
        expression_id=expression_id,
        expression_spec=spec,
        features_used=features,
        addresses=addresses,
        body="# Strategy: Smoke\n",
    )


def _thesis_md(direction="reversal", features=("vpin",)):
    return f"""---
thesis_id: th_000
fingerprint: sha256:deadbeef
status: ACTIVE
direction: {direction}
features: [{", ".join(features)}]
trigger_schema:
  when: "vpin > p90"
  side: sell
---

# Thesis
Smoke thesis body.
"""


class ScriptedCoordinator:
    """Drives agent responses from a scripted queue.

    Each orchestrator iteration consumes one item from each queue it needs:
    compose_expression (or new_thesis on first iter of a fresh thesis),
    analyze. Developer always succeeds.
    """

    def __init__(self, *, analyses, expression_specs, thesis_directions=None):
        self.analyses = list(analyses)
        self.expression_specs = list(expression_specs)
        self.thesis_directions = list(thesis_directions or ["reversal"])
        self.compose_calls = 0
        self.new_thesis_calls = 0
        self.analyze_calls = 0
        self.develop_calls = 0

    # --- researcher roles -----------------------------------------------

    def new_thesis(self, req):
        self.new_thesis_calls += 1
        direction = self.thesis_directions.pop(0)
        expression_id = "exp_001"
        spec, features = self.expression_specs.pop(0)
        prompt = _algorithm_prompt_text(req.thesis_id, expression_id, spec, features)
        return orch.NewThesisResponse(
            thesis_md_text=f"""---
thesis_id: {req.thesis_id}
fingerprint: sha256:{direction}_{len(self.thesis_directions)}
status: ACTIVE
direction: {direction}
features: {list(features)}
trigger_schema:
  when: "x"
---

# Thesis ({direction})
""",
            algorithm_prompt_text=prompt,
        )

    def compose_expression(self, req):
        self.compose_calls += 1
        spec, features = self.expression_specs.pop(0)
        expression_id = f"exp_{self.compose_calls + 1:03d}"
        prompt = _algorithm_prompt_text(
            req.thesis_id, expression_id, spec, features, addresses=req.addresses_hint
        )
        return orch.ComposeExpressionResponse(algorithm_prompt_text=prompt)

    # --- developer ------------------------------------------------------

    def develop(self, req):
        self.develop_calls += 1
        return orch.DeveloperResponse(ok=True)

    # --- analyst --------------------------------------------------------

    def analyze(self, req):
        self.analyze_calls += 1
        failure_mode, metrics = self.analyses.pop(0)
        return orch.AnalystResponse(
            failure_mode=failure_mode,
            metrics=metrics,
        )


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(scaffold, "ARCHIVE_ROOT", tmp_path)
    result = scaffold.scaffold_run("smoke", force=True)
    result.plan_path.write_text(PLAN_TEXT)
    return result.path


@pytest.fixture
def plan():
    return plan_mod.parse(PLAN_TEXT)


# ---------------------------------------------------------------------------
# APPROVED path — single expression, immediate stop.
# ---------------------------------------------------------------------------


def test_approved_first_expression_terminates_run(run_dir, plan):
    coord = ScriptedCoordinator(
        analyses=[("APPROVED", {"profit_factor": 1.8, "total_trades": 120})],
        expression_specs=[(_spec(), ["vpin"])],
    )
    result = orch.run(run_dir=run_dir, plan=plan, coord=coord)
    assert result.decision.should_exit
    assert result.decision.reason == "TARGETS_MET"
    assert (run_dir / "DONE").is_file()
    assert coord.new_thesis_calls == 1
    assert coord.compose_calls == 0
    # expression_log recorded the APPROVED entry
    lines = (run_dir / "expression_log.jsonl").read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["failure_mode"] == "APPROVED"
    assert entry["verdict_after"] == "APPROVED"


# ---------------------------------------------------------------------------
# REFUTED path — 3 orthogonal SIGNAL_NOISY on same thesis triggers new_thesis.
# ---------------------------------------------------------------------------


def test_refuted_triggers_new_thesis(run_dir, plan):
    # 3 SIGNAL_NOISY on thesis 1 (orthogonal), then APPROVED on thesis 2.
    coord = ScriptedCoordinator(
        analyses=[
            ("SIGNAL_NOISY", {"profit_factor": 1.02, "total_trades": 60, "win_rate": 0.5}),
            ("SIGNAL_NOISY", {"profit_factor": 0.98, "total_trades": 60, "win_rate": 0.5}),
            ("SIGNAL_NOISY", {"profit_factor": 1.01, "total_trades": 60, "win_rate": 0.5}),
            ("APPROVED", {"profit_factor": 1.8, "total_trades": 120}),
        ],
        expression_specs=[
            (_spec(), ["vpin"]),
            (_spec(signal_form="z_score", threshold_type="adaptive_quantile"), ["vpin"]),
            (_spec(signal_form="rolling_rank", threshold_type="regime_conditional",
                   regime_filter="vol_regime"), ["vpin"]),
            (_spec(), ["ofi"]),  # thesis 2 baseline
        ],
        thesis_directions=["reversal", "momentum"],
    )
    result = orch.run(run_dir=run_dir, plan=plan, coord=coord)
    assert result.decision.reason == "TARGETS_MET"
    assert coord.new_thesis_calls == 2  # original + after REFUTED
    # Verdict file for th_000 should be REFUTED
    verdict_text = (run_dir / "theses" / "th_000" / "verdict.md").read_text()
    assert "verdict: REFUTED" in verdict_text


# ---------------------------------------------------------------------------
# MAX_TRIALS exit.
# ---------------------------------------------------------------------------


def test_max_trials_exit(run_dir, plan):
    # All noisy, never approved, but min_evidence never triggers REFUTED since
    # we stay on the same axes → orchestrator hits MAX_TRIALS.
    # plan.max_trials = 6, plan.max_expressions_per_thesis = 3, plan.max_theses = 2.
    coord = ScriptedCoordinator(
        analyses=[
            ("LATE_ENTRY", {"profit_factor": 0.95, "total_trades": 50,
                            "win_rate": 0.4, "entry_to_peak_ratio": 0.15})
            for _ in range(6)
        ],
        expression_specs=[(_spec(), ["vpin"]) for _ in range(6)],
        thesis_directions=["reversal", "momentum"],
    )
    result = orch.run(run_dir=run_dir, plan=plan, coord=coord)
    assert result.decision.should_exit
    assert result.decision.reason == "MAX_TRIALS"


# ---------------------------------------------------------------------------
# max_expressions_per_thesis — orchestrator switches thesis when per-thesis cap hit.
# ---------------------------------------------------------------------------


def test_switches_thesis_when_per_thesis_cap_reached(run_dir, plan):
    # Thesis 1 gets 3 non-REFUTED expressions (capped at max=3 per plan),
    # then orchestrator must mint thesis 2.
    # Use SIGNAL_SPARSE (implication=expression → EXHAUSTED at 3 orthogonal).
    coord = ScriptedCoordinator(
        analyses=[
            ("SIGNAL_SPARSE", {"total_trades": 2, "profit_factor": 0}),
            ("SIGNAL_SPARSE", {"total_trades": 3, "profit_factor": 0}),
            ("SIGNAL_SPARSE", {"total_trades": 2, "profit_factor": 0}),
            # thesis 2
            ("APPROVED", {"profit_factor": 1.5, "total_trades": 80}),
        ],
        expression_specs=[
            (_spec(), ["vpin"]),
            (_spec(signal_form="z_score", threshold_type="adaptive_quantile"), ["vpin"]),
            (_spec(aggregation="ema", exit_rule="sl_tp", regime_filter="session"), ["vpin"]),
            (_spec(), ["ofi"]),
        ],
        thesis_directions=["reversal", "momentum"],
    )
    result = orch.run(run_dir=run_dir, plan=plan, coord=coord)
    assert result.decision.reason == "TARGETS_MET"
    assert coord.new_thesis_calls == 2


# ---------------------------------------------------------------------------
# Side effects — research_map.md, verdict.md, seen_failure_modes, DONE all written.
# ---------------------------------------------------------------------------


def test_iter_duration_is_recorded(run_dir, plan):
    coord = ScriptedCoordinator(
        analyses=[
            ("APPROVED", {"profit_factor": 1.8, "total_trades": 120}),
        ],
        expression_specs=[(_spec(), ["vpin"])],
    )
    orch.run(run_dir=run_dir, plan=plan, coord=coord)
    lines = (run_dir / "expression_log.jsonl").read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert "iter_duration_s" in entry
    assert isinstance(entry["iter_duration_s"], (int, float))
    assert entry["iter_duration_s"] >= 0.0


def test_all_artifacts_written(run_dir, plan):
    coord = ScriptedCoordinator(
        analyses=[
            ("SIGNAL_NOISY", {"profit_factor": 1.0, "total_trades": 60, "win_rate": 0.5}),
            ("APPROVED", {"profit_factor": 1.8, "total_trades": 120}),
        ],
        expression_specs=[
            (_spec(), ["vpin"]),
            (_spec(signal_form="z_score"), ["vpin"]),
        ],
    )
    orch.run(run_dir=run_dir, plan=plan, coord=coord)

    assert (run_dir / "research_map.md").read_text().startswith("# Research Map:")
    assert (run_dir / "theses" / "th_000" / "verdict.md").is_file()
    assert (run_dir / "theses" / "th_000" / "seen_failure_modes.jsonl").is_file()
    assert (run_dir / "DONE").is_file()

    # Expression directory contains algorithm_prompt.txt
    exp_dir = run_dir / "theses" / "th_000" / "expressions" / "exp_001"
    assert (exp_dir / "algorithm_prompt.txt").is_file()
