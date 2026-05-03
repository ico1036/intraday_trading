from __future__ import annotations

import json

import pandas as pd
import pytest

from scripts.agent import exploration


def _valid_cell(**overrides):
    cell = {axis: values[0] for axis, values in exploration.SEARCH_SPACE.items()}
    cell.update(overrides)
    return cell


def _write_core_artifacts(alpha_dir, *, target_weight=0.25):
    alpha_dir.mkdir(parents=True, exist_ok=True)
    for name in exploration.CORE_ARTIFACTS - {"weights.parquet", "metrics.json"}:
        if name.endswith(".json"):
            (alpha_dir / name).write_text("{}")
        elif name.endswith(".csv"):
            (alpha_dir / name).write_text("k,v\n")
        elif name.endswith(".md"):
            (alpha_dir / name).write_text("# Backtest Report\n")
        else:
            pd.DataFrame({"timestamp": [pd.Timestamp("2025-03-01")]}).to_parquet(
                alpha_dir / name,
                index=False,
            )

    pd.DataFrame(
        [
            {
                "timestamp": pd.Timestamp("2025-03-01"),
                "alpha_id": alpha_dir.name,
                "symbol": "BTCUSDT",
                "target_weight": target_weight,
                "target_notional": 2500.0,
                "target_qty": 0.05,
                "price": 50000.0,
                "bar_type": "TIME",
                "bar_size": 60.0,
                "metadata": "{}",
            }
        ]
    ).to_parquet(alpha_dir / "weights.parquet", index=False)
    (alpha_dir / "metrics.json").write_text(
        json.dumps(
            {
                "total_return": 0.01,
                "profit_factor": 1.2,
                "max_drawdown": -0.02,
                "total_trades": 3,
                "win_rate": 0.66,
                "sharpe": 0.8,
            }
        )
    )


def test_init_run_creates_coverage_and_index(tmp_path):
    run_dir = tmp_path / "run"

    exploration.init_run(run_dir)

    assert (run_dir / "alphas").is_dir()
    assert (run_dir / "coverage_map.json").is_file()
    assert (run_dir / "alpha_index.csv").is_file()


def test_next_cells_avoids_already_visited_direct_cell(tmp_path):
    run_dir = tmp_path / "run"
    exploration.init_run(run_dir)
    first = exploration.next_cells(run_dir, limit=1)[0]
    alpha_dir = run_dir / "alphas" / "alpha_001"
    alpha_dir.mkdir(parents=True)
    (alpha_dir / "search_cell.json").write_text(json.dumps(first))
    _write_core_artifacts(alpha_dir)

    exploration.record_alpha(run_dir, "alpha_001")
    next_cell = exploration.next_cells(run_dir, limit=1)[0]

    assert next_cell != first


def test_record_alpha_updates_coverage_and_index(tmp_path):
    run_dir = tmp_path / "run"
    alpha_dir = run_dir / "alphas" / "alpha_001"
    cell = _valid_cell(signal_family="lead_lag", feature_set="cross_rank")
    alpha_dir.mkdir(parents=True)
    (alpha_dir / "search_cell.json").write_text(json.dumps(cell))
    _write_core_artifacts(alpha_dir)

    entry = exploration.record_alpha(run_dir, "alpha_001")

    coverage = json.loads((run_dir / "coverage_map.json").read_text())
    index_text = (run_dir / "alpha_index.csv").read_text()

    assert entry["valid"] is True
    assert coverage["axis_counts"]["signal_family"]["lead_lag"] == 1
    assert coverage["axis_counts"]["feature_set"]["cross_rank"] == 1
    assert "alpha_001" in index_text
    assert "0.01" in index_text


def test_record_alpha_rejects_bad_search_cell(tmp_path):
    run_dir = tmp_path / "run"
    alpha_dir = run_dir / "alphas" / "alpha_bad"
    alpha_dir.mkdir(parents=True)
    (alpha_dir / "search_cell.json").write_text(json.dumps({"signal_family": "momentum"}))

    with pytest.raises(exploration.ExplorationError, match="missing axes"):
        exploration.record_alpha(run_dir, "alpha_bad")


def test_record_alpha_marks_invalid_weight_artifact(tmp_path):
    run_dir = tmp_path / "run"
    alpha_dir = run_dir / "alphas" / "alpha_bad_weight"
    alpha_dir.mkdir(parents=True)
    (alpha_dir / "search_cell.json").write_text(json.dumps(_valid_cell()))
    _write_core_artifacts(alpha_dir, target_weight=float("nan"))

    entry = exploration.record_alpha(run_dir, "alpha_bad_weight")

    assert entry["valid"] is False
    assert entry["evidence"] == {"invalid_target_weight": True}
