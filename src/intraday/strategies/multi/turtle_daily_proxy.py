"""Turtle Daily-Proxy Strategy (5-Minute Cross-Asset)

A redesigned Turtle strategy adapted for intraday 5-minute bars with:
- 288/576 bar windows (1-day/2-day lookback proxy)
- Confirmation bars (price must hold above/below breakout)
- ATR percentile regime filter
- Breakeven stop after 1 ATR profit
- Time stop after max bars in trade

Based on algorithm_prompt.txt design addressing:
- Excessive trading (8874 trades -> target <100)
- Poor risk/reward (PF 0.93 -> target >1.5)
- Timeframe mismatch (now aligns with daily Turtle concept)
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


class TurtleDailyProxyStrategy:
    """Cross-asset Turtle strategy with daily-proxy windows and confirmation filters."""

    def __init__(
        self,
        symbols: list[str],
        # Breakout windows (daily proxy)
        fast_window: int = 288,  # 24 hours at 5-min bars
        slow_window: int = 576,  # 48 hours at 5-min bars
        # ATR & Risk
        atr_window: int = 288,
        stop_atr: float = 3.0,  # Wider stop for noise survival
        trail_atr: float = 2.0,  # Tighter trail after confirmation
        # Confirmation filter
        confirm_bars: int = 3,  # Must hold breakout for 3 bars (15 min)
        atr_percentile_window: int = 288,  # Lookback for ATR percentile
        atr_percentile_threshold: float = 0.7,  # Only trade when ATR > 70th percentile
        # Time stop
        max_bars_in_trade: int = 576,  # Exit after 2 days
        # Breakeven stop
        use_breakeven_stop: bool = True,
        # Position sizing
        n_unit: float = 0.02,  # 2% risk per unit
        max_risk_per_trade_unit: float = 1.0,  # Max 1N per trade
        max_open_positions: int = 2,  # Concentrated portfolio
        # Technical
        atr_min: float = 1e-8,
        history_max_len: int = 1200,  # ~4 days of 5-min bars
    ):
        if fast_window < 1 or slow_window < fast_window:
            raise ValueError("slow_window must be >= fast_window and both > 0")
        if not (0 < n_unit < 1):
            raise ValueError("n_unit must be between 0 and 1")

        self.symbols = symbols
        self.fast_window = int(fast_window)
        self.slow_window = int(slow_window)
        self.atr_window = max(1, int(atr_window))
        self.stop_atr = float(stop_atr)
        self.trail_atr = float(trail_atr)

        # New parameters
        self.confirm_bars = max(1, int(confirm_bars))
        self.atr_percentile_window = max(1, int(atr_percentile_window))
        self.atr_percentile_threshold = float(atr_percentile_threshold)
        self.max_bars_in_trade = max(1, int(max_bars_in_trade))
        self.use_breakeven_stop = bool(use_breakeven_stop)

        self.n_unit = float(n_unit)
        self.max_risk_per_trade_unit = float(max_risk_per_trade_unit)
        self.max_open_positions = max(1, int(max_open_positions))
        self.atr_min = float(atr_min)
        self.history_max_len = max(10, int(history_max_len))

        self.initial_capital = 100_000.0

        # Bar history per symbol
        self._bars: dict[str, pd.DataFrame] = {
            sym: pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
            for sym in symbols
        }
        self._bar_count: int = 0

        # Position state per symbol
        self._position_state: dict[str, dict] = {}

        # Confirmation tracking: bars since breakout signal
        self._confirm_count: dict[str, int] = {}
        self._confirm_direction: dict[str, int] = {}  # 1=LONG, -1=SHORT, 0=none
        self._confirm_level: dict[str, float] = {}  # breakout level to hold

        # ATR history for percentile calculation
        self._atr_history: dict[str, list[float]] = {sym: [] for sym in symbols}

        self._last_ts: Optional[datetime] = None
        self._pending_orders: dict[str, Order] = {}
        self._pending_ts: Optional[datetime] = None

        self.last_reason: str = "init"
        self.last_state: dict = {
            "timestamp": None,
            "signals": {},
            "orders": {},
        }

    def set_initial_capital(self, initial_capital: float) -> None:
        if initial_capital > 0:
            self.initial_capital = float(initial_capital)

    # ── Data Handling ──────────────────────────────────────────────────────────

    def _append_bar(
        self, symbol: str, ts: datetime, o: float, h: float, l: float, c: float, v: float
    ) -> None:
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

        df = df.sort_index().tail(self.history_max_len)
        df = df[~df.index.duplicated(keep="last")]
        self._bars[symbol] = df

    def _update_bars(self, state: MarketState) -> bool:
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
        need = self.slow_window + max(1, self.atr_window)
        for sym in self.symbols:
            df = self._bars.get(sym)
            if df is None or len(df) < need:
                self.last_reason = f"need_more_bars:{sym}:{len(df) if df is not None else 0}"
                return False
        return True

    # ── Indicators ─────────────────────────────────────────────────────────────

    def _atr(self, sym: str) -> Optional[float]:
        """Calculate ATR for symbol and update history."""
        df = self._bars.get(sym)
        if df is None or len(df) < self.atr_window + 1:
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
        tr = tr.iloc[1:]
        v = float(tr.rolling(self.atr_window).mean().iloc[-1])

        if pd.notna(v) and v > 0:
            # Update ATR history for percentile calculation
            history = self._atr_history[sym]
            history.append(v)
            # Keep only atr_percentile_window entries
            if len(history) > self.atr_percentile_window:
                self._atr_history[sym] = history[-self.atr_percentile_window:]
            return v
        return None

    def _is_trending_regime(self, sym: str) -> bool:
        """Check if current ATR is above the percentile threshold (high volatility regime)."""
        history = self._atr_history.get(sym, [])
        if len(history) < 20:  # Need minimum history
            return True  # Allow trades during warmup

        current_atr = history[-1] if history else 0
        threshold = np.percentile(history, self.atr_percentile_threshold * 100)
        return current_atr > threshold

    def _get_breakout_levels(self, sym: str) -> tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
        """Get fast/slow high/low levels for breakout detection.

        Returns:
            (fast_high, slow_high, fast_low, slow_low) - excluding current bar
        """
        df = self._bars.get(sym)
        if df is None or len(df) <= self.slow_window:
            return None, None, None, None

        # Exclude current bar for breakout detection
        fast_hi = float(df["high"].iloc[-self.fast_window - 1:-1].max())
        slow_hi = float(df["high"].iloc[-self.slow_window - 1:-1].max())
        fast_lo = float(df["low"].iloc[-self.fast_window - 1:-1].min())
        slow_lo = float(df["low"].iloc[-self.slow_window - 1:-1].min())

        return fast_hi, slow_hi, fast_lo, slow_lo

    def _raw_breakout_signal(self, sym: str) -> int:
        """Check for raw breakout signal (before confirmation).

        Returns:
            1 for LONG breakout, -1 for SHORT breakout, 0 for no signal
        """
        df = self._bars.get(sym)
        if df is None or len(df) <= self.slow_window:
            return 0

        c = float(df["close"].iloc[-1])
        fast_hi, slow_hi, fast_lo, slow_lo = self._get_breakout_levels(sym)

        if fast_hi is None:
            return 0

        # LONG: close > both fast and slow highs
        if c > fast_hi and c > slow_hi:
            return 1
        # SHORT: close < both fast and slow lows
        if c < fast_lo and c < slow_lo:
            return -1
        return 0

    def _update_confirmation(self, sym: str, current_close: float) -> bool:
        """Update confirmation counter and check if entry is confirmed.

        Returns:
            True if position should be entered (confirmation complete)
        """
        raw_signal = self._raw_breakout_signal(sym)

        # Get breakout levels
        fast_hi, slow_hi, fast_lo, slow_lo = self._get_breakout_levels(sym)
        if fast_hi is None:
            self._confirm_count[sym] = 0
            self._confirm_direction[sym] = 0
            return False

        # Check if we have an active confirmation tracking
        prev_direction = self._confirm_direction.get(sym, 0)
        prev_count = self._confirm_count.get(sym, 0)

        if raw_signal == 1:  # LONG breakout
            breakout_level = max(fast_hi, slow_hi)
            if prev_direction == 1 and current_close > self._confirm_level.get(sym, 0):
                # Continue counting if still above breakout level
                self._confirm_count[sym] = prev_count + 1
            else:
                # Start new confirmation
                self._confirm_count[sym] = 1
                self._confirm_direction[sym] = 1
                self._confirm_level[sym] = breakout_level

        elif raw_signal == -1:  # SHORT breakout
            breakout_level = min(fast_lo, slow_lo)
            if prev_direction == -1 and current_close < self._confirm_level.get(sym, float('inf')):
                # Continue counting if still below breakout level
                self._confirm_count[sym] = prev_count + 1
            else:
                # Start new confirmation
                self._confirm_count[sym] = 1
                self._confirm_direction[sym] = -1
                self._confirm_level[sym] = breakout_level
        else:
            # No breakout signal - reset confirmation
            self._confirm_count[sym] = 0
            self._confirm_direction[sym] = 0

        # Check if confirmation is complete
        return self._confirm_count.get(sym, 0) >= self.confirm_bars

    def _confirmed_signal(self, sym: str) -> int:
        """Get confirmed breakout signal (after confirmation bars).

        Returns:
            1 for confirmed LONG, -1 for confirmed SHORT, 0 for no confirmed signal
        """
        df = self._bars.get(sym)
        if df is None or len(df) <= self.slow_window:
            return 0

        current_close = float(df["close"].iloc[-1])

        # Update confirmation tracking
        is_confirmed = self._update_confirmation(sym, current_close)

        if is_confirmed:
            direction = self._confirm_direction.get(sym, 0)
            # Check ATR regime filter
            if not self._is_trending_regime(sym):
                return 0
            return direction

        return 0

    def _risk_unit(self) -> float:
        """Calculate N (risk unit)."""
        return self.initial_capital * self.n_unit

    def _max_risk_for_symbol(self, symbol: str) -> float:
        """Get max risk for a new position."""
        return self._risk_unit() * self.max_risk_per_trade_unit

    def _position_qty(self, symbol: str, side: int, price: float) -> float:
        """Calculate position quantity based on risk budget."""
        atr = self._atr(symbol)
        if atr is None or atr < self.atr_min or price <= 0:
            return 0.0

        risk_budget = self._max_risk_for_symbol(symbol)
        stop_distance = atr * self.stop_atr
        qty = risk_budget / stop_distance
        return float(max(0.0, qty))

    # ── Stop Management ────────────────────────────────────────────────────────

    def _update_stop(self, sym: str, price: float, atr: float) -> None:
        """Update stop levels including breakeven and trailing logic."""
        if sym not in self._position_state:
            return

        info = self._position_state[sym]
        entry = info["entry_price"]
        side = info["side"]

        if side == "LONG":
            # Breakeven stop: after 1 ATR profit, move stop to entry
            if self.use_breakeven_stop and price >= entry + atr:
                info["breakeven_activated"] = True
                info["stop"] = max(info.get("stop", 0), entry)

            # Trailing stop: max of current trailing and new trail level
            if info.get("breakeven_activated", False):
                new_trail = price - atr * self.trail_atr
                info["trailing_stop"] = max(info.get("trailing_stop", 0), new_trail)
            else:
                # Before breakeven, use initial stop
                info["trailing_stop"] = max(
                    info.get("trailing_stop", 0),
                    price - atr * self.trail_atr
                )
        else:  # SHORT
            # Breakeven stop: after 1 ATR profit, move stop to entry
            if self.use_breakeven_stop and price <= entry - atr:
                info["breakeven_activated"] = True
                info["stop"] = min(info.get("stop", float('inf')), entry)

            # Trailing stop
            if info.get("breakeven_activated", False):
                new_trail = price + atr * self.trail_atr
                info["trailing_stop"] = min(
                    info.get("trailing_stop", float('inf')),
                    new_trail
                )
            else:
                info["trailing_stop"] = min(
                    info.get("trailing_stop", float('inf')),
                    price + atr * self.trail_atr
                )

        # Increment bars in trade
        info["bars_in_trade"] = info.get("bars_in_trade", 0) + 1

    def _should_exit(self, sym: str, price: float, atr: float) -> tuple[bool, str]:
        """Check if position should be exited.

        Returns:
            (should_exit, reason)
        """
        if sym not in self._position_state:
            return False, ""

        info = self._position_state[sym]
        side = info["side"]

        # Time stop
        bars_in_trade = info.get("bars_in_trade", 0)
        if bars_in_trade >= self.max_bars_in_trade:
            return True, "time_stop"

        # Get reversal signal
        confirmed_signal = self._confirmed_signal(sym)

        if side == "LONG":
            # Check trailing stop
            trail = info.get("trailing_stop", 0)
            if price <= trail:
                return True, "trailing_stop"

            # Check reversal signal
            if confirmed_signal == -1:
                return True, "reversal_signal"

        else:  # SHORT
            # Check trailing stop
            trail = info.get("trailing_stop", float('inf'))
            if price >= trail:
                return True, "trailing_stop"

            # Check reversal signal
            if confirmed_signal == 1:
                return True, "reversal_signal"

        return False, ""

    # ── Execution Plan ─────────────────────────────────────────────────────────

    def _build_plan(self, state: MarketState) -> dict[str, Optional[Order]]:
        """Build execution plan for all symbols."""
        ts = state.timestamp

        signals: dict[str, int] = {}
        atrs: dict[str, float] = {}
        prices: dict[str, float] = {}

        for sym in self.symbols:
            df = self._bars.get(sym)
            if df is None or df.empty:
                continue
            last = float(df["close"].iloc[-1])
            atr_v = self._atr(sym)
            if np.isfinite(last) and last > 0 and atr_v is not None and atr_v > 0:
                signals[sym] = self._confirmed_signal(sym)
                atrs[sym] = float(atr_v)
                prices[sym] = last
            else:
                signals[sym] = 0

        orders: dict[str, Optional[Order]] = {}

        # 1) Exit existing positions
        for sym in self.symbols:
            if sym not in self._position_state:
                continue
            info = self._position_state[sym]
            side = info["side"]
            price = prices.get(sym)
            atr = atrs.get(sym)
            if price is None or atr is None:
                continue

            # Update stop levels
            self._update_stop(sym, price, atr)

            # Check exit conditions
            should_exit, exit_reason = self._should_exit(sym, price, atr)

            if should_exit:
                qty = info.get("qty", 0.0)
                if qty > 0:
                    exit_side = Side.SELL if side == "LONG" else Side.BUY
                    orders[sym] = Order(
                        side=exit_side,
                        quantity=qty,
                        order_type=OrderType.MARKET,
                    )
                    self.last_reason = f"exit:{sym}:{exit_reason}"

        # Remove closed positions
        for sym in list(self._position_state.keys()):
            if sym in orders and orders[sym] is not None:
                self._position_state.pop(sym, None)
                # Reset confirmation tracking
                self._confirm_count[sym] = 0
                self._confirm_direction[sym] = 0

        # 2) New entries (max open positions limit)
        open_count = len(self._position_state)
        if open_count < self.max_open_positions:
            # Priority: signal strength (distance from breakout)
            candidates: list[tuple[str, int, float]] = []
            for sym, sig in signals.items():
                if sig == 0:
                    continue
                if sym in self._position_state:
                    continue
                if sym in orders and orders[sym] is not None:
                    continue

                df = self._bars.get(sym)
                if df is None or len(df) <= self.slow_window:
                    continue

                close = float(df["close"].iloc[-1])
                baseline = float(df["close"].iloc[-self.slow_window - 1])
                score = abs(close - baseline) / baseline if baseline > 0 else 0
                candidates.append((sym, sig, score))

            candidates.sort(key=lambda x: x[2], reverse=True)

            for sym, sig, _score in candidates:
                if len(self._position_state) >= self.max_open_positions:
                    break

                if sym not in atrs or sym not in prices:
                    continue

                price = prices[sym]
                qty = self._position_qty(sym, sig, price)
                if qty <= 0:
                    continue

                atr = atrs[sym]
                if sig == 1:  # LONG
                    stop = price - atr * self.stop_atr
                    orders[sym] = Order(
                        side=Side.BUY,
                        quantity=qty,
                        order_type=OrderType.MARKET,
                        stop_loss=stop,
                    )
                    self._position_state[sym] = {
                        "side": "LONG",
                        "entry_price": price,
                        "qty": qty,
                        "stop": stop,
                        "trailing_stop": price - atr * self.trail_atr,
                        "entry_atr": atr,
                        "bars_in_trade": 0,
                        "breakeven_activated": False,
                    }
                    # Reset confirmation after entry
                    self._confirm_count[sym] = 0
                    self._confirm_direction[sym] = 0

                elif sig == -1:  # SHORT
                    stop = price + atr * self.stop_atr
                    orders[sym] = Order(
                        side=Side.SELL,
                        quantity=qty,
                        order_type=OrderType.MARKET,
                        stop_loss=stop,
                    )
                    self._position_state[sym] = {
                        "side": "SHORT",
                        "entry_price": price,
                        "qty": qty,
                        "stop": stop,
                        "trailing_stop": price + atr * self.trail_atr,
                        "entry_atr": atr,
                        "bars_in_trade": 0,
                        "breakeven_activated": False,
                    }
                    # Reset confirmation after entry
                    self._confirm_count[sym] = 0
                    self._confirm_direction[sym] = 0

        self.last_state = {
            "timestamp": ts.isoformat() if ts else None,
            "signals": signals,
            "orders": {
                k: ("LONG" if v and v.side == Side.BUY else "SHORT" if v and v.side == Side.SELL else None)
                for k, v in orders.items()
            },
        }

        return orders

    # ── Public Interface ───────────────────────────────────────────────────────

    def generate_order(self, state: MarketState) -> PortfolioOrder | None:
        """Generate orders based on market state."""
        if state.panel is None:
            return None

        if not state.symbol:
            return None

        if not self._update_bars(state):
            return None

        if not self._has_warmup():
            return None

        ts = state.timestamp
        if self._pending_ts != ts:
            self._pending_orders = self._build_plan(state)
            self._pending_ts = ts

        if state.symbol in self._pending_orders:
            order = self._pending_orders[state.symbol]
            if order is None:
                self.last_reason = f"no_action:{state.symbol}"
                return None
            self.last_reason = f"order:{state.symbol}:{order.side.value}:{order.quantity:.6f}"
            return PortfolioOrder({state.symbol: order})

        self.last_reason = f"no_action:{state.symbol}"
        return None

    # ── Debug/Inspection Methods ───────────────────────────────────────────────

    def get_position_state(self, symbol: str) -> Optional[dict]:
        """Get current position state for a symbol (for testing/debugging)."""
        return self._position_state.get(symbol)

    def get_confirmation_state(self, symbol: str) -> dict:
        """Get confirmation tracking state for a symbol (for testing/debugging)."""
        return {
            "count": self._confirm_count.get(symbol, 0),
            "direction": self._confirm_direction.get(symbol, 0),
            "level": self._confirm_level.get(symbol, None),
        }

    def get_atr_percentile_info(self, symbol: str) -> dict:
        """Get ATR percentile info for a symbol (for testing/debugging)."""
        history = self._atr_history.get(symbol, [])
        if not history:
            return {"current": None, "threshold": None, "is_trending": None}

        current = history[-1]
        threshold = np.percentile(history, self.atr_percentile_threshold * 100) if len(history) >= 20 else 0
        is_trending = self._is_trending_regime(symbol)

        return {
            "current": current,
            "threshold": threshold,
            "is_trending": is_trending,
            "history_len": len(history),
        }
