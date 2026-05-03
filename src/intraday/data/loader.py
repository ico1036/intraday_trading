"""Historical tick data loader."""

from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional, Union

import pandas as pd
import pyarrow.parquet as pq

from ..client import AggTrade
from .timeframe import TimeframeConfig, get_config


class TickDataLoader:
    """
    Parquet에서 AggTrade 로드

    사용 예시:
        # 방법 1: 직접 경로 지정
        loader = TickDataLoader(Path("./data/ticks"))

        # 방법 2: Timeframe 설정 사용 (권장)
        loader = TickDataLoader.from_timeframe(
            symbol="BTCUSDT",
            timeframe="tf1",
            period="is",  # "eda", "is", "os"
        )

        for trade in loader.iter_trades():
            print(trade.price, trade.quantity)

    교육 포인트:
        - Parquet는 컬럼 기반이라 특정 컬럼만 읽을 때 빠름
        - Iterator로 한 번에 메모리에 올리지 않고 처리 가능
        - Timeframe으로 EDA/IS/OS 기간 자동 적용
    """

    def __init__(
        self,
        data_path: Union[Path, str],
        symbol: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ):
        """
        Args:
            data_path: Parquet 파일 또는 디렉토리 경로
            symbol: 필터링할 심볼 (None이면 모든 심볼)
            start_time: 기본 시작 시간 (iter_trades에서 오버라이드 가능)
            end_time: 기본 종료 시간 (iter_trades에서 오버라이드 가능)
        """
        self.data_path = Path(data_path)
        self.symbol = symbol.upper() if symbol else None
        self.default_start_time = start_time
        self.default_end_time = end_time
        self._files: list[Path] = []
        self._load_files()

    @classmethod
    def from_timeframe(
        cls,
        symbol: str,
        timeframe: str = "tf1",
        period: str = "is",
        config: Optional[TimeframeConfig] = None,
    ) -> "TickDataLoader":
        """
        Timeframe 설정으로 로더 생성

        Args:
            symbol: 거래쌍 (예: "BTCUSDT")
            timeframe: 타임프레임 ID (예: "tf1")
            period: 기간 타입 ("eda", "is", "os")
            config: TimeframeConfig 인스턴스 (None이면 기본 사용)

        Returns:
            설정된 TickDataLoader

        사용 예시:
            # IS 기간 데이터 로드
            loader = TickDataLoader.from_timeframe("BTCUSDT", "tf1", "is")

            # OS 기간 데이터 로드
            loader = TickDataLoader.from_timeframe("BTCUSDT", "tf1", "os")
        """
        if config is None:
            config = get_config()

        tf = config.get_timeframe(timeframe)
        p = tf.get_period(period)
        data_path = config.get_data_path(symbol)

        print(f"[TickDataLoader] {symbol} | {timeframe}/{period} | {p}")

        return cls(
            data_path=data_path,
            symbol=symbol,
            start_time=p.start,
            end_time=p.end,
        )

    def _load_files(self) -> None:
        """Parquet 파일 목록 로드 (하위 폴더 포함)"""
        if self.data_path.is_file():
            self._files = [self.data_path]
        elif self.data_path.is_dir():
            # rglob으로 하위 폴더까지 재귀 탐색
            pattern = "*.parquet"
            self._files = sorted(self.data_path.rglob(pattern))

            # 심볼별 디렉터리(BTCUSDT/ticks.parquet)는 파일명에 심볼이 없어도 허용.
            if self.symbol and self.data_path.name.upper() != self.symbol:
                self._files = [f for f in self._files if self.symbol in f.name.upper()]
        else:
            raise FileNotFoundError(f"Path not found: {self.data_path}")

        if not self._files:
            raise FileNotFoundError(f"No parquet files found in {self.data_path}")

        print(f"[TickDataLoader] Found {len(self._files)} file(s)")

    def estimate_total_rows(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> int:
        """
        Estimate total rows matching the given time window.

        - No time filter: read parquet metadata row count.
        - With time filter: count rows per-file after filtering timestamps.
        """
        start_time = start_time or self.default_start_time
        end_time = end_time or self.default_end_time

        total = 0
        for filepath in self._files:
            if start_time is None and end_time is None:
                # Metadata-only fast path
                metadata = pq.ParquetFile(filepath).metadata
                total += int(metadata.num_rows)
                continue

            df = pd.read_parquet(filepath, columns=["timestamp"])
            if df.empty:
                continue

            if start_time:
                start_cmp = start_time.replace(tzinfo=None) if start_time.tzinfo is not None else start_time
                df = df[df["timestamp"] >= start_cmp]
            if end_time:
                end_cmp = end_time.replace(tzinfo=None) if end_time.tzinfo is not None else end_time
                df = df[df["timestamp"] <= end_cmp]

            total += len(df)

        return int(total)

    def iter_trades(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        chunk_size: int = 100000,
    ) -> Iterator[AggTrade]:
        """
        AggTrade를 시간순으로 yield

        Args:
            start_time: 시작 시간 (None이면 기본값 또는 처음부터)
            end_time: 종료 시간 (None이면 기본값 또는 끝까지)
            chunk_size: 한 번에 읽을 행 수 (메모리 효율)

        Yields:
            AggTrade 객체

        교육 포인트:
            - 큰 파일도 청크 단위로 읽어 메모리 절약
            - 시간 필터링으로 필요한 구간만 처리
            - from_timeframe()으로 생성하면 기본 기간 자동 적용
        """
        # 기본값 적용
        start_time = start_time or self.default_start_time
        end_time = end_time or self.default_end_time

        for filepath in self._files:
            # Parquet 파일 읽기
            df = pd.read_parquet(filepath)

            # timestamp 컬럼 확인 및 변환
            if "timestamp" not in df.columns:
                print(f"[TickDataLoader] Warning: No timestamp column in {filepath}")
                continue

            # 시간 필터링 (timezone 통일)
            if start_time:
                # start_time이 timezone-aware면 naive로 변환 (UTC 기준)
                if start_time.tzinfo is not None:
                    start_cmp = start_time.replace(tzinfo=None)
                else:
                    start_cmp = start_time
                df = df[df["timestamp"] >= start_cmp]
            if end_time:
                if end_time.tzinfo is not None:
                    end_cmp = end_time.replace(tzinfo=None)
                else:
                    end_cmp = end_time
                df = df[df["timestamp"] <= end_cmp]

            # 시간순 정렬
            df = df.sort_values("timestamp")

            # AggTrade로 변환하여 yield
            for _, row in df.iterrows():
                yield AggTrade(
                    timestamp=row["timestamp"].to_pydatetime() if hasattr(row["timestamp"], "to_pydatetime") else row["timestamp"],
                    symbol=row.get("symbol", self.symbol or "UNKNOWN"),
                    price=float(row["price"]),
                    quantity=float(row["quantity"]),
                    is_buyer_maker=bool(row["is_buyer_maker"]),
                )

    def to_dataframe(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """
        전체 데이터를 DataFrame으로 로드

        Args:
            start_time: 시작 시간 (None이면 기본값 사용)
            end_time: 종료 시간 (None이면 기본값 사용)

        Returns:
            병합된 DataFrame

        Note:
            큰 데이터셋에서는 메모리 주의!
        """
        # 기본값 적용
        start_time = start_time or self.default_start_time
        end_time = end_time or self.default_end_time

        dfs = []
        for filepath in self._files:
            df = pd.read_parquet(filepath)

            if start_time:
                df = df[df["timestamp"] >= start_time]
            if end_time:
                df = df[df["timestamp"] <= end_time]

            dfs.append(df)

        if not dfs:
            return pd.DataFrame()

        result = pd.concat(dfs, ignore_index=True)
        result = result.sort_values("timestamp").reset_index(drop=True)

        return result

    @property
    def file_count(self) -> int:
        """로드된 파일 수"""
        return len(self._files)
