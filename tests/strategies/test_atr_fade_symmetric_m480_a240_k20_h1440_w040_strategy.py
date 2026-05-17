from __future__ import annotations
from intraday.strategies.multi.atr_fade_symmetric_m480_a240_k20_h1440_w040_strategy import AtrFadeSymmetricM480A240K20H1440W040Strategy

def test_instantiate_and_run_smoke():
    s = AtrFadeSymmetricM480A240K20H1440W040Strategy(symbols=["BTCUSDT","ETHUSDT","SOLUSDT"])
    class _S:
        timestamp = None
        panel = None
        positions = {}
    out = s.generate_order(_S())
    assert out is None or hasattr(out, "orders")
