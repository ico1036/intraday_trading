"""
OBI (Order Book Imbalance) Strategy

오더북 불균형을 기반으로 매매 신호를 생성합니다.
"""

from ..base import StrategyBase, MarketState, Side, OrderType


class OBIStrategy(StrategyBase):
    """
    OBI (Order Book Imbalance) 기반 전략

    전략 로직:
        - imbalance > buy_threshold → 매수 (매수 압력 강함)
        - imbalance < sell_threshold → 매도 (매도 압력 강함)

    Parameters:
        quantity: 주문 수량 (기본 0.01)
        buy_threshold: 매수 임계값 (기본 0.3)
        sell_threshold: 매도 임계값 (기본 -0.3)

    사용 예시:
        strategy = OBIStrategy(quantity=0.01, buy_threshold=0.3)
        runner = OrderbookBacktestRunner(strategy=strategy, ...)
    """

    def setup(self) -> None:
        self.buy_threshold = self.params.get("buy_threshold", 0.3)
        self.sell_threshold = self.params.get("sell_threshold", -0.3)

    def should_buy(self, state: MarketState) -> bool:
        return state.imbalance > self.buy_threshold

    def should_sell(self, state: MarketState) -> bool:
        return state.imbalance < self.sell_threshold

    def get_order_type(self) -> OrderType:
        return OrderType.LIMIT

    def get_limit_price(self, state: MarketState, side: Side) -> float:
        # Taker 방식: 즉시 체결
        if side == Side.BUY:
            return state.best_ask
        else:
            return state.best_bid
