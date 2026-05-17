from __future__ import annotations
from intraday.strategies.multi.rsi_fade_symmetric_r240_l20h80_h7200_w040_strategy import RsiFadeSymmetricR240L20h80H7200W040Strategy

def test_instantiate_and_run_smoke():
    s = RsiFadeSymmetricR240L20h80H7200W040Strategy(symbols=["BTCUSDT","ETHUSDT","SOLUSDT"])
    class _S:
        timestamp = None
        panel = None
        positions = {}
    out = s.generate_order(_S())
    assert out is None or hasattr(out, "orders")
