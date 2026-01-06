"""
Strategy Base Class (DO NOT MODIFY)

이 파일은 모든 전략의 기반이 되는 추상 클래스를 정의합니다.
에이전트나 개발자는 이 파일을 수정하지 말고, StrategyBase를 상속받아 사용하세요.

Usage:
    from intraday.strategies.base import StrategyBase, MarketState, Order, Side, OrderType

    class MyStrategy(StrategyBase):
        def setup(self) -> None:
            self.threshold = self.params.get("threshold", 0.3)

        def should_buy(self, state: MarketState) -> bool:
            return state.imbalance > self.threshold

        def should_sell(self, state: MarketState) -> bool:
            return state.imbalance < -self.threshold
"""

from abc import ABC, abstractmethod
from typing import Any

# Core types are imported from strategy.py to avoid enum duplication issues
# (Different enum instances with same values don't compare equal)
from ..strategy import Side, OrderType, Order, MarketState


# ============================================================
# STRATEGY BASE CLASS (DO NOT MODIFY)
# ============================================================

class StrategyBase(ABC):
    """
    전략 추상 베이스 클래스

    모든 커스텀 전략은 이 클래스를 상속받아야 합니다.

    필수 구현 메서드:
        - should_buy(state) -> bool: 매수 조건
        - should_sell(state) -> bool: 매도 조건

    선택 구현 메서드:
        - setup(): 초기화 로직 (params 접근 가능)
        - get_order_type(): MARKET 또는 LIMIT 반환
        - get_limit_price(state, side): LIMIT 주문 시 가격

    Example:
        class SimpleStrategy(StrategyBase):
            def setup(self):
                self.threshold = self.params.get("threshold", 0.3)

            def should_buy(self, state):
                return state.imbalance > self.threshold

            def should_sell(self, state):
                return state.imbalance < -self.threshold
    """

    def __init__(self, quantity: float = 0.01, **params: Any):
        """
        Args:
            quantity: 주문 수량 (기본 0.01)
            **params: 전략별 커스텀 파라미터
        """
        self.quantity = quantity
        self.params = params
        self.setup()

    # ----------------------------------------------------------
    # OVERRIDE THESE METHODS (에이전트가 수정할 부분)
    # ----------------------------------------------------------

    def setup(self) -> None:
        """
        초기화 로직 (선택적 오버라이드)

        self.params에서 커스텀 파라미터를 읽어올 수 있습니다.

        Example:
            def setup(self):
                self.buy_threshold = self.params.get("buy_threshold", 0.3)
                self.sell_threshold = self.params.get("sell_threshold", -0.3)
        """
        pass

    @abstractmethod
    def should_buy(self, state: MarketState) -> bool:
        """
        매수 조건 판단 (필수 구현)

        Args:
            state: 현재 시장 상태

        Returns:
            True: 매수 신호 발생
            False: 매수하지 않음

        Example:
            def should_buy(self, state):
                return state.imbalance > 0.3
        """
        ...

    @abstractmethod
    def should_sell(self, state: MarketState) -> bool:
        """
        매도 조건 판단 (필수 구현)

        Args:
            state: 현재 시장 상태

        Returns:
            True: 매도 신호 발생
            False: 매도하지 않음

        Example:
            def should_sell(self, state):
                return state.imbalance < -0.3
        """
        ...

    def get_order_type(self) -> OrderType:
        """
        주문 타입 반환 (선택적 오버라이드)

        기본값: MARKET (시장가)
        LIMIT 주문 사용 시 오버라이드하세요.

        Returns:
            OrderType.MARKET 또는 OrderType.LIMIT
        """
        return OrderType.MARKET

    def get_limit_price(self, state: MarketState, side: Side) -> float:
        """
        LIMIT 주문 시 가격 반환 (선택적 오버라이드)

        get_order_type()이 LIMIT을 반환할 때만 호출됩니다.
        기본값: Taker 방식 (즉시 체결)

        Args:
            state: 현재 시장 상태
            side: 주문 방향

        Returns:
            지정가 가격
        """
        if side == Side.BUY:
            return state.best_ask  # Taker: 매도 호가에 매수
        else:
            return state.best_bid  # Taker: 매수 호가에 매도

    # ----------------------------------------------------------
    # DO NOT OVERRIDE (고정 로직)
    # ----------------------------------------------------------

    def generate_order(self, state: MarketState) -> Order | None:
        """
        주문 생성 (수정 금지)

        should_buy/should_sell 결과를 바탕으로 Order를 생성합니다.
        이 메서드는 오버라이드하지 마세요.
        """
        # 매수 조건 체크
        if self.should_buy(state):
            # 중복 방지: 이미 BUY 포지션이면 스킵
            if state.position_side == Side.BUY:
                return None
            return self._create_order(state, Side.BUY)

        # 매도 조건 체크
        if self.should_sell(state):
            # 현물: 포지션 없으면 SELL 불가
            if state.position_side is None:
                return None
            # 중복 방지: 이미 청산됐으면 스킵
            if state.position_side == Side.SELL:
                return None
            return self._create_order(state, Side.SELL)

        return None

    def _create_order(self, state: MarketState, side: Side) -> Order:
        """Order 객체 생성 (내부용)"""
        order_type = self.get_order_type()
        limit_price = None

        if order_type == OrderType.LIMIT:
            limit_price = self.get_limit_price(state, side)

        return Order(
            side=side,
            quantity=self.quantity,
            order_type=order_type,
            limit_price=limit_price,
        )
