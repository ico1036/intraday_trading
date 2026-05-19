"""xs_max_lottery — short top-MAX, long bottom-MAX cross-section.

Hypothesis: lottery-ticket anomaly (Bali, Cakici & Whitelaw 2011) ported
to crypto daily bars. The single-highest daily return over the past
``lookback`` days is a clean skew proxy; retail overpays for positive-
skew names, so the top of that distribution carries a forward-return
discount. We short the top half and long the bottom half, daily rebalance.

See ``research/notes/xs_max_lottery.md`` for the mechanism and the
search-space cell justification.
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
    "idea_family": "lottery_max",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_max_lottery.md"]


class XsMaxLotteryStrategy:
    """Cross-sectional lottery-ticket reversal on daily bars.

    Mirrors ``XsVolumeRankStrategy`` accumulator pattern (decide once
    per day on COMPLETE prior-day data), but the ranking key is
    ``max(daily_return) over lookback days`` rather than quote_volume.

    The framework calls ``generate_order`` once per (symbol, bar) event.
    Across the multi-symbol panel each daily close fires N callbacks at
    the same timestamp. We:

    1. Accumulate today's close into ``_close_today`` on every call,
       discarding entries whose timestamp doesn't match ``current_date``.
    2. On the FIRST call of a new date, today is yesterday — we move
       ``_close_today`` into the per-symbol ``_history`` deques, compute
       MAX(daily_return) over the trailing ``lookback`` days, and rank.
    3. All later same-day calls return ``None`` until the next day flip.
    """

    def __init__(
        self,
        symbols: list[str],
        lookback: int = 14,
        rebalance_bars: int = 1,
        max_weight: float = 0.05,
        reverse: bool = False,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        # Need ``lookback + 1`` daily closes to compute ``lookback`` returns.
        self.lookback = max(2, int(lookback))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self.reverse = bool(reverse)

        # Per-symbol rolling close window. Kept as plain list trimmed to
        # ``lookback + 1`` to keep MAX computation a single pass.
        self._history: dict[str, list[float]] = {s: [] for s in self.symbols}
        # Today's accumulator — closes seen for the *current* date only.
        self._close_today: dict[str, float] = {}
        self._current_date = None
        self._bar = 0

    # ----- helpers ---------------------------------------------------
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
        """Move yesterday's closes from ``_close_today`` into the rolling
        history deques. Called exactly once on every day transition."""
        for sym, close in self._close_today.items():
            hist = self._history[sym]
            hist.append(close)
            if len(hist) > self.lookback + 1:
                # +1 because N returns need N+1 closes.
                del hist[: len(hist) - (self.lookback + 1)]
        self._close_today = {}

    def _max_returns(self) -> dict[str, float]:
        """Per-symbol MAX(daily return) over the rolling window. Symbols
        without enough history are excluded — ranking only runs on the
        eligible subset."""
        out: dict[str, float] = {}
        for sym in self.symbols:
            hist = self._history[sym]
            if len(hist) < self.lookback + 1:
                continue
            rets = []
            for i in range(1, len(hist)):
                prev = hist[i - 1]
                if prev <= 0:
                    continue
                rets.append(hist[i] / prev - 1.0)
            if not rets:
                continue
            out[sym] = max(rets)
        return out

    def _build_orders(self, state: MarketState, scores: dict[str, float]) -> PortfolioOrder | None:
        if len(scores) < 2:
            return None
        # Descending: top of list = highest MAX (lottery-like).
        ranked = sorted(scores.items(), key=lambda t: t[1], reverse=True)
        half = len(ranked) // 2
        if half == 0:
            return None

        # Lottery anomaly direction: short the top, long the bottom.
        # ``reverse=True`` flips for symmetry runs.
        if self.reverse:
            new_long = {s for s, _ in ranked[:half]}
            new_short = {s for s, _ in ranked[-half:]}
        else:
            new_short = {s for s, _ in ranked[:half]}
            new_long = {s for s, _ in ranked[-half:]}

        # Variable per_leg keeps gross ~= 1.0 as the eligible basket
        # changes (e.g. a coin missing one day's close).
        per_leg = min(self.max_weight, 0.5 / half)

        orders: dict[str, Order | None] = {}
        for sym in self.symbols:
            current = self._side(state, sym)
            if sym in new_long:
                orders[sym] = Order(
                    side=Side.BUY,
                    quantity=0.0,
                    weight=per_leg,
                    order_type=OrderType.MARKET,
                )
            elif sym in new_short:
                orders[sym] = Order(
                    side=Side.SELL,
                    quantity=0.0,
                    weight=per_leg,
                    order_type=OrderType.MARKET,
                )
            else:
                orders[sym] = self._close_order(current)

        active = {sym: o for sym, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None

    # ----- main contract ---------------------------------------------
    def generate_order(self, state: MarketState) -> PortfolioOrder | None:
        if state.panel is None or state.timestamp is None:
            return None

        current_date = state.timestamp.date()

        # Day flip: yesterday's _close_today is now complete. Commit to
        # history, then rank on the rolling window. Emit at most once
        # per day; further calls before the next date roll return None.
        orders = None
        if self._current_date is not None and current_date != self._current_date:
            self._commit_yesterday()
            self._bar += 1
            if self._bar % self.rebalance_bars == 0:
                scores = self._max_returns()
                if len(scores) >= 2:
                    orders = self._build_orders(state, scores)
        self._current_date = current_date

        # Accumulate today's closes. Multiple symbols share the same
        # bar timestamp, so we overwrite — last value for current_date
        # wins, which is fine because daily close is point-in-time.
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
                close = float(close)
            except (TypeError, ValueError):
                continue
            if close <= 0:
                continue
            self._close_today[sym] = close

        return orders
