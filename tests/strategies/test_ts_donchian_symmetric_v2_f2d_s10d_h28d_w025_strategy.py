from __future__ import annotations

from intraday.strategies.multi.ts_donchian_symmetric_v2_f2d_s10d_h28d_w025_strategy import TsDonchianSymmetricV2F2dS10dH28dW025Strategy


def test_instantiate_and_run_smoke():
    s = TsDonchianSymmetricV2F2dS10dH28dW025Strategy(symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    class _S:
        timestamp = None
        panel = None
        positions = {}
    out = s.generate_order(_S())
    assert out is None or hasattr(out, "orders")
