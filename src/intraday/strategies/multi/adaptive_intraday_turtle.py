"""Adaptive Intraday Turtle (AIT) Strategy.

Adapts the classic Turtle trading system for 5-minute crypto intraday trading with:
- Extended lookback: 144/288 bars (12-24 hours) instead of 20/55
- Volume filter: 1.3x above average required
- Volatility regime filter: ATR expansion > 0.85
- Wider stops: 3.5 ATR (vs 2.0)
- Reduced leverage: 2x (vs 5x)
- Position limit: 3 max

Key Adaptations from Classic Turtle:
- Classic Turtle uses 20/55 daily bars = 20-55 days lookback
- 5-minute equivalent: 20 bars = 100 min (too short, whipsaw)
- Our adaptation: 144-288 bars = 12-24 hours (captures full session cycles)
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


class AdaptiveIntradayTurtleStrategy:
    """Adaptive Intraday Turtle strategy for multi-symbol portfolio trading."""

    def __init__(
        self,
        symbols: list[str],
        # Lookback Parameters
        fast_window: int = 144,  # 12 hours at 5-min bars
        slow_window: int = 288,  # 24 hours at 5-min bars
        atr_window: int = 24,  # 2 hours for responsive ATR
        vol_regime_window: int = 96,  # 8 hours baseline for volatility regime
        # Filter Parameters
        volume_threshold: float = 1.3,  # Above-average volume confirms institutional participation
        vol_regime_threshold: float = 0.85,  # Avoid low-volatility chop periods
        breakout_atr_multiple: float = 0.5,  # Minimum breakout magnitude to filter noise
        corr_threshold: float = 0.85,  # Correlation limit for same-direction positions
        # Risk Management Parameters
        stop_atr_multiple: float = 3.5,  # Wider than classic Turtle (2.0) for crypto noise
        trail_atr_multiple: float = 2.5,  # Tighter than stop to lock profits
        trail_activate_atr: float = 2.0,  # Activate trailing after meaningful profit
        max_positions: int = 3,  # Concentrated portfolio for conviction trades
        max_holding_bars: int = 576,  # 48 hours maximum hold
        # Additional Parameters
        volume_ma_window: int = 24,  # 2 hours for volume moving average
        corr_window: int = 120,  # Window for correlation calculation
        history_max_len: int = 2000,  # Maximum bars to keep in memory
        atr_min: float = 1e-8,  # Minimum ATR to avoid division by zero
    ):
        # Validate parameters
        if fast_window < 1 or slow_window < fast_window:
            raise ValueError("slow_window must be >= fast_window and both > 0")

        # Store parameters
        self.symbols = symbols
        self.fast_window = int(fast_window)
        self.slow_window = int(slow_window)
        self.atr_window = int(atr_window)
        self.vol_regime_window = int(vol_regime_window)
        self.volume_threshold = float(volume_threshold)
        self.vol_regime_threshold = float(vol_regime_threshold)
        self.breakout_atr_multiple = float(breakout_atr_multiple)
        self.corr_threshold = float(corr_threshold)
        self.stop_atr_multiple = float(stop_atr_multiple)
        self.trail_atr_multiple = float(trail_atr_multiple)
        self.trail_activate_atr = float(trail_activate_atr)
        self.max_positions = int(max_positions)
        self.max_holding_bars = int(max_holding_bars)
        self.volume_ma_window = int(volume_ma_window)
        self.corr_window = int(corr_window)
        self.history_max_len = int(history_max_len)
        self.atr_min = float(atr_min)

        # Initialize data structures
        self._bars: dict[str, pd.DataFrame] = {
            sym: pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
            for sym in symbols
        }
        self._bar_count: int = 0

        # Position tracking
        # {symbol: {side, entry_price, entry_bar, entry_atr, stop_loss, trail_stop, trail_active, qty}}
        self._position_state: dict[str, dict] = {}

        # Pending orders for current timestamp
        self._last_ts: Optional[datetime] = None
        self._pending_orders: dict[str, Order] = {}
        self._pending_ts: Optional[datetime] = None

        # Debugging/monitoring
        self.last_reason: str = "init"
        self.last_state: dict = {
            "timestamp": None,
            "signals": {},
            "orders": {},
        }

    # =========================================================================
    # Data Handling
    # =========================================================================

    def _append_bar(
        self, symbol: str, ts: datetime, o: float, h: float, l: float, c: float, v: float
    ) -> None:
        """Append a new bar to the symbol's history."""
        row = pd.DataFrame(
            {
                "open": [float(o)],
                "high": [float(h)],
                "low": [float(l)],
                "close": [float(c)],
                "volume": [float(v)],
            },
            index=[ts],
        )

        df = self._bars.get(symbol)
        if df is None or df.empty:
            df = row
        else:
            df = pd.concat([df, row])

        # Keep only the most recent bars and remove duplicates
        df = df.sort_index().tail(self.history_max_len)
        df = df[~df.index.duplicated(keep="last")]
        self._bars[symbol] = df

    def _update_bars(self, state: MarketState) -> bool:
        """Update bar data from MarketState panel."""
        panel = state.panel
        if not panel:
            return False

        ts = state.timestamp
        changed = False
        for sym, bar in panel.items():
            if sym not in self._bars:
                continue
            if not bar:
                continue
            o = bar.get("open")
            h = bar.get("high")
            l = bar.get("low")
            c = bar.get("close")
            v = bar.get("volume", 0.0)
            if o is None or h is None or l is None or c is None:
                continue
            self._append_bar(sym, ts, float(o), float(h), float(l), float(c), float(v or 0.0))
            changed = True

        if changed:
            self._bar_count += 1
        return changed

    def _has_warmup(self) -> bool:
        """Check if we have enough bars for all indicators."""
        # Need slow_window + atr_window for Donchian and ATR
        # Also need vol_regime_window for ATR regime
        need = max(self.slow_window, self.vol_regime_window) + self.atr_window + 1
        for sym, df in self._bars.items():
            if len(df) < need:
                self.last_reason = f"need_more_bars:{sym}:{len(df)}/{need}"
                return False
        return True

    # =========================================================================
    # Indicators
    # =========================================================================

    def _atr(self, sym: str) -> Optional[float]:
        """Calculate current ATR for a symbol."""
        df = self._bars[sym]
        if len(df) < self.atr_window + 1:
            return None

        d = df.tail(self.atr_window + 1)
        prev = d["close"].shift(1)
        tr = pd.concat(
            [
                (d["high"] - d["low"]).abs(),
                (d["high"] - prev).abs(),
                (d["low"] - prev).abs(),
            ],
            axis=1,
        ).max(axis=1)
        tr = tr.iloc[1:]  # Remove first NaN
        v = float(tr.rolling(self.atr_window).mean().iloc[-1])
        return v if pd.notna(v) and v > self.atr_min else None

    def _atr_regime_ratio(self, sym: str) -> Optional[float]:
        """Calculate ATR regime ratio: current ATR / SMA(ATR, vol_regime_window)."""
        df = self._bars[sym]
        if len(df) < self.vol_regime_window + self.atr_window + 1:
            return None

        # Calculate rolling ATR series
        d = df.tail(self.vol_regime_window + self.atr_window + 1)
        prev = d["close"].shift(1)
        tr = pd.concat(
            [
                (d["high"] - d["low"]).abs(),
                (d["high"] - prev).abs(),
                (d["low"] - prev).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr_series = tr.rolling(self.atr_window).mean()

        current_atr = float(atr_series.iloc[-1])
        atr_ma = float(atr_series.tail(self.vol_regime_window).mean())

        if pd.isna(current_atr) or pd.isna(atr_ma) or atr_ma < self.atr_min:
            return None

        return current_atr / atr_ma

    def _volume_ratio(self, sym: str) -> Optional[float]:
        """Calculate volume ratio: current volume / SMA(volume, volume_ma_window)."""
        df = self._bars[sym]
        if len(df) < self.volume_ma_window + 1:
            return None

        current_vol = float(df["volume"].iloc[-1])
        vol_ma = float(df["volume"].tail(self.volume_ma_window + 1).iloc[:-1].mean())

        if pd.isna(current_vol) or pd.isna(vol_ma) or vol_ma <= 0:
            return None

        return current_vol / vol_ma

    def _donchian_channels(self, sym: str, window: int) -> tuple[Optional[float], Optional[float]]:
        """Calculate Donchian channel high and low (excluding current bar)."""
        df = self._bars[sym]
        if len(df) <= window:
            return None, None

        # Exclude current bar (use -window-1:-1)
        lookback = df.iloc[-window - 1 : -1]
        high = float(lookback["high"].max())
        low = float(lookback["low"].min())

        if pd.isna(high) or pd.isna(low):
            return None, None

        return high, low

    def _corr(self, sym_a: str, sym_b: str) -> float:
        """Calculate correlation between two symbols."""
        if sym_a not in self._bars or sym_b not in self._bars:
            return 0.0
        da = self._bars[sym_a]["close"].pct_change().tail(self.corr_window)
        db = self._bars[sym_b]["close"].pct_change().tail(self.corr_window)
        if len(da) < 20 or len(db) < 20:
            return 0.0
        df_corr = pd.concat([da, db], axis=1).dropna()
        if len(df_corr) < 20:
            return 0.0
        return float(df_corr.iloc[:, 0].corr(df_corr.iloc[:, 1]))

    # =========================================================================
    # Entry Conditions
    # =========================================================================

    def _check_entry_signal(self, sym: str) -> int:
        """
        Check entry conditions for a symbol.

        Returns:
            1 for LONG signal
            -1 for SHORT signal
            0 for no signal
        """
        df = self._bars[sym]
        if len(df) <= self.slow_window:
            return 0

        close = float(df["close"].iloc[-1])

        # Get Donchian channels
        fast_high, fast_low = self._donchian_channels(sym, self.fast_window)
        slow_high, slow_low = self._donchian_channels(sym, self.slow_window)

        if fast_high is None or slow_high is None:
            return 0

        # Get ATR for breakout magnitude check
        atr = self._atr(sym)
        if atr is None or atr < self.atr_min:
            return 0

        # Get volume ratio
        vol_ratio = self._volume_ratio(sym)
        if vol_ratio is None:
            return 0

        # Get ATR regime ratio
        atr_regime = self._atr_regime_ratio(sym)
        if atr_regime is None:
            return 0

        # LONG conditions
        if close > fast_high and close > slow_high:
            # Check breakout magnitude
            breakout_magnitude = close - fast_high
            if breakout_magnitude < self.breakout_atr_multiple * atr:
                return 0

            # Check volume filter
            if vol_ratio < self.volume_threshold:
                return 0

            # Check volatility regime
            if atr_regime < self.vol_regime_threshold:
                return 0

            return 1

        # SHORT conditions
        if close < fast_low and close < slow_low:
            # Check breakout magnitude
            breakout_magnitude = fast_low - close
            if breakout_magnitude < self.breakout_atr_multiple * atr:
                return 0

            # Check volume filter
            if vol_ratio < self.volume_threshold:
                return 0

            # Check volatility regime
            if atr_regime < self.vol_regime_threshold:
                return 0

            return -1

        return 0

    def _check_position_limit(self, side: int) -> bool:
        """Check if we can open a new position given position limits."""
        open_count = len(self._position_state)
        if open_count >= self.max_positions:
            return False
        return True

    def _check_correlation_limit(self, symbol: str, side: int) -> bool:
        """
        Check correlation limit: If entering same direction as existing position,
        correlation < corr_threshold OR position count in direction < 2.
        """
        # Count positions in the same direction
        same_direction_count = 0
        side_str = "LONG" if side == 1 else "SHORT"

        for open_sym, info in self._position_state.items():
            if open_sym == symbol:
                continue
            if info["side"] == side_str:
                same_direction_count += 1
                # Check correlation
                corr = abs(self._corr(symbol, open_sym))
                if corr >= self.corr_threshold and same_direction_count >= 2:
                    return False

        return True

    # =========================================================================
    # Exit Conditions
    # =========================================================================

    def _check_exit_conditions(
        self, sym: str, info: dict, current_price: float, atr: float
    ) -> tuple[bool, str]:
        """
        Check exit conditions for an open position.

        Returns:
            (should_exit, reason)
        """
        side = info["side"]
        entry_price = info["entry_price"]
        entry_bar = info["entry_bar"]
        stop_loss = info["stop_loss"]
        trail_stop = info["trail_stop"]
        trail_active = info["trail_active"]
        entry_atr = info["entry_atr"]

        # 1. Stop Loss (Hard Exit)
        if side == "LONG" and current_price <= stop_loss:
            return True, "stop_loss"
        if side == "SHORT" and current_price >= stop_loss:
            return True, "stop_loss"

        # 2. Trailing Stop
        if trail_active:
            if side == "LONG" and current_price <= trail_stop:
                return True, "trailing_stop"
            if side == "SHORT" and current_price >= trail_stop:
                return True, "trailing_stop"

        # 3. Max Holding Time
        bars_held = self._bar_count - entry_bar
        if bars_held >= self.max_holding_bars:
            return True, "max_holding_time"

        # 4. Counter-Signal Exit
        _, slow_low = self._donchian_channels(sym, self.slow_window)
        slow_high, _ = self._donchian_channels(sym, self.slow_window)

        if side == "LONG" and slow_low is not None:
            if current_price < slow_low:
                return True, "counter_signal"

        if side == "SHORT" and slow_high is not None:
            if current_price > slow_high:
                return True, "counter_signal"

        return False, ""

    def _update_trailing_stop(
        self, sym: str, info: dict, current_price: float, current_high: float, current_low: float, atr: float
    ) -> None:
        """Update trailing stop for an open position."""
        side = info["side"]
        entry_price = info["entry_price"]
        entry_atr = info["entry_atr"]
        trail_active = info["trail_active"]

        # Check if trailing should be activated
        if not trail_active:
            if side == "LONG":
                profit_atr = (current_price - entry_price) / entry_atr
                if profit_atr >= self.trail_activate_atr:
                    info["trail_active"] = True
                    info["trail_stop"] = current_high - atr * self.trail_atr_multiple
            else:  # SHORT
                profit_atr = (entry_price - current_price) / entry_atr
                if profit_atr >= self.trail_activate_atr:
                    info["trail_active"] = True
                    info["trail_stop"] = current_low + atr * self.trail_atr_multiple

        # Update trailing stop if active
        if info["trail_active"]:
            if side == "LONG":
                new_trail = current_high - atr * self.trail_atr_multiple
                info["trail_stop"] = max(info["trail_stop"], new_trail)
            else:  # SHORT
                new_trail = current_low + atr * self.trail_atr_multiple
                info["trail_stop"] = min(info["trail_stop"], new_trail)

    # =========================================================================
    # Order Building
    # =========================================================================

    def _build_plan(self, state: MarketState) -> dict[str, Optional[Order]]:
        """Build order plan for all symbols at current timestamp."""
        ts = state.timestamp

        # Collect current prices and ATRs
        signals: dict[str, int] = {}
        atrs: dict[str, float] = {}
        prices: dict[str, float] = {}
        highs: dict[str, float] = {}
        lows: dict[str, float] = {}

        for sym in self.symbols:
            if sym not in self._bars or self._bars[sym].empty:
                continue
            df = self._bars[sym]
            close = float(df["close"].iloc[-1])
            high = float(df["high"].iloc[-1])
            low = float(df["low"].iloc[-1])
            atr_v = self._atr(sym)

            if np.isfinite(close) and close > 0 and atr_v is not None and atr_v > 0:
                prices[sym] = close
                highs[sym] = high
                lows[sym] = low
                atrs[sym] = float(atr_v)
                signals[sym] = self._check_entry_signal(sym)
            else:
                signals[sym] = 0

        orders: dict[str, Optional[Order]] = {}

        # 1. Check existing positions for exits
        symbols_to_close = []
        for sym in list(self._position_state.keys()):
            info = self._position_state[sym]
            price = prices.get(sym)
            atr = atrs.get(sym)
            high = highs.get(sym, price)
            low = lows.get(sym, price)

            if price is None or atr is None:
                continue

            # Update trailing stop first
            self._update_trailing_stop(sym, info, price, high, low, atr)

            # Check exit conditions
            should_exit, exit_reason = self._check_exit_conditions(sym, info, price, atr)

            if should_exit:
                qty = info.get("qty", 0.0)
                if qty > 0:
                    if info["side"] == "LONG":
                        orders[sym] = Order(
                            side=Side.SELL,
                            quantity=qty,
                            order_type=OrderType.MARKET,
                        )
                    else:  # SHORT
                        orders[sym] = Order(
                            side=Side.BUY,
                            quantity=qty,
                            order_type=OrderType.MARKET,
                        )
                    symbols_to_close.append(sym)

        # Remove closed positions
        for sym in symbols_to_close:
            self._position_state.pop(sym, None)

        # 2. Check for new entries (if position slots available)
        # Sort candidates by signal strength (breakout magnitude)
        candidates: list[tuple[str, int, float]] = []
        for sym, sig in signals.items():
            if sig == 0:
                continue
            if sym in self._position_state:
                continue
            if sym in orders and orders[sym] is not None:
                continue
            if sym not in prices or sym not in atrs:
                continue

            # Calculate score based on breakout magnitude
            df = self._bars[sym]
            close = prices[sym]
            atr = atrs[sym]

            fast_high, fast_low = self._donchian_channels(sym, self.fast_window)
            if fast_high is None:
                continue

            if sig == 1:
                breakout_mag = (close - fast_high) / atr
            else:
                breakout_mag = (fast_low - close) / atr

            candidates.append((sym, sig, breakout_mag))

        # Sort by breakout magnitude (higher is better)
        candidates.sort(key=lambda x: x[2], reverse=True)

        for sym, sig, _score in candidates:
            # Check position limit
            if not self._check_position_limit(sig):
                break

            # Check correlation limit
            if not self._check_correlation_limit(sym, sig):
                continue

            if sym not in prices or sym not in atrs:
                continue

            price = prices[sym]
            atr = atrs[sym]

            # Position sizing (simple fixed quantity for now - can be enhanced)
            qty = 1.0  # Will be scaled by runner based on risk parameters

            if sig == 1:  # LONG
                stop_loss = price - atr * self.stop_atr_multiple
                orders[sym] = Order(
                    side=Side.BUY,
                    quantity=qty,
                    order_type=OrderType.MARKET,
                    stop_loss=stop_loss,
                )
                self._position_state[sym] = {
                    "side": "LONG",
                    "entry_price": price,
                    "entry_bar": self._bar_count,
                    "entry_atr": atr,
                    "qty": qty,
                    "stop_loss": stop_loss,
                    "trail_stop": price - atr * self.trail_atr_multiple,
                    "trail_active": False,
                }

            elif sig == -1:  # SHORT
                stop_loss = price + atr * self.stop_atr_multiple
                orders[sym] = Order(
                    side=Side.SELL,
                    quantity=qty,
                    order_type=OrderType.MARKET,
                    stop_loss=stop_loss,
                )
                self._position_state[sym] = {
                    "side": "SHORT",
                    "entry_price": price,
                    "entry_bar": self._bar_count,
                    "entry_atr": atr,
                    "qty": qty,
                    "stop_loss": stop_loss,
                    "trail_stop": price + atr * self.trail_atr_multiple,
                    "trail_active": False,
                }

        # Store state for debugging
        self.last_state = {
            "timestamp": ts.isoformat() if ts else None,
            "signals": signals,
            "orders": {
                k: (
                    "LONG"
                    if v and v.side == Side.BUY
                    else "SHORT"
                    if v and v.side == Side.SELL
                    else None
                )
                for k, v in orders.items()
            },
        }

        return orders

    # =========================================================================
    # Public Interface
    # =========================================================================

    def generate_order(self, state: MarketState) -> PortfolioOrder | None:
        """
        Generate trading orders based on current market state.

        Args:
            state: Current market state with panel data

        Returns:
            PortfolioOrder with orders for the triggering symbol, or None
        """
        if state.panel is None:
            return None

        if not state.symbol:
            return None

        if not self._update_bars(state):
            return None

        if not self._has_warmup():
            return None

        ts = state.timestamp

        # Build order plan once per timestamp
        if self._pending_ts != ts:
            self._pending_orders = self._build_plan(state)
            self._pending_ts = ts

        # Return order for the current symbol if any
        if state.symbol in self._pending_orders:
            order = self._pending_orders[state.symbol]
            if order is None:
                self.last_reason = f"no_action:{state.symbol}"
                return None
            self.last_reason = f"order:{state.symbol}:{order.side.value}:{order.quantity:.6f}"
            return PortfolioOrder({state.symbol: order})

        self.last_reason = f"no_action:{state.symbol}"
        return None

    def set_initial_capital(self, initial_capital: float) -> None:
        """Set initial capital for risk calculations (optional)."""
        # This can be used by runners to inform the strategy of capital
        pass
