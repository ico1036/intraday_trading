from __future__ import annotations
from intraday.strategies.multi.atr_fade_symmetric_m240_a240_k30_h1440_w040_strategy import AtrFadeSymmetricM240A240K30H1440W040Strategy

def test_instantiate_and_run_smoke():
    s = AtrFadeSymmetricM240A240K30H1440W040Strategy(symbols=["BTCUSDT","ETHUSDT","SOLUSDT"])
    class _S:
        timestamp = None
        panel = None
        positions = {}
    out = s.generate_order(_S())
    assert out is None or hasattr(out, "orders")
