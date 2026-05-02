"""
ATR Volume Unit Risk Portfolio Strategy V3 - Volatility Breakout

Complete redesign from V1 (Momentum) and V2 (Mean Reversion) that both failed.

Core Hypothesis:
High-conviction breakouts with institutional volume in trend direction have follow-through.

Triple Confirmation Required (ALL must be true):
1. Volatility Breakout: (high - low) / ATR > 1.5 (~5% of bars)
2. Volume Spike: volume / volume_MA(20) > 2.0 (~10% of bars)
3. Trend Alignment: close > SMA(50) for long, < for short
4. Bar Direction: close > open for bullish breakout

Key Differences from V1/V2:
| V1 (Failed) | V2 (Failed) | V3 (New) |
|-------------|-------------|----------|
| Momentum    | Mean Reversion | Breakout Continuation |
| 600-850/month | 5,800/month | 30-100/month target |
| Volume > median | Volume < avg | Volume SPIKE (> 2x) |
| No trend filter | No trend filter | SMA trend alignment |
| Fixed target | Fixed target | TRAILING STOP |

Mathematical Foundation:
- Combined probability of all conditions: 5% x 10% x 50% = 0.25% of bars
- With 4 symbols, 288 bars/day: ~3 signals/day
- 4-hour cooldown per symbol prevents overtrading

Risk Management (2% Rule):
- Initial stop: ATR * 2.0
- Trailing stop: highest/lowest since entry - ATR * 2.5
- Break-even stop: Move stop to entry after 1.5x ATR profit
- Time stop: Exit after 96 bars (8 hours)
- Unit-based position sizing with correlation limits
"""

from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


