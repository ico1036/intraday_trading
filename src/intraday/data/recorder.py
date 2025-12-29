"""
Orderbook 데이터 수집기

WebSocket에서 오더북 스냅샷을 실시간 수집하여 Parquet로 저장합니다.

교육 포인트:
    - Binance는 오더북 히스토리를 제공하지 않음
    - 백테스트용 오더북 데이터는 직접 수집해야 함
    - 100ms마다 스냅샷 → 하루 약 864,000개
"""

import asyncio
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from ..client import BinanceCombinedClient, OrderbookSnapshot, AggTrade


class OrderbookRecorder:
    """
    오더북 스냅샷 실시간 수집 및 저장
    
    사용 예시:
        recorder = OrderbookRecorder()
        
        # 1시간 동안 수집
        filepath = await recorder.record(
            symbol="btcusdt",
            duration_seconds=3600,
            output_dir=Path("./data/orderbook")
        )
    
    교육 포인트:
        - 메모리 버퍼에 쌓다가 주기적으로 Parquet flush
        - depth20@100ms 기준: 1시간 약 36,000개 스냅샷
        - 각 스냅샷에 20레벨 bid/ask 저장
    """
    
    def __init__(
        self,
        depth_levels: int = 20,
        flush_interval: int = 10000,
    ):
        """
        Args:
            depth_levels: 저장할 호가 깊이 (기본 20)
            flush_interval: 메모리에서 파일로 flush하는 레코드 수 (기본 10000)
        """
        self.depth_levels = depth_levels
        self.flush_interval = flush_interval
        
        # 내부 상태
        self._buffer: deque[dict] = deque()
        self._trade_buffer: deque[dict] = deque()
        self._running = False
        self._client: Optional[BinanceCombinedClient] = None
        self._output_dir: Optional[Path] = None
        self._symbol: str = ""
        self._start_time: Optional[datetime] = None
        
        # 통계
        self._snapshot_count = 0
        self._trade_count = 0
        self._file_count = 0
    
    async def record(
        self,
        symbol: str,
        duration_seconds: float,
        output_dir: Path,
        include_trades: bool = True,
    ) -> tuple[Path, Optional[Path]]:
        """
        지정 시간 동안 수집 후 Parquet 저장
        
        Args:
            symbol: 거래쌍 (예: "btcusdt")
            duration_seconds: 수집 시간 (초)
            output_dir: 저장 디렉토리
            include_trades: aggTrade도 함께 저장할지 여부
            
        Returns:
            (orderbook_filepath, trades_filepath) 튜플
            include_trades=False면 trades_filepath는 None
            
        교육 포인트:
            - BinanceCombinedClient를 재사용하여 OB + Trade 동시 수집
            - 오래 수집할수록 파일 크기가 커지므로 적절히 분할 권장
        """
        self._symbol = symbol.lower()
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)
        
        self._running = True
        self._start_time = datetime.now()
        self._snapshot_count = 0
        self._trade_count = 0
        self._buffer.clear()
        self._trade_buffer.clear()
        
        # 클라이언트 생성
        self._client = BinanceCombinedClient(
            symbol=self._symbol,
            depth_levels=self.depth_levels,
        )
        
        print(f"[Recorder] Starting recording for {symbol.upper()}...")
        print(f"[Recorder] Duration: {duration_seconds}s, Output: {output_dir}")
        
        # 타이머 태스크
        asyncio.create_task(self._stop_after(duration_seconds))
        
        # 수집 시작
        await self._client.connect(
            on_orderbook=self._on_orderbook,
            on_trade=self._on_trade if include_trades else lambda _: None,
            on_error=self._on_error,
        )
        
        # 남은 버퍼 저장
        ob_filepath = self._flush_orderbook_buffer(final=True)
        trade_filepath = None
        if include_trades:
            trade_filepath = self._flush_trade_buffer(final=True)
        
        print(f"[Recorder] Recording finished.")
        print(f"[Recorder] Orderbook snapshots: {self._snapshot_count:,}")
        print(f"[Recorder] Trades: {self._trade_count:,}")
        
        return ob_filepath, trade_filepath
    
    async def _stop_after(self, seconds: float) -> None:
        """지정 시간 후 중지"""
        await asyncio.sleep(seconds)
        if self._running:
            print(f"[Recorder] Duration reached ({seconds}s). Stopping...")
            await self.stop()
    
    async def stop(self) -> None:
        """수집 중지"""
        self._running = False
        if self._client:
            await self._client.disconnect()
    
    def _on_orderbook(self, snapshot: OrderbookSnapshot) -> None:
        """오더북 스냅샷 수신 처리"""
        self._snapshot_count += 1
        
        # 플랫 구조로 변환 (Parquet 저장용)
        record = {
            "timestamp": snapshot.timestamp,
            "last_update_id": snapshot.last_update_id,
            "symbol": snapshot.symbol,
        }
        
        # Bid 레벨 추가 (price, qty)
        for i, (price, qty) in enumerate(snapshot.bids[:self.depth_levels]):
            record[f"bid_price_{i}"] = price
            record[f"bid_qty_{i}"] = qty
        
        # Ask 레벨 추가 (price, qty)
        for i, (price, qty) in enumerate(snapshot.asks[:self.depth_levels]):
            record[f"ask_price_{i}"] = price
            record[f"ask_qty_{i}"] = qty
        
        self._buffer.append(record)
        
        # 주기적 flush
        if len(self._buffer) >= self.flush_interval:
            self._flush_orderbook_buffer()
        
        # 진행 상황 출력
        if self._snapshot_count % 1000 == 0:
            print(f"[Recorder] Orderbook snapshots: {self._snapshot_count:,}")
    
    def _on_trade(self, trade: AggTrade) -> None:
        """체결 데이터 수신 처리"""
        self._trade_count += 1
        
        record = {
            "timestamp": trade.timestamp,
            "symbol": trade.symbol,
            "price": trade.price,
            "quantity": trade.quantity,
            "is_buyer_maker": trade.is_buyer_maker,
        }
        
        self._trade_buffer.append(record)
        
        # 주기적 flush
        if len(self._trade_buffer) >= self.flush_interval:
            self._flush_trade_buffer()
    
    def _on_error(self, error: Exception) -> None:
        """에러 처리"""
        print(f"[Recorder] Error: {error}")
    
    def _flush_orderbook_buffer(self, final: bool = False) -> Path:
        """버퍼를 Parquet 파일로 저장"""
        if not self._buffer:
            # 빈 버퍼면 빈 파일 생성 방지
            if final:
                # final인데 버퍼가 비어있으면 빈 DataFrame으로 최소 파일 생성
                timestamp_str = self._start_time.strftime("%Y%m%d_%H%M%S")
                filepath = self._output_dir / f"orderbook_{self._symbol}_{timestamp_str}.parquet"
                pd.DataFrame().to_parquet(filepath)
                return filepath
            return None
        
        df = pd.DataFrame(list(self._buffer))
        self._buffer.clear()
        
        # 파일명: orderbook_{symbol}_{timestamp}.parquet
        timestamp_str = self._start_time.strftime("%Y%m%d_%H%M%S")
        if final:
            filepath = self._output_dir / f"orderbook_{self._symbol}_{timestamp_str}.parquet"
        else:
            self._file_count += 1
            filepath = self._output_dir / f"orderbook_{self._symbol}_{timestamp_str}_{self._file_count:03d}.parquet"
        
        df.to_parquet(filepath, index=False, compression="snappy")
        print(f"[Recorder] Saved {len(df):,} orderbook snapshots to {filepath}")
        
        return filepath
    
    def _flush_trade_buffer(self, final: bool = False) -> Optional[Path]:
        """Trade 버퍼를 Parquet 파일로 저장"""
        if not self._trade_buffer:
            if final:
                timestamp_str = self._start_time.strftime("%Y%m%d_%H%M%S")
                filepath = self._output_dir / f"trades_{self._symbol}_{timestamp_str}.parquet"
                pd.DataFrame().to_parquet(filepath)
                return filepath
            return None
        
        df = pd.DataFrame(list(self._trade_buffer))
        self._trade_buffer.clear()
        
        timestamp_str = self._start_time.strftime("%Y%m%d_%H%M%S")
        filepath = self._output_dir / f"trades_{self._symbol}_{timestamp_str}.parquet"
        
        df.to_parquet(filepath, index=False, compression="snappy")
        print(f"[Recorder] Saved {len(df):,} trades to {filepath}")
        
        return filepath








