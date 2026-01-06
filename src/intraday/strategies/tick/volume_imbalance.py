"""
Volume Imbalance Strategy

틱 볼륨 방향성을 기반으로 매매 신호를 생성합니다.
"""

from ..base import StrategyBase, MarketState, OrderType


class VolumeImbalanceStrategy(StrategyBase):
    """
    볼륨 불균형 기반 전략

    전략 로직:
        - 볼륨 imbalance > buy_threshold → 시장가 매수
        - 볼륨 imbalance < sell_threshold → 시장가 매도

    Parameters:
        quantity: 주문 수량 (기본 0.01)
        buy_threshold: 매수 임계값 (기본 0.4)
        sell_threshold: 매도 임계값 (기본 -0.4)

    사용 예시:
        strategy = VolumeImbalanceStrategy(quantity=0.01, buy_threshold=0.5)
        runner = TickBacktestRunner(strategy=strategy, bar_type=CandleType.VOLUME, ...)
    """

    def setup(self) -> None:
        self.buy_threshold = self.params.get("buy_threshold", 0.4)
        self.sell_threshold = self.params.get("sell_threshold", -0.4)

    def should_buy(self, state: MarketState) -> bool:
        return state.imbalance > self.buy_threshold

    def should_sell(self, state: MarketState) -> bool:
        return state.imbalance < self.sell_threshold

    def get_order_type(self) -> OrderType:
        return OrderType.MARKET
