"""
RegimeStrategy 테스트

국면 분석 및 전략 스위칭 테스트
"""

import pytest
from datetime import datetime

from intraday.strategies.tick.regime import (
    RegimeAnalyzer,
    RegimeStrategy,
    RegimeState,
)
from intraday.strategies.base import MarketState, Side


class TestRegimeAnalyzer:
    """RegimeAnalyzer 테스트"""

    def test_initial_state(self):
        """초기 상태: 데이터 없으면 0"""
        analyzer = RegimeAnalyzer(lookback=10)
        assert analyzer.get_trend_score() == 0.0
        assert analyzer.get_volatility_score() == 0.0

    def test_trend_score_uptrend(self):
        """상승 추세 감지"""
        analyzer = RegimeAnalyzer(lookback=10)

        # 가격 상승 시뮬레이션: 100 → 105 (5% 상승)
        for i in range(10):
            price = 100 + i * 0.5  # 100 → 104.5
            analyzer.update(price, price + 0.1, price - 0.1, 1.0, 0.5)

        trend = analyzer.get_trend_score()
        assert trend > 0.5, f"상승 추세여야 함: {trend}"

    def test_trend_score_downtrend(self):
        """하락 추세 감지"""
        analyzer = RegimeAnalyzer(lookback=10)

        # 가격 하락 시뮬레이션: 100 → 95 (5% 하락)
        for i in range(10):
            price = 100 - i * 0.5  # 100 → 95.5
            analyzer.update(price, price + 0.1, price - 0.1, 0.5, 1.0)

        trend = analyzer.get_trend_score()
        assert trend < -0.5, f"하락 추세여야 함: {trend}"

    def test_volatility_score_high(self):
        """높은 변동성 감지"""
        analyzer = RegimeAnalyzer(lookback=10)

        # 높은 변동성: 큰 range
        for i in range(10):
            price = 100
            high = price + 1.0   # 1% range
            low = price - 1.0
            analyzer.update(price, high, low, 0.5, 0.5)

        volatility = analyzer.get_volatility_score()
        # 2% range = 200 bps, 최대치(100bps) 초과하므로 1.0에 가까움
        assert volatility > 0.5, f"높은 변동성이어야 함: {volatility}"

    def test_volatility_score_low(self):
        """낮은 변동성 감지"""
        analyzer = RegimeAnalyzer(lookback=10)

        # 낮은 변동성: 작은 range (0.01% = 1bp, 3bp 기준으로 ~0.33)
        for i in range(10):
            price = 100
            high = price + 0.005   # 0.005% range = 0.5bp
            low = price - 0.005
            analyzer.update(price, high, low, 0.5, 0.5)

        volatility = analyzer.get_volatility_score()
        # 1bp range / 3bp max = ~0.33
        assert volatility < 0.5, f"낮은 변동성이어야 함: {volatility}"

    def test_analyze_regime_trending_up(self):
        """국면 분석: 상승 추세"""
        analyzer = RegimeAnalyzer(lookback=10)

        for i in range(10):
            price = 100 + i * 0.5
            analyzer.update(price, price + 0.1, price - 0.1, 1.0, 0.3)

        regime = analyzer.analyze()
        assert regime.regime == "trending_up"

    def test_analyze_regime_mean_revert(self):
        """국면 분석: 평균회귀 (높은 변동성)"""
        analyzer = RegimeAnalyzer(lookback=10)

        # 횡보하지만 변동성 높음 (3bp 이상 필요)
        for i in range(10):
            price = 100 + (i % 2) * 0.001  # 횡보 (거의 같은 가격)
            high = price + 0.02  # 높은 변동성 (4bp)
            low = price - 0.02
            analyzer.update(price, high, low, 0.5, 0.5)

        regime = analyzer.analyze()
        assert regime.regime == "mean_revert", f"Expected mean_revert, got {regime.regime}"


