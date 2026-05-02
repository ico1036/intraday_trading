"""
ATR Volume Unit Risk Portfolio Strategy V4 - Cross-Sectional Relative Strength

Paradigm shift from V1-V3 directional trading to RELATIVE VALUE trading.

Core Hypothesis:
When one coin significantly outperforms others over a short period, this relative
strength tends to continue, while the weakest continues underperforming. By going
long the strongest and short the weakest, we create a market-neutral position.

Key Differences from V1-V3:
| V1-V3 | V4 |
|-------|-----|
| Directional trading | Relative value trading |
| Predict absolute direction | Predict relative performance |
| Full directional exposure | Market-neutral (hedged) |
| Single-asset indicators | Cross-asset comparison |

Relative Strength Calculation:
    RS(symbol) = (close - close[lookback]) / (ATR(14) * lookback)

Entry Conditions:
    - Spread = RS(rank_1) - RS(rank_4) > min_spread_threshold
    - Volume dispersion > min_volume_dispersion
    - No existing pair OR holding period exceeded

Exit Conditions:
    1. Rank reversal (long drops to 3-4, short rises to 1-2)
    2. Spread collapse < spread_exit_threshold
    3. Per-leg stop loss (ATR-based)
    4. Time stop (max_holding_bars exceeded)

Risk Management (2% Rule):
    - Per-leg risk: 1% of AUM (2 legs = 2% total)
    - Stop Loss: 1.5 ATR per leg
    - Max concurrent positions: 1 pair (2 legs)
"""

from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


