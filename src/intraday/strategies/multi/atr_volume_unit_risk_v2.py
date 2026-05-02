"""
ATR Volume Unit Risk Portfolio Strategy V2 - Mean Reversion

Complete redesign from V1 momentum strategy that failed (-31% return).

Core Hypothesis:
Intraday crypto markets mean-revert on short timeframes. When:
1. Price deviates significantly from mean (z-score < -1.5 or > +1.5)
2. Volume is declining (exhaustion, not breakout)
3. Volatility is normal (not extreme)
Then: Enter counter-trend position, exit when price returns to mean.

Key Differences from V1:
| V1 (Failed) | V2 (New) |
|-------------|----------|
| Momentum (trend-following) | Mean Reversion (counter-trend) |
| Buy when price UP | Buy when price DOWN (oversold) |
| High volume confirms | LOW volume confirms (exhaustion) |
| Exit on reversal signal | Exit on mean return + time stop |

Mathematical Foundation:
- Z-score = (close - SMA(close, lookback)) / std(close, lookback)
- Oversold = z-score < -z_threshold (e.g., -1.5)
- Overbought = z-score > +z_threshold (e.g., +1.5)
- Volume Exhaustion = current_volume < volume_ma * ratio_threshold

Risk Management (2% Rule):
- Maximum loss per trade: 2% of portfolio
- Stop loss: max(2%, ATR * 2.0 / price)
- Time stop: exit after max_hold_bars if mean doesn't return
- Unit-based position sizing with correlation limits
"""

from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


