from datetime import datetime
from intraday.strategies.multi.pair_spread_btc_eth_strategy import (
    ALPHA_CELL, SOURCE_NOTES, PairSpreadBtcEthStrategy
)
from intraday.strategy import MarketState


def _state(panel):
    return MarketState(
        timestamp=datetime(2026, 3, 4), mid_price=0, imbalance=0, spread=0,
        spread_bps=0, best_bid=0, best_ask=0, best_bid_qty=0, best_ask_qty=0,
        panel=panel, positions={},
    )


def test_metadata():
    assert ALPHA_CELL["idea_family"] == "pair_spread_meanrev"
    assert SOURCE_NOTES


def test_high_z_shorts_a_longs_b():
    s = PairSpreadBtcEthStrategy(
        ["BTCUSDT", "ETHUSDT"], lookback_bars=20, rebalance_bars=1,
        entry_z=0.5, exit_z=0.1,
    )
    out = None
    # 20 bars: BTC=100, ETH=100 → spread=0
    for _ in range(20):
        out = s.generate_order(_state({"BTCUSDT": {"close": 100}, "ETHUSDT": {"close": 100}}))
    # Then BTC spikes to 110 → spread > 0, z high
    for _ in range(10):
        out = s.generate_order(_state({"BTCUSDT": {"close": 110}, "ETHUSDT": {"close": 100}}))
    assert out is not None
    assert out["BTCUSDT"] is not None and out["BTCUSDT"].side.value == "SELL"
    assert out["ETHUSDT"] is not None and out["ETHUSDT"].side.value == "BUY"
