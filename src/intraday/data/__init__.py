"""
데이터 수집 및 로딩 모듈

히스토리컬 데이터 다운로드, 실시간 수집, 로딩 기능을 제공합니다.

교육 포인트:
    - Tick 데이터: Binance Public Data에서 다운로드 가능
    - Orderbook 데이터: WebSocket으로 직접 수집 필요
    - Parquet 형식: 압축률 높고 빠른 읽기, pandas 친화적
"""

from .downloader import TickDataDownloader
from .recorder import OrderbookRecorder
from .loader import TickDataLoader, OrderbookDataLoader

__all__ = [
    "TickDataDownloader",
    "OrderbookRecorder",
    "TickDataLoader",
    "OrderbookDataLoader",
]








