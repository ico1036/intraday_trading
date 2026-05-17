from __future__ import annotations
from intraday.strategies.multi.xs_range_fade_l7d_k1_r3d_w060_strategy import XsRangeFadeL7dK1R3dW060Strategy

def test_instantiate_and_run_smoke():
    s = XsRangeFadeL7dK1R3dW060Strategy(symbols=["BTCUSDT","ETHUSDT","SOLUSDT"])
    class _S:
        timestamp = None
        panel = None
        positions = {}
    out = s.generate_order(_S())
    assert out is None or hasattr(out, "orders")
