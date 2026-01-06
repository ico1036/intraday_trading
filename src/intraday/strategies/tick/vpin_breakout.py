"""
VPIN Breakout Strategy

VPIN(Volume-Synchronized Probability of Informed Trading)과 가격 돌파를 결합한 전략.

VPIN 개념:
    - 볼륨 버킷 기반 order flow toxicity 측정
    - VPIN = Σ|V_buy - V_sell| / (n × V)
    - 높은 VPIN = informed trading 활발 = 방향성 있는 움직임

전략 로직:
    - 상단 돌파 + 높은 VPIN → BUY (추세 확인)
    - 하단 돌파 + 높은 VPIN → SELL (선물 숏 또는 청산)
    - VPIN이 낮으면 돌파해도 진입 안 함 (노이즈 필터)

선물 거래용:
    - 상단 돌파 → 롱 진입
    - 하단 돌파 → 숏 진입 (또는 롱 청산)
"""

from collections import deque

from ..base import StrategyBase, MarketState, Order, Side, OrderType


class VPINBreakoutStrategy(StrategyBase):
    """
    VPIN 기반 Breakout 전략 (선물용)

    진입 조건:
        - 상단 돌파: close > max(high[-N:]) + VPIN > threshold → BUY
        - 하단 돌파: close < min(low[-N:]) + VPIN > threshold → SELL (숏)

    청산 조건:
        - 반대 방향 돌파 시 (포지션 반전)

    Parameters:
        quantity: 주문 수량 (기본 0.01)
        n_buckets: VPIN 계산 윈도우 (기본 50)
        breakout_lookback: 돌파 판단 기간 (기본 20)
        vpin_threshold: VPIN 진입 임계값 (기본 0.4)

    사용 예시:
        strategy = VPINBreakoutStrategy(
            quantity=0.01,
            n_buckets=50,
            breakout_lookback=20,
            vpin_threshold=0.4,
        )
        runner = TickBacktestRunner(
            strategy=strategy,
            data_loader=loader,
            leverage=10,  # 선물 10x
            bar_type=CandleType.VOLUME,
        )
    """

    def setup(self) -> None:
        """파라미터 초기화"""
        self.n_buckets = self.params.get("n_buckets", 50)
        self.lookback = self.params.get("breakout_lookback", 20)
        self.vpin_threshold = self.params.get("vpin_threshold", 0.4)

        # VPIN 계산용 (rolling window)
        self._imbalances: deque[float] = deque(maxlen=self.n_buckets)
        self._volumes: deque[float] = deque(maxlen=self.n_buckets)

        # Breakout 판단용 (가격 히스토리)
        self._highs: deque[float] = deque(maxlen=self.lookback)
        self._lows: deque[float] = deque(maxlen=self.lookback)

        # 현재 VPIN 값 (캐시)
        self._current_vpin: float = 0.0

    def _update_state(self, state: MarketState) -> None:
        """
        캔들 데이터로 VPIN 및 가격 히스토리 업데이트

        교육 포인트:
            - TickRunner에서 best_bid_qty = buy_volume, best_ask_qty = sell_volume
            - VPIN = Σ|buy - sell| / Σ(buy + sell)
        """
        buy_vol = state.best_bid_qty
        sell_vol = state.best_ask_qty
        total_vol = buy_vol + sell_vol

        # 볼륨 데이터 추가
        if total_vol > 0:
            self._imbalances.append(abs(buy_vol - sell_vol))
            self._volumes.append(total_vol)

        # VPIN 계산
        if len(self._volumes) >= 2:
            total_volume = sum(self._volumes)
            if total_volume > 0:
                self._current_vpin = sum(self._imbalances) / total_volume

        # 가격 히스토리 추가
        if state.high is not None:
            self._highs.append(state.high)
        if state.low is not None:
            self._lows.append(state.low)

    def _is_upward_breakout(self, state: MarketState) -> bool:
        """상단 돌파 확인"""
        if len(self._highs) < self.lookback:
            return False

        # 이전 캔들들의 최고가 대비 현재 종가 비교
        previous_highs = list(self._highs)[:-1]  # 현재 캔들 제외
        if not previous_highs:
            return False

        return state.close is not None and state.close > max(previous_highs)

    def _is_downward_breakout(self, state: MarketState) -> bool:
        """하단 돌파 확인"""
        if len(self._lows) < self.lookback:
            return False

        # 이전 캔들들의 최저가 대비 현재 종가 비교
        previous_lows = list(self._lows)[:-1]  # 현재 캔들 제외
        if not previous_lows:
            return False

        return state.close is not None and state.close < min(previous_lows)

    def _is_high_vpin(self) -> bool:
        """VPIN이 threshold 이상인지 확인"""
        return self._current_vpin > self.vpin_threshold

    def should_buy(self, state: MarketState) -> bool:
        """
        매수 조건: 상단 돌파 + 높은 VPIN

        교육 포인트:
            - 단순 돌파만으로는 noise일 수 있음
            - VPIN이 높으면 informed trader가 참여 → 진짜 돌파
        """
        # 상단 돌파 + 높은 VPIN
        return self._is_upward_breakout(state) and self._is_high_vpin()

    def should_sell(self, state: MarketState) -> bool:
        """
        매도 조건: 하단 돌파 + 높은 VPIN

        선물 모드에서:
            - 포지션 없음 → 숏 진입
            - 롱 포지션 → 청산

        교육 포인트:
            - generate_order()를 오버라이드하여 선물 숏 지원
        """
        # 하단 돌파 + 높은 VPIN
        return self._is_downward_breakout(state) and self._is_high_vpin()

    def generate_order(self, state: MarketState) -> Order | None:
        """
        주문 생성 (선물용 오버라이드)

        StrategyBase와 차이점:
            - 포지션 없어도 SELL 가능 (선물 숏)
        """
        # 상태 업데이트 (한 번만)
        self._update_state(state)

        # 매수 조건 체크
        if self.should_buy(state):
            # 중복 방지: 이미 BUY 포지션이면 스킵
            if state.position_side == Side.BUY:
                return None
            return self._create_order(state, Side.BUY)

        # 매도 조건 체크
        if self.should_sell(state):
            # 선물: 포지션 없어도 SELL 가능 (숏 진입)
            # 중복 방지: 이미 SELL 포지션이면 스킵
            if state.position_side == Side.SELL:
                return None
            return self._create_order(state, Side.SELL)

        return None

    def get_order_type(self) -> OrderType:
        """시장가 주문 (빠른 체결)"""
        return OrderType.MARKET

    @property
    def current_vpin(self) -> float:
        """현재 VPIN 값 (모니터링/디버깅용)"""
        return self._current_vpin
