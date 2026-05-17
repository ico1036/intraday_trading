from __future__ import annotations

from intraday.strategies.multi.xs_donchian_rank_c5d_k1_r1d_strategy import XsDonchianRankC5dK1R1dStrategy


def test_instantiate_and_run_smoke():
    s = XsDonchianRankC5dK1R1dStrategy(symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    # No data yet — generate_order must be safe.
    class _S:
        timestamp = None
        panel = None
        positions = {}
    assert s.generate_order(_S()) is None or hasattr(s.generate_order(_S()), "orders") or s.generate_order(_S()) is None
