from __future__ import annotations
from intraday.strategies.multi.xs_range_fade_l5d_k1_r1d_w040_strategy import XsRangeFadeL5dK1R1dW040Strategy

def test_instantiate_and_run_smoke():
    s = XsRangeFadeL5dK1R1dW040Strategy(symbols=["BTCUSDT","ETHUSDT","SOLUSDT"])
    class _S:
        timestamp = None
        panel = None
        positions = {}
    out = s.generate_order(_S())
    assert out is None or hasattr(out, "orders")
