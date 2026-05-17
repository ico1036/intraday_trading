from __future__ import annotations
from intraday.strategies.multi.atr_fade_symmetric_m480_a240_k30_h480_w060_strategy import AtrFadeSymmetricM480A240K30H480W060Strategy

def test_instantiate_and_run_smoke():
    s = AtrFadeSymmetricM480A240K30H480W060Strategy(symbols=["BTCUSDT","ETHUSDT","SOLUSDT"])
    class _S:
        timestamp = None
        panel = None
        positions = {}
    out = s.generate_order(_S())
    assert out is None or hasattr(out, "orders")
