"""Tests for the composite runner: combine math, look-ahead guards, and pipeline."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from intraday.composites import _runner


UNIVERSE = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _events(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    """Build a long-format weights DF from (timestamp_str, symbol, weight) tuples."""
    return pd.DataFrame(
        [
            {"timestamp": pd.Timestamp(ts), "symbol": s, "target_weight": w}
            for ts, s, w in rows
        ]
    )


def _panel_from_events(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    return _runner._events_to_panel(_events(rows), UNIVERSE)


# --------------------------------------------------------------------------
# look-ahead guard: load_alpha_index_is_only
# --------------------------------------------------------------------------


def _write_fake_index(run_dir: Path) -> None:
    pd.DataFrame(
        [
            {
                "alpha_id": "a1", "status": "IS_PASS", "strategy": "Foo",
                "is_sharpe": 1.5, "is_sharpe_daily": 1.4, "is_return": 0.10,
                "is_trades": 200, "is_dd": -0.05, "is_winrate": 0.55,
                "os_sharpe": 0.9, "os_sharpe_daily": 0.85, "os_return": 0.04,
                "os_trades": 180, "os_dd": -0.07,
                "artifact_dir": "alphas/a1", "notes": "",
            },
            {
                "alpha_id": "a2", "status": "IS_PASS", "strategy": "Bar",
                "is_sharpe": 2.0, "is_sharpe_daily": 1.9, "is_return": 0.15,
                "is_trades": 300, "is_dd": -0.04, "is_winrate": 0.58,
                "os_sharpe": 1.1, "os_sharpe_daily": 1.0, "os_return": 0.06,
                "os_trades": 250, "os_dd": -0.06,
                "artifact_dir": "alphas/a2", "notes": "",
            },
        ]
    ).to_csv(run_dir / "alpha_index.csv", index=False)


def test_load_alpha_index_strips_os_columns(tmp_path, monkeypatch):
    monkeypatch.setattr(_runner, "ARCHIVE_ROOT", tmp_path)
    run_dir = tmp_path / "run_x"
    run_dir.mkdir()
    _write_fake_index(run_dir)

    df = _runner.load_alpha_index_is_only("run_x")

    assert all(not c.startswith("os_") for c in df.columns)
    assert "is_sharpe" in df.columns
    assert "is_sharpe_daily" in df.columns
    # Confirm that hostile user code referencing OS column raises immediately.
    with pytest.raises(KeyError):
        _ = df["os_sharpe"]


def test_load_alpha_index_missing_file_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(_runner, "ARCHIVE_ROOT", tmp_path)
    with pytest.raises(FileNotFoundError):
        _runner.load_alpha_index_is_only("does_not_exist")


# --------------------------------------------------------------------------
# _events_to_panel + _gross_mean_from_panel
# --------------------------------------------------------------------------


def test_events_to_panel_pivots_and_aligns_universe():
    panel = _panel_from_events(
        [
            ("2026-01-01 00:00", "BTCUSDT", 0.3),
            ("2026-01-01 00:00", "ETHUSDT", -0.2),
            ("2026-01-01 01:00", "BTCUSDT", 0.4),
        ]
    )
    assert list(panel.columns) == UNIVERSE
    # SOLUSDT column exists but has all NaN (universe alignment)
    assert panel["SOLUSDT"].isna().all()
    assert panel.loc[pd.Timestamp("2026-01-01 00:00"), "BTCUSDT"] == pytest.approx(0.3)
    assert panel.loc[pd.Timestamp("2026-01-01 01:00"), "BTCUSDT"] == pytest.approx(0.4)


def test_events_to_panel_empty_returns_empty_with_universe_columns():
    panel = _runner._events_to_panel(pd.DataFrame(columns=["timestamp", "symbol", "target_weight"]), UNIVERSE)
    assert list(panel.columns) == UNIVERSE
    assert panel.empty


def test_gross_mean_from_panel():
    # BTC=0.3 then 0.4; ETH=-0.2 throughout once event lands; SOL never traded.
    panel = _panel_from_events(
        [
            ("2026-01-01 00:00", "BTCUSDT", 0.3),
            ("2026-01-01 00:00", "ETHUSDT", -0.2),
            ("2026-01-01 01:00", "BTCUSDT", 0.4),
        ]
    )
    # After ffill: row0 |.|sum = 0.3 + 0.2 = 0.5; row1 = 0.4 + 0.2 = 0.6 → mean = 0.55
    gm = _runner._gross_mean_from_panel(panel)
    assert gm == pytest.approx(0.55)


def test_gross_mean_empty_panel_is_none():
    assert _runner._gross_mean_from_panel(pd.DataFrame(columns=UNIVERSE)) is None


# --------------------------------------------------------------------------
# combine_weights — the core math
# --------------------------------------------------------------------------


def test_combine_equal_coef_averages_aligned_panels():
    a = _panel_from_events([("2026-01-01 00:00", "BTCUSDT", 0.4)])
    b = _panel_from_events([("2026-01-01 00:00", "BTCUSDT", 0.2)])
    long_df, stats = _runner.combine_weights(
        {"a": a, "b": b}, {"a": 0.5, "b": 0.5}, UNIVERSE
    )
    # Expected combined BTC = 0.5*0.4 + 0.5*0.2 = 0.3, single change event from 0.
    btc = long_df[long_df["symbol"] == "BTCUSDT"]
    assert len(btc) == 1
    assert btc.iloc[0]["target_weight"] == pytest.approx(0.3)
    assert stats["n_change_events"] == 1
    assert stats["n_rows_clipped"] == 0


def test_combine_offsetting_signals_cancel():
    a = _panel_from_events([("2026-01-01 00:00", "BTCUSDT", 0.5)])
    b = _panel_from_events([("2026-01-01 00:00", "BTCUSDT", -0.5)])
    long_df, stats = _runner.combine_weights(
        {"a": a, "b": b}, {"a": 0.5, "b": 0.5}, UNIVERSE
    )
    # Net zero → initial-flat-zero suppression → no events.
    assert long_df.empty
    assert stats["n_change_events"] == 0


def test_combine_late_member_contributes_zero_before_first_event():
    """Causal alignment: a member whose first event lands at t=10 must
    contribute 0 to W_comp at t=5 (no bfill, no peeking)."""
    early = _panel_from_events([("2026-01-01 00:00", "BTCUSDT", 0.4)])
    late = _panel_from_events([("2026-01-01 02:00", "BTCUSDT", 0.4)])
    long_df, _ = _runner.combine_weights(
        {"early": early, "late": late}, {"early": 1.0, "late": 1.0}, UNIVERSE
    )
    # At t=00:00: early=0.4, late=0  → 0.4
    # At t=02:00: early=0.4 (ffill), late=0.4 → 0.8
    rows = long_df[long_df["symbol"] == "BTCUSDT"].sort_values("timestamp")
    assert len(rows) == 2
    assert rows.iloc[0]["target_weight"] == pytest.approx(0.4)
    assert rows.iloc[0]["timestamp"] == pd.Timestamp("2026-01-01 00:00")
    assert rows.iloc[1]["target_weight"] == pytest.approx(0.8)
    assert rows.iloc[1]["timestamp"] == pd.Timestamp("2026-01-01 02:00")


def test_combine_row_l1_clipped_when_gross_exceeds_one():
    """Σ|w_s| > 1 is normalized down so the runner's gross-exposure
    invariant is preserved."""
    a = _panel_from_events(
        [
            ("2026-01-01 00:00", "BTCUSDT", 0.7),
            ("2026-01-01 00:00", "ETHUSDT", 0.7),
        ]
    )
    long_df, stats = _runner.combine_weights({"a": a}, {"a": 1.0}, UNIVERSE)
    # Pre-norm row L1 = 1.4 → scale = 1/1.4 → both legs = 0.5
    btc = long_df[long_df["symbol"] == "BTCUSDT"].iloc[0]
    eth = long_df[long_df["symbol"] == "ETHUSDT"].iloc[0]
    assert btc["target_weight"] == pytest.approx(0.5)
    assert eth["target_weight"] == pytest.approx(0.5)
    assert stats["n_rows_clipped"] == 1
    assert stats["max_row_l1"] == pytest.approx(1.4)


def test_combine_emits_only_change_events():
    """Symbol whose value is unchanged across two timestamps gets one
    event, not two."""
    a = _panel_from_events(
        [
            ("2026-01-01 00:00", "BTCUSDT", 0.3),
            ("2026-01-01 01:00", "BTCUSDT", 0.3),  # repeat
            ("2026-01-01 02:00", "BTCUSDT", 0.0),  # close
        ]
    )
    long_df, _ = _runner.combine_weights({"a": a}, {"a": 1.0}, UNIVERSE)
    btc = long_df[long_df["symbol"] == "BTCUSDT"].sort_values("timestamp")
    # Open at 00:00 (0→0.3), close at 02:00 (0.3→0). No event for the unchanged 01:00 row.
    assert len(btc) == 2
    assert list(btc["target_weight"]) == pytest.approx([0.3, 0.0])
    assert list(btc["timestamp"]) == [pd.Timestamp("2026-01-01 00:00"), pd.Timestamp("2026-01-01 02:00")]


def test_combine_initial_flat_zero_not_emitted():
    """A symbol that starts at 0 with NaN prior should not produce a leading
    no-op event."""
    a = _panel_from_events([("2026-01-01 00:00", "BTCUSDT", 0.5)])
    # Combined panel grid only has the 00:00 timestamp; ETH/SOL stay at 0.
    long_df, _ = _runner.combine_weights({"a": a}, {"a": 1.0}, UNIVERSE)
    # Only BTCUSDT event emitted.
    assert set(long_df["symbol"]) == {"BTCUSDT"}


def test_combine_empty_members_returns_empty():
    long_df, stats = _runner.combine_weights({}, {}, UNIVERSE)
    assert long_df.empty
    assert stats["n_change_events"] == 0


# --------------------------------------------------------------------------
# build_and_backtest — end-to-end pipeline (subprocess mocked)
# --------------------------------------------------------------------------


def _write_member_weights(run_dir: Path, alpha_id: str, split: str, rows: list[dict]) -> None:
    d = run_dir / "alphas" / alpha_id / split
    d.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(d / "weights.parquet")


def _setup_fake_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run_demo"
    run_dir.mkdir()
    _write_fake_index(run_dir)
    (run_dir / "splits.json").write_text(
        json.dumps(
            {
                "run_id": "run_demo",
                "universe": UNIVERSE,
                "is": {"start": "2025-01-01 00:00:00", "end": "2025-06-30 23:59:00"},
                "os": {"start": "2025-07-01 00:00:00", "end": "2025-12-31 23:59:00"},
            }
        )
    )
    # Member a1: simple LONG BTC for both windows
    _write_member_weights(
        run_dir, "a1", "is",
        [
            {"timestamp": pd.Timestamp("2025-02-01 00:00"), "symbol": "BTCUSDT", "target_weight": 0.5},
            {"timestamp": pd.Timestamp("2025-04-01 00:00"), "symbol": "BTCUSDT", "target_weight": 0.0},
        ],
    )
    _write_member_weights(
        run_dir, "a1", "os",
        [
            {"timestamp": pd.Timestamp("2025-08-01 00:00"), "symbol": "BTCUSDT", "target_weight": 0.4},
        ],
    )
    # Member a2: SHORT ETH
    _write_member_weights(
        run_dir, "a2", "is",
        [
            {"timestamp": pd.Timestamp("2025-02-15 00:00"), "symbol": "ETHUSDT", "target_weight": -0.4},
        ],
    )
    _write_member_weights(
        run_dir, "a2", "os",
        [
            {"timestamp": pd.Timestamp("2025-09-01 00:00"), "symbol": "ETHUSDT", "target_weight": -0.3},
        ],
    )
    return run_dir


def _select_top2(df: pd.DataFrame) -> list[str]:
    return df.nlargest(2, "is_sharpe_daily")["alpha_id"].tolist()


def _equal_weight(ids: list[str], _: pd.DataFrame) -> dict[str, float]:
    return {a: 1.0 / len(ids) for a in ids}


def test_build_and_backtest_writes_artifacts(tmp_path, monkeypatch):
    _setup_fake_run(tmp_path)
    monkeypatch.setattr(_runner, "ARCHIVE_ROOT", tmp_path)

    calls: list[list[str]] = []

    def fake_run(cmd, check, cwd):  # noqa: ARG001
        calls.append(cmd)
        # Mimic the real backtest: create output dir + metrics.json so the
        # runner's existence check passes.
        out_dir = Path(cmd[cmd.index("--output-dir") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "metrics.json").write_text("{}")
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    monkeypatch.setattr(_runner.subprocess, "run", fake_run)

    comp_dir = _runner.build_and_backtest(
        composite_id="demo_eqw",
        run_id="run_demo",
        select_members=_select_top2,
        member_weights=_equal_weight,
        composition_note="equal_weight_demo",
        include_os=True,
    )

    # Composite directory & artifacts
    assert comp_dir == tmp_path / "run_demo" / "composites" / "demo_eqw"
    assert (comp_dir / "weights.parquet").exists()
    assert (comp_dir / "metrics.json").exists()
    assert not (comp_dir / "manifest.json").exists()
    assert (comp_dir / "members.csv").exists()

    # Composite metadata is folded into metrics.json.
    metrics = json.loads((comp_dir / "metrics.json").read_text())
    assert metrics["composite_id"] == "demo_eqw"
    assert metrics["method"] == "equal_weight_demo"
    assert metrics["n_members"] == 2
    assert metrics["is_window"]["start"] == "2025-01-01 00:00:00"
    assert metrics["os_window"]["start"] == "2025-07-01 00:00:00"
    assert metrics["selection_bias_warning"]  # populated

    # members.csv contains both alphas with coefficients summing to 1.0
    members = pd.read_csv(comp_dir / "members.csv")
    assert set(members["alpha_id"]) == {"a1", "a2"}
    assert members["coefficient"].sum() == pytest.approx(1.0)
    assert members["is_gross_mean"].notna().all()

    # weights.parquet has expected schema and is non-empty
    weights = pd.read_parquet(comp_dir / "weights.parquet")
    assert set(weights.columns) == {"timestamp", "symbol", "target_weight"}
    assert len(weights) > 0

    # One full-window invocation; IS/OS split is recorded inside metrics.json
    # via --is-end, not by writing comp_dir/is and comp_dir/os artifacts.
    assert len(calls) == 1
    is_cmd = calls[0]
    assert "--start" in is_cmd and is_cmd[is_cmd.index("--start") + 1] == "2025-01-01 00:00:00"
    assert "--end" in is_cmd and is_cmd[is_cmd.index("--end") + 1] == "2025-12-31 23:59:00"
    assert is_cmd[is_cmd.index("--output-dir") + 1].endswith("/demo_eqw")
    assert is_cmd[is_cmd.index("--is-end") + 1] == "2025-06-30 23:59:00"
    is_params = json.loads(is_cmd[is_cmd.index("--strategy-params") + 1])
    assert is_params["weights_path"].endswith("/demo_eqw/weights.parquet")
    # Composite backtests must skip the per-alpha gates that would otherwise
    # delete the parent composite directory on failure.
    for cmd in calls:
        assert "--no-enforce-quality" in cmd
        assert "--no-enforce-governance" in cmd


def test_build_skips_os_when_include_os_false(tmp_path, monkeypatch):
    _setup_fake_run(tmp_path)
    monkeypatch.setattr(_runner, "ARCHIVE_ROOT", tmp_path)

    calls: list[list[str]] = []

    def fake_run(cmd, check, cwd):  # noqa: ARG001
        calls.append(cmd)
        out_dir = Path(cmd[cmd.index("--output-dir") + 1])
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "metrics.json").write_text("{}")
        return subprocess.CompletedProcess(args=cmd, returncode=0)

    monkeypatch.setattr(_runner.subprocess, "run", fake_run)

    comp_dir = _runner.build_and_backtest(
        composite_id="demo_isonly",
        run_id="run_demo",
        select_members=_select_top2,
        member_weights=_equal_weight,
        include_os=False,
    )

    assert len(calls) == 1  # only IS
    metrics = json.loads((comp_dir / "metrics.json").read_text())
    assert metrics["os_window"] is None


def test_build_rejects_empty_selection(tmp_path, monkeypatch):
    _setup_fake_run(tmp_path)
    monkeypatch.setattr(_runner, "ARCHIVE_ROOT", tmp_path)
    with pytest.raises(ValueError, match="empty list"):
        _runner.build_and_backtest(
            composite_id="bad",
            run_id="run_demo",
            select_members=lambda _: [],
            member_weights=_equal_weight,
        )


def test_build_rejects_missing_coefficient(tmp_path, monkeypatch):
    _setup_fake_run(tmp_path)
    monkeypatch.setattr(_runner, "ARCHIVE_ROOT", tmp_path)
    with pytest.raises(ValueError, match="missing entries"):
        _runner.build_and_backtest(
            composite_id="bad",
            run_id="run_demo",
            select_members=_select_top2,
            member_weights=lambda ids, _df: {ids[0]: 1.0},  # only one of two
        )


# --------------------------------------------------------------------------
# Look-ahead guard: hostile selection function gets KeyError, not silent leak
# --------------------------------------------------------------------------


def test_user_code_touching_os_column_raises(tmp_path, monkeypatch):
    _setup_fake_run(tmp_path)
    monkeypatch.setattr(_runner, "ARCHIVE_ROOT", tmp_path)
    monkeypatch.setattr(_runner.subprocess, "run", lambda cmd, check, cwd: None)

    def hostile_select(df: pd.DataFrame) -> list[str]:
        # User attempts to peek at OS Sharpe — should fail loud.
        return df.nlargest(2, "os_sharpe")["alpha_id"].tolist()

    with pytest.raises(KeyError):
        _runner.build_and_backtest(
            composite_id="leaky",
            run_id="run_demo",
            select_members=hostile_select,
            member_weights=_equal_weight,
        )


def test_user_weighting_touching_os_column_raises(tmp_path, monkeypatch):
    _setup_fake_run(tmp_path)
    monkeypatch.setattr(_runner, "ARCHIVE_ROOT", tmp_path)
    monkeypatch.setattr(_runner.subprocess, "run", lambda cmd, check, cwd: None)

    def hostile_weights(ids: list[str], df: pd.DataFrame) -> dict[str, float]:
        # OS-derived coefficients — hard fail expected.
        sub = df.set_index("alpha_id").loc[ids]
        return sub["os_sharpe"].to_dict()

    with pytest.raises(KeyError):
        _runner.build_and_backtest(
            composite_id="leaky2",
            run_id="run_demo",
            select_members=_select_top2,
            member_weights=hostile_weights,
        )
