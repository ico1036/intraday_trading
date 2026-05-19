"""ts_weekend_fakeout — short top weekend-return, long bottom.

Weekly long/short basket triggered on Monday's daily candle (UTC 00:00 =
KST 09:00 — the canonical institutional-return point). Signal is the
weekend cumulative return ``close_{Sun}/close_{Thu} - 1``; ranking is
cross-sectional; the basket holds through the week.

See ``research/notes/ts_weekend_fakeout.md``.
"""
from __future__ import annotations

from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "rolling_rank",
    "horizon": "session",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "weekend_fakeout",
}
SOURCE_NOTES: list[str] = ["research/notes/ts_weekend_fakeout.md"]


class TsWeekendFakeoutStrategy:
    """Weekend pump → Monday mean-reversion.

    Same accumulator pattern as the xs_* alphas: emit only on day flips,
    here additionally conditioned on the *new* day being Monday. The
    weekend return spans the prior 3 daily candles (Fri / Sat / Sun)
    relative to the Thursday close, so we keep a rolling 4-deep close
    history per symbol.
    """

    def __init__(
        self,
        symbols: list[str],
        rebalance_bars: int = 1,
        max_weight: float = 0.05,
        reverse: bool = False,
        concentration_pct: float = 0.5,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self.reverse = bool(reverse)
        # Fraction of the eligible cross-section to take on each leg.
        # 0.5 = old half-basket. 0.1 = top/bottom 10% only.
        self.concentration_pct = max(0.01, min(0.5, float(concentration_pct)))

        # Per-symbol last 4 closes (most-recent last). Need exactly 4 to
        # compute close_{t-1} / close_{t-4} — that's Sun/Thu when ``t`` is
        # Monday's candle.
        self._history: dict[str, list[float]] = {s: [] for s in self.symbols}
        self._today_close: dict[str, float] = {}
        self._current_date = None
        self._monday_bar = 0

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
        for sym, close in self._today_close.items():
            hist = self._history[sym]
            hist.append(close)
            # Keep last 4 closes: Thu / Fri / Sat / Sun when next day is Mon.
            if len(hist) > 4:
                del hist[: len(hist) - 4]
        self._today_close = {}

    def _weekend_returns(self) -> dict[str, float]:
        """Per-symbol close_{t-1} / close_{t-4} - 1.

        Only symbols with a full 4-deep history (i.e. closes for Thu, Fri,
        Sat, Sun) contribute. Anchoring at ``close_{t-4}`` (Thursday) and
        ``close_{t-1}`` (Sunday) gives a 3-day Fri→Sun cumulative return.
        """
        out: dict[str, float] = {}
        for sym in self.symbols:
            hist = self._history[sym]
            if len(hist) < 4:
                continue
            base = hist[-4]
            end = hist[-1]
            if base <= 0:
                continue
            out[sym] = end / base - 1.0
        return out

    def _build_orders(self, state: MarketState, scores: dict[str, float]) -> PortfolioOrder | None:
        if len(scores) < 2:
            return None
        # Descending: top of list = biggest weekend rally (most "pumped").
        ranked = sorted(scores.items(), key=lambda t: t[1], reverse=True)
        # Concentration-aware basket: take the top/bottom ``concentration_pct``
        # of the eligible cross-section instead of full half-baskets. EDA
        # showed Q5-Q1 spread is ~2x stronger than half-basket spread, and
        # fewer legs => less fee drag.
        k = max(1, int(len(ranked) * self.concentration_pct))
        if k == 0:
            return None

        if self.reverse:
            new_long = {s for s, _ in ranked[:k]}
            new_short = {s for s, _ in ranked[-k:]}
        else:
            new_short = {s for s, _ in ranked[:k]}
            new_long = {s for s, _ in ranked[-k:]}

        per_leg = min(self.max_weight, 0.5 / k)

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
            # Monday-only emission. Other day flips still slide the history
            # window forward but don't rank.
            if current_date.weekday() == 0:
                self._monday_bar += 1
                if self._monday_bar % self.rebalance_bars == 0:
                    scores = self._weekend_returns()
                    if len(scores) >= 2:
                        orders = self._build_orders(state, scores)
        self._current_date = current_date

        # Accumulate today's close.
        for sym in self.symbols:
            data = state.panel.get(sym)
            if data is None:
                continue
            sym_ts = data.get("timestamp")
            if sym_ts is None or sym_ts.date() != current_date:
                continue
            close = data.get("close")
            if close is None:
                continue
            try:
                close_f = float(close)
            except (TypeError, ValueError):
                continue
            if close_f <= 0:
                continue
            self._today_close[sym] = close_f

        return orders
