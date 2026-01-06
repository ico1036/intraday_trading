"""
Regime-based Strategy (PoC)

시장 국면(방향성/변동성)을 분석하여 전략을 스위칭합니다.

국면 분석:
    - Trend Score: 방향성 (-1 ~ +1)
    - Volatility Score: 변동성 (0 ~ 1)

전략 스위칭:
    - 강한 추세 → 추세추종 (모멘텀)
    - 높은 변동성 → 역추세 (평균회귀)
    - 그 외 → 관망
"""

from collections import deque
from dataclasses import dataclass

from ..base import StrategyBase, MarketState, Side, OrderType


@dataclass
class RegimeState:
    """시장 국면 상태"""
    trend_score: float      # -1 (하락) ~ +1 (상승)
    volatility_score: float # 0 (낮음) ~ 1 (높음)
    regime: str             # "trending_up", "trending_down", "mean_revert", "neutral"


class RegimeAnalyzer:
    """
    시장 국면 분석기

    캔들 히스토리를 기반으로 방향성과 변동성을 스코어링합니다.
    """

    def __init__(self, lookback: int = 20):
        """
        Args:
            lookback: 분석에 사용할 캔들 수
        """
        self.lookback = lookback
        self._prices: deque[float] = deque(maxlen=lookback)
        self._ranges: deque[float] = deque(maxlen=lookback)
        self._deltas: deque[float] = deque(maxlen=lookback)  # buy - sell volume

    def update(self, price: float, high: float, low: float,
               buy_volume: float, sell_volume: float) -> None:
        """캔들 데이터 업데이트"""
        self._prices.append(price)
        self._ranges.append(high - low)
        self._deltas.append(buy_volume - sell_volume)

    def get_trend_score(self) -> float:
        """
        방향성 스코어 (-1 ~ +1)

        계산 방식:
            1. 가격 변화율: (현재가 - N개전 가격) / N개전 가격
            2. 정규화하여 -1 ~ +1 범위로
        """
        if len(self._prices) < 2:
            return 0.0

        # 가격 변화율
        oldest = self._prices[0]
        newest = self._prices[-1]

        if oldest == 0:
            return 0.0

        change_pct = (newest - oldest) / oldest

        # -1 ~ +1로 정규화 (0.1% = 10bps 변화를 최대치로 가정 - 볼륨바)
        normalized = max(-1.0, min(1.0, change_pct / 0.001))

        return normalized

    def get_volatility_score(self) -> float:
        """
        변동성 스코어 (0 ~ 1)

        계산 방식:
            1. 평균 캔들 범위 (ATR 유사)
            2. 현재가 대비 비율로 정규화
        """
        if len(self._ranges) < 2 or len(self._prices) < 1:
            return 0.0

        avg_range = sum(self._ranges) / len(self._ranges)
        current_price = self._prices[-1]

        if current_price == 0:
            return 0.0

        # 평균 범위를 가격 대비 비율로 (bps)
        range_bps = (avg_range / current_price) * 10000

        # 0 ~ 1로 정규화 (3 bps를 최대치로 가정 - 볼륨바)
        normalized = min(1.0, range_bps / 3)

        return normalized

    def get_cvd_score(self) -> float:
        """
        CVD (Cumulative Volume Delta) 스코어 (-1 ~ +1)

        매수 체결량 - 매도 체결량의 누적
        """
        if len(self._deltas) < 2:
            return 0.0

        total_delta = sum(self._deltas)
        total_volume = sum(abs(d) for d in self._deltas)

        if total_volume == 0:
            return 0.0

        return total_delta / total_volume

    def analyze(self) -> RegimeState:
        """현재 시장 국면 분석"""
        trend = self.get_trend_score()
        volatility = self.get_volatility_score()

        # 국면 결정
        if trend > 0.3:
            regime = "trending_up"
        elif trend < -0.3:
            regime = "trending_down"
        elif volatility > 0.5:
            regime = "mean_revert"
        else:
            regime = "neutral"

        return RegimeState(
            trend_score=trend,
            volatility_score=volatility,
            regime=regime,
        )


