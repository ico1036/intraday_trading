"""
UI 성과 요약 팝업 테스트

Stop 버튼 클릭 시 표시되는 성과 리포트의 정확성을 검증합니다.
"""

import pytest
from datetime import datetime, timedelta

from intraday.performance import PerformanceReport, PerformanceCalculator
from intraday.paper_trader import PaperTrader, Trade, Side


class TestPerformanceReportAttributes:
    """PerformanceReport가 UI에서 필요로 하는 모든 속성을 가지고 있는지 검증"""
    
    def test_report_has_required_attributes_for_ui(self):
        """UI 표시에 필요한 모든 속성이 존재해야 한다"""
        report = PerformanceReport(
            strategy_name="TestStrategy",
            symbol="BTCUSDT",
            start_time=datetime.now(),
            end_time=datetime.now(),
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
        
        # UI에서 사용하는 속성들 검증
        assert hasattr(report, 'total_return'), "total_return 속성이 필요합니다"
        assert hasattr(report, 'win_rate'), "win_rate 속성이 필요합니다"
        assert hasattr(report, 'winning_trades'), "winning_trades 속성이 필요합니다"
        assert hasattr(report, 'losing_trades'), "losing_trades 속성이 필요합니다"
        assert hasattr(report, 'total_trades'), "total_trades 속성이 필요합니다"
        assert hasattr(report, 'initial_capital'), "initial_capital 속성이 필요합니다"
        assert hasattr(report, 'final_capital'), "final_capital 속성이 필요합니다"
    
    def test_realized_pnl_can_be_calculated(self):
        """실현 PnL은 final_capital - initial_capital로 계산 가능해야 한다"""
        initial = 10000.0
        final = 10500.0
        
        report = PerformanceReport(
            strategy_name="TestStrategy",
            symbol="BTCUSDT",
            start_time=datetime.now(),
            end_time=datetime.now(),
            initial_capital=initial,
            final_capital=final,
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
        
        # realized_pnl 계산
        realized_pnl = report.final_capital - report.initial_capital
        
        assert realized_pnl == 500.0, "PnL은 final - initial 이어야 한다"
    
    def test_report_values_are_correct_types(self):
        """모든 값이 올바른 타입이어야 한다"""
        report = PerformanceReport(
            strategy_name="TestStrategy",
            symbol="BTCUSDT",
            start_time=datetime.now(),
            end_time=datetime.now(),
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
        
        assert isinstance(report.total_return, float)
        assert isinstance(report.win_rate, float)
        assert isinstance(report.total_trades, int)
        assert isinstance(report.winning_trades, int)
        assert isinstance(report.losing_trades, int)


class TestPerformanceReportCalculation:
    """PerformanceCalculator가 올바른 리포트를 생성하는지 검증"""
    
    def test_calculator_with_winning_trades(self):
        """수익이 난 거래들로 리포트 생성"""
        trades = [
            Trade(
                timestamp=datetime.now(),
                side=Side.BUY,
                price=100.0,
                quantity=1.0,
                fee=0.1,
                pnl=0.0,  # 진입
            ),
            Trade(
                timestamp=datetime.now(),
                side=Side.SELL,
                price=110.0,
                quantity=1.0,
                fee=0.1,
                pnl=9.8,  # 10 - 0.2 수수료
            ),
        ]
        
        # PerformanceCalculator.calculate는 정적 메서드
        report = PerformanceCalculator.calculate(
            trades=trades,
            initial_capital=1000.0,
            strategy_name="WinTest",
            symbol="TEST",
            start_time=datetime.now() - timedelta(hours=1),
            end_time=datetime.now(),
        )
        
        assert report.total_trades == 2
        assert report.winning_trades >= 1
        assert report.final_capital > report.initial_capital
        
        # realized_pnl은 final - initial로 계산
        realized_pnl = report.final_capital - report.initial_capital
        assert realized_pnl > 0, "수익이 나야 한다"
    
    def test_calculator_with_no_trades(self):
        """거래가 없을 때도 리포트 생성 가능"""
        report = PerformanceCalculator.calculate(
            trades=[],
            initial_capital=1000.0,
            strategy_name="NoTradeTest",
            symbol="TEST",
            start_time=datetime.now() - timedelta(hours=1),
            end_time=datetime.now(),
        )
        
        assert report.total_trades == 0
        assert report.winning_trades == 0
        assert report.losing_trades == 0
        assert report.win_rate == 0.0
        assert report.final_capital == report.initial_capital


class TestUIPerformanceSummaryDisplay:
    """UI에서 성과 요약을 올바르게 표시할 수 있는지 검증"""
    
    def test_pnl_display_format(self):
        """PnL 표시 형식 검증"""
        initial = 10000.0
        final = 10500.0
        
        # UI에서 사용할 PnL 계산
        pnl = final - initial
        
        # 양수일 때 +500.00 형식
        display = f"${pnl:+,.2f}"
        assert display == "$+500.00"
        
        # 음수일 때
        pnl_loss = 9500.0 - 10000.0
        display_loss = f"${pnl_loss:+,.2f}"
        assert display_loss == "$-500.00"
    
    def test_win_rate_display_format(self):
        """승률 표시 형식 검증"""
        win_rate = 66.6666667
        display = f"{win_rate:.1f}%"
        assert display == "66.7%"
    
    def test_total_return_display_format(self):
        """수익률 표시 형식 검증"""
        total_return = 5.5
        display = f"{total_return:+.2f}%"
        assert display == "+5.50%"
        
        total_return_loss = -3.2
        display_loss = f"{total_return_loss:+.2f}%"
        assert display_loss == "-3.20%"

