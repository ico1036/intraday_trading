"""
Strategy 모듈

전략 인터페이스와 구현체를 정의합니다.
교육 목적으로 상세한 주석을 포함합니다.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Protocol


class Side(Enum):
    """
    주문 방향
    
    교육 포인트:
        - BUY: 매수 (자산을 구매)
        - SELL: 매도 (자산을 판매)
    """
    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    """
    주문 타입
    
    교육 포인트:
        - MARKET: 시장가 주문 - 현재 시장 가격에 즉시 체결
        - LIMIT: 지정가 주문 - 지정한 가격에 도달할 때만 체결
    """
    MARKET = "MARKET"
    LIMIT = "LIMIT"


@dataclass
class Order:
    """
    전략이 생성하는 주문
    
    Attributes:
        side: 주문 방향 (BUY/SELL)
        quantity: 주문 수량
        order_type: 주문 타입 (MARKET/LIMIT)
        limit_price: 지정가 (LIMIT 주문 시 필수)
        stop_loss: 손절가 (옵션, 전략 레벨에서 관리)
        take_profit: 익절가 (옵션, 전략 레벨에서 관리)
    
    교육 포인트:
        - 시장가 주문은 빠르게 체결되지만 가격 보장 없음
        - 지정가 주문은 원하는 가격에 체결되지만 체결 보장 없음
        - stop_loss/take_profit은 전략이 MarketState를 받을 때마다 체크하여
          조건 충족 시 청산 주문을 생성하는 방식으로 구현
        - PaperTrader는 주문 실행만 담당하며, 리스크 관리는 전략의 책임
    """
    side: Side
    quantity: float
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    stop_loss: float | None = None  # 전략이 내부적으로 추적 (메타데이터)
    take_profit: float | None = None  # 전략이 내부적으로 추적 (메타데이터)


@dataclass
class MarketState:
    """
    전략에 전달되는 시장 상태
    
    Attributes:
        timestamp: 현재 시간
        mid_price: 중간가 (best_bid + best_ask) / 2
        imbalance: 주문 불균형 (-1 ~ +1)
        spread: Bid-Ask 스프레드 (절대값)
        spread_bps: 스프레드 (basis points)
        best_bid: 최고 매수 호가
        best_ask: 최저 매도 호가
        best_bid_qty: 최고 매수 호가의 수량
        best_ask_qty: 최저 매도 호가의 수량
    
    교육 포인트:
        - imbalance > 0: 매수 압력이 강함 (가격 상승 가능성)
        - imbalance < 0: 매도 압력이 강함 (가격 하락 가능성)
        - spread가 좁을수록 유동성이 좋음
    """
    timestamp: datetime
    mid_price: float
    imbalance: float
    spread: float
    spread_bps: float
    best_bid: float
    best_ask: float
    best_bid_qty: float
    best_ask_qty: float
    
    # 현재 포지션 정보 (전략에서 중복 주문 방지용)
    position_side: Optional[Side] = None  # BUY/SELL/None
    position_qty: float = 0.0


class Strategy(Protocol):
    """
    모든 전략이 구현해야 하는 인터페이스
    
    Protocol을 사용하여 덕 타이핑 지원:
        - 이 클래스를 상속하지 않아도 됨
        - generate_order 메서드만 구현하면 Strategy로 인정
    
    교육 포인트:
        - Protocol은 Python 3.8+에서 지원하는 구조적 타이핑
        - 인터페이스 기반 설계로 전략 교체가 용이
    
    리스크 관리:
        - stop_loss, take_profit, trailing_stop은 전략 레벨에서 구현
        - 전략이 MarketState를 받을 때마다 현재 포지션과 비교하여
          조건 충족 시 청산 주문(SELL/BUY)을 생성
        - 예시:
            if position and current_price <= stop_loss:
                return Order(side=SELL, quantity=position.quantity, ...)
    """
    
    def generate_order(self, state: MarketState) -> Order | None:
        """
        현재 시장 상태를 분석하여 주문 생성
        
        Args:
            state: 현재 시장 상태
            
        Returns:
            Order: 생성된 주문 (신규 진입 또는 청산)
            None: 주문하지 않음
        
        Note:
            - 신규 진입 주문과 청산 주문 모두 이 메서드에서 반환
            - 전략은 내부적으로 포지션 상태와 stop_loss/take_profit을 추적해야 함
            - Runner는 전략에 포지션 정보를 제공하지 않으므로, 전략이 직접 관리 필요
        """
        ...


class OBIStrategy:
    """
    OBI (Order Book Imbalance) 기반 전략
    
    주문 불균형을 기반으로 매매 신호를 생성합니다.
    
    전략 로직:
        - imbalance > buy_threshold → LIMIT BUY at best_bid
        - imbalance < sell_threshold → LIMIT SELL at best_ask
        - 그 외 → 대기 (None 반환)
    
    교육 포인트:
        - OBI는 단기 가격 예측에 유용한 지표
        - 매수 물량 > 매도 물량이면 가격 상승 압력
        - LIMIT 주문으로 슬리피지 최소화
    """
    
    def __init__(
        self,
        buy_threshold: float = 0.3,
        sell_threshold: float = -0.3,
        quantity: float = 0.01,
    ):
        """
        Args:
            buy_threshold: 매수 신호 임계값 (기본 0.3)
            sell_threshold: 매도 신호 임계값 (기본 -0.3)
            quantity: 주문 수량 (기본 0.01 BTC)
        
        교육 포인트:
            - 임계값이 높을수록 신호 빈도 감소, 신뢰도 증가
            - 임계값이 낮을수록 신호 빈도 증가, 신뢰도 감소
        """
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self.quantity = quantity
    
    def generate_order(self, state: MarketState) -> Order | None:
        """
        OBI 기반 주문 생성
        
        Args:
            state: 현재 시장 상태
            
        Returns:
            Order: 생성된 주문 (LIMIT, Taker 스타일)
            None: 조건 미충족 시
        
        교육 포인트:
            - Taker 전략: 즉시 체결을 위해 상대방 호가에 주문
            - BUY: best_ask에 주문 (매도 호가에 매수)
            - SELL: best_bid에 주문 (매수 호가에 매도)
            - OBI 시그널은 빠른 체결이 중요하므로 Taker 방식 적합
            - 중복 주문 방지: 이미 같은 방향 포지션이면 추가 주문 안 함
        """
        # 매수 신호: imbalance가 buy_threshold 초과
        if state.imbalance > self.buy_threshold:
            # 중복 방지: 이미 BUY 포지션이면 추가 BUY 안 함
            if state.position_side == Side.BUY:
                return None
            
            return Order(
                side=Side.BUY,
                quantity=self.quantity,
                order_type=OrderType.LIMIT,
                limit_price=state.best_ask,  # Best Ask에 주문 → 즉시 체결 (Taker)
            )
        
        # 매도 신호: imbalance가 sell_threshold 미만
        if state.imbalance < self.sell_threshold:
            # 중복 방지: 이미 SELL 포지션이면 추가 SELL 안 함
            # (현물 거래에서는 BUY 포지션이 있어야 SELL 가능)
            if state.position_side is None:
                return None  # 포지션 없으면 SELL 불가 (현물)
            if state.position_side == Side.SELL:
                return None  # 이미 청산 완료
            
            # BUY 포지션 보유 중 → SELL (청산)
            return Order(
                side=Side.SELL,
                quantity=self.quantity,
                order_type=OrderType.LIMIT,
                limit_price=state.best_bid,  # Best Bid에 주문 → 즉시 체결 (Taker)
            )
        
        # 중립 구간: 주문 없음
        return None

