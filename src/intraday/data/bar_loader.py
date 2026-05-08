"""Historical OHLCV bar data loader."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterator

import pandas as pd


class BarDataLoader:
    """Load parquet OHLCV bars and yield :class:`Candle` objects."""

    def __init__(
        self,
        data_path: Path | str,
        symbol: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ):
        self.data_path = Path(data_path)
        self.symbol = symbol.upper() if symbol else None
        self.default_start_time = start_time
        self.default_end_time = end_time
        self._files: list[Path] = []
        self._load_files()

    def _load_files(self) -> None:
        if self.data_path.is_file():
            self._files = [self.data_path]
        elif self.data_path.is_dir():
            self._files = sorted(self.data_path.rglob("*.parquet"))
            if self.symbol and self.data_path.name.upper() != self.symbol:
                self._files = [f for f in self._files if self.symbol in f.name.upper()]
        else:
            raise FileNotFoundError(f"Path not found: {self.data_path}")

        if not self._files:
            raise FileNotFoundError(f"No parquet files found in {self.data_path}")

    def estimate_total_rows(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> int:
        return len(self.to_dataframe(start_time, end_time))

    def to_dataframe(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> pd.DataFrame:
        start_time = start_time or self.default_start_time
        end_time = end_time or self.default_end_time
        dfs = [pd.read_parquet(path) for path in self._files]
        df = pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()
        if df.empty:
            return df

        if "timestamp" not in df.columns:
            raise ValueError(f"bar data missing timestamp column: {self.data_path}")
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        if self.symbol and "symbol" in df.columns:
            df = df[df["symbol"].str.upper() == self.symbol]
        if start_time:
            df = df[df["timestamp"] >= start_time]
        if end_time:
            df = df[df["timestamp"] <= end_time]
        return df.sort_values("timestamp").reset_index(drop=True)

    def iter_bars(
        self,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> Iterator[object]:
        from ..candle_builder import Candle

        df = self.to_dataframe(start_time, end_time)
        for _, row in df.iterrows():
            volume = float(row["volume"])
            taker_buy_volume = float(row.get("taker_buy_volume", 0.0) or 0.0)
            sell_volume = max(0.0, volume - taker_buy_volume)
            yield Candle(
                timestamp=row["timestamp"].to_pydatetime()
                if hasattr(row["timestamp"], "to_pydatetime")
                else row["timestamp"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=volume,
                quote_volume=float(row.get("quote_volume", 0.0) or 0.0),
                trade_count=int(row.get("trade_count", 0) or 0),
                buy_volume=taker_buy_volume,
                sell_volume=sell_volume,
            )
