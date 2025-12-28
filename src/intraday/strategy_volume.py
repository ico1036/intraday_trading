"""
Volume Imbalance 기반 전략

틱 데이터의 매수주도/매도주도 비율을 기반으로 한 전략입니다.
OBI (Order Book Imbalance)와 다른 개념입니다.

교육 포인트:
    - OBI: 오더북의 bid_qty vs ask_qty 불균형
    - Volume Imbalance: 체결의 buyer vs seller 불균형
    - is_buyer_maker=False → 매수 주도 (Taker가 매수)
    - is_buyer_maker=True → 매도 주도 (Taker가 매도)
"""

from dataclasses import dataclass
from typing import Optional

from .strategy import Order, Side, OrderType, MarketState


class VolumeImbalanceStrategy:
    """
    Volume Imbalance 기반 전략 (틱 데이터용)
    
    틱 데이터에서 매수주도/매도주도 비율을 분석하여 매매 신호를 생성합니다.
    
    전략 로직:
        - volume_imbalance > buy_threshold → BUY
        - volume_imbalance < sell_threshold → SELL
    
    사용 예시:
        strategy = VolumeImbalanceStrategy(buy_threshold=0.4, sell_threshold=-0.4)
        runner = TickBacktestRunner(strategy=strategy, ...)
    
    교육 포인트:
        - volume_imbalance = (buy_volume - sell_volume) / total_volume
        - +1에 가까우면 매수 주도 → 가격 상승 압력
        - -1에 가까우면 매도 주도 → 가격 하락 압력
        - OBIStrategy와 달리 오더북 없이 체결 데이터만으로 작동
    """
    
    def __init__(
        self,
        buy_threshold: float = 0.4,
        sell_threshold: float = -0.4,
        quantity: float = 0.01,
    ):
        """
        Args:
            buy_threshold: 매수 신호 임계값 (기본 0.4)
            sell_threshold: 매도 신호 임계값 (기본 -0.4)
            quantity: 주문 수량 (기본 0.01 BTC)
        
        교육 포인트:
            - OBI보다 높은 임계값 권장 (0.4 vs 0.3)
            - 볼륨 불균형은 오더북 불균형보다 노이즈가 많음
        """
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self.quantity = quantity
    
    def generate_order(self, state: MarketState) -> Order | None:
        """
        Volume Imbalance 기반 주문 생성
        
        Args:
            state: 현재 시장 상태 (TickBacktestRunner에서 제공)
                   - state.imbalance는 실제로 volume_imbalance
        
        Returns:
            Order: 생성된 주문
            None: 조건 미충족 시
        
        Note:
            TickBacktestRunner에서 state.imbalance에 bar.volume_imbalance를 넣습니다.
            이 전략은 그 값을 기반으로 매매 신호를 생성합니다.
        """
        volume_imbalance = state.imbalance
        
        # 매수 신호: 매수 주도 (volume_imbalance > threshold)
        if volume_imbalance > self.buy_threshold:
            # 중복 방지
            if state.position_side == Side.BUY:
                return None
            
            return Order(
                side=Side.BUY,
                quantity=self.quantity,
                order_type=OrderType.MARKET,  # 틱 기반은 MARKET 주문
            )
        
        # 매도 신호: 매도 주도 (volume_imbalance < threshold)
        if volume_imbalance < self.sell_threshold:
            # 포지션 없으면 SELL 불가 (현물)
            if state.position_side is None:
                return None
            if state.position_side == Side.SELL:
                return None
            
            return Order(
                side=Side.SELL,
                quantity=self.quantity,
                order_type=OrderType.MARKET,
            )
        
        return None





