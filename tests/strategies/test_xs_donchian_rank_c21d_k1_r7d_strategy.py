from __future__ import annotations

from intraday.strategies.multi.xs_donchian_rank_c21d_k1_r7d_strategy import XsDonchianRankC21dK1R7dStrategy


def test_instantiate_and_run_smoke():
    s = XsDonchianRankC21dK1R7dStrategy(symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    # No data yet — generate_order must be safe.
    class _S:
        timestamp = None
        panel = None
        positions = {}
    assert s.generate_order(_S()) is None or hasattr(s.generate_order(_S()), "orders") or s.generate_order(_S()) is None
