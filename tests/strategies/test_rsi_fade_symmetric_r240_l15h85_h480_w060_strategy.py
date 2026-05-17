from __future__ import annotations
from intraday.strategies.multi.rsi_fade_symmetric_r240_l15h85_h480_w060_strategy import RsiFadeSymmetricR240L15h85H480W060Strategy

def test_instantiate_and_run_smoke():
    s = RsiFadeSymmetricR240L15h85H480W060Strategy(symbols=["BTCUSDT","ETHUSDT","SOLUSDT"])
    class _S:
        timestamp = None
        panel = None
        positions = {}
    out = s.generate_order(_S())
    assert out is None or hasattr(out, "orders")
