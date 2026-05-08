"""Physics-inspired oscillator reversion alpha."""
from __future__ import annotations

from collections import deque
from math import isfinite, log, sqrt
from statistics import mean, median, pstdev
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


class PhysicsOscillatorReversion:
    """Long low oscillator states and short high oscillator states.

    Price is treated as a damped oscillator around a slow EMA equilibrium. The
    signal estimates a positive spring constant from recent displacement,
    velocity, and acceleration, then scores how strongly the current state
    should mean-revert toward equilibrium.
    """

    def __init__(
        self,
        symbols: list[str],
        alpha_id: str = "physics_oscillator_reversion",
        equilibrium_window: int = 720,
        stiffness_window: int = 240,
        vol_window: int = 720,
        rebalance_bars: int = 120,
        entry_threshold: float = 0.8,
        exit_threshold: float = 0.15,
        damping: float = 0.35,
        max_weight: float = 0.18,
        top_k: int = 2,
        side_mode: str = "long_short",
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.alpha_id = alpha_id
        self.equilibrium_window = max(8, int(equilibrium_window))
        self.stiffness_window = max(12, int(stiffness_window))
        self.vol_window = max(12, int(vol_window))
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.entry_threshold = float(entry_threshold)
        self.exit_threshold = float(exit_threshold)
        self.damping = max(0.0, float(damping))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self.top_k = max(1, int(top_k))
        self.side_mode = side_mode

        maxlen = max(self.equilibrium_window, self.stiffness_window, self.vol_window) + 8
        self._log_prices: dict[str, deque[float]] = {
            symbol: deque(maxlen=maxlen)
            for symbol in self.symbols
        }
        self._displacements: dict[str, deque[float]] = {
            symbol: deque(maxlen=maxlen)
            for symbol in self.symbols
        }
        self._equilibrium: dict[str, float | None] = {symbol: None for symbol in self.symbols}
        self._bar_count = 0

    def _update_equilibrium(self, symbol: str, value: float) -> float | None:
        prices = self._log_prices[symbol]
        current = self._equilibrium[symbol]
        if current is None:
            if len(prices) < self.equilibrium_window:
                return None
            current = mean(list(prices)[-self.equilibrium_window:])
        else:
            alpha = 2.0 / (self.equilibrium_window + 1.0)
            current = alpha * value + (1.0 - alpha) * current
        self._equilibrium[symbol] = current
        return current

    def _score_symbol(self, symbol: str) -> float | None:
        if len(self._log_prices[symbol]) < self.equilibrium_window:
            return None
        displacements = list(self._displacements[symbol])
        if len(displacements) < max(self.stiffness_window, self.vol_window) + 3:
            return None

        x0, x1, x2 = displacements[-3], displacements[-2], displacements[-1]
        x = x2
        velocity = x2 - x1
        acceleration = x2 - 2.0 * x1 + x0

        k_samples = []
        recent = displacements[-self.stiffness_window:]
        for prev, cur, nxt in zip(recent[:-2], recent[1:-1], recent[2:]):
            v = cur - prev
            a = nxt - 2.0 * cur + prev
            if abs(cur) < 1e-8:
                continue
            k = -(a + self.damping * v) / cur
            if isfinite(k) and k > 0:
                k_samples.append(k)
        if not k_samples:
            return None

        stiffness = median(k_samples)
        vol_sample = displacements[-self.vol_window:]
        vol = pstdev(vol_sample) or 0.0
        if vol <= 0:
            return None

        displacement_z = x / vol
        restoring_force = -stiffness * x
        phase_penalty = max(0.0, velocity * displacement_z)
        oscillator_energy = 0.5 * velocity * velocity + 0.5 * stiffness * x * x
        energy_scale = 1.0 + sqrt(max(0.0, oscillator_energy)) / vol

        score = (-displacement_z + restoring_force / vol - phase_penalty) * energy_scale
        return score if isfinite(score) else None

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
            if close is None or close <= 0:
                continue
            logs = self._log_prices[symbol]
            logs.append(log(float(close)))
            equilibrium = self._update_equilibrium(symbol, logs[-1])
            if equilibrium is not None:
                self._displacements[symbol].append(logs[-1] - equilibrium)

        self._bar_count += 1
        if self._bar_count % self.rebalance_bars != 0:
            return None

        scores = {
            symbol: score
            for symbol in self.symbols
            if (score := self._score_symbol(symbol)) is not None
        }
        if not scores:
            return None

        longs = sorted(
            ((s, v) for s, v in scores.items() if v > self.entry_threshold),
            key=lambda item: item[1],
            reverse=True,
        )[: self.top_k]
        shorts = sorted(
            ((s, v) for s, v in scores.items() if v < -self.entry_threshold),
            key=lambda item: item[1],
        )[: self.top_k]

        if self.side_mode == "long_only":
            shorts = []
        elif self.side_mode == "short_only":
            longs = []

        targets = {symbol: 0 for symbol in self.symbols}
        for symbol, _ in longs:
            targets[symbol] = 1
        for symbol, _ in shorts:
            targets[symbol] = -1

        active_count = sum(1 for target in targets.values() if target)
        weight = min(self.max_weight, 1.0 / active_count) if active_count else 0.0

        orders: dict[str, Order | None] = {}
        for symbol, target in targets.items():
            current_side = self._position_side(state, symbol)
            score = scores.get(symbol, 0.0)
            if target == 1:
                orders[symbol] = None if current_side == "LONG" else Order(
                    side=Side.BUY,
                    quantity=0.0,
                    weight=weight,
                    order_type=OrderType.MARKET,
                )
            elif target == -1:
                orders[symbol] = None if current_side == "SHORT" else Order(
                    side=Side.SELL,
                    quantity=0.0,
                    weight=weight,
                    order_type=OrderType.MARKET,
                )
            elif abs(score) < self.exit_threshold:
                orders[symbol] = self._close_order(current_side)
            else:
                orders[symbol] = None

        return PortfolioOrder(orders=orders) if any(order is not None for order in orders.values()) else None
