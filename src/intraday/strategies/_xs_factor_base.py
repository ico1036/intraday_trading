"""Shared XS factor strategy base.

A generic cross-section ranker: each emit bar t, score every symbol by
``_compute_score(history)``, rank, take the top/bottom ``concentration_pct``
slice, equal-weight per leg. Direction = ``reverse``: when True, bottom
gets longs and top gets shorts (the "fade" pattern the volume-rank
alphas use). When False, top gets longs.

Generated alpha modules subclass this and only override
``_compute_score`` plus the ALPHA_CELL idea_family. Same-day universe
semantics (yesterday's qv must be > 0 to be eligible) are inherited.
"""
from __future__ import annotations

from collections import deque
from typing import Any

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


class XsFactorBase:
    """Base class for cross-section single-factor long/short alphas."""

    # Subclasses override these.
    HISTORY_FIELDS: tuple[str, ...] = ("close", "quote_volume")
    HISTORY_LEN: int = 64

    def __init__(
        self,
        symbols: list[str],
        rebalance_bars: int = 1,
        max_weight: float = 0.20,
        concentration_pct: float = 0.10,
        reverse: bool = False,
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.rebalance_bars = max(1, int(rebalance_bars))
        self.max_weight = max(0.0, min(1.0, float(max_weight)))
        self.concentration_pct = max(0.01, min(0.5, float(concentration_pct)))
        self.reverse = bool(reverse)

        self._history: dict[str, dict[str, deque]] = {
            s: {f: deque(maxlen=self.HISTORY_LEN) for f in self.HISTORY_FIELDS}
            for s in self.symbols
        }
        # today_<field> accumulates the current bar's reading until the day
        # rolls over and commit_yesterday() folds it into history.
        self._today: dict[str, dict[str, float | None]] = {
            s: {f: None for f in self.HISTORY_FIELDS} for s in self.symbols
        }
        self._current_date = None
        self._bar = 0

    # ----- subclass hook -----
    def _compute_score(self, hist: dict[str, list[float]]) -> float | None:
        """Return signed signal score from this symbol's full history.

        ``hist`` is a dict {field -> list[float]} of length up to
        HISTORY_LEN. Return ``None`` if the score is undefined (e.g.
        insufficient history).
        """
        raise NotImplementedError

    # ----- emit machinery -----
    def _side(self, state: MarketState, sym: str) -> str | None:
        if not state.positions: return None
        info = state.positions.get(sym)
        if not info: return None
        sd = info.get("side")
        return sd if sd in {"LONG", "SHORT"} else None

    def _close_order(self, side: str | None) -> Order | None:
        if side == "LONG":
            return Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
        if side == "SHORT":
            return Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
        return None

    def _commit_yesterday(self) -> None:
        # Same-day semantics: only symbols that reported today join the
        # next ranking universe.
        for sym in self.symbols:
            today = self._today[sym]
            if today.get(self.HISTORY_FIELDS[0]) is None:
                # No fresh reading today — clear history's "ready" sentinel by
                # NOT appending. Stale data drops out organically once the
                # history fills with newer values from other days.
                pass
            else:
                for f in self.HISTORY_FIELDS:
                    v = today.get(f)
                    if v is not None:
                        self._history[sym][f].append(float(v))
            self._today[sym] = {f: None for f in self.HISTORY_FIELDS}

    def _build_orders(self, state: MarketState) -> PortfolioOrder | None:
        scores: dict[str, float] = {}
        for sym in self.symbols:
            hist = {f: list(self._history[sym][f]) for f in self.HISTORY_FIELDS}
            primary = hist[self.HISTORY_FIELDS[0]]
            if not primary:
                continue
            try:
                s = self._compute_score(hist)
            except Exception:
                s = None
            if s is None:
                continue
            try:
                fv = float(s)
            except (TypeError, ValueError):
                continue
            if fv != fv:  # NaN
                continue
            scores[sym] = fv

        if len(scores) < 4:
            return None
        ranked = sorted(scores.items(), key=lambda kv: kv[1])
        k = max(1, int(len(ranked) * self.concentration_pct))
        if self.reverse:
            longs = {s for s, _ in ranked[:k]}
            shorts = {s for s, _ in ranked[-k:]}
        else:
            longs = {s for s, _ in ranked[-k:]}
            shorts = {s for s, _ in ranked[:k]}
        per_leg = min(self.max_weight, 0.5 / k)

        orders: dict[str, Order | None] = {}
        for sym in self.symbols:
            current = self._side(state, sym)
            if sym in longs:
                orders[sym] = Order(side=Side.BUY, quantity=0.0,
                                    weight=per_leg, order_type=OrderType.MARKET)
            elif sym in shorts:
                orders[sym] = Order(side=Side.SELL, quantity=0.0,
                                    weight=per_leg, order_type=OrderType.MARKET)
            else:
                orders[sym] = self._close_order(current)

        active = {s: o for s, o in orders.items() if o is not None}
        return PortfolioOrder(orders=orders) if active else None

    def generate_order(self, state: MarketState) -> PortfolioOrder | None:
        if state.panel is None or state.timestamp is None:
            return None

        current_date = state.timestamp.date()
        orders = None
        if self._current_date is not None and current_date != self._current_date:
            self._commit_yesterday()
            self._bar += 1
            if self._bar % self.rebalance_bars == 0:
                orders = self._build_orders(state)
        self._current_date = current_date

        for sym in self.symbols:
            data = state.panel.get(sym)
            if data is None:
                continue
            sym_ts = data.get("timestamp")
            if sym_ts is None or sym_ts.date() != current_date:
                continue
            for f in self.HISTORY_FIELDS:
                v = data.get(f)
                if v is None:
                    continue
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    continue
                self._today[sym][f] = fv

        return orders
