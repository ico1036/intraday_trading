from __future__ import annotations
from intraday.strategies.multi.bb_fade_symmetric_l720_z20_h2880_w040_strategy import BbFadeSymmetricL720Z20H2880W040Strategy

def test_instantiate_and_run_smoke():
    s = BbFadeSymmetricL720Z20H2880W040Strategy(symbols=["BTCUSDT","ETHUSDT","SOLUSDT"])
    class _S:
        timestamp = None
        panel = None
        positions = {}
    out = s.generate_order(_S())
    assert out is None or hasattr(out, "orders")
