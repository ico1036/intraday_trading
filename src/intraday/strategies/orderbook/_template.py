"""
Orderbook Strategy Template (에이전트 참조용)

Orderbook 데이터 기반 전략을 만들 때 이 파일을 복사하세요.
OrderbookBacktestRunner 또는 ForwardRunner와 함께 사용합니다.

=== 데이터 소스 ===
- OrderbookBacktestRunner: 과거 오더북 스냅샷
- ForwardRunner: 실시간 오더북 + 체결 데이터

=== 사용 가능한 MarketState 필드 ===
- state.imbalance: 오더북 불균형 (OBI, -1 ~ +1)
- state.spread: Bid-Ask 스프레드 (절대값)
- state.spread_bps: 스프레드 (basis points)
- state.best_bid / state.best_ask: 실제 최우선 호가
- state.best_bid_qty / state.best_ask_qty: 호가 수량
- state.mid_price: 중간가
- state.position_side: 현재 포지션 (Side.BUY/SELL/None)
- state.position_qty: 현재 포지션 수량

=== 적합한 전략 유형 ===
- OBI (Order Book Imbalance) 전략
- 스프레드 기반 전략
- 마켓 메이킹
- 호가창 depth 분석

=== 수정 가능/불가 영역 ===
# >>> MODIFY: 수정 가능
# <<< DO NOT MODIFY: 수정 금지
"""

from ..base import StrategyBase, MarketState, Order, Side, OrderType  # <<< DO NOT MODIFY


# >>> MODIFY: 클래스명을 전략에 맞게 변경하세요
class MyOrderbookStrategy(StrategyBase):
    """
    >>> MODIFY: 전략 설명을 작성하세요

    전략 로직:
        - 매수 조건: ...
        - 매도 조건: ...

    Parameters:
        quantity: 주문 수량
        (추가 파라미터 설명)
    """

    # >>> MODIFY: 초기화 로직
    def setup(self) -> None:
        """파라미터 초기화"""
        self.buy_threshold = self.params.get("buy_threshold", 0.3)
        self.sell_threshold = self.params.get("sell_threshold", -0.3)
        self.max_spread_bps = self.params.get("max_spread_bps", 10.0)

    # >>> MODIFY: 매수 조건 구현 (필수)
    def should_buy(self, state: MarketState) -> bool:
        """
        매수 조건 판단

        Orderbook 전략에서 자주 쓰는 조건:
            - state.imbalance > threshold (OBI)
            - state.spread_bps < max_spread (스프레드 필터)
            - state.best_bid_qty > state.best_ask_qty (수량 비교)
        """
        # 스프레드가 너무 넓으면 진입 안 함
        if state.spread_bps > self.max_spread_bps:
            return False

        return state.imbalance > self.buy_threshold

    # >>> MODIFY: 매도 조건 구현 (필수)
    def should_sell(self, state: MarketState) -> bool:
        """매도 조건 판단"""
        return state.imbalance < self.sell_threshold

    # >>> MODIFY (선택): LIMIT 주문 사용 시 오버라이드
    def get_order_type(self) -> OrderType:
        """Orderbook 전략은 보통 LIMIT 주문 사용"""
        return OrderType.LIMIT

    # >>> MODIFY (선택): LIMIT 주문 가격 커스터마이즈
    def get_limit_price(self, state: MarketState, side: Side) -> float:
        """
        Orderbook 전략 가격 설정 예시:
            - Taker: best_ask(BUY) / best_bid(SELL) → 즉시 체결
            - Maker: best_bid(BUY) / best_ask(SELL) → 호가에 대기
        """
        if side == Side.BUY:
            return state.best_ask  # Taker 방식
        else:
            return state.best_bid  # Taker 방식


# =============================================================================
# 사용 예시 (백테스트)
# =============================================================================
#
# from intraday.strategies.orderbook.my_strategy import MyOrderbookStrategy
# from intraday.backtest import OrderbookBacktestRunner
# from intraday.data import OrderbookDataLoader
#
# strategy = MyOrderbookStrategy(
#     quantity=0.01,
#     buy_threshold=0.3,
#     max_spread_bps=5.0,
# )
#
# loader = OrderbookDataLoader(Path("./data/orderbook"))
# runner = OrderbookBacktestRunner(strategy=strategy, data_loader=loader)
# report = runner.run()
