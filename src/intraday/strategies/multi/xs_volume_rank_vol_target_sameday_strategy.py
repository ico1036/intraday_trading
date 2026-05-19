"""xs_vrev_vol_target_sameday — vol-target half-basket, same-day universe.

Identical signal + weighting to XsVolumeRankVolTargetStrategy. The only
fix is the universe: ``_commit_yesterday`` now *replaces* ``_prev_qv``
with the symbols that reported a fresh quote_volume today, instead of
unioning. The legacy variant carried over stale symbols and roughly
doubled the eligible universe size, halving the per-leg weight and the
realised gross exposure.

See ``research/notes/xs_vrev_variants.md`` and
``research/notes/xs_vrev_sameday_fix.md``.
"""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "rolling_rank",
    "horizon": "multi_day",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "xs_vrev_vol_target_sameday",
}
SOURCE_NOTES: list[str] = [
    "research/notes/xs_vrev_variants.md",
    "research/notes/xs_vrev_sameday_fix.md",
]


class XsVolumeRankVolTargetSamedayStrategy:
    """Half-basket reverse-volume, inverse-vol leg weights, same-day universe."""

    def __init__(
        self,
        symbols: list[str],
        rebalance_bars: int = 1,
        max_weight: float = 0.20,
        vol_lookback: int = 20,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self.vol_lookback = max(2, int(vol_lookback))

        self._closes: dict[str, deque[float]] = {
            s: deque(maxlen=self.vol_lookback + 1) for s in self.symbols
        }
        self._today_close: dict[str, float] = {}
        self._today_qv: dict[str, float] = {}
        self._prev_qv: dict[str, float] = {}
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
        # closes are a rolling history — keep growing.
        for sym in self.symbols:
            close = self._today_close.get(sym)
            if close is not None:
                self._closes[sym].append(close)
        # qv is a point-in-time signal — replace, do not union. Symbols
        # missing today's bar drop out of the next ranking.
        self._prev_qv = {s: q for s, q in self._today_qv.items()
                         if q is not None and q > 0}
        self._today_close = {}
        self._today_qv = {}

    def _rolling_vol(self, sym: str) -> float | None:
        closes = list(self._closes[sym])
        if len(closes) < self.vol_lookback + 1:
            return None
        rets = []
        for i in range(1, len(closes)):
            if closes[i - 1] <= 0:
                continue
            rets.append(closes[i] / closes[i - 1] - 1.0)
        if len(rets) < 2:
            return None
        m = sum(rets) / len(rets)
        var = sum((r - m) ** 2 for r in rets) / (len(rets) - 1)
        return var ** 0.5 if var > 0 else None

    def _build_orders(self, state: MarketState) -> PortfolioOrder | None:
        ranked = []
        vols = {}
        for sym, qv in self._prev_qv.items():
            if qv is None or qv <= 0:
                continue
            sigma = self._rolling_vol(sym)
            if sigma is None or sigma <= 0:
                continue
            ranked.append((sym, qv))
            vols[sym] = sigma
        if len(ranked) < 4:
            return None
        ranked.sort(key=lambda t: t[1])
        half = len(ranked) // 2
        if half == 0:
            return None
        longs = [s for s, _ in ranked[:half]]
        shorts = [s for s, _ in ranked[-half:]]

        weights: dict[str, float] = {}
        for leg, sign in [(longs, +1.0), (shorts, -1.0)]:
            inv = {s: 1.0 / vols[s] for s in leg}
            total = sum(inv.values())
            if total <= 0:
                continue
            for s, v in inv.items():
                weights[s] = sign * 0.5 * (v / total)

        orders: dict[str, Order | None] = {}
        for sym in self.symbols:
            current = self._side(state, sym)
            w = weights.get(sym)
            if w is None:
                orders[sym] = self._close_order(current)
                continue
            mag = min(self.max_weight, abs(w))
            if w > 0:
                orders[sym] = Order(side=Side.BUY, quantity=0.0,
                                    weight=mag, order_type=OrderType.MARKET)
            elif w < 0:
                orders[sym] = Order(side=Side.SELL, quantity=0.0,
                                    weight=mag, order_type=OrderType.MARKET)
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
