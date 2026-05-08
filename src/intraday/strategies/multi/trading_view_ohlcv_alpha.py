"""TradingView-inspired OHLCV alpha formulas.

The class is parameterized so one compact strategy surface can generate many
independent alpha ledgers. Ideas are limited to features available from 1m
klines: OHLCV, taker-buy volume, and cross-symbol panels.
"""
from __future__ import annotations

from collections import deque
from statistics import mean, pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


class TradingViewOhlcvAlpha:
    def __init__(
        self,
        symbols: list[str],
        alpha_id: str = "tv_ohlcv_alpha",
        formula: str = "",
        fast: int = 12,
        slow: int = 48,
        lookback: int = 40,
        rsi_window: int = 14,
        bb_window: int = 40,
        bb_k: float = 2.0,
        atr_window: int = 20,
        entry_threshold: float = 0.001,
        exit_threshold: float = 0.0002,
        rebalance_bars: int = 5,
        max_weight: float = 0.25,
        **kwargs: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.alpha_id = alpha_id
        self.formula = formula or str(kwargs.get("family") or "ema_vwap")
        self.fast = max(2, int(fast))
        self.slow = max(self.fast + 1, int(slow))
        self.lookback = max(3, int(lookback))
        self.rsi_window = max(2, int(rsi_window))
        self.bb_window = max(3, int(bb_window))
        self.bb_k = float(bb_k)
        self.atr_window = max(2, int(atr_window))
        self.entry_threshold = float(entry_threshold)
        self.exit_threshold = float(exit_threshold)
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))

        maxlen = max(self.slow, self.lookback, self.bb_window, self.atr_window, self.rsi_window) + 5
        self._hist = {
            symbol: {
                "open": deque(maxlen=maxlen),
                "high": deque(maxlen=maxlen),
                "low": deque(maxlen=maxlen),
                "close": deque(maxlen=maxlen),
                "volume": deque(maxlen=maxlen),
                "vwap": deque(maxlen=maxlen),
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

    def _rsi(self, closes: list[float]) -> float | None:
        if len(closes) < self.rsi_window + 1:
            return None
        gains = []
        losses = []
        for prev, cur in zip(closes[-self.rsi_window - 1:-1], closes[-self.rsi_window:]):
            delta = cur - prev
            gains.append(max(delta, 0.0))
            losses.append(max(-delta, 0.0))
        avg_gain = mean(gains)
        avg_loss = mean(losses)
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - 100.0 / (1.0 + rs)

    def _atr(self, highs: list[float], lows: list[float], closes: list[float]) -> float | None:
        if len(closes) < self.atr_window + 1:
            return None
        ranges = []
        for idx in range(-self.atr_window, 0):
            ranges.append(
                max(
                    highs[idx] - lows[idx],
                    abs(highs[idx] - closes[idx - 1]),
                    abs(lows[idx] - closes[idx - 1]),
                )
            )
        return mean(ranges)

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

    def _score(self, symbol: str) -> float | None:
        h = self._hist[symbol]
        closes = list(h["close"])
        highs = list(h["high"])
        lows = list(h["low"])
        volumes = list(h["volume"])
        vwaps = list(h["vwap"])
        if len(closes) < max(self.fast, self.lookback):
            return None
        close = closes[-1]
        if close <= 0:
            return None

        if self.formula == "ema_vwap":
            fast = self._ema(closes, self.fast)
            slow = self._ema(closes, self.slow)
            if fast is None or slow is None:
                return None
            vwap = vwaps[-1] if vwaps else close
            return (fast - slow) / close + 0.5 * ((close - vwap) / close)

        if self.formula == "donchian_breakout":
            if len(highs) < self.lookback + 1:
                return None
            prev_high = max(highs[-self.lookback - 1:-1])
            prev_low = min(lows[-self.lookback - 1:-1])
            if close > prev_high:
                return (close - prev_high) / close
            if close < prev_low:
                return -(prev_low - close) / close
            return 0.0

        if self.formula == "bb_rsi_reversion":
            if len(closes) < self.bb_window:
                return None
            window = closes[-self.bb_window:]
            mid = mean(window)
            sd = pstdev(window) or 0.0
            rsi = self._rsi(closes)
            if rsi is None or sd == 0:
                return None
            z = (close - mid) / sd
            if z < -self.bb_k and rsi < 35:
                return abs(z) / 10.0
            if z > self.bb_k and rsi > 65:
                return -abs(z) / 10.0
            return 0.0

        if self.formula == "keltner_squeeze":
            if len(closes) < self.bb_window:
                return None
            atr = self._atr(highs, lows, closes)
            if atr is None or atr <= 0:
                return None
            window = closes[-self.bb_window:]
            width = 2.0 * (pstdev(window) or 0.0) / close
            atr_width = atr / close
            ret = (closes[-1] - closes[-self.fast]) / closes[-self.fast]
            return ret if width < atr_width * self.bb_k else 0.0

        if self.formula == "volume_breakout":
            if len(volumes) < self.lookback or closes[-self.lookback] <= 0:
                return None
            vol_base = mean(volumes[-self.lookback:-1]) or 0.0
            vol_ratio = volumes[-1] / vol_base if vol_base > 0 else 0.0
            ret = (closes[-1] - closes[-self.lookback]) / closes[-self.lookback]
            return ret * min(3.0, vol_ratio)

        if self.formula == "macd_rsi":
            fast = self._ema(closes, self.fast)
            slow = self._ema(closes, self.slow)
            rsi = self._rsi(closes)
            if fast is None or slow is None or rsi is None:
                return None
            macd = (fast - slow) / close
            if rsi > 55:
                return macd
            if rsi < 45:
                return -macd
            return 0.0

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

        signals: dict[str, int] = {}
        closes: dict[str, float] = {}
        for symbol in self.symbols:
            score = self._score(symbol)
            close = self._hist[symbol]["close"][-1] if self._hist[symbol]["close"] else 0.0
            closes[symbol] = close
            if score is None:
                continue
            if score > self.entry_threshold:
                signals[symbol] = 1
            elif score < -self.entry_threshold:
                signals[symbol] = -1
            elif abs(score) < self.exit_threshold:
                signals[symbol] = 0

        active_count = sum(1 for value in signals.values() if value)
        weight = min(self.max_weight, 1.0 / active_count) if active_count else 0.0

        orders: dict[str, Order | None] = {}
        for symbol in self.symbols:
            signal = signals.get(symbol)
            current_side = self._position_side(state, symbol)
            if signal == 1:
                orders[symbol] = None if current_side == "LONG" else Order(
                    side=Side.BUY,
                    quantity=0.0,
                    weight=weight,
                    order_type=OrderType.MARKET,
                )
            elif signal == -1:
                orders[symbol] = None if current_side == "SHORT" else Order(
                    side=Side.SELL,
                    quantity=0.0,
                    weight=weight,
                    order_type=OrderType.MARKET,
                )
            elif signal == 0:
                orders[symbol] = self._close_order(current_side)
            else:
                orders[symbol] = None

        return PortfolioOrder(orders=orders) if any(o is not None for o in orders.values()) else None
