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
        weight: 포트폴리오 전략에서 특정 심볼 할당 비중(0~1)
                - None이면 quantity를 직접 사용
                - 값이 있으면 runner가 quantity를 계산해 할당

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
    weight: float | None = None  # 포트폴리오 전략에서 비중 기반 오더 지원


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

    # OHLCV 필드 (현재 포트폴리오 포워드는 tick/candle 기반만 사용, 주문서 미사용 시 None 가능)
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[float] = None
    vwap: Optional[float] = None

    # 포트폴리오 확장 필드 (하위 호환: 기본값 None)
    symbol: Optional[str] = None  # 현재 심볼 (예: "BTCUSDT")
    panel: Optional[dict] = None  # 크로스섹셔널 데이터 {symbol: {field: value}}
    positions: Optional[dict] = None  # 포트폴리오 포지션 {symbol: {side, qty, entry_price}}


class PortfolioOrder:
    """
    포트폴리오 주문 - 여러 코인에 대한 동시 주문

    포트폴리오 전략이 generate_order에서 반환할 수 있는 확장 주문 타입.

    사용 예시:
        orders = PortfolioOrder(orders={
            "BTCUSDT": Order(side=Side.BUY, quantity=0.1),
            "ETHUSDT": Order(side=Side.SELL, quantity=1.0),
            "SOLUSDT": None,  # 주문 없음
        })
    """

    def __init__(self, orders: dict[str, Optional[Order]]):
        """
        Args:
            orders: {symbol: Order | None} 매핑
        """
        self._orders = orders

    def __getitem__(self, symbol: str) -> Optional[Order]:
        """symbol로 주문 조회"""
        return self._orders.get(symbol)

    @property
    def active_orders(self) -> dict[str, Order]:
        """None이 아닌 주문만 반환"""
        return {s: o for s, o in self._orders.items() if o is not None}

    @property
    def symbols(self) -> list[str]:
        """모든 심볼 목록"""
        return list(self._orders.keys())

    def items(self):
        """dict-like iteration"""
        return self._orders.items()


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
