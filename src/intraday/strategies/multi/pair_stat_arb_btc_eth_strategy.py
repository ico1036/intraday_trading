"""is_400_pair_stat_arb_btc_eth — BTC-ETH pair stat-arb, market-neutral.

Trade the log-spread between BTC and ETH. When |z| > entry_z, take the
mean-reverting position: LONG underperformer, SHORT outperformer at equal
notional → dollar-neutral. Exit when |z| < exit_z or time stop.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "z_score",
    "horizon": "intraday",
    "universe": "pair",
    "exit": "neutral_zone",
    "idea_family": "pair_stat_arb_btc_eth",
}
SOURCE_NOTES: list[str] = ["research/notes/pair_stat_arb_btc_eth.md"]


class PairStatArbBtcEthStrategy:
    """BTC-ETH pair mean reversion on log spread."""

    def __init__(
        self,
        symbols: list[str],
        spread_window_bars: int = 1440,
        rebalance_bars: int = 60,
        entry_z: float = 2.0,
        exit_z: float = 0.3,
        hold_bars: int = 4320,
        max_weight: float = 0.30,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.pair = ("BTCUSDT", "ETHUSDT")
        self.window = max(60, int(spread_window_bars))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.entry_z = float(entry_z)
        self.exit_z = float(exit_z)
        self.hold_bars = max(1, int(hold_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        # log close history per pair leg
        self._logs: dict[str, deque[float]] = {
            s: deque(maxlen=self.window) for s in self.pair
        }
        # rolling spread history with online sum/sumsq for O(1) variance
        self._spread_hist: deque[float] = deque(maxlen=self.window)
        self._sum = 0.0
        self._sumsq = 0.0
        self._open_at: int | None = None
        self._open_dir: str | None = None  # "LONG_BTC" or "SHORT_BTC"
        self._bar_count = 0

    def _push_spread(self, s: float) -> None:
        if len(self._spread_hist) == self._spread_hist.maxlen:
            old = self._spread_hist[0]
            self._sum -= old
            self._sumsq -= old * old
        self._spread_hist.append(s)
        self._sum += s
        self._sumsq += s * s

    def _current_z(self) -> float | None:
        b, e = self.pair
        if len(self._logs[b]) < 1 or len(self._logs[e]) < 1:
            return None
        n = len(self._spread_hist)
        if n < self.window:
            return None
        mean = self._sum / n
        var = self._sumsq / n - mean * mean
        if var <= 0 or not math.isfinite(var):
            return None
        sd = math.sqrt(var)
        cur = self._logs[b][-1] - self._logs[e][-1]
        return (cur - mean) / sd

    def _side(self, state: MarketState, s: str) -> str | None:
        if not state.positions:
            return None
        info = state.positions.get(s)
        if not info:
            return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def generate_order(self, state: MarketState) -> PortfolioOrder | None:
        if state.panel is None:
            return None
        b, e = self.pair
        bd = state.panel.get(b)
        ed = state.panel.get(e)
        if not bd or not ed:
            return None
        bp = bd.get("close")
        ep = ed.get("close")
        if bp is None or ep is None or bp <= 0 or ep <= 0:
            return None
        lb = math.log(float(bp))
        le = math.log(float(ep))
        self._logs[b].append(lb)
        self._logs[e].append(le)
        self._push_spread(lb - le)

        self._bar_count += 1

        # Time-stop
        orders: dict[str, Order | None] = {}
        any_change = False
        cur_b_side = self._side(state, b)
        cur_e_side = self._side(state, e)
        if self._open_at is not None and self._bar_count - self._open_at >= self.hold_bars:
            if cur_b_side == "LONG":
                orders[b] = Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
            elif cur_b_side == "SHORT":
                orders[b] = Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
            if cur_e_side == "LONG":
                orders[e] = Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
            elif cur_e_side == "SHORT":
                orders[e] = Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
            if orders:
                any_change = True
                self._open_at = None
                self._open_dir = None

        # Rebalance / new signal
        if self._bar_count % self.rebalance_bars == 0:
            z = self._current_z()
            if z is not None:
                # If holding: check exit (|z| < exit_z)
                if self._open_at is not None and abs(z) < self.exit_z:
                    if cur_b_side == "LONG":
                        orders[b] = Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
                    elif cur_b_side == "SHORT":
                        orders[b] = Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
                    if cur_e_side == "LONG":
                        orders[e] = Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
                    elif cur_e_side == "SHORT":
                        orders[e] = Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
                    if any(v is not None for v in orders.values()):
                        any_change = True
                        self._open_at = None
                        self._open_dir = None
                elif self._open_at is None and abs(z) >= self.entry_z:
                    # Open new pair position
                    w = self.max_weight / 2  # half on each leg → total exposure max_weight
                    if z > 0:
                        # spread high: BTC overpriced → SHORT BTC, LONG ETH
                        orders[b] = Order(side=Side.SELL, quantity=0.0, weight=w, order_type=OrderType.MARKET)
                        orders[e] = Order(side=Side.BUY, quantity=0.0, weight=w, order_type=OrderType.MARKET)
                        self._open_dir = "SHORT_BTC"
                    else:
                        orders[b] = Order(side=Side.BUY, quantity=0.0, weight=w, order_type=OrderType.MARKET)
                        orders[e] = Order(side=Side.SELL, quantity=0.0, weight=w, order_type=OrderType.MARKET)
                        self._open_dir = "LONG_BTC"
                    self._open_at = self._bar_count
                    any_change = True

        # All non-pair symbols stay flat (None)
        for s in self.symbols:
            if s not in orders:
                orders[s] = None
        return PortfolioOrder(orders=orders) if any_change else None