class ATRVolumeUnitRiskMultiStrategyV2:
    """
    ATR + Volume Exhaustion Mean Reversion Portfolio Strategy V2.

    Entry Conditions (Long - OVERSOLD):
    - Z-score < -z_threshold (price significantly below mean)
    - Volume < volume_ma * volume_ratio_threshold (exhaustion)
    - ATR percentile < max_atr_percentile (normal volatility)
    - No existing long position
    - Unit limits satisfied
    - Not on cooldown (recently exited)

    Entry Conditions (Short - OVERBOUGHT):
    - Z-score > +z_threshold (price significantly above mean)
    - Volume < volume_ma * volume_ratio_threshold (exhaustion)
    - Other conditions same as long

    Exit Conditions:
    - Stop loss hit: max(2%, ATR * atr_stop_multiplier)
    - Take profit hit: ATR * atr_target_multiplier
    - Time stop: bars_held >= max_hold_bars

    Note: Mean reversion exit (z-score returns to 0) is DISABLED to prevent
    flip-flop behavior. After exit, symbol enters cooldown (6 bars = 30 min).

    Risk Management:
    - 2% max loss per trade
    - 4 units max per symbol
    - 6 units max per correlated cluster
    - 6 units max total portfolio
    """

    def __init__(
        self,
        symbols: list[str],
        z_threshold: float = 1.5,
        lookback_bars: int = 24,
        volume_ratio_threshold: float = 0.8,
        exit_zscore: float = 0.0,
        atr_window: int = 14,
        atr_stop_multiplier: float = 2.0,
        atr_target_multiplier: float = 3.0,
        max_atr_percentile: float = 80.0,
        max_hold_bars: int = 20,
        top_n: int = 2,
        bottom_n: int = 1,
        rebalance_interval_minutes: int = 30,
        correlation_threshold: float = 0.7,
        corr_lookback_bars: int = 48,
        max_units_single: int = 4,
        max_units_corr_cluster: int = 6,
        max_units_total: int = 6,
        history_max_len: int = 2000,
    ):
        """
        Initialize the ATR Volume Unit Risk Portfolio Strategy V2.

        Args:
            symbols: List of trading symbols (min 2)
            z_threshold: Z-score threshold for entry (default 1.5)
            lookback_bars: Lookback period for mean/std calculation (default 24)
            volume_ratio_threshold: Volume must be below this ratio of MA (default 0.8)
            exit_zscore: Exit when z-score returns to this level (default 0.0 = mean)
            atr_window: ATR calculation window (default 14)
            atr_stop_multiplier: Stop distance = ATR * multiplier (default 2.0)
            atr_target_multiplier: Target distance = ATR * multiplier (default 3.0)
            max_atr_percentile: Skip entries above this volatility percentile (default 80)
            max_hold_bars: Maximum bars to hold a position (default 20)
            top_n: Maximum long positions (default 2)
            bottom_n: Maximum short positions (default 1)
            rebalance_interval_minutes: Rebalancing frequency (default 30)
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
        self.z_threshold = float(z_threshold)
        self.lookback_bars = max(2, int(lookback_bars))
        self.volume_ratio_threshold = float(volume_ratio_threshold)
        self.exit_zscore = float(exit_zscore)
        self.atr_window = max(1, int(atr_window))
        self.atr_stop_multiplier = float(atr_stop_multiplier)
        self.atr_target_multiplier = float(atr_target_multiplier)
        self.max_atr_percentile = float(max_atr_percentile)
        self.max_hold_bars = max(1, int(max_hold_bars))
        self.top_n = top_n
        self.bottom_n = bottom_n
        self.rebalance_interval_minutes = max(1, int(rebalance_interval_minutes))
        self.correlation_threshold = float(correlation_threshold)
        self.corr_lookback_bars = max(2, int(corr_lookback_bars))
        self.max_units_single = max(1, int(max_units_single))
        self.max_units_corr_cluster = max(1, int(max_units_corr_cluster))
        self.max_units_total = max(1, int(max_units_total))
        self.history_max_len = max(10, int(history_max_len))

        # Price history: symbol -> DataFrame with OHLCV columns
        self._bars: dict[str, pd.DataFrame] = {
            sym: pd.DataFrame(columns=["close", "high", "low", "volume"])
            for sym in self.symbols
        }

        # ATR history for regime filtering
        self._atr_history: dict[str, list[float]] = {sym: [] for sym in self.symbols}

        # Position entry tracking for time stops
        # {symbol: {"entry_bar": int, "side": str}}
        self._position_entry: dict[str, dict] = {}
        self._bar_count: int = 0  # Global bar counter

        # Exit cooldown tracking to prevent flip-flop behavior
        # {symbol: bar_count when exited}
        self._exit_cooldown: dict[str, int] = {}
        self._cooldown_bars: int = 6  # 30 min cooldown (6 bars * 5 min)

        # Diagnostics and state
        self.last_rebalance_ts: Optional[datetime] = None
        self.last_reason: str = "init"
        self.last_action: dict = {
            "ts": None,
            "long_targets": [],
            "short_targets": [],
            "close_symbols": [],
            "skipped": {},
            "orders": {},
        }

        self._last_rebalance: Optional[datetime] = None

    # ========================== State Management ==========================

    def _append_bar(self, symbol: str, ts: datetime, bar: dict) -> None:
        """Append a new bar to the price history."""
        df = self._bars.setdefault(
            symbol, pd.DataFrame(columns=["close", "high", "low", "volume"])
        )

        close_val = float(bar["close"])
        high_val = float(bar["high"])
        low_val = float(bar["low"])
        volume_val = float(bar.get("volume", 0.0))

        row = pd.DataFrame(
            {
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
        """Get price DataFrame for a symbol."""
        return self._bars.setdefault(
            symbol, pd.DataFrame(columns=["close", "high", "low", "volume"])
        )

    def _has_warmup(self, now: datetime) -> bool:
        """Check if enough historical data exists for calculations."""
        min_bars = max(self.lookback_bars, self.atr_window + 2)
        for sym in self.symbols:
            df = self._get_df(sym)
            if len(df) < min_bars:
                self.last_reason = f"not_enough_bars:{sym}:{len(df)}"
                return False
            if float(df["close"].iloc[-1]) <= 0:
                self.last_reason = f"invalid_price:{sym}"
                return False
        return True

    def _has_rebalance_time(self, now: datetime) -> bool:
        """Check if enough time has passed since last rebalance."""
        if self._last_rebalance is None:
            return True
        elapsed = (now - self._last_rebalance).total_seconds() / 60
        return elapsed >= self.rebalance_interval_minutes

    # ========================== Indicators ==========================

    def _zscore(self, symbol: str) -> Optional[float]:
        """
        Calculate z-score for the latest price.

        Z-score = (close - mean) / std

        Returns:
            Z-score value or None if insufficient data.
            Negative = oversold, Positive = overbought.
        """
        df = self._get_df(symbol)
        if len(df) < self.lookback_bars:
            return None

        prices = df["close"].iloc[-self.lookback_bars:]
        mean = float(prices.mean())
        std = float(prices.std())

        if std <= 0:
            return 0.0

        current_price = float(prices.iloc[-1])
        return (current_price - mean) / std

    def _is_volume_exhausted(self, symbol: str) -> bool:
        """
        Check if current volume indicates exhaustion (OPPOSITE of V1!).

        Volume exhaustion = current volume < volume_ma * ratio_threshold

        This is the KEY DIFFERENCE from V1:
        - V1: required volume > median (confirming breakouts)
        - V2: requires volume < average * 0.8 (exhaustion = move ending)

        Returns:
            True if volume is exhausted (low), False otherwise.
        """
        df = self._get_df(symbol)
        if len(df) < self.lookback_bars:
            return False

        volumes = df["volume"].iloc[-self.lookback_bars:]
        if volumes.sum() <= 0:
            return True  # No volume data, assume exhaustion

        vol_ma = float(volumes.mean())
        current_vol = float(volumes.iloc[-1])

        if vol_ma <= 0:
            return True

        # Volume exhaustion: current volume is BELOW threshold of average
        # This is OPPOSITE of V1 which required volume > median
        return current_vol < vol_ma * self.volume_ratio_threshold

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

        # Track ATR history for regime filtering
        if not pd.isna(atr_value):
            atr_hist = self._atr_history.setdefault(symbol, [])
            atr_hist.append(atr_value)
            if len(atr_hist) > 100:
                self._atr_history[symbol] = atr_hist[-100:]

        return atr_value

    def _atr_percentile(self, symbol: str) -> Optional[float]:
        """
        Calculate current ATR percentile rank over history.

        Returns:
            Percentile (0-100) of current ATR vs historical ATR.
        """
        atr = self._atr(symbol)
        if atr is None:
            return None

        atr_hist = self._atr_history.get(symbol, [])
        if len(atr_hist) < 10:
            return 50.0  # Default to median if insufficient history

        # Calculate percentile rank
        count_below = sum(1 for h in atr_hist if h < atr)
        return (count_below / len(atr_hist)) * 100.0

    def _is_volatility_extreme(self, symbol: str) -> bool:
        """
        Check if current volatility is extreme (above max_atr_percentile).

        Returns True if ATR percentile > max_atr_percentile (skip entry).
        """
        percentile = self._atr_percentile(symbol)
        if percentile is None:
            return False
        return percentile > self.max_atr_percentile

    def _risk_levels(self, symbol: str) -> Optional[tuple[float, float, float]]:
        """
        Calculate risk levels for a symbol.

        Returns:
            Tuple of (stop_pct, target_pct, atr_pct)
            - stop_pct = max(2%, atr_pct * atr_stop_multiplier)
            - target_pct = max(1.5%, atr_pct * atr_target_multiplier)
        """
        atr = self._atr(symbol)
        if atr is None:
            return None
        df = self._get_df(symbol)
        px = float(df["close"].iloc[-1])
        if px <= 0:
            return None

        atr_pct = atr / px
        stop_pct = max(0.02, atr_pct * self.atr_stop_multiplier)
        target_pct = max(0.015, atr_pct * self.atr_target_multiplier)  # Min 1.5%
        return stop_pct, target_pct, atr_pct

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

    def _select_units(self, zscore: float) -> int:
        """
        Allocate units based on z-score extremity.

        More extreme z-score = higher conviction = more units.

        Returns:
            0-4 units based on z-score extremity.
        """
        extremity = abs(zscore) / self.z_threshold
        if extremity <= 1.0:
            return 0  # Below threshold - no trade
        elif extremity <= 1.5:
            return 1  # Marginal
        elif extremity <= 2.0:
            return 2  # Good
        elif extremity <= 2.5:
            return 3  # Strong
        else:
            return min(4, self.max_units_single)  # Extreme (capped)

    def _cluster_allows(
        self, symbol: str, side: str, selected: list[dict], corr: pd.DataFrame
    ) -> bool:
        """
        Check if adding a position violates correlation cluster limits.

        Checks:
        1. Single symbol limit (max_units_single)
        2. Correlated cluster limit (max_units_corr_cluster)
        3. Total portfolio limit (max_units_total)
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

    def _is_on_cooldown(self, symbol: str) -> bool:
        """
        Check if symbol is on cooldown after recent exit.

        Prevents flip-flop behavior where positions constantly reverse.

        Returns:
            True if symbol was recently exited and should not re-enter.
        """
        if symbol not in self._exit_cooldown:
            return False
        bars_since_exit = self._bar_count - self._exit_cooldown[symbol]
        return bars_since_exit < self._cooldown_bars

    def _build_candidates(self, now: datetime) -> tuple[list[dict], list[dict]]:
        """
        Build ranked lists of long and short candidates.

        V2 Mean Reversion Logic:
        - LONG: z-score < -z_threshold (OVERSOLD)
        - SHORT: z-score > +z_threshold (OVERBOUGHT)
        - Require volume exhaustion (low volume)
        - Require normal volatility regime

        This is OPPOSITE of V1 momentum logic.
        """
        skipped: dict[str, str] = {}
        long_cands: list[dict] = []
        short_cands: list[dict] = []

        for sym in self.symbols:
            # Check cooldown first - prevent flip-flop behavior
            if self._is_on_cooldown(sym):
                skipped[sym] = "on_cooldown"
                continue
            # Check volatility regime
            if self._is_volatility_extreme(sym):
                skipped[sym] = "extreme_volatility"
                continue

            # Calculate z-score (mean reversion signal)
            zscore = self._zscore(sym)
            if zscore is None:
                skipped[sym] = "insufficient_zscore_data"
                continue

            # Check volume exhaustion (MUST be low volume for mean reversion)
            if not self._is_volume_exhausted(sym):
                skipped[sym] = "volume_not_exhausted"
                continue

            # Check risk levels
            risk = self._risk_levels(sym)
            if risk is None:
                skipped[sym] = "insufficient_atr"
                continue

            # Calculate units based on z-score extremity
            units = self._select_units(zscore)
            if units <= 0:
                skipped[sym] = f"zscore_below_threshold_{self.z_threshold}"
                continue

            units = min(self.max_units_single, units)

            # MEAN REVERSION LOGIC (OPPOSITE OF V1):
            # - Negative z-score (oversold) = BUY (price will revert UP)
            # - Positive z-score (overbought) = SELL (price will revert DOWN)
            if zscore < -self.z_threshold:
                # OVERSOLD - price below mean - BUY expecting reversion UP
                long_cands.append({
                    "symbol": sym,
                    "side": "LONG",
                    "zscore": zscore,
                    "units": units,
                    "extremity": abs(zscore) / self.z_threshold,
                })
            elif zscore > self.z_threshold:
                # OVERBOUGHT - price above mean - SELL expecting reversion DOWN
                short_cands.append({
                    "symbol": sym,
                    "side": "SHORT",
                    "zscore": zscore,
                    "units": units,
                    "extremity": abs(zscore) / self.z_threshold,
                })

        # Sort by extremity descending (most extreme z-scores first)
        long_cands.sort(key=lambda x: x["extremity"], reverse=True)
        short_cands.sort(key=lambda x: x["extremity"], reverse=True)

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

    # ========================== Exit Management ==========================

    def _check_time_stop(self, symbol: str) -> bool:
        """
        Check if position has exceeded max_hold_bars.

        This is a NEW feature in V2 - prevents holding losers too long.

        Returns:
            True if position should be exited due to time stop.
        """
        entry_info = self._position_entry.get(symbol)
        if entry_info is None:
            return False

        entry_bar = entry_info.get("entry_bar", self._bar_count)
        bars_held = self._bar_count - entry_bar

        return bars_held >= self.max_hold_bars

    def _check_mean_reversion_exit(self, symbol: str, current_side: str) -> bool:
        """
        Check if price has returned to mean (exit signal for mean reversion).

        V2 Exit Logic:
        - LONG: exit when z-score returns to exit_zscore (default 0.0)
        - SHORT: exit when z-score returns to exit_zscore (default 0.0)

        Returns:
            True if should exit based on mean reversion target.
        """
        zscore = self._zscore(symbol)
        if zscore is None:
            return False

        if current_side == "LONG":
            # Was oversold (z < -threshold), exit when z returns toward 0
            return zscore >= self.exit_zscore
        elif current_side == "SHORT":
            # Was overbought (z > +threshold), exit when z returns toward 0
            return zscore <= self.exit_zscore

        return False

    def _risk_exit_orders(self, state: MarketState) -> dict[str, Order]:
        """
        Generate exit orders for positions hitting stop, target, or time stop.

        V2 Exit Priority:
        1. Stop loss (ATR-based)
        2. Take profit (ATR-based)
        3. Time stop (max_hold_bars exceeded)

        Note: Mean reversion exit (z-score returns to 0) was DISABLED to prevent
        flip-flop behavior where positions constantly reverse direction.
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

            # Track position entry for time stop
            if sym not in self._position_entry:
                self._position_entry[sym] = {
                    "entry_bar": self._bar_count,
                    "side": side,
                }

            risk = self._risk_levels(sym)
            if risk is None:
                continue
            stop_pct, target_pct, _ = risk

            # Get current price
            df = self._get_df(sym)
            now_price = float(df["close"].iloc[-1]) if not df.empty else None
            if now_price is None:
                if state.close is not None:
                    now_price = float(state.close)
                else:
                    continue

            should_exit = False
            exit_reason = ""

            # Check stop loss and take profit
            if side == "LONG":
                stop_price = entry * (1 - stop_pct)
                target_price = entry * (1 + target_pct)
                if now_price <= stop_price:
                    should_exit = True
                    exit_reason = "stop_loss"
                elif now_price >= target_price:
                    should_exit = True
                    exit_reason = "take_profit"
            elif side == "SHORT":
                stop_price = entry * (1 + stop_pct)
                target_price = entry * (1 - target_pct)
                if now_price >= stop_price:
                    should_exit = True
                    exit_reason = "stop_loss"
                elif now_price <= target_price:
                    should_exit = True
                    exit_reason = "take_profit"

            # DISABLED: Mean reversion exit causes flip-flop behavior
            # When z-score returns to 0, position exits, then immediately
            # re-enters in opposite direction on next rebalance.
            # Rely on stop/target/time_stop instead.
            # if not should_exit and self._check_mean_reversion_exit(sym, side):
            #     should_exit = True
            #     exit_reason = "mean_reversion"

            # Check time stop (V2 NEW FEATURE)
            if not should_exit and self._check_time_stop(sym):
                should_exit = True
                exit_reason = "time_stop"

            if should_exit:
                exit_side = Side.SELL if side == "LONG" else Side.BUY
                orders[sym] = Order(
                    side=exit_side, quantity=qty, order_type=OrderType.MARKET
                )
                self.last_reason = f"exit_{side.lower()}_{exit_reason}"
                # Clear position entry tracking
                self._position_entry.pop(sym, None)
                # Set cooldown to prevent immediate re-entry
                self._exit_cooldown[sym] = self._bar_count

        return orders

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
        3. Check for risk-based exits (stop/target/time)
        4. Check if rebalance interval reached
        5. Build mean reversion candidates and generate orders
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

        # Check rebalance interval
        if not self._has_rebalance_time(state.timestamp):
            return None

        self._last_rebalance = state.timestamp
        self.last_rebalance_ts = state.timestamp

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

                # Track position entry for time stop
                self._position_entry[sym] = {
                    "entry_bar": self._bar_count,
                    "side": expected_side,
                }

                debug_row = {
                    "symbol": sym,
                    "units": units,
                    "weight": self._weights_from_units(units),
                    "zscore": row["zscore"],
                    "extremity": row["extremity"],
                }
                if expected_side == "LONG":
                    debug_long.append(debug_row)
                else:
                    debug_short.append(debug_row)

        _append(selected_long, "LONG")
        _append(selected_short, "SHORT")

        # Close positions no longer in target list
        hold_symbols = {r["symbol"] for r in selected_long + selected_short}
        for sym, pos in positions.items():
            if (
                sym not in hold_symbols
                and pos
                and pos.get("side") in {"LONG", "SHORT"}
            ):
                qty = float(pos.get("qty", 0.0) or 0.0)
                if qty <= 0:
                    continue
                side = Side.SELL if pos.get("side") == "LONG" else Side.BUY
                orders[sym] = Order(side=side, quantity=qty, order_type=OrderType.MARKET)
                # Clear position entry tracking
                self._position_entry.pop(sym, None)
                # Set cooldown to prevent immediate re-entry
                self._exit_cooldown[sym] = self._bar_count

        self.last_action = {
            "ts": state.timestamp.isoformat() if state.timestamp else None,
            "long_targets": debug_long,
            "short_targets": debug_short,
            "close_symbols": [
                k
                for k, v in orders.items()
                if v.quantity > 0
                and v.side in {Side.SELL, Side.BUY}
                and positions.get(k, {}).get("side")
            ],
            "skipped": self.last_action.get("skipped", {}),
            "orders": {
                k: ("BUY" if v.side == Side.BUY else "SELL") for k, v in orders.items()
            },
        }

        self.last_reason = "rebalance_ok" if orders else "no_signal"
        if not orders:
            return None

        return PortfolioOrder(orders)

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(symbols={len(self.symbols)}, "
            f"z_threshold={self.z_threshold}, lookback={self.lookback_bars}, "
            f"vol_ratio={self.volume_ratio_threshold}, exit_z={self.exit_zscore}, "
            f"top_n={self.top_n}, bottom_n={self.bottom_n}, "
            f"max_hold={self.max_hold_bars})"
        )
