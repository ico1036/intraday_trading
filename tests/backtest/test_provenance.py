"""run_config round-trips through the CLI; the engine fingerprint tracks engine files."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from intraday.backtest import provenance

REPO = Path(__file__).resolve().parents[2]


def _backtest_module():
    spec = importlib.util.spec_from_file_location("backtest_cli", REPO / "scripts" / "tools" / "backtest.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_run_config_round_trips_through_the_cli():
    cfg = {
        "strategy": "XsVolumeRankStrategy", "strategy_params": {"reverse": True},
        "data_type": "bars", "data_path": "data/futures_klines_daily_pit", "symbol_data_paths": {},
        "bar_type": "TIME", "bar_size": 86400.0,
        "start": "2022-01-01", "end": "2026-05-07 23:59", "is_end": "2024-04-19 23:59",
        "initial_capital": 10000.0, "position_size_pct": 1.0, "leverage": 1, "max_portfolio_weight": 1.0,
        "maker_fee_rate": 0.0002, "taker_fee_rate": 0.0005, "fixed_aum_sizing": True,
        "funding": True, "funding_path": "data/funding_rates_full", "slippage": "adv_tier", "stale_bar_exit": 2,
    }
    cli = provenance.run_config_to_cli(cfg, output_dir="out", symbols=["BTCUSDT", "ETHUSDT"])
    args = _backtest_module().parse_args(cli)
    params = json.loads(args.strategy_params)
    assert provenance.run_config_from_args(args, params, {}) == cfg
    assert args.output_dir == "out" and args.symbols == ["BTCUSDT", "ETHUSDT"]


def test_run_config_overrides_and_no_funding():
    cfg = {"strategy": "Foo", "strategy_params": {}, "data_type": "bars", "data_path": "a", "symbol_data_paths": {},
           "bar_type": "TIME", "bar_size": 60.0, "start": None, "end": None, "is_end": None,
           "initial_capital": 1.0, "position_size_pct": 1.0, "leverage": 1, "max_portfolio_weight": 1.0,
           "maker_fee_rate": 0.0, "taker_fee_rate": 0.0, "fixed_aum_sizing": False,
           "funding": False, "funding_path": "f", "slippage": "none", "stale_bar_exit": 0}
    cli = provenance.run_config_to_cli(cfg, output_dir="o", symbols=["A"], overrides={"data_path": "b", "stale_bar_exit": 2})
    assert "--no-funding" in cli and "--fixed-aum-sizing" not in cli and "--start" not in cli
    assert cli[cli.index("--data-path") + 1] == "b" and cli[cli.index("--stale-bar-exit") + 1] == "2"


def test_cli_cost_defaults_come_from_one_place():
    args = _backtest_module().parse_args(["--strategy", "X", "--symbols", "A", "--output-dir", "o"])
    for key, value in provenance.COST_DEFAULTS.items():
        assert getattr(args, key) == value


def test_engine_fingerprint_tracks_engine_files(tmp_path):
    for rel in provenance.ENGINE_FILES:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x")
    before = provenance.engine_fingerprint(tmp_path)
    assert before == provenance.engine_fingerprint(tmp_path)
    (tmp_path / provenance.ENGINE_FILES[0]).write_text("y")
    assert provenance.engine_fingerprint(tmp_path) != before
    assert len(before) == 16


def test_class_to_module_name():
    assert provenance.class_to_module_name("XsFactorAmihud60dFwdC10") == "xs_factor_amihud60d_fwd_c10"
    assert provenance.class_to_module_name("XsVolumeRankStrategy") == "xs_volume_rank_strategy"
