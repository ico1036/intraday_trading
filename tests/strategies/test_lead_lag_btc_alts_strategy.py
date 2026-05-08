from __future__ import annotations

from datetime import datetime

from intraday.strategies.multi.lead_lag_btc_alts_strategy import (
    ALPHA_CELL,
    SOURCE_NOTES,
    LeadLagBtcAltsStrategy,
)
from intraday.strategy import MarketState


def _state(panel):
    return MarketState(
        timestamp=datetime(2026, 3, 4),
        mid_price=0,
        imbalance=0,
        spread=0,
        spread_bps=0,
        best_bid=0,
        best_ask=0,
        best_bid_qty=0,
        best_ask_qty=0,
        panel=panel,
        positions={},
    )


def test_metadata():
    assert ALPHA_CELL["idea_family"] == "lead_lag_btc"
    assert SOURCE_NOTES


def test_btc_uptrend_longs_basket():
    syms = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    s = LeadLagBtcAltsStrategy(
        syms, signal_bars=10, rebalance_bars=10, entry_threshold=0.001
    )
    out = None
    for t in range(30):
        panel = {
            "BTCUSDT": {"close": 100.0 + t * 1.0},
            "ETHUSDT": {"close": 200.0},
            "SOLUSDT": {"close": 50.0},
        }
        out = s.generate_order(_state(panel))
    assert out is not None
    assert out["ETHUSDT"] is not None and out["ETHUSDT"].side.value == "BUY"
    assert out["SOLUSDT"] is not None and out["SOLUSDT"].side.value == "BUY"


def test_btc_downtrend_shorts_basket():
    syms = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    s = LeadLagBtcAltsStrategy(
        syms, signal_bars=10, rebalance_bars=10, entry_threshold=0.001
    )
    out = None
    for t in range(30):
        panel = {
            "BTCUSDT": {"close": 100.0 - t * 1.0},
            "ETHUSDT": {"close": 200.0},
            "SOLUSDT": {"close": 50.0},
        }
        out = s.generate_order(_state(panel))
    assert out is not None
    assert out["ETHUSDT"] is not None and out["ETHUSDT"].side.value == "SELL"
