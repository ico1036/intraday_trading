"""xs_amihud_illiq — Amihud illiquidity rank, short top, long bottom.

For each symbol on the prior day:
    illiq = |daily_return| / quote_volume

High illiq = thin-book pump that flipped on small flow → short.
Low illiq  = deep-book absorption (real money, no price impact) → long.

See ``research/notes/xs_amihud_illiq.md``.
"""
from __future__ import annotations

from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "rolling_rank",
    "horizon": "multi_day",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "amihud_illiq",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_amihud_illiq.md"]


class XsAmihudIlliqStrategy:
    """Cross-sectional Amihud-illiq daily long/short.

    Same accumulator pattern as XsVolumeRank / XsMaxLottery: decide once
    per day on prior-day complete data. Each call:

    1. Stash today's close + quote_volume per symbol in ``_today``.
    2. On the first call of a new date, the prior day's ``_today`` is
       complete — compute return vs the day-before-that close and divide
       by prior quote_volume to get ILLIQ. Rank, emit basket.

    Needs two prior closes (for ``ret_{t-1}``) plus prior quote_volume
    to score a symbol. Symbols missing either are excluded from ranking.
    """

    def __init__(
        self,
        symbols: list[str],
        rebalance_bars: int = 1,
        max_weight: float = 0.05,
        reverse: bool = False,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self.reverse = bool(reverse)

        # Most-recent two closes per symbol so we can compute one daily
        # return on every day-flip.
        self._prev_close: dict[str, float | None] = {s: None for s in self.symbols}
        self._prev_prev_close: dict[str, float | None] = {s: None for s in self.symbols}
        self._prev_qv: dict[str, float | None] = {s: None for s in self.symbols}
        # Today's accumulator (close + quote_volume only).
        self._today_close: dict[str, float] = {}
        self._today_qv: dict[str, float] = {}
        self._current_date = None
        self._bar = 0

    def _side(self, state: MarketState, sym: str) -> str | None:
        if not state.positions:
            return None
        info = state.positions.get(sym)
        if not info:
            return None
        sd = info.get("side")
        return sd if sd in {"LONG", "SHORT"} else None

    def _close_order(self, side: str | None) -> Order | None:
        if side == "LONG":
            return Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
        if side == "SHORT":
            return Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
        return None

    def _commit_yesterday(self) -> None:
        """Slide ``_today_*`` (yesterday at this point in time) into the
        ``_prev_*`` slots and the older prev into ``_prev_prev_close``."""
        for sym in self.symbols:
            close = self._today_close.get(sym)
            qv = self._today_qv.get(sym)
            if close is None:
                continue
            self._prev_prev_close[sym] = self._prev_close[sym]
            self._prev_close[sym] = close
            self._prev_qv[sym] = qv
        self._today_close = {}
        self._today_qv = {}

    def _scores(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for sym in self.symbols:
            c1 = self._prev_close[sym]
            c0 = self._prev_prev_close[sym]
            qv = self._prev_qv[sym]
            if c0 is None or c1 is None or qv is None:
                continue
            if c0 <= 0 or qv <= 0:
                continue
            ret = c1 / c0 - 1.0
            illiq = abs(ret) / qv
            out[sym] = illiq
        return out

    def _build_orders(self, state: MarketState, scores: dict[str, float]) -> PortfolioOrder | None:
        if len(scores) < 2:
            return None
        # Descending: top = highest ILLIQ (thinnest book / pump).
        ranked = sorted(scores.items(), key=lambda t: t[1], reverse=True)
        half = len(ranked) // 2
        if half == 0:
            return None

        if self.reverse:
            new_long = {s for s, _ in ranked[:half]}
            new_short = {s for s, _ in ranked[-half:]}
        else:
            new_short = {s for s, _ in ranked[:half]}
            new_long = {s for s, _ in ranked[-half:]}

        per_leg = min(self.max_weight, 0.5 / half)

        orders: dict[str, Order | None] = {}
        for sym in self.symbols:
            current = self._side(state, sym)
            if sym in new_long:
                orders[sym] = Order(side=Side.BUY, quantity=0.0,
                                    weight=per_leg, order_type=OrderType.MARKET)
            elif sym in new_short:
                orders[sym] = Order(side=Side.SELL, quantity=0.0,
                                    weight=per_leg, order_type=OrderType.MARKET)
            else:
                orders[sym] = self._close_order(current)

        active = {sym: o for sym, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None

    def generate_order(self, state: MarketState) -> PortfolioOrder | None:
        if state.panel is None or state.timestamp is None:
            return None

        current_date = state.timestamp.date()

        orders = None
        if self._current_date is not None and current_date != self._current_date:
            self._commit_yesterday()
            self._bar += 1
            if self._bar % self.rebalance_bars == 0:
                scores = self._scores()
                if len(scores) >= 2:
                    orders = self._build_orders(state, scores)
        self._current_date = current_date

        # Accumulate today's close + quote_volume.
        for sym in self.symbols:
            data = state.panel.get(sym)
            if data is None:
                continue
            sym_ts = data.get("timestamp")
            if sym_ts is None or sym_ts.date() != current_date:
                continue
            close = data.get("close")
            qv = data.get("quote_volume")
            if close is None or qv is None:
                continue
            try:
                close_f = float(close)
                qv_f = float(qv)
            except (TypeError, ValueError):
                continue
            if close_f <= 0 or qv_f <= 0:
                continue
            self._today_close[sym] = close_f
            self._today_qv[sym] = qv_f

        return orders
