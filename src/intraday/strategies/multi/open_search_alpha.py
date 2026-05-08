"""Open-ended OHLCV search alpha.

This strategy intentionally avoids a fixed idea family enum. The ``idea`` field
is a free-form selector used by a search queue to explore different signal
shapes while keeping one stable strategy contract for the backtester.
"""
from __future__ import annotations

from collections import deque
from statistics import mean, pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


class OpenSearchAlpha:
    def __init__(
        self,
        symbols: list[str],
        alpha_id: str = "open_search_alpha",
        idea: str = "trend_follow",
        lookback: int = 240,
        fast: int = 60,
        slow: int = 720,
        vol_window: int = 240,
        rebalance_bars: int = 60,
        entry_threshold: float = 0.002,
        exit_threshold: float = 0.0005,
        max_weight: float = 0.20,
        top_k: int = 2,
        side_mode: str = "long_short",
        btc_regime_filter: bool = False,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.alpha_id = alpha_id
        self.idea = idea
        self.lookback = max(3, int(lookback))
        self.fast = max(2, int(fast))
        self.slow = max(self.fast + 1, int(slow))
        self.vol_window = max(3, int(vol_window))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.entry_threshold = float(entry_threshold)
        self.exit_threshold = float(exit_threshold)
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self.top_k = max(1, int(top_k))
        self.side_mode = side_mode
        self.btc_regime_filter = bool(btc_regime_filter)

        maxlen = max(self.lookback, self.slow, self.vol_window) + 5
        self._hist = {
            symbol: {
                "close": deque(maxlen=maxlen),
                "high": deque(maxlen=maxlen),
                "low": deque(maxlen=maxlen),
                "volume": deque(maxlen=maxlen),
            }
            for symbol in self.symbols
        }
        self._bar_count = 0

    def _ema(self, values: list[float], window: int) -> float | None:
        if len(values) < window:
            return None
        alpha = 2.0 / (window + 1.0)
        out = values[-window]
        for value in values[-window + 1:]:
            out = alpha * value + (1.0 - alpha) * out
        return out

    def _returns(self, closes: list[float], window: int) -> list[float]:
        if len(closes) < window + 1:
            return []
        out = []
        segment = closes[-window - 1:]
        for prev, cur in zip(segment[:-1], segment[1:]):
            out.append((cur - prev) / prev if prev > 0 else 0.0)
        return out

    def _zscore(self, value: float, sample: list[float]) -> float:
        if len(sample) < 3:
            return 0.0
        sd = pstdev(sample) or 0.0
        return 0.0 if sd == 0 else (value - mean(sample)) / sd

    def _btc_risk_on(self) -> bool:
        symbol = "BTCUSDT" if "BTCUSDT" in self._hist else self.symbols[0]
        closes = list(self._hist[symbol]["close"])
        fast = self._ema(closes, self.fast)
        slow = self._ema(closes, self.slow)
        return bool(fast is not None and slow is not None and fast >= slow)

    def _score_symbol(self, symbol: str) -> float | None:
        h = self._hist[symbol]
        closes = list(h["close"])
        highs = list(h["high"])
        lows = list(h["low"])
        volumes = list(h["volume"])
        if len(closes) < max(self.lookback, self.fast) + 1:
            if self.idea == "constant_short":
                return -1.0
            if self.idea == "constant_long":
                return 1.0
            return None
        close = closes[-1]
        if close <= 0:
            return None

        lookback_price = closes[-self.lookback]
        trend_ret = (close - lookback_price) / lookback_price if lookback_price > 0 else 0.0

        if self.idea == "constant_short":
            return -1.0

        if self.idea == "constant_long":
            return 1.0

        if self.idea == "btc_regime_short":
            return -1.0 if not self._btc_risk_on() else 0.0

        if self.idea == "btc_regime_long":
            return 1.0 if self._btc_risk_on() else 0.0

        if self.idea == "trend_follow":
            fast = self._ema(closes, self.fast)
            slow = self._ema(closes, self.slow)
            if fast is None or slow is None:
                return None
            return (fast - slow) / close + trend_ret

        if self.idea == "trend_reversal":
            rets = self._returns(closes, self.vol_window)
            return -self._zscore(trend_ret, rets)

        if self.idea == "breakout_hold":
            if len(highs) < self.lookback + 1:
                return None
            prev_high = max(highs[-self.lookback - 1:-1])
            prev_low = min(lows[-self.lookback - 1:-1])
            if close > prev_high:
                return (close - prev_high) / close
            if close < prev_low:
                return -(prev_low - close) / close
            return 0.0

        if self.idea == "volume_exhaustion":
            if len(volumes) < self.vol_window + 1:
                return None
            vol_base = mean(volumes[-self.vol_window - 1:-1]) or 0.0
            vol_z = self._zscore(volumes[-1], list(volumes[-self.vol_window - 1:-1]))
            return -trend_ret * max(0.0, vol_z) if vol_base > 0 else 0.0

        if self.idea == "low_vol_trend":
            rets = self._returns(closes, self.vol_window)
            vol = pstdev(rets) if len(rets) > 2 else 0.0
            return trend_ret / vol if vol > 0 else 0.0

        return trend_ret

    def _position_side(self, state: MarketState, symbol: str) -> str | None:
        if not state.positions:
            return None
        info = state.positions.get(symbol)
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

    def generate_order(self, state: MarketState) -> PortfolioOrder | None:
        if state.panel is None:
            return None

        for symbol in self.symbols:
            data = state.panel.get(symbol)
            if not data:
                continue
            h = self._hist[symbol]
            for key in h:
                value = data.get(key)
                if value is not None:
                    h[key].append(float(value))

        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0:
            return None

        raw_scores = {
            symbol: score
            for symbol in self.symbols
            if (score := self._score_symbol(symbol)) is not None
        }
        if not raw_scores:
            return None

        risk_on = self._btc_risk_on()
        longs = sorted(
            ((s, v) for s, v in raw_scores.items() if v > self.entry_threshold),
            key=lambda item: item[1],
            reverse=True,
        )[: self.top_k]
        shorts = sorted(
            ((s, v) for s, v in raw_scores.items() if v < -self.entry_threshold),
            key=lambda item: item[1],
        )[: self.top_k]

        if self.btc_regime_filter:
            if risk_on:
                shorts = []
            else:
                longs = []
        if self.side_mode == "long_only":
            shorts = []
        elif self.side_mode == "short_only":
            longs = []

        targets = {symbol: 0 for symbol in self.symbols}
        for symbol, _ in longs:
            targets[symbol] = 1
        for symbol, _ in shorts:
            targets[symbol] = -1

        active_count = sum(1 for target in targets.values() if target)
        weight = min(self.max_weight, 1.0 / active_count) if active_count else 0.0

        orders: dict[str, Order | None] = {}
        for symbol, target in targets.items():
            score = raw_scores.get(symbol, 0.0)
            current_side = self._position_side(state, symbol)
            if target == 1:
                orders[symbol] = None if current_side == "LONG" else Order(
                    side=Side.BUY,
                    quantity=0.0,
                    weight=weight,
                    order_type=OrderType.MARKET,
                )
            elif target == -1:
                orders[symbol] = None if current_side == "SHORT" else Order(
                    side=Side.SELL,
                    quantity=0.0,
                    weight=weight,
                    order_type=OrderType.MARKET,
                )
            elif abs(score) < self.exit_threshold:
                orders[symbol] = self._close_order(current_side)
            else:
                orders[symbol] = None

        return PortfolioOrder(orders=orders) if any(order is not None for order in orders.values()) else None
