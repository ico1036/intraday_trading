"""
Orderbook 데이터 처리 모듈

Orderbook 스냅샷을 저장하고 히트맵 시각화를 위한 데이터를 생성합니다.
교육 목적으로 상세한 주석을 포함합니다.
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from .client import OrderbookSnapshot


@dataclass
class OrderbookState:
    """
    현재 Orderbook 상태
    
    교육 포인트:
        - Orderbook은 매수자와 매도자가 원하는 가격과 수량을 보여줍니다.
        - "호가창"이라고도 부르며, 시장의 수요와 공급을 실시간으로 파악할 수 있습니다.
        - bids(매수)는 가격이 높은 순, asks(매도)는 가격이 낮은 순으로 정렬됩니다.
    """
    timestamp: datetime
    symbol: str
    
    # 매수 호가 (Bids)
    bid_prices: list[float]     # 매수 가격들 (내림차순)
    bid_quantities: list[float] # 각 가격의 매수 수량
    
    # 매도 호가 (Asks)
    ask_prices: list[float]     # 매도 가격들 (오름차순)
    ask_quantities: list[float] # 각 가격의 매도 수량
    
    @property
    def best_bid(self) -> tuple[float, float]:
        """
        최고 매수 호가 (Best Bid)
        
        교육 포인트:
            - 시장에서 가장 높은 가격에 매수하려는 주문
            - 시장가 매도 시 이 가격에 체결됩니다.
            - "내가 팔면 이 가격에 팔린다"
        """
        if self.bid_prices:
            return (self.bid_prices[0], self.bid_quantities[0])
        return (0.0, 0.0)
    
    @property
    def best_ask(self) -> tuple[float, float]:
        """
        최저 매도 호가 (Best Ask)
        
        교육 포인트:
            - 시장에서 가장 낮은 가격에 매도하려는 주문
            - 시장가 매수 시 이 가격에 체결됩니다.
            - "내가 사면 이 가격에 산다"
        """
        if self.ask_prices:
            return (self.ask_prices[0], self.ask_quantities[0])
        return (0.0, 0.0)
    
    @property
    def spread(self) -> float:
        """
        Bid-Ask Spread (스프레드)
        
        교육 포인트:
            - Best Ask - Best Bid = 매수가와 매도가의 차이
            - 스프레드가 좁을수록 유동성이 높음 (거래가 활발함)
            - 스프레드가 넓을수록 거래 비용이 높음
            - BTC/USDT 같은 메이저 페어는 스프레드가 매우 좁음 (보통 $0.01~$1)
        """
        return self.best_ask[0] - self.best_bid[0]
    
    @property
    def spread_bps(self) -> float:
        """
        스프레드 (Basis Points, bps)
        
        교육 포인트:
            - 1 bps = 0.01% = 0.0001
            - 상대적 스프레드로, 다른 자산 간 유동성 비교에 유용
            - 예: 10 bps = 0.1%
        """
        mid = (self.best_bid[0] + self.best_ask[0]) / 2
        if mid > 0:
            return (self.spread / mid) * 10000
        return 0.0
    
    @property
    def mid_price(self) -> float:
        """
        Mid-price (중간가)
        
        교육 포인트:
            - (Best Bid + Best Ask) / 2
            - 현재 "공정 가격"의 단순한 추정치
            - 주문량을 고려하지 않는 단점이 있음
        """
        return (self.best_bid[0] + self.best_ask[0]) / 2
    
    @property
    def micro_price(self) -> float:
        """
        Micro-price (마이크로 프라이스)
        
        교육 포인트:
            - 주문량으로 가중한 중간가
            - 공식: (Best Bid × Ask Qty + Best Ask × Bid Qty) / (Bid Qty + Ask Qty)
            - 어느 쪽에 물량이 더 많은지 반영
            
            예시:
                - Bid: $100에 10BTC, Ask: $101에 1BTC
                - Mid-price = $100.5
                - Micro-price = (100×1 + 101×10) / (10+1) = $100.91
                - → 매도 물량이 적으므로 가격이 올라갈 가능성 반영
        """
        bid_price, bid_qty = self.best_bid
        ask_price, ask_qty = self.best_ask
        
        total_qty = bid_qty + ask_qty
        if total_qty > 0:
            # 반대쪽 물량으로 가중 (매도 물량이 적으면 매수 쪽으로 치우침)
            return (bid_price * ask_qty + ask_price * bid_qty) / total_qty
        return self.mid_price
    
    @property
    def imbalance(self) -> float:
        """
        Order Imbalance (주문 불균형)
        
        교육 포인트:
            - (Bid Qty - Ask Qty) / (Bid Qty + Ask Qty)
            - 범위: -1 ~ +1
            - +1에 가까우면: 매수 물량이 많음 (가격 상승 압력)
            - -1에 가까우면: 매도 물량이 많음 (가격 하락 압력)
        """
        bid_qty = self.best_bid[1]
        ask_qty = self.best_ask[1]
        total = bid_qty + ask_qty
        if total > 0:
            return (bid_qty - ask_qty) / total
        return 0.0


class OrderbookProcessor:
    """
    Orderbook 데이터 처리기
    
    실시간 스냅샷을 저장하고 히트맵/시계열 분석을 위한 데이터를 생성합니다.
    
    교육 포인트:
        - 시계열 데이터 저장으로 과거 패턴 분석 가능
        - deque를 사용해 메모리 효율적으로 최근 N개 데이터만 유지
    """
    
    def __init__(self, max_history: int = 1000):
        """
        Args:
            max_history: 저장할 최대 스냅샷 수
        """
        self.max_history = max_history
        self._history: deque[OrderbookState] = deque(maxlen=max_history)
        self._current: Optional[OrderbookState] = None
    
    def update(self, snapshot: OrderbookSnapshot) -> OrderbookState:
        """
        새 스냅샷으로 상태 업데이트
        
        Args:
            snapshot: BinanceWebSocketClient에서 받은 스냅샷
            
        Returns:
            현재 OrderbookState
        """
        state = OrderbookState(
            timestamp=snapshot.timestamp,
            symbol=snapshot.symbol,
            bid_prices=[p for p, _ in snapshot.bids],
            bid_quantities=[q for _, q in snapshot.bids],
            ask_prices=[p for p, _ in snapshot.asks],
            ask_quantities=[q for _, q in snapshot.asks],
        )
        
        self._current = state
        self._history.append(state)
        
        return state
    
    @property
    def current(self) -> Optional[OrderbookState]:
        """현재 Orderbook 상태"""
        return self._current
    
    @property
    def history(self) -> list[OrderbookState]:
        """저장된 히스토리 (복사본)"""
        return list(self._history)
    
    def get_heatmap_data(self, num_levels: int = 20) -> dict:
        """
        히트맵 시각화용 데이터 생성
        
        Returns:
            {
                "prices": [가격 레벨들],
                "bid_quantities": [각 가격의 매수 수량],
                "ask_quantities": [각 가격의 매도 수량],
            }
        
        교육 포인트:
            - 히트맵은 가격별 주문량을 색상 강도로 표현
            - 큰 주문("벽")이 있는 가격대를 쉽게 파악 가능
            - 지지/저항 수준을 예측하는 데 활용
        """
        if not self._current:
            return {"prices": [], "bid_quantities": [], "ask_quantities": []}
        
        state = self._current
        
        # 모든 가격 레벨 수집
        all_prices = set(state.bid_prices[:num_levels]) | set(state.ask_prices[:num_levels])
        prices = sorted(all_prices)
        
        # 각 가격의 수량 매핑
        bid_map = dict(zip(state.bid_prices, state.bid_quantities))
        ask_map = dict(zip(state.ask_prices, state.ask_quantities))
        
        bid_quantities = [bid_map.get(p, 0) for p in prices]
        ask_quantities = [ask_map.get(p, 0) for p in prices]
        
        return {
            "prices": prices,
            "bid_quantities": bid_quantities,
            "ask_quantities": ask_quantities,
        }
    
    def get_depth_chart_data(self, num_levels: int = 20) -> dict:
        """
        Depth Chart (깊이 차트)용 데이터 생성
        
        Returns:
            {
                "bid_prices": [...],
                "bid_cumulative": [...],  # 누적 매수량
                "ask_prices": [...],
                "ask_cumulative": [...],  # 누적 매도량
            }
        
        교육 포인트:
            - Depth Chart는 누적 주문량을 보여줌
            - 특정 가격까지 얼마나 많은 물량이 있는지 파악
            - 큰 주문이 있는 가격대에서 계단 형태로 나타남
        """
        if not self._current:
            return {
                "bid_prices": [], "bid_cumulative": [],
                "ask_prices": [], "ask_cumulative": []
            }
        
        state = self._current
        
        # 누적 수량 계산
        bid_cumulative = np.cumsum(state.bid_quantities[:num_levels]).tolist()
        ask_cumulative = np.cumsum(state.ask_quantities[:num_levels]).tolist()
        
        return {
            "bid_prices": state.bid_prices[:num_levels],
            "bid_cumulative": bid_cumulative,
            "ask_prices": state.ask_prices[:num_levels],
            "ask_cumulative": ask_cumulative,
        }
    
    def to_dataframe(self) -> pd.DataFrame:
        """
        히스토리를 DataFrame으로 변환
        
        교육 포인트:
            - pandas DataFrame은 시계열 분석에 필수
            - 스프레드, 가격 변화 등의 패턴 분석 가능
        """
        if not self._history:
            return pd.DataFrame()
        
        records = []
        for state in self._history:
            records.append({
                "timestamp": state.timestamp,
                "symbol": state.symbol,
                "best_bid_price": state.best_bid[0],
                "best_bid_qty": state.best_bid[1],
                "best_ask_price": state.best_ask[0],
                "best_ask_qty": state.best_ask[1],
                "spread": state.spread,
                "spread_bps": state.spread_bps,
                "mid_price": state.mid_price,
                "micro_price": state.micro_price,
                "imbalance": state.imbalance,
            })
        
        df = pd.DataFrame(records)
        df.set_index("timestamp", inplace=True)
        return df

