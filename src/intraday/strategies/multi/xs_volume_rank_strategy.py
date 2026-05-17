"""xs_volume_rank — cross-section daily: long top-50% by prev-day quote_volume, short bottom-50%.

Hypothesis: high quote-volume days are followed by mean-reverting flow into
the lower-attention names — or, alternatively, continued momentum in the
high-flow names. We trade the directional version (long high, short low),
equal-weight basket, daily rebalance. Treat the result as a breadth test on
the existing pipeline using a 500-coin universe at daily frequency.
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
    "idea_family": "xs_volume_rank",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_volume_rank.md"]


class XsVolumeRankStrategy:
    """Daily long-top / short-bottom basket by quote_volume rank.

    The framework calls ``generate_order`` once per (symbol, bar) event.
    Multiple symbols share the same daily timestamp, so the strategy is
    called many times per day, but with an incrementally-built panel
    (each call adds one more symbol's current-day data). To decide once
    per day on COMPLETE prior-day data, this strategy:

    1. Accumulates ``quote_volume`` into ``_qv_today`` on every call,
       discarding entries whose panel timestamp does not match the
       current bar's date.
    2. On the FIRST call of a new date, the accumulator holds yesterday's
       complete data — at that moment, build the basket: long top-half
       by yesterday's quote_volume, short bottom-half. ``per_leg =
       min(max_weight, 0.5 / half)`` keeps gross ≈ 1.0.
    3. All other calls return ``None`` (no emission).
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
        self._qv_today: dict[str, float] = {}
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

        # Variable per_leg keeps gross ~= 1.0 as basket size changes.
        # Daily drift causes micro-rebalance for stable basket members —
        # this is intentional: it's how dollar-neutral exposure stays
        # constant when the universe size shifts day to day.
        per_leg = min(self.max_weight, 0.5 / half)

        orders: dict[str, Order | None] = {}
        for s in self.symbols:
            current = self._side(state, s)
            if s in new_long:
                orders[s] = Order(
                    side=Side.BUY,
                    quantity=0.0,
                    weight=per_leg,
                    order_type=OrderType.MARKET,
                )
            elif s in new_short:
                orders[s] = Order(
                    side=Side.SELL,
                    quantity=0.0,
                    weight=per_leg,
                    order_type=OrderType.MARKET,
                )
            else:
                orders[s] = self._close_order(current)

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None

    def generate_order(self, state: MarketState) -> PortfolioOrder | None:
        if state.panel is None or state.timestamp is None:
            return None

        current_date = state.timestamp.date()

        # On day transition: the just-completed _qv_today holds yesterday's
        # FULL accumulator. Emit orders based on it (decision once per day).
        # Then reset and start accumulating today's qv.
        #
        # Emitting only on day transitions is critical: emitting on every
        # intra-day call would overwrite the correct full-day pending with
        # partial-accumulator rankings before they fire.
        orders = None
        if self._current_date is not None and current_date != self._current_date:
            self._bar += 1
            if self._bar % self.rebalance_bars == 0 and len(self._qv_today) >= 2:
                orders = self._build_orders(state, dict(self._qv_today))
            self._qv_today = {}
        self._current_date = current_date

        # Accumulate current call's fresh entries into today's qv.
        for s in self.symbols:
            d = state.panel.get(s)
            if d is None:
                continue
            sym_ts = d.get("timestamp")
            if sym_ts is None or sym_ts.date() != current_date:
                continue
            quote_vol = d.get("quote_volume")
            if quote_vol is None:
                continue
            q = float(quote_vol)
            if q <= 0:
                continue
            self._qv_today[s] = q

        return orders
