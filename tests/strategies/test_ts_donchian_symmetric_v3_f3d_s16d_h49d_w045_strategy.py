from __future__ import annotations

from intraday.strategies.multi.ts_donchian_symmetric_v3_f3d_s16d_h49d_w045_strategy import TsDonchianSymmetricV3F3dS16dH49dW045Strategy


def test_instantiate_and_run_smoke():
    s = TsDonchianSymmetricV3F3dS16dH49dW045Strategy(symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    class _S:
        timestamp = None
        panel = None
        positions = {}
    out = s.generate_order(_S())
    assert out is None or hasattr(out, "orders")
