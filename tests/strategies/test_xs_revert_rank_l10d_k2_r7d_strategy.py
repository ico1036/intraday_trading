from __future__ import annotations

from intraday.strategies.multi.xs_revert_rank_l10d_k2_r7d_strategy import XsRevertRankL10dK2R7dStrategy


def test_instantiate_and_run_smoke():
    s = XsRevertRankL10dK2R7dStrategy(symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    # No data yet — generate_order must be safe.
    class _S:
        timestamp = None
        panel = None
        positions = {}
    assert s.generate_order(_S()) is None or hasattr(s.generate_order(_S()), "orders") or s.generate_order(_S()) is None
