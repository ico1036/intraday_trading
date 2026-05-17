from __future__ import annotations
from intraday.strategies.multi.atr_fade_symmetric_m480_a480_k15_h2880_w060_strategy import AtrFadeSymmetricM480A480K15H2880W060Strategy

def test_instantiate_and_run_smoke():
    s = AtrFadeSymmetricM480A480K15H2880W060Strategy(symbols=["BTCUSDT","ETHUSDT","SOLUSDT"])
    class _S:
        timestamp = None
        panel = None
        positions = {}
    out = s.generate_order(_S())
    assert out is None or hasattr(out, "orders")
