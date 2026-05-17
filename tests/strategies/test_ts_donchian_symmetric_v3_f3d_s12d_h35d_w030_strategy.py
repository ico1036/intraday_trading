from __future__ import annotations

from intraday.strategies.multi.ts_donchian_symmetric_v3_f3d_s12d_h35d_w030_strategy import TsDonchianSymmetricV3F3dS12dH35dW030Strategy


def test_instantiate_and_run_smoke():
    s = TsDonchianSymmetricV3F3dS12dH35dW030Strategy(symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    class _S:
        timestamp = None
        panel = None
        positions = {}
    out = s.generate_order(_S())
    assert out is None or hasattr(out, "orders")
