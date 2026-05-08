"""Funding rate downloader compatibility module.

Provides `FundingRateDownloader` expected by tests and legacy callers.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import requests

from intraday.funding import FundingRate, FundingRateLoader


class FundingRateDownloader:
    """Download and persist funding rate history from Binance Futures REST API."""

    BASE_URL = "https://fapi.binance.com/fapi/v1/fundingRate"
    DEFAULT_LIMIT = 1000

    def _fetch_page(
        self,
        symbol: str,
        start_time_ms: int,
        end_time_ms: int,
        limit: int,
        page: int,
    ):
        params = {
            "symbol": symbol,
            "startTime": int(start_time_ms),
            "endTime": int(end_time_ms),
            "limit": int(limit),
        }
        response = requests.get(self.BASE_URL, params=params, timeout=20)
        response.raise_for_status()
        return response.json()

    def _to_dt(self, ms: int) -> datetime:
        return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)

    def download_range(
        self,
        symbol: str,
        start_time: datetime,
        end_time: datetime,
        limit: int | None = None,
    ) -> list[FundingRate]:
        """Download funding rates in [start_time, end_time]."""
        start_ms = int(start_time.timestamp() * 1000)
        end_ms = int(end_time.timestamp() * 1000)
        page_limit = int(limit or self.DEFAULT_LIMIT)

        out: list[FundingRate] = []
        cursor = start_ms
        while True:
            rows = self._fetch_page(
                symbol=symbol,
                start_time_ms=cursor,
                end_time_ms=end_ms,
                limit=page_limit,
                page=len(out) // page_limit,
            )
            if not isinstance(rows, list):
                break
            if not rows:
                break

            for row in rows:
                ts_ms = int(row["fundingTime"])
                if ts_ms < start_ms or ts_ms > end_ms:
                    continue
                out.append(
                    FundingRate(
                        timestamp=self._to_dt(ts_ms),
                        symbol=row.get("symbol", symbol),
                        funding_rate=float(row["fundingRate"]),
                        mark_price=float(row.get("markPrice", 0.0)),
                    )
                )

            if len(rows) < page_limit:
                break

            # pagination by moving cursor beyond last returned timestamp
            cursor = int(rows[-1]["fundingTime"]) + 1
            if cursor > end_ms:
                break

        return out

    def save_to_parquet(self, rates: Iterable[FundingRate], output_dir: Path | str) -> Path:
        """Save rates to parquet and return file path."""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        output_file = output_dir / "funding_rates.parquet"
        import pandas as pd

        rows = [
            {
                "timestamp": r.timestamp,
                "symbol": r.symbol,
                "funding_rate": r.funding_rate,
                "mark_price": r.mark_price,
            }
            for r in rates
        ]
        pd.DataFrame(rows).to_parquet(output_file, index=False)
        return output_file

    def load_from_parquet(self, file_path: Path | str) -> list[FundingRate]:
        """Load rates from parquet file."""
        import pandas as pd

        df = pd.read_parquet(file_path)
        return [
            FundingRate(
                timestamp=pd.to_datetime(row["timestamp"]).to_pydatetime(),
                symbol=row["symbol"],
                funding_rate=float(row["funding_rate"]),
                mark_price=float(row["mark_price"]),
            )
            for _, row in df.iterrows()
        ]

    def load_as_loader(self, file_path: Path | str) -> FundingRateLoader:
        """Load parquet and return `FundingRateLoader`."""
        return FundingRateLoader.from_list(self.load_from_parquet(file_path))
