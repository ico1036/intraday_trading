"""Replay a precomputed combined-weights series through the standard backtest engine.

This strategy is a pure adapter: it loads a long-format parquet of
``(timestamp, symbol, target_weight)`` rebalance events produced by a composite
build step and emits the corresponding ``PortfolioOrder`` whenever the engine
visits a scheduled bar. All combination logic lives in the upstream build
script; the adapter performs no combination of its own.

Expected parquet schema:

- ``timestamp``  datetime64[ns]
- ``symbol``     str
- ``target_weight``  float (signed; magnitude in [0, 1])

Only rows where the per-symbol target changes from the previous bar should be
included; unchanged symbols are simply omitted (the engine retains the prior
target until a new event arrives).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from intraday.strategy import MarketState, Order, OrderType, PortfolioOrder, Side


ALPHA_CELL = {
    "bar": "TIME",
    "transform": "composite",
    "horizon": "intraday",
    "universe": "basket_full",
    "exit": "signal_flip",
    "idea_family": "precomputed_weights_replay",
}
SOURCE_NOTES: list[str] = ["research/notes/composite_alpha_method.md"]


_FLAT_EPS = 1e-9


class PrecomputedWeightsStrategy:
    """Replay a (timestamp, symbol, target_weight) schedule.

    Parameters
    ----------
    symbols
        Run universe; injected by the backtest CLI from ``--symbols``.
    weights_path
        Path to the long-format combined weights parquet.
    alpha_id
        Identifier recorded in the output ``weights.parquet``.
    """

    def __init__(
        self,
        symbols: list[str],
        weights_path: str,
        alpha_id: str = "precomputed_replay",
        **_: Any,
    ):
        if not symbols:
            raise ValueError("symbols must contain at least one symbol")
        self.symbols = [s.upper() for s in symbols]
        self.alpha_id = alpha_id

        path = Path(weights_path)
        if not path.exists():
            raise FileNotFoundError(f"weights parquet not found: {path}")

        df = pd.read_parquet(path)
        required = {"timestamp", "symbol", "target_weight"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"weights parquet missing columns: {sorted(missing)}")
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["symbol"] = df["symbol"].astype(str).str.upper()

        unknown = set(df["symbol"]) - set(self.symbols)
        if unknown:
            raise ValueError(
                f"weights parquet contains symbols outside run universe: {sorted(unknown)}"
            )

        self._schedule: dict[pd.Timestamp, dict[str, float]] = {
            ts: g.set_index("symbol")["target_weight"].astype(float).to_dict()
            for ts, g in df.groupby("timestamp")
        }
        self._weights_path = str(path)
        self._row_count = len(df)
        self._n_timestamps = len(self._schedule)

    @staticmethod
    def _close_order(side: str | None) -> Order | None:
        if side == "LONG":
            return Order(side=Side.SELL, quantity=0.0, order_type=OrderType.MARKET)
        if side == "SHORT":
            return Order(side=Side.BUY, quantity=0.0, order_type=OrderType.MARKET)
        return None

    def generate_order(self, state: MarketState) -> PortfolioOrder | None:
        ts = getattr(state, "timestamp", None)
        if ts is None:
            return None
        targets = self._schedule.get(pd.Timestamp(ts))
        if not targets:
            return None

        positions = getattr(state, "positions", None) or {}
        orders: dict[str, Order | None] = {}
        for sym, raw in targets.items():
            if sym not in self.symbols:
                continue
            weight = float(raw)
            cur_side = (positions.get(sym) or {}).get("side")
            if abs(weight) < _FLAT_EPS:
                close = self._close_order(cur_side)
                if close is not None:
                    orders[sym] = close
                continue
            magnitude = min(abs(weight), 1.0)
            side = Side.BUY if weight > 0 else Side.SELL
            orders[sym] = Order(
                side=side,
                quantity=0.0,
                weight=magnitude,
                order_type=OrderType.MARKET,
            )

        if not orders:
            return None
        return PortfolioOrder(orders=orders)

    def describe(self) -> dict[str, Any]:
        return {
            "alpha_id": self.alpha_id,
            "weights_path": self._weights_path,
            "n_rows": self._row_count,
            "n_timestamps": self._n_timestamps,
            "symbols": self.symbols,
        }
