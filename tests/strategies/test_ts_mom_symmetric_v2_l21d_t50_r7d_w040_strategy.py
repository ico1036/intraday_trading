from __future__ import annotations

from intraday.strategies.multi.ts_mom_symmetric_v2_l21d_t50_r7d_w040_strategy import TsMomSymmetricV2L21dT50R7dW040Strategy


def test_instantiate_and_run_smoke():
    s = TsMomSymmetricV2L21dT50R7dW040Strategy(symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    class _S:
        timestamp = None
        panel = None
        positions = {}
    out = s.generate_order(_S())
    assert out is None or hasattr(out, "orders")
