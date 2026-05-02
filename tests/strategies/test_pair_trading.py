"""
Pair Trading 전략 테스트

TDD: 상관관계 높은 코인 간 스프레드 트레이딩
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime

from intraday.strategies.multi.pair import PairTradingStrategy, SpreadCalculator


class TestSpreadCalculator:
    """스프레드 계산 테스트"""
    
    def test_calculate_ratio_spread(self):
        """비율 스프레드 계산"""
        btc = pd.Series([50000, 51000, 52000, 51500])
        eth = pd.Series([3000, 3100, 3150, 3050])
        
        spread = SpreadCalculator.ratio_spread(btc, eth)
        
        assert len(spread) == 4
        assert spread.iloc[0] == pytest.approx(50000 / 3000, rel=0.01)
    
    def test_calculate_zscore(self):
        """Z-score 계산"""
        spread = pd.Series([16.5, 16.8, 16.3, 16.9, 16.4, 17.0, 16.2])
        
        zscore = SpreadCalculator.zscore(spread, window=5)
        
        # 첫 4개는 NaN (윈도우 부족)
        assert pd.isna(zscore.iloc[3])
        assert not pd.isna(zscore.iloc[4])
    
    def test_zscore_normalized(self):
        """Z-score가 정규화되었는지"""
        np.random.seed(42)
        spread = pd.Series(np.random.randn(100) + 16.5)
        
        zscore = SpreadCalculator.zscore(spread, window=20)
        valid_zscore = zscore.dropna()
        
        # 대부분 -3 ~ 3 사이
        assert (abs(valid_zscore) < 3).mean() > 0.95


class TestPairTradingStrategy:
    """Pair Trading 전략 테스트"""
    
    def test_init(self):
        """초기화"""
        strategy = PairTradingStrategy(
            coin_a="BTCUSDT",
            coin_b="ETHUSDT",
            zscore_entry=2.0,
            zscore_exit=0.5,
            lookback=60,
        )
        
        assert strategy.coin_a == "BTCUSDT"
        assert strategy.coin_b == "ETHUSDT"
        assert strategy.zscore_entry == 2.0
    
    def test_no_signal_in_normal_range(self):
        """정상 범위에서는 시그널 없음"""
        strategy = PairTradingStrategy(
            coin_a="BTCUSDT",
            coin_b="ETHUSDT",
            zscore_entry=2.0,
            zscore_exit=0.5,
            lookback=20,
        )
        
        # Z-score가 정상 범위
        current_zscore = 0.5
        current_position = None
        
        signal = strategy.generate_signal(current_zscore, current_position)
        
        assert signal is None
    
    def test_long_spread_signal(self):
        """스프레드 롱 시그널 (Z-score < -entry)"""
        strategy = PairTradingStrategy(
            coin_a="BTCUSDT",
            coin_b="ETHUSDT",
            zscore_entry=2.0,
            zscore_exit=0.5,
            lookback=20,
        )
        
        # Z-score가 -2 이하 (스프레드가 평균보다 낮음)
        # → A 롱, B 숏 (스프레드가 평균으로 회귀할 것 기대)
        current_zscore = -2.5
        current_position = None
        
        signal = strategy.generate_signal(current_zscore, current_position)
        
        assert signal == "LONG_SPREAD"  # A롱, B숏
    
    def test_short_spread_signal(self):
        """스프레드 숏 시그널 (Z-score > entry)"""
        strategy = PairTradingStrategy(
            coin_a="BTCUSDT",
            coin_b="ETHUSDT",
            zscore_entry=2.0,
            zscore_exit=0.5,
            lookback=20,
        )
        
        current_zscore = 2.5
        current_position = None
        
        signal = strategy.generate_signal(current_zscore, current_position)
        
        assert signal == "SHORT_SPREAD"  # A숏, B롱
    
    def test_exit_signal(self):
        """청산 시그널 (Z-score 중립 복귀)"""
        strategy = PairTradingStrategy(
            coin_a="BTCUSDT",
            coin_b="ETHUSDT",
            zscore_entry=2.0,
            zscore_exit=0.5,
            lookback=20,
        )
        
        current_zscore = 0.3  # 중립 근처
        current_position = "LONG_SPREAD"
        
        signal = strategy.generate_signal(current_zscore, current_position)
        
        assert signal == "EXIT"
    
    def test_hold_signal(self):
        """포지션 유지 (아직 exit 조건 안됨)"""
        strategy = PairTradingStrategy(
            coin_a="BTCUSDT",
            coin_b="ETHUSDT",
            zscore_entry=2.0,
            zscore_exit=0.5,
            lookback=20,
        )
        
        current_zscore = -1.0  # entry < |zscore| < 아직 음수
        current_position = "LONG_SPREAD"
        
        signal = strategy.generate_signal(current_zscore, current_position)
        
        assert signal == "HOLD"


class TestPairTradingIntegration:
    """통합 테스트"""
    
    def test_full_cycle(self):
        """전체 사이클"""
        strategy = PairTradingStrategy(
            coin_a="BTCUSDT",
            coin_b="ETHUSDT",
            zscore_entry=2.0,
            zscore_exit=0.5,
            lookback=20,
        )
        
        # 가격 데이터 시뮬레이션
        np.random.seed(42)
        n = 100
        btc = pd.Series(50000 + np.cumsum(np.random.randn(n) * 100))
        eth = pd.Series(3000 + np.cumsum(np.random.randn(n) * 50))
        
        # 스프레드 계산
        spread = SpreadCalculator.ratio_spread(btc, eth)
        zscore = SpreadCalculator.zscore(spread, window=20)
        
        # 시그널 생성
        position = None
        signals = []
        
        for i in range(len(zscore)):
            if pd.isna(zscore.iloc[i]):
                signals.append(None)
                continue
            
            signal = strategy.generate_signal(zscore.iloc[i], position)
            signals.append(signal)
            
            if signal == "LONG_SPREAD":
                position = "LONG_SPREAD"
            elif signal == "SHORT_SPREAD":
                position = "SHORT_SPREAD"
            elif signal == "EXIT":
                position = None
        
        # 시그널이 생성되었는지 확인
        non_none = [s for s in signals if s is not None]
        assert len(non_none) > 0
