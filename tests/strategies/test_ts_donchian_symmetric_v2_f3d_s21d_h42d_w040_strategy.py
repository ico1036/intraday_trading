from __future__ import annotations

from intraday.strategies.multi.ts_donchian_symmetric_v2_f3d_s21d_h42d_w040_strategy import TsDonchianSymmetricV2F3dS21dH42dW040Strategy


def test_instantiate_and_run_smoke():
    s = TsDonchianSymmetricV2F3dS21dH42dW040Strategy(symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    class _S:
        timestamp = None
        panel = None
        positions = {}
    out = s.generate_order(_S())
    assert out is None or hasattr(out, "orders")
