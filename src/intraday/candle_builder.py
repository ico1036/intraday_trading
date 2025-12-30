"""
캔들 빌더 모듈

틱 데이터를 원하는 단위의 캔들(OHLCV)로 변환합니다.

지원하는 캔들 타입:
    - 볼륨 캔들: 특정 거래량마다 캔들 생성
    - 틱 캔들: 특정 틱 수마다 캔들 생성
    - 시간 캔들: 특정 시간마다 캔들 생성
    - 달러 캔들: 특정 달러 금액마다 캔들 생성

교육 포인트:
    - 전통적 시간 캔들: 시간에 따라 균등하게 분할 (변동성 무시)
    - 볼륨/틱 캔들: 시장 활동에 따라 분할 (변동성 반영)
    - 달러 캔들: 거래 금액 기준 (가격 변동 반영)
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Iterator, Optional, List

import pandas as pd

from .client import AggTrade
from .data.loader import TickDataLoader


class CandleType(Enum):
    """
    캔들 타입
    
    교육 포인트:
        - VOLUME: 거래량 기반 (시장 활동 기준)
        - TICK: 체결 횟수 기반 (거래 빈도 기준)
        - TIME: 시간 기반 (전통적 방식)
        - DOLLAR: 달러 금액 기반 (거래 가치 기준)
    """
    VOLUME = "volume"
    TICK = "tick"
    TIME = "time"
    DOLLAR = "dollar"


@dataclass
class Candle:
    """
    캔들스틱 (OHLCV)
    
    Attributes:
        timestamp: 캔들 시작 시간
        open: 시가
        high: 고가
        low: 저가
        close: 종가
        volume: 거래량 (BTC)
        quote_volume: 거래대금 (USDT)
        trade_count: 체결 수
        buy_volume: 매수 주도 거래량
        sell_volume: 매도 주도 거래량
    """
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    quote_volume: float = 0.0
    trade_count: int = 0
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    
    @property
    def vwap(self) -> float:
        """Volume Weighted Average Price"""
        if self.volume > 0:
            return self.quote_volume / self.volume
        return (self.open + self.high + self.low + self.close) / 4
    
    @property
    def volume_imbalance(self) -> float:
        """볼륨 불균형 (-1 ~ +1)"""
        total = self.buy_volume + self.sell_volume
        if total > 0:
            return (self.buy_volume - self.sell_volume) / total
        return 0.0
    
    @property
    def range(self) -> float:
        """캔들 범위 (고가 - 저가)"""
        return self.high - self.low
    
    @property
    def body(self) -> float:
        """캔들 몸통 (종가 - 시가)"""
        return self.close - self.open
    
    @property
    def is_bullish(self) -> bool:
        """양봉 여부"""
        return self.close > self.open


class CandleBuilder:
    """
    틱 데이터 → 캔들 변환기
    
    사용 예시:
        # 볼륨 캔들 (10 BTC 단위)
        builder = CandleBuilder(CandleType.VOLUME, size=10.0)
        candles = builder.build_from_loader(loader)
        
        # 시간 캔들 (1분)
        builder = CandleBuilder(CandleType.TIME, size=60)
        candles = builder.build_from_loader(loader)
        
        # 달러 캔들 (100만 달러)
        builder = CandleBuilder(CandleType.DOLLAR, size=1_000_000)
        candles = builder.build_from_loader(loader)
    
    교육 포인트:
        - 볼륨 캔들은 변동성 높을 때 더 많은 캔들 생성
        - 달러 캔들은 가격이 높을 때 적은 거래량으로도 캔들 완성
        - 시간 캔들은 시장 활동과 무관하게 균등 분할
    """
    
    def __init__(self, candle_type: CandleType, size: float):
        """
        Args:
            candle_type: 캔들 타입 (VOLUME, TICK, TIME, DOLLAR)
            size: 캔들 크기
                - VOLUME: 거래량 (BTC), 예: 10.0 → 10 BTC마다
                - TICK: 틱 수, 예: 100 → 100틱마다
                - TIME: 초, 예: 60 → 1분마다
                - DOLLAR: 달러 금액, 예: 1000000 → 100만 달러마다
        """
        self.candle_type = candle_type
        self.size = size
        
        # 현재 캔들 상태
        self._reset()
    
    def _reset(self) -> None:
        """상태 초기화"""
        self._start_time: Optional[datetime] = None
        self._open: float = 0.0
        self._high: float = 0.0
        self._low: float = float("inf")
        self._close: float = 0.0
        self._volume: float = 0.0
        self._quote_volume: float = 0.0
        self._trade_count: int = 0
        self._buy_volume: float = 0.0
        self._sell_volume: float = 0.0
    
    def _start_new_candle(self, trade: AggTrade) -> None:
        """새 캔들 시작"""
        self._start_time = trade.timestamp
        self._open = trade.price
        self._high = trade.price
        self._low = trade.price
        self._close = trade.price
        self._volume = 0.0
        self._quote_volume = 0.0
        self._trade_count = 0
        self._buy_volume = 0.0
        self._sell_volume = 0.0
    
    def _update(self, trade: AggTrade) -> None:
        """틱으로 현재 캔들 업데이트"""
        self._high = max(self._high, trade.price)
        self._low = min(self._low, trade.price)
        self._close = trade.price
        
        self._volume += trade.quantity
        self._quote_volume += trade.price * trade.quantity
        self._trade_count += 1
        
        if trade.is_buyer_maker:
            self._sell_volume += trade.quantity
        else:
            self._buy_volume += trade.quantity
    
    def _build_candle(self) -> Candle:
        """현재 상태로 캔들 생성"""
        return Candle(
            timestamp=self._start_time,
            open=self._open,
            high=self._high,
            low=self._low,
            close=self._close,
            volume=self._volume,
            quote_volume=self._quote_volume,
            trade_count=self._trade_count,
            buy_volume=self._buy_volume,
            sell_volume=self._sell_volume,
        )
    
    def _is_complete(self, trade: AggTrade) -> bool:
        """캔들 완성 조건 확인"""
        if self._start_time is None:
            return False
        
        if self.candle_type == CandleType.VOLUME:
            return self._volume >= self.size
        
        elif self.candle_type == CandleType.TICK:
            return self._trade_count >= int(self.size)
        
        elif self.candle_type == CandleType.TIME:
            elapsed = (trade.timestamp - self._start_time).total_seconds()
            return elapsed >= self.size
        
        elif self.candle_type == CandleType.DOLLAR:
            return self._quote_volume >= self.size
        
        return False
    
    def update(self, trade: AggTrade) -> Optional[Candle]:
        """
        스트리밍 모드: 틱 추가 및 캔들 완성 시 반환
        
        백테스터에서 틱마다 호출하여 캔들 완성 여부를 확인합니다.
        
        Args:
            trade: AggTrade 틱 데이터
            
        Returns:
            완성된 Candle (미완성이면 None)
        
        사용 예시:
            builder = CandleBuilder(CandleType.VOLUME, size=10.0)
            for trade in trades:
                candle = builder.update(trade)
                if candle:
                    # 캔들 완성! 전략 실행
                    strategy.generate_order(...)
        """
        # 첫 틱이면 새 캔들 시작
        if self._start_time is None:
            self._start_new_candle(trade)
        
        # 틱 업데이트
        self._update(trade)
        
        # 캔들 완성 확인
        if self._is_complete(trade):
            candle = self._build_candle()
            self._reset()
            return candle
        
        return None
    
    @property
    def current_candle(self) -> Optional[Candle]:
        """현재 진행 중인 캔들 (미완성)"""
        if self._start_time is None:
            return None
        return self._build_candle()
    
    def build_from_trades(self, trades: Iterator[AggTrade]) -> List[Candle]:
        """
        틱 Iterator에서 캔들 리스트 생성
        
        Args:
            trades: AggTrade Iterator
            
        Returns:
            Candle 리스트
        """
        candles = []
        self._reset()
        
        for trade in trades:
            # 첫 틱이면 새 캔들 시작
            if self._start_time is None:
                self._start_new_candle(trade)
            
            # 틱 업데이트
            self._update(trade)
            
            # 캔들 완성 확인
            if self._is_complete(trade):
                candles.append(self._build_candle())
                self._reset()
        
        return candles
    
    def build_from_loader(
        self,
        loader: TickDataLoader,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
    ) -> List[Candle]:
        """
        TickDataLoader에서 캔들 리스트 생성
        
        Args:
            loader: TickDataLoader 인스턴스
            start_time: 시작 시간 (선택)
            end_time: 종료 시간 (선택)
            
        Returns:
            Candle 리스트
        """
        trades = loader.iter_trades(start_time=start_time, end_time=end_time)
        return self.build_from_trades(trades)
    
    def to_dataframe(self, candles: List[Candle]) -> pd.DataFrame:
        """
        캔들 리스트를 DataFrame으로 변환
        
        Args:
            candles: Candle 리스트
            
        Returns:
            pandas DataFrame
        """
        records = []
        for c in candles:
            records.append({
                "timestamp": c.timestamp,
                "open": c.open,
                "high": c.high,
                "low": c.low,
                "close": c.close,
                "volume": c.volume,
                "quote_volume": c.quote_volume,
                "trade_count": c.trade_count,
                "buy_volume": c.buy_volume,
                "sell_volume": c.sell_volume,
                "vwap": c.vwap,
                "volume_imbalance": c.volume_imbalance,
            })
        
        df = pd.DataFrame(records)
        if not df.empty:
            df.set_index("timestamp", inplace=True)
        return df


def build_candles(
    data_path: Path,
    symbol: str,
    candle_type: CandleType,
    size: float,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
) -> pd.DataFrame:
    """
    편의 함수: 파일에서 바로 캔들 DataFrame 생성
    
    사용 예시:
        # 10 BTC 볼륨 캔들
        df = build_candles(
            data_path=Path("./data/ticks"),
            symbol="BTCUSDT",
            candle_type=CandleType.VOLUME,
            size=10.0,
        )
        
        # 1분 캔들
        df = build_candles(
            data_path=Path("./data/ticks"),
            symbol="BTCUSDT",
            candle_type=CandleType.TIME,
            size=60,
        )
    
    Args:
        data_path: Parquet 파일 경로 또는 디렉토리
        symbol: 거래쌍 (예: "BTCUSDT")
        candle_type: 캔들 타입
        size: 캔들 크기
        start_time: 시작 시간 (선택)
        end_time: 종료 시간 (선택)
        
    Returns:
        캔들 DataFrame (index=timestamp)
    """
    loader = TickDataLoader(data_path, symbol=symbol)
    builder = CandleBuilder(candle_type, size)
    candles = builder.build_from_loader(loader, start_time, end_time)
    return builder.to_dataframe(candles)

