"""
ATR 기반 리스크 관리 포트폴리오 전략 (Enhanced v2)

설계 포인트
- 모멘텀만으로 진입하지 않고 2%/ATR 기반 리스크 룰을 붙여 손익비(R:R)를 중시
- 포트폴리오 엔진에서 PortfolioOrder를 반환하여 동시 주문 지원
- 상관관계가 높은 그룹은 최대 6유닛, 심볼 1개는 최대 4유닛 제한

Enhanced v2 개선사항:
- EMA 트렌드 필터 추가
- min_rr 조정 (1.0 -> 1.5)
- ATR 변동성 필터 추가 (0.5%-4% 범위)
- rebalance_interval 조정 (30 -> 60분)
- cooldown_bars 추가
- trailing stop 로직 추가
- 새 파라미터: momentum_threshold, min_atr_pct, max_atr_pct, cooldown_bars, max_stop_pct
"""

from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from intraday.strategy import MarketState, Order, OrderType, OrderType as _OrderTypeAlias, PortfolioOrder, Side


class ATRVolumeRiskMomentumStrategy:
    """ATR + 2% 룰 기반 포트폴리오 심볼 리스크 전략 (Enhanced v2)."""

    def __init__(
        self,
        symbols: list[str],
        lookback_minutes: int = 60,
        top_n: int = 2,
        bottom_n: int = 1,
        atr_window: int = 20,
        atr_stop_multiplier: float = 2.0,
        target_rr: float = 1.8,
        min_rr: float = 1.5,  # Increased from 1.0
        rebalance_interval_minutes: int = 60,  # Increased from 30
        min_volume: float = 0.0,
        correlation_threshold: float = 0.7,
        corr_lookback_bars: int = 48,
        max_units_single: int = 4,
        max_units_corr_cluster: int = 6,
        max_units_total: int = 6,
        history_max_len: int = 2000,
        # NEW parameters for Enhanced v2
        momentum_threshold: float = 0.003,  # 0.3% minimum momentum
        min_atr_pct: float = 0.005,  # 0.5% minimum ATR
        max_atr_pct: float = 0.04,  # 4% maximum ATR
        cooldown_bars: int = 6,  # 30 min cooldown (6 x 5-min bars)
        max_stop_pct: float = 0.04,  # 4% stop cap
        ema_window: int = 12,  # EMA window for trend filter
    ):
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
        self.min_volume = float(min_volume)
        self.correlation_threshold = float(correlation_threshold)
        self.corr_lookback_bars = max(2, int(corr_lookback_bars))
        self.max_units_single = max(1, int(max_units_single))
        self.max_units_corr_cluster = max(1, int(max_units_corr_cluster))
        self.max_units_total = max(1, int(max_units_total))
        self.history_max_len = max(10, int(history_max_len))

        # NEW parameters (Enhanced v2)
        self.momentum_threshold = float(momentum_threshold)
        self.min_atr_pct = float(min_atr_pct)
        self.max_atr_pct = float(max_atr_pct)
        self.cooldown_bars = max(1, int(cooldown_bars))
        self.max_stop_pct = float(max_stop_pct)
        self.ema_window = max(2, int(ema_window))

        # symbol -> candle panel history (close/high/low/volume)
        self._bars: dict[str, pd.DataFrame] = {
            sym: pd.DataFrame(columns=["close", "high", "low", "volume"])
            for sym in self.symbols
        }

        # Cooldown tracking (Enhanced v2)
        self._last_exit_bar: dict[str, int] = {}  # symbol -> bar index when exited
        self._bar_count: int = 0

        # Trailing stop tracking (Enhanced v2)
        self._position_high: dict[str, float] = {}  # symbol -> highest price since entry
        self._position_low: dict[str, float] = {}  # symbol -> lowest price since entry
        self._trailing_active: dict[str, bool] = {}  # symbol -> whether trailing stop is active
        self._entry_atr: dict[str, float] = {}  # symbol -> ATR at entry time

        # diagnostics
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

    # ---------------------------- state mgmt ----------------------------
    def _append_bar(self, symbol: str, ts: datetime, bar: dict) -> None:
        df = self._bars.setdefault(symbol, pd.DataFrame(columns=["close", "high", "low", "volume"]))
        row = pd.DataFrame(
            {
                "close": [float(bar["close"])],
                "high": [float(bar["high"])],
                "low": [float(bar["low"])],
                "volume": [float(bar.get("volume", 0.0))],
            },
            index=[ts],
        )
        # Avoid FutureWarning: only concat if df is not empty
        if df.empty:
            df = row
        else:
            df = pd.concat([df, row]).sort_index().tail(self.history_max_len)
        # 동일 타임스탬프가 들어올 수 있으므로 마지막 값으로 정리
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

        # Increment bar count for cooldown tracking
        if updated:
            self._bar_count += 1

        return updated

    def _get_df(self, symbol: str) -> pd.DataFrame:
        return self._bars.setdefault(symbol, pd.DataFrame(columns=["close", "high", "low", "volume"]))

    def _has_warmup(self, now: datetime) -> bool:
        earliest = now - timedelta(minutes=self.lookback_minutes)
        for sym in self.symbols:
            df = self._get_df(sym)
            if len(df) < max(self.atr_window + 2, self.ema_window + 1, 2):
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
        if self._last_rebalance is None:
            return True
        elapsed = (now - self._last_rebalance).total_seconds() / 60
        return elapsed >= self.rebalance_interval_minutes

    # ---------------------------- indicators ----------------------------
    def _momentum(self, symbol: str, now: datetime) -> Optional[float]:
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

    def _atr(self, symbol: str) -> Optional[float]:
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

    def _ema(self, symbol: str, window: int = None) -> Optional[float]:
        """Calculate EMA for trend quality filter (Enhanced v2)."""
        if window is None:
            window = self.ema_window
        df = self._get_df(symbol)
        if len(df) < window:
            return None
        return float(df["close"].ewm(span=window, adjust=False).mean().iloc[-1])

    def _trend_quality(self, symbol: str) -> Optional[str]:
        """Check if trend direction matches momentum (Enhanced v2)."""
        ema = self._ema(symbol)
        if ema is None:
            return None
        df = self._get_df(symbol)
        close = float(df["close"].iloc[-1])

        if close > ema * 1.001:  # 0.1% above EMA
            return "BULLISH"
        elif close < ema * 0.999:  # 0.1% below EMA
            return "BEARISH"
        return "NEUTRAL"

    def _volatility_acceptable(self, symbol: str) -> bool:
        """Check if ATR is within acceptable range (Enhanced v2)."""
        atr = self._atr(symbol)
        if atr is None:
            return False
        df = self._get_df(symbol)
        px = float(df["close"].iloc[-1])
        if px <= 0:
            return False
        atr_pct = atr / px
        return self.min_atr_pct <= atr_pct <= self.max_atr_pct

    def _cooldown_clear(self, symbol: str) -> bool:
        """Check if symbol has passed cooldown period (Enhanced v2)."""
        last_exit = self._last_exit_bar.get(symbol, -999)
        return (self._bar_count - last_exit) >= self.cooldown_bars

    def _risk_levels(self, symbol: str) -> Optional[tuple[float, float, float]]:
        atr = self._atr(symbol)
        if atr is None:
            return None
        df = self._get_df(symbol)
        px = float(df["close"].iloc[-1])
        if px <= 0:
            return None

        atr_pct = atr / px
        # Apply max_stop_pct cap (Enhanced v2)
        stop_pct = min(self.max_stop_pct, max(0.02, atr_pct * self.atr_stop_multiplier))
        target_pct = stop_pct * self.target_rr
        return stop_pct, target_pct, atr_pct

    def _correlation(self) -> pd.DataFrame:
        # 상관행렬 (최근 close return)
        aligned: dict[str, pd.Series] = {}
        for sym in self.symbols:
            df = self._get_df(sym)
            if len(df) > 2:
                aligned[sym] = df["close"].tail(self.corr_lookback_bars)

        if len(aligned) < 2:
            return pd.DataFrame()

        returns = pd.DataFrame(aligned).pct_change().dropna()
        return returns.corr().fillna(0.0)

    def _select_units(self, rr: float) -> int:
        # R:R가 높을수록 유닛 강화(최대 4유닛)
        if rr <= 1:
            return 1
        if rr <= 1.5:
            return 2
        if rr <= 2.0:
            return 3
        return 4

    def _cluster_allows(self, symbol: str, side: str, selected: list[dict], corr: pd.DataFrame) -> bool:
        # 같은 side 내에서 상관군 cap 적용
        if not selected:
            return True

        same_side = [x for x in selected if x["side"] == side]
        if not same_side:
            return True

        if corr.empty:
            return sum(x["units"] for x in same_side) < self.max_units_corr_cluster

        # 기존 심볼 중 하나라도 상관임계 초과 시 동일 군집으로 간주
        for sel in same_side:
            a = symbol
            b = sel["symbol"]
            if a in corr.columns and b in corr.index and abs(float(corr.loc[a, b])) >= self.correlation_threshold:
                if sum(x["units"] for x in same_side) + 1 > self.max_units_corr_cluster:
                    return False
                return True

        # 비상관이면 새 군집. 단일 심볼 cap은 기본 4유닛이므로 유닛 합 제한은 동일하지 않음.
        # 다만 전체 노출도 제어
        if sum(x["units"] for x in same_side) + 1 > self.max_units_total:
            return False

        return True

    def _build_candidates(self, now: datetime) -> tuple[list[dict], list[dict]]:
        skipped: dict[str, str] = {}
        long_cands: list[dict] = []
        short_cands: list[dict] = []

        for sym in self.symbols:
            mom = self._momentum(sym, now)
            if mom is None:
                skipped[sym] = "insufficient_momentum"
                continue
            if mom == 0:
                skipped[sym] = "flat"
                continue

            # Check minimum momentum threshold (Enhanced v2)
            if abs(mom) < self.momentum_threshold:
                skipped[sym] = f"momentum_below_{self.momentum_threshold}"
                continue

            # Check trend quality (Enhanced v2)
            trend = self._trend_quality(sym)
            if trend is None:
                skipped[sym] = "no_trend_data"
                continue

            # For LONG candidate, require BULLISH trend
            if mom > 0 and trend != "BULLISH":
                skipped[sym] = "trend_not_bullish"
                continue

            # For SHORT candidate, require BEARISH trend
            if mom < 0 and trend != "BEARISH":
                skipped[sym] = "trend_not_bearish"
                continue

            # Check volatility (Enhanced v2)
            if not self._volatility_acceptable(sym):
                skipped[sym] = "volatility_out_of_range"
                continue

            # Check cooldown (Enhanced v2)
            if not self._cooldown_clear(sym):
                skipped[sym] = "in_cooldown"
                continue

            risk = self._risk_levels(sym)
            if risk is None:
                skipped[sym] = "insufficient_atr"
                continue

            stop_pct, _target_pct, _ = risk
            rr = abs(mom) / stop_pct if stop_pct > 0 else 0.0
            if rr < self.min_rr:
                skipped[sym] = f"rr_below_{self.min_rr:.1f}"
                continue

            df = self._get_df(sym)
            if float(df["volume"].iloc[-1]) < self.min_volume:
                skipped[sym] = "low_volume"
                continue

            units = min(self.max_units_single, self._select_units(rr))
            row = {
                "symbol": sym,
                "side": "LONG" if mom > 0 else "SHORT",
                "momentum": mom,
                "rr": rr,
                "units": units,
            }

            if row["side"] == "LONG":
                long_cands.append(row)
            else:
                short_cands.append(row)

        long_cands.sort(key=lambda x: x["rr"], reverse=True)
        short_cands.sort(key=lambda x: x["rr"], reverse=True)

        corr = self._correlation()

        selected_long: list[dict] = []
        for row in long_cands[: self.top_n]:
            if sum(x["units"] for x in selected_long) >= self.max_units_total:
                break
            if not self._cluster_allows(row["symbol"], "LONG", selected_long, corr):
                skipped[row["symbol"]] = "cluster_cap"
                continue
            selected_long.append(row)

        selected_short: list[dict] = []
        for row in short_cands[: self.bottom_n]:
            if sum(x["units"] for x in selected_short) >= self.max_units_total:
                break
            if not self._cluster_allows(row["symbol"], "SHORT", selected_short, corr):
                skipped[row["symbol"]] = "cluster_cap"
                continue
            selected_short.append(row)

        self.last_action["skipped"] = skipped
        return selected_long, selected_short

    # ---------------------------- exits ----------------------------
    def _risk_exit_orders(self, state: MarketState) -> dict[str, Order]:
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

            # Use entry-time ATR if available, otherwise current ATR
            entry_atr = self._entry_atr.get(sym)
            if entry_atr is None:
                entry_atr = self._atr(sym)
            if entry_atr is None:
                entry_atr = 0.0

            now_price = self._get_df(sym)["close"].iloc[-1] if not self._get_df(sym).empty else state.close
            if now_price is None:
                continue
            now_price = float(now_price)

            # Get current momentum and trend for trend reversal exit
            mom = self._momentum(sym, state.timestamp)
            ema = self._ema(sym)

            if side == "LONG":
                stop = entry * (1 - stop_pct)
                take = entry * (1 + target_pct)

                # Update high water mark for trailing stop (Enhanced v2)
                if sym not in self._position_high:
                    self._position_high[sym] = now_price
                else:
                    self._position_high[sym] = max(self._position_high[sym], now_price)

                # Check if trailing should activate (50% of target reached) (Enhanced v2)
                partial_target = entry * (1 + 0.5 * target_pct)
                if now_price >= partial_target:
                    self._trailing_active[sym] = True

                # Apply trailing stop if active (Enhanced v2)
                if self._trailing_active.get(sym, False) and entry_atr > 0:
                    trailing_stop = self._position_high[sym] - (0.5 * entry_atr)
                    trailing_stop = max(trailing_stop, entry)  # Never below breakeven
                    if now_price <= trailing_stop:
                        orders[sym] = Order(side=Side.SELL, quantity=qty, order_type=OrderType.MARKET)
                        self.last_reason = "trailing_stop_hit"
                        self._record_exit(sym)
                        continue

                # Trend reversal exit (Enhanced v2)
                if mom is not None and ema is not None:
                    if mom < 0 and now_price < ema:
                        orders[sym] = Order(side=Side.SELL, quantity=qty, order_type=OrderType.MARKET)
                        self.last_reason = "trend_reversal"
                        self._record_exit(sym)
                        continue

                # Standard stop/target exit
                if now_price <= stop or now_price >= take:
                    orders[sym] = Order(side=Side.SELL, quantity=qty, order_type=OrderType.MARKET)
                    self.last_reason = "exit_long_stop_or_target"
                    self._record_exit(sym)

            elif side == "SHORT":
                stop = entry * (1 + stop_pct)
                take = entry * (1 - target_pct)

                # Update low water mark for trailing stop (Enhanced v2)
                if sym not in self._position_low:
                    self._position_low[sym] = now_price
                else:
                    self._position_low[sym] = min(self._position_low[sym], now_price)

                # Check if trailing should activate (50% of target reached) (Enhanced v2)
                partial_target = entry * (1 - 0.5 * target_pct)
                if now_price <= partial_target:
                    self._trailing_active[sym] = True

                # Apply trailing stop if active (Enhanced v2)
                if self._trailing_active.get(sym, False) and entry_atr > 0:
                    trailing_stop = self._position_low[sym] + (0.5 * entry_atr)
                    trailing_stop = min(trailing_stop, entry)  # Never above breakeven
                    if now_price >= trailing_stop:
                        orders[sym] = Order(side=Side.BUY, quantity=qty, order_type=OrderType.MARKET)
                        self.last_reason = "trailing_stop_hit"
                        self._record_exit(sym)
                        continue

                # Trend reversal exit (Enhanced v2)
                if mom is not None and ema is not None:
                    if mom > 0 and now_price > ema:
                        orders[sym] = Order(side=Side.BUY, quantity=qty, order_type=OrderType.MARKET)
                        self.last_reason = "trend_reversal"
                        self._record_exit(sym)
                        continue

                # Standard stop/target exit
                if now_price >= stop or now_price <= take:
                    orders[sym] = Order(side=Side.BUY, quantity=qty, order_type=OrderType.MARKET)
                    self.last_reason = "exit_short_stop_or_target"
                    self._record_exit(sym)

        return orders

    def _record_exit(self, symbol: str) -> None:
        """Record exit for cooldown tracking and clean up trailing stop state (Enhanced v2)."""
        self._last_exit_bar[symbol] = self._bar_count
        # Clean up trailing stop state
        self._position_high.pop(symbol, None)
        self._position_low.pop(symbol, None)
        self._trailing_active.pop(symbol, None)
        self._entry_atr.pop(symbol, None)

    def _record_entry(self, symbol: str) -> None:
        """Record entry for ATR tracking (Enhanced v2)."""
        atr = self._atr(symbol)
        if atr is not None:
            self._entry_atr[symbol] = atr
        # Initialize trailing stop state
        self._trailing_active[symbol] = False
        self._position_high.pop(symbol, None)
        self._position_low.pop(symbol, None)

    # ---------------------------- execution ----------------------------
    def _weights_from_units(self, units: int) -> float:
        # 6유닛 기준 총합 1.0
        base = 1.0 / self.max_units_corr_cluster
        return float(np.clip(units * base, 0.0, 1.0))

    def generate_order(self, state: MarketState) -> PortfolioOrder | None:
        if state.symbol is None:
            return None
        if state.panel is None:
            return None

        self._update_panel(state)

        if not self._has_warmup(state.timestamp):
            return None

        # risk-based exit has highest priority
        risk_exit = self._risk_exit_orders(state)
        if risk_exit:
            return PortfolioOrder(risk_exit)

        # 일정 주기 리밸런스
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

                current_side = positions.get(sym, {}).get("side") if positions else None
                if current_side == expected_side:
                    continue

                orders[sym] = Order(
                    side=target_side,
                    quantity=0.0,
                    order_type=OrderType.MARKET,
                    weight=self._weights_from_units(units),
                )

                # Record entry for ATR tracking (Enhanced v2)
                self._record_entry(sym)

                row = {
                    "symbol": sym,
                    "units": units,
                    "weight": self._weights_from_units(units),
                    "rr": row["rr"],
                    "momentum": row["momentum"],
                }
                if expected_side == "LONG":
                    debug_long.append(row)
                else:
                    debug_short.append(row)

        _append(selected_long, "LONG")
        _append(selected_short, "SHORT")

        # 타겟에서 빠진 기존 포지션은 정리
        hold_symbols = {r["symbol"] for r in selected_long + selected_short}
        for sym, pos in positions.items():
            if sym not in hold_symbols and pos and pos.get("side") in {"LONG", "SHORT"}:
                qty = float(pos.get("qty", 0.0) or 0.0)
                if qty <= 0:
                    continue
                side = Side.SELL if pos.get("side") == "LONG" else Side.BUY
                orders[sym] = Order(side=side, quantity=qty, order_type=OrderType.MARKET)
                # Record exit for cooldown (Enhanced v2)
                self._record_exit(sym)

        self.last_action = {
            "ts": state.timestamp.isoformat(),
            "long_targets": debug_long,
            "short_targets": debug_short,
            "close_symbols": [k for k, v in orders.items() if v.quantity > 0 and v.side in {Side.SELL, Side.BUY} and positions.get(k, {}).get("side")],
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
            f"lookback={self.lookback_minutes}, top_n={self.top_n}, bottom_n={self.bottom_n}, "
            f"min_rr={self.min_rr}, rebalance={self.rebalance_interval_minutes}min)"
        )
