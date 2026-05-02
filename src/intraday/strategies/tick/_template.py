"""
Tick Strategy Template (agent coding baseline)

이 템플릿은 에이전트(Developer)가 `MyTickStrategy`를 그대로 복사해
전략 클래스를 만들 때의 시작점입니다.

핵심 원칙
- 전략은 항상 `StrategyBase`를 상속합니다.
- 상속 후 오버라이드 허용/금지 규칙을 반드시 지킵니다.
- 템플릿은 **참고용 골격**이며, 정책은 아래 "필수 규칙"이 최고 우선입니다.

=== 실행 규칙 (필수) ===
1) 상속 규칙
   - 클래스: `StrategyBase`
   - 금지 오버라이드: `__init__`, `generate_order`, `_create_order`
   - 권장 오버라이드: `setup`, `should_buy`, `should_sell`
   - 선택 오버라이드: `get_order_type`, `get_limit_price`

2) 파라미터/상태
   - 모든 파라미터는 `self.params.get("name", default)`로 읽기
   - 계산 상태(Deque, 카운터, 누적값)는 `setup()`에서 초기화

3) 테스트 호환성
   - 시장 상태 값 유효성은 직접 검사
   - 진입/청산 신호는 가능한 한 결정론적으로 작성
   - `state.position_side`/`state.position_qty`는 포지션 추적에만 사용

4) 호환성
   - 심볼 수 노출 용어는 혼용하지 않음
   - 파이프라인 경로 선택은 런처가 처리(`run_backtest` 내부), 전략은 `Order` 또는 `PortfolioOrder` 가능

=== 사용 가능한 MarketState 핵심 필드 ===
- state.imbalance: -1~+1 (buy_volume-sell_volume)/(buy_volume+sell_volume) 추정치
- state.mid_price / state.open / state.high / state.low / state.close
- state.volume / state.best_bid_qty / state.best_ask_qty / state.vwap
- state.position_side (Side.BUY/Side.SELL/None), state.position_qty
- (포트폴리오 모드) state.symbol, state.panel, state.positions: 선택적으로 사용 가능

주의: tick 데이터 특성상 orderbook가 없어 spread/spread_bps는 신뢰 지표로 보지 않습니다.
"""

from ..base import StrategyBase, MarketState, Order, Side, OrderType  # <<< DO NOT MODIFY


# >>> MODIFY: 클래스명을 전략명에 맞게 변경
class MyTickStrategy(StrategyBase):
    """
    >>> MODIFY: 전략 설명

    매수 조건 / 매도 조건:
      - ...
      - ...

    Parameters:
      - quantity: 주문 수량
      - (추가 파라미터)
    """

    # >>> MODIFY: 전략 파라미터와 상태 초기화
    def setup(self) -> None:
        """Initialize parameters and internal state."""
        self.buy_threshold = self.params.get("buy_threshold", 0.4)
        self.sell_threshold = self.params.get("sell_threshold", -0.4)
        # 예시 내부 상태
        self._prev_close: float | None = None

    # >>> MODIFY: 매수 신호
    def should_buy(self, state: MarketState) -> bool:
        """Return True when long entry conditions are met."""
        return state.imbalance > self.buy_threshold

    # >>> MODIFY: 매도 신호
    def should_sell(self, state: MarketState) -> bool:
        """Return True when exit conditions are met."""
        return state.imbalance < self.sell_threshold

    # >>> MODIFY (선택): 주문 타입. 전략 성격에 맞춰 변경
    def get_order_type(self) -> OrderType:
        """Default: MARKET for simplicity. Override to LIMIT when maker-first."""
        return OrderType.MARKET

    # >>> MODIFY (선택): LIMIT 주문 사용 시 가격 결정
    # def get_order_type(self) -> OrderType:
    #     return OrderType.LIMIT
    #
    # def get_limit_price(self, state: MarketState, side: Side) -> float:
    #     # 틱 데이터는 실제 호가가 없으므로 종가 기준으로 둠
    #     # 필요 시 슬리피지 버퍼 적용
    #     buffer = 0.0001
    #     if side == Side.BUY:
    #         return state.close * (1 - buffer)
    #     return state.close * (1 + buffer)


# =============================================================================
# 사용 예시 (참고, 실행 예시용)
# =============================================================================
#
# from intraday.strategies.tick.my_strategy import MyTickStrategy
# from intraday.backtest.tick_runner import TickBacktestRunner
#
# strategy = MyTickStrategy(
#     quantity=0.01,
#     buy_threshold=0.5,
#     sell_threshold=-0.5,
# )
#
# runner = TickBacktestRunner(
#     strategy=strategy,
#     data_path="./data/futures_ticks/BTCUSDT",
#     bar_type="VOLUME",
#     bar_size=10,
# )
# report = runner.run()
