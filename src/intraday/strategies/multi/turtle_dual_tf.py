"""Dual-timeframe Turtle-like portfolio strategy (ATR risk-based).

요구사항 매핑:
- 20/55 같은 서로 다른 타임프레임 기준으로 추세 돌파/추세 반전 조건 사용
- ATR 기반 스탑 & 트레일링 스탑
- 위험 단위 N = initial_capital * n_unit (기본 1%)
- 단일 신규 진입당 최대 손실 기준치: 2N
- 동일/고상관(옵션)에서는 4N/6N까지 노출 상향 허용

주의:
- 포트폴리오 틱/캔들러너에서 MarketState.panel이 있을 때 동작.
- 체결 단가는 state.timestamp 시점의 close/가격으로 가정.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


class TurtleDualTimeframeStrategy:
    """포트폴리오심볼, ATR-리스크 기반 Turtle-ish 전략."""

    def __init__(
        self,
        symbols: list[str],
        fast_window: int = 20,
        slow_window: int = 55,
        atr_window: int = 14,
        stop_atr: float = 2.0,
        trail_atr: float = 1.5,
        n_unit: float = 0.01,
        max_risk_per_trade_unit: float = 2.0,
        max_risk_same_symbol_unit: float = 4.0,
        max_risk_corr_symbol_unit: float = 6.0,
        corr_window: int = 120,
        corr_threshold: float = 0.7,
        max_open_positions: int = 4,
        atr_min: float = 1e-8,
        history_max_len: int = 2000,
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
        self.n_unit = float(n_unit)
        self.max_risk_per_trade_unit = float(max_risk_per_trade_unit)
        self.max_risk_same_symbol_unit = float(max_risk_same_symbol_unit)
        self.max_risk_corr_symbol_unit = float(max_risk_corr_symbol_unit)
        self.corr_window = max(10, int(corr_window))
        self.corr_threshold = float(corr_threshold)
        self.max_open_positions = max(1, int(max_open_positions))
        self.atr_min = float(atr_min)
        self.history_max_len = max(10, int(history_max_len))

        self.initial_capital = 100_000.0  # 전략 내부 기본치. 실제 실행 파라미터에서 초기자본에 맞춰 조정 가능
        self._bars: dict[str, pd.DataFrame] = {
            sym: pd.DataFrame(columns=["open", "high", "low", "close", "volume"]) for sym in symbols
        }
        self._bar_count: int = 0

        self._position_state: dict[str, dict] = {}

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

    # ── data handling ──────────────────────────────────────────────────────────────
    def _append_bar(self, symbol: str, ts: datetime, o: float, h: float, l: float, c: float, v: float) -> None:
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
        for sym, df in self._bars.items():
            if len(df) < need:
                self.last_reason = f"need_more_bars:{sym}:{len(df)}"
                return False
        return True

    # ── signals/indicators ─────────────────────────────────────────────────────────
    def _atr(self, sym: str) -> Optional[float]:
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
        tr = tr.iloc[1:]
        v = float(tr.rolling(self.atr_window).mean().iloc[-1])
        return v if pd.notna(v) else None

    def _momentum_signal(self, sym: str) -> int:
        df = self._bars[sym]
        if len(df) <= self.slow_window:
            return 0
        c = float(df["close"].iloc[-1])
        fast_hi = float(df["high"].iloc[-self.fast_window - 1 : -1].max())
        slow_hi = float(df["high"].iloc[-self.slow_window - 1 : -1].max())
        fast_lo = float(df["low"].iloc[-self.fast_window - 1 : -1].min())
        slow_lo = float(df["low"].iloc[-self.slow_window - 1 : -1].min())

        if c > fast_hi and c > slow_hi:
            return 1
        if c < fast_lo and c < slow_lo:
            return -1
        return 0

    def _corr(self, sym_a: str, sym_b: str) -> float:
        if sym_a not in self._bars or sym_b not in self._bars:
            return 0.0
        da = self._bars[sym_a]["close"].pct_change().tail(self.corr_window)
        db = self._bars[sym_b]["close"].pct_change().tail(self.corr_window)
        if len(da) < 20 or len(db) < 20:
            return 0.0
        df = pd.concat([da, db], axis=1).dropna()
        if len(df) < 20:
            return 0.0
        return float(df.iloc[:, 0].corr(df.iloc[:, 1]))

    def _risk_unit(self) -> float:
        # N
        return self.initial_capital * self.n_unit

    def _max_risk_for_symbol(self, symbol: str, side: int) -> float:
        # 2N 기본, 상관관계에 따라 최대 허용치 확장(요구사항 반영: 4N/6N)
        base = self._risk_unit() * self.max_risk_per_trade_unit
        base_cap = self._risk_unit() * self.max_risk_same_symbol_unit

        for open_sym, info in self._position_state.items():
            if open_sym == symbol:
                continue
            corr = self._corr(symbol, open_sym)
            if abs(corr) >= self.corr_threshold:
                        return self._risk_unit() * self.max_risk_corr_symbol_unit

        return min(base_cap, base)

    def _position_qty(self, symbol: str, side: int, price: float) -> float:
        atr = self._atr(symbol)
        if atr is None or atr < self.atr_min or price <= 0:
            return 0.0

        risk_budget = self._max_risk_for_symbol(symbol, side)
        stop_distance = atr * self.stop_atr
        qty = risk_budget / stop_distance
        return float(max(0.0, qty))

    # ── execution plan ─────────────────────────────────────────────────────────────
    def _build_plan(self, state: MarketState) -> dict[str, Optional[Order]]:
        # 현재 시점의 시그널/포지션 상태 갱신 후 전체 심볼 주문계획 생성.
        ts = state.timestamp

        signals: dict[str, int] = {}
        atrs: dict[str, float] = {}
        prices: dict[str, float] = {}

        for sym in self.symbols:
            if sym not in self._bars or self._bars[sym].empty:
                continue
            last = float(self._bars[sym]["close"].iloc[-1])
            atr_v = self._atr(sym)
            if np.isfinite(last) and last > 0 and atr_v is not None and atr_v > 0:
                signals[sym] = self._momentum_signal(sym)
                atrs[sym] = float(atr_v)
                prices[sym] = last
            else:
                signals[sym] = 0

        orders: dict[str, Optional[Order]] = {}
        # 1) 기존 포지션 종료: 추세반전 또는 스탑/트레일링
        for sym in self.symbols:
            if sym not in self._position_state:
                continue
            info = self._position_state[sym]
            side = info["side"]
            price = prices.get(sym)
            atr = atrs.get(sym)
            if price is None or atr is None:
                continue

            if side == "LONG":
                # 트레일 스탑 갱신
                trail = max(info["trailing_stop"], price - atr * self.trail_atr)
                info["trailing_stop"] = trail

                if price <= trail or signals.get(sym) == -1:
                    qty = info.get("qty", 0.0)
                    if qty > 0:
                        orders[sym] = Order(
                            side=Side.SELL,
                            quantity=qty,
                            order_type=OrderType.MARKET,
                        )
                    continue
            else:  # SHORT
                trail = min(info["trailing_stop"], price + atr * self.trail_atr)
                info["trailing_stop"] = trail

                if price >= trail or signals.get(sym) == 1:
                    qty = info.get("qty", 0.0)
                    if qty > 0:
                        orders[sym] = Order(
                            side=Side.BUY,
                            quantity=qty,
                            order_type=OrderType.MARKET,
                        )

        # close 완료 처리
        for sym in list(self._position_state.keys()):
            if sym in orders and orders[sym] is not None:
                self._position_state.pop(sym, None)

        # 2) 신규 진입 (최대 동시 포지션 수 제한)
        if len(orders) > 0:
            # 이미 이번 바에서 청산이 있으면 슬롯이 비워짐
            pass

        open_count = len(self._position_state)
        if open_count < self.max_open_positions:
            # 우선순위: 신호 강도 (abs(close - slow/fast 기준)
            candidates: list[tuple[str, int, float]] = []
            for sym, sig in signals.items():
                if sig == 0:
                    continue
                if sym in self._position_state:
                    continue
                if sym in orders and orders[sym] is not None:
                    continue
                cands = self._bars[sym]
                close = float(cands["close"].iloc[-1])
                baseline = float(cands["close"].iloc[-self.slow_window - 1])
                score = abs(close - baseline) / baseline
                candidates.append((sym, sig, score))

            candidates.sort(key=lambda x: x[2], reverse=True)
            for sym, sig, _score in candidates:
                if len(self._position_state) >= self.max_open_positions:
                    break

                if sym not in self._bars or sym not in atrs or sym not in prices:
                    continue

                price = prices[sym]
                qty = self._position_qty(sym, sig, price)
                if qty <= 0:
                    continue

                atr = atrs[sym]
                if sig == 1:
                    stop = price - atr * self.stop_atr
                    orders[sym] = Order(
                        side=Side.BUY,
                        quantity=qty,
                        order_type=OrderType.MARKET,
                        limit_price=None,
                        stop_loss=stop,
                    )
                    # NOTE: strategy 측은 수동 트레일링 관리
                    self._position_state[sym] = {
                        "side": "LONG",
                        "entry_price": price,
                        "qty": qty,
                        "trailing_stop": price - atr * self.trail_atr,
                        "entry_atr": atr,
                    }
                elif sig == -1:
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
                        "trailing_stop": price + atr * self.trail_atr,
                        "entry_atr": atr,
                    }

        self.last_state = {
            "timestamp": ts.isoformat() if ts else None,
            "signals": signals,
            "orders": {k: ("LONG" if v and v.side == Side.BUY else "SHORT" if v and v.side == Side.SELL else None) for k, v in orders.items()},
        }

        return orders

    # ── public interface ────────────────────────────────────────────────────────────
    def generate_order(self, state: MarketState) -> PortfolioOrder | None:
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
