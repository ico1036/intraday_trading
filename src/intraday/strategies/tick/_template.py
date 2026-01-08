"""
Tick Strategy Template (에이전트 참조용)

Tick(체결) 데이터 기반 전략을 만들 때 이 파일을 복사하세요.
TickBacktestRunner와 함께 사용합니다.

=== 데이터 소스 ===
- TickBacktestRunner: 과거 체결 데이터 → 캔들(Volume/Tick/Time/Dollar)

=== 사용 가능한 MarketState 필드 ===
- state.imbalance: 볼륨 불균형 (매수-매도 비율, -1 ~ +1)
- state.mid_price: 캔들 종가
- state.spread: 항상 0 (오더북 없음)
- state.spread_bps: 항상 0
- state.best_bid / state.best_ask: 캔들 종가 (추정치)
- state.position_side: 현재 포지션 (Side.BUY/SELL/None)
- state.position_qty: 현재 포지션 수량

=== Tick 전략에서 추가로 사용 가능한 Candle 속성 ===
(TickBacktestRunner 내부에서 Candle 객체로 접근 가능)
- candle.buy_volume / candle.sell_volume: 매수/매도 체결량
- candle.vwap: 거래량 가중 평균가
- candle.volume_imbalance: (buy - sell) / total
- candle.trade_count: 체결 수

=== 적합한 전략 유형 ===
- 볼륨 불균형 전략
- 모멘텀 전략
- VWAP 기반 전략
- Footprint / Delta 분석
- CVD (Cumulative Volume Delta)

=== 외부 데이터 접근 (선택) ===
- Funding Rate: self.params.get("funding_loader") 또는 setup()에서 직접 로드
- 외부 지표: setup()에서 계산 및 저장, should_buy()에서 사용

=== 수정 가능/불가 영역 ===
# >>> MODIFY: 수정 가능
# <<< DO NOT MODIFY: 수정 금지
"""

from ..base import StrategyBase, MarketState, Order, Side, OrderType  # <<< DO NOT MODIFY


# >>> MODIFY: 클래스명을 전략에 맞게 변경하세요
class MyTickStrategy(StrategyBase):
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
        """
        파라미터 초기화

        외부 데이터 접근 예시:
            # Funding Rate 사용 시
            self.funding_loader = self.params.get("funding_loader")

            # 또는 직접 로드
            # from intraday.funding import FundingRateLoader
            # self.funding_loader = FundingRateLoader.from_list(rates)

            # Rolling window 사용 시
            # from collections import deque
            # self.price_history = deque(maxlen=50)
        """
        self.buy_threshold = self.params.get("buy_threshold", 0.4)
        self.sell_threshold = self.params.get("sell_threshold", -0.4)

    # >>> MODIFY: 매수 조건 구현 (필수)
    def should_buy(self, state: MarketState) -> bool:
        """
        매수 조건 판단

        Tick 전략에서 자주 쓰는 조건:
            - state.imbalance > threshold (볼륨 불균형)
            - 가격 모멘텀 (이전 캔들 대비)
            - CVD 추세 (누적 delta)
        """
        return state.imbalance > self.buy_threshold

    # >>> MODIFY: 매도 조건 구현 (필수)
    def should_sell(self, state: MarketState) -> bool:
        """매도 조건 판단"""
        return state.imbalance < self.sell_threshold

    # >>> MODIFY (선택): 주문 타입
    def get_order_type(self) -> OrderType:
        """Tick 전략은 보통 MARKET 주문 (스프레드 정보 없음)"""
        return OrderType.MARKET

    # >>> MODIFY (선택): LIMIT 주문 사용 시
    # def get_order_type(self) -> OrderType:
    #     return OrderType.LIMIT
    #
    # def get_limit_price(self, state: MarketState, side: Side) -> float:
    #     # Tick 데이터는 실제 호가가 없으므로 캔들 종가 기준
    #     # 슬리피지 고려 시 약간의 버퍼 추가 가능
    #     buffer = 0.0001  # 0.01%
    #     if side == Side.BUY:
    #         return state.mid_price * (1 + buffer)
    #     else:
    #         return state.mid_price * (1 - buffer)


# =============================================================================
# 사용 예시 (백테스트)
# =============================================================================
#
# from intraday.strategies.tick.my_strategy import MyTickStrategy
# from intraday.backtest import TickBacktestRunner
# from intraday.data import TickDataLoader
# from intraday import CandleType
#
# strategy = MyTickStrategy(
#     quantity=0.01,
#     buy_threshold=0.5,
#     sell_threshold=-0.5,
# )
#
# loader = TickDataLoader(Path("./data/ticks"))
# runner = TickBacktestRunner(
#     strategy=strategy,
#     data_loader=loader,
#     bar_type=CandleType.VOLUME,
#     bar_size=1.0,  # 1 BTC마다 캔들
# )
# report = runner.run()
