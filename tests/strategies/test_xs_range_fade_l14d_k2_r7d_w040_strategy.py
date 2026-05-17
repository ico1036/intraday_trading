from __future__ import annotations
from intraday.strategies.multi.xs_range_fade_l14d_k2_r7d_w040_strategy import XsRangeFadeL14dK2R7dW040Strategy

def test_instantiate_and_run_smoke():
    s = XsRangeFadeL14dK2R7dW040Strategy(symbols=["BTCUSDT","ETHUSDT","SOLUSDT"])
    class _S:
        timestamp = None
        panel = None
        positions = {}
    out = s.generate_order(_S())
    assert out is None or hasattr(out, "orders")
