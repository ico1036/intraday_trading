"""One-cycle v2 harness integration test.

This uses phase-local fake agents instead of a real SDK call. The point is to
exercise the same coordinator/orchestrator file contract for one full
Research -> Develop -> Backtest/Analyze -> Result cycle without network or LLM
dependencies.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.agent.v2 import algorithm_prompt as ap
from scripts.agent.v2 import orchestrator as orch
from scripts.agent.v2 import sdk_coordinator
from scripts.agent.v2.deterministic import plan as plan_mod

pd = pytest.importorskip("pandas")


PLAN_TEXT = """# Run: cycle_smoke

## Targets
profit_factor: 1.1
max_drawdown: -0.20
total_return: 0.01
total_trades: 1
max_trials: 1
max_expressions_per_thesis: 1
max_theses_per_run: 1

## Strategy request
Generate one compact portfolio alpha and verify saved weights.

## Universe
symbols: [BTCUSDT, ETHUSDT]

## IS / OS periods
is_start: 2025-03-01
is_end: 2025-03-31
os_start: 2025-10-01
os_end: 2025-10-31
"""


def _spec() -> dict:
    return {
        "bar_domain": "VOLUME",
        "bar_granularity": "medium",
        "signal_form": "raw",
        "threshold_type": "absolute",
        "aggregation": "instantaneous",
        "regime_filter": "none",
        "exit_rule": "time_stop",
        "sizing": "fixed",
        "universe": "basket_topk",
    }


def test_v2_research_develop_backtest_review_one_cycle(tmp_path):
    run_dir = tmp_path / "archive" / "cycle_smoke"
    run_dir.mkdir(parents=True)
    (run_dir / "theses").mkdir()
    plan_path = run_dir / "PLAN.md"
    plan_path.write_text(PLAN_TEXT)
    plan = plan_mod.parse(PLAN_TEXT)

    phases: list[str] = []

    def invoke(phase_name: str, prompt: str) -> None:
        phases.append(phase_name)

        thesis_id = "th_000"
        exp_id = "exp_001"
        exp_dir = run_dir / "theses" / thesis_id / "expressions" / exp_id

        if phase_name == "researcher":
            exp_dir.mkdir(parents=True)
            (run_dir / "theses" / thesis_id / "thesis.md").write_text(
                """---
thesis_id: th_000
fingerprint: sha256:cycle-smoke
status: ACTIVE
direction: momentum
features: [vpin]
trigger_schema:
  when: "lookback return crosses threshold"
---

# Thesis
Compact VPIN momentum alpha for one or many symbols.
"""
            )
            (exp_dir / "algorithm_prompt.txt").write_text(
                ap.build(
                    thesis_id=thesis_id,
                    expression_id=exp_id,
                    expression_spec=_spec(),
                    features_used=["vpin"],
                    addresses=None,
                    body="# Strategy: CycleSmokeAlpha\n",
                )
            )
            return

        if phase_name == "developer":
            assert "src/intraday/strategies/multi/_alpha_template.py" in prompt
            assert "symbols: list[str]" in prompt
            assert "PortfolioOrder" in prompt
            exp_dir.mkdir(parents=True, exist_ok=True)
            template = Path(
                "src/intraday/strategies/multi/_alpha_template.py"
            ).read_text()
            (exp_dir / "cycle_smoke_alpha.py").write_text(
                template.replace("AlphaTemplateStrategy", "CycleSmokeAlpha")
            )
            (exp_dir / "test_cycle_smoke_alpha.py").write_text(
                "def test_generated_strategy_file_exists():\n    assert True\n"
            )
            return

        if phase_name == "analyst":
            assert (exp_dir / "cycle_smoke_alpha.py").is_file()
            assert "output_dir" in prompt
            weights = pd.DataFrame(
                [
                    {
                        "timestamp": pd.Timestamp("2025-03-01T00:00:00Z"),
                        "alpha_id": "cycle_smoke",
                        "symbol": "BTCUSDT",
                        "target_weight": 0.5,
                        "target_notional": 50000.0,
                        "target_qty": 0.5,
                        "price": 100000.0,
                        "bar_type": "VOLUME",
                        "bar_size": 20.0,
                        "metadata": "{}",
                    },
                    {
                        "timestamp": pd.Timestamp("2025-03-01T00:00:00Z"),
                        "alpha_id": "cycle_smoke",
                        "symbol": "ETHUSDT",
                        "target_weight": -0.5,
                        "target_notional": -50000.0,
                        "target_qty": -12.5,
                        "price": 4000.0,
                        "bar_type": "VOLUME",
                        "bar_size": 20.0,
                        "metadata": "{}",
                    },
                ]
            )
            weights.to_parquet(exp_dir / "weights.parquet", index=False)
            for name in ("equity_curve", "trades", "events"):
                pd.DataFrame({"timestamp": weights["timestamp"]}).to_parquet(
                    exp_dir / f"{name}.parquet",
                    index=False,
                )
            metrics = {
                "profit_factor": 1.4,
                "total_return": 0.03,
                "max_drawdown": -0.04,
                "total_trades": 4,
                "win_rate": 0.5,
                "sharpe": 1.2,
                "per_symbol": {"BTCUSDT": {}, "ETHUSDT": {}},
            }
            (exp_dir / "manifest.json").write_text(json.dumps({"alpha_id": "cycle_smoke"}))
            (exp_dir / "metrics.json").write_text(json.dumps(metrics))
            (exp_dir / "summary.json").write_text(json.dumps(metrics))
            (exp_dir / "summary.csv").write_text("metric,value\nprofit_factor,1.4\n")
            (exp_dir / "backtest_report.md").write_text("# Backtest Report\n")
            (exp_dir / "failure_mode.txt").write_text("APPROVED\n")
            return

        raise AssertionError(f"unexpected phase: {phase_name}")

    coord = sdk_coordinator.SDKCoordinator(
        run_dir=run_dir,
        plan=plan,
        invoke=invoke,
        plan_path=plan_path,
    )

    result = orch.run(run_dir=run_dir, plan=plan, coord=coord)

    exp_dir = run_dir / "theses" / "th_000" / "expressions" / "exp_001"
    assert phases == ["researcher", "developer", "analyst"]
    assert result.decision.reason == "TARGETS_MET"
    assert (run_dir / "DONE").is_file()
    assert "verdict: APPROVED" in (run_dir / "theses" / "th_000" / "verdict.md").read_text()
    assert (exp_dir / "weights.parquet").is_file()
    assert set(pd.read_parquet(exp_dir / "weights.parquet")["symbol"]) == {
        "BTCUSDT",
        "ETHUSDT",
    }
