from __future__ import annotations
from intraday.strategies.multi.bb_fade_symmetric_l480_z15_h2880_w060_strategy import BbFadeSymmetricL480Z15H2880W060Strategy

def test_instantiate_and_run_smoke():
    s = BbFadeSymmetricL480Z15H2880W060Strategy(symbols=["BTCUSDT","ETHUSDT","SOLUSDT"])
    class _S:
        timestamp = None
        panel = None
        positions = {}
    out = s.generate_order(_S())
    assert out is None or hasattr(out, "orders")
