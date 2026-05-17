from __future__ import annotations
from intraday.strategies.multi.rsi_fade_symmetric_r1440_l30h70_h2880_w060_strategy import RsiFadeSymmetricR1440L30h70H2880W060Strategy

def test_instantiate_and_run_smoke():
    s = RsiFadeSymmetricR1440L30h70H2880W060Strategy(symbols=["BTCUSDT","ETHUSDT","SOLUSDT"])
    class _S:
        timestamp = None
        panel = None
        positions = {}
    out = s.generate_order(_S())
    assert out is None or hasattr(out, "orders")
