"""Cross-sectional regression alpha base.

Each emit bar t fits a daily cross-sectional model on the eligible
universe:

    target_i  = next-bar return of symbol i
    features_i = vector of recent signals (mom_5d, vol_20d, ...) for i
    fit       = ridge OLS or numpy linear-regression of target ~ features

We don't have future returns at decision time, so the model trains on
a *rolling window of past N days* and predicts today's cross-section
weights. The predicted score is rank-normalised to give equal-weight
long/short legs over the top/bottom ``concentration_pct`` slice.

Same emit semantics as XsFactorBase (day-flip emit + same-day
universe). Subclasses just plug in:

    FEATURE_FNS : ordered list of feature-extractor callables
    RIDGE_ALPHA : float regularisation
    TRAIN_WINDOW: int rolling days

The class is intentionally tiny — heavy lifting is the per-bar fit.
"""
from __future__ import annotations

from collections import deque
from typing import Any, Callable

import math

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


class XsRegressionBase:
    HISTORY_FIELDS: tuple[str, ...] = ("close", "quote_volume")
    HISTORY_LEN: int = 120
    FEATURE_FNS: tuple[Callable[[dict], float | None], ...] = ()
    RIDGE_ALPHA: float = 1.0
    TRAIN_WINDOW: int = 60

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

        # symbol → field → deque
        self._history: dict[str, dict[str, deque]] = {
            s: {f: deque(maxlen=self.HISTORY_LEN) for f in self.HISTORY_FIELDS}
            for s in self.symbols
        }
        self._today: dict[str, dict[str, float | None]] = {
            s: {f: None for f in self.HISTORY_FIELDS} for s in self.symbols
        }
        self._current_date = None
        self._bar = 0

        # Rolling training set: per day,  X (n_syms × n_features), y (n_syms)
        self._train_X: deque[list[list[float]]] = deque(maxlen=self.TRAIN_WINDOW)
        self._train_y: deque[list[float]] = deque(maxlen=self.TRAIN_WINDOW)
        # The previous emit's feature snapshot — paired with realised next
        # return on the following day commit.
        self._pending_features: list[tuple[str, list[float]]] | None = None
        self._pending_close_by_sym: dict[str, float] = {}

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
        # 1. realise yesterday's training labels (next-bar return) for
        #    each symbol that had a pending feature row.
        if self._pending_features is not None:
            xs, ys = [], []
            for sym, feats in self._pending_features:
                prev = self._pending_close_by_sym.get(sym)
                today = self._today[sym].get("close")
                if prev is None or today is None or prev <= 0:
                    continue
                ret = today / prev - 1.0
                xs.append(feats)
                ys.append(ret)
            if xs:
                self._train_X.append(xs)
                self._train_y.append(ys)
            self._pending_features = None
            self._pending_close_by_sym = {}

        # 2. roll today's readings into the per-symbol history
        for sym in self.symbols:
            for f in self.HISTORY_FIELDS:
                v = self._today[sym].get(f)
                if v is not None:
                    self._history[sym][f].append(float(v))
            self._today[sym] = {f: None for f in self.HISTORY_FIELDS}

    # ----- feature build + ridge fit -----
    def _features_for(self, sym: str) -> list[float] | None:
        hist = {f: list(self._history[sym][f]) for f in self.HISTORY_FIELDS}
        if not hist[self.HISTORY_FIELDS[0]]:
            return None
        feats: list[float] = []
        for fn in self.FEATURE_FNS:
            try:
                v = fn(hist)
            except Exception:
                return None
            if v is None or (isinstance(v, float) and v != v):
                return None
            try:
                feats.append(float(v))
            except (TypeError, ValueError):
                return None
        return feats

    def _ridge_fit_predict(self, train_xs: list[list[list[float]]],
                           train_ys: list[list[float]],
                           today_X: list[list[float]]) -> list[float]:
        """Pool every training day's cross-section into one (N, K) matrix,
        fit ridge β = (XᵀX + αI)⁻¹ Xᵀy by hand (no sklearn), then return
        today_X @ β as per-symbol predictions."""
        rows: list[list[float]] = []
        ys: list[float] = []
        for xs, ysl in zip(train_xs, train_ys):
            rows.extend(xs)
            ys.extend(ysl)
        if not rows:
            return [0.0] * len(today_X)
        k = len(rows[0])
        # XᵀX (k × k)
        xtx = [[0.0] * k for _ in range(k)]
        xty = [0.0] * k
        for r, yv in zip(rows, ys):
            if len(r) != k:
                continue
            for a in range(k):
                xty[a] += r[a] * yv
                for b in range(k):
                    xtx[a][b] += r[a] * r[b]
        # ridge: add αI
        for a in range(k):
            xtx[a][a] += self.RIDGE_ALPHA
        # Solve via Gauss elimination
        beta = _solve(xtx, xty)
        if beta is None:
            return [0.0] * len(today_X)
        out: list[float] = []
        for row in today_X:
            if len(row) != k:
                out.append(0.0)
            else:
                out.append(sum(row[a] * beta[a] for a in range(k)))
        return out

    def _build_orders(self, state: MarketState) -> PortfolioOrder | None:
        eligible: list[str] = []
        today_X: list[list[float]] = []
        today_close: dict[str, float] = {}
        for sym in self.symbols:
            feats = self._features_for(sym)
            if feats is None:
                continue
            close = self._history[sym]["close"][-1] if self._history[sym]["close"] else None
            if close is None or close <= 0:
                continue
            eligible.append(sym)
            today_X.append(feats)
            today_close[sym] = float(close)
        if len(eligible) < 4 or not self._train_X:
            # Cache today's feature snapshot for labelling tomorrow.
            self._pending_features = list(zip(eligible, today_X))
            self._pending_close_by_sym = today_close
            return None

        preds = self._ridge_fit_predict(list(self._train_X), list(self._train_y), today_X)
        # cache for tomorrow's labelling
        self._pending_features = list(zip(eligible, today_X))
        self._pending_close_by_sym = today_close

        ranked = sorted(zip(eligible, preds), key=lambda kv: kv[1])
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
            if data is None: continue
            sym_ts = data.get("timestamp")
            if sym_ts is None or sym_ts.date() != current_date: continue
            for f in self.HISTORY_FIELDS:
                v = data.get(f)
                if v is None: continue
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    continue
                self._today[sym][f] = fv
        return orders


def _solve(A: list[list[float]], b: list[float]) -> list[float] | None:
    """Naive Gauss elimination, k × k. k stays ≤ ~20 in practice."""
    n = len(A)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-12:
            return None
        M[col], M[piv] = M[piv], M[col]
        for r in range(col + 1, n):
            f = M[r][col] / M[col][col]
            for c in range(col, n + 1):
                M[r][c] -= f * M[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (M[r][n] - sum(M[r][c] * x[c] for c in range(r + 1, n))) / M[r][r]
    return x
