"""xs_vrev_conc — xs_volume_rank reverse with quintile concentration.

Same signal as XsVolumeRankStrategy(reverse=True) but only the top
``concentration_pct`` (short) and bottom ``concentration_pct`` (long) of
the cross-section trade. Half-basket diluted the Q5-Q1 spread; this
recovers it. Variance rises because the basket is smaller — pair with
xs_vrev_vol_target for the combined effect.

EDA on IS 2022-2024 (274-coin): cum +67.8%, sharpe 0.96 (high mean,
high variance) vs base 1.20. The cum gain (+76% mean) is the win.

See ``research/notes/xs_vrev_variants.md``.
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
    "idea_family": "xs_vrev_conc",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_vrev_variants.md"]


class XsVolumeRankConcStrategy:
    """Reverse-volume rank, top/bottom ``concentration_pct`` only."""

    def __init__(
        self,
        symbols: list[str],
        rebalance_bars: int = 1,
        max_weight: float = 0.05,
        concentration_pct: float = 0.10,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self.concentration_pct = max(0.01, min(0.5, float(concentration_pct)))

        self._prev_qv: dict[str, float] = {}
        self._today_qv: dict[str, float] = {}
        self._current_date = None
        self._bar = 0

    def _side(self, state: MarketState, sym: str) -> str | None:
        if not state.positions: return None
        info = state.positions.get(sym)
        if not info: return None
        sd = info.get("side")
        return sd if sd in {"LONG", "SHORT"} else None

    def _close_order(self, side: str | None) -> Order | None:
        if side == "LONG":
            return Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
        if side == "SHORT":
            return Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
        return None

    def _commit_yesterday(self) -> None:
        for sym, qv in self._today_qv.items():
            if qv is not None and qv > 0:
                self._prev_qv[sym] = qv
        self._today_qv = {}

    def _build_orders(self, state: MarketState) -> PortfolioOrder | None:
        valid = [(s, q) for s, q in self._prev_qv.items() if q is not None and q > 0]
        if len(valid) < 4:
            return None
        valid.sort(key=lambda t: t[1])
        k = max(1, int(len(valid) * self.concentration_pct))
        if k == 0:
            return None
        longs = {s for s, _ in valid[:k]}
        shorts = {s for s, _ in valid[-k:]}
        per_leg = min(self.max_weight, 0.5 / k)

        orders: dict[str, Order | None] = {}
        for sym in self.symbols:
            current = self._side(state, sym)
            if sym in longs:
                orders[sym] = Order(side=Side.BUY, quantity=0.0,
                                    weight=per_leg, order_type=OrderType.MARKET)
            elif sym in shorts:
                orders[sym] = Order(side=Side.SELL, quantity=0.0,
                                    weight=per_leg, order_type=OrderType.MARKET)
            else:
                orders[sym] = self._close_order(current)

        active = {s: o for s, o in orders.items() if o is not None}
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
                orders = self._build_orders(state)
        self._current_date = current_date

        for sym in self.symbols:
            data = state.panel.get(sym)
            if data is None: continue
            sym_ts = data.get("timestamp")
            if sym_ts is None or sym_ts.date() != current_date: continue
            qv = data.get("quote_volume")
            if qv is None: continue
            try:
                qv_f = float(qv)
            except (TypeError, ValueError):
                continue
            if qv_f <= 0: continue
            self._today_qv[sym] = qv_f

        return orders
