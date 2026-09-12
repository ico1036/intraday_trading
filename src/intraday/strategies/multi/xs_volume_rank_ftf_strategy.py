"""xs_volume_rank_ftf — xs_volume_rank (reverse) with the funding tail filter.

Same book as ``XsVolumeRankStrategy(reverse=True)``: long the bottom half of
the universe by yesterday's quote volume, short the top half, equal weight,
daily. Before the short leg is placed, every candidate whose predicted
funding for the day is below −80 bps is dropped and the remaining shorts are
scaled back to 0.5 gross. The predictor is ``intraday.funding_filter``
(frozen rule funding_tail_filter_v1; see research/notes).

Why: the short leg's realized funding is a fat left tail — a squeezed name
pays hundreds of bps a day and the same names carry the price alpha, so a
level cut on predicted funding is the only cut that removes cost without
removing the whole leg. The pre-registration sets the read-out.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side
from intraday.strategies.multi.xs_volume_rank_strategy import XsVolumeRankStrategy


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "rolling_rank",
    "horizon": "multi_day",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "xs_volume_rank_funding_filter",
}
SOURCE_NOTES: list[str] = [
    "research/notes/xs_volume_rank.md",
    "research/notes/funding_tail_onset.md",
    "research/notes/funding_tail_filter_v1_prereg.md",
]


class XsVolumeRankFtfStrategy(XsVolumeRankStrategy):
    def __init__(
        self,
        symbols: list[str],
        rebalance_bars: int = 1,
        max_weight: float = 0.05,
        reverse: bool = True,
        threshold_bps: float = -80.0,
        funding_path: str = "data/funding_rates_full",
        klines_path: str = "data/futures_klines_daily_pit",
        model_dir: str = "data/funding_filter_models",
        filter: Any = None,
        **kw: Any,
    ):
        super().__init__(symbols, rebalance_bars=rebalance_bars, max_weight=max_weight, reverse=reverse, **kw)
        self.threshold_bps = float(threshold_bps)
        self.funding_path = funding_path
        self.klines_path = klines_path
        self.model_dir = model_dir
        self._filter = filter
        self.blocked_log: list[tuple[pd.Timestamp, int, int]] = []

    def _get_filter(self):
        if self._filter is None:
            from intraday.funding_filter import FundingTailFilter
            self._filter = FundingTailFilter(
                self.symbols, funding_path=self.funding_path, klines_path=self.klines_path,
                model_dir=self.model_dir, threshold_bps=self.threshold_bps,
            )
        return self._filter

    def _build_orders(self, state: MarketState, qv: dict[str, float]) -> PortfolioOrder | None:
        if len(qv) < 2:
            return None
        ranked = sorted(qv.items(), key=lambda t: t[1], reverse=True)
        half = len(ranked) // 2
        if half == 0:
            return None
        if self.reverse:
            new_long = {s for s, _ in ranked[-half:]}
            new_short = {s for s, _ in ranked[:half]}
        else:
            new_long = {s for s, _ in ranked[:half]}
            new_short = {s for s, _ in ranked[-half:]}

        # The book for the day starting at state.timestamp; the filter sees
        # data through yesterday plus today's 00:00 settlement.
        day = pd.Timestamp(state.timestamp).normalize()
        blocked = self._get_filter().blocked(day, new_short)
        if blocked:
            self.blocked_log.append((day, len(blocked), len(new_short)))
            new_short = new_short - blocked

        per_long = min(self.max_weight, 0.5 / half)
        per_short = min(self.max_weight, 0.5 / len(new_short)) if new_short else 0.0

        orders: dict[str, Order | None] = {}
        for s in self.symbols:
            current = self._side(state, s)
            if s in new_long:
                orders[s] = Order(side=Side.BUY, quantity=0.0, weight=per_long, order_type=OrderType.MARKET)
            elif s in new_short:
                orders[s] = Order(side=Side.SELL, quantity=0.0, weight=per_short, order_type=OrderType.MARKET)
            else:
                orders[s] = self._close_order(current)

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
