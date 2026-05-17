from __future__ import annotations
from intraday.strategies.multi.rsi_fade_symmetric_r1440_l25h75_h480_w060_strategy import RsiFadeSymmetricR1440L25h75H480W060Strategy

def test_instantiate_and_run_smoke():
    s = RsiFadeSymmetricR1440L25h75H480W060Strategy(symbols=["BTCUSDT","ETHUSDT","SOLUSDT"])
    class _S:
        timestamp = None
        panel = None
        positions = {}
    out = s.generate_order(_S())
    assert out is None or hasattr(out, "orders")
