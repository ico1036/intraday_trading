"""
시장 지표 계산 모듈

Orderbook 데이터에서 다양한 시장 지표를 계산합니다.
교육 목적으로 상세한 주석을 포함합니다.
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from .orderbook import OrderbookState


@dataclass
class MetricsSnapshot:
    """
    시점별 지표 스냅샷
    
    교육 포인트:
        - 여러 지표를 한 번에 계산하여 저장
        - 시계열 분석 및 시각화에 활용
    """
    timestamp: datetime
    symbol: str
    
    # 가격 지표
    best_bid: float
    best_ask: float
    mid_price: float
    micro_price: float
    
    # 스프레드 지표
    spread: float       # 절대값 ($)
    spread_bps: float   # 상대값 (basis points)
    
    # 주문량 지표
    bid_qty: float      # Best bid 수량
    ask_qty: float      # Best ask 수량
    imbalance: float    # 주문 불균형 (-1 ~ +1)
    
    # 파생 지표 (이전 스냅샷 대비)
    mid_price_change: float = 0.0     # 중간가 변화
    micro_price_change: float = 0.0   # 마이크로가 변화
    spread_change: float = 0.0        # 스프레드 변화


class MetricsCalculator:
    """
    시장 지표 계산기
    
    Orderbook 데이터에서 다양한 지표를 계산하고 시계열로 저장합니다.
    
    교육 포인트:
        - 단일 스냅샷 지표: spread, mid_price, micro_price
        - 시계열 지표: 변화율, 이동평균, 변동성
        - 이 지표들을 조합하여 트레이딩 신호를 생성할 수 있음
    """
    
    def __init__(self, max_history: int = 10000):
        """
        Args:
            max_history: 저장할 최대 스냅샷 수
        """
        self.max_history = max_history
        self._history: deque[MetricsSnapshot] = deque(maxlen=max_history)
        self._prev_snapshot: Optional[MetricsSnapshot] = None
    
    def calculate(self, state: OrderbookState) -> MetricsSnapshot:
        """
        OrderbookState에서 지표 계산
        
        Args:
            state: 현재 Orderbook 상태
            
        Returns:
            계산된 MetricsSnapshot
        """
        best_bid_price, best_bid_qty = state.best_bid
        best_ask_price, best_ask_qty = state.best_ask
        
        # 기본 지표 계산
        mid_price = state.mid_price
        micro_price = state.micro_price
        spread = state.spread
        spread_bps = state.spread_bps
        imbalance = state.imbalance
        
        # 변화량 계산 (이전 스냅샷 대비)
        mid_price_change = 0.0
        micro_price_change = 0.0
        spread_change = 0.0
        
        if self._prev_snapshot:
            mid_price_change = mid_price - self._prev_snapshot.mid_price
            micro_price_change = micro_price - self._prev_snapshot.micro_price
            spread_change = spread - self._prev_snapshot.spread
        
        snapshot = MetricsSnapshot(
            timestamp=state.timestamp,
            symbol=state.symbol,
            best_bid=best_bid_price,
            best_ask=best_ask_price,
            mid_price=mid_price,
            micro_price=micro_price,
            spread=spread,
            spread_bps=spread_bps,
            bid_qty=best_bid_qty,
            ask_qty=best_ask_qty,
            imbalance=imbalance,
            mid_price_change=mid_price_change,
            micro_price_change=micro_price_change,
            spread_change=spread_change,
        )
        
        self._history.append(snapshot)
        self._prev_snapshot = snapshot
        
        return snapshot
    
    @property
    def current(self) -> Optional[MetricsSnapshot]:
        """현재 스냅샷"""
        return self._prev_snapshot
    
    @property
    def history(self) -> list[MetricsSnapshot]:
        """히스토리 (복사본)"""
        return list(self._history)
    
    def to_dataframe(self) -> pd.DataFrame:
        """
        히스토리를 DataFrame으로 변환
        
        Returns:
            시계열 지표 DataFrame
        """
        if not self._history:
            return pd.DataFrame()
        
        records = []
        for s in self._history:
            records.append({
                "timestamp": s.timestamp,
                "symbol": s.symbol,
                "best_bid": s.best_bid,
                "best_ask": s.best_ask,
                "mid_price": s.mid_price,
                "micro_price": s.micro_price,
                "spread": s.spread,
                "spread_bps": s.spread_bps,
                "bid_qty": s.bid_qty,
                "ask_qty": s.ask_qty,
                "imbalance": s.imbalance,
                "mid_price_change": s.mid_price_change,
                "micro_price_change": s.micro_price_change,
            })
        
        df = pd.DataFrame(records)
        df.set_index("timestamp", inplace=True)
        return df
    
    def get_recent_stats(self, window_seconds: float = 60.0) -> dict:
        """
        최근 N초간 통계 계산
        
        Args:
            window_seconds: 윈도우 크기 (초)
            
        Returns:
            통계 딕셔너리
        
        교육 포인트:
            - 이동 통계는 시장 상태를 파악하는 데 중요
            - 평균 스프레드: 평소 유동성 수준
            - 스프레드 변동성: 시장 불안정성
            - 가격 변동성: 현재 시장의 활발함
        """
        if not self._history:
            return {}
        
        now = datetime.now()
        cutoff = now - timedelta(seconds=window_seconds)
        
        # 윈도우 내 데이터 필터링
        recent = [s for s in self._history if s.timestamp >= cutoff]
        
        if not recent:
            return {}
        
        spreads = [s.spread for s in recent]
        spread_bps_list = [s.spread_bps for s in recent]
        mid_prices = [s.mid_price for s in recent]
        micro_prices = [s.micro_price for s in recent]
        imbalances = [s.imbalance for s in recent]
        
        return {
            "window_seconds": window_seconds,
            "sample_count": len(recent),
            
            # 스프레드 통계
            "spread_mean": np.mean(spreads),
            "spread_std": np.std(spreads),
            "spread_min": np.min(spreads),
            "spread_max": np.max(spreads),
            "spread_bps_mean": np.mean(spread_bps_list),
            
            # 가격 통계
            "mid_price_mean": np.mean(mid_prices),
            "mid_price_std": np.std(mid_prices),
            "mid_price_range": np.max(mid_prices) - np.min(mid_prices),
            
            # Micro-price vs Mid-price 차이
            "micro_mid_diff_mean": np.mean([m - p for m, p in zip(micro_prices, mid_prices)]),
            
            # 불균형 통계
            "imbalance_mean": np.mean(imbalances),
            "imbalance_std": np.std(imbalances),
        }
    
    def get_price_comparison(self) -> dict:
        """
        Mid-price와 Micro-price 비교 데이터
        
        Returns:
            비교 데이터 딕셔너리
        
        교육 포인트:
            - Micro-price - Mid-price > 0: 매도 물량 < 매수 물량 (상승 압력)
            - Micro-price - Mid-price < 0: 매도 물량 > 매수 물량 (하락 압력)
            - 이 차이가 커질수록 한쪽으로의 압력이 강함
        """
        if not self._prev_snapshot:
            return {}
        
        s = self._prev_snapshot
        diff = s.micro_price - s.mid_price
        
        # 방향성 판단
        if abs(diff) < 0.01:  # 거의 차이 없음
            direction = "neutral"
        elif diff > 0:
            direction = "bullish"  # 상승 압력
        else:
            direction = "bearish"  # 하락 압력
        
        return {
            "mid_price": s.mid_price,
            "micro_price": s.micro_price,
            "difference": diff,
            "difference_bps": (diff / s.mid_price) * 10000 if s.mid_price > 0 else 0,
            "direction": direction,
            "imbalance": s.imbalance,
            "interpretation": self._get_interpretation(s),
        }
    
    def _get_interpretation(self, snapshot: MetricsSnapshot) -> str:
        """
        현재 시장 상태 해석 (교육용)
        
        교육 포인트:
            - 지표를 조합하여 시장 상태를 해석하는 예시
            - 실제 트레이딩에서는 더 정교한 분석 필요
        """
        diff = snapshot.micro_price - snapshot.mid_price
        imb = snapshot.imbalance
        
        interpretations = []
        
        # Imbalance 해석
        if imb > 0.3:
            interpretations.append("매수 물량이 매도보다 많음 (상승 압력)")
        elif imb < -0.3:
            interpretations.append("매도 물량이 매수보다 많음 (하락 압력)")
        else:
            interpretations.append("매수/매도 균형 상태")
        
        # Micro vs Mid 해석
        if diff > 0.5:
            interpretations.append("Micro-price가 Mid-price보다 높음 → 단기 상승 가능성")
        elif diff < -0.5:
            interpretations.append("Micro-price가 Mid-price보다 낮음 → 단기 하락 가능성")
        
        # 스프레드 해석
        if snapshot.spread_bps > 5:
            interpretations.append(f"스프레드 넓음 ({snapshot.spread_bps:.1f} bps) → 유동성 낮음")
        elif snapshot.spread_bps < 1:
            interpretations.append(f"스프레드 좁음 ({snapshot.spread_bps:.1f} bps) → 유동성 높음")
        
        return " | ".join(interpretations)


def calculate_vwap(prices: list[float], quantities: list[float]) -> float:
    """
    VWAP (Volume-Weighted Average Price) 계산
    
    교육 포인트:
        - VWAP = Σ(Price × Volume) / Σ(Volume)
        - 거래량 가중 평균 가격
        - 기관 투자자들이 자주 사용하는 벤치마크
        - 현재 가격이 VWAP 위면 "비싸게 사는 것", 아래면 "싸게 사는 것"
    """
    if not prices or not quantities:
        return 0.0
    
    total_value = sum(p * q for p, q in zip(prices, quantities))
    total_volume = sum(quantities)
    
    if total_volume > 0:
        return total_value / total_volume
    return 0.0


def calculate_weighted_mid(
    bid_prices: list[float],
    bid_quantities: list[float],
    ask_prices: list[float],
    ask_quantities: list[float],
    levels: int = 5
) -> float:
    """
    가중 중간가 계산 (여러 호가 레벨 사용)
    
    교육 포인트:
        - Best bid/ask만 사용하는 Micro-price의 확장
        - 여러 호가 레벨의 물량을 고려
        - 더 깊은 유동성 정보를 반영
    """
    bid_vwap = calculate_vwap(bid_prices[:levels], bid_quantities[:levels])
    ask_vwap = calculate_vwap(ask_prices[:levels], ask_quantities[:levels])
    
    total_bid_qty = sum(bid_quantities[:levels])
    total_ask_qty = sum(ask_quantities[:levels])
    total_qty = total_bid_qty + total_ask_qty
    
    if total_qty > 0:
        # 반대쪽 물량으로 가중
        return (bid_vwap * total_ask_qty + ask_vwap * total_bid_qty) / total_qty
    return (bid_vwap + ask_vwap) / 2



