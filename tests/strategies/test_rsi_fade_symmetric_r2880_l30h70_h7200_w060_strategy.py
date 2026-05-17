from __future__ import annotations
from intraday.strategies.multi.rsi_fade_symmetric_r2880_l30h70_h7200_w060_strategy import RsiFadeSymmetricR2880L30h70H7200W060Strategy

def test_instantiate_and_run_smoke():
    s = RsiFadeSymmetricR2880L30h70H7200W060Strategy(symbols=["BTCUSDT","ETHUSDT","SOLUSDT"])
    class _S:
        timestamp = None
        panel = None
        positions = {}
    out = s.generate_order(_S())
    assert out is None or hasattr(out, "orders")