class ATRVolumeUnitRiskMultiStrategyV3:
    """
    ATR + Volume Spike Volatility Breakout Portfolio Strategy V3.

    Entry Conditions (LONG - Triple Confirmation):
    1. Volatility Breakout: (high - low) / ATR > breakout_threshold
    2. Volume Spike: volume / volume_MA > volume_spike_threshold
    3. Trend Alignment: close > SMA(trend_period)
    4. Bar Direction: close > open (bullish)
    5. No existing long position
    6. Unit limits satisfied
    7. Not on entry cooldown (4 hours since last entry)

    Entry Conditions (SHORT - Triple Confirmation):
    Same but inverted:
    - close < SMA (downtrend)
    - close < open (bearish)

    Exit Conditions:
    1. Initial stop loss: entry - ATR * atr_stop_multiplier
    2. Trailing stop: highest_since_entry - ATR * trailing_atr_multiplier
    3. Break-even: Move stop to entry + small buffer after profit
    4. Time stop: Exit after max_hold_bars (96 = 8 hours)

    Risk Management:
    - 2% max loss per trade
    - 4 units max per symbol
    - 6 units max per correlated cluster
    - 6 units max total portfolio
    """

    def __init__(
        self,
        symbols: list[str],
        # V3 Core Signal Parameters
        breakout_threshold: float = 1.5,
        volume_spike_threshold: float = 2.0,
        trend_period: int = 50,
        volume_lookback: int = 20,
        # Entry Cooldown (CRITICAL for reducing overtrading)
        min_bars_between_entries: int = 48,  # 4 hours
        # Risk Parameters
        atr_window: int = 14,
        atr_stop_multiplier: float = 2.0,
        trailing_atr_multiplier: float = 2.5,
        breakeven_trigger_atr: float = 1.5,
        max_hold_bars: int = 96,  # 8 hours
        # Selection Parameters
        top_n: int = 2,
        bottom_n: int = 1,
        # Correlation/Unit Parameters
        correlation_threshold: float = 0.7,
        corr_lookback_bars: int = 48,
        max_units_single: int = 4,
        max_units_corr_cluster: int = 6,
        max_units_total: int = 6,
        history_max_len: int = 2000,
    ):
        """
        Initialize the ATR Volume Unit Risk Portfolio Strategy V3.

        Args:
            symbols: List of trading symbols (min 2)
            breakout_threshold: Range/ATR ratio for breakout detection (default 1.5)
            volume_spike_threshold: Volume/MA ratio for spike detection (default 2.0)
            trend_period: SMA period for trend alignment (default 50)
            volume_lookback: Bars for volume MA calculation (default 20)
            min_bars_between_entries: Cooldown between entries per symbol (default 48 = 4h)
            atr_window: ATR calculation window (default 14)
            atr_stop_multiplier: Initial stop distance in ATR (default 2.0)
            trailing_atr_multiplier: Trailing stop distance in ATR (default 2.5)
            breakeven_trigger_atr: Move to breakeven after this profit in ATR (default 1.5)
            max_hold_bars: Maximum bars to hold a position (default 96 = 8h)
            top_n: Maximum long positions (default 2)
            bottom_n: Maximum short positions (default 1)
            correlation_threshold: Correlation threshold for clustering (default 0.7)
            corr_lookback_bars: Rolling correlation lookback (default 48)
            max_units_single: Max units per symbol (default 4)
            max_units_corr_cluster: Max units for correlated cluster (default 6)
            max_units_total: Max total portfolio units (default 6)
            history_max_len: Max bars to retain in history (default 2000)
        """
        if len(symbols) < 2:
            raise ValueError("symbols must contain at least two symbols")
        if top_n < 0 or bottom_n < 0 or top_n + bottom_n == 0:
            raise ValueError("top_n and bottom_n must allow at least one side position")

        self.symbols = symbols

        # V3 Core Parameters
        self.breakout_threshold = float(breakout_threshold)
        self.volume_spike_threshold = float(volume_spike_threshold)
        self.trend_period = max(2, int(trend_period))
        self.volume_lookback = max(2, int(volume_lookback))
        self.min_bars_between_entries = max(1, int(min_bars_between_entries))

        # Risk Parameters
        self.atr_window = max(1, int(atr_window))
        self.atr_stop_multiplier = float(atr_stop_multiplier)
        self.trailing_atr_multiplier = float(trailing_atr_multiplier)
        self.breakeven_trigger_atr = float(breakeven_trigger_atr)
        self.max_hold_bars = max(1, int(max_hold_bars))

        # Selection Parameters
        self.top_n = top_n
        self.bottom_n = bottom_n

        # Correlation/Unit Parameters
        self.correlation_threshold = float(correlation_threshold)
        self.corr_lookback_bars = max(2, int(corr_lookback_bars))
        self.max_units_single = max(1, int(max_units_single))
        self.max_units_corr_cluster = max(1, int(max_units_corr_cluster))
        self.max_units_total = max(1, int(max_units_total))
        self.history_max_len = max(10, int(history_max_len))

        # Price history: symbol -> DataFrame with OHLCV columns
        self._bars: dict[str, pd.DataFrame] = {
            sym: pd.DataFrame(columns=["open", "close", "high", "low", "volume"])
            for sym in self.symbols
        }

        # Global bar counter
        self._bar_count: int = 0

        # Last entry bar per symbol (for cooldown)
        self._last_entry_bar: dict[str, int] = {}

        # Position tracking for trailing stop and break-even
        # {symbol: {"entry_bar": int, "entry_price": float, "side": str,
        #           "high_since": float, "low_since": float, "breakeven_activated": bool}}
        self._position_tracking: dict[str, dict] = {}

        # Diagnostics and state
        self.last_reason: str = "init"
        self.last_action: dict = {
            "ts": None,
            "long_targets": [],
            "short_targets": [],
            "close_symbols": [],
            "skipped": {},
            "orders": {},
        }

    # ========================== State Management ==========================

    def _append_bar(self, symbol: str, ts: datetime, bar: dict) -> None:
        """Append a new bar to the price history."""
        df = self._bars.setdefault(
            symbol, pd.DataFrame(columns=["open", "close", "high", "low", "volume"])
        )

        open_val = float(bar["open"])
        close_val = float(bar["close"])
        high_val = float(bar["high"])
        low_val = float(bar["low"])
        volume_val = float(bar.get("volume", 0.0))

        row = pd.DataFrame(
            {
                "open": [open_val],
                "close": [close_val],
                "high": [high_val],
                "low": [low_val],
                "volume": [volume_val],
            },
            index=[ts],
        )

        if df.empty:
            df = row
        else:
            df = pd.concat([df, row])
        df = df.sort_index().tail(self.history_max_len)
        df = df[~df.index.duplicated(keep="last")]
        self._bars[symbol] = df

    def _update_panel(self, state: MarketState) -> bool:
        """Update internal state from MarketState panel."""
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
            open_price = bar.get("open")
            close = bar.get("close")
            high = bar.get("high")
            low = bar.get("low")
            if open_price is None or close is None or high is None or low is None:
                continue
            close = float(close)
            if close <= 0:
                continue

            self._append_bar(
                sym,
                ts,
                {
                    "open": float(open_price),
                    "close": close,
                    "high": float(high),
                    "low": float(low),
                    "volume": float(bar.get("volume", 0.0)),
                },
            )

            # Update position tracking for trailing stop
            if sym in self._position_tracking:
                track = self._position_tracking[sym]
                track["high_since"] = max(track["high_since"], float(high))
                track["low_since"] = min(track["low_since"], float(low))

            updated = True

        if updated:
            self._bar_count += 1

        return updated

    def _get_df(self, symbol: str) -> pd.DataFrame:
        """Get price DataFrame for a symbol."""
        return self._bars.setdefault(
            symbol, pd.DataFrame(columns=["open", "close", "high", "low", "volume"])
        )

    def _has_warmup(self, now: datetime) -> bool:
        """Check if enough historical data exists for calculations."""
        min_bars = max(self.trend_period, self.atr_window + 2, self.volume_lookback)
        for sym in self.symbols:
            df = self._get_df(sym)
            if len(df) < min_bars:
                self.last_reason = f"not_enough_bars:{sym}:{len(df)}"
                return False
            if float(df["close"].iloc[-1]) <= 0:
                self.last_reason = f"invalid_price:{sym}"
                return False
        return True

    # ========================== Indicators ==========================

    def _atr(self, symbol: str) -> Optional[float]:
        """
        Calculate ATR using True Range.

        True Range = max(high-low, |high-prev_close|, |low-prev_close|)
        ATR = rolling mean of True Range over atr_window periods.
        """
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
        atr_value = float(tr.rolling(self.atr_window).mean().iloc[-1])
        return atr_value if not pd.isna(atr_value) else None

    def _sma(self, symbol: str, period: int) -> Optional[float]:
        """Calculate Simple Moving Average of close prices."""
        df = self._get_df(symbol)
        if len(df) < period:
            return None
        sma_value = float(df["close"].iloc[-period:].mean())
        return sma_value

    def _volume_ma(self, symbol: str) -> Optional[float]:
        """Calculate volume moving average."""
        df = self._get_df(symbol)
        if len(df) < self.volume_lookback:
            return None
        vol_ma = float(df["volume"].iloc[-self.volume_lookback:].mean())
        return vol_ma if vol_ma > 0 else None

    # ========================== V3 Signal Detection ==========================

    def _is_volatility_breakout(self, symbol: str) -> tuple[bool, float]:
        """
        Detect if current bar is a volatility breakout.

        Returns:
            (is_breakout, breakout_ratio)
            breakout_ratio = (high - low) / ATR
        """
        df = self._get_df(symbol)
        if len(df) < 2:
            return False, 0.0

        current_high = float(df["high"].iloc[-1])
        current_low = float(df["low"].iloc[-1])
        current_range = current_high - current_low

        atr = self._atr(symbol)
        if atr is None or atr <= 0:
            return False, 0.0

        breakout_ratio = current_range / atr
        is_breakout = breakout_ratio > self.breakout_threshold

        return is_breakout, breakout_ratio

    def _is_volume_spike(self, symbol: str) -> tuple[bool, float]:
        """
        Detect if current volume is a spike.

        Returns:
            (is_spike, volume_ratio)
            volume_ratio = current_volume / volume_MA
        """
        df = self._get_df(symbol)
        if len(df) < self.volume_lookback:
            return False, 0.0

        current_volume = float(df["volume"].iloc[-1])
        vol_ma = self._volume_ma(symbol)

        if vol_ma is None or vol_ma <= 0:
            return False, 0.0

        volume_ratio = current_volume / vol_ma
        is_spike = volume_ratio > self.volume_spike_threshold

        return is_spike, volume_ratio

    def _get_trend_direction(self, symbol: str) -> str:
        """
        Determine trend direction using SMA.

        Returns:
            "UP" if close > SMA (uptrend)
            "DOWN" if close < SMA (downtrend)
            "NEUTRAL" if insufficient data or close == SMA
        """
        df = self._get_df(symbol)
        if len(df) < self.trend_period:
            return "NEUTRAL"

        sma = self._sma(symbol, self.trend_period)
        if sma is None:
            return "NEUTRAL"

        current_price = float(df["close"].iloc[-1])

        # Small buffer to avoid whipsaw on exact SMA
        buffer = 0.005 * sma  # 0.5%

        if current_price > sma + buffer:
            return "UP"
        elif current_price < sma - buffer:
            return "DOWN"
        else:
            return "NEUTRAL"

    def _get_bar_direction(self, symbol: str) -> str:
        """
        Determine current bar direction.

        Returns:
            "UP" if close > open (bullish bar)
            "DOWN" if close < open (bearish bar)
            "NEUTRAL" if close == open
        """
        df = self._get_df(symbol)
        if len(df) < 1:
            return "NEUTRAL"

        current_open = float(df["open"].iloc[-1])
        current_close = float(df["close"].iloc[-1])

        if current_close > current_open:
            return "UP"
        elif current_close < current_open:
            return "DOWN"
        else:
            return "NEUTRAL"

    def _is_on_entry_cooldown(self, symbol: str) -> bool:
        """
        Check if symbol is on entry cooldown.

        Returns True if last entry was less than min_bars_between_entries ago.
        """
        if symbol not in self._last_entry_bar:
            return False
        bars_since = self._bar_count - self._last_entry_bar[symbol]
        return bars_since < self.min_bars_between_entries

    def _generate_entry_signal(self, symbol: str) -> Optional[str]:
        """
        Generate entry signal based on V3 Triple Confirmation logic.

        Returns:
            "LONG" if all long conditions met
            "SHORT" if all short conditions met
            None if no signal
        """
        # Check cooldown first (most important filter)
        if self._is_on_entry_cooldown(symbol):
            return None

        # 1. Volatility breakout
        is_breakout, breakout_ratio = self._is_volatility_breakout(symbol)
        if not is_breakout:
            return None

        # 2. Volume spike
        is_spike, volume_ratio = self._is_volume_spike(symbol)
        if not is_spike:
            return None

        # 3. Trend alignment
        trend = self._get_trend_direction(symbol)
        if trend == "NEUTRAL":
            return None

        # 4. Bar direction
        bar_dir = self._get_bar_direction(symbol)
        if bar_dir == "NEUTRAL":
            return None

        # Combined logic
        if bar_dir == "UP" and trend == "UP":
            return "LONG"
        elif bar_dir == "DOWN" and trend == "DOWN":
            return "SHORT"

        return None

    def _select_units(self, breakout_ratio: float, volume_ratio: float) -> int:
        """
        Allocate units based on combined signal strength.

        signal_strength = (breakout_ratio - 1.0) + (volume_ratio - 1.0)
        """
        signal_strength = (breakout_ratio - 1.0) + (volume_ratio - 1.0)

        if signal_strength <= 1.0:
            return 1  # Marginal signal
        elif signal_strength <= 2.0:
            return 2  # Good signal
        elif signal_strength <= 3.0:
            return 3  # Strong signal
        else:
            return min(4, self.max_units_single)  # Extreme signal (capped)

    # ========================== Correlation Management ==========================

    def _correlation(self) -> pd.DataFrame:
        """
        Calculate rolling correlation matrix of returns.

        Uses corr_lookback_bars of price data to compute correlations.
        """
        aligned: dict[str, pd.Series] = {}
        for sym in self.symbols:
            df = self._get_df(sym)
            if len(df) > 2:
                aligned[sym] = df["close"].tail(self.corr_lookback_bars)

        if len(aligned) < 2:
            return pd.DataFrame()

        returns = pd.DataFrame(aligned).pct_change().dropna()
        return returns.corr().fillna(0.0)

    def _cluster_allows(
        self, symbol: str, side: str, selected: list[dict], corr: pd.DataFrame
    ) -> bool:
        """
        Check if adding a position violates correlation cluster limits.
        """
        if not selected:
            return True

        same_side = [x for x in selected if x["side"] == side]
        if not same_side:
            return True

        if corr.empty:
            return sum(x["units"] for x in same_side) < self.max_units_corr_cluster

        # Check if symbol is correlated with any existing position
        for sel in same_side:
            a = symbol
            b = sel["symbol"]
            if (
                a in corr.columns
                and b in corr.index
                and abs(float(corr.loc[a, b])) >= self.correlation_threshold
            ):
                # In same cluster - check cluster limit
                if (
                    sum(x["units"] for x in same_side) + 1
                    > self.max_units_corr_cluster
                ):
                    return False
                return True

        # Not correlated - check total exposure limit
        if sum(x["units"] for x in same_side) + 1 > self.max_units_total:
            return False

        return True

    # ========================== Exit Management ==========================

    def _get_trailing_stop(self, symbol: str) -> Optional[float]:
        """
        Calculate trailing stop price for a position.

        For LONG: highest_since_entry - (ATR * trailing_atr_multiplier)
        For SHORT: lowest_since_entry + (ATR * trailing_atr_multiplier)
        """
        track = self._position_tracking.get(symbol)
        if not track:
            return None

        atr = self._atr(symbol)
        if atr is None:
            return None

        side = track["side"]
        if side == "LONG":
            return track["high_since"] - (atr * self.trailing_atr_multiplier)
        else:  # SHORT
            return track["low_since"] + (atr * self.trailing_atr_multiplier)

    def _should_move_to_breakeven(self, symbol: str, current_price: float) -> bool:
        """
        Check if position should move stop to breakeven.

        Returns True if profit exceeds breakeven_trigger_atr * ATR.
        """
        track = self._position_tracking.get(symbol)
        if not track:
            return False

        if track.get("breakeven_activated", False):
            return False  # Already at breakeven

        atr = self._atr(symbol)
        if atr is None:
            return False

        entry_price = track["entry_price"]
        side = track["side"]

        if side == "LONG":
            profit = current_price - entry_price
            return profit >= atr * self.breakeven_trigger_atr
        else:  # SHORT
            profit = entry_price - current_price
            return profit >= atr * self.breakeven_trigger_atr

    def _get_breakeven_stop(self, symbol: str) -> Optional[float]:
        """
        Get breakeven stop price.

        For LONG: entry_price + small buffer (0.25 * ATR)
        For SHORT: entry_price - small buffer (0.25 * ATR)
        """
        track = self._position_tracking.get(symbol)
        if not track:
            return None

        atr = self._atr(symbol)
        if atr is None:
            return None

        entry_price = track["entry_price"]
        buffer = atr * 0.25

        side = track["side"]
        if side == "LONG":
            return entry_price + buffer
        else:  # SHORT
            return entry_price - buffer

    def _check_time_stop(self, symbol: str) -> bool:
        """
        Check if position has exceeded max_hold_bars.

        Returns True if position should be exited due to time stop.
        """
        track = self._position_tracking.get(symbol)
        if not track:
            return False

        entry_bar = track.get("entry_bar", self._bar_count)
        bars_held = self._bar_count - entry_bar

        return bars_held >= self.max_hold_bars

    def _risk_exit_orders(self, state: MarketState) -> dict[str, Order]:
        """
        Generate exit orders for positions hitting stop or time stop.

        V3 Exit Priority:
        1. Initial stop loss (ATR-based)
        2. Break-even stop (after profit threshold)
        3. Trailing stop (dynamic)
        4. Time stop (max_hold_bars exceeded)
        """
        orders: dict[str, Order] = {}
        if not state.positions:
            return orders

        for sym, pos in state.positions.items():
            if not pos:
                continue
            side = pos.get("side")
            qty = float(pos.get("qty", 0.0) or 0.0)
            entry = float(pos.get("entry_price", 0.0) or 0.0)
            if qty <= 0 or entry <= 0:
                continue

            # Initialize position tracking if new position
            if sym not in self._position_tracking:
                df = self._get_df(sym)
                if df.empty:
                    continue
                current_high = float(df["high"].iloc[-1])
                current_low = float(df["low"].iloc[-1])
                self._position_tracking[sym] = {
                    "entry_bar": self._bar_count,
                    "entry_price": entry,
                    "side": side,
                    "high_since": current_high,
                    "low_since": current_low,
                    "breakeven_activated": False,
                }

            track = self._position_tracking[sym]

            # Get current price
            df = self._get_df(sym)
            now_price = float(df["close"].iloc[-1]) if not df.empty else None
            if now_price is None:
                if state.close is not None:
                    now_price = float(state.close)
                else:
                    continue

            atr = self._atr(sym)
            if atr is None:
                continue

            should_exit = False
            exit_reason = ""

            # Calculate stop levels
            initial_stop_pct = max(0.02, (atr * self.atr_stop_multiplier) / entry)

            if side == "LONG":
                # Initial stop
                initial_stop = entry * (1 - initial_stop_pct)

                # Check for breakeven activation
                if self._should_move_to_breakeven(sym, now_price):
                    track["breakeven_activated"] = True
                    self._position_tracking[sym] = track

                # Determine active stop
                if track.get("breakeven_activated", False):
                    breakeven_stop = self._get_breakeven_stop(sym)
                    trailing_stop = self._get_trailing_stop(sym)
                    if breakeven_stop and trailing_stop:
                        active_stop = max(breakeven_stop, trailing_stop)
                    else:
                        active_stop = breakeven_stop or trailing_stop or initial_stop
                else:
                    trailing_stop = self._get_trailing_stop(sym)
                    if trailing_stop and trailing_stop > initial_stop:
                        active_stop = trailing_stop
                    else:
                        active_stop = initial_stop

                if now_price <= active_stop:
                    should_exit = True
                    exit_reason = "stop_loss" if now_price <= initial_stop else "trailing_stop"

            elif side == "SHORT":
                # Initial stop
                initial_stop = entry * (1 + initial_stop_pct)

                # Check for breakeven activation
                if self._should_move_to_breakeven(sym, now_price):
                    track["breakeven_activated"] = True
                    self._position_tracking[sym] = track

                # Determine active stop
                if track.get("breakeven_activated", False):
                    breakeven_stop = self._get_breakeven_stop(sym)
                    trailing_stop = self._get_trailing_stop(sym)
                    if breakeven_stop and trailing_stop:
                        active_stop = min(breakeven_stop, trailing_stop)
                    else:
                        active_stop = breakeven_stop or trailing_stop or initial_stop
                else:
                    trailing_stop = self._get_trailing_stop(sym)
                    if trailing_stop and trailing_stop < initial_stop:
                        active_stop = trailing_stop
                    else:
                        active_stop = initial_stop

                if now_price >= active_stop:
                    should_exit = True
                    exit_reason = "stop_loss" if now_price >= initial_stop else "trailing_stop"

            # Check time stop
            if not should_exit and self._check_time_stop(sym):
                should_exit = True
                exit_reason = "time_stop"

            if should_exit:
                exit_side = Side.SELL if side == "LONG" else Side.BUY
                orders[sym] = Order(
                    side=exit_side, quantity=qty, order_type=OrderType.MARKET
                )
                self.last_reason = f"exit_{side.lower()}_{exit_reason}"
                # Clear position tracking
                self._position_tracking.pop(sym, None)

        return orders

    # ========================== Candidate Building ==========================

    def _build_candidates(self, now: datetime) -> tuple[list[dict], list[dict]]:
        """
        Build ranked lists of long and short candidates.

        V3 Breakout Logic (Triple Confirmation):
        - LONG: breakout + volume spike + uptrend + bullish bar
        - SHORT: breakout + volume spike + downtrend + bearish bar
        """
        skipped: dict[str, str] = {}
        long_cands: list[dict] = []
        short_cands: list[dict] = []

        for sym in self.symbols:
            # Check cooldown first
            if self._is_on_entry_cooldown(sym):
                skipped[sym] = f"on_cooldown (need {self.min_bars_between_entries} bars)"
                continue

            # 1. Volatility breakout
            is_breakout, breakout_ratio = self._is_volatility_breakout(sym)
            if not is_breakout:
                skipped[sym] = f"no_breakout (ratio={breakout_ratio:.2f})"
                continue

            # 2. Volume spike
            is_spike, volume_ratio = self._is_volume_spike(sym)
            if not is_spike:
                skipped[sym] = f"no_volume_spike (ratio={volume_ratio:.2f})"
                continue

            # 3. Trend alignment
            trend = self._get_trend_direction(sym)
            if trend == "NEUTRAL":
                skipped[sym] = "neutral_trend"
                continue

            # 4. Bar direction
            bar_dir = self._get_bar_direction(sym)
            if bar_dir == "NEUTRAL":
                skipped[sym] = "neutral_bar"
                continue

            # Calculate units based on signal strength
            units = self._select_units(breakout_ratio, volume_ratio)
            units = min(self.max_units_single, units)

            # Combined logic
            if bar_dir == "UP" and trend == "UP":
                long_cands.append({
                    "symbol": sym,
                    "side": "LONG",
                    "breakout_ratio": breakout_ratio,
                    "volume_ratio": volume_ratio,
                    "units": units,
                    "signal_strength": (breakout_ratio - 1.0) + (volume_ratio - 1.0),
                })
            elif bar_dir == "DOWN" and trend == "DOWN":
                short_cands.append({
                    "symbol": sym,
                    "side": "SHORT",
                    "breakout_ratio": breakout_ratio,
                    "volume_ratio": volume_ratio,
                    "units": units,
                    "signal_strength": (breakout_ratio - 1.0) + (volume_ratio - 1.0),
                })
            else:
                skipped[sym] = f"direction_mismatch (bar={bar_dir}, trend={trend})"

        # Sort by signal strength descending (strongest signals first)
        long_cands.sort(key=lambda x: x["signal_strength"], reverse=True)
        short_cands.sort(key=lambda x: x["signal_strength"], reverse=True)

        corr = self._correlation()

        # Select top N longs within unit limits
        selected_long: list[dict] = []
        for row in long_cands[: self.top_n * 2]:
            if len(selected_long) >= self.top_n:
                break
            if sum(x["units"] for x in selected_long) >= self.max_units_total:
                break
            if not self._cluster_allows(row["symbol"], "LONG", selected_long, corr):
                skipped[row["symbol"]] = "cluster_cap"
                continue
            selected_long.append(row)

        # Select bottom N shorts within unit limits
        selected_short: list[dict] = []
        for row in short_cands[: self.bottom_n * 2]:
            if len(selected_short) >= self.bottom_n:
                break
            if sum(x["units"] for x in selected_short) >= self.max_units_total:
                break
            if not self._cluster_allows(row["symbol"], "SHORT", selected_short, corr):
                skipped[row["symbol"]] = "cluster_cap"
                continue
            selected_short.append(row)

        self.last_action["skipped"] = skipped
        return selected_long, selected_short

    # ========================== Execution ==========================

    def _weights_from_units(self, units: int) -> float:
        """
        Convert units to portfolio weight.

        6 units = 100% of allocated capital
        1 unit = ~16.7% of allocated capital
        """
        base = 1.0 / self.max_units_corr_cluster
        return float(np.clip(units * base, 0.0, 1.0))

    def generate_order(self, state: MarketState) -> PortfolioOrder | None:
        """
        Main order generation method.

        Flow:
        1. Update internal state from panel
        2. Check warmup conditions
        3. Check for risk-based exits (trailing stop/time stop)
        4. Build breakout candidates and generate orders
        """
        if state.symbol is None:
            return None
        if state.panel is None:
            return None

        self._update_panel(state)

        if not self._has_warmup(state.timestamp):
            return None

        # Risk-based exit has highest priority
        risk_exit = self._risk_exit_orders(state)
        if risk_exit:
            return PortfolioOrder(risk_exit)

        # Build candidates (no rebalance interval - check every bar for trailing stop)
        selected_long, selected_short = self._build_candidates(state.timestamp)
        positions = state.positions or {}

        orders: dict[str, Order] = {}
        used_units = 0

        debug_long = []
        debug_short = []

        def _append(side_rows: list[dict], expected_side: str) -> None:
            nonlocal orders, used_units
            for row in side_rows:
                if used_units >= self.max_units_total:
                    break
                sym = row["symbol"]
                units = min(self.max_units_single, int(row["units"]))
                if used_units + units > self.max_units_total:
                    continue

                used_units += units
                target_side = Side.BUY if expected_side == "LONG" else Side.SELL

                current_side = (
                    positions.get(sym, {}).get("side") if positions else None
                )
                if current_side == expected_side:
                    continue

                orders[sym] = Order(
                    side=target_side,
                    quantity=0.0,
                    order_type=OrderType.MARKET,
                    weight=self._weights_from_units(units),
                )

                # Track entry for cooldown
                self._last_entry_bar[sym] = self._bar_count

                # Initialize position tracking
                df = self._get_df(sym)
                if not df.empty:
                    current_price = float(df["close"].iloc[-1])
                    current_high = float(df["high"].iloc[-1])
                    current_low = float(df["low"].iloc[-1])
                    self._position_tracking[sym] = {
                        "entry_bar": self._bar_count,
                        "entry_price": current_price,
                        "side": expected_side,
                        "high_since": current_high,
                        "low_since": current_low,
                        "breakeven_activated": False,
                    }

                debug_row = {
                    "symbol": sym,
                    "units": units,
                    "weight": self._weights_from_units(units),
                    "breakout_ratio": row["breakout_ratio"],
                    "volume_ratio": row["volume_ratio"],
                    "signal_strength": row["signal_strength"],
                }
                if expected_side == "LONG":
                    debug_long.append(debug_row)
                else:
                    debug_short.append(debug_row)

        _append(selected_long, "LONG")
        _append(selected_short, "SHORT")

        # Close positions no longer in target list (NOT in V3 - hold until exit conditions)
        # V3 only exits via trailing stop, time stop, or stop loss - not via signal disappearing

        self.last_action = {
            "ts": state.timestamp.isoformat() if state.timestamp else None,
            "long_targets": debug_long,
            "short_targets": debug_short,
            "close_symbols": [],
            "skipped": self.last_action.get("skipped", {}),
            "orders": {
                k: ("BUY" if v.side == Side.BUY else "SELL") for k, v in orders.items()
            },
        }

        self.last_reason = "breakout_signal" if orders else "no_signal"
        if not orders:
            return None

        return PortfolioOrder(orders)

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(symbols={len(self.symbols)}, "
            f"breakout={self.breakout_threshold}, vol_spike={self.volume_spike_threshold}, "
            f"trend_period={self.trend_period}, cooldown={self.min_bars_between_entries}, "
            f"trailing_atr={self.trailing_atr_multiplier}, max_hold={self.max_hold_bars})"
        )
