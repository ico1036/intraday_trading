"""
Tick 데이터 다운로더

Binance Public Data에서 aggTrades 데이터를 다운로드하여 Parquet로 저장합니다.

교육 포인트:
    - Binance는 https://data.binance.vision/ 에서 무료 히스토리컬 데이터 제공
    - aggTrades: 같은 가격, 같은 방향의 연속 체결을 집계한 데이터
    - 월별/일별 ZIP 파일로 제공됨
"""

import io
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import requests

from ..client import AggTrade


class TickDataDownloader:
    """
    Binance Public Data에서 aggTrades 다운로드
    
    사용 예시:
        downloader = TickDataDownloader()
        filepath = downloader.download_monthly(
            symbol="BTCUSDT",
            year=2024,
            month=1,
            output_dir=Path("./data/ticks")
        )
    
    교육 포인트:
        - 월별 데이터는 약 200MB~1GB (심볼/시장 상황에 따라 다름)
        - 다운로드 후 Parquet로 변환하여 저장 (약 50% 압축)
    """
    
    # Binance Public Data 기본 URL
    BASE_URL = "https://data.binance.vision/data/spot"
    
    def __init__(self, timeout: int = 300):
        """
        Args:
            timeout: HTTP 요청 타임아웃 (초, 기본 5분)
        """
        self.timeout = timeout
    
    def download_monthly(
        self,
        symbol: str,
        year: int,
        month: int,
        output_dir: Path,
    ) -> Path:
        """
        월별 aggTrades 데이터 다운로드 및 Parquet 저장
        
        Args:
            symbol: 거래쌍 (예: "BTCUSDT")
            year: 연도 (예: 2024)
            month: 월 (1-12)
            output_dir: 저장 디렉토리
            
        Returns:
            저장된 Parquet 파일 경로
            
        Raises:
            requests.HTTPError: 다운로드 실패 시
            
        교육 포인트:
            - URL 형식: /monthly/aggTrades/{SYMBOL}/{SYMBOL}-aggTrades-{YYYY}-{MM}.zip
            - ZIP 내부에 CSV 파일이 있음
        """
        symbol = symbol.upper()
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 출력 파일 경로
        output_file = output_dir / f"{symbol}-aggTrades-{year}-{month:02d}.parquet"
        
        # 이미 존재하면 스킵
        if output_file.exists():
            print(f"[Downloader] File already exists: {output_file}")
            return output_file
        
        # URL 구성
        url = (
            f"{self.BASE_URL}/monthly/aggTrades/{symbol}/"
            f"{symbol}-aggTrades-{year}-{month:02d}.zip"
        )
        
        print(f"[Downloader] Downloading {url}...")
        
        # 다운로드
        response = requests.get(url, timeout=self.timeout)
        response.raise_for_status()
        
        print(f"[Downloader] Downloaded {len(response.content) / 1024 / 1024:.1f} MB")
        
        # ZIP 압축 해제 및 CSV 파싱
        df = self._extract_and_parse(response.content, symbol, year, month)
        
        # Parquet로 저장
        df.to_parquet(output_file, index=False, compression="snappy")
        
        print(f"[Downloader] Saved to {output_file} ({len(df):,} records)")
        
        return output_file
    
    def download_daily(
        self,
        symbol: str,
        date: datetime,
        output_dir: Path,
    ) -> Path:
        """
        일별 aggTrades 데이터 다운로드 및 Parquet 저장
        
        Args:
            symbol: 거래쌍 (예: "BTCUSDT")
            date: 날짜
            output_dir: 저장 디렉토리
            
        Returns:
            저장된 Parquet 파일 경로
            
        교육 포인트:
            - 일별 데이터는 최신 데이터에 유용 (월별 데이터는 전월까지만 제공)
            - URL 형식: /daily/aggTrades/{SYMBOL}/{SYMBOL}-aggTrades-{YYYY}-{MM}-{DD}.zip
        """
        symbol = symbol.upper()
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        date_str = date.strftime("%Y-%m-%d")
        output_file = output_dir / f"{symbol}-aggTrades-{date_str}.parquet"
        
        # 이미 존재하면 스킵
        if output_file.exists():
            print(f"[Downloader] File already exists: {output_file}")
            return output_file
        
        # URL 구성
        url = (
            f"{self.BASE_URL}/daily/aggTrades/{symbol}/"
            f"{symbol}-aggTrades-{date_str}.zip"
        )
        
        print(f"[Downloader] Downloading {url}...")
        
        # 다운로드
        response = requests.get(url, timeout=self.timeout)
        response.raise_for_status()
        
        print(f"[Downloader] Downloaded {len(response.content) / 1024:.1f} KB")
        
        # ZIP 압축 해제 및 CSV 파싱
        df = self._extract_and_parse(
            response.content, 
            symbol, 
            date.year, 
            date.month,
            date.day,
        )
        
        # Parquet로 저장
        df.to_parquet(output_file, index=False, compression="snappy")
        
        print(f"[Downloader] Saved to {output_file} ({len(df):,} records)")
        
        return output_file
    
    def _extract_and_parse(
        self,
        zip_content: bytes,
        symbol: str,
        year: int,
        month: int,
        day: Optional[int] = None,
    ) -> pd.DataFrame:
        """
        ZIP 압축 해제 및 CSV 파싱
        
        Args:
            zip_content: ZIP 파일 내용
            symbol: 거래쌍
            year, month, day: 날짜 정보
            
        Returns:
            파싱된 DataFrame
            
        교육 포인트:
            - Binance aggTrades CSV 컬럼:
              agg_trade_id, price, quantity, first_trade_id, 
              last_trade_id, timestamp, is_buyer_maker, is_best_match
        """
        # ZIP 압축 해제
        with zipfile.ZipFile(io.BytesIO(zip_content)) as zf:
            # ZIP 내 첫 번째 파일 (CSV)
            csv_filename = zf.namelist()[0]
            
            with zf.open(csv_filename) as f:
                # CSV 파싱
                df = pd.read_csv(
                    f,
                    names=[
                        "agg_trade_id",
                        "price",
                        "quantity",
                        "first_trade_id",
                        "last_trade_id",
                        "timestamp",
                        "is_buyer_maker",
                        "is_best_match",
                    ],
                    dtype={
                        "agg_trade_id": "int64",
                        "price": "float64",
                        "quantity": "float64",
                        "first_trade_id": "int64",
                        "last_trade_id": "int64",
                        "timestamp": "int64",
                        "is_buyer_maker": "bool",
                        "is_best_match": "bool",
                    },
                )
        
        # timestamp를 datetime으로 변환 (밀리초)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        
        # 심볼 추가
        df["symbol"] = symbol
        
        return df
    
    def get_available_months(self, symbol: str) -> list[tuple[int, int]]:
        """
        다운로드 가능한 월 목록 조회
        
        Args:
            symbol: 거래쌍
            
        Returns:
            [(year, month), ...] 형식의 목록
            
        Note:
            이 메서드는 Binance 서버에서 직접 목록을 가져오는 것이 아니라,
            일반적으로 사용 가능한 범위를 추정합니다.
            실제 가용 여부는 다운로드 시 확인됩니다.
        """
        # 현재 날짜 기준 전월까지 가능 (월별 데이터는 다음 달에 업로드됨)
        now = datetime.now()
        current_year = now.year
        current_month = now.month - 1  # 전월까지
        
        if current_month == 0:
            current_year -= 1
            current_month = 12
        
        # 2020년 1월부터 시작 (Binance 데이터 시작점은 심볼마다 다름)
        result = []
        for year in range(2020, current_year + 1):
            start_month = 1
            end_month = 12 if year < current_year else current_month
            
            for month in range(start_month, end_month + 1):
                result.append((year, month))
        
        return result




