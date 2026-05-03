"""Phase 1-5 — SDKCoordinator file-parsing contract.

The LLM call itself is impossible to unit-test. We test the surrounding
logic: given a fake ``invoke`` that materialises the expected agent
artefacts, the coordinator returns the right response and validates the
artefacts match the protocol.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pytest

from scripts.agent.v2 import (
    algorithm_prompt as ap,
    orchestrator as orch,
    sdk_coordinator as sdk,
)
from scripts.agent.v2.deterministic import plan as plan_mod


# ---------------------------------------------------------------------------
# Fixtures.
# ---------------------------------------------------------------------------


PLAN_TEXT = """# Run: sdk_smoke

## Targets
profit_factor: 1.3
max_drawdown: -0.15
total_return: 0.05
total_trades: 30

## Strategy request
Smoke SDK coord test.

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


@pytest.fixture
def plan():
    return plan_mod.parse(PLAN_TEXT)


@pytest.fixture
def run_dir(tmp_path):
    (tmp_path / "theses").mkdir()
    (tmp_path / "PLAN.md").write_text(PLAN_TEXT)
    return tmp_path


# ---------------------------------------------------------------------------
# new_thesis — fake researcher that writes thesis.md + exp_001 prompt.
# ---------------------------------------------------------------------------


def _fake_new_thesis_invoke(run_dir: Path) -> Callable[[str, str], None]:
    def _invoke(agent: str, prompt: str) -> None:
        assert agent == "researcher"
        # Extract thesis_id from the prompt so we match test data.
        lines = [l for l in prompt.splitlines() if "thesis_id:" in l]
        assert lines, "thesis_id not in prompt"
        thesis_id = lines[0].split("thesis_id:", 1)[1].strip()
        thesis_dir = run_dir / "theses" / thesis_id
        (thesis_dir / "expressions" / "exp_001").mkdir(parents=True, exist_ok=True)
        (thesis_dir / "thesis.md").write_text(
            f"""---
thesis_id: {thesis_id}
fingerprint: sha256:aa
status: ACTIVE
direction: reversal
features: [vpin]
trigger_schema:
  when: "x"
---

# Thesis body
"""
        )
        (thesis_dir / "expressions" / "exp_001" / "algorithm_prompt.txt").write_text(
            ap.build(
                thesis_id=thesis_id,
                expression_id="exp_001",
                expression_spec=_spec(),
                features_used=["vpin"],
                addresses=None,
                body="# Strategy: Fake\n",
            )
        )
    return _invoke


def test_sdk_coordinator_new_thesis(run_dir, plan):
    coord = sdk.SDKCoordinator(
        run_dir=run_dir,
        plan=plan,
        invoke=_fake_new_thesis_invoke(run_dir),
    )
    req = orch.NewThesisRequest(
        run_id="sdk_smoke",
        thesis_id="th_000",
        plan=plan,
        research_map="",
        refuted_fingerprints=[],
    )
    resp = coord.new_thesis(req)
    assert "th_000" in resp.thesis_md_text
    assert "exp_001" in resp.algorithm_prompt_text


def test_sdk_coordinator_raises_when_new_thesis_skips_files(run_dir, plan):
    coord = sdk.SDKCoordinator(
        run_dir=run_dir,
        plan=plan,
        invoke=lambda agent, prompt: None,  # deadbeat agent
    )
    with pytest.raises(sdk.SDKCoordinatorError):
        coord.new_thesis(
            orch.NewThesisRequest(
                run_id="sdk_smoke",
                thesis_id="th_000",
                plan=plan,
                research_map="",
                refuted_fingerprints=[],
            )
        )


# ---------------------------------------------------------------------------
# compose_expression — fake researcher writes next exp_NNN file.
# ---------------------------------------------------------------------------


