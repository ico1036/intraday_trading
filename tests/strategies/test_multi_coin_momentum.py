"""
포트폴리오 모멘텀 전략 테스트

TDD로 개발: 테스트 먼저 작성 → 구현 → 통과

전략 개요:
    - 여러 코인의 수익률(모멘텀)을 비교
    - 상대적으로 강한 코인 롱, 약한 코인 숏
    - 리밸런싱 주기마다 포지션 조정
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
import pandas as pd
import numpy as np

# 테스트 대상 (아직 구현 안됨)
from intraday.strategies.multi import PortfolioMomentum, CoinReturn


class TestCoinReturn:
    """개별 코인 수익률 계산 테스트"""
    
    def test_calculate_return_from_prices(self):
        """가격 시리즈에서 수익률 계산"""
        prices = pd.Series([100, 105, 103, 110])
        
        coin_return = CoinReturn.from_prices("BTCUSDT", prices)
        
        assert coin_return.symbol == "BTCUSDT"
        assert coin_return.total_return == pytest.approx(0.10, rel=0.01)  # 10%
    
    def test_calculate_return_handles_empty(self):
        """빈 데이터 처리"""
        prices = pd.Series([], dtype=float)
        
        coin_return = CoinReturn.from_prices("BTCUSDT", prices)
        
        assert coin_return.total_return == 0.0
    
    def test_compare_returns(self):
        """수익률 비교"""
        btc = CoinReturn("BTCUSDT", total_return=0.05)
        eth = CoinReturn("ETHUSDT", total_return=0.08)
        sol = CoinReturn("SOLUSDT", total_return=-0.02)
        
        ranked = sorted([btc, eth, sol], key=lambda x: x.total_return, reverse=True)
        
        assert ranked[0].symbol == "ETHUSDT"  # 가장 강함
        assert ranked[-1].symbol == "SOLUSDT"  # 가장 약함


class TestPortfolioMomentum:
    """포트폴리오 모멘텀 전략 테스트"""
    
    def test_strategy_init(self):
        """전략 초기화"""
        strategy = PortfolioMomentum(
            symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            lookback_minutes=60,
            top_n=1,
            bottom_n=1,
        )
        
        assert strategy.symbols == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        assert strategy.lookback_minutes == 60
        assert strategy.top_n == 1
        assert strategy.bottom_n == 1
    
    def test_calculate_rankings(self):
        """코인 순위 계산"""
        strategy = PortfolioMomentum(
            symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            lookback_minutes=60,
            top_n=1,
            bottom_n=1,
        )
        
        # Mock 가격 데이터: ETH 가장 강함, SOL 가장 약함
        price_data = {
            "BTCUSDT": pd.Series([100, 102, 104, 105]),  # +5%
            "ETHUSDT": pd.Series([100, 105, 108, 112]),  # +12%
            "SOLUSDT": pd.Series([100, 98, 96, 95]),     # -5%
        }
        
        rankings = strategy.calculate_rankings(price_data)
        
        assert rankings["long"] == ["ETHUSDT"]
        assert rankings["short"] == ["SOLUSDT"]
    
    def test_generate_signals(self):
        """시그널 생성"""
        strategy = PortfolioMomentum(
            symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            lookback_minutes=60,
            top_n=1,
            bottom_n=1,
        )
        
        # 현재 포지션: 없음
        current_positions = {}
        
        rankings = {"long": ["ETHUSDT"], "short": ["SOLUSDT"]}
        
        signals = strategy.generate_signals(rankings, current_positions)
        
        # ETH 롱, SOL 숏 시그널
        assert signals["ETHUSDT"] == "LONG"
        assert signals["SOLUSDT"] == "SHORT"
        assert "BTCUSDT" not in signals  # 중간은 무시
    
    def test_no_signal_when_already_positioned(self):
        """이미 포지션 있으면 시그널 없음"""
        strategy = PortfolioMomentum(
            symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            lookback_minutes=60,
            top_n=1,
            bottom_n=1,
        )
        
        current_positions = {"ETHUSDT": "LONG", "SOLUSDT": "SHORT"}
        rankings = {"long": ["ETHUSDT"], "short": ["SOLUSDT"]}
        
        signals = strategy.generate_signals(rankings, current_positions)
        
        assert signals == {}  # 이미 올바른 포지션
    
    def test_rebalance_signal(self):
        """리밸런싱 시그널 (순위 변경 시)"""
        strategy = PortfolioMomentum(
            symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            lookback_minutes=60,
            top_n=1,
            bottom_n=1,
        )
        
        # 기존: ETH 롱, SOL 숏
        # 신규: BTC가 1등, ETH가 꼴등
        current_positions = {"ETHUSDT": "LONG", "SOLUSDT": "SHORT"}
        new_rankings = {"long": ["BTCUSDT"], "short": ["ETHUSDT"]}
        
        signals = strategy.generate_signals(new_rankings, current_positions)
        
        # ETH 롱 청산 + 숏 진입, SOL 숏 청산, BTC 롱 진입
        assert "ETHUSDT" in signals
        assert "SOLUSDT" in signals
        assert "BTCUSDT" in signals
    
    def test_long_only_mode(self):
        """롱 온리 모드"""
        strategy = PortfolioMomentum(
            symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            lookback_minutes=60,
            top_n=1,
            bottom_n=0,  # 숏 없음
        )
        
        rankings = {"long": ["ETHUSDT"], "short": []}
        signals = strategy.generate_signals(rankings, {})
        
        assert signals == {"ETHUSDT": "LONG"}


class TestPortfolioMomentumIntegration:
    """통합 테스트 - 실제 데이터 흐름"""
    
    def test_full_cycle(self):
        """전체 사이클: 데이터 → 순위 → 시그널"""
        strategy = PortfolioMomentum(
            symbols=["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            lookback_minutes=60,
            top_n=1,
            bottom_n=1,
        )
        
        # 시뮬레이션된 가격 데이터
        price_data = {
            "BTCUSDT": pd.Series([100, 101, 102, 103, 104, 105]),
            "ETHUSDT": pd.Series([100, 103, 106, 109, 112, 115]),
            "SOLUSDT": pd.Series([100, 99, 98, 97, 96, 95]),
        }
        
        # 1. 순위 계산
        rankings = strategy.calculate_rankings(price_data)
        
        # 2. 시그널 생성
        signals = strategy.generate_signals(rankings, {})
        
        # 3. 검증
        assert signals["ETHUSDT"] == "LONG"
        assert signals["SOLUSDT"] == "SHORT"
    
    def test_with_bar_data(self):
        """캔들/바 데이터로 테스트"""
        strategy = PortfolioMomentum(
            symbols=["BTCUSDT", "ETHUSDT"],
            lookback_minutes=60,
            top_n=1,
            bottom_n=1,
        )
        
        # OHLCV 형태 데이터 (close 사용)
        btc_bars = pd.DataFrame({
            "open": [100, 102, 104],
            "high": [103, 105, 107],
            "low": [99, 101, 103],
            "close": [102, 104, 106],
            "volume": [1000, 1100, 1200],
        })
        
        eth_bars = pd.DataFrame({
            "open": [100, 105, 108],
            "high": [106, 110, 115],
            "low": [99, 104, 107],
            "close": [105, 108, 112],
            "volume": [2000, 2200, 2400],
        })
        
        price_data = {
            "BTCUSDT": btc_bars["close"],
            "ETHUSDT": eth_bars["close"],
        }
        
        rankings = strategy.calculate_rankings(price_data)
        
        # ETH가 더 강함 (6% vs 12%)
        assert rankings["long"] == ["ETHUSDT"]
        assert rankings["short"] == ["BTCUSDT"]