class ATRVolumeUnitRiskMultiStrategyV4:
    """
    Cross-Sectional Relative Strength Rotation Strategy.

    Market-neutral strategy that goes LONG the strongest relative performer
    and SHORT the weakest relative performer simultaneously.

    Entry (Pair Trade):
        1. Calculate ATR-normalized relative strength for each symbol
        2. Rank symbols (1 = strongest, N = weakest)
        3. Enter when spread (RS_best - RS_worst) > threshold
        4. LONG rank 1 + SHORT rank N

    Exit:
        1. Rank reversal (positions swap ranks significantly)
        2. Spread compression (RS spread < exit_threshold)
        3. Per-leg ATR stop loss
        4. Time stop (max holding period)

    Risk Management:
        - Always paired (market neutral)
        - ATR-normalized position sizing
        - 2% total risk (1% per leg)
    """

    def __init__(
        self,
        symbols: list[str],
        # Relative Strength Parameters
        lookback_period: int = 18,  # ~1.5 hours of 5-min bars
        min_spread_threshold: float = 2.0,  # Require 2.0 ATR-normalized spread
        spread_exit_threshold: float = 0.5,  # Exit when spread compresses
        volume_dispersion_threshold: float = 1.5,  # Volume ratio best/worst > 1.5x
        # Holding Parameters
        min_holding_bars: int = 6,  # 30 minutes minimum hold
        max_holding_bars: int = 48,  # 4 hours maximum hold
        min_bars_between_trades: int = 6,  # Cooldown after exit
        # Risk Parameters
        atr_period: int = 14,
        stop_loss_atr: float = 1.5,  # Tight stop per leg
        # Position Sizing
        position_weight: float = 0.5,  # 50% per side
        # History
        history_max_len: int = 2000,
    ):
        """
        Initialize the Cross-Sectional Relative Strength Strategy.

        Args:
            symbols: List of trading symbols (min 2 for cross-sectional)
            lookback_period: Bars for relative strength calculation
            min_spread_threshold: Minimum RS spread to enter
            spread_exit_threshold: Exit when spread falls below
            volume_dispersion_threshold: Min volume ratio between extremes
            min_holding_bars: Minimum bars before exiting
            max_holding_bars: Maximum bars before forced exit
            min_bars_between_trades: Cooldown after closing a pair
            atr_period: ATR calculation window
            stop_loss_atr: Stop loss distance in ATR multiples
            position_weight: Weight per leg (0.5 = 50% each side)
            history_max_len: Max bars to retain in history
        """
        if len(symbols) < 2:
            raise ValueError("symbols must contain at least two symbols for cross-sectional analysis")

        self.symbols = symbols

        # Relative Strength Parameters
        self.lookback_period = max(2, int(lookback_period))
        self.min_spread_threshold = float(min_spread_threshold)
        self.spread_exit_threshold = float(spread_exit_threshold)
        self.volume_dispersion_threshold = float(volume_dispersion_threshold)

        # Holding Parameters
        self.min_holding_bars = max(1, int(min_holding_bars))
        self.max_holding_bars = max(1, int(max_holding_bars))
        self.min_bars_between_trades = max(0, int(min_bars_between_trades))

        # Risk Parameters
        self.atr_period = max(1, int(atr_period))
        self.stop_loss_atr = float(stop_loss_atr)

        # Position Sizing
        self.position_weight = float(np.clip(position_weight, 0.1, 0.5))

        # History
        self.history_max_len = max(10, int(history_max_len))

        # Price history: symbol -> DataFrame with OHLCV columns
        self._bars: dict[str, pd.DataFrame] = {
            sym: pd.DataFrame(columns=["open", "close", "high", "low", "volume"])
            for sym in self.symbols
        }

        # Global bar counter
        self._bar_count: int = 0

        # Active pair tracking
        # {
        #   "long_symbol": str,
        #   "short_symbol": str,
        #   "entry_bar": int,
        #   "long_entry_price": float,
        #   "short_entry_price": float,
        #   "entry_spread": float,
        # }
        self._active_pair: Optional[dict] = None

        # Cooldown tracking
        self._last_exit_bar: int = -999

        # Diagnostics
        self.last_reason: str = "init"
        self.last_rs_scores: dict[str, float] = {}
        self.last_spread: float = 0.0
        self.last_action: dict = {
            "ts": None,
            "rs_ranking": [],
            "spread": 0.0,
            "action": "none",
            "details": {},
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
            updated = True

        if updated:
            self._bar_count += 1

        return updated

    def _get_df(self, symbol: str) -> pd.DataFrame:
        """Get price DataFrame for a symbol."""
        return self._bars.setdefault(
            symbol, pd.DataFrame(columns=["open", "close", "high", "low", "volume"])
        )

    def _has_warmup(self) -> bool:
        """Check if enough historical data exists for calculations."""
        min_bars = max(self.lookback_period + 1, self.atr_period + 2)
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
        ATR = rolling mean of True Range over atr_period.
        """
        df = self._get_df(symbol)
        if len(df) < self.atr_period + 1:
            return None
        d = df.tail(self.atr_period + 1).copy()
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
        atr_value = float(tr.rolling(self.atr_period).mean().iloc[-1])
        return atr_value if not pd.isna(atr_value) else None

    def _relative_strength(self, symbol: str) -> Optional[float]:
        """
        Calculate ATR-normalized relative strength.

        RS = (close - close[lookback]) / (ATR * lookback)

        This normalizes returns by volatility, making comparison fair
        across different volatility regimes and assets.
        """
        df = self._get_df(symbol)
        if len(df) < self.lookback_period + 1:
            return None

        current_close = float(df["close"].iloc[-1])
        past_close = float(df["close"].iloc[-self.lookback_period - 1])

        if past_close <= 0:
            return None

        atr = self._atr(symbol)
        if atr is None or atr <= 0:
            return None

        # ATR-normalized return
        # Divide by lookback to normalize time period
        rs = (current_close - past_close) / (atr * self.lookback_period)
        return rs

    def _current_volume(self, symbol: str) -> Optional[float]:
        """Get the most recent volume."""
        df = self._get_df(symbol)
        if df.empty:
            return None
        return float(df["volume"].iloc[-1])

    # ========================== Relative Strength Ranking ==========================

    def _calculate_rs_ranking(self) -> list[dict]:
        """
        Calculate and rank all symbols by relative strength.

        Returns:
            List of dicts with symbol, rs_score, volume, atr, rank
            Sorted by rs_score descending (strongest first).
        """
        rs_data = []

        for sym in self.symbols:
            rs = self._relative_strength(sym)
            if rs is None:
                continue

            atr = self._atr(sym)
            volume = self._current_volume(sym)
            df = self._get_df(sym)
            current_price = float(df["close"].iloc[-1]) if not df.empty else 0.0

            rs_data.append({
                "symbol": sym,
                "rs_score": rs,
                "volume": volume or 0.0,
                "atr": atr or 0.0,
                "price": current_price,
            })

        # Sort by RS score descending (strongest first)
        rs_data.sort(key=lambda x: x["rs_score"], reverse=True)

        # Assign ranks
        for i, item in enumerate(rs_data):
            item["rank"] = i + 1

        # Store for diagnostics
        self.last_rs_scores = {item["symbol"]: item["rs_score"] for item in rs_data}

        return rs_data

    def _calculate_spread(self, rs_ranking: list[dict]) -> float:
        """
        Calculate the spread between strongest and weakest RS.

        Spread = RS(rank_1) - RS(rank_N)
        """
        if len(rs_ranking) < 2:
            return 0.0

        strongest = rs_ranking[0]["rs_score"]
        weakest = rs_ranking[-1]["rs_score"]

        spread = strongest - weakest
        self.last_spread = spread
        return spread

    def _check_volume_dispersion(self, rs_ranking: list[dict]) -> bool:
        """
        Check if volume dispersion is sufficient for conviction.

        We want to see meaningful volume difference between extremes,
        indicating conviction in the relative strength signal.
        """
        if len(rs_ranking) < 2:
            return False

        strongest_vol = rs_ranking[0]["volume"]
        weakest_vol = rs_ranking[-1]["volume"]

        if weakest_vol <= 0:
            return False

        # Either extreme should have higher volume than the other
        volume_ratio = max(strongest_vol, weakest_vol) / min(strongest_vol, weakest_vol)
        return volume_ratio >= self.volume_dispersion_threshold

    # ========================== Entry Logic ==========================

    def _should_enter_pair(self, rs_ranking: list[dict], positions: dict) -> bool:
        """
        Check if conditions are met to enter a new pair trade.

        Entry conditions:
        1. No active pair position
        2. Not on cooldown
        3. Spread > min_spread_threshold
        4. Volume dispersion check passed
        """
        # Check if we have an active pair
        if self._active_pair is not None:
            return False

        # Check cooldown
        bars_since_exit = self._bar_count - self._last_exit_bar
        if bars_since_exit < self.min_bars_between_trades:
            self.last_reason = f"cooldown ({bars_since_exit}/{self.min_bars_between_trades} bars)"
            return False

        # Need at least 2 symbols for pair trade
        if len(rs_ranking) < 2:
            self.last_reason = "insufficient_symbols"
            return False

        # Check spread threshold
        spread = self._calculate_spread(rs_ranking)
        if spread < self.min_spread_threshold:
            self.last_reason = f"spread_too_low ({spread:.2f} < {self.min_spread_threshold})"
            return False

        # Check volume dispersion
        if not self._check_volume_dispersion(rs_ranking):
            self.last_reason = "volume_dispersion_low"
            return False

        return True

    def _generate_entry_orders(self, rs_ranking: list[dict]) -> dict[str, Order]:
        """
        Generate entry orders for the pair trade.

        LONG the strongest (rank 1)
        SHORT the weakest (rank N)
        """
        if len(rs_ranking) < 2:
            return {}

        strongest = rs_ranking[0]
        weakest = rs_ranking[-1]

        long_sym = strongest["symbol"]
        short_sym = weakest["symbol"]

        # Track the active pair
        self._active_pair = {
            "long_symbol": long_sym,
            "short_symbol": short_sym,
            "entry_bar": self._bar_count,
            "long_entry_price": strongest["price"],
            "short_entry_price": weakest["price"],
            "long_atr": strongest["atr"],
            "short_atr": weakest["atr"],
            "entry_spread": self._calculate_spread(rs_ranking),
        }

        orders = {
            long_sym: Order(
                side=Side.BUY,
                quantity=0.0,  # Weight-based sizing
                order_type=OrderType.MARKET,
                weight=self.position_weight,
            ),
            short_sym: Order(
                side=Side.SELL,
                quantity=0.0,  # Weight-based sizing
                order_type=OrderType.MARKET,
                weight=self.position_weight,
            ),
        }

        self.last_reason = f"enter_pair: LONG {long_sym} / SHORT {short_sym}"
        self.last_action["action"] = "enter"
        self.last_action["details"] = {
            "long_symbol": long_sym,
            "short_symbol": short_sym,
            "long_rs": strongest["rs_score"],
            "short_rs": weakest["rs_score"],
            "spread": self._active_pair["entry_spread"],
        }

        return orders

    # ========================== Exit Logic ==========================

    def _should_exit_pair(
        self, rs_ranking: list[dict], positions: dict
    ) -> tuple[bool, str]:
        """
        Check if the active pair should be exited.

        Exit conditions:
        1. Rank reversal (long drops to bottom half, short rises to top half)
        2. Spread compression (below exit threshold)
        3. Per-leg stop loss triggered
        4. Max holding period exceeded
        5. Min holding period not yet reached (prevent exit)

        Returns:
            (should_exit, reason)
        """
        if self._active_pair is None:
            return False, ""

        bars_held = self._bar_count - self._active_pair["entry_bar"]

        # Min holding period check
        if bars_held < self.min_holding_bars:
            return False, ""

        long_sym = self._active_pair["long_symbol"]
        short_sym = self._active_pair["short_symbol"]

        # Find current ranks
        long_rank = None
        short_rank = None
        for item in rs_ranking:
            if item["symbol"] == long_sym:
                long_rank = item["rank"]
            elif item["symbol"] == short_sym:
                short_rank = item["rank"]

        n_symbols = len(rs_ranking)

        # 1. Rank reversal check
        # Long should stay in top half, short should stay in bottom half
        if long_rank is not None and short_rank is not None:
            top_half = n_symbols // 2
            bottom_half = n_symbols - top_half

            # Long dropped to bottom half (rank > top_half)
            if long_rank > top_half:
                return True, f"rank_reversal_long (rank {long_rank}/{n_symbols})"

            # Short rose to top half (rank <= top_half)
            if short_rank <= top_half:
                return True, f"rank_reversal_short (rank {short_rank}/{n_symbols})"

        # 2. Spread compression check
        current_spread = self._calculate_spread(rs_ranking)
        if current_spread < self.spread_exit_threshold:
            return True, f"spread_compression ({current_spread:.2f} < {self.spread_exit_threshold})"

        # 3. Per-leg stop loss check
        for item in rs_ranking:
            if item["symbol"] == long_sym:
                current_price = item["price"]
                entry_price = self._active_pair["long_entry_price"]
                atr = self._active_pair["long_atr"]
                if atr > 0:
                    stop_price = entry_price - (atr * self.stop_loss_atr)
                    if current_price <= stop_price:
                        return True, f"stop_loss_long ({current_price:.2f} <= {stop_price:.2f})"

            elif item["symbol"] == short_sym:
                current_price = item["price"]
                entry_price = self._active_pair["short_entry_price"]
                atr = self._active_pair["short_atr"]
                if atr > 0:
                    stop_price = entry_price + (atr * self.stop_loss_atr)
                    if current_price >= stop_price:
                        return True, f"stop_loss_short ({current_price:.2f} >= {stop_price:.2f})"

        # 4. Max holding period check
        if bars_held >= self.max_holding_bars:
            return True, f"time_stop ({bars_held} >= {self.max_holding_bars} bars)"

        return False, ""

    def _generate_exit_orders(self, positions: dict, reason: str) -> dict[str, Order]:
        """
        Generate exit orders to close the pair.

        Close both legs of the pair trade.
        """
        if self._active_pair is None:
            return {}

        orders = {}
        long_sym = self._active_pair["long_symbol"]
        short_sym = self._active_pair["short_symbol"]

        # Close long position
        if long_sym in positions:
            pos = positions[long_sym]
            qty = float(pos.get("qty", 0.0) or 0.0)
            if qty > 0 and pos.get("side") == "LONG":
                orders[long_sym] = Order(
                    side=Side.SELL,
                    quantity=qty,
                    order_type=OrderType.MARKET,
                )

        # Close short position
        if short_sym in positions:
            pos = positions[short_sym]
            qty = float(pos.get("qty", 0.0) or 0.0)
            if qty > 0 and pos.get("side") == "SHORT":
                orders[short_sym] = Order(
                    side=Side.BUY,
                    quantity=qty,
                    order_type=OrderType.MARKET,
                )

        if orders:
            self._last_exit_bar = self._bar_count
            self._active_pair = None
            self.last_reason = f"exit_pair: {reason}"
            self.last_action["action"] = "exit"
            self.last_action["details"] = {"reason": reason}

        return orders

    # ========================== Main Order Generation ==========================

    def generate_order(self, state: MarketState) -> PortfolioOrder | None:
        """
        Main order generation method.

        Flow:
        1. Update internal state from panel
        2. Check warmup conditions
        3. Calculate relative strength ranking
        4. Check for exit conditions (if pair active)
        5. Check for entry conditions (if no pair active)
        """
        if state.symbol is None:
            return None
        if state.panel is None:
            return None

        self._update_panel(state)

        if not self._has_warmup():
            return None

        # Calculate RS ranking
        rs_ranking = self._calculate_rs_ranking()
        spread = self._calculate_spread(rs_ranking)

        # Update diagnostics
        self.last_action = {
            "ts": state.timestamp.isoformat() if state.timestamp else None,
            "rs_ranking": [
                {"symbol": r["symbol"], "rs": r["rs_score"], "rank": r["rank"]}
                for r in rs_ranking
            ],
            "spread": spread,
            "action": "none",
            "details": {},
        }

        positions = state.positions or {}

        # Priority 1: Check exit conditions for active pair
        if self._active_pair is not None:
            should_exit, exit_reason = self._should_exit_pair(rs_ranking, positions)
            if should_exit:
                exit_orders = self._generate_exit_orders(positions, exit_reason)
                if exit_orders:
                    return PortfolioOrder(exit_orders)

        # Priority 2: Check entry conditions
        # _should_enter_pair sets last_reason if it returns False
        can_enter = self._should_enter_pair(rs_ranking, positions)
        if can_enter:
            entry_orders = self._generate_entry_orders(rs_ranking)
            if entry_orders:
                return PortfolioOrder(entry_orders)

        # Only set no_action if _should_enter_pair didn't set a specific reason
        if can_enter or not self.last_reason.startswith(("cooldown", "spread_too_low", "volume_dispersion", "insufficient")):
            self.last_reason = "no_action"
        return None

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}(symbols={len(self.symbols)}, "
            f"lookback={self.lookback_period}, spread_thresh={self.min_spread_threshold}, "
            f"exit_thresh={self.spread_exit_threshold}, max_hold={self.max_holding_bars})"
        )