class RegimeStrategy(StrategyBase):
    """
    국면 기반 전략 (PoC)

    시장 국면에 따라 다른 매매 로직을 적용합니다.

    전략 로직:
        - trending_up (상승 추세): 매수 (추세추종)
        - trending_down (하락 추세): 관망 (현물이라 숏 불가)
        - mean_revert (높은 변동성): 급락 시 매수 (역추세)
        - neutral: 관망

    Parameters:
        quantity: 주문 수량 (기본 0.01)
        lookback: 국면 분석에 사용할 캔들 수 (기본 20)
        trend_threshold: 추세 판단 임계값 (기본 0.3)
        volatility_threshold: 변동성 판단 임계값 (기본 0.5)
        mean_revert_entry: 역추세 진입 조건 (imbalance 임계값, 기본 -0.4)

    사용 예시:
        strategy = RegimeStrategy(
            quantity=0.01,
            lookback=20,
            trend_threshold=0.3,
        )
        runner = TickBacktestRunner(strategy=strategy, bar_type=CandleType.VOLUME, ...)
    """

    def setup(self) -> None:
        self.lookback = self.params.get("lookback", 20)
        self.trend_threshold = self.params.get("trend_threshold", 0.3)
        self.volatility_threshold = self.params.get("volatility_threshold", 0.5)
        self.mean_revert_entry = self.params.get("mean_revert_entry", -0.4)
        self.trend_exit = self.params.get("trend_exit", -0.2)

        # 국면 분석기
        self._analyzer = RegimeAnalyzer(lookback=self.lookback)
        self._regime: RegimeState | None = None
        self._candle_count = 0

    def on_candle(self, price: float, high: float, low: float,
                  buy_volume: float, sell_volume: float) -> None:
        """
        캔들 완성 시 호출 (Runner에서 호출해야 함)

        Note: 현재 Runner는 이 메서드를 호출하지 않음.
              PoC에서는 MarketState만으로 간단히 구현.
        """
        self._analyzer.update(price, high, low, buy_volume, sell_volume)
        self._regime = self._analyzer.analyze()
        self._candle_count += 1

    def _update_from_state(self, state: MarketState) -> None:
        """MarketState에서 OHLCV로 업데이트"""
        # OHLCV 필드가 있으면 사용, 없으면 추정
        if state.high is not None and state.low is not None:
            high = state.high
            low = state.low
        else:
            high = state.mid_price * 1.001
            low = state.mid_price * 0.999

        # 볼륨 정보
        if state.volume is not None:
            # best_bid_qty, best_ask_qty는 buy/sell volume으로 매핑됨
            buy_volume = state.best_bid_qty
            sell_volume = state.best_ask_qty
        else:
            buy_volume = max(0, state.imbalance)
            sell_volume = max(0, -state.imbalance)

        price = state.close if state.close is not None else state.mid_price

        self._analyzer.update(
            price=price,
            high=high,
            low=low,
            buy_volume=buy_volume,
            sell_volume=sell_volume,
        )
        self._regime = self._analyzer.analyze()
        self._candle_count += 1

    def should_buy(self, state: MarketState) -> bool:
        """
        매수 조건

        - trending_up: 추세추종 매수
        - mean_revert: 급락 시 역추세 매수
        """
        self._update_from_state(state)

        # 충분한 데이터가 쌓이기 전에는 거래 안 함
        if self._candle_count < self.lookback // 2:
            return False

        if self._regime is None:
            return False

        regime = self._regime.regime

        # 추세추종: 상승 추세에서 매수
        if regime == "trending_up":
            # 추가 확인: imbalance도 양수여야 함
            return state.imbalance > 0

        # 역추세: 높은 변동성 + 급락 시 매수 (평균회귀 기대)
        if regime == "mean_revert":
            return state.imbalance < self.mean_revert_entry

        return False

    def should_sell(self, state: MarketState) -> bool:
        """
        매도 조건 (청산)

        - trending_up → 추세 약화 시 청산
        - mean_revert → 반등 시 청산
        """
        if self._regime is None:
            return False

        regime = self._regime.regime

        # 추세추종 청산: 추세 약화
        if regime == "trending_up":
            return state.imbalance < self.trend_exit

        # 역추세 청산: 반등 (imbalance 양수로 전환)
        if regime == "mean_revert":
            return state.imbalance > 0.2

        # 추세 하락 전환 시 청산
        if regime == "trending_down":
            return True

        return False

    def get_order_type(self) -> OrderType:
        return OrderType.MARKET

    @property
    def current_regime(self) -> RegimeState | None:
        """현재 국면 상태 (디버깅/모니터링용)"""
        return self._regime
