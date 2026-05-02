"""
CrossSectionalMomentum 전략

4개 코인의 과거 수익률을 랭킹하여
가장 강한 코인 LONG, 가장 약한 코인 SHORT.

AI Agent 워크플로우 테스트용 첫 포트폴리오 전략.
"""

from collections import deque
from typing import Optional

from intraday.strategy import MarketState, Order, Side, OrderType, PortfolioOrder


class CrossSectionalMomentumStrategy:
    """
    크로스섹셔널 모멘텀 전략

    매 rebalance_bars마다 코인별 과거 lookback_bars 수익률 기준
    랭킹하여 1위 LONG, 꼴찌 SHORT.

    Args:
        symbols: 거래할 심볼 목록
        lookback_bars: 모멘텀 측정 기간 (캔들 수, 기본 24 = 2시간@5분봉)
        rebalance_bars: 리밸런싱 주기 (캔들 수, 기본 24 = 2시간@5분봉)
        quantity: 코인당 주문 수량
    """

    def __init__(
        self,
        symbols: list[str],
        lookback_bars: int = 24,
        rebalance_bars: int = 24,
        quantity: float = 0.01,
    ):
        self.symbols = symbols
        self.lookback_bars = lookback_bars
        self.rebalance_bars = rebalance_bars
        self.quantity = quantity

        # 심볼별 close 가격 히스토리
        self._price_history: dict[str, deque] = {
            sym: deque(maxlen=lookback_bars + 1) for sym in symbols
        }

        # 리밸런싱 카운터 (심볼별 캔들 수)
        self._bar_count: int = 0

        # 현재 타겟 포지션
        self._target_long: Optional[str] = None
        self._target_short: Optional[str] = None

    def generate_order(self, state: MarketState) -> PortfolioOrder | None:
        """
        캔들 완성 시 호출. 패널 데이터에서 모멘텀 랭킹 계산.
        """
        if state.panel is None or state.symbol is None:
            return None

        # 패널에서 각 심볼의 close 업데이트
        for sym in self.symbols:
            if sym in state.panel and state.panel[sym].get("close") is not None:
                self._price_history[sym].append(state.panel[sym]["close"])

        self._bar_count += 1

        # 리밸런싱 주기가 아니면 스킵
        if self._bar_count % self.rebalance_bars != 0:
            return None

        # 모든 심볼에 충분한 히스토리가 있는지 확인
        for sym in self.symbols:
            if len(self._price_history[sym]) < self.lookback_bars + 1:
                return None

        # 모멘텀 (lookback 기간 수익률) 계산
        momentums = {}
        for sym in self.symbols:
            prices = list(self._price_history[sym])
            old_price = prices[0]
            new_price = prices[-1]
            if old_price > 0:
                momentums[sym] = (new_price - old_price) / old_price

        if len(momentums) < 2:
            return None

        # 랭킹: 수익률 기준 정렬
        ranked = sorted(momentums.keys(), key=lambda s: momentums[s])
        new_short = ranked[0]   # 가장 약한 코인
        new_long = ranked[-1]   # 가장 강한 코인

        # 주문 생성
        orders: dict[str, Optional[Order]] = {}

        for sym in self.symbols:
            current_side = None
            if state.positions and sym in state.positions:
                current_side = state.positions[sym].get("side")

            if sym == new_long:
                # LONG 타겟
                if current_side != "LONG":
                    orders[sym] = Order(
                        side=Side.BUY,
                        quantity=self.quantity,
                        order_type=OrderType.MARKET,
                    )
            elif sym == new_short:
                # SHORT 타겟
                if current_side != "SHORT":
                    orders[sym] = Order(
                        side=Side.SELL,
                        quantity=self.quantity,
                        order_type=OrderType.MARKET,
                    )
            else:
                # 중간 순위: 기존 포지션 청산
                if current_side == "LONG":
                    orders[sym] = Order(
                        side=Side.SELL,
                        quantity=self.quantity,
                        order_type=OrderType.MARKET,
                    )
                elif current_side == "SHORT":
                    orders[sym] = Order(
                        side=Side.BUY,
                        quantity=self.quantity,
                        order_type=OrderType.MARKET,
                    )

        self._target_long = new_long
        self._target_short = new_short

        if not orders:
            return None

        return PortfolioOrder(orders=orders)
