"""Tests for the composite runner: combine math, member freshness, look-ahead guards, and pipeline."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from intraday.composites import _runner


UNIVERSE = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
FP = "fp-test"
IS = {"start": "2025-01-01 00:00:00", "end": "2025-06-30 23:59:00"}
OS = {"start": "2025-07-01 00:00:00", "end": "2025-12-31 23:59:00"}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _events(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"timestamp": pd.Timestamp(ts), "symbol": s, "target_weight": w} for ts, s, w in rows]
    )


def _panel_from_events(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    return _runner._events_to_panel(_events(rows), UNIVERSE)


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


def _run_config(data_path: str, strategy: str, **over) -> dict:
    cfg = {
        "strategy": strategy, "strategy_params": {"k": 1}, "data_type": "bars", "data_path": data_path,
        "symbol_data_paths": {}, "bar_type": "TIME", "bar_size": 86400.0,
        "start": IS["start"], "end": OS["end"], "is_end": IS["end"],
        "initial_capital": 10000.0, "position_size_pct": 1.0, "leverage": 1, "max_portfolio_weight": 1.0,
        "maker_fee_rate": 0.0002, "taker_fee_rate": 0.0005, "fixed_aum_sizing": True,
        **_runner.COST_DEFAULTS,
    }
    cfg.update(over)
    return cfg


def _write_member(run_dir: Path, alpha_id: str, rows: list[dict], *, source: Path, cfg: dict | None,
                  fingerprint: str = FP, symbols: list[str] | None = None) -> None:
    """A member archive in the current single-file layout."""
    d = run_dir / "alphas" / alpha_id
    d.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(d / "weights.parquet")
    (d / "strategy_source.py").write_bytes(source.read_bytes())
    metrics = {
        "generated_at": "2026-01-01T00:00:00", "strategy_class": (cfg or {}).get("strategy", "Foo"),
        "source_original_path": str(source), "engine_fingerprint": fingerprint,
        "symbols": UNIVERSE if symbols is None else symbols,
        "is": {"sharpe": 1.0, "total_return": 0.1, "total_trades": 50},
    }
    if cfg is not None:
        metrics["run_config"] = cfg
    (d / "metrics.json").write_text(json.dumps(metrics))


A1_ROWS = [
    {"timestamp": pd.Timestamp("2025-02-01"), "symbol": "BTCUSDT", "target_weight": 0.5},
    {"timestamp": pd.Timestamp("2025-04-01"), "symbol": "BTCUSDT", "target_weight": 0.0},
    {"timestamp": pd.Timestamp("2025-08-01"), "symbol": "BTCUSDT", "target_weight": 0.4},
]
A2_ROWS = [
    {"timestamp": pd.Timestamp("2025-02-15"), "symbol": "ETHUSDT", "target_weight": -0.4},
    {"timestamp": pd.Timestamp("2025-09-01"), "symbol": "ETHUSDT", "target_weight": -0.3},
]


def _setup_fake_run(tmp_path: Path, monkeypatch, *, with_config: bool = True) -> Path:
    """A run whose two members are fresh under fingerprint FP."""
    monkeypatch.setattr(_runner, "ARCHIVE_ROOT", tmp_path)
    monkeypatch.setattr(_runner, "engine_fingerprint", lambda: FP)
    run_dir = tmp_path / "run_demo"
    run_dir.mkdir()
    data = tmp_path / "data"
    for s in UNIVERSE:
        (data / s).mkdir(parents=True)
    _write_fake_index(run_dir)
    (run_dir / "splits.json").write_text(json.dumps(
        {"run_id": "run_demo", "universe": UNIVERSE, "is": IS, "os": OS, "data_path": str(data)}
    ))
    src = tmp_path / "src"
    src.mkdir()
    for alpha_id, strategy, rows in (("a1", "Foo", A1_ROWS), ("a2", "Bar", A2_ROWS)):
        source = src / f"{alpha_id}.py"
        source.write_text(f"# {alpha_id}\n")
        cfg = _run_config(str(data), strategy) if with_config else None
        _write_member(run_dir, alpha_id, rows, source=source, cfg=cfg)
    return run_dir


def _flag(cmd: list[str], name: str) -> str:
    return cmd[cmd.index(name) + 1]


def _fake_backtest(calls: list[list[str]]):
    """Stand-in for backtest.py: a composite replay writes metrics.json; a
    member rerun re-archives the member fresh under the flags it was given."""
    def run(cmd, check=False, cwd=None, **_):
        calls.append(cmd)
        out_dir = Path(_flag(cmd, "--output-dir"))
        out_dir.mkdir(parents=True, exist_ok=True)
        if _flag(cmd, "--strategy") == "PrecomputedWeightsStrategy":
            (out_dir / "metrics.json").write_text("{}")
        else:
            metrics = json.loads((out_dir / "metrics.json").read_text())
            source = Path(metrics["source_original_path"])
            (out_dir / "strategy_source.py").write_bytes(source.read_bytes())
            cfg = metrics.get("run_config", {})
            cfg.update({
                "data_path": _flag(cmd, "--data-path"), "start": _flag(cmd, "--start"),
                "end": _flag(cmd, "--end"), "is_end": _flag(cmd, "--is-end"),
                "stale_bar_exit": int(_flag(cmd, "--stale-bar-exit")), "slippage": _flag(cmd, "--slippage"),
                "funding_path": _flag(cmd, "--funding-path"), "funding": "--no-funding" not in cmd,
            })
            metrics.update({"run_config": cfg, "engine_fingerprint": FP, "generated_at": "2026-02-02T00:00:00",
                            "symbols": cmd[cmd.index("--symbols") + 1: cmd.index("--data-type")]})
            (out_dir / "metrics.json").write_text(json.dumps(metrics))
        return subprocess.CompletedProcess(args=cmd, returncode=0)
    return run


def _select_top2(df: pd.DataFrame) -> list[str]:
    return df.nlargest(2, "is_sharpe_daily")["alpha_id"].tolist()


def _equal_weight(ids: list[str], _: pd.DataFrame) -> dict[str, float]:
    return {a: 1.0 / len(ids) for a in ids}


def _build(**kw) -> Path:
    base = dict(composite_id="demo_eqw", run_id="run_demo", select_members=_select_top2,
                member_weights=_equal_weight, composition_note="equal_weight_demo")
    base.update(kw)
    return _runner.build_and_backtest(**base)


# --------------------------------------------------------------------------
# look-ahead guard: load_alpha_index_is_only
# --------------------------------------------------------------------------


def test_load_alpha_index_strips_os_columns(tmp_path, monkeypatch):
    monkeypatch.setattr(_runner, "ARCHIVE_ROOT", tmp_path)
    run_dir = tmp_path / "run_x"
    run_dir.mkdir()
    _write_fake_index(run_dir)
    df = _runner.load_alpha_index_is_only("run_x")
    assert all(not c.startswith("os_") for c in df.columns)
    assert "is_sharpe" in df.columns
    with pytest.raises(KeyError):
        _ = df["os_sharpe"]


def test_load_alpha_index_missing_file_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(_runner, "ARCHIVE_ROOT", tmp_path)
    with pytest.raises(FileNotFoundError):
        _runner.load_alpha_index_is_only("does_not_exist")


# --------------------------------------------------------------------------
# run context + member archives
# --------------------------------------------------------------------------


def test_run_context_reads_data_path_and_drops_symbols_without_data(tmp_path, monkeypatch):
    _setup_fake_run(tmp_path, monkeypatch)
    (tmp_path / "data" / "SOLUSDT").rmdir()
    ctx = _runner.load_run_context("run_demo")
    assert ctx.data_path == str(tmp_path / "data")
    assert ctx.universe == ["BTCUSDT", "ETHUSDT"]
    assert ctx.unavailable == ["SOLUSDT"]
    assert ctx.start == IS["start"] and ctx.is_end == IS["end"] and ctx.end == OS["end"]
    assert _runner.load_run_context("run_demo", include_os=False).replay_end == IS["end"]


def test_run_context_defaults_data_path(tmp_path, monkeypatch):
    run_dir = _setup_fake_run(tmp_path, monkeypatch)
    splits = json.loads((run_dir / "splits.json").read_text())
    del splits["data_path"]
    (run_dir / "splits.json").write_text(json.dumps(splits))
    assert _runner.load_run_context("run_demo").data_path == _runner.DEFAULT_DATA_PATH


def test_load_member_events_splits_one_file_at_is_end(tmp_path, monkeypatch):
    _setup_fake_run(tmp_path, monkeypatch)
    is_events = _runner._load_member_events("run_demo", "a1", "is", IS["end"])
    os_events = _runner._load_member_events("run_demo", "a1", "os", IS["end"])
    assert list(is_events["timestamp"]) == [pd.Timestamp("2025-02-01"), pd.Timestamp("2025-04-01")]
    assert list(os_events["timestamp"]) == [pd.Timestamp("2025-08-01")]


def test_load_member_events_reads_legacy_split_dirs(tmp_path, monkeypatch):
    run_dir = _setup_fake_run(tmp_path, monkeypatch)
    legacy = run_dir / "alphas" / "a1" / "is"
    legacy.mkdir()
    pd.DataFrame([{"timestamp": pd.Timestamp("2025-03-03 04:00"), "symbol": "SOLUSDT", "target_weight": 0.2}]).to_parquet(legacy / "weights.parquet")
    events = _runner._load_member_events("run_demo", "a1", "is", IS["end"])
    # the legacy file wins and an intraday event snaps forward to the next midnight
    assert list(events["symbol"]) == ["SOLUSDT"]
    assert events["timestamp"].iloc[0] == pd.Timestamp("2025-03-04")


def test_events_to_panel_pivots_and_aligns_universe():
    panel = _panel_from_events([("2026-01-01 00:00", "BTCUSDT", 0.3), ("2026-01-01 00:00", "ETHUSDT", -0.2), ("2026-01-01 01:00", "BTCUSDT", 0.4)])
    assert list(panel.columns) == UNIVERSE
    assert panel["SOLUSDT"].isna().all()
    assert panel.loc[pd.Timestamp("2026-01-01 01:00"), "BTCUSDT"] == pytest.approx(0.4)


def test_gross_mean_from_panel():
    panel = _panel_from_events([("2026-01-01 00:00", "BTCUSDT", 0.3), ("2026-01-01 00:00", "ETHUSDT", -0.2), ("2026-01-01 01:00", "BTCUSDT", 0.4)])
    assert _runner._gross_mean_from_panel(panel) == pytest.approx(0.55)
    assert _runner._gross_mean_from_panel(pd.DataFrame(columns=UNIVERSE)) is None


# --------------------------------------------------------------------------
# member freshness
# --------------------------------------------------------------------------


def test_member_status_fresh_when_archive_matches_run(tmp_path, monkeypatch):
    _setup_fake_run(tmp_path, monkeypatch)
    ctx = _runner.load_run_context("run_demo")
    status = _runner.member_status("run_demo", "a1", ctx, FP)
    assert status.fresh and status.rerunnable
    assert status.engine_fingerprint == FP and status.strategy_sha


@pytest.mark.parametrize("mutate, expected", [
    (lambda run_dir, tmp: None, "engine"),
    (lambda run_dir, tmp: (tmp / "src" / "a1.py").write_text("# edited\n"), "strategy source changed"),
    (lambda run_dir, tmp: (tmp / "src" / "a1.py").unlink(), "missing from the working tree"),
])
def test_member_status_names_the_reason(tmp_path, monkeypatch, mutate, expected):
    run_dir = _setup_fake_run(tmp_path, monkeypatch)
    mutate(run_dir, tmp_path)
    ctx = _runner.load_run_context("run_demo")
    fingerprint = "fp-other" if expected == "engine" else FP
    status = _runner.member_status("run_demo", "a1", ctx, fingerprint)
    assert not status.fresh
    assert any(expected in r for r in status.reasons), status.reasons


def test_member_status_flags_config_drift(tmp_path, monkeypatch):
    run_dir = _setup_fake_run(tmp_path, monkeypatch)
    d = run_dir / "alphas" / "a1"
    metrics = json.loads((d / "metrics.json").read_text())
    metrics["run_config"].update({"data_path": "data/other", "stale_bar_exit": 0, "end": "2025-10-01 00:00:00"})
    metrics["symbols"] = ["BTCUSDT"]
    (d / "metrics.json").write_text(json.dumps(metrics))
    status = _runner.member_status("run_demo", "a1", _runner.load_run_context("run_demo"), FP)
    joined = " | ".join(status.reasons)
    assert "data_path" in joined and "stale_bar_exit" in joined and "window" in joined and "universe" in joined
    assert status.rerunnable


def test_member_without_run_config_is_stale_and_not_rerunnable(tmp_path, monkeypatch):
    _setup_fake_run(tmp_path, monkeypatch, with_config=False)
    status = _runner.member_status("run_demo", "a1", _runner.load_run_context("run_demo"), FP)
    assert not status.fresh and not status.rerunnable
    assert any("run_config" in r for r in status.reasons)


# --------------------------------------------------------------------------
# combine_weights: the core math
# --------------------------------------------------------------------------


def test_combine_equal_coef_averages_aligned_panels():
    a = _panel_from_events([("2026-01-01 00:00", "BTCUSDT", 0.4)])
    b = _panel_from_events([("2026-01-01 00:00", "BTCUSDT", 0.2)])
    long_df, stats = _runner.combine_weights({"a": a, "b": b}, {"a": 0.5, "b": 0.5}, UNIVERSE)
    btc = long_df[long_df["symbol"] == "BTCUSDT"]
    assert len(btc) == 1 and btc.iloc[0]["target_weight"] == pytest.approx(0.3)
    assert stats["n_change_events"] == 1 and stats["n_rows_clipped"] == 0


def test_combine_offsetting_signals_cancel():
    a = _panel_from_events([("2026-01-01 00:00", "BTCUSDT", 0.5)])
    b = _panel_from_events([("2026-01-01 00:00", "BTCUSDT", -0.5)])
    long_df, stats = _runner.combine_weights({"a": a, "b": b}, {"a": 0.5, "b": 0.5}, UNIVERSE)
    assert long_df.empty and stats["n_change_events"] == 0


def test_combine_late_member_contributes_zero_before_first_event():
    early = _panel_from_events([("2026-01-01 00:00", "BTCUSDT", 0.4)])
    late = _panel_from_events([("2026-01-01 02:00", "BTCUSDT", 0.4)])
    long_df, _ = _runner.combine_weights({"early": early, "late": late}, {"early": 1.0, "late": 1.0}, UNIVERSE)
    rows = long_df[long_df["symbol"] == "BTCUSDT"].sort_values("timestamp")
    assert list(rows["target_weight"]) == pytest.approx([0.4, 0.8])
    assert list(rows["timestamp"]) == [pd.Timestamp("2026-01-01 00:00"), pd.Timestamp("2026-01-01 02:00")]


def test_combine_row_l1_clipped_when_gross_exceeds_one():
    a = _panel_from_events([("2026-01-01 00:00", "BTCUSDT", 0.7), ("2026-01-01 00:00", "ETHUSDT", 0.7)])
    long_df, stats = _runner.combine_weights({"a": a}, {"a": 1.0}, UNIVERSE)
    assert sorted(long_df["target_weight"]) == pytest.approx([0.5, 0.5])
    assert stats["n_rows_clipped"] == 1
    assert stats["raw_max_row_l1"] == pytest.approx(1.4)
    assert stats["max_row_l1"] == pytest.approx(1.0)


def test_combine_target_gross_scales_every_row():
    a = _panel_from_events([("2026-01-01 00:00", "BTCUSDT", 0.1), ("2026-01-01 00:00", "ETHUSDT", -0.3)])
    long_df, stats = _runner.combine_weights({"a": a}, {"a": 1.0}, UNIVERSE, target_gross=5.0)
    by_symbol = long_df.set_index("symbol")["target_weight"]
    assert by_symbol["BTCUSDT"] == pytest.approx(1.25) and by_symbol["ETHUSDT"] == pytest.approx(-3.75)
    assert stats["mean_row_l1"] == pytest.approx(5.0) and stats["raw_mean_row_l1"] == pytest.approx(0.4)
    assert stats["target_gross"] == 5.0


def test_combine_reemits_when_a_member_rebalances():
    """A member that re-emits the same target rebalanced to it (fixed-AUM
    sizing trades the price move), so the composite re-emits too. A change
    to zero closes; nothing is emitted for a symbol nobody holds."""
    a = _panel_from_events([
        ("2026-01-01 00:00", "BTCUSDT", 0.3),
        ("2026-01-01 01:00", "BTCUSDT", 0.3),
        ("2026-01-01 02:00", "BTCUSDT", 0.0),
        ("2026-01-01 02:00", "ETHUSDT", 0.0),
    ])
    long_df, _ = _runner.combine_weights({"a": a}, {"a": 1.0}, UNIVERSE)
    btc = long_df[long_df["symbol"] == "BTCUSDT"].sort_values("timestamp")
    assert list(btc["target_weight"]) == pytest.approx([0.3, 0.3, 0.0])
    assert set(long_df["symbol"]) == {"BTCUSDT"}


def test_combine_empty_members_returns_empty():
    long_df, stats = _runner.combine_weights({}, {}, UNIVERSE)
    assert long_df.empty and stats["n_change_events"] == 0


# --------------------------------------------------------------------------
# build_and_backtest: end-to-end pipeline (subprocess mocked)
# --------------------------------------------------------------------------


def test_build_and_backtest_writes_artifacts_and_replays_on_the_runs_data(tmp_path, monkeypatch):
    _setup_fake_run(tmp_path, monkeypatch)
    calls: list[list[str]] = []
    monkeypatch.setattr(_runner.subprocess, "run", _fake_backtest(calls))

    comp_dir = _build(include_os=True)

    assert comp_dir == tmp_path / "run_demo" / "composites" / "demo_eqw"
    for name in ("weights.parquet", "metrics.json", "manifest.json", "members.csv", "member_gross_daily.parquet"):
        assert (comp_dir / name).exists(), name

    manifest = json.loads((comp_dir / "manifest.json").read_text())
    assert manifest["members"] == ["a2", "a1"] and manifest["coefficients"] == {"a1": 0.5, "a2": 0.5}
    assert manifest["data_path"] == str(tmp_path / "data") and manifest["n_symbols"] == 3
    assert manifest["engine_fingerprint"] == FP
    assert [p["rerun"] for p in manifest["members_provenance"]] == [False, False]
    assert manifest["sizing"]["fixed_aum_sizing"] is True

    metrics = json.loads((comp_dir / "metrics.json").read_text())
    assert metrics["composite_id"] == "demo_eqw" and metrics["method"] == "equal_weight_demo"
    assert metrics["is_window"]["start"] == IS["start"] and metrics["os_window"]["start"] == OS["start"]

    members = pd.read_csv(comp_dir / "members.csv")
    assert set(members["alpha_id"]) == {"a1", "a2"}
    assert members["coefficient"].sum() == pytest.approx(1.0)
    assert members["is_gross_mean"].notna().all()

    weights = pd.read_parquet(comp_dir / "weights.parquet")
    assert set(weights.columns) == {"timestamp", "symbol", "target_weight"} and len(weights) > 0

    # fresh members: one call, the replay, on the run's data path and window
    assert len(calls) == 1
    cmd = calls[0]
    assert _flag(cmd, "--strategy") == "PrecomputedWeightsStrategy"
    assert _flag(cmd, "--data-path") == str(tmp_path / "data")
    assert _flag(cmd, "--start") == IS["start"] and _flag(cmd, "--end") == OS["end"]
    assert _flag(cmd, "--is-end") == IS["end"]
    assert _flag(cmd, "--max-portfolio-weight") == "1.0" and "--fixed-aum-sizing" in cmd
    assert json.loads(_flag(cmd, "--strategy-params"))["alpha_id"] == "demo_eqw"
    for flag in ("--no-prefix-check", "--no-enforce-quality", "--no-enforce-governance"):
        assert flag in cmd


def test_manifest_is_frozen_before_the_replay(tmp_path, monkeypatch):
    _setup_fake_run(tmp_path, monkeypatch)
    seen: list[bool] = []
    inner = _fake_backtest([])

    def run(cmd, **kw):
        seen.append((Path(_flag(cmd, "--output-dir")) / "manifest.json").exists())
        return inner(cmd, **kw)

    monkeypatch.setattr(_runner.subprocess, "run", run)
    _build()
    assert seen == [True]


def test_build_reruns_a_stale_member_in_auto_mode(tmp_path, monkeypatch):
    _setup_fake_run(tmp_path, monkeypatch)
    (tmp_path / "src" / "a1.py").write_text("# edited after archiving\n")
    calls: list[list[str]] = []
    monkeypatch.setattr(_runner.subprocess, "run", _fake_backtest(calls))

    comp_dir = _build()

    assert [_flag(c, "--strategy") for c in calls] == ["Foo", "PrecomputedWeightsStrategy"]
    member_cmd = calls[0]
    assert _flag(member_cmd, "--data-path") == str(tmp_path / "data")
    assert _flag(member_cmd, "--stale-bar-exit") == "2" and _flag(member_cmd, "--slippage") == "adv_tier"
    assert json.loads(_flag(member_cmd, "--strategy-params")) == {"k": 1}
    assert "--no-prefix-check" not in member_cmd  # changed source keeps the truncation check
    provenance = {p["alpha_id"]: p for p in json.loads((comp_dir / "manifest.json").read_text())["members_provenance"]}
    assert provenance["a1"]["rerun"] is True and provenance["a2"]["rerun"] is False


def test_build_reruns_every_member_in_always_mode(tmp_path, monkeypatch):
    _setup_fake_run(tmp_path, monkeypatch)
    calls: list[list[str]] = []
    monkeypatch.setattr(_runner.subprocess, "run", _fake_backtest(calls))
    _build(rerun_members="always")
    strategies = [_flag(c, "--strategy") for c in calls]
    assert sorted(strategies[:2]) == ["Bar", "Foo"] and strategies[2] == "PrecomputedWeightsStrategy"
    assert all("--no-prefix-check" in c for c in calls[:2])  # unchanged source: replay only


def test_build_never_mode_combines_stale_members_as_archived(tmp_path, monkeypatch, capsys):
    _setup_fake_run(tmp_path, monkeypatch)
    monkeypatch.setattr(_runner, "engine_fingerprint", lambda: "fp-new")
    calls: list[list[str]] = []
    monkeypatch.setattr(_runner.subprocess, "run", _fake_backtest(calls))
    comp_dir = _build(rerun_members="never")
    assert [_flag(c, "--strategy") for c in calls] == ["PrecomputedWeightsStrategy"]
    provenance = json.loads((comp_dir / "manifest.json").read_text())["members_provenance"]
    assert all(p["stale_reasons"] for p in provenance)
    assert "using stale member" in capsys.readouterr().err


def test_build_raises_when_a_stale_member_cannot_be_rerun(tmp_path, monkeypatch):
    _setup_fake_run(tmp_path, monkeypatch, with_config=False)
    monkeypatch.setattr(_runner.subprocess, "run", _fake_backtest([]))
    with pytest.raises(RuntimeError, match="cannot be rerun"):
        _build()


def test_build_rejects_invalid_rerun_mode(tmp_path, monkeypatch):
    _setup_fake_run(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="rerun_members"):
        _build(rerun_members="sometimes")


def test_build_rejects_members_that_disagree_on_sizing(tmp_path, monkeypatch):
    run_dir = _setup_fake_run(tmp_path, monkeypatch)
    d = run_dir / "alphas" / "a2"
    metrics = json.loads((d / "metrics.json").read_text())
    metrics["run_config"]["fixed_aum_sizing"] = False
    (d / "metrics.json").write_text(json.dumps(metrics))
    monkeypatch.setattr(_runner.subprocess, "run", _fake_backtest([]))
    with pytest.raises(ValueError, match="sizing"):
        _build()


def test_build_skips_os_when_include_os_false(tmp_path, monkeypatch):
    _setup_fake_run(tmp_path, monkeypatch)
    calls: list[list[str]] = []
    monkeypatch.setattr(_runner.subprocess, "run", _fake_backtest(calls))
    comp_dir = _build(composite_id="demo_isonly", include_os=False)
    assert len(calls) == 1 and "--is-end" not in calls[0]
    assert _flag(calls[0], "--end") == IS["end"]
    assert json.loads((comp_dir / "metrics.json").read_text())["os_window"] is None


def test_build_passes_target_gross_to_the_replay(tmp_path, monkeypatch):
    _setup_fake_run(tmp_path, monkeypatch)
    calls: list[list[str]] = []
    monkeypatch.setattr(_runner.subprocess, "run", _fake_backtest(calls))
    comp_dir = _build(target_gross=5.0)
    assert _flag(calls[0], "--max-portfolio-weight") == "5.0"
    manifest = json.loads((comp_dir / "manifest.json").read_text())
    assert manifest["target_gross"] == 5.0 and manifest["mean_row_l1"] == pytest.approx(5.0)


def test_build_rejects_empty_selection(tmp_path, monkeypatch):
    _setup_fake_run(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="empty list"):
        _build(select_members=lambda _: [])


def test_build_rejects_missing_coefficient(tmp_path, monkeypatch):
    _setup_fake_run(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="missing entries"):
        _build(member_weights=lambda ids, _df: {ids[0]: 1.0})


# --------------------------------------------------------------------------
# look-ahead guard: hostile selection code gets KeyError, not a silent leak
# --------------------------------------------------------------------------


def test_user_code_touching_os_column_raises(tmp_path, monkeypatch):
    _setup_fake_run(tmp_path, monkeypatch)
    monkeypatch.setattr(_runner.subprocess, "run", lambda cmd, **kw: None)
    with pytest.raises(KeyError):
        _build(select_members=lambda df: df.nlargest(2, "os_sharpe")["alpha_id"].tolist())


def test_user_weighting_touching_os_column_raises(tmp_path, monkeypatch):
    _setup_fake_run(tmp_path, monkeypatch)
    monkeypatch.setattr(_runner.subprocess, "run", lambda cmd, **kw: None)

    def hostile_weights(ids: list[str], df: pd.DataFrame) -> dict[str, float]:
        return df.set_index("alpha_id").loc[ids]["os_sharpe"].to_dict()

    with pytest.raises(KeyError):
        _build(member_weights=hostile_weights)
