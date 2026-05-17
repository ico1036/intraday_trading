from __future__ import annotations
from intraday.strategies.multi.atr_fade_symmetric_m2880_a480_k15_h1440_w060_strategy import AtrFadeSymmetricM2880A480K15H1440W060Strategy

def test_instantiate_and_run_smoke():
    s = AtrFadeSymmetricM2880A480K15H1440W060Strategy(symbols=["BTCUSDT","ETHUSDT","SOLUSDT"])
    class _S:
        timestamp = None
        panel = None
        positions = {}
    out = s.generate_order(_S())
    assert out is None or hasattr(out, "orders")
