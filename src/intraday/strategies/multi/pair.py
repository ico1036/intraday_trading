"""
Pair Trading 전략

상관관계 높은 두 코인 간의 스프레드가 평균으로 회귀하는 것을 이용한 전략.

전략 로직:
    1. 두 코인의 가격 비율(스프레드) 계산
    2. 스프레드의 Z-score 계산
    3. Z-score가 임계값 초과 시 진입
    4. Z-score가 중립 복귀 시 청산

사용 예시:
    strategy = PairTradingStrategy(
        coin_a="BTCUSDT",
        coin_b="ETHUSDT",
        zscore_entry=2.0,
        zscore_exit=0.5,
    )
"""

from typing import Optional

import numpy as np
import pandas as pd


class SpreadCalculator:
    """스프레드 계산 유틸리티"""
    
    @staticmethod
    def ratio_spread(price_a: pd.Series, price_b: pd.Series) -> pd.Series:
        """
        비율 스프레드 계산 (A / B)
        
        Args:
            price_a: 코인 A 가격 시리즈
            price_b: 코인 B 가격 시리즈
            
        Returns:
            스프레드 시리즈
        """
        return price_a / price_b
    
    @staticmethod
    def log_spread(price_a: pd.Series, price_b: pd.Series) -> pd.Series:
        """
        로그 스프레드 계산 (log(A) - log(B))
        
        더 안정적인 스프레드 계산
        """
        return np.log(price_a) - np.log(price_b)
    
    @staticmethod
    def zscore(spread: pd.Series, window: int = 20) -> pd.Series:
        """
        Z-score 계산
        
        Args:
            spread: 스프레드 시리즈
            window: 이동 평균/표준편차 윈도우
            
        Returns:
            Z-score 시리즈
        """
        mean = spread.rolling(window=window).mean()
        std = spread.rolling(window=window).std()
        
        return (spread - mean) / std


class PairTradingStrategy:
    """
    Pair Trading 전략
    
    Z-score 기반 평균 회귀 전략
    
    Attributes:
        coin_a: 첫 번째 코인 (분자)
        coin_b: 두 번째 코인 (분모)
        zscore_entry: 진입 임계값 (절대값)
        zscore_exit: 청산 임계값 (절대값)
        lookback: Z-score 계산 윈도우
    """
    
    def __init__(
        self,
        coin_a: str,
        coin_b: str,
        zscore_entry: float = 2.0,
        zscore_exit: float = 0.5,
        lookback: int = 60,
    ):
        """
        Args:
            coin_a: 첫 번째 코인
            coin_b: 두 번째 코인
            zscore_entry: 진입 Z-score 임계값
            zscore_exit: 청산 Z-score 임계값
            lookback: Z-score 계산 윈도우 (봉 수)
        """
        self.coin_a = coin_a
        self.coin_b = coin_b
        self.zscore_entry = abs(zscore_entry)
        self.zscore_exit = abs(zscore_exit)
        self.lookback = lookback
    
    @property
    def symbols(self) -> list[str]:
        """거래 심볼 목록"""
        return [self.coin_a, self.coin_b]
    
    def generate_signal(
        self,
        current_zscore: float,
        current_position: Optional[str],
    ) -> Optional[str]:
        """
        시그널 생성
        
        Args:
            current_zscore: 현재 Z-score
            current_position: 현재 포지션 (None, "LONG_SPREAD", "SHORT_SPREAD")
            
        Returns:
            시그널: None, "LONG_SPREAD", "SHORT_SPREAD", "EXIT", "HOLD"
            
            - LONG_SPREAD: A 롱 + B 숏 (스프레드가 낮을 때, 올라갈 것 기대)
            - SHORT_SPREAD: A 숏 + B 롱 (스프레드가 높을 때, 내려갈 것 기대)
            - EXIT: 포지션 청산
            - HOLD: 유지
        """
        # 포지션 없을 때: 진입 조건 확인
        if current_position is None:
            if current_zscore < -self.zscore_entry:
                # 스프레드가 평균보다 많이 낮음 → 롱 스프레드
                return "LONG_SPREAD"
            elif current_zscore > self.zscore_entry:
                # 스프레드가 평균보다 많이 높음 → 숏 스프레드
                return "SHORT_SPREAD"
            return None
        
        # 포지션 있을 때: 청산 조건 확인
        if current_position == "LONG_SPREAD":
            # 롱 스프레드: Z-score가 0 근처로 복귀하면 청산
            if current_zscore >= -self.zscore_exit:
                return "EXIT"
            return "HOLD"
        
        elif current_position == "SHORT_SPREAD":
            # 숏 스프레드: Z-score가 0 근처로 복귀하면 청산
            if current_zscore <= self.zscore_exit:
                return "EXIT"
            return "HOLD"
        
        return None
    
    def calculate_spread_zscore(
        self,
        price_a: pd.Series,
        price_b: pd.Series,
    ) -> pd.Series:
        """
        스프레드와 Z-score 계산
        
        Args:
            price_a: 코인 A 가격 시리즈
            price_b: 코인 B 가격 시리즈
            
        Returns:
            Z-score 시리즈
        """
        spread = SpreadCalculator.ratio_spread(price_a, price_b)
        zscore = SpreadCalculator.zscore(spread, window=self.lookback)
        return zscore
