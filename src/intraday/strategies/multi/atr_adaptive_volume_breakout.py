"""
ATR-Adaptive Volume Breakout (AAVB) Strategy

Entry Logic:
- Volume Breakout: Current bar volume > 1.5x SMA(volume, 20)
- ATR Range Break: close > close[1] + ATR (LONG) or close < close[1] - ATR (SHORT)
- Minimum Move: bar return > 0.3% (or < -0.3% for SHORT)
- Cooldown: No re-entry on same symbol within 6 bars after exit
- ATR Safety: ATR < 1.5 * ATR[20] (no extreme volatility)

Exit Logic:
- Stop Loss: 2x ATR (capped at 4%)
- Take Profit: 2:1 R:R (stop_pct * 2)
- Trailing Stop: Move to breakeven after 50% of target reached
- Time Stop: Close position if held > 60 bars

Unit System:
- 1 Unit: Base signal (volume > 1.5x AND return > 0.3%)
- 2 Units: Strong signal (volume > 2x AND return > 0.5%)
- 3 Units: Very strong (volume > 2.5x AND return > 0.7%)
- 4 Units: Extreme (volume > 3x AND return > 1%)
- Max 4 units per symbol, max 6 total portfolio
"""

from collections import deque
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


class ATRAdaptiveVolumeBreakoutStrategy:
    """ATR-Adaptive Volume Breakout Strategy with Unit-based Risk Management."""

    def __init__(
        self,
        symbols: list[str],
        # ATR parameters
        atr_window: int = 20,
        atr_breakout_mult: float = 1.0,
        atr_stop_mult: float = 2.0,
        max_stop_pct: float = 0.04,
        atr_acceleration_limit: float = 1.5,
        # Volume parameters
        volume_lookback: int = 20,
        volume_mult: float = 1.5,
        # Entry parameters
        min_bar_return: float = 0.003,
        # Exit parameters
        target_rr: float = 2.0,
        max_hold_bars: int = 60,
        cooldown_bars: int = 6,
        # Unit/Risk parameters
        max_units_single: int = 4,
        max_units_cluster: int = 6,
        max_units_total: int = 6,
        correlation_threshold: float = 0.7,
        corr_lookback_bars: int = 48,
        # Other
        history_max_len: int = 2000,
    ):
        if len(symbols) < 1:
            raise ValueError("symbols must contain at least one symbol")

        self.symbols = symbols

        # ATR parameters
        self.atr_window = max(1, int(atr_window))
        self.atr_breakout_mult = float(atr_breakout_mult)
        self.atr_stop_mult = float(atr_stop_mult)
        self.max_stop_pct = float(max_stop_pct)
        self.atr_acceleration_limit = float(atr_acceleration_limit)

        # Volume parameters
        self.volume_lookback = max(1, int(volume_lookback))
        self.volume_mult = float(volume_mult)

        # Entry parameters
        self.min_bar_return = float(min_bar_return)

        # Exit parameters
        self.target_rr = float(target_rr)
        self.max_hold_bars = int(max_hold_bars)
        self.cooldown_bars = int(cooldown_bars)

        # Unit/Risk parameters
        self.max_units_single = max(1, int(max_units_single))
        self.max_units_cluster = max(1, int(max_units_cluster))
        self.max_units_total = max(1, int(max_units_total))
        self.correlation_threshold = float(correlation_threshold)
        self.corr_lookback_bars = max(2, int(corr_lookback_bars))

        self.history_max_len = max(10, int(history_max_len))

        # Price/volume history: symbol -> DataFrame with columns [close, high, low, volume]
        self._bars: dict[str, pd.DataFrame] = {
            sym: pd.DataFrame(columns=["close", "high", "low", "volume"])
            for sym in self.symbols
        }

        # Per-symbol tracking state
        self._position_state: dict[str, dict] = {}
        # Structure: {symbol: {
        #   "entry_price": float,
        #   "entry_bar_idx": int,
        #   "stop_price": float,
        #   "target_price": float,
        #   "trailing_active": bool,
        #   "side": "LONG" or "SHORT",
        #   "units": int,
        # }}

        # Cooldown tracking: symbol -> bar index when last exited
        self._last_exit_bar: dict[str, int] = {}

        # Global bar counter for time-based logic
        self._bar_count: int = 0

        # Diagnostics
        self.last_reason: str = "init"
        self.last_action: dict = {}

    # ----------------------------------------------------------------
    # State Management
    # ----------------------------------------------------------------
    def _append_bar(self, symbol: str, ts: datetime, bar: dict) -> None:
        """Append a new bar to history."""
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
        # Avoid FutureWarning by only concatenating non-empty DataFrames
        if df.empty:
            df = row
        else:
            df = pd.concat([df, row]).sort_index().tail(self.history_max_len)
        df = df[~df.index.duplicated(keep="last")]
        self._bars[symbol] = df

    def _update_panel(self, state: MarketState) -> bool:
        """Update internal bar history from panel data."""
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

        return updated

    def _get_df(self, symbol: str) -> pd.DataFrame:
        """Get bar history DataFrame for a symbol."""
        return self._bars.setdefault(
            symbol, pd.DataFrame(columns=["close", "high", "low", "volume"])
        )

    def _has_warmup(self) -> bool:
        """Check if we have enough bars for all indicators."""
        required_bars = max(self.atr_window + 2, self.volume_lookback + 2)
        for sym in self.symbols:
            df = self._get_df(sym)
            if len(df) < required_bars:
                self.last_reason = f"not_enough_bars:{sym}:{len(df)}"
                return False
        return True

    # ----------------------------------------------------------------
    # Indicators
    # ----------------------------------------------------------------
    def _atr(self, symbol: str) -> Optional[float]:
        """Calculate ATR for a symbol."""
        df = self._get_df(symbol)
        if len(df) < self.atr_window + 1:
            return None

        d = df.tail(self.atr_window + 1).copy()
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

    def _atr_from_n_bars_ago(self, symbol: str, n_bars: int = 20) -> Optional[float]:
        """Calculate ATR from n bars ago (for acceleration check)."""
        df = self._get_df(symbol)
        required = self.atr_window + 1 + n_bars
        if len(df) < required:
            return None

        d = df.iloc[-(self.atr_window + 1 + n_bars) : -n_bars].copy()
        if len(d) < self.atr_window + 1:
            return None

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

    def _volume_sma(self, symbol: str) -> Optional[float]:
        """Calculate volume SMA."""
        df = self._get_df(symbol)
        if len(df) < self.volume_lookback:
            return None
        vol = df["volume"].tail(self.volume_lookback)
        return float(vol.mean())

    def _bar_return(self, symbol: str) -> Optional[float]:
        """Calculate return of the current bar (close vs previous close)."""
        df = self._get_df(symbol)
        if len(df) < 2:
            return None
        prev_close = float(df["close"].iloc[-2])
        curr_close = float(df["close"].iloc[-1])
        if prev_close <= 0:
            return None
        return (curr_close - prev_close) / prev_close

    def _current_volume(self, symbol: str) -> Optional[float]:
        """Get current bar volume."""
        df = self._get_df(symbol)
        if df.empty:
            return None
        return float(df["volume"].iloc[-1])

    def _current_close(self, symbol: str) -> Optional[float]:
        """Get current close price."""
        df = self._get_df(symbol)
        if df.empty:
            return None
        return float(df["close"].iloc[-1])

    def _prev_close(self, symbol: str) -> Optional[float]:
        """Get previous close price."""
        df = self._get_df(symbol)
        if len(df) < 2:
            return None
        return float(df["close"].iloc[-2])

    def _correlation(self) -> pd.DataFrame:
        """Calculate correlation matrix across symbols."""
        aligned: dict[str, pd.Series] = {}
        for sym in self.symbols:
            df = self._get_df(sym)
            if len(df) > 2:
                aligned[sym] = df["close"].tail(self.corr_lookback_bars)

        if len(aligned) < 2:
            return pd.DataFrame()

        returns = pd.DataFrame(aligned).pct_change().dropna()
        return returns.corr().fillna(0.0)

    # ----------------------------------------------------------------
    # Entry Logic
    # ----------------------------------------------------------------
    def _check_entry_conditions(self, symbol: str) -> Optional[dict]:
        """
        Check if entry conditions are met for a symbol.

        Returns:
            dict with entry details if conditions met, None otherwise
        """
        # Get indicators
        atr = self._atr(symbol)
        atr_old = self._atr_from_n_bars_ago(symbol, 20)
        vol_sma = self._volume_sma(symbol)
        curr_vol = self._current_volume(symbol)
        bar_ret = self._bar_return(symbol)
        curr_close = self._current_close(symbol)
        prev_close = self._prev_close(symbol)

        if any(
            x is None
            for x in [atr, vol_sma, curr_vol, bar_ret, curr_close, prev_close]
        ):
            return None

        # Check cooldown
        if symbol in self._last_exit_bar:
            bars_since_exit = self._bar_count - self._last_exit_bar[symbol]
            if bars_since_exit < self.cooldown_bars:
                return None

        # Check ATR acceleration (no extreme volatility)
        if atr_old is not None and atr_old > 0:
            if atr / atr_old > self.atr_acceleration_limit:
                return None

        # Volume breakout check
        vol_ratio = curr_vol / vol_sma if vol_sma > 0 else 0
        if vol_ratio < self.volume_mult:
            return None

        # Determine direction and check ATR range break
        side = None
        if bar_ret > self.min_bar_return:
            # Potential LONG
            atr_break_threshold = prev_close + self.atr_breakout_mult * atr
            if curr_close > atr_break_threshold:
                side = "LONG"
        elif bar_ret < -self.min_bar_return:
            # Potential SHORT
            atr_break_threshold = prev_close - self.atr_breakout_mult * atr
            if curr_close < atr_break_threshold:
                side = "SHORT"

        if side is None:
            return None

        # Calculate units based on signal strength
        units = self._calculate_units(vol_ratio, abs(bar_ret))

        # Calculate stop and target
        stop_pct = min(self.atr_stop_mult * (atr / curr_close), self.max_stop_pct)
        target_pct = stop_pct * self.target_rr

        if side == "LONG":
            stop_price = curr_close * (1 - stop_pct)
            target_price = curr_close * (1 + target_pct)
        else:
            stop_price = curr_close * (1 + stop_pct)
            target_price = curr_close * (1 - target_pct)

        return {
            "symbol": symbol,
            "side": side,
            "entry_price": curr_close,
            "stop_price": stop_price,
            "target_price": target_price,
            "stop_pct": stop_pct,
            "target_pct": target_pct,
            "units": units,
            "vol_ratio": vol_ratio,
            "bar_return": bar_ret,
        }

    def _calculate_units(self, vol_ratio: float, abs_return: float) -> int:
        """
        Calculate number of units based on signal strength.

        Unit allocation:
        - 1 Unit: vol > 1.5x AND return > 0.3%
        - 2 Units: vol > 2x AND return > 0.5%
        - 3 Units: vol > 2.5x AND return > 0.7%
        - 4 Units: vol > 3x AND return > 1%
        """
        if vol_ratio >= 3.0 and abs_return >= 0.01:
            return 4
        elif vol_ratio >= 2.5 and abs_return >= 0.007:
            return 3
        elif vol_ratio >= 2.0 and abs_return >= 0.005:
            return 2
        else:
            return 1

    # ----------------------------------------------------------------
    # Exit Logic
    # ----------------------------------------------------------------
    def _check_exit_conditions(
        self, symbol: str, position: dict, state: MarketState
    ) -> Optional[str]:
        """
        Check if exit conditions are met for an open position.

        Returns:
            Exit reason string if should exit, None otherwise
        """
        pos_state = self._position_state.get(symbol)
        if pos_state is None:
            return None

        curr_close = self._current_close(symbol)
        if curr_close is None:
            return None

        side = pos_state["side"]
        entry_price = pos_state["entry_price"]
        stop_price = pos_state["stop_price"]
        target_price = pos_state["target_price"]
        entry_bar = pos_state["entry_bar_idx"]
        trailing_active = pos_state.get("trailing_active", False)

        # Time stop
        bars_held = self._bar_count - entry_bar
        if bars_held >= self.max_hold_bars:
            return "time_stop"

        if side == "LONG":
            # Stop loss
            if curr_close <= stop_price:
                return "stop_loss"
            # Take profit
            if curr_close >= target_price:
                return "take_profit"

            # Trailing stop logic: activate at 50% of target
            halfway = entry_price + (target_price - entry_price) * 0.5
            if curr_close >= halfway and not trailing_active:
                # Move stop to breakeven
                pos_state["stop_price"] = entry_price
                pos_state["trailing_active"] = True

        else:  # SHORT
            # Stop loss
            if curr_close >= stop_price:
                return "stop_loss"
            # Take profit
            if curr_close <= target_price:
                return "take_profit"

            # Trailing stop logic
            halfway = entry_price - (entry_price - target_price) * 0.5
            if curr_close <= halfway and not trailing_active:
                pos_state["stop_price"] = entry_price
                pos_state["trailing_active"] = True

        return None

    # ----------------------------------------------------------------
    # Risk Management
    # ----------------------------------------------------------------
    def _cluster_allows(
        self,
        symbol: str,
        side: str,
        units: int,
        current_positions: dict[str, dict],
        corr: pd.DataFrame,
    ) -> bool:
        """
        Check if adding position respects cluster/unit limits.
        """
        # Count current units
        total_units = sum(
            self._position_state.get(s, {}).get("units", 0)
            for s in current_positions
            if current_positions.get(s, {}).get("side")
        )

        # Check total portfolio limit
        if total_units + units > self.max_units_total:
            return False

        # Check single symbol limit
        if units > self.max_units_single:
            return False

        # Check correlation cluster limit
        if corr.empty:
            return True

        cluster_units = units
        for other_sym, pos_state in self._position_state.items():
            if other_sym == symbol:
                continue
            if pos_state.get("side") != side:
                continue

            # Check if correlated
            if symbol in corr.columns and other_sym in corr.index:
                correlation = abs(float(corr.loc[symbol, other_sym]))
                if correlation >= self.correlation_threshold:
                    cluster_units += pos_state.get("units", 0)

        if cluster_units > self.max_units_cluster:
            return False

        return True

    def _calculate_weight(self, units: int) -> float:
        """Convert units to portfolio weight."""
        base = 1.0 / self.max_units_total
        return float(np.clip(units * base, 0.0, 1.0))

    # ----------------------------------------------------------------
    # Main Order Generation
    # ----------------------------------------------------------------
    def generate_order(self, state: MarketState) -> PortfolioOrder | None:
        """Generate portfolio orders based on entry/exit signals."""
        if state.symbol is None:
            return None
        if state.panel is None:
            return None

        # Update internal state
        self._update_panel(state)
        self._bar_count += 1

        if not self._has_warmup():
            return None

        positions = state.positions or {}
        orders: dict[str, Order] = {}

        # Step 1: Check exits for existing positions
        for symbol in list(self._position_state.keys()):
            pos = positions.get(symbol, {})
            if not pos or not pos.get("side"):
                # Position was closed externally, clean up
                if symbol in self._position_state:
                    del self._position_state[symbol]
                continue

            exit_reason = self._check_exit_conditions(symbol, pos, state)
            if exit_reason:
                qty = float(pos.get("qty", 0.0) or 0.0)
                if qty > 0:
                    side_order = (
                        Side.SELL
                        if self._position_state[symbol]["side"] == "LONG"
                        else Side.BUY
                    )
                    orders[symbol] = Order(
                        side=side_order, quantity=qty, order_type=OrderType.MARKET
                    )
                    self._last_exit_bar[symbol] = self._bar_count
                    self.last_reason = f"exit_{symbol}_{exit_reason}"

                # Remove from position state
                del self._position_state[symbol]

        # Step 2: Check entries for symbols without positions
        corr = self._correlation()
        entry_candidates: list[dict] = []

        for symbol in self.symbols:
            # Skip if already have position
            if symbol in self._position_state:
                continue

            pos = positions.get(symbol, {})
            if pos and pos.get("side"):
                continue

            entry = self._check_entry_conditions(symbol)
            if entry:
                entry_candidates.append(entry)

        # Sort by signal strength (vol_ratio * abs_return)
        entry_candidates.sort(
            key=lambda x: x["vol_ratio"] * abs(x["bar_return"]), reverse=True
        )

        # Apply entries respecting unit limits
        for entry in entry_candidates:
            symbol = entry["symbol"]
            units = min(entry["units"], self.max_units_single)

            if not self._cluster_allows(symbol, entry["side"], units, positions, corr):
                continue

            # Create entry order
            order_side = Side.BUY if entry["side"] == "LONG" else Side.SELL
            orders[symbol] = Order(
                side=order_side,
                quantity=0.0,  # Let runner calculate from weight
                order_type=OrderType.MARKET,
                weight=self._calculate_weight(units),
            )

            # Track position state
            self._position_state[symbol] = {
                "entry_price": entry["entry_price"],
                "entry_bar_idx": self._bar_count,
                "stop_price": entry["stop_price"],
                "target_price": entry["target_price"],
                "trailing_active": False,
                "side": entry["side"],
                "units": units,
            }

            self.last_reason = f"entry_{symbol}_{entry['side']}"

        # Update diagnostics
        self.last_action = {
            "ts": state.timestamp.isoformat() if state.timestamp else None,
            "bar_count": self._bar_count,
            "active_positions": list(self._position_state.keys()),
            "orders": {k: v.side.value for k, v in orders.items()},
        }

        if not orders:
            return None

        return PortfolioOrder(orders)

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(symbols={len(self.symbols)}, "
            f"atr_window={self.atr_window}, volume_mult={self.volume_mult})"
        )