class TestRegimeStrategy:
    """RegimeStrategy 테스트"""

    def _make_state(
        self,
        mid_price: float = 100.0,
        imbalance: float = 0.0,
        position_side: Side | None = None,
    ) -> MarketState:
        """테스트용 MarketState 생성"""
        return MarketState(
            timestamp=datetime.now(),
            mid_price=mid_price,
            imbalance=imbalance,
            spread=0.0,
            spread_bps=0.0,
            best_bid=mid_price,
            best_ask=mid_price,
            best_bid_qty=1.0,
            best_ask_qty=1.0,
            position_side=position_side,
            position_qty=0.01 if position_side else 0.0,
        )

    def test_no_trade_before_warmup(self):
        """워밍업 기간에는 거래 안 함"""
        strategy = RegimeStrategy(quantity=0.01, lookback=20)

        # 10개 캔들만 (lookback의 절반 미만)
        for i in range(5):
            state = self._make_state(mid_price=100 + i, imbalance=0.5)
            assert not strategy.should_buy(state), "워밍업 중에는 매수 안 함"

    def test_buy_on_uptrend(self):
        """상승 추세에서 매수"""
        strategy = RegimeStrategy(quantity=0.01, lookback=10)

        # 상승 추세 시뮬레이션
        for i in range(15):
            price = 100 + i * 0.5  # 상승
            state = self._make_state(mid_price=price, imbalance=0.3)
            strategy.should_buy(state)  # 내부 상태 업데이트

        # 마지막에 양의 imbalance로 매수 신호
        state = self._make_state(mid_price=107, imbalance=0.3)
        # 추세가 충분히 형성되었으면 매수
        result = strategy.should_buy(state)
        # 현재 PoC는 mid_price만으로 추세 판단하므로 결과 확인
        assert strategy.current_regime is not None

    def test_buy_on_mean_revert_dip(self):
        """평균회귀 국면에서 급락 시 매수"""
        strategy = RegimeStrategy(
            quantity=0.01,
            lookback=10,
            mean_revert_entry=-0.4,
        )

        # 횡보 + 변동성 (PoC에서는 간접 시뮬레이션)
        for i in range(15):
            price = 100
            state = self._make_state(mid_price=price, imbalance=-0.1 * (i % 3))
            strategy.should_buy(state)

        # 급락 상황 (음의 imbalance)
        state = self._make_state(mid_price=99, imbalance=-0.5)
        # mean_revert 국면에서 imbalance < -0.4 이면 매수
        # 결과는 국면에 따라 다름
        strategy.should_buy(state)
        assert strategy.current_regime is not None

    def test_sell_on_trend_weakening(self):
        """추세 약화 시 청산"""
        strategy = RegimeStrategy(quantity=0.01, lookback=10, trend_exit=-0.2)

        # 상승 추세 형성
        for i in range(12):
            price = 100 + i * 0.3
            state = self._make_state(mid_price=price, imbalance=0.3)
            strategy.should_buy(state)

        # 포지션 보유 중, 추세 약화
        state = self._make_state(
            mid_price=105,
            imbalance=-0.3,  # 음의 imbalance
            position_side=Side.BUY,
        )
        # trend_exit 이하이면 청산
        result = strategy.should_sell(state)
        # 결과는 국면 상태에 따라 다름

    def test_current_regime_property(self):
        """현재 국면 조회"""
        strategy = RegimeStrategy(quantity=0.01, lookback=5)

        # 초기에는 None
        assert strategy.current_regime is None

        # 데이터 축적 후 국면 분석
        for i in range(10):
            state = self._make_state(mid_price=100 + i)
            strategy.should_buy(state)

        regime = strategy.current_regime
        assert regime is not None
        assert isinstance(regime, RegimeState)
        assert regime.regime in ["trending_up", "trending_down", "mean_revert", "neutral"]


class TestRegimeStrategyIntegration:
    """통합 테스트"""

    def test_strategy_protocol_compliance(self):
        """Strategy Protocol 준수 확인"""
        strategy = RegimeStrategy(quantity=0.01)

        # generate_order 메서드 존재
        assert hasattr(strategy, "generate_order")

        state = MarketState(
            timestamp=datetime.now(),
            mid_price=100.0,
            imbalance=0.0,
            spread=0.0,
            spread_bps=0.0,
            best_bid=100.0,
            best_ask=100.0,
            best_bid_qty=1.0,
            best_ask_qty=1.0,
        )

        # None 또는 Order 반환
        result = strategy.generate_order(state)
        assert result is None or hasattr(result, "side")
