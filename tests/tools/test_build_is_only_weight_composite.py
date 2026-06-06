from __future__ import annotations

import importlib.util
from pathlib import Path

import pandas as pd
import pytest


MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "tools" / "build_is_only_weight_composite.py"
SPEC = importlib.util.spec_from_file_location("build_is_only_weight_composite", MODULE_PATH)
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


UNIVERSE = ["BTCUSDT", "ETHUSDT"]


def _panel(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
    events = pd.DataFrame(
        [{"timestamp": pd.Timestamp(ts), "symbol": symbol, "target_weight": weight} for ts, symbol, weight in rows]
    )
    return builder._events_to_panel(events, UNIVERSE)


def test_target_gross_scales_netted_weights_without_changing_direction():
    panels = {
        "a": _panel([("2026-01-01", "BTCUSDT", 0.30)]),
        "b": _panel([("2026-01-01", "ETHUSDT", -0.10)]),
    }

    long_df, stats = builder._combine_weights(
        panels,
        {"a": 1.0, "b": 1.0},
        UNIVERSE,
        target_gross=0.8,
        max_gross=1.0,
    )

    weights = dict(zip(long_df["symbol"], long_df["target_weight"]))
    assert weights["BTCUSDT"] == pytest.approx(0.6)
    assert weights["ETHUSDT"] == pytest.approx(-0.2)
    assert stats["raw_mean_row_l1"] == pytest.approx(0.4)
    assert stats["mean_row_l1"] == pytest.approx(0.8)
    assert stats["n_rows_clipped"] == 0


def test_target_gross_is_capped_by_max_gross():
    panels = {"a": _panel([("2026-01-01", "BTCUSDT", 0.25)])}

    _, stats = builder._combine_weights(
        panels,
        {"a": 1.0},
        UNIVERSE,
        target_gross=1.5,
        max_gross=1.0,
    )

    assert stats["mean_row_l1"] == pytest.approx(1.0)
    assert stats["target_gross"] == pytest.approx(1.5)
    assert stats["max_gross"] == pytest.approx(1.0)


def test_combine_reemits_unchanged_nonzero_targets_each_rebalance():
    panels = {"a": _panel([
        ("2026-01-01", "BTCUSDT", 0.25),
        ("2026-01-02", "BTCUSDT", 0.25),
    ])}

    long_df, _ = builder._combine_weights(panels, {"a": 1.0}, UNIVERSE)

    btc = long_df[long_df["symbol"] == "BTCUSDT"].sort_values("timestamp")
    assert list(btc["timestamp"]) == [pd.Timestamp("2026-01-01"), pd.Timestamp("2026-01-02")]
    assert list(btc["target_weight"]) == pytest.approx([0.25, 0.25])


def test_netted_greedy_drop_uses_is_price_returns_to_remove_bad_member():
    dates = pd.date_range("2026-01-01", periods=5, freq="D")
    price_returns = pd.DataFrame(
        {
            "BTCUSDT": [0.0, 0.03, 0.03, 0.03, 0.03],
            "ETHUSDT": [0.0, 0.0, 0.0, 0.0, 0.0],
        },
        index=dates,
    )
    panels = {
        "good": _panel([("2026-01-01", "BTCUSDT", 0.5)]),
        "bad": _panel([("2026-01-01", "BTCUSDT", -0.5)]),
    }

    kept, meta = builder._netted_greedy_drop(
        ["good", "bad"],
        panels,
        {"good": 1, "bad": 1},
        UNIVERSE,
        price_returns,
        min_members=1,
        objective="return",
        min_improvement=0.0,
    )

    assert kept == ["good"]
    assert meta["netted_greedy_final_members"] == 1
    assert meta["netted_greedy_drops"][0]["dropped"] == "bad"


def test_rolling_combine_resets_portfolio_at_rebalance_date():
    panels = {
        "a": _panel([("2026-01-01", "BTCUSDT", 0.4)]),
        "b": _panel([("2026-01-01", "ETHUSDT", 0.5)]),
    }
    schedule = [
        {
            "rebal_date": pd.Timestamp("2026-01-01"),
            "end_date": pd.Timestamp("2026-02-01"),
            "selected": ["a"],
            "coefficients": {"a": 1.0},
        },
        {
            "rebal_date": pd.Timestamp("2026-02-01"),
            "end_date": pd.Timestamp("2026-03-01"),
            "selected": ["b"],
            "coefficients": {"b": 1.0},
        },
    ]

    long_df, stats = builder._combine_rolling_weights(panels, schedule, UNIVERSE)

    rows = {
        (row.timestamp, row.symbol): row.target_weight
        for row in long_df.itertuples(index=False)
    }
    assert rows[(pd.Timestamp("2026-01-01"), "BTCUSDT")] == pytest.approx(0.4)
    assert rows[(pd.Timestamp("2026-02-01"), "BTCUSDT")] == pytest.approx(0.0)
    assert rows[(pd.Timestamp("2026-02-01"), "ETHUSDT")] == pytest.approx(0.5)
    assert stats["mean_row_l1"] == pytest.approx(0.45)
