"""xs_volume_spike_fade_v2 — fade suspicious crypto volume spikes.

This is a filtered version of the live reverse volume-rank idea. It shorts
liquid symbols whose prior-day quote volume spikes versus their own recent
baseline, but avoids shorting names with strong positive price confirmation.
The long book is built from liquid, positively trending names with non-extreme
volume so the portfolio stays dollar neutral.
"""
from __future__ import annotations

from collections import deque
from statistics import median
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "rolling_rank",
    "horizon": "multi_day",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "xs_volume_spike_fade_v2",
}
SOURCE_NOTES: list[str] = ["research/notes/xs_volume_spike_fade_v2.md"]


class XsVolumeSpikeFadeV2Strategy:
    """Daily volume-spike fade with liquidity and health filters."""

    def __init__(
        self,
        symbols: list[str],
        rebalance_bars: int = 1,
        max_weight: float = 0.05,
        volume_lookback: int = 20,
        health_lookback: int = 5,
        min_median_quote_volume: float = 250_000.0,
        min_quote_volume: float = 100_000.0,
        min_spike_ratio: float = 3.0,
        healthy_return_threshold: float = 0.08,
        min_long_return: float = 0.0,
        max_long_volume_ratio: float = 2.0,
        short_pct: float = 0.10,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self.volume_lookback = max(2, int(volume_lookback))
        self.health_lookback = max(1, int(health_lookback))
        self.min_median_quote_volume = max(0.0, float(min_median_quote_volume))
        self.min_quote_volume = max(0.0, float(min_quote_volume))
        self.min_spike_ratio = max(1.0, float(min_spike_ratio))
        self.healthy_return_threshold = float(healthy_return_threshold)
        self.min_long_return = float(min_long_return)
        self.max_long_volume_ratio = max(1.0, float(max_long_volume_ratio))
        self.short_pct = max(0.01, min(0.5, float(short_pct)))

        qv_len = self.volume_lookback + 1
        close_len = self.health_lookback + 1
        self._qv_hist: dict[str, deque[float]] = {
            s: deque(maxlen=qv_len) for s in self.symbols
        }
        self._close_hist: dict[str, deque[float]] = {
            s: deque(maxlen=close_len) for s in self.symbols
        }
        self._today_qv: dict[str, float] = {}
        self._today_close: dict[str, float] = {}
        self._current_date = None
        self._bar = 0

    def _side(self, state: MarketState, sym: str) -> str | None:
        if not state.positions:
            return None
        info = state.positions.get(sym)
        if not info:
            return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def _close_order(self, side: str | None) -> Order | None:
        if side == "LONG":
            return Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
        if side == "SHORT":
            return Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
        return None

    def _commit_yesterday(self) -> None:
        for sym in self.symbols:
            qv = self._today_qv.get(sym)
            close = self._today_close.get(sym)
            if qv is not None and qv > 0:
                self._qv_hist[sym].append(qv)
            if close is not None and close > 0:
                self._close_hist[sym].append(close)
        self._today_qv = {}
        self._today_close = {}

    def _stats(self, sym: str) -> dict[str, float] | None:
        qv_hist = list(self._qv_hist[sym])
        close_hist = list(self._close_hist[sym])
        if len(qv_hist) < self.volume_lookback + 1:
            return None
        if len(close_hist) < self.health_lookback + 1:
            return None

        latest_qv = qv_hist[-1]
        base_qv = median(qv_hist[:-1])
        if base_qv <= 0 or latest_qv <= 0:
            return None
        if base_qv < self.min_median_quote_volume:
            return None
        if latest_qv < self.min_quote_volume:
            return None

        start_close = close_hist[-(self.health_lookback + 1)]
        latest_close = close_hist[-1]
        if start_close <= 0 or latest_close <= 0:
            return None

        return {
            "latest_qv": latest_qv,
            "base_qv": base_qv,
            "volume_ratio": latest_qv / base_qv,
            "momentum": latest_close / start_close - 1.0,
        }

    def _build_orders(self, state: MarketState) -> PortfolioOrder | None:
        rows: list[tuple[str, dict[str, float]]] = []
        for sym in self.symbols:
            stats = self._stats(sym)
            if stats is not None:
                rows.append((sym, stats))
        if len(rows) < 2:
            return None

        short_candidates = [
            (sym, st)
            for sym, st in rows
            if st["volume_ratio"] >= self.min_spike_ratio
            and st["momentum"] < self.healthy_return_threshold
        ]
        if not short_candidates:
            return None
        short_candidates.sort(
            key=lambda item: (item[1]["volume_ratio"], -item[1]["momentum"]),
            reverse=True,
        )
        target_k = max(1, int(len(rows) * self.short_pct))
        shorts = [sym for sym, _ in short_candidates[:target_k]]
        short_set = set(shorts)

        long_candidates = [
            (sym, st)
            for sym, st in rows
            if sym not in short_set
            and st["momentum"] >= self.min_long_return
            and st["volume_ratio"] <= self.max_long_volume_ratio
        ]
        long_candidates.sort(
            key=lambda item: (item[1]["momentum"], item[1]["base_qv"]),
            reverse=True,
        )
        k = min(len(shorts), len(long_candidates))
        if k <= 0:
            return None
        shorts = shorts[:k]
        longs = [sym for sym, _ in long_candidates[:k]]
        short_set = set(shorts)
        long_set = set(longs)
        per_leg = min(self.max_weight, 0.5 / k)

        orders: dict[str, Order | None] = {}
        for sym in self.symbols:
            current = self._side(state, sym)
            if sym in long_set:
                orders[sym] = Order(
                    side=Side.BUY,
                    quantity=0.0,
                    weight=per_leg,
                    order_type=OrderType.MARKET,
                )
            elif sym in short_set:
                orders[sym] = Order(
                    side=Side.SELL,
                    quantity=0.0,
                    weight=per_leg,
                    order_type=OrderType.MARKET,
                )
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
            qv = data.get("quote_volume")
            close = data.get("close")
            if qv is None or close is None:
                continue
            try:
                qv_f = float(qv)
                close_f = float(close)
            except (TypeError, ValueError):
                continue
            if qv_f <= 0 or close_f <= 0:
                continue
            self._today_qv[sym] = qv_f
            self._today_close[sym] = close_f

        return orders

