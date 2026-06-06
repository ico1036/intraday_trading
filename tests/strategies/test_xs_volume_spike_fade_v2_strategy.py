from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from intraday.strategies.multi.xs_volume_spike_fade_v2_strategy import (
    ALPHA_CELL,
    SOURCE_NOTES,
    XsVolumeSpikeFadeV2Strategy,
)
from intraday.strategy import MarketState, Side


D0 = datetime(2024, 1, 1)


def _state(panel: dict, ts: datetime, positions: dict | None = None) -> MarketState:
    panel = {
        s: ({**v, "timestamp": ts} if "timestamp" not in v else v)
        for s, v in panel.items()
    }
    return MarketState(
        timestamp=ts,
        mid_price=0.0,
        imbalance=0.0,
        spread=0.0,
        spread_bps=0.0,
        best_bid=0.0,
        best_ask=0.0,
        best_bid_qty=0.0,
        best_ask_qty=0.0,
        panel=panel,
        positions=positions or {},
    )


def _feed_days(strat, daily: list[dict], positions: dict | None = None):
    out = None
    for i, panel in enumerate(daily):
        out = strat.generate_order(_state(panel, D0 + timedelta(days=i), positions))
    out = strat.generate_order(
        _state({}, D0 + timedelta(days=len(daily)), positions)
    )
    return out


def _strategy(symbols: list[str]) -> XsVolumeSpikeFadeV2Strategy:
    return XsVolumeSpikeFadeV2Strategy(
        symbols=symbols,
        max_weight=1.0,
        volume_lookback=3,
        health_lookback=2,
        min_median_quote_volume=100.0,
        min_quote_volume=100.0,
        min_spike_ratio=3.0,
        healthy_return_threshold=0.05,
        min_long_return=0.0,
        max_long_volume_ratio=2.0,
        short_pct=0.5,
    )


def test_alpha_metadata_contract():
    assert set(ALPHA_CELL) == {"bar", "transform", "horizon", "universe", "exit", "idea_family"}
    assert ALPHA_CELL["idea_family"] == "xs_volume_spike_fade_v2"
    assert SOURCE_NOTES == ["research/notes/xs_volume_spike_fade_v2.md"]


def test_shorts_suspicious_volume_spike_but_not_healthy_growth_or_trash():
    syms = ["SUSP", "HEALTHY", "TRASH", "LONG"]
    strat = _strategy(syms)
    daily = [
        {
            "SUSP": {"quote_volume": 100.0, "close": 100.0},
            "HEALTHY": {"quote_volume": 100.0, "close": 100.0},
            "TRASH": {"quote_volume": 1.0, "close": 10.0},
            "LONG": {"quote_volume": 200.0, "close": 100.0},
        },
        {
            "SUSP": {"quote_volume": 110.0, "close": 99.0},
            "HEALTHY": {"quote_volume": 110.0, "close": 103.0},
            "TRASH": {"quote_volume": 2.0, "close": 10.0},
            "LONG": {"quote_volume": 210.0, "close": 101.0},
        },
        {
            "SUSP": {"quote_volume": 105.0, "close": 98.0},
            "HEALTHY": {"quote_volume": 105.0, "close": 108.0},
            "TRASH": {"quote_volume": 1.0, "close": 9.0},
            "LONG": {"quote_volume": 205.0, "close": 103.0},
        },
        {
            "SUSP": {"quote_volume": 650.0, "close": 97.0},
            "HEALTHY": {"quote_volume": 700.0, "close": 115.0},
            "TRASH": {"quote_volume": 1000.0, "close": 8.0},
            "LONG": {"quote_volume": 220.0, "close": 106.0},
        },
    ]

    po = _feed_days(strat, daily)

    assert po is not None
    active = po.active_orders
    assert active["SUSP"].side is Side.SELL
    assert active["LONG"].side is Side.BUY
    assert "HEALTHY" not in active
    assert "TRASH" not in active


def test_long_short_weights_are_dollar_neutral():
    syms = ["S1", "S2", "L1", "L2", "NEUTRAL"]
    strat = _strategy(syms)
    daily = []
    for qv_s1, qv_s2, qv_l1, qv_l2, qv_n, c_s1, c_s2, c_l1, c_l2, c_n in [
        (100, 120, 200, 220, 180, 100, 100, 100, 100, 100),
        (105, 125, 205, 225, 182, 99, 99, 101, 102, 100),
        (100, 120, 210, 230, 181, 98, 98, 103, 104, 100),
        (600, 700, 220, 240, 180, 97, 96, 106, 108, 100),
    ]:
        daily.append({
            "S1": {"quote_volume": qv_s1, "close": c_s1},
            "S2": {"quote_volume": qv_s2, "close": c_s2},
            "L1": {"quote_volume": qv_l1, "close": c_l1},
            "L2": {"quote_volume": qv_l2, "close": c_l2},
            "NEUTRAL": {"quote_volume": qv_n, "close": c_n},
        })

    po = _feed_days(strat, daily)

    assert po is not None
    buy_gross = sum(o.weight for o in po.active_orders.values() if o.side is Side.BUY)
    sell_gross = sum(o.weight for o in po.active_orders.values() if o.side is Side.SELL)
    assert buy_gross == pytest.approx(0.5)
    assert sell_gross == pytest.approx(0.5)


def test_filtered_symbol_with_existing_position_is_closed():
    syms = ["SUSP", "LONG", "TRASH"]
    strat = _strategy(syms)
    daily = [
        {
            "SUSP": {"quote_volume": 100.0, "close": 100.0},
            "LONG": {"quote_volume": 200.0, "close": 100.0},
            "TRASH": {"quote_volume": 1.0, "close": 10.0},
        },
        {
            "SUSP": {"quote_volume": 105.0, "close": 99.0},
            "LONG": {"quote_volume": 210.0, "close": 101.0},
            "TRASH": {"quote_volume": 2.0, "close": 10.0},
        },
        {
            "SUSP": {"quote_volume": 100.0, "close": 98.0},
            "LONG": {"quote_volume": 205.0, "close": 103.0},
            "TRASH": {"quote_volume": 1.0, "close": 9.0},
        },
        {
            "SUSP": {"quote_volume": 600.0, "close": 97.0},
            "LONG": {"quote_volume": 220.0, "close": 106.0},
            "TRASH": {"quote_volume": 1000.0, "close": 8.0},
        },
    ]
    positions = {"TRASH": {"side": "LONG"}}

    po = _feed_days(strat, daily, positions=positions)

    assert po is not None
    assert po["TRASH"].side is Side.SELL
    assert po["TRASH"].quantity == 0.0