def test_sdk_coordinator_compose_expression(run_dir, plan):
    # Pre-seed thesis 000 with exp_001 already there
    thesis_dir = run_dir / "theses" / "th_000"
    (thesis_dir / "expressions" / "exp_001").mkdir(parents=True)
    (thesis_dir / "expressions" / "exp_001" / "algorithm_prompt.txt").write_text(
        ap.build(
            thesis_id="th_000",
            expression_id="exp_001",
            expression_spec=_spec(),
            features_used=["vpin"],
            addresses=None,
            body="# Strategy: Seed\n",
        )
    )

    def _invoke(agent, prompt):
        # Next expression id should be exp_002
        assert "exp_002" in prompt
        (thesis_dir / "expressions" / "exp_002").mkdir(parents=True)
        (thesis_dir / "expressions" / "exp_002" / "algorithm_prompt.txt").write_text(
            ap.build(
                thesis_id="th_000",
                expression_id="exp_002",
                expression_spec=_spec(signal_form="z_score"),
                features_used=["vpin"],
                addresses="exp_001:SIGNAL_NOISY",
                body="# Strategy: Second\n",
            )
        )

    coord = sdk.SDKCoordinator(run_dir=run_dir, plan=plan, invoke=_invoke)
    req = orch.ComposeExpressionRequest(
        run_id="sdk_smoke",
        thesis_id="th_000",
        thesis_md="# thesis",
        prior_seen=[
            {
                "expression_id": "exp_001",
                "failure_mode": "SIGNAL_NOISY",
                "expression_spec": _spec(),
            }
        ],
        research_map="",
        verdict_hints=["new_axis_required"],
        addresses_hint="exp_001:SIGNAL_NOISY",
    )
    resp = coord.compose_expression(req)
    assert "exp_002" in resp.algorithm_prompt_text


# ---------------------------------------------------------------------------
# developer — just ok=True after invoke.
# ---------------------------------------------------------------------------


def test_sdk_coordinator_develop_returns_ok(tmp_path, plan):
    called = {"count": 0}
    strategy_root = tmp_path / "strategies" / "multi"
    strategy_root.mkdir(parents=True)

    def _invoke(agent, prompt):
        assert agent == "developer"
        called["count"] += 1
        (strategy_root / "x.py").write_text("class X:\n    pass\n")

    workdir = tmp_path / "wd"
    workdir.mkdir()
    # Minimal algorithm_prompt file for the developer task prompt reference
    (workdir / "algorithm_prompt.txt").write_text(
        ap.build(
            thesis_id="th_000",
            expression_id="exp_001",
            expression_spec=_spec(),
            features_used=["vpin"],
            addresses=None,
            body="# Strategy: X\n",
        )
    )
    parsed = ap.parse((workdir / "algorithm_prompt.txt").read_text())

    coord = sdk.SDKCoordinator(
        run_dir=tmp_path,
        plan=plan,
        invoke=_invoke,
        strategy_root=strategy_root,
    )
    resp = coord.develop(orch.DeveloperRequest(algorithm_prompt=parsed, workdir=workdir))
    assert resp.ok
    assert called["count"] == 1


def test_sdk_coordinator_develop_requires_strategy_in_strategy_root(tmp_path, plan):
    strategy_root = tmp_path / "strategies" / "multi"
    strategy_root.mkdir(parents=True)
    workdir = tmp_path / "wd"
    workdir.mkdir()
    (workdir / "algorithm_prompt.txt").write_text(
        ap.build(
            thesis_id="th_000",
            expression_id="exp_001",
            expression_spec=_spec(),
            features_used=["vpin"],
            addresses=None,
            body="# Strategy: MissingAlpha\n",
        )
    )
    parsed = ap.parse((workdir / "algorithm_prompt.txt").read_text())

    coord = sdk.SDKCoordinator(
        run_dir=tmp_path,
        plan=plan,
        invoke=lambda *_: None,
        strategy_root=strategy_root,
    )

    with pytest.raises(sdk.SDKCoordinatorError, match="strategy file"):
        coord.develop(orch.DeveloperRequest(algorithm_prompt=parsed, workdir=workdir))


