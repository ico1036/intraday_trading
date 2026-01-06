"""
VPIN Breakout Strategy 테스트

TDD 방식: 클라이언트 관점에서 기대 동작 정의
"""

from datetime import datetime

import pytest

from intraday.strategy import MarketState, Side


def make_market_state(
    close: float,
    high: float,
    low: float,
    buy_volume: float,
    sell_volume: float,
    position_side: Side | None = None,
) -> MarketState:
    """테스트용 MarketState 생성"""
    return MarketState(
        timestamp=datetime.now(),
        mid_price=close,
        imbalance=(buy_volume - sell_volume) / (buy_volume + sell_volume) if (buy_volume + sell_volume) > 0 else 0,
        spread=0.0,
        spread_bps=0.0,
        best_bid=close,
        best_ask=close,
        best_bid_qty=buy_volume,  # TickRunner에서 buy_volume으로 매핑됨
        best_ask_qty=sell_volume,  # TickRunner에서 sell_volume으로 매핑됨
        position_side=position_side,
        position_qty=0.01 if position_side else 0.0,
        open=close,
        high=high,
        low=low,
        close=close,
        volume=buy_volume + sell_volume,
        vwap=close,
    )


class TestVPINBreakoutStrategy:
    """VPIN Breakout 전략 테스트"""

    def test_buy_on_upward_breakout_with_high_vpin(self):
        """상단 돌파 + 높은 VPIN → BUY 신호"""
        from intraday.strategies.tick.vpin_breakout import VPINBreakoutStrategy

        strategy = VPINBreakoutStrategy(
            quantity=0.01,
            n_buckets=5,
            breakout_lookback=3,
            vpin_threshold=0.3,
        )

        # Given: lookback 기간 동안 가격 히스토리 쌓기
        # 매수 압력이 점점 높아지는 상황 (VPIN 상승)
        for i in range(3):
            state = make_market_state(
                close=100.0,
                high=101.0,
                low=99.0,
                buy_volume=6.0 + i,  # 점점 매수 압력 증가
                sell_volume=4.0 - i,
            )
            order = strategy.generate_order(state)
            assert order is None  # 돌파 전이라 신호 없음

        # When: 상단 돌파 + 높은 VPIN (강한 매수 압력)
        breakout_state = make_market_state(
            close=105.0,  # 이전 high (101) 돌파
            high=106.0,
            low=104.0,
            buy_volume=9.0,  # 강한 불균형 → 높은 VPIN
            sell_volume=1.0,
        )
        order = strategy.generate_order(breakout_state)

        # Then: BUY 신호
        assert order is not None
        assert order.side == Side.BUY

    def test_sell_on_downward_breakout_with_high_vpin(self):
        """하단 돌파 + 높은 VPIN → SELL 신호 (선물 숏)"""
        from intraday.strategies.tick.vpin_breakout import VPINBreakoutStrategy

        strategy = VPINBreakoutStrategy(
            quantity=0.01,
            n_buckets=5,
            breakout_lookback=3,
            vpin_threshold=0.3,
        )

        # Given: lookback 기간 동안 가격 히스토리 쌓기
        # 매도 압력이 점점 높아지는 상황 (VPIN 상승)
        for i in range(3):
            state = make_market_state(
                close=100.0,
                high=101.0,
                low=99.0,
                buy_volume=4.0 - i,  # 점점 매도 압력 증가
                sell_volume=6.0 + i,
            )
            strategy.generate_order(state)

        # When: 하단 돌파 + 높은 VPIN (강한 매도 압력)
        breakout_state = make_market_state(
            close=95.0,  # 이전 low (99) 하향 돌파
            high=96.0,
            low=94.0,
            buy_volume=1.0,  # 강한 불균형 → 높은 VPIN
            sell_volume=9.0,
        )
        order = strategy.generate_order(breakout_state)

        # Then: SELL 신호 (선물 숏 진입)
        assert order is not None
        assert order.side == Side.SELL

    def test_no_signal_when_vpin_low(self):
        """돌파했지만 VPIN 낮으면 → 신호 없음 (노이즈 필터)"""
        from intraday.strategies.tick.vpin_breakout import VPINBreakoutStrategy

        strategy = VPINBreakoutStrategy(
            quantity=0.01,
            n_buckets=5,
            breakout_lookback=3,
            vpin_threshold=0.5,  # 높은 threshold
        )

        # Given: lookback 기간 동안 가격 히스토리 쌓기
        for i in range(3):
            state = make_market_state(
                close=100.0,
                high=101.0,
                low=99.0,
                buy_volume=5.0,
                sell_volume=5.0,
            )
            strategy.generate_order(state)

        # When: 상단 돌파 BUT 균형 잡힌 볼륨 (낮은 VPIN)
        breakout_state = make_market_state(
            close=105.0,  # 돌파
            high=106.0,
            low=104.0,
            buy_volume=5.0,  # 균형 → 낮은 VPIN
            sell_volume=5.0,
        )
        order = strategy.generate_order(breakout_state)

        # Then: 신호 없음 (VPIN 필터)
        assert order is None

    def test_no_signal_when_no_breakout(self):
        """높은 VPIN이지만 돌파 없으면 → 신호 없음"""
        from intraday.strategies.tick.vpin_breakout import VPINBreakoutStrategy

        strategy = VPINBreakoutStrategy(
            quantity=0.01,
            n_buckets=5,
            breakout_lookback=3,
            vpin_threshold=0.3,
        )

        # Given: lookback 기간 동안 가격 히스토리 쌓기
        for i in range(3):
            state = make_market_state(
                close=100.0,
                high=101.0,
                low=99.0,
                buy_volume=5.0,
                sell_volume=5.0,
            )
            strategy.generate_order(state)

        # When: 높은 VPIN BUT 돌파 없음 (범위 내)
        state = make_market_state(
            close=100.5,  # 이전 high(101) 미달
            high=100.8,
            low=100.0,
            buy_volume=9.0,  # 높은 VPIN
            sell_volume=1.0,
        )
        order = strategy.generate_order(state)

        # Then: 신호 없음 (돌파 필터)
        assert order is None

    def test_no_duplicate_buy_when_already_long(self):
        """이미 롱 포지션이면 추가 BUY 없음"""
        from intraday.strategies.tick.vpin_breakout import VPINBreakoutStrategy

        strategy = VPINBreakoutStrategy(
            quantity=0.01,
            n_buckets=5,
            breakout_lookback=3,
            vpin_threshold=0.3,
        )

        # Given: lookback 기간 쌓기
        for i in range(3):
            state = make_market_state(
                close=100.0, high=101.0, low=99.0,
                buy_volume=5.0, sell_volume=5.0,
            )
            strategy.generate_order(state)

        # When: 돌파 + 높은 VPIN + 이미 롱 포지션
        breakout_state = make_market_state(
            close=105.0, high=106.0, low=104.0,
            buy_volume=9.0, sell_volume=1.0,
            position_side=Side.BUY,  # 이미 롱
        )
        order = strategy.generate_order(breakout_state)

        # Then: 추가 BUY 없음
        assert order is None

    def test_close_long_on_downward_breakout(self):
        """롱 포지션 중 하단 돌파 → 청산 (SELL)"""
        from intraday.strategies.tick.vpin_breakout import VPINBreakoutStrategy

        strategy = VPINBreakoutStrategy(
            quantity=0.01,
            n_buckets=5,
            breakout_lookback=3,
            vpin_threshold=0.3,
        )

        # Given: lookback 기간 쌓기 (매도 압력 증가로 VPIN 상승)
        for i in range(3):
            state = make_market_state(
                close=100.0, high=101.0, low=99.0,
                buy_volume=4.0 - i,  # 매도 압력 증가
                sell_volume=6.0 + i,
            )
            strategy.generate_order(state)

        # When: 하단 돌파 + 높은 VPIN + 롱 포지션
        breakout_state = make_market_state(
            close=95.0, high=96.0, low=94.0,
            buy_volume=1.0, sell_volume=9.0,
            position_side=Side.BUY,  # 롱 보유 중
        )
        order = strategy.generate_order(breakout_state)

        # Then: SELL (청산)
        assert order is not None
        assert order.side == Side.SELL
