"""
Binance REST API Klines Client

REST API를 통해 과거 캔들 데이터를 가져옵니다.
WebSocket 연결 전 전략 웜업에 사용됩니다.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List

import aiohttp

from .candle_builder import Candle


@dataclass
class Kline:
    """Binance Kline 데이터"""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class BinanceKlinesClient:
    """
    Binance REST API Klines 클라이언트

    사용법:
        client = BinanceKlinesClient()
        klines = await client.fetch_klines("BTCUSDT", "1m", limit=100)
        candles = await client.fetch_resampled_klines("BTCUSDT", 240, count=25)
    """

    BASE_URL = "https://fapi.binance.com"  # USDT-M Futures

    def __init__(self, base_url: str | None = None):
        """
        Args:
            base_url: API base URL (기본값: Binance Futures)
        """
        self.base_url = base_url or self.BASE_URL

    async def fetch_klines(
        self,
        symbol: str,
        interval: str,
        limit: int = 100,
    ) -> List[Kline]:
        """
        Binance REST API에서 Klines 가져오기

        Args:
            symbol: 거래쌍 (예: "BTCUSDT")
            interval: 캔들 간격 (예: "1m", "5m", "1h")
            limit: 가져올 캔들 수 (최대 1500)

        Returns:
            Kline 리스트 (시간순 정렬)
        """
        url = f"{self.base_url}/fapi/v1/klines"
        params = {
            "symbol": symbol.upper(),
            "interval": interval,
            "limit": limit,
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                response.raise_for_status()
                data = await response.json()

        klines = []
        for item in data:
            # Binance Kline format:
            # [0] Open time, [1] Open, [2] High, [3] Low, [4] Close,
            # [5] Volume, [6] Close time, ...
            kline = Kline(
                timestamp=datetime.fromtimestamp(item[0] / 1000, tz=timezone.utc),
                open=float(item[1]),
                high=float(item[2]),
                low=float(item[3]),
                close=float(item[4]),
                volume=float(item[5]),
            )
            klines.append(kline)

        # 시간순 정렬 (Binance는 이미 정렬되어 있지만 확실히)
        klines.sort(key=lambda k: k.timestamp)

        return klines

    async def fetch_resampled_klines(
        self,
        symbol: str,
        target_interval_seconds: int,
        count: int,
    ) -> List[Candle]:
        """
        1분봉을 가져와서 원하는 간격으로 리샘플링

        Binance는 4분봉을 지원하지 않으므로 1분봉을 리샘플링합니다.

        Args:
            symbol: 거래쌍 (예: "BTCUSDT")
            target_interval_seconds: 목표 캔들 간격 (초)
            count: 목표 캔들 수

        Returns:
            리샘플링된 Candle 리스트
        """
        # 필요한 1분봉 수 계산 (버퍼 추가)
        bars_per_target = target_interval_seconds // 60
        needed_1m_bars = count * bars_per_target + bars_per_target  # 1개 여유

        # 1분봉 가져오기
        klines_1m = await self.fetch_klines(
            symbol=symbol,
            interval="1m",
            limit=needed_1m_bars,
        )

        # 리샘플링
        candles = self._resample_klines(klines_1m, target_interval_seconds)

        # 정확히 count 개만 반환 (최신 count 개)
        if len(candles) > count:
            candles = candles[-count:]

        return candles

    def _resample_klines(
        self,
        klines: List[Kline],
        target_interval_seconds: int,
    ) -> List[Candle]:
        """
        Klines를 목표 간격으로 리샘플링

        Args:
            klines: 1분봉 Kline 리스트
            target_interval_seconds: 목표 간격 (초)

        Returns:
            리샘플링된 Candle 리스트
        """
        if not klines:
            return []

        candles = []
        bars_per_candle = target_interval_seconds // 60

        # 시작 시간을 target_interval에 맞게 정렬
        first_ts = klines[0].timestamp
        aligned_start = self._align_timestamp(first_ts, target_interval_seconds)

        current_group: List[Kline] = []
        current_boundary = aligned_start

        for kline in klines:
            # 현재 캔들 범위에 속하는지 확인
            kline_ts = kline.timestamp
            next_boundary = datetime.fromtimestamp(
                current_boundary.timestamp() + target_interval_seconds,
                tz=timezone.utc,
            )

            if kline_ts >= next_boundary:
                # 이전 그룹 완료 → 캔들 생성
                if current_group:
                    candle = self._aggregate_klines(current_group, current_boundary)
                    candles.append(candle)

                # 새 그룹 시작 (건너뛴 간격 처리)
                while kline_ts >= next_boundary:
                    current_boundary = next_boundary
                    next_boundary = datetime.fromtimestamp(
                        current_boundary.timestamp() + target_interval_seconds,
                        tz=timezone.utc,
                    )
                current_group = [kline]
            else:
                current_group.append(kline)

        # 마지막 그룹 처리 (완전한 경우만)
        if len(current_group) >= bars_per_candle:
            candle = self._aggregate_klines(current_group, current_boundary)
            candles.append(candle)

        return candles

    def _align_timestamp(
        self, ts: datetime, interval_seconds: int
    ) -> datetime:
        """타임스탬프를 interval에 맞게 정렬"""
        epoch = ts.timestamp()
        aligned_epoch = (epoch // interval_seconds) * interval_seconds
        return datetime.fromtimestamp(aligned_epoch, tz=timezone.utc)

    def _aggregate_klines(
        self, klines: List[Kline], timestamp: datetime
    ) -> Candle:
        """Kline 그룹을 하나의 Candle로 집계"""
        return Candle(
            timestamp=timestamp,
            open=klines[0].open,
            high=max(k.high for k in klines),
            low=min(k.low for k in klines),
            close=klines[-1].close,
            volume=sum(k.volume for k in klines),
        )
