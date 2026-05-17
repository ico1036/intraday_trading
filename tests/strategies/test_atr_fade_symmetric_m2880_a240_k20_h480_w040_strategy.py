from __future__ import annotations
from intraday.strategies.multi.atr_fade_symmetric_m2880_a240_k20_h480_w040_strategy import AtrFadeSymmetricM2880A240K20H480W040Strategy

def test_instantiate_and_run_smoke():
    s = AtrFadeSymmetricM2880A240K20H480W040Strategy(symbols=["BTCUSDT","ETHUSDT","SOLUSDT"])
    class _S:
        timestamp = None
        panel = None
        positions = {}
    out = s.generate_order(_S())
    assert out is None or hasattr(out, "orders")
