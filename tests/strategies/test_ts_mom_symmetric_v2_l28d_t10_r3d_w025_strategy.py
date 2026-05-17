from __future__ import annotations

from intraday.strategies.multi.ts_mom_symmetric_v2_l28d_t10_r3d_w025_strategy import TsMomSymmetricV2L28dT10R3dW025Strategy


def test_instantiate_and_run_smoke():
    s = TsMomSymmetricV2L28dT10R3dW025Strategy(symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    class _S:
        timestamp = None
        panel = None
        positions = {}
    out = s.generate_order(_S())
    assert out is None or hasattr(out, "orders")
