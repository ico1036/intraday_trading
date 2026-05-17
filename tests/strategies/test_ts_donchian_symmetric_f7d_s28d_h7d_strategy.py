from __future__ import annotations

from intraday.strategies.multi.ts_donchian_symmetric_f7d_s28d_h7d_strategy import TsDonchianSymmetricF7dS28dH7dStrategy


def test_instantiate_and_run_smoke():
    s = TsDonchianSymmetricF7dS28dH7dStrategy(symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    # No data yet — generate_order must be safe.
    class _S:
        timestamp = None
        panel = None
        positions = {}
    assert s.generate_order(_S()) is None or hasattr(s.generate_order(_S()), "orders") or s.generate_order(_S()) is None
