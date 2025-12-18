"""
전략 구현 예시

stop_loss, take_profit, trailing_stop을 전략 레벨에서 구현하는 방법을 보여줍니다.
"""

from datetime import datetime
from typing import Optional

from .strategy import Strategy, MarketState, Order, Side, OrderType


class OBIStrategyWithStopLoss:
    """
    OBI 전략 + Stop Loss 구현 예시
    
    전략 레벨에서 포지션과 stop_loss를 추적하는 방법을 보여줍니다.
    """
    
    def __init__(
        self,
        buy_threshold: float = 0.3,
        sell_threshold: float = -0.3,
        quantity: float = 0.01,
        stop_loss_pct: float = 0.02,  # 2% 손절
        take_profit_pct: float = 0.05,  # 5% 익절
    ):
        self.buy_threshold = buy_threshold
        self.sell_threshold = sell_threshold
        self.quantity = quantity
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        
        # 전략이 내부적으로 포지션 추적
        self._position_side: Optional[Side] = None
        self._entry_price: float = 0.0
        self._position_quantity: float = 0.0
    
    def generate_order(self, state: MarketState) -> Order | None:
        """
        주문 생성 (리스크 관리 포함)
        
        전략이 MarketState를 받을 때마다:
        1. 현재 포지션이 있는지 확인
        2. stop_loss/take_profit 체크
        3. 조건 충족 시 청산 주문 생성
        4. 조건 미충족 시 신규 진입 신호 확인
        """
        # 1. 포지션이 있는 경우: 리스크 관리 체크
        if self._position_side is not None:
            # 손절/익절 체크
            if self._position_side == Side.BUY:
                stop_loss_price = self._entry_price * (1 - self.stop_loss_pct)
                take_profit_price = self._entry_price * (1 + self.take_profit_pct)
                
                if state.mid_price <= stop_loss_price:
                    # 손절 청산
                    qty = self._position_quantity
                    self._clear_position()
                    return Order(
                        side=Side.SELL,
                        quantity=qty,
                        order_type=OrderType.MARKET,
                    )
                
                if state.mid_price >= take_profit_price:
                    # 익절 청산
                    qty = self._position_quantity
                    self._clear_position()
                    return Order(
                        side=Side.SELL,
                        quantity=qty,
                        order_type=OrderType.MARKET,
                    )
            
            elif self._position_side == Side.SELL:
                stop_loss_price = self._entry_price * (1 + self.stop_loss_pct)
                take_profit_price = self._entry_price * (1 - self.take_profit_pct)
                
                if state.mid_price >= stop_loss_price:
                    qty = self._position_quantity
                    self._clear_position()
                    return Order(
                        side=Side.BUY,
                        quantity=qty,
                        order_type=OrderType.MARKET,
                    )
                
                if state.mid_price <= take_profit_price:
                    qty = self._position_quantity
                    self._clear_position()
                    return Order(
                        side=Side.BUY,
                        quantity=qty,
                        order_type=OrderType.MARKET,
                    )
            
            # 포지션이 있으면 신규 진입 신호 무시
            return None
        
        # 2. 포지션이 없는 경우: 신규 진입 신호 확인
        if state.imbalance > self.buy_threshold:
            self._position_side = Side.BUY
            self._entry_price = state.mid_price
            self._position_quantity = self.quantity
            
            return Order(
                side=Side.BUY,
                quantity=self.quantity,
                order_type=OrderType.LIMIT,
                limit_price=state.best_bid,
            )
        
        if state.imbalance < self.sell_threshold:
            self._position_side = Side.SELL
            self._entry_price = state.mid_price
            self._position_quantity = self.quantity
            
            return Order(
                side=Side.SELL,
                quantity=self.quantity,
                order_type=OrderType.LIMIT,
                limit_price=state.best_ask,
            )
        
        return None
    
    def _clear_position(self):
        """포지션 초기화"""
        self._position_side = None
        self._entry_price = 0.0
        self._position_quantity = 0.0
    
    def on_trade_executed(self, side: Side, price: float, quantity: float):
        """
        거래 체결 시 호출 (선택적)
        
        실제로는 Runner가 이 메서드를 호출하지 않으므로,
        전략이 체결 여부를 추정하거나, Runner를 확장하여 호출하도록 구현 가능
        """
        # 체결 확인 시 포지션 업데이트
        if side == Side.BUY:
            if self._position_side == Side.BUY:
                # 평균가 업데이트
                total_cost = self._entry_price * self._position_quantity + price * quantity
                self._position_quantity += quantity
                self._entry_price = total_cost / self._position_quantity
        elif side == Side.SELL:
            if self._position_side == Side.SELL:
                # 매도 포지션도 동일하게 처리
                ...


class TrailingStopStrategy:
    """
    Trailing Stop 구현 예시
    
    최고가를 추적하며, 일정 비율 하락 시 청산합니다.
    """
    
    def __init__(self, trailing_pct: float = 0.01, quantity: float = 0.01):  # 1% 트레일링
        self.trailing_pct = trailing_pct
        self.quantity = quantity
        self._position_side: Optional[Side] = None
        self._entry_price: float = 0.0
        self._position_quantity: float = 0.0
        self._highest_price: float = 0.0  # 최고가 추적
        self._lowest_price: float = float('inf')  # 최저가 추적
    
    def generate_order(self, state: MarketState) -> Order | None:
        """Trailing Stop 로직"""
        if self._position_side == Side.BUY:
            # 최고가 업데이트
            if state.mid_price > self._highest_price:
                self._highest_price = state.mid_price
            
            # Trailing Stop 체크: 최고가 대비 trailing_pct 하락 시 청산
            trailing_stop_price = self._highest_price * (1 - self.trailing_pct)
            
            if state.mid_price <= trailing_stop_price:
                self._clear_position()
                return Order(
                    side=Side.SELL,
                    quantity=self._position_quantity,
                    order_type=OrderType.MARKET,
                )
        
        elif self._position_side == Side.SELL:
            # 최저가 업데이트
            if state.mid_price < self._lowest_price:
                self._lowest_price = state.mid_price
            
            # Trailing Stop 체크: 최저가 대비 trailing_pct 상승 시 청산
            trailing_stop_price = self._lowest_price * (1 + self.trailing_pct)
            
            if state.mid_price >= trailing_stop_price:
                self._clear_position()
                return Order(
                    side=Side.BUY,
                    quantity=self._position_quantity,
                    order_type=OrderType.MARKET,
                )
        
        # 신규 진입 로직은 여기에...
        return None
    
    def _clear_position(self):
        """포지션 초기화"""
        self._position_side = None
        self._entry_price = 0.0
        self._highest_price = 0.0
        self._lowest_price = float('inf')
        self._position_quantity = 0.0

