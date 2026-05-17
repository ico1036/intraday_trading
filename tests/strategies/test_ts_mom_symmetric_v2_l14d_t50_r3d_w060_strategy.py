from __future__ import annotations

from intraday.strategies.multi.ts_mom_symmetric_v2_l14d_t50_r3d_w060_strategy import TsMomSymmetricV2L14dT50R3dW060Strategy


def test_instantiate_and_run_smoke():
    s = TsMomSymmetricV2L14dT50R3dW060Strategy(symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    class _S:
        timestamp = None
        panel = None
        positions = {}
    out = s.generate_order(_S())
    assert out is None or hasattr(out, "orders")
