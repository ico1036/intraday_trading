from __future__ import annotations
from intraday.strategies.multi.rsi_fade_symmetric_r1440_l20h80_h7200_w060_strategy import RsiFadeSymmetricR1440L20h80H7200W060Strategy

def test_instantiate_and_run_smoke():
    s = RsiFadeSymmetricR1440L20h80H7200W060Strategy(symbols=["BTCUSDT","ETHUSDT","SOLUSDT"])
    class _S:
        timestamp = None
        panel = None
        positions = {}
    out = s.generate_order(_S())
    assert out is None or hasattr(out, "orders")
