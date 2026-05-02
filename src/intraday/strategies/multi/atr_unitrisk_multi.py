"""
ATR Unit Risk Cross-Asset Strategy

Algorithm: ATRUnitRiskMultiStrategy
- ATR-normalized momentum with volume confirmation
- 2% risk rule with ATR-based stops
- Unit-based position sizing (max 4 per symbol, max 6 correlated, max 8 total)
- Trend alignment (EMA fast > EMA slow) and volatility filter

Key Design Points:
1. Entry: ATR-normalized momentum > threshold + volume + trend + volatility + R:R
2. Exit: Stop-loss, take-profit, trend reversal, time-based
3. Position sizing: Units based on R:R quality (1.5-2.0: 1 unit, ... >3.0: 4 units)
4. Correlation constraints: Max 6 units in correlated cluster (correlation > 0.7)
"""

from datetime import datetime, timedelta
from typing import Optional
import math

import numpy as np
import pandas as pd

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


class ATRUnitRiskMultiStrategy:
    """ATR Unit Risk Cross-Asset Portfolio Strategy."""

    def __init__(
        self,
        symbols: list[str],
        # Momentum parameters
        lookback_bars: int = 20,
        momentum_threshold: float = 1.5,
        # ATR & Risk parameters
        atr_window: int = 20,
        atr_stop_multiplier: float = 2.0,
        target_rr: float = 2.0,
        min_rr: float = 1.5,
        # EMA trend parameters
        ema_fast: int = 10,
        ema_slow: int = 30,
        # Volume & Volatility filters
        volume_threshold: float = 1.2,
        min_volatility_pct: float = 0.5,
        # Portfolio selection
        top_n: int = 2,
        bottom_n: int = 1,
        # Correlation constraints
        correlation_threshold: float = 0.7,
        corr_lookback_bars: int = 48,
        # Unit management
        max_units_single: int = 4,
        max_units_corr_cluster: int = 6,
        max_units_total: int = 8,
        # Time constraints
        rebalance_interval_minutes: int = 30,
        max_holding_bars: int = 100,
        # Continuation factor for expected reward
        continuation_factor: float = 0.5,
        # Internal
        history_max_len: int = 2000,
    ):
        if len(symbols) < 2:
            raise ValueError("symbols must contain at least two symbols")
        if top_n < 0 or bottom_n < 0 or top_n + bottom_n == 0:
            raise ValueError("top_n and bottom_n must allow at least one side position")

        self.symbols = symbols
        self.lookback_bars = max(1, int(lookback_bars))
        self.momentum_threshold = float(momentum_threshold)
        self.atr_window = max(1, int(atr_window))
        self.atr_stop_multiplier = float(atr_stop_multiplier)
        self.target_rr = float(target_rr)
        self.min_rr = float(min_rr)
        self.ema_fast = max(1, int(ema_fast))
        self.ema_slow = max(1, int(ema_slow))
        self.volume_threshold = float(volume_threshold)
        self.min_volatility_pct = float(min_volatility_pct) / 100.0  # Convert to decimal
        self.top_n = top_n
        self.bottom_n = bottom_n
        self.correlation_threshold = float(correlation_threshold)
        self.corr_lookback_bars = max(2, int(corr_lookback_bars))
        self.max_units_single = max(1, int(max_units_single))
        self.max_units_corr_cluster = max(1, int(max_units_corr_cluster))
        self.max_units_total = max(1, int(max_units_total))
        self.rebalance_interval_minutes = max(1, int(rebalance_interval_minutes))
        self.max_holding_bars = max(1, int(max_holding_bars))
        self.continuation_factor = float(continuation_factor)
        self.history_max_len = max(10, int(history_max_len))

        # Symbol -> candle panel history (close/high/low/volume)
        self._bars: dict[str, pd.DataFrame] = {
            sym: pd.DataFrame(columns=["close", "high", "low", "volume"])
            for sym in self.symbols
        }

        # Position tracking for exits
        self._position_entry: dict[str, dict] = {}  # {symbol: {price, atr, bars_held, side}}

        # Diagnostics
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

    # ---------------------------- State Management ----------------------------
    def _append_bar(self, symbol: str, ts: datetime, bar: dict) -> None:
        df = self._bars.get(symbol)
        new_row = {
            "close": float(bar["close"]),
            "high": float(bar["high"]),
            "low": float(bar["low"]),
            "volume": float(bar.get("volume", 0.0)),
        }

        if df is None or df.empty:
            # Create new DataFrame with proper dtypes
            df = pd.DataFrame([new_row], index=[ts])
        else:
            # Append to existing DataFrame
            new_df = pd.DataFrame([new_row], index=[ts])
            df = pd.concat([df, new_df]).sort_index().tail(self.history_max_len)
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

        # Update bars held for existing positions
        for sym in self._position_entry:
            if sym in self._position_entry:
                self._position_entry[sym]["bars_held"] = (
                    self._position_entry[sym].get("bars_held", 0) + 1
                )

        return updated

    def _get_df(self, symbol: str) -> pd.DataFrame:
        df = self._bars.get(symbol)
        if df is None:
            return pd.DataFrame(columns=["close", "high", "low", "volume"])
        return df

    def _has_warmup(self) -> bool:
        min_bars = max(self.atr_window + 2, self.lookback_bars + 2, self.ema_slow + 2)
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
        if self._last_rebalance is None:
            return True
        elapsed = (now - self._last_rebalance).total_seconds() / 60
        return elapsed >= self.rebalance_interval_minutes

    # ---------------------------- Indicators ----------------------------
    def _atr(self, symbol: str) -> Optional[float]:
        """Calculate Average True Range."""
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
        return float(tr.rolling(self.atr_window).mean().iloc[-1])

    def _atr_normalized_momentum(self, symbol: str) -> Optional[float]:
        """
        Calculate ATR-normalized momentum.
        Formula: (close - close_N_bars_ago) / (ATR * sqrt(N))
        """
        df = self._get_df(symbol)
        if len(df) < self.lookback_bars + 1:
            return None

        atr = self._atr(symbol)
        if atr is None or atr <= 0:
            return None

        close_now = float(df["close"].iloc[-1])
        close_past = float(df["close"].iloc[-self.lookback_bars - 1])

        if close_past <= 0:
            return None

        price_change = close_now - close_past
        normalized = price_change / (atr * math.sqrt(self.lookback_bars))
        return normalized

    def _ema(self, symbol: str, period: int) -> Optional[float]:
        """Calculate Exponential Moving Average."""
        df = self._get_df(symbol)
        if len(df) < period:
            return None
        return float(df["close"].ewm(span=period, adjust=False).mean().iloc[-1])

    def _volume_ratio(self, symbol: str) -> Optional[float]:
        """Calculate current volume / average volume ratio."""
        df = self._get_df(symbol)
        if len(df) < self.lookback_bars:
            return None

        current_vol = float(df["volume"].iloc[-1])
        avg_vol = float(df["volume"].tail(self.lookback_bars).mean())

        if avg_vol <= 0:
            return None
        return current_vol / avg_vol

    def _volatility_pct(self, symbol: str) -> Optional[float]:
        """Calculate ATR / Price as volatility percentage."""
        atr = self._atr(symbol)
        if atr is None:
            return None

        df = self._get_df(symbol)
        px = float(df["close"].iloc[-1])
        if px <= 0:
            return None

        return atr / px

    def _calculate_rr(self, symbol: str, side: str) -> Optional[float]:
        """
        Calculate expected Risk:Reward ratio.
        Expected reward = momentum_pct * continuation_factor
        Risk = ATR * atr_stop_multiplier / close
        """
        df = self._get_df(symbol)
        if len(df) < self.lookback_bars + 1:
            return None

        atr = self._atr(symbol)
        if atr is None or atr <= 0:
            return None

        close_now = float(df["close"].iloc[-1])
        close_past = float(df["close"].iloc[-self.lookback_bars - 1])

        if close_past <= 0 or close_now <= 0:
            return None

        momentum_pct = abs(close_now - close_past) / close_past
        expected_reward = momentum_pct * self.continuation_factor
        risk = atr * self.atr_stop_multiplier / close_now

        if risk <= 0:
            return None

        return expected_reward / risk

    def _risk_levels(self, symbol: str) -> Optional[tuple[float, float, float]]:
        """Calculate stop_pct, target_pct, and atr_pct."""
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
        """Calculate correlation matrix from recent returns."""
        aligned: dict[str, pd.Series] = {}
        for sym in self.symbols:
            df = self._get_df(sym)
            if len(df) > 2:
                aligned[sym] = df["close"].tail(self.corr_lookback_bars)

        if len(aligned) < 2:
            return pd.DataFrame()

        returns = pd.DataFrame(aligned).pct_change().dropna()
        return returns.corr().fillna(0.0)

    # ---------------------------- Unit Management ----------------------------
    def _select_units(self, rr: float) -> int:
        """
        Allocate units based on R:R quality.
        1.5-2.0: 1 unit
        2.0-2.5: 2 units
        2.5-3.0: 3 units
        > 3.0: 4 units (max)
        """
        if rr < 1.5:
            return 0
        if rr < 2.0:
            return 1
        if rr < 2.5:
            return 2
        if rr < 3.0:
            return 3
        return 4

    def _cluster_allows(
        self, symbol: str, side: str, selected: list[dict], corr: pd.DataFrame
    ) -> bool:
        """Check if adding symbol respects correlation cluster limits."""
        # Check total units limit first (applies to all cases)
        total_units = sum(x["units"] for x in selected)
        if total_units >= self.max_units_total:
            return False

        if not selected:
            return True

        same_side = [x for x in selected if x["side"] == side]
        if not same_side:
            return True

        if corr.empty:
            return sum(x["units"] for x in same_side) < self.max_units_corr_cluster

        # Check correlation with existing positions
        for sel in same_side:
            a = symbol
            b = sel["symbol"]
            if (
                a in corr.columns
                and b in corr.index
                and abs(float(corr.loc[a, b])) >= self.correlation_threshold
            ):
                cluster_units = sum(
                    x["units"]
                    for x in same_side
                    if x["symbol"] in corr.index
                    and abs(float(corr.loc[a, x["symbol"]])) >= self.correlation_threshold
                )
                if cluster_units + 1 > self.max_units_corr_cluster:
                    return False

        return True

    def _weights_from_units(self, units: int) -> float:
        """Convert units to portfolio weight."""
        base = 1.0 / self.max_units_total
        return float(np.clip(units * base, 0.0, 1.0))

    # ---------------------------- Entry Logic ----------------------------
    def _check_entry_conditions(self, symbol: str) -> Optional[dict]:
        """
        Check all entry conditions for a symbol.
        Returns dict with signal info or None if no entry.
        """
        # 1. ATR-Normalized Momentum
        norm_mom = self._atr_normalized_momentum(symbol)
        if norm_mom is None:
            return None

        if abs(norm_mom) <= self.momentum_threshold:
            return None

        side = "LONG" if norm_mom > 0 else "SHORT"

        # 2. Volume Confirmation
        vol_ratio = self._volume_ratio(symbol)
        if vol_ratio is None or vol_ratio < self.volume_threshold:
            return None

        # 3. Trend Alignment (EMA fast vs EMA slow)
        ema_f = self._ema(symbol, self.ema_fast)
        ema_s = self._ema(symbol, self.ema_slow)
        if ema_f is None or ema_s is None:
            return None

        df = self._get_df(symbol)
        close = float(df["close"].iloc[-1])

        if side == "LONG":
            # Close > EMA_fast > EMA_slow
            if not (close > ema_f > ema_s):
                return None
        else:  # SHORT
            # Close < EMA_fast < EMA_slow
            if not (close < ema_f < ema_s):
                return None

        # 4. Volatility Filter
        vol_pct = self._volatility_pct(symbol)
        if vol_pct is None or vol_pct < self.min_volatility_pct:
            return None

        # 5. R:R Check
        rr = self._calculate_rr(symbol, side)
        if rr is None or rr < self.min_rr:
            return None

        # Calculate units
        units = min(self.max_units_single, self._select_units(rr))
        if units <= 0:
            return None

        return {
            "symbol": symbol,
            "side": side,
            "norm_momentum": norm_mom,
            "rr": rr,
            "units": units,
            "volume_ratio": vol_ratio,
        }

    def _build_candidates(self) -> tuple[list[dict], list[dict]]:
        """Build and filter entry candidates."""
        skipped: dict[str, str] = {}
        long_cands: list[dict] = []
        short_cands: list[dict] = []

        for sym in self.symbols:
            signal = self._check_entry_conditions(sym)
            if signal is None:
                skipped[sym] = "no_signal"
                continue

            if signal["side"] == "LONG":
                long_cands.append(signal)
            else:
                short_cands.append(signal)

        # Sort by R:R (best first)
        long_cands.sort(key=lambda x: x["rr"], reverse=True)
        short_cands.sort(key=lambda x: x["rr"], reverse=True)

        corr = self._correlation()

        # Select top_n long candidates with constraints
        selected_long: list[dict] = []
        total_units = 0
        for row in long_cands[: self.top_n * 2]:  # Consider more for filtering
            if len(selected_long) >= self.top_n:
                break
            if total_units >= self.max_units_total:
                break
            if total_units + row["units"] > self.max_units_total:
                skipped[row["symbol"]] = "total_units_exceeded"
                continue
            if not self._cluster_allows(row["symbol"], "LONG", selected_long, corr):
                skipped[row["symbol"]] = "cluster_cap"
                continue
            selected_long.append(row)
            total_units += row["units"]

        # Select bottom_n short candidates with constraints
        selected_short: list[dict] = []
        for row in short_cands[: self.bottom_n * 2]:
            if len(selected_short) >= self.bottom_n:
                break
            if total_units >= self.max_units_total:
                break
            if total_units + row["units"] > self.max_units_total:
                skipped[row["symbol"]] = "total_units_exceeded"
                continue
            if not self._cluster_allows(
                row["symbol"], "SHORT", selected_long + selected_short, corr
            ):
                skipped[row["symbol"]] = "cluster_cap"
                continue
            selected_short.append(row)
            total_units += row["units"]

        self.last_action["skipped"] = skipped
        return selected_long, selected_short

    # ---------------------------- Exit Logic ----------------------------
    def _check_exit_conditions(self, state: MarketState) -> dict[str, Order]:
        """
        Check exit conditions for existing positions.
        Priority: Stop-loss > Take-profit > Trend reversal > Time-based
        """
        orders: dict[str, Order] = {}
        if not state.positions:
            return orders

        for sym, pos in state.positions.items():
            if not pos:
                continue
            side = pos.get("side")
            qty = float(pos.get("qty", 0.0) or 0.0)
            entry_price = float(pos.get("entry_price", 0.0) or 0.0)

            if qty <= 0 or entry_price <= 0:
                continue

            df = self._get_df(sym)
            if df.empty:
                continue

            current_price = float(df["close"].iloc[-1])
            if current_price <= 0:
                continue

            # Get position entry info
            entry_info = self._position_entry.get(sym, {})
            entry_atr = entry_info.get("atr", self._atr(sym) or 0.02 * entry_price)
            bars_held = entry_info.get("bars_held", 0)

            # Calculate stop and target levels
            atr_pct = entry_atr / entry_price if entry_price > 0 else 0.02
            stop_pct = max(0.02, atr_pct * self.atr_stop_multiplier)
            target_pct = stop_pct * self.target_rr

            exit_reason = None

            if side == "LONG":
                stop_price = entry_price * (1 - stop_pct)
                target_price = entry_price * (1 + target_pct)

                # Priority 1: Stop-loss
                if current_price <= stop_price:
                    exit_reason = "stop_loss"
                # Priority 2: Take-profit
                elif current_price >= target_price:
                    exit_reason = "take_profit"
                # Priority 3: Trend reversal (close < EMA_slow)
                else:
                    ema_s = self._ema(sym, self.ema_slow)
                    if ema_s is not None and current_price < ema_s:
                        exit_reason = "trend_reversal"
                # Priority 4: Time-based
                if exit_reason is None and bars_held >= self.max_holding_bars:
                    exit_reason = "time_exit"

                if exit_reason:
                    orders[sym] = Order(
                        side=Side.SELL, quantity=qty, order_type=OrderType.MARKET
                    )
                    self.last_reason = f"exit_long_{exit_reason}"

            elif side == "SHORT":
                stop_price = entry_price * (1 + stop_pct)
                target_price = entry_price * (1 - target_pct)

                # Priority 1: Stop-loss
                if current_price >= stop_price:
                    exit_reason = "stop_loss"
                # Priority 2: Take-profit
                elif current_price <= target_price:
                    exit_reason = "take_profit"
                # Priority 3: Trend reversal (close > EMA_slow)
                else:
                    ema_s = self._ema(sym, self.ema_slow)
                    if ema_s is not None and current_price > ema_s:
                        exit_reason = "trend_reversal"
                # Priority 4: Time-based
                if exit_reason is None and bars_held >= self.max_holding_bars:
                    exit_reason = "time_exit"

                if exit_reason:
                    orders[sym] = Order(
                        side=Side.BUY, quantity=qty, order_type=OrderType.MARKET
                    )
                    self.last_reason = f"exit_short_{exit_reason}"

        return orders

    # ---------------------------- Main Order Generation ----------------------------
    def generate_order(self, state: MarketState) -> PortfolioOrder | None:
        """Generate portfolio orders based on current market state."""
        if state.symbol is None:
            return None
        if state.panel is None:
            return None

        self._update_panel(state)

        if not self._has_warmup():
            return None

        # Priority 1: Check exit conditions (stop/target/trend/time)
        exit_orders = self._check_exit_conditions(state)
        if exit_orders:
            # Clean up position tracking for exited positions
            for sym in exit_orders:
                if sym in self._position_entry:
                    del self._position_entry[sym]
            return PortfolioOrder(exit_orders)

        # Rebalance interval check
        if not self._has_rebalance_time(state.timestamp):
            return None

        self._last_rebalance = state.timestamp
        self.last_rebalance_ts = state.timestamp

        # Build entry candidates
        selected_long, selected_short = self._build_candidates()
        positions = state.positions or {}

        orders: dict[str, Order] = {}
        debug_long = []
        debug_short = []

        # Process long entries
        for row in selected_long:
            sym = row["symbol"]
            units = row["units"]

            current_side = positions.get(sym, {}).get("side") if positions else None
            if current_side == "LONG":
                continue  # Already long

            orders[sym] = Order(
                side=Side.BUY,
                quantity=0.0,  # Weight-based
                order_type=OrderType.MARKET,
                weight=self._weights_from_units(units),
            )

            # Track position entry
            atr = self._atr(sym)
            self._position_entry[sym] = {
                "price": float(self._get_df(sym)["close"].iloc[-1]),
                "atr": atr if atr else 0.0,
                "bars_held": 0,
                "side": "LONG",
            }

            debug_long.append(
                {
                    "symbol": sym,
                    "units": units,
                    "weight": self._weights_from_units(units),
                    "rr": row["rr"],
                    "norm_momentum": row["norm_momentum"],
                }
            )

        # Process short entries
        for row in selected_short:
            sym = row["symbol"]
            units = row["units"]

            current_side = positions.get(sym, {}).get("side") if positions else None
            if current_side == "SHORT":
                continue  # Already short

            orders[sym] = Order(
                side=Side.SELL,
                quantity=0.0,  # Weight-based
                order_type=OrderType.MARKET,
                weight=self._weights_from_units(units),
            )

            # Track position entry
            atr = self._atr(sym)
            self._position_entry[sym] = {
                "price": float(self._get_df(sym)["close"].iloc[-1]),
                "atr": atr if atr else 0.0,
                "bars_held": 0,
                "side": "SHORT",
            }

            debug_short.append(
                {
                    "symbol": sym,
                    "units": units,
                    "weight": self._weights_from_units(units),
                    "rr": row["rr"],
                    "norm_momentum": row["norm_momentum"],
                }
            )

        # Close positions not in selected targets (rebalance exit)
        hold_symbols = {r["symbol"] for r in selected_long + selected_short}
        for sym, pos in positions.items():
            if sym not in hold_symbols and pos and pos.get("side") in {"LONG", "SHORT"}:
                qty = float(pos.get("qty", 0.0) or 0.0)
                if qty <= 0:
                    continue
                side = Side.SELL if pos.get("side") == "LONG" else Side.BUY
                orders[sym] = Order(side=side, quantity=qty, order_type=OrderType.MARKET)

                # Clean up position tracking
                if sym in self._position_entry:
                    del self._position_entry[sym]

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
            "orders": {k: ("BUY" if v.side == Side.BUY else "SELL") for k, v in orders.items()},
        }

        self.last_reason = "rebalance_ok" if orders else "no_signal"
        if not orders:
            return None

        return PortfolioOrder(orders)

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(symbols={len(self.symbols)}, "
            f"lookback={self.lookback_bars}, top_n={self.top_n}, bottom_n={self.bottom_n}, "
            f"momentum_threshold={self.momentum_threshold}, min_rr={self.min_rr})"
        )
