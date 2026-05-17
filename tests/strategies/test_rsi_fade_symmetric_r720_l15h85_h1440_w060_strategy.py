from __future__ import annotations
from intraday.strategies.multi.rsi_fade_symmetric_r720_l15h85_h1440_w060_strategy import RsiFadeSymmetricR720L15h85H1440W060Strategy

def test_instantiate_and_run_smoke():
    s = RsiFadeSymmetricR720L15h85H1440W060Strategy(symbols=["BTCUSDT","ETHUSDT","SOLUSDT"])
    class _S:
        timestamp = None
        panel = None
        positions = {}
    out = s.generate_order(_S())
    assert out is None or hasattr(out, "orders")
