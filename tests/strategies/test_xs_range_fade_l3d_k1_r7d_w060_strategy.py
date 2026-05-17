from __future__ import annotations
from intraday.strategies.multi.xs_range_fade_l3d_k1_r7d_w060_strategy import XsRangeFadeL3dK1R7dW060Strategy

def test_instantiate_and_run_smoke():
    s = XsRangeFadeL3dK1R7dW060Strategy(symbols=["BTCUSDT","ETHUSDT","SOLUSDT"])
    class _S:
        timestamp = None
        panel = None
        positions = {}
    out = s.generate_order(_S())
    assert out is None or hasattr(out, "orders")
