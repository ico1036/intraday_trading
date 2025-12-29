"""
데이터 로더

Parquet 파일에서 AggTrade 및 OrderbookSnapshot을 로드합니다.

교육 포인트:
    - Iterator 패턴으로 메모리 효율적 처리
    - 여러 파일을 시간순으로 자동 병합
    - 기존 DTO (AggTrade, OrderbookSnapshot)와 호환
"""

from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional, Union

import pandas as pd

from ..client import AggTrade, OrderbookSnapshot


class TickDataLoader:
    """
    Parquet에서 AggTrade 로드
    
    사용 예시:
        loader = TickDataLoader(Path("./data/ticks"))
        
        for trade in loader.iter_trades():
            print(trade.price, trade.quantity)
    
    교육 포인트:
        - Parquet는 컬럼 기반이라 특정 컬럼만 읽을 때 빠름
        - Iterator로 한 번에 메모리에 올리지 않고 처리 가능
    """
    
    def __init__(
        self,
        data_path: Union[Path, str],
        symbol: Optional[str] = None,
    ):
        """
        Args:
            data_path: Parquet 파일 또는 디렉토리 경로
            symbol: 필터링할 심볼 (None이면 모든 심볼)
        """
        self.data_path = Path(data_path)
        self.symbol = symbol.upper() if symbol else None
        self._files: list[Path] = []
        self._load_files()
    
    def _load_files(self) -> None:
        """Parquet 파일 목록 로드"""
        if self.data_path.is_file():
            self._files = [self.data_path]
        elif self.data_path.is_dir():
            pattern = "*.parquet"
            if self.symbol:
                pattern = f"{self.symbol}*.parquet"
            self._files = sorted(self.data_path.glob(pattern))
        else:
            raise FileNotFoundError(f"Path not found: {self.data_path}")
        
        if not self._files:
            raise FileNotFoundError(f"No parquet files found in {self.data_path}")
        
        print(f"[TickDataLoader] Found {len(self._files)} file(s)")
    
    def iter_trades(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        chunk_size: int = 100000,
    ) -> Iterator[AggTrade]:
        """
        AggTrade를 시간순으로 yield
        
        Args:
            start_time: 시작 시간 (None이면 처음부터)
            end_time: 종료 시간 (None이면 끝까지)
            chunk_size: 한 번에 읽을 행 수 (메모리 효율)
            
        Yields:
            AggTrade 객체
            
        교육 포인트:
            - 큰 파일도 청크 단위로 읽어 메모리 절약
            - 시간 필터링으로 필요한 구간만 처리
        """
        for filepath in self._files:
            # Parquet 파일 읽기
            df = pd.read_parquet(filepath)
            
            # timestamp 컬럼 확인 및 변환
            if "timestamp" not in df.columns:
                print(f"[TickDataLoader] Warning: No timestamp column in {filepath}")
                continue
            
            # 시간 필터링
            if start_time:
                df = df[df["timestamp"] >= start_time]
            if end_time:
                df = df[df["timestamp"] <= end_time]
            
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
            start_time: 시작 시간
            end_time: 종료 시간
            
        Returns:
            병합된 DataFrame
            
        Note:
            큰 데이터셋에서는 메모리 주의!
        """
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


class OrderbookDataLoader:
    """
    Parquet에서 OrderbookSnapshot 로드
    
    사용 예시:
        loader = OrderbookDataLoader(Path("./data/orderbook"))
        
        for snapshot in loader.iter_snapshots():
            print(snapshot.bids[0], snapshot.asks[0])
    
    교육 포인트:
        - 저장 시 플랫 구조 (bid_price_0, bid_qty_0, ...)
        - 로드 시 다시 리스트 구조로 복원
    """
    
    def __init__(
        self,
        data_path: Union[Path, str],
        symbol: Optional[str] = None,
    ):
        """
        Args:
            data_path: Parquet 파일 또는 디렉토리 경로
            symbol: 필터링할 심볼 (None이면 모든 심볼)
        """
        self.data_path = Path(data_path)
        self.symbol = symbol.lower() if symbol else None
        self._files: list[Path] = []
        self._depth_levels: int = 20  # 기본값, 파일에서 감지
        self._load_files()
    
    def _load_files(self) -> None:
        """Parquet 파일 목록 로드"""
        if self.data_path.is_file():
            self._files = [self.data_path]
        elif self.data_path.is_dir():
            pattern = "orderbook*.parquet"
            if self.symbol:
                pattern = f"orderbook_{self.symbol}*.parquet"
            self._files = sorted(self.data_path.glob(pattern))
        else:
            raise FileNotFoundError(f"Path not found: {self.data_path}")
        
        if not self._files:
            raise FileNotFoundError(f"No orderbook parquet files found in {self.data_path}")
        
        # depth levels 감지
        self._detect_depth_levels()
        
        print(f"[OrderbookDataLoader] Found {len(self._files)} file(s), depth={self._depth_levels}")
    
    def _detect_depth_levels(self) -> None:
        """파일에서 depth levels 감지"""
        if not self._files:
            return
        
        # 첫 번째 파일의 컬럼에서 감지
        df = pd.read_parquet(self._files[0], columns=None)
        
        # bid_price_X 컬럼 수로 감지
        bid_cols = [c for c in df.columns if c.startswith("bid_price_")]
        if bid_cols:
            self._depth_levels = len(bid_cols)
    
    def iter_snapshots(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> Iterator[OrderbookSnapshot]:
        """
        OrderbookSnapshot을 시간순으로 yield
        
        Args:
            start_time: 시작 시간 (None이면 처음부터)
            end_time: 종료 시간 (None이면 끝까지)
            
        Yields:
            OrderbookSnapshot 객체
            
        교육 포인트:
            - 플랫 구조에서 리스트 구조로 복원
            - [(price, qty), ...] 형태로 변환
        """
        for filepath in self._files:
            df = pd.read_parquet(filepath)
            
            if df.empty:
                continue
            
            # timestamp 필터링
            if "timestamp" not in df.columns:
                print(f"[OrderbookDataLoader] Warning: No timestamp in {filepath}")
                continue
            
            if start_time:
                df = df[df["timestamp"] >= start_time]
            if end_time:
                df = df[df["timestamp"] <= end_time]
            
            df = df.sort_values("timestamp")
            
            # 각 행을 OrderbookSnapshot으로 변환
            for _, row in df.iterrows():
                # Bids 복원
                bids = []
                for i in range(self._depth_levels):
                    price_col = f"bid_price_{i}"
                    qty_col = f"bid_qty_{i}"
                    if price_col in row and qty_col in row:
                        price = row[price_col]
                        qty = row[qty_col]
                        if pd.notna(price) and pd.notna(qty):
                            bids.append((float(price), float(qty)))
                
                # Asks 복원
                asks = []
                for i in range(self._depth_levels):
                    price_col = f"ask_price_{i}"
                    qty_col = f"ask_qty_{i}"
                    if price_col in row and qty_col in row:
                        price = row[price_col]
                        qty = row[qty_col]
                        if pd.notna(price) and pd.notna(qty):
                            asks.append((float(price), float(qty)))
                
                yield OrderbookSnapshot(
                    timestamp=row["timestamp"].to_pydatetime() if hasattr(row["timestamp"], "to_pydatetime") else row["timestamp"],
                    last_update_id=int(row.get("last_update_id", 0)),
                    bids=bids,
                    asks=asks,
                    symbol=str(row.get("symbol", self.symbol or "UNKNOWN")).upper(),
                )
    
    def to_dataframe(
        self,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """
        전체 데이터를 DataFrame으로 로드 (플랫 구조)
        
        Args:
            start_time: 시작 시간
            end_time: 종료 시간
            
        Returns:
            병합된 DataFrame
        """
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
    
    @property
    def depth_levels(self) -> int:
        """감지된 호가 깊이"""
        return self._depth_levels




