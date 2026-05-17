from __future__ import annotations
from intraday.strategies.multi.atr_fade_symmetric_m1440_a1440_k15_h7200_w060_strategy import AtrFadeSymmetricM1440A1440K15H7200W060Strategy

def test_instantiate_and_run_smoke():
    s = AtrFadeSymmetricM1440A1440K15H7200W060Strategy(symbols=["BTCUSDT","ETHUSDT","SOLUSDT"])
    class _S:
        timestamp = None
        panel = None
        positions = {}
    out = s.generate_order(_S())
    assert out is None or hasattr(out, "orders")
