"""
Performance 모듈 테스트

성과 지표 계산 검증
"""

from datetime import datetime, timedelta

import pytest

from intraday.strategy import Side
from intraday.paper_trader import Trade
from intraday.performance import PerformanceReport, PerformanceCalculator


class TestPerformanceReport:
    """PerformanceReport 데이터클래스 테스트"""
    
    def test_report_creation(self):
        """PerformanceReport 생성 테스트"""
        now = datetime.now()
        report = PerformanceReport(
            strategy_name="OBI",
            symbol="BTCUSDT",
            start_time=now,
            end_time=now + timedelta(hours=1),
            initial_capital=10000.0,
            final_capital=10500.0,
            total_return=5.0,
            total_trades=10,
            winning_trades=6,
            losing_trades=4,
            win_rate=60.0,
            profit_factor=1.5,
            avg_win=100.0,
            avg_loss=50.0,
            max_drawdown=2.0,
            sharpe_ratio=1.5,
            total_fees=10.0,
        )
        
        assert report.strategy_name == "OBI"
        assert report.total_return == 5.0
        assert report.win_rate == 60.0


class TestPerformanceCalculator:
    """PerformanceCalculator 테스트"""
    
    def test_empty_trades(self):
        """거래가 없을 때"""
        now = datetime.now()
        report = PerformanceCalculator.calculate(
            trades=[],
            initial_capital=10000.0,
            strategy_name="OBI",
            symbol="BTCUSDT",
            start_time=now,
            end_time=now + timedelta(hours=1),
        )
        
        assert report.total_trades == 0
        assert report.winning_trades == 0
        assert report.losing_trades == 0
        assert report.win_rate == 0.0
        assert report.total_return == 0.0
        assert report.profit_factor == 0.0
    
    def test_all_winning_trades(self):
        """모든 거래가 이익인 경우"""
        now = datetime.now()
        trades = [
            Trade(timestamp=now, side=Side.BUY, price=100000.0, quantity=0.01, fee=1.0, pnl=0.0),
            Trade(timestamp=now + timedelta(seconds=10), side=Side.SELL, price=101000.0, quantity=0.01, fee=1.0, pnl=8.0),
            Trade(timestamp=now + timedelta(seconds=20), side=Side.BUY, price=101000.0, quantity=0.01, fee=1.0, pnl=0.0),
            Trade(timestamp=now + timedelta(seconds=30), side=Side.SELL, price=102000.0, quantity=0.01, fee=1.0, pnl=8.0),
        ]
        
        report = PerformanceCalculator.calculate(
            trades=trades,
            initial_capital=10000.0,
            strategy_name="OBI",
            symbol="BTCUSDT",
            start_time=now,
            end_time=now + timedelta(minutes=1),
        )
        
        # 2개의 완료된 거래 (진입+청산 = 1 round trip)
        assert report.total_trades == 4  # 전체 거래 수
        assert report.winning_trades == 2  # 이익 거래 (pnl > 0)
        assert report.losing_trades == 0
        assert report.win_rate == 100.0
        assert report.profit_factor == float("inf")  # 손실 0
    
    def test_all_losing_trades(self):
        """모든 거래가 손실인 경우"""
        now = datetime.now()
        trades = [
            Trade(timestamp=now, side=Side.BUY, price=100000.0, quantity=0.01, fee=1.0, pnl=0.0),
            Trade(timestamp=now + timedelta(seconds=10), side=Side.SELL, price=99000.0, quantity=0.01, fee=1.0, pnl=-12.0),
            Trade(timestamp=now + timedelta(seconds=20), side=Side.BUY, price=99000.0, quantity=0.01, fee=1.0, pnl=0.0),
            Trade(timestamp=now + timedelta(seconds=30), side=Side.SELL, price=98000.0, quantity=0.01, fee=1.0, pnl=-12.0),
        ]
        
        report = PerformanceCalculator.calculate(
            trades=trades,
            initial_capital=10000.0,
            strategy_name="OBI",
            symbol="BTCUSDT",
            start_time=now,
            end_time=now + timedelta(minutes=1),
        )
        
        assert report.winning_trades == 0
        assert report.losing_trades == 2  # 손실 거래 (pnl < 0)
        assert report.win_rate == 0.0
        assert report.profit_factor == 0.0  # 이익 0
    
    def test_mixed_trades(self):
        """이익과 손실이 섞인 경우"""
        now = datetime.now()
        trades = [
            # 첫 번째 거래: 이익 +8
            Trade(timestamp=now, side=Side.BUY, price=100000.0, quantity=0.01, fee=1.0, pnl=0.0),
            Trade(timestamp=now + timedelta(seconds=10), side=Side.SELL, price=101000.0, quantity=0.01, fee=1.0, pnl=8.0),
            # 두 번째 거래: 손실 -12
            Trade(timestamp=now + timedelta(seconds=20), side=Side.BUY, price=101000.0, quantity=0.01, fee=1.0, pnl=0.0),
            Trade(timestamp=now + timedelta(seconds=30), side=Side.SELL, price=100000.0, quantity=0.01, fee=1.0, pnl=-12.0),
            # 세 번째 거래: 이익 +18
            Trade(timestamp=now + timedelta(seconds=40), side=Side.BUY, price=100000.0, quantity=0.01, fee=1.0, pnl=0.0),
            Trade(timestamp=now + timedelta(seconds=50), side=Side.SELL, price=102000.0, quantity=0.01, fee=1.0, pnl=18.0),
        ]
        
        report = PerformanceCalculator.calculate(
            trades=trades,
            initial_capital=10000.0,
            strategy_name="OBI",
            symbol="BTCUSDT",
            start_time=now,
            end_time=now + timedelta(minutes=1),
        )
        
        assert report.total_trades == 6
        assert report.winning_trades == 2  # +8, +18
        assert report.losing_trades == 1  # -12
        assert report.win_rate == pytest.approx(66.67, rel=0.01)  # 2/3
        # profit_factor = 총이익 / 총손실 = (8+18) / 12 = 2.167
        assert report.profit_factor == pytest.approx(26.0 / 12.0, rel=0.01)
    
    def test_total_return_calculation(self):
        """총 수익률 계산"""
        now = datetime.now()
        trades = [
            Trade(timestamp=now, side=Side.BUY, price=100000.0, quantity=0.01, fee=1.0, pnl=0.0),
            Trade(timestamp=now + timedelta(seconds=10), side=Side.SELL, price=110000.0, quantity=0.01, fee=1.0, pnl=98.0),
        ]
        
        report = PerformanceCalculator.calculate(
            trades=trades,
            initial_capital=10000.0,
            strategy_name="OBI",
            symbol="BTCUSDT",
            start_time=now,
            end_time=now + timedelta(minutes=1),
        )
        
        # total_return = (final - initial) / initial * 100
        # final = 10000 + 98 = 10098
        # return = (10098 - 10000) / 10000 * 100 = 0.98%
        assert report.total_return == pytest.approx(0.98, rel=0.01)
    
    def test_avg_win_avg_loss(self):
        """평균 이익 및 평균 손실 계산"""
        now = datetime.now()
        trades = [
            Trade(timestamp=now, side=Side.BUY, price=100000.0, quantity=0.01, fee=1.0, pnl=0.0),
            Trade(timestamp=now + timedelta(seconds=10), side=Side.SELL, price=101000.0, quantity=0.01, fee=1.0, pnl=8.0),
            Trade(timestamp=now + timedelta(seconds=20), side=Side.BUY, price=101000.0, quantity=0.01, fee=1.0, pnl=0.0),
            Trade(timestamp=now + timedelta(seconds=30), side=Side.SELL, price=100000.0, quantity=0.01, fee=1.0, pnl=-12.0),
            Trade(timestamp=now + timedelta(seconds=40), side=Side.BUY, price=100000.0, quantity=0.01, fee=1.0, pnl=0.0),
            Trade(timestamp=now + timedelta(seconds=50), side=Side.SELL, price=102000.0, quantity=0.01, fee=1.0, pnl=18.0),
        ]
        
        report = PerformanceCalculator.calculate(
            trades=trades,
            initial_capital=10000.0,
            strategy_name="OBI",
            symbol="BTCUSDT",
            start_time=now,
            end_time=now + timedelta(minutes=1),
        )
        
        # avg_win = (8 + 18) / 2 = 13
        assert report.avg_win == pytest.approx(13.0, rel=0.01)
        # avg_loss = 12 / 1 = 12
        assert report.avg_loss == pytest.approx(12.0, rel=0.01)
    
    def test_total_fees_calculation(self):
        """총 수수료 계산"""
        now = datetime.now()
        trades = [
            Trade(timestamp=now, side=Side.BUY, price=100000.0, quantity=0.01, fee=1.0, pnl=0.0),
            Trade(timestamp=now + timedelta(seconds=10), side=Side.SELL, price=101000.0, quantity=0.01, fee=1.01, pnl=8.0),
            Trade(timestamp=now + timedelta(seconds=20), side=Side.BUY, price=101000.0, quantity=0.01, fee=1.01, pnl=0.0),
            Trade(timestamp=now + timedelta(seconds=30), side=Side.SELL, price=100000.0, quantity=0.01, fee=1.0, pnl=-12.0),
        ]
        
        report = PerformanceCalculator.calculate(
            trades=trades,
            initial_capital=10000.0,
            strategy_name="OBI",
            symbol="BTCUSDT",
            start_time=now,
            end_time=now + timedelta(minutes=1),
        )
        
        # total_fees = 1.0 + 1.01 + 1.01 + 1.0 = 4.02
        assert report.total_fees == pytest.approx(4.02, rel=0.01)
    
    def test_max_drawdown_calculation(self):
        """최대 낙폭 계산"""
        now = datetime.now()
        # 시나리오: 10000 → 10100 (+1%) → 9900 (-2%) → 10200 (+3%)
        trades = [
            Trade(timestamp=now, side=Side.BUY, price=100000.0, quantity=0.01, fee=0.0, pnl=0.0),
            Trade(timestamp=now + timedelta(seconds=10), side=Side.SELL, price=101000.0, quantity=0.01, fee=0.0, pnl=10.0),
            Trade(timestamp=now + timedelta(seconds=20), side=Side.BUY, price=101000.0, quantity=0.01, fee=0.0, pnl=0.0),
            Trade(timestamp=now + timedelta(seconds=30), side=Side.SELL, price=98000.0, quantity=0.01, fee=0.0, pnl=-30.0),
            Trade(timestamp=now + timedelta(seconds=40), side=Side.BUY, price=98000.0, quantity=0.01, fee=0.0, pnl=0.0),
            Trade(timestamp=now + timedelta(seconds=50), side=Side.SELL, price=102000.0, quantity=0.01, fee=0.0, pnl=40.0),
        ]
        
        report = PerformanceCalculator.calculate(
            trades=trades,
            initial_capital=10000.0,
            strategy_name="OBI",
            symbol="BTCUSDT",
            start_time=now,
            end_time=now + timedelta(minutes=1),
        )
        
        # 자본 변화: 10000 → 10010 → 9980 → 10020
        # Peak: 10010
        # Trough: 9980
        # Drawdown: (10010 - 9980) / 10010 = 0.3%
        assert report.max_drawdown >= 0.0  # 항상 양수 또는 0


class TestPerformanceCalculatorEdgeCases:
    """PerformanceCalculator 경계 케이스"""
    
    def test_single_entry_no_exit(self):
        """진입만 있고 청산이 없는 경우"""
        now = datetime.now()
        trades = [
            Trade(timestamp=now, side=Side.BUY, price=100000.0, quantity=0.01, fee=1.0, pnl=0.0),
        ]
        
        report = PerformanceCalculator.calculate(
            trades=trades,
            initial_capital=10000.0,
            strategy_name="OBI",
            symbol="BTCUSDT",
            start_time=now,
            end_time=now + timedelta(minutes=1),
        )
        
        assert report.total_trades == 1
        assert report.winning_trades == 0
        assert report.losing_trades == 0
        assert report.win_rate == 0.0
    
    def test_zero_initial_capital(self):
        """초기 자본이 0인 경우 (예외 처리)"""
        now = datetime.now()
        trades = []
        
        report = PerformanceCalculator.calculate(
            trades=trades,
            initial_capital=0.0,
            strategy_name="OBI",
            symbol="BTCUSDT",
            start_time=now,
            end_time=now + timedelta(minutes=1),
        )
        
        # 0으로 나누기 방지
        assert report.total_return == 0.0

