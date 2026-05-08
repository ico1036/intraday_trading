"""is_005 — orderflow × price confluence cross-section.

Hypothesis: cross-sectional rank by composite of price-return z-score and
CVD-ratio z-score is more discriminating than either alone, because
orderflow filters out price moves driven by passive flow / mechanical
rebalancing. Trade only the symbols where both signals agree in sign and
the composite rank is at the extreme.

Design choices:
    - 8h lookback (480 bars) — captures intraday session orderflow
    - 4h rebalance (240 bars) — twice-daily decision pace
    - top-1 long / bottom-1 short by composite
    - require sign(z_price) == sign(z_cvd) at the picked symbol; else hold cash
    - direction parameter: ``"continuation"`` or ``"reversion"``
"""
from __future__ import annotations

import math
from collections import deque
from statistics import mean, pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


class OrderflowPriceConfluenceStrategy:
    def __init__(
        self,
        symbols: list[str],
        lookback_bars: int = 480,
        rebalance_bars: int = 240,
        top_k: int = 1,
        max_weight: float = 0.4,
        direction: str = "continuation",
        require_agreement: bool = True,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        if direction not in {"continuation", "reversion"}:
            raise ValueError("direction must be 'continuation' or 'reversion'")

        self.symbols = [s.upper() for s in symbols]
        self.lookback_bars = max(2, int(lookback_bars))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.top_k = max(1, int(top_k))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self.direction = direction
        self.require_agreement = bool(require_agreement)

        self._closes: dict[str, deque[float]] = {
            s: deque(maxlen=self.lookback_bars + 1) for s in self.symbols
        }
        self._signed_vol: dict[str, deque[float]] = {
            s: deque(maxlen=self.lookback_bars) for s in self.symbols
        }
        self._total_vol: dict[str, deque[float]] = {
            s: deque(maxlen=self.lookback_bars) for s in self.symbols
        }
        self._bar_count = 0

    def _price_return(self, symbol: str) -> float | None:
        c = self._closes[symbol]
        if len(c) < self.lookback_bars + 1:
            return None
        start, end = c[0], c[-1]
        if start <= 0:
            return None
        return (end - start) / start

    def _cvd_ratio(self, symbol: str) -> float | None:
        sv = self._signed_vol[symbol]
        tv = self._total_vol[symbol]
        if len(sv) < self.lookback_bars:
            return None
        total = sum(tv)
        if total <= 0:
            return None
        return sum(sv) / total

    def _xs_z(self, values: dict[str, float]) -> dict[str, float]:
        if len(values) < 2:
            return {}
        mu = mean(values.values())
        sigma = pstdev(values.values())
        if sigma <= 0 or not math.isfinite(sigma):
            return {}
        return {s: (v - mu) / sigma for s, v in values.items()}

    def _position_side(self, state: MarketState, symbol: str) -> str | None:
        if not state.positions:
            return None
        info = state.positions.get(symbol)
        if not info:
            return None
        side = info.get("side")
        return side if side in {"LONG", "SHORT"} else None

    def _close_order(self, side: str | None) -> Order | None:
        if side == "LONG":
            return Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
        if side == "SHORT":
            return Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
        return None

    def generate_order(self, state: MarketState) -> PortfolioOrder | None:
        if state.panel is None:
            return None

        for symbol in self.symbols:
            data = state.panel.get(symbol)
            if not data:
                continue
            close = data.get("close")
            vol = data.get("volume")
            imb = data.get("volume_imbalance")
            if close is not None and float(close) > 0 and math.isfinite(float(close)):
                self._closes[symbol].append(float(close))
            if vol is None or imb is None:
                continue
            v = float(vol)
            i = float(imb)
            if not (math.isfinite(v) and math.isfinite(i)) or v <= 0:
                continue
            self._signed_vol[symbol].append(i * v)
            self._total_vol[symbol].append(v)

        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0:
            return None

        price_rets: dict[str, float] = {}
        cvds: dict[str, float] = {}
        for symbol in self.symbols:
            pr = self._price_return(symbol)
            cv = self._cvd_ratio(symbol)
            if pr is None or cv is None:
                continue
            price_rets[symbol] = pr
            cvds[symbol] = cv

        if len(price_rets) < 2 * self.top_k:
            return None

        z_price = self._xs_z(price_rets)
        z_cvd = self._xs_z(cvds)
        if not z_price or not z_cvd:
            return None

        composite: dict[str, float] = {}
        for symbol in price_rets:
            zp = z_price[symbol]
            zc = z_cvd[symbol]
            if self.require_agreement and (zp * zc) <= 0:
                continue
            composite[symbol] = zp + zc

        if len(composite) < 2 * self.top_k:
            longs: set[str] = set()
            shorts: set[str] = set()
        else:
            sorted_syms = sorted(composite.keys(), key=lambda s: composite[s])
            bottom = set(sorted_syms[: self.top_k])
            top = set(sorted_syms[-self.top_k :])
            if self.direction == "continuation":
                longs, shorts = top, bottom
            else:
                longs, shorts = bottom, top

        n_active = len(longs) + len(shorts)
        per_leg_weight = (
            min(self.max_weight, 1.0 / n_active) if n_active > 0 else 0.0
        )

        orders: dict[str, Order | None] = {}
        for symbol in self.symbols:
            current_side = self._position_side(state, symbol)
            if symbol in longs:
                orders[symbol] = (
                    None
                    if current_side == "LONG"
                    else Order(
                        side=Side.BUY,
                        quantity=0.0,
                        weight=per_leg_weight,
                        order_type=OrderType.MARKET,
                    )
                )
            elif symbol in shorts:
                orders[symbol] = (
                    None
                    if current_side == "SHORT"
                    else Order(
                        side=Side.SELL,
                        quantity=0.0,
                        weight=per_leg_weight,
                        order_type=OrderType.MARKET,
                    )
                )
            else:
                orders[symbol] = self._close_order(current_side)

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None