# ---------------------------------------------------------------------------
# analyst — reads failure_mode.txt and metrics.json.
# ---------------------------------------------------------------------------


def test_sdk_coordinator_analyze(tmp_path, plan):
    workdir = tmp_path / "wd"
    workdir.mkdir()
    (workdir / "algorithm_prompt.txt").write_text(
        ap.build(
            thesis_id="th_000",
            expression_id="exp_001",
            expression_spec=_spec(),
            features_used=["vpin"],
            addresses=None,
            body="# Strategy: Smoke\n",
        )
    )
    parsed = ap.parse((workdir / "algorithm_prompt.txt").read_text())

    def _invoke(agent, prompt):
        assert agent == "analyst"
        (workdir / "failure_mode.txt").write_text("SIGNAL_NOISY\n")
        (workdir / "metrics.json").write_text(
            json.dumps(
                {
                    "profit_factor": 1.0,
                    "total_trades": 60,
                    "win_rate": 0.5,
                }
            )
        )

    coord = sdk.SDKCoordinator(run_dir=tmp_path, plan=plan, invoke=_invoke)
    resp = coord.analyze(
        orch.AnalystRequest(
            algorithm_prompt=parsed,
            workdir=workdir,
            plan=plan,
        )
    )
    assert resp.failure_mode == "SIGNAL_NOISY"
    assert resp.metrics["profit_factor"] == 1.0


def test_sdk_coordinator_analyze_tolerates_missing_metrics_json(tmp_path, plan):
    workdir = tmp_path / "wd"
    workdir.mkdir()
    (workdir / "algorithm_prompt.txt").write_text(
        ap.build(
            thesis_id="th_000",
            expression_id="exp_001",
            expression_spec=_spec(),
            features_used=["vpin"],
            addresses=None,
            body="# Strategy: Smoke\n",
        )
    )
    parsed = ap.parse((workdir / "algorithm_prompt.txt").read_text())

    def _invoke(agent, prompt):
        (workdir / "failure_mode.txt").write_text("APPROVED\n")
        # No metrics.json — coord should still return the failure_mode.

    coord = sdk.SDKCoordinator(run_dir=tmp_path, plan=plan, invoke=_invoke)
    resp = coord.analyze(
        orch.AnalystRequest(algorithm_prompt=parsed, workdir=workdir, plan=plan)
    )
    assert resp.failure_mode == "APPROVED"
    assert resp.metrics == {}


def test_sdk_coordinator_analyze_raises_if_failure_file_missing(tmp_path, plan):
    workdir = tmp_path / "wd"
    workdir.mkdir()
    (workdir / "algorithm_prompt.txt").write_text(
        ap.build(
            thesis_id="th_000",
            expression_id="exp_001",
            expression_spec=_spec(),
            features_used=["vpin"],
            addresses=None,
            body="# Strategy: Smoke\n",
        )
    )
    parsed = ap.parse((workdir / "algorithm_prompt.txt").read_text())
    coord = sdk.SDKCoordinator(run_dir=tmp_path, plan=plan, invoke=lambda *a: None)
    with pytest.raises(sdk.SDKCoordinatorError):
        coord.analyze(
            orch.AnalystRequest(algorithm_prompt=parsed, workdir=workdir, plan=plan)
        )


# ---------------------------------------------------------------------------
# _next_expression_id helper.
# ---------------------------------------------------------------------------


def test_next_expression_id_on_empty_thesis(tmp_path):
    assert sdk._next_expression_id(tmp_path, "th_000") == "exp_001"


def test_next_expression_id_counts_existing(tmp_path):
    exp_dir = tmp_path / "theses" / "th_000" / "expressions"
    exp_dir.mkdir(parents=True)
    for i in range(1, 4):
        (exp_dir / f"exp_{i:03d}").mkdir()
    assert sdk._next_expression_id(tmp_path, "th_000") == "exp_004"
