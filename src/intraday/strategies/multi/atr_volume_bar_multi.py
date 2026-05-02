"""
ATR Volume Bar Portfolio Strategy

VWAP-weighted momentum strategy with volume-based entry confirmation
and ATR-based risk management across multiple crypto assets.

Core Innovation - VWAP Divergence Signal:
1. Volume-weighted momentum vs simple price momentum
2. Divergence indicates informed trader activity
3. ATR-based stops adapt to current volatility
4. Volatility regime filter (skip extremes)

Mathematical Foundation:
- VWAP Momentum = (VWAP_now - VWAP_lookback) / VWAP_lookback
- Price Momentum = (Close_now - Close_lookback) / Close_lookback
- Signal Strength = |VWAP_Momentum - Price_Momentum| (divergence)

Risk Management (2% Rule):
- Maximum loss per trade: 2% of portfolio
- Stop loss: max(2%, ATR * 2.0 / price)
- Unit-based position sizing with correlation limits
"""

from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


class ATRVolumeBarMultiStrategy:
    """
    ATR + VWAP-weighted Momentum Portfolio Strategy.

    Entry Conditions (Long):
    - Volume-weighted momentum > 0 over lookback period
    - VWAP divergence confirms (VW momentum >= Price momentum)
    - Current volume > 50th percentile of recent 20 bars
    - ATR-based R:R ratio >= min_rr threshold
    - Unit limits satisfied (single <= 4, cluster <= 6, total <= 6)
    - Volatility regime not extreme (ATR < 90th percentile)

    Entry Conditions (Short):
    - Volume-weighted momentum < 0 over lookback period
    - VWAP divergence confirms (VW momentum <= Price momentum)
    - Other conditions same as long

    Exit Conditions:
    - Stop loss hit: max(2%, ATR * 2)
    - Take profit hit: stop_pct * target_rr
    - Signal direction change (rebalance)

    Risk Management:
    - 2% max loss per trade
    - 4 units max per symbol
    - 6 units max per correlated cluster
    - 6 units max total portfolio
    """

    def __init__(
        self,
        symbols: list[str],
        lookback_minutes: int = 60,
        top_n: int = 2,
        bottom_n: int = 1,
        atr_window: int = 14,
        atr_stop_multiplier: float = 2.0,
        target_rr: float = 2.0,
        min_rr: float = 1.5,
        rebalance_interval_minutes: int = 30,
        min_volume_percentile: float = 50.0,
        vwap_divergence_threshold: float = 0.001,
        max_atr_percentile: float = 90.0,
        correlation_threshold: float = 0.7,
        corr_lookback_bars: int = 48,
        max_units_single: int = 4,
        max_units_corr_cluster: int = 6,
        max_units_total: int = 6,
        history_max_len: int = 2000,
    ):
        """
        Initialize the ATR Volume Bar Portfolio Strategy.

        Args:
            symbols: List of trading symbols (min 2)
            lookback_minutes: Momentum calculation lookback period
            top_n: Maximum long positions
            bottom_n: Maximum short positions
            atr_window: ATR calculation window (14 bars = 70 min with 5-min bars)
            atr_stop_multiplier: Stop distance = ATR * multiplier (min 2%)
            target_rr: Target risk:reward ratio for take profit
            min_rr: Minimum R:R ratio to enter trade
            rebalance_interval_minutes: Rebalancing frequency
            min_volume_percentile: Volume percentile filter (0-100)
            vwap_divergence_threshold: Min divergence for signal confirmation
            max_atr_percentile: Skip entries above this volatility percentile
            correlation_threshold: Correlation threshold for clustering (0.7)
            corr_lookback_bars: Rolling correlation lookback (48 bars = 4 hours)
            max_units_single: Max units per symbol (4)
            max_units_corr_cluster: Max units for correlated cluster (6)
            max_units_total: Max total portfolio units (6)
            history_max_len: Max bars to retain in history
        """
        if len(symbols) < 2:
            raise ValueError("symbols must contain at least two symbols")
        if top_n < 0 or bottom_n < 0 or top_n + bottom_n == 0:
            raise ValueError("top_n and bottom_n must allow at least one side position")

        self.symbols = symbols
        self.lookback_minutes = int(lookback_minutes)
        self.top_n = top_n
        self.bottom_n = bottom_n
        self.atr_window = max(1, int(atr_window))
        self.atr_stop_multiplier = float(atr_stop_multiplier)
        self.target_rr = float(target_rr)
        self.min_rr = float(min_rr)
        self.rebalance_interval_minutes = max(1, int(rebalance_interval_minutes))
        self.min_volume_percentile = float(min_volume_percentile)
        self.vwap_divergence_threshold = float(vwap_divergence_threshold)
        self.max_atr_percentile = float(max_atr_percentile)
        self.correlation_threshold = float(correlation_threshold)
        self.corr_lookback_bars = max(2, int(corr_lookback_bars))
        self.max_units_single = max(1, int(max_units_single))
        self.max_units_corr_cluster = max(1, int(max_units_corr_cluster))
        self.max_units_total = max(1, int(max_units_total))
        self.history_max_len = max(10, int(history_max_len))

        # Price history: symbol -> DataFrame with OHLCV + VWAP columns
        self._bars: dict[str, pd.DataFrame] = {
            sym: pd.DataFrame(columns=["close", "high", "low", "volume", "vwap"])
            for sym in self.symbols
        }

        # Volume history for percentile calculation
        self._volume_history: dict[str, list[float]] = {sym: [] for sym in self.symbols}

        # ATR history for regime filtering
        self._atr_history: dict[str, list[float]] = {sym: [] for sym in self.symbols}

        # VWAP cumulative tracking (reset daily or use rolling)
        self._cumulative_tpv: dict[str, float] = {sym: 0.0 for sym in self.symbols}
        self._cumulative_volume: dict[str, float] = {sym: 0.0 for sym in self.symbols}

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

    def _calculate_vwap(
        self, symbol: str, high: float, low: float, close: float, volume: float
    ) -> float:
        """
        Calculate VWAP using cumulative typical price * volume.

        VWAP = cumulative(typical_price * volume) / cumulative(volume)
        typical_price = (high + low + close) / 3
        """
        if volume <= 0:
            # Return last VWAP if no volume
            df = self._bars.get(symbol)
            if df is not None and not df.empty and "vwap" in df.columns:
                last_vwap = df["vwap"].iloc[-1]
                if pd.notna(last_vwap):
                    return float(last_vwap)
            return close

        typical_price = (high + low + close) / 3.0
        self._cumulative_tpv[symbol] += typical_price * volume
        self._cumulative_volume[symbol] += volume

        if self._cumulative_volume[symbol] > 0:
            return self._cumulative_tpv[symbol] / self._cumulative_volume[symbol]
        return close

    def _append_bar(self, symbol: str, ts: datetime, bar: dict) -> None:
        """Append a new bar to the price history with VWAP calculation."""
        df = self._bars.setdefault(
            symbol, pd.DataFrame(columns=["close", "high", "low", "volume", "vwap"])
        )

        close_val = float(bar["close"])
        high_val = float(bar["high"])
        low_val = float(bar["low"])
        volume_val = float(bar.get("volume", 0.0))

        # Calculate VWAP
        vwap_val = self._calculate_vwap(symbol, high_val, low_val, close_val, volume_val)

        row = pd.DataFrame(
            {
                "close": [close_val],
                "high": [high_val],
                "low": [low_val],
                "volume": [volume_val],
                "vwap": [vwap_val],
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

        # Track volume for percentile calculation
        if volume_val > 0:
            vol_hist = self._volume_history.setdefault(symbol, [])
            vol_hist.append(volume_val)
            if len(vol_hist) > 20:
                self._volume_history[symbol] = vol_hist[-20:]

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

        return updated

    def _get_df(self, symbol: str) -> pd.DataFrame:
        """Get price DataFrame for a symbol."""
        return self._bars.setdefault(
            symbol, pd.DataFrame(columns=["close", "high", "low", "volume", "vwap"])
        )

    def _has_warmup(self, now: datetime) -> bool:
        """Check if enough historical data exists for calculations."""
        earliest = now - timedelta(minutes=self.lookback_minutes)
        for sym in self.symbols:
            df = self._get_df(sym)
            if len(df) < max(self.atr_window + 2, 2):
                self.last_reason = f"not_enough_bars:{sym}:{len(df)}"
                return False
            if df.index.max() < earliest:
                self.last_reason = f"not_enough_lookback_time:{sym}"
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

    def _vwap_momentum(self, symbol: str, now: datetime) -> Optional[float]:
        """
        Calculate VWAP-weighted momentum over lookback period.

        Returns:
            Percentage change of VWAP from lookback_minutes ago to now.
        """
        df = self._get_df(symbol)
        if df.empty or "vwap" not in df.columns:
            return None
        window = df[df.index >= now - timedelta(minutes=self.lookback_minutes)]["vwap"]
        if len(window) < 2:
            return None
        first = float(window.iloc[0])
        last = float(window.iloc[-1])
        if first <= 0 or pd.isna(first) or pd.isna(last):
            return None
        return (last - first) / first

    def _price_momentum(self, symbol: str, now: datetime) -> Optional[float]:
        """
        Calculate simple price momentum over lookback period.

        Returns:
            Percentage change of close price from lookback_minutes ago to now.
        """
        df = self._get_df(symbol)
        if df.empty:
            return None
        window = df[df.index >= now - timedelta(minutes=self.lookback_minutes)]["close"]
        if len(window) < 2:
            return None
        first = float(window.iloc[0])
        last = float(window.iloc[-1])
        if first <= 0:
            return None
        return (last - first) / first

    def _vwap_divergence(self, symbol: str, now: datetime) -> Optional[tuple[float, float, float]]:
        """
        Calculate VWAP divergence (VW momentum - Price momentum).

        Returns:
            Tuple of (vwap_momentum, price_momentum, divergence)
        """
        vwap_mom = self._vwap_momentum(symbol, now)
        price_mom = self._price_momentum(symbol, now)
        if vwap_mom is None or price_mom is None:
            return None
        divergence = vwap_mom - price_mom
        return vwap_mom, price_mom, divergence

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
            - stop_pct = max(2%, atr_pct * atr_multiplier)
            - target_pct = stop_pct * target_rr
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
        target_pct = stop_pct * self.target_rr
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

    def _volume_filter_passed(self, symbol: str) -> bool:
        """
        Check if current volume is above percentile threshold.

        Returns True if volume >= threshold based on min_volume_percentile.
        """
        df = self._get_df(symbol)
        if df.empty:
            return True

        current_volume = float(df["volume"].iloc[-1])

        vol_hist = self._volume_history.get(symbol, [])
        if len(vol_hist) < 2:
            return True

        # Calculate percentile threshold
        sorted_vols = sorted(vol_hist)
        percentile_idx = int(len(sorted_vols) * self.min_volume_percentile / 100.0)
        percentile_idx = min(percentile_idx, len(sorted_vols) - 1)
        threshold = sorted_vols[percentile_idx]

        return current_volume >= threshold

    def _select_units(self, rr: float) -> int:
        """
        Allocate units based on R:R quality.

        Higher R:R = more conviction = more units.

        Returns:
            1-4 units based on R:R ratio.
        """
        if rr <= 1.0:
            return 1
        elif rr <= 1.5:
            return 2
        elif rr <= 2.0:
            return 3
        else:
            return 4  # Maximum for very high R:R

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

    def _build_candidates(self, now: datetime) -> tuple[list[dict], list[dict]]:
        """
        Build ranked lists of long and short candidates.

        Filters by:
        - VWAP momentum calculation success
        - VWAP divergence confirmation
        - R:R ratio >= min_rr
        - Volume filter
        - Volatility regime filter

        Ranks by R:R ratio (descending).
        """
        skipped: dict[str, str] = {}
        long_cands: list[dict] = []
        short_cands: list[dict] = []

        for sym in self.symbols:
            # Check volatility regime
            if self._is_volatility_extreme(sym):
                skipped[sym] = "extreme_volatility"
                continue

            # Calculate VWAP divergence
            divergence_result = self._vwap_divergence(sym, now)
            if divergence_result is None:
                skipped[sym] = "insufficient_vwap_data"
                continue

            vwap_mom, price_mom, divergence = divergence_result

            # Determine signal direction
            if vwap_mom == 0:
                skipped[sym] = "flat_vwap_momentum"
                continue

            # Check VWAP divergence confirmation
            if vwap_mom > 0:
                # For LONG: VW momentum >= Price momentum (accumulation)
                if divergence < -self.vwap_divergence_threshold:
                    skipped[sym] = "vwap_divergence_not_confirmed_long"
                    continue
            else:
                # For SHORT: VW momentum <= Price momentum (distribution)
                if divergence > self.vwap_divergence_threshold:
                    skipped[sym] = "vwap_divergence_not_confirmed_short"
                    continue

            # Check risk levels
            risk = self._risk_levels(sym)
            if risk is None:
                skipped[sym] = "insufficient_atr"
                continue

            stop_pct, _target_pct, _ = risk
            rr = abs(vwap_mom) / stop_pct if stop_pct > 0 else 0.0
            if rr < self.min_rr:
                skipped[sym] = f"rr_below_{self.min_rr:.1f}"
                continue

            # Check volume filter
            if not self._volume_filter_passed(sym):
                skipped[sym] = "low_volume"
                continue

            units = min(self.max_units_single, self._select_units(rr))
            row = {
                "symbol": sym,
                "side": "LONG" if vwap_mom > 0 else "SHORT",
                "vwap_momentum": vwap_mom,
                "price_momentum": price_mom,
                "divergence": divergence,
                "rr": rr,
                "units": units,
            }

            if row["side"] == "LONG":
                long_cands.append(row)
            else:
                short_cands.append(row)

        # Sort by R:R descending (best opportunities first)
        long_cands.sort(key=lambda x: x["rr"], reverse=True)
        short_cands.sort(key=lambda x: x["rr"], reverse=True)

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

    # ========================== Risk Management / Exits ==========================

    def _calculate_stop_price(
        self, entry_price: float, stop_pct: float, side: str
    ) -> float:
        """Calculate stop loss price."""
        if side == "LONG":
            return entry_price * (1 - stop_pct)
        else:
            return entry_price * (1 + stop_pct)

    def _calculate_target_price(
        self, entry_price: float, stop_pct: float, side: str
    ) -> float:
        """Calculate take profit price."""
        target_pct = stop_pct * self.target_rr
        if side == "LONG":
            return entry_price * (1 + target_pct)
        else:
            return entry_price * (1 - target_pct)

    def _risk_exit_orders(self, state: MarketState) -> dict[str, Order]:
        """
        Generate exit orders for positions hitting stop or target.

        Priority: This runs before rebalancing.
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

            # Calculate stop and target
            if side == "LONG":
                stop_price = entry * (1 - stop_pct)
                target_price = entry * (1 + target_pct)
                if now_price <= stop_price or now_price >= target_price:
                    orders[sym] = Order(
                        side=Side.SELL, quantity=qty, order_type=OrderType.MARKET
                    )
                    self.last_reason = f"exit_long_{'stop' if now_price <= stop_price else 'target'}"
            elif side == "SHORT":
                stop_price = entry * (1 + stop_pct)
                target_price = entry * (1 - target_pct)
                if now_price >= stop_price or now_price <= target_price:
                    orders[sym] = Order(
                        side=Side.BUY, quantity=qty, order_type=OrderType.MARKET
                    )
                    self.last_reason = f"exit_short_{'stop' if now_price >= stop_price else 'target'}"

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
        3. Check for risk-based exits (stop/target)
        4. Check if rebalance interval reached
        5. Build candidates and generate orders
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

                debug_row = {
                    "symbol": sym,
                    "units": units,
                    "weight": self._weights_from_units(units),
                    "rr": row["rr"],
                    "vwap_momentum": row["vwap_momentum"],
                    "divergence": row["divergence"],
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
            f"lookback={self.lookback_minutes}, top_n={self.top_n}, "
            f"bottom_n={self.bottom_n}, atr_window={self.atr_window}, "
            f"target_rr={self.target_rr}, min_rr={self.min_rr}, "
            f"vwap_div_thresh={self.vwap_divergence_threshold})"
        )
