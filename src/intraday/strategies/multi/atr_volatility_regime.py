"""
ATR Volatility Regime Strategy

Volatility regime-adaptive strategy that switches between two modes:
1. TRENDING Mode: Trade breakouts when volatility expands
2. RANGING Mode: Trade mean-reversion when volatility contracts

Key Innovation: Detect the market regime first and apply the appropriate strategy.

Regime Detection:
- TRENDING: volatility_ratio > 1.2 (ATR expanding)
- RANGING: volatility_ratio < 0.8 (ATR contracting)
- NEUTRAL: no trade when uncertain

Single position design to avoid correlation trap.
"""

from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


class ATRVolatilityRegimeStrategy:
    """ATR-based volatility regime strategy with breakout and mean-reversion modes."""

    def __init__(
        self,
        symbols: list[str],
        atr_window: int = 14,
        sma_window: int = 20,
        regime_atr_slow: int = 24,
        vol_expand_threshold: float = 1.2,
        vol_contract_threshold: float = 0.8,
        breakout_atr_mult: float = 2.0,
        reversion_atr_mult: float = 1.5,
        trailing_stop_mult: float = 1.5,
        take_profit_mult: float = 3.0,
        reversion_stop_mult: float = 1.0,
        momentum_lookback: int = 60,
        rsi_window: int = 14,
        rsi_oversold: int = 30,
        volume_confirm_mult: float = 1.2,
        max_hold_breakout: int = 240,
        max_hold_reversion: int = 120,
        min_bars_between_trades: int = 6,
        history_max_len: int = 2000,
    ):
        if len(symbols) < 1:
            raise ValueError("symbols must contain at least one symbol")

        self.symbols = symbols
        self.atr_window = max(1, int(atr_window))
        self.sma_window = max(1, int(sma_window))
        self.regime_atr_slow = max(1, int(regime_atr_slow))
        self.vol_expand_threshold = float(vol_expand_threshold)
        self.vol_contract_threshold = float(vol_contract_threshold)
        self.breakout_atr_mult = float(breakout_atr_mult)
        self.reversion_atr_mult = float(reversion_atr_mult)
        self.trailing_stop_mult = float(trailing_stop_mult)
        self.take_profit_mult = float(take_profit_mult)
        self.reversion_stop_mult = float(reversion_stop_mult)
        self.momentum_lookback = max(1, int(momentum_lookback))
        self.rsi_window = max(1, int(rsi_window))
        self.rsi_oversold = int(rsi_oversold)
        self.volume_confirm_mult = float(volume_confirm_mult)
        self.max_hold_breakout = int(max_hold_breakout)
        self.max_hold_reversion = int(max_hold_reversion)
        self.min_bars_between_trades = max(0, int(min_bars_between_trades))
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
        self._entry_regime: Optional[str] = None  # "TRENDING" or "RANGING"
        self._trailing_stop_price: float = 0.0
        self._position_high: float = 0.0  # Highest price since entry (for trailing stop long)
        self._position_low: float = float("inf")  # Lowest price since entry (for trailing stop short)

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
            self.atr_window + self.regime_atr_slow + 2,
            self.sma_window + 2,
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

    def _sma(self, symbol: str, field: str = "close") -> Optional[float]:
        """Calculate SMA of close prices."""
        df = self._get_df(symbol)
        if len(df) < self.sma_window:
            return None
        return float(df[field].tail(self.sma_window).mean())

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

    def _momentum(self, symbol: str, now: datetime) -> Optional[float]:
        """Calculate momentum as return over lookback period."""
        df = self._get_df(symbol)
        if df.empty:
            return None
        lookback_bars = self.momentum_lookback // 5  # Assuming 5-min bars
        if len(df) < lookback_bars:
            return None
        window = df["close"].tail(lookback_bars)
        if len(window) < 2:
            return None
        first = float(window.iloc[0])
        last = float(window.iloc[-1])
        if first <= 0:
            return None
        return (last - first) / first

    def _volume_avg(self, symbol: str, lookback: int = 20) -> Optional[float]:
        """Calculate average volume."""
        df = self._get_df(symbol)
        if len(df) < lookback:
            return None
        return float(df["volume"].tail(lookback).mean())

    # ---------------------------- Regime Detection ----------------------------
    def _calculate_regime(self, symbol: str) -> str:
        """
        Determine market regime based on ATR expansion/contraction.

        Returns:
            "TRENDING" if volatility expanding (ATR > slow_avg * threshold)
            "RANGING" if volatility contracting (ATR < slow_avg * threshold)
            "NEUTRAL" otherwise
        """
        atr_now = self._atr(symbol, self.atr_window)
        if atr_now is None:
            return "NEUTRAL"

        # Calculate slow ATR SMA
        df = self._get_df(symbol)
        if len(df) < self.atr_window + self.regime_atr_slow + 1:
            return "NEUTRAL"

        # Calculate ATR for each bar in the slow window
        atr_series = []
        for i in range(self.regime_atr_slow):
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
                atr_series.append(float(tr.mean()))

        if len(atr_series) < 2:
            return "NEUTRAL"

        atr_slow = np.mean(atr_series)
        if atr_slow <= 0:
            return "NEUTRAL"

        volatility_ratio = atr_now / atr_slow

        if volatility_ratio > self.vol_expand_threshold:
            return "TRENDING"
        elif volatility_ratio < self.vol_contract_threshold:
            return "RANGING"
        else:
            return "NEUTRAL"

    # ---------------------------- Entry Logic ----------------------------
    def _check_breakout_entry(
        self, state: MarketState, now: datetime
    ) -> Optional[tuple[str, str, float]]:
        """
        Check for breakout entry in TRENDING regime.

        Returns:
            (symbol, side, entry_price) or None
        """
        long_candidates = []
        short_candidates = []

        for sym in self.symbols:
            df = self._get_df(sym)
            if df.empty:
                continue

            close = float(df["close"].iloc[-1])
            sma = self._sma(sym)
            atr = self._atr(sym)
            if sma is None or atr is None:
                continue

            upper_band = sma + self.breakout_atr_mult * atr
            lower_band = sma - self.breakout_atr_mult * atr

            # Volume confirmation
            vol = float(df["volume"].iloc[-1])
            vol_avg = self._volume_avg(sym)
            if vol_avg is None or vol_avg <= 0:
                vol_confirmed = True  # Skip volume filter if no data
            else:
                vol_confirmed = vol >= vol_avg * self.volume_confirm_mult

            mom = self._momentum(sym, now)
            if mom is None:
                mom = 0.0

            if close > upper_band and vol_confirmed:
                long_candidates.append((sym, mom, close))
            elif close < lower_band and vol_confirmed:
                short_candidates.append((sym, mom, close))

        # Select strongest for long (highest momentum)
        if long_candidates:
            long_candidates.sort(key=lambda x: x[1], reverse=True)
            sym, _, price = long_candidates[0]
            return (sym, "LONG", price)

        # Select weakest for short (lowest momentum)
        if short_candidates:
            short_candidates.sort(key=lambda x: x[1])
            sym, _, price = short_candidates[0]
            return (sym, "SHORT", price)

        return None

    def _check_reversion_entry(
        self, state: MarketState, now: datetime
    ) -> Optional[tuple[str, str, float]]:
        """
        Check for mean-reversion entry in RANGING regime.
        LONG ONLY - no shorts in ranging mode.

        Returns:
            (symbol, "LONG", entry_price) or None
        """
        candidates = []

        for sym in self.symbols:
            df = self._get_df(sym)
            if df.empty:
                continue

            close = float(df["close"].iloc[-1])
            sma = self._sma(sym)
            atr = self._atr(sym)
            rsi = self._rsi(sym)
            if sma is None or atr is None or rsi is None:
                continue

            lower_range = sma - self.reversion_atr_mult * atr

            # Mean-reversion long: price below lower range AND RSI oversold
            if close < lower_range and rsi < self.rsi_oversold:
                # Score by how oversold (lower RSI = better candidate)
                candidates.append((sym, rsi, close))

        if candidates:
            # Select most oversold
            candidates.sort(key=lambda x: x[1])
            sym, _, price = candidates[0]
            return (sym, "LONG", price)

        return None

    # ---------------------------- Exit Logic ----------------------------
    def _check_exits(
        self, state: MarketState, now: datetime
    ) -> Optional[tuple[Order, str]]:
        """
        Check all exit conditions for current position.

        Returns:
            Exit Order if any exit condition met, None otherwise
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
        atr = self._atr(sym)
        if atr is None:
            atr = 0.0

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
            self._clear_position()
            return None

        exit_side = Side.SELL if self._position_side == "LONG" else Side.BUY
        exit_reason = None

        # 1. Regime change exit
        current_regime = self._calculate_regime(sym)
        if self._entry_regime and current_regime != self._entry_regime and current_regime != "NEUTRAL":
            exit_reason = "regime_change"

        # 2. Stop loss / Take profit (breakout mode)
        if self._entry_regime == "TRENDING" and not exit_reason:
            if self._position_side == "LONG":
                # Trailing stop
                trailing_stop = self._position_high - self.trailing_stop_mult * atr
                if close <= trailing_stop:
                    exit_reason = "trailing_stop"
                # Take profit
                take_profit = self._entry_price + self.take_profit_mult * atr
                if close >= take_profit:
                    exit_reason = "take_profit"
            else:  # SHORT
                # Trailing stop
                trailing_stop = self._position_low + self.trailing_stop_mult * atr
                if close >= trailing_stop:
                    exit_reason = "trailing_stop"
                # Take profit
                take_profit = self._entry_price - self.take_profit_mult * atr
                if close <= take_profit:
                    exit_reason = "take_profit"

        # 3. Stop loss / Take profit (reversion mode)
        if self._entry_regime == "RANGING" and not exit_reason:
            if self._position_side == "LONG":
                # Fixed stop
                stop_loss = self._entry_price - self.reversion_stop_mult * atr
                if close <= stop_loss:
                    exit_reason = "stop_loss"
                # Take profit at SMA (mean)
                sma = self._sma(sym)
                if sma and close >= sma:
                    exit_reason = "mean_target"

        # 4. Time-based exit
        if self._entry_time and not exit_reason:
            elapsed_minutes = (now - self._entry_time).total_seconds() / 60
            if self._entry_regime == "TRENDING" and elapsed_minutes >= self.max_hold_breakout:
                exit_reason = "time_exit_breakout"
            elif self._entry_regime == "RANGING" and elapsed_minutes >= self.max_hold_reversion:
                exit_reason = "time_exit_reversion"

        if exit_reason:
            self.last_reason = f"exit:{exit_reason}"
            # Save symbol before clearing position
            exit_symbol = self._position_symbol
            self._clear_position()
            self._last_trade_bar = self._bar_count
            # Return tuple with (order, symbol) - generate_order will unpack
            return (Order(side=exit_side, quantity=qty, order_type=OrderType.MARKET), exit_symbol)

        return None

    def _clear_position(self) -> None:
        """Reset position tracking."""
        self._position_symbol = None
        self._position_side = None
        self._entry_price = 0.0
        self._entry_time = None
        self._entry_regime = None
        self._trailing_stop_price = 0.0
        self._position_high = 0.0
        self._position_low = float("inf")

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
                    self._entry_regime = self._calculate_regime(sym)
                    df = self._get_df(sym)
                    if not df.empty:
                        self._position_high = float(df["high"].iloc[-1])
                        self._position_low = float(df["low"].iloc[-1])
                    break

    # ---------------------------- Main Logic ----------------------------
    def generate_order(self, state: MarketState) -> PortfolioOrder | None:
        """
        Generate trading orders based on volatility regime.

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
        if self._bar_count - self._last_trade_bar < self.min_bars_between_trades:
            self.last_reason = "cooldown"
            return None

        # Determine regime using first symbol (leader - BTC typically)
        leader_symbol = self.symbols[0]
        regime = self._calculate_regime(leader_symbol)
        self.last_regime = regime

        if regime == "NEUTRAL":
            self.last_reason = "neutral_regime"
            return None

        # Entry logic based on regime
        entry = None
        if regime == "TRENDING":
            entry = self._check_breakout_entry(state, now)
        elif regime == "RANGING":
            entry = self._check_reversion_entry(state, now)

        if entry is None:
            self.last_reason = f"no_signal_{regime.lower()}"
            return None

        sym, side, entry_price = entry

        # Set up position tracking
        self._position_symbol = sym
        self._position_side = side
        self._entry_price = entry_price
        self._entry_time = now
        self._entry_regime = regime
        self._position_high = entry_price
        self._position_low = entry_price
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
            f"atr_window={self.atr_window}, regime={self.last_regime})"
        )
