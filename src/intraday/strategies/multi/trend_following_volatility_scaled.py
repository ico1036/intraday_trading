"""
Trend Following Volatility Scaled Strategy (TFVS)

A symmetric trend-following strategy that:
1. Detects market regime using BTC as the leader (UPTREND/DOWNTREND/NEUTRAL)
2. Selects the best symbol based on momentum (strongest for longs, weakest for shorts)
3. Applies volatility-scaled position sizing using the 2% risk rule
4. Uses wide ATR-based stops to avoid whipsaws

Key Features:
- Symmetric: Longs in uptrends, shorts in downtrends
- Single position: Avoids correlation trap by concentrating on best candidate
- Wide stops: 3x ATR to reduce whipsaw damage
- Trailing stop: Activates after 1R profit (3x ATR)
- Time exit: Max 12 hours to limit funding rate exposure
"""

from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


class TrendFollowingVolatilityScaledStrategy:
    """Trend-following strategy with volatility-scaled position sizing."""

    def __init__(
        self,
        symbols: list[str],
        sma_fast: int = 20,
        sma_slow: int = 50,
        atr_window: int = 14,
        momentum_short: int = 20,
        momentum_long: int = 50,
        min_momentum_pct: float = 0.5,
        entry_momentum_pct: float = 1.0,
        stop_atr_mult: float = 3.0,
        take_profit_atr_mult: float = 6.0,
        trail_activation_mult: float = 3.0,
        trail_distance_mult: float = 2.0,
        max_atr_ratio: float = 2.0,
        rsi_window: int = 14,
        rsi_overbought: int = 70,
        rsi_oversold: int = 30,
        volume_confirm_mult: float = 0.8,
        max_hold_minutes: int = 720,
        cooldown_bars: int = 6,
        history_max_len: int = 2000,
    ):
        if len(symbols) < 1:
            raise ValueError("symbols must contain at least one symbol")

        self.symbols = symbols
        self.sma_fast = max(1, int(sma_fast))
        self.sma_slow = max(1, int(sma_slow))
        self.atr_window = max(1, int(atr_window))
        self.momentum_short = max(1, int(momentum_short))
        self.momentum_long = max(1, int(momentum_long))
        self.min_momentum_pct = float(min_momentum_pct)
        self.entry_momentum_pct = float(entry_momentum_pct)
        self.stop_atr_mult = float(stop_atr_mult)
        self.take_profit_atr_mult = float(take_profit_atr_mult)
        self.trail_activation_mult = float(trail_activation_mult)
        self.trail_distance_mult = float(trail_distance_mult)
        self.max_atr_ratio = float(max_atr_ratio)
        self.rsi_window = max(1, int(rsi_window))
        self.rsi_overbought = int(rsi_overbought)
        self.rsi_oversold = int(rsi_oversold)
        self.volume_confirm_mult = float(volume_confirm_mult)
        self.max_hold_minutes = int(max_hold_minutes)
        self.cooldown_bars = max(0, int(cooldown_bars))
        self.history_max_len = max(10, int(history_max_len))

        # symbol -> candle history (close/high/low/volume)
        self._bars: dict[str, pd.DataFrame] = {
            sym: pd.DataFrame(columns=["close", "high", "low", "volume"])
            for sym in self.symbols
        }

        # Position tracking (single position)
        self._position_symbol: Optional[str] = None
        self._position_side: Optional[str] = None  # "LONG" or "SHORT"
        self._entry_price: float = 0.0
        self._entry_time: Optional[datetime] = None
        self._entry_atr: float = 0.0  # ATR at entry for stop/target calculation
        self._position_high: float = 0.0  # Highest price since entry (for trailing stop long)
        self._position_low: float = float("inf")  # Lowest price since entry (for trailing stop short)
        self._trailing_active: bool = False  # Whether trailing stop is activated

        # Regime tracking
        self._current_regime: str = "NEUTRAL"

        # Trade cooldown
        self._last_trade_bar: int = -999

        # Current bar counter
        self._bar_count: int = 0

        # Diagnostics
        self.last_regime: str = "NEUTRAL"
        self.last_reason: str = "init"

    # ---------------------------- State Management ----------------------------
    def _append_bar(self, symbol: str, ts: datetime, bar: dict) -> None:
        df = self._bars.setdefault(
            symbol, pd.DataFrame(columns=["close", "high", "low", "volume"])
        )
        row = pd.DataFrame(
            {
                "close": [float(bar["close"])],
                "high": [float(bar["high"])],
                "low": [float(bar["low"])],
                "volume": [float(bar.get("volume", 0.0))],
            },
            index=[ts],
        )
        if df.empty:
            df = row
        else:
            df = pd.concat([df, row]).sort_index().tail(self.history_max_len)
        df = df[~df.index.duplicated(keep="last")]
        self._bars[symbol] = df

    def _update_panel(self, state: MarketState) -> bool:
        panel = state.panel
        if panel is None:
            return False

        ts = state.timestamp
        updated = False

        for sym, bar in panel.items():
            if sym not in self._bars:
                continue
            if not bar:
                continue
            close = bar.get("close")
            high = bar.get("high")
            low = bar.get("low")
            if close is None or high is None or low is None:
                continue
            close = float(close)
            if close <= 0:
                continue

            self._append_bar(
                sym,
                ts,
                {
                    "close": close,
                    "high": float(high),
                    "low": float(low),
                    "volume": float(bar.get("volume", 0.0)),
                },
            )
            updated = True

        if updated:
            self._bar_count += 1

        return updated

    def _get_df(self, symbol: str) -> pd.DataFrame:
        return self._bars.setdefault(
            symbol, pd.DataFrame(columns=["close", "high", "low", "volume"])
        )

    def _has_warmup(self) -> bool:
        """Check if we have enough data for all indicators."""
        required_bars = max(
            self.sma_slow + 2,
            self.atr_window + 2,
            self.momentum_long + 2,
            self.rsi_window + 2,
        )
        for sym in self.symbols:
            df = self._get_df(sym)
            if len(df) < required_bars:
                self.last_reason = f"warmup:{sym}:{len(df)}/{required_bars}"
                return False
        return True

    # ---------------------------- Indicators ----------------------------
    def _atr(self, symbol: str, window: Optional[int] = None) -> Optional[float]:
        """Calculate ATR for a symbol."""
        if window is None:
            window = self.atr_window
        df = self._get_df(symbol)
        if len(df) < window + 1:
            return None
        d = df.tail(window + 1).copy()
        prev_close = d["close"].shift(1)
        tr = pd.concat(
            [
                (d["high"] - d["low"]).abs(),
                (d["high"] - prev_close).abs(),
                (d["low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        tr = tr.iloc[1:]
        if tr.empty:
            return None
        return float(tr.mean())

    def _sma(self, symbol: str, window: int, field: str = "close") -> Optional[float]:
        """Calculate SMA of specified field."""
        df = self._get_df(symbol)
        if len(df) < window:
            return None
        return float(df[field].tail(window).mean())

    def _rsi(self, symbol: str) -> Optional[float]:
        """Calculate RSI."""
        df = self._get_df(symbol)
        if len(df) < self.rsi_window + 1:
            return None
        closes = df["close"].tail(self.rsi_window + 1)
        delta = closes.diff().dropna()
        gains = delta.where(delta > 0, 0.0)
        losses = (-delta).where(delta < 0, 0.0)
        avg_gain = gains.mean()
        avg_loss = losses.mean()
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return float(100.0 - (100.0 / (1.0 + rs)))

    def _momentum(self, symbol: str, lookback: int) -> Optional[float]:
        """Calculate momentum as percentage return over lookback period."""
        df = self._get_df(symbol)
        if len(df) < lookback:
            return None
        window = df["close"].tail(lookback)
        if len(window) < 2:
            return None
        first = float(window.iloc[0])
        last = float(window.iloc[-1])
        if first <= 0:
            return None
        return ((last - first) / first) * 100.0  # Return as percentage

    def _volume_avg(self, symbol: str, lookback: int = 20) -> Optional[float]:
        """Calculate average volume."""
        df = self._get_df(symbol)
        if len(df) < lookback:
            return None
        return float(df["volume"].tail(lookback).mean())

    def _atr_ratio(self, symbol: str) -> Optional[float]:
        """Calculate current ATR / average ATR ratio for volatility assessment."""
        atr_now = self._atr(symbol)
        if atr_now is None:
            return None

        # Calculate average ATR over longer period
        df = self._get_df(symbol)
        lookback = self.sma_slow  # Use slow SMA period for ATR averaging
        if len(df) < self.atr_window + lookback:
            return 1.0  # Default ratio if not enough data

        atr_values = []
        for i in range(lookback):
            end_idx = len(df) - i
            start_idx = max(0, end_idx - self.atr_window - 1)
            if end_idx - start_idx < self.atr_window + 1:
                continue
            d = df.iloc[start_idx:end_idx].copy()
            prev_close = d["close"].shift(1)
            tr = pd.concat(
                [
                    (d["high"] - d["low"]).abs(),
                    (d["high"] - prev_close).abs(),
                    (d["low"] - prev_close).abs(),
                ],
                axis=1,
            ).max(axis=1)
            tr = tr.iloc[1:]
            if len(tr) >= self.atr_window:
                atr_values.append(float(tr.mean()))

        if len(atr_values) < 2:
            return 1.0

        avg_atr = np.mean(atr_values)
        if avg_atr <= 0:
            return 1.0

        return atr_now / avg_atr

    # ---------------------------- Regime Detection ----------------------------
    def _calculate_regime(self, symbol: Optional[str] = None) -> str:
        """
        Determine market regime based on BTC (or specified symbol) as leader.

        Returns:
            "UPTREND": Strong upward trend - go long
            "DOWNTREND": Strong downward trend - go short
            "NEUTRAL": Mixed signals or extreme volatility - no trade
        """
        # Use BTC as leader if symbol not specified
        if symbol is None:
            symbol = self.symbols[0]  # BTC should be first

        df = self._get_df(symbol)
        if df.empty:
            return "NEUTRAL"

        close = float(df["close"].iloc[-1])

        # Calculate SMAs
        sma_fast = self._sma(symbol, self.sma_fast)
        sma_slow = self._sma(symbol, self.sma_slow)
        if sma_fast is None or sma_slow is None:
            return "NEUTRAL"

        # Calculate momentum (short and long)
        mom_short = self._momentum(symbol, self.momentum_short)
        mom_long = self._momentum(symbol, self.momentum_long)
        if mom_short is None or mom_long is None:
            return "NEUTRAL"

        # Check for extreme volatility (NEUTRAL if too volatile)
        atr_ratio = self._atr_ratio(symbol)
        if atr_ratio is not None and atr_ratio > self.max_atr_ratio:
            self.last_reason = f"extreme_volatility:{atr_ratio:.2f}"
            return "NEUTRAL"

        # Check for minimum momentum (NEUTRAL if no clear direction)
        if abs(mom_short) < self.min_momentum_pct:
            self.last_reason = f"weak_momentum:{mom_short:.2f}%"
            return "NEUTRAL"

        # UPTREND conditions:
        # - close > SMA(50)
        # - SMA(20) > SMA(50)
        # - momentum_20 > 0
        # - momentum_50 > 0
        if (close > sma_slow and
            sma_fast > sma_slow and
            mom_short > 0 and
            mom_long > 0):
            return "UPTREND"

        # DOWNTREND conditions:
        # - close < SMA(50)
        # - SMA(20) < SMA(50)
        # - momentum_20 < 0
        # - momentum_50 < 0
        if (close < sma_slow and
            sma_fast < sma_slow and
            mom_short < 0 and
            mom_long < 0):
            return "DOWNTREND"

        # Mixed signals
        self.last_reason = "mixed_signals"
        return "NEUTRAL"

    # ---------------------------- Symbol Selection ----------------------------
    def _select_best_symbol(self, regime: str) -> Optional[tuple[str, float]]:
        """
        Select the best symbol based on momentum.

        For UPTREND: Select symbol with HIGHEST momentum (strongest)
        For DOWNTREND: Select symbol with LOWEST momentum (weakest)

        Returns:
            (symbol, momentum_value) or None if no valid candidate
        """
        candidates = []

        for sym in self.symbols:
            mom = self._momentum(sym, self.momentum_short)
            if mom is None:
                continue
            candidates.append((sym, mom))

        if not candidates:
            return None

        if regime == "UPTREND":
            # Select strongest (highest momentum)
            candidates.sort(key=lambda x: x[1], reverse=True)
        else:  # DOWNTREND
            # Select weakest (lowest momentum)
            candidates.sort(key=lambda x: x[1])

        return candidates[0]

    # ---------------------------- Entry Logic ----------------------------
    def _check_entry(
        self, state: MarketState, regime: str, now: datetime
    ) -> Optional[tuple[str, str, float]]:
        """
        Check entry conditions based on regime.

        Returns:
            (symbol, side, entry_price) or None
        """
        if regime == "NEUTRAL":
            return None

        # Select best symbol
        best = self._select_best_symbol(regime)
        if best is None:
            self.last_reason = "no_valid_symbol"
            return None

        sym, momentum = best
        df = self._get_df(sym)
        if df.empty:
            return None

        close = float(df["close"].iloc[-1])
        sma_fast = self._sma(sym, self.sma_fast)
        rsi = self._rsi(sym)
        vol = float(df["volume"].iloc[-1])
        vol_avg = self._volume_avg(sym)

        if sma_fast is None or rsi is None:
            return None

        # Volume confirmation
        if vol_avg is not None and vol_avg > 0:
            vol_confirmed = vol >= vol_avg * self.volume_confirm_mult
        else:
            vol_confirmed = True  # Skip volume filter if no data

        if not vol_confirmed:
            self.last_reason = f"low_volume:{sym}"
            return None

        # LONG entry (UPTREND regime only)
        if regime == "UPTREND":
            # 1. Momentum > entry_momentum_pct
            if momentum < self.entry_momentum_pct:
                self.last_reason = f"weak_entry_momentum:{momentum:.2f}%"
                return None
            # 2. Close > SMA(20)
            if close <= sma_fast:
                self.last_reason = f"close_below_sma20:{sym}"
                return None
            # 3. RSI < overbought
            if rsi >= self.rsi_overbought:
                self.last_reason = f"overbought:{rsi:.1f}"
                return None

            return (sym, "LONG", close)

        # SHORT entry (DOWNTREND regime only)
        if regime == "DOWNTREND":
            # 1. Momentum < -entry_momentum_pct
            if momentum > -self.entry_momentum_pct:
                self.last_reason = f"weak_entry_momentum:{momentum:.2f}%"
                return None
            # 2. Close < SMA(20)
            if close >= sma_fast:
                self.last_reason = f"close_above_sma20:{sym}"
                return None
            # 3. RSI > oversold (avoid shorting at bottom)
            if rsi <= self.rsi_oversold:
                self.last_reason = f"oversold:{rsi:.1f}"
                return None

            return (sym, "SHORT", close)

        return None

    # ---------------------------- Exit Logic ----------------------------
    def _check_exits(
        self, state: MarketState, now: datetime
    ) -> Optional[tuple[Order, str]]:
        """
        Check all exit conditions for current position.

        Exit priority:
        1. Stop Loss: 3x ATR from entry
        2. Take Profit: 6x ATR from entry
        3. Trailing Stop: After 1R profit, trail at 2x ATR
        4. Regime Change: Exit if trend flips
        5. Time Exit: Max 720 minutes (12 hours)

        Returns:
            (Exit Order, symbol) if any exit condition met, None otherwise
        """
        if self._position_symbol is None:
            return None

        sym = self._position_symbol
        df = self._get_df(sym)
        if df.empty:
            return None

        close = float(df["close"].iloc[-1])
        high = float(df["high"].iloc[-1])
        low = float(df["low"].iloc[-1])

        # Use entry ATR for consistent stop/target levels
        atr = self._entry_atr if self._entry_atr > 0 else self._atr(sym)
        if atr is None or atr <= 0:
            atr = close * 0.01  # Fallback: 1% of price

        # Update position high/low for trailing stop
        if self._position_side == "LONG":
            self._position_high = max(self._position_high, high)
        else:  # SHORT
            self._position_low = min(self._position_low, low)

        # Get position quantity from state
        positions = state.positions or {}
        pos = positions.get(sym, {})
        qty = float(pos.get("qty", 0.0) or 0.0)
        if qty <= 0:
            # Position closed externally
            exit_symbol = self._position_symbol
            self._clear_position()
            return None

        exit_side = Side.SELL if self._position_side == "LONG" else Side.BUY
        exit_reason = None

        # Calculate stop/target levels
        if self._position_side == "LONG":
            stop_loss = self._entry_price - self.stop_atr_mult * atr
            take_profit = self._entry_price + self.take_profit_atr_mult * atr
            trail_activation = self._entry_price + self.trail_activation_mult * atr

            # Check if trailing should be activated
            if self._position_high >= trail_activation:
                self._trailing_active = True

            # 1. Stop Loss
            if close <= stop_loss:
                exit_reason = "stop_loss"
            # 2. Take Profit
            elif close >= take_profit:
                exit_reason = "take_profit"
            # 3. Trailing Stop (only if activated)
            elif self._trailing_active:
                trailing_stop = self._position_high - self.trail_distance_mult * atr
                if close <= trailing_stop:
                    exit_reason = "trailing_stop"

        else:  # SHORT
            stop_loss = self._entry_price + self.stop_atr_mult * atr
            take_profit = self._entry_price - self.take_profit_atr_mult * atr
            trail_activation = self._entry_price - self.trail_activation_mult * atr

            # Check if trailing should be activated
            if self._position_low <= trail_activation:
                self._trailing_active = True

            # 1. Stop Loss
            if close >= stop_loss:
                exit_reason = "stop_loss"
            # 2. Take Profit
            elif close <= take_profit:
                exit_reason = "take_profit"
            # 3. Trailing Stop (only if activated)
            elif self._trailing_active:
                trailing_stop = self._position_low + self.trail_distance_mult * atr
                if close >= trailing_stop:
                    exit_reason = "trailing_stop"

        # 4. Regime Change Exit
        if not exit_reason:
            current_regime = self._calculate_regime()
            old_direction = "UP" if self._position_side == "LONG" else "DOWN"
            new_direction = "UP" if current_regime == "UPTREND" else ("DOWN" if current_regime == "DOWNTREND" else None)

            # Exit if regime flips (UPTREND -> DOWNTREND or vice versa)
            if new_direction is not None and old_direction != new_direction:
                exit_reason = "regime_change"

        # 5. Time-Based Exit
        if self._entry_time and not exit_reason:
            elapsed_minutes = (now - self._entry_time).total_seconds() / 60
            if elapsed_minutes >= self.max_hold_minutes:
                exit_reason = "time_exit"

        if exit_reason:
            self.last_reason = f"exit:{exit_reason}"
            # Save symbol before clearing position
            exit_symbol = self._position_symbol
            self._clear_position()
            self._last_trade_bar = self._bar_count
            # Return tuple with (order, symbol)
            return (Order(side=exit_side, quantity=qty, order_type=OrderType.MARKET), exit_symbol)

        return None

    def _clear_position(self) -> None:
        """Reset position tracking."""
        self._position_symbol = None
        self._position_side = None
        self._entry_price = 0.0
        self._entry_time = None
        self._entry_atr = 0.0
        self._position_high = 0.0
        self._position_low = float("inf")
        self._trailing_active = False
        self._current_regime = "NEUTRAL"

    def _sync_position_from_state(self, state: MarketState) -> None:
        """Sync internal position tracking with actual state."""
        positions = state.positions or {}

        # Check if our tracked position still exists
        if self._position_symbol:
            pos = positions.get(self._position_symbol, {})
            qty = float(pos.get("qty", 0.0) or 0.0)
            if qty <= 0:
                # Position was closed (stop loss hit externally, etc.)
                self._clear_position()

        # Check for any existing position we should track
        if not self._position_symbol:
            for sym, pos in positions.items():
                if not pos:
                    continue
                side = pos.get("side")
                qty = float(pos.get("qty", 0.0) or 0.0)
                entry = float(pos.get("entry_price", 0.0) or 0.0)
                if qty > 0 and side in ("LONG", "SHORT"):
                    # Found an existing position - track it
                    self._position_symbol = sym
                    self._position_side = side
                    self._entry_price = entry
                    self._entry_time = state.timestamp
                    self._entry_atr = self._atr(sym) or 0.0
                    self._current_regime = self._calculate_regime()
                    df = self._get_df(sym)
                    if not df.empty:
                        self._position_high = float(df["high"].iloc[-1])
                        self._position_low = float(df["low"].iloc[-1])
                    break

    # ---------------------------- Main Logic ----------------------------
    def generate_order(self, state: MarketState) -> PortfolioOrder | None:
        """
        Generate trading orders based on trend-following regime.

        Returns:
            PortfolioOrder with single position order, or None
        """
        if state.symbol is None:
            return None
        if state.panel is None:
            return None

        self._update_panel(state)

        if not self._has_warmup():
            return None

        self._sync_position_from_state(state)
        now = state.timestamp

        # Check exits first (highest priority)
        exit_result = self._check_exits(state, now)
        if exit_result:
            exit_order, exit_symbol = exit_result
            return PortfolioOrder({exit_symbol: exit_order})

        # Don't enter if we have a position
        if self._position_symbol:
            self.last_reason = "holding_position"
            return None

        # Trade cooldown
        if self._bar_count - self._last_trade_bar < self.cooldown_bars:
            self.last_reason = "cooldown"
            return None

        # Determine regime using BTC as leader
        regime = self._calculate_regime()
        self.last_regime = regime
        self._current_regime = regime

        if regime == "NEUTRAL":
            self.last_reason = "neutral_regime"
            return None

        # Check entry conditions
        entry = self._check_entry(state, regime, now)

        if entry is None:
            self.last_reason = f"no_signal_{regime.lower()}"
            return None

        sym, side, entry_price = entry

        # Get ATR for position sizing
        atr = self._atr(sym)
        if atr is None or atr <= 0:
            self.last_reason = f"no_atr:{sym}"
            return None

        # Set up position tracking
        self._position_symbol = sym
        self._position_side = side
        self._entry_price = entry_price
        self._entry_time = now
        self._entry_atr = atr
        self._position_high = entry_price
        self._position_low = entry_price
        self._trailing_active = False
        self._last_trade_bar = self._bar_count

        # Create order
        order_side = Side.BUY if side == "LONG" else Side.SELL
        order = Order(
            side=order_side,
            quantity=0.0,  # Let runner calculate based on weight
            order_type=OrderType.MARKET,
            weight=1.0,  # Full allocation to single position
        )

        self.last_reason = f"entry_{regime.lower()}_{side.lower()}"
        return PortfolioOrder({sym: order})

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(symbols={len(self.symbols)}, "
            f"regime={self.last_regime}, reason={self.last_reason})"
        )
